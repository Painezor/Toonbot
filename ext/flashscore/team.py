"""Working with teams retrieved from flashscore"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal

from lxml import html
from pydantic import BaseModel


from ext.utils import timed_events

from .constants import (
    FLASHSCORE,
    GOAL_EMOJI,
    INBOUND_EMOJI,
    INJURY_EMOJI,
    OUTBOUND_EMOJI,
    RED_CARD_EMOJI,
    TEAM_EMOJI,
    YELLOW_CARD_EMOJI,
)
from .fixture import HasFixtures
from .logos import HasLogo
from .news import HasNews
from .table import HasTable
from .topscorers import HasScorers

if TYPE_CHECKING:
    from playwright.async_api import Page

    from .cache import FlashscoreCache
    from .competitions import Competition
    from .players import FSPlayer


TFOpts = Literal["All", "Arrivals", "Departures"]


class Team(BaseModel, HasFixtures, HasTable, HasNews, HasScorers, HasLogo):
    """An object representing a Team from Flashscore"""

    name: str | None = None
    id: str | None = None  # pylint: disable=C0103
    url: str | None = None

    logo_url: str | None = None

    competition: Competition | None = None
    gender: str | None = None
    logo_url: str | None = None

    emoji = TEAM_EMOJI

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    @property
    def ac_row(self) -> str:
        """Autocomplete"""
        txt = f"{self.emoji} {self.title}"
        if self.competition is not None:
            txt += f" ({self.competition.name})"
        return f"{self.emoji} {txt}"

    @property
    def markdown(self) -> str:
        return f"[{self.name}]({self.url})"

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        if self.name is None:
            return "???"

        if len(self.name.split()) == 1:
            return "".join(self.name[:3]).upper()
        return "".join([i for i in self.name if i.isupper()])

    @property
    def title(self) -> str:
        return f"{TEAM_EMOJI} {self.name}"

    async def get_squad(
        self, page: Page, btn_name: str | None = None
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
        self, page: Page, label: TFOpts, cache: FlashscoreCache
    ) -> list[FSTransfer]:
        """Get a list of transfers for the team retrieved from flashscore"""
        from .players import FSPlayer  # pylint disable=C0415

        if page.url != (url := f"{self.url}/transfers/"):
            await page.goto(url, timeout=500)
            await page.wait_for_selector("section#transfers", timeout=500)

        filters = page.locator("button.filter__filter", has_text=label).first
        await filters.click(force=True)

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

            plr = FSPlayer(forename=forename, surname=surname, url=link)
            plr.country = i.xpath('.//span[@class="flag"]/@title')

            xpath = './/div[@class="transferTab__season"]/text()'
            _ = "".join(i.xpath(xpath))
            date = datetime.datetime.strptime(_, "%d.%m.%Y")

            _ = "".join(i.xpath(".//svg[1]/@class"))
            out = "in" if "icon--in" in _ else "out"

            _ = i.xpath('.//div[@class="transferTab__text"]/text()')
            type = "".join(_)

            trans = FSTransfer(date=date, direction=out, player=plr, type=type)
            xpath = './/div[contains(@class, "team--to")]/div/a'
            if team_name := "".join(i.xpath(xpath + "/text()")):
                tm_lnk = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))
                team_id = tm_lnk.split("/")[-2]

                if (team := cache.get_team(team_id)) is None:
                    team = Team(id=team_id, name=team_name, url=tm_lnk)
                trans.team = team
            output.append(trans)
        return output


def parse_row(row: html.HtmlElement, position: str) -> SquadMember:
    from .players import FSPlayer

    xpath = './/div[contains(@class, "cell--name")]/a/@href'
    link = FLASHSCORE + "".join(row.xpath(xpath))

    xpath = './/div[contains(@class, "cell--name")]/a/text()'
    name = "".join(row.xpath(xpath)).strip()
    try:  # Name comes in reverse order.
        sur, first = name.rsplit(" ", 1)
    except ValueError:
        first, sur = None, name

    plr = FSPlayer(forename=first, surname=sur, url=link)
    xpath = './/div[contains(@class,"flag")]/@title'
    plr.country = [str(x.strip()) for x in row.xpath(xpath) if x]
    xpath = './/div[contains(@class,"cell--age")]/text()'
    if age := "".join(row.xpath(xpath)).strip():
        plr.age = int(age)

    xpath = './/div[contains(@class,"jersey")]/text()'
    num = int("".join(row.xpath(xpath)) or 0)

    xpath = './/div[contains(@class,"matchesPlayed")]/text()'
    if apps := "".join(row.xpath(xpath)).strip():
        apps = int(apps)
    else:
        apps = 0

    xpath = './/div[contains(@class,"cell--goal")]/text()'
    if goals := "".join(row.xpath(xpath)).strip():
        goals = int(goals)
    else:
        goals = 0

    xpath = './/div[contains(@class,"yellowCard")]/text()'
    if yellows := "".join(row.xpath(xpath)).strip():
        yellows = int(yellows)
    else:
        yellows = 0

    xpath = './/div[contains(@class,"redCard")]/text()'
    if reds := "".join(row.xpath(xpath)).strip():
        reds = int(reds)
    else:
        reds = 0

    xpath = './/div[contains(@title,"Injury")]/@title'
    injury = "".join(row.xpath(xpath)).strip()

    return SquadMember(
        player=plr,
        position=position,
        squad_number=num,
        appearances=apps,
        goals=goals,
        assists=0,
        yellows=yellows,
        reds=reds,
        injury=injury,
    )


class SquadMember(BaseModel):
    """A Player that is a member of a team"""

    player: FSPlayer
    position: str

    squad_number: int
    position: str
    appearances: int
    goals: int
    assists: int
    yellows: int
    reds: int
    injury: str

    @property
    def output(self) -> str:
        """Return a row representing the Squad Member"""
        plr = self.player
        pos = self.position
        text = f"`#{self.squad_number}` {plr.flags} {plr.markdown} ({pos}): "

        if self.goals:
            text += f" {GOAL_EMOJI} {self.goals}"
        if self.appearances:
            text += f" {TEAM_EMOJI} {self.appearances}"
        if self.reds:
            text += f" {RED_CARD_EMOJI} {self.reds}"
        if self.yellows:
            text += f" {YELLOW_CARD_EMOJI} {self.yellows}"
        if self.injury:
            text += f" {INJURY_EMOJI} {self.injury}"
        return text


class FSTransfer(BaseModel):
    """A Transfer Retrieved from Flashscore"""

    class Config:
        arbitrary_types_allowed = True

    date: datetime.datetime
    direction: str
    player: FSPlayer
    type: str

    team: Team | None = None

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
