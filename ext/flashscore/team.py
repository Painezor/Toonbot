"""Working with teams retrieved from flashscore"""
from __future__ import annotations

import dataclasses
import datetime
import typing

import asyncpg
from lxml import html
from playwright.async_api import Page

from ext.utils import timed_events

from .abc import FlashScoreItem
from .competitions import Competition
from .constants import FLASHSCORE, INBOUND_EMOJI, OUTBOUND_EMOJI, TEAM_EMOJI
from .players import Player
from .search import save_team

if typing.TYPE_CHECKING:
    from core import Bot

TFOpts = typing.Literal["All", "Arrivals", "Departures"]


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""

    __slots__ = {
        "competition": "The competition the team belongs to",
        "logo_url": "A link to a logo representing the competition",
        "gender": "The Gender that this team is comprised of",
    }

    # Constant
    emoji = TEAM_EMOJI

    def __init__(
        self, fs_id: typing.Optional[str], name: str, url: typing.Optional[str]
    ) -> None:
        # Example URL:
        # https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        # https://www.flashscore.com/?r=3:jLsL0hAF

        if fs_id is None and url:
            fs_id = url.split("/")[-1]
        elif url and fs_id and FLASHSCORE not in url:
            url = f"{FLASHSCORE}/team/{url}/{fs_id}"
        elif fs_id and not url:
            url = f"https://www.flashscore.com/?r=3:{id}"

        super().__init__(fs_id, name, url)

        self.gender: typing.Optional[str] = None
        self.competition: typing.Optional[Competition] = None

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Team:
        """Retrieve a Team object from an asyncpg Record"""
        team = Team(record["id"], record["name"], record["url"])
        team.logo_url = record["logo_url"]
        return team

    @classmethod
    async def from_fixture_html(
        cls, bot: Bot, tree, home: bool = True
    ) -> Team:
        """Parse a team from the HTML of a flashscore FIxture"""
        attr = "home" if home else "away"

        xpath = f".//div[contains(@class, 'duelParticipant__{attr}')]"
        div = tree.xpath(xpath)
        if not div:
            raise LookupError("Cannot find team on page.")

        div = div[0]  # Only One

        # Get Name
        xpath = ".//a[contains(@class, 'participant__participantName')]/"
        name = "".join(div.xpath(xpath + "text()"))
        url = "".join(div.xpath(xpath + "@href"))

        team_id = url.split("/")[-2]

        if (team := bot.get_team(team_id)) is not None:
            if team.name != name:
                team.name = name
        else:
            for i in bot.teams:
                if i.url and url in i.url:
                    team = i
                    break
            else:
                team = Team(team_id, name, FLASHSCORE + url)

        if team.logo_url is None:
            logo = div.xpath('.//img[@class="participant__image"]/@src')
            logo = "".join(logo)
            if logo:
                team.logo_url = FLASHSCORE + logo

        if team not in bot.teams:
            await save_team(bot, team)

        return team

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        if len(self.name.split()) == 1:
            return "".join(self.name[:3]).upper()
        return "".join([i for i in self.name if i.isupper()])

    async def get_squad(
        self, page: Page, btn_name: typing.Optional[str] = None
    ) -> list[SquadMember]:
        """Get all squad members for a tournament"""
        url = f"{self.url}/squad"

        if page.url != url:
            await page.goto(url, timeout=300)

        loc = page.locator(".lineup")
        await loc.wait_for(timeout=300)

        if btn_name is not None:
            btn = page.locator(btn_name)
            await btn.wait_for(timeout=300)
            await btn.click(force=True)

        # to_click refers to a button press.
        tree = html.fromstring(await loc.inner_html())

        def parse_row(row, position: str) -> SquadMember:
            xpath = './/div[contains(@class, "cell--name")]/a/@href'
            link = FLASHSCORE + "".join(row.xpath(xpath))

            xpath = './/div[contains(@class, "cell--name")]/a/text()'
            name = "".join(row.xpath(xpath)).strip()
            try:  # Name comes in reverse order.
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            player = Player(forename, surname, link)
            xpath = './/div[contains(@class,"flag")]/@title'
            player.country = [str(x.strip()) for x in row.xpath(xpath) if x]
            xpath = './/div[contains(@class,"cell--age")]/text()'
            if age := "".join(row.xpath(xpath)).strip():
                player.age = int(age)

            member = SquadMember(player=player, position=position)
            xpath = './/div[contains(@class,"jersey")]/text()'
            member.squad_number = int("".join(row.xpath(xpath)) or 0)

            xpath = './/div[contains(@class,"cell--goal")]/text()'
            if goals := "".join(row.xpath(xpath)).strip():
                member.goals = int(goals)

            xpath = './/div[contains(@class,"matchesPlayed")]/text()'
            if appearances := "".join(row.xpath(xpath)).strip():
                member.appearances = int(appearances)

            xpath = './/div[contains(@class,"yellowCard")]/text()'
            if yellows := "".join(row.xpath(xpath)).strip():
                member.yellows = int(yellows)

            xpath = './/div[contains(@class,"redCard")]/text()'
            if reds := "".join(row.xpath(xpath)).strip():
                member.reds = int(reds)

            xpath = './/div[contains(@title,"Injury")]/@title'
            member.injury = "".join(row.xpath(xpath)).strip()
            return member

        # Grab All Players.
        members: list[SquadMember] = []
        for i in tree.xpath('.//div[@class="lineup__rows"]'):
            # A header row with the player's position.
            xpath = "./div[@class='lineup__title']/text()"
            position = "".join(i.xpath(xpath)).strip()
            pl_rows = i.xpath('.//div[@class="lineup__row"]')
            members += [parse_row(i, position) for i in pl_rows]
        return members

    async def get_transfers(
        self, page: Page, type_: TFOpts, cache: list[Team]
    ) -> list[FSTransfer]:
        """Get a list of transfers for the team retrieved from flashscore"""
        if page.url != (url := f"{self.url}/transfers/"):
            await page.goto(url, timeout=500)
            await page.wait_for_selector("section#transfers", timeout=500)

        filters = page.locator("button.filter__filter")

        for i in range(await filters.count()):
            if i == {"All": 0, "Arrivals": 1, "Departures": 2}[type_]:
                await filters.nth(i).click(force=True)

            show_more = page.locator("Show more")
            for _ in range(20):
                if await show_more.count():
                    await show_more.click()

        tree = html.fromstring(await page.inner_html(".transferTab"))

        output: list[FSTransfer] = []
        for i in tree.xpath('.//div[@class="transferTab__row"]'):
            xpath = './/div[contains(@class, "team--from")]/div/a'
            name = "".join(i.xpath(xpath + "/text()"))
            link = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))

            try:
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            trans = FSTransfer()
            player = Player(forename, surname, link)
            player.country = i.xpath('.//span[@class="flag"]/@title')
            trans.player = player

            xpath = './/div[@class="transferTab__season"]/text()'
            _ = "".join(i.xpath(xpath))
            trans.date = datetime.datetime.strptime(_, "%d.%m.%Y")

            _ = "".join(i.xpath(".//svg[1]/@class"))
            trans.direction = "in" if "icon--in" in _ else "out"

            _ = i.xpath('.//div[@class="transferTab__text"]/text()')
            trans.type = "".join(_)

            xpath = './/div[contains(@class, "team--to")]/div/a'
            if team_name := "".join(i.xpath(xpath + "/text()")):
                tm_lnk = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))

                team_id = tm_lnk.split("/")[-2]

                try:
                    team = next(i for i in cache if i.id == team_id)
                except StopIteration:
                    team = Team(team_id, team_name, tm_lnk)

                trans.team = team
            output.append(trans)
        return output


@dataclasses.dataclass(slots=True)
class SquadMember:
    """A Player that is a member of a team"""

    player: Player
    position: str

    squad_number: int
    position: str
    appearances: int
    goals: int
    assists: int
    yellows: int
    reds: int
    injury: str
    rank: typing.Optional[int] = None

    def __init__(self, **kwargs) -> None:
        for k, val in kwargs.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class FSTransfer:
    """A Transfer Retrieved from Flashscore"""

    date: datetime.datetime
    direction: str
    player: Player
    type: str

    team: typing.Optional[Team] = None  #

    def __init__(self) -> None:
        pass

    @property
    def emoji(self) -> str:
        """Return emoji depending on whether transfer is inbound or outbound"""
        return INBOUND_EMOJI if self.direction == "in" else OUTBOUND_EMOJI

    @property
    def output(self) -> str:
        """Player Markdown, Emoji, Team Markdown, Date, Type of transfer"""
        pmd = self.player.markdown
        tmd = self.team.markdown if self.team else "Free Agent"
        date = timed_events.Timestamp(self.date).date
        return f"{pmd} {self.emoji} {tmd}\n{date} {self.type}\n"
