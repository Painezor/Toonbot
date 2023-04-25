"""Submodule for handling Fixtures"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Optional

import discord
from lxml import html
from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel

from ext.utils import timed_events

from .abc import FSObject
from .constants import FLASHSCORE, GOAL_EMOJI, RED_CARD_EMOJI
from .gamestate import GameState as GS
from .matchevents import parse_events

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .competitions import Competition
    from .team import Team
    from .matchevents import MatchEvent

logger = logging.getLogger("flashscore.fixture")


class MatchStat(BaseModel):
    home: str
    label: str
    away: str

    def __str__(self) -> str:
        hom = self.home
        return f"{hom.rjust(4)} [{self.label.center(19)}] {self.away.ljust(4)}"


class MatchPhoto(BaseModel):
    """A photo from a fixture"""

    description: str
    url: str


class Fixture(FSObject):
    """An object representing a Fixture from the Flashscore Website"""

    emoji = GOAL_EMOJI

    def __init__(
        self, home: Team, away: Team, fs_id: Optional[str], url: Optional[str]
    ) -> None:
        if fs_id and not url:
            url = f"https://www.flashscore.com/?r=5:{fs_id}"

        if url and FLASHSCORE not in url:
            logger.info("Invalid url %s", url)

        super().__init__(fs_id, f"{home.name}:{away.name}", url)

        self.away: Team = away
        self.away_cards: Optional[int] = None
        self.away_score: Optional[int] = None
        self.penalties_away: Optional[int] = None

        self.home: Team = home
        self.home_cards: Optional[int] = None
        self.home_score: Optional[int] = None
        self.penalties_home: Optional[int] = None

        self.time: Optional[str | GS] = None
        self.kickoff: Optional[datetime.datetime] = None
        self.ordinal: Optional[int] = None

        self.attendance: Optional[int] = None
        self.competition: Optional[Competition] = None
        self.events: list[MatchEvent] = []
        self.infobox: Optional[str] = None
        self.images: Optional[list[str]] = None

        self.referee: Optional[str] = None
        self.stadium: Optional[str] = None

        # Hacky but works for results
        self.win: Optional[str] = None

    @classmethod
    def from_mobi(cls, node: html.HtmlElement, id_: str) -> Optional[Fixture]:
        # TODO: Nuke Circular
        from .team import Team

        link = "".join(node.xpath(".//a/@href"))
        url = FLASHSCORE + link

        xpath = "./text()"
        teams = [i.strip() for i in node.xpath(xpath) if i.strip()]

        if teams[0].startswith("updates"):
            # Awaiting Updates.
            teams[0] = teams[0].replace("updates", "")

        if len(teams) == 1:
            teams = teams[0].split(" - ")

        if len(teams) == 2:
            home_name, away_name = teams

        elif len(teams) == 3:
            if teams[1] == "La Duchere":
                home_name = f"{teams[0]} {teams[1]}"
                away_name = teams[2]
            elif teams[2] == "La Duchere":
                home_name = teams[0]
                away_name = f"{teams[1]} {teams[2]}"

            elif teams[0] == "Banik Most":
                home_name = f"{teams[0]} {teams[1]}"
                away_name = teams[2]
            elif teams[1] == "Banik Most":
                home_name = teams[0]
                away_name = f"{teams[1]} {teams[2]}"
            else:
                logger.error("Fetch games found %s", teams)
                return None
        else:
            logger.error("Fetch games found teams %s", teams)
            return None

        home = Team(None, home_name, None)
        away = Team(None, away_name, None)
        return Fixture(home, away, id_, url)

    def set_time(self, node: html.HtmlElement) -> None:
        """Set the time of the fixture from parse_fixtures"""
        state = None
        time = "".join(node.xpath('.//div[@class="event__time"]//text()'))
        override = "".join([i for i in time if i.isalpha()])
        time = time.replace(override, "")

        if override:
            try:
                self.time = {
                    "Abn": GS.ABANDONED,
                    "AET": GS.AFTER_EXTRA_TIME,
                    "Awrd": GS.AWARDED,
                    "FRO": GS.FINAL_RESULT_ONLY,
                    "Pen": GS.AFTER_PENS,
                    "Postp": GS.POSTPONED,
                    "WO": GS.WALKOVER,
                }[override]
            except KeyError:
                logger.error("missing state for override %s", override)

        dtn = datetime.datetime.now(tz=datetime.timezone.utc)
        for string, fmt in [
            (time, "%d.%m.%Y."),
            (time, "%d.%m.%Y"),
            (f"{dtn.year}.{time}", "%Y.%d.%m. %H:%M"),
            (f"{dtn.year}.{dtn.day}.{dtn.month}.{time}", "%Y.%d.%m.%H:%M"),
        ]:
            try:
                k_o = datetime.datetime.strptime(string, fmt)
                self.kickoff = k_o.astimezone(datetime.timezone.utc)

                if self.kickoff < dtn:
                    self.time = GS.SCHEDULED
                self.time = GS.FULL_TIME
                return
            except ValueError:
                continue
        else:
            logger.error("Failed to convert %s to datetime.", time)

        # Bypass time setter by directly changing _private val.
        if "'" in time or "+" in time or time.isdigit():
            self.time = time
            return
        logger.error('state "%s" (%s) not handled.', state, time)

    def set_score(self, node: html.HtmlElement) -> None:
        """Parse & set scoreline from parse_fixtures"""
        try:
            xpath = './/div[contains(@class,"event__score")]//text()'
            score_home, score_away = node.xpath(xpath)
            self.home_score = int(score_home.strip())
            self.away_score = int(score_away.strip())
        except ValueError:
            pass

    def __str__(self) -> str:
        if self.time in [GS.LIVE, GS.STOPPAGE_TIME, GS.EXTRA_TIME]:
            time = self.state.name if self.state else None
        elif isinstance(self.time, GS):
            time = self.ko_relative
        else:
            time = self.time

        return f"{time}: {self.bold_markdown}"

    @property
    def ac_row(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        out = f"⚽ {self.home.name} {self.score} {self.away.name}"
        if self.competition:
            out += f" ({self.competition.title})"
        return out

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold **winning** team, with
        [score](as markdown link)."""
        if self.home_score is None or self.away_score is None:
            return f"[{self.home.name} vs {self.away.name}]({self.url})"

        home = self.home.name
        away = self.away.name
        # Embolden Winner
        if self.home_score > self.away_score:
            home = f"**{home}**"
        if self.away_score > self.home_score:
            away = f"**{away}**"

        def parse_cards(cards: Optional[int]) -> str:
            """Get a number of icons matching number of cards"""
            if not cards:
                return ""
            if cards == 1:
                return f"`{RED_CARD_EMOJI}` "
            return f"`{RED_CARD_EMOJI} x{cards}` "

        h_s, a_s = self.home_score, self.away_score
        h_c = parse_cards(self.home_cards)
        a_c = parse_cards(self.away_cards)
        return f"{home} {h_c}[{h_s} - {a_s}]({self.url}){a_c} {away}"

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if self.kickoff is None:
            return ""

        time = timed_events.Timestamp(self.kickoff)
        dtn = datetime.datetime.now(tz=datetime.timezone.utc)
        if self.kickoff.date == dtn.date:
            # If the match is today, return HH:MM
            return time.time_hour
        elif self.kickoff.year != dtn.year:
            # if a different year, return DD/MM/YYYY
            return time.date
        elif self.kickoff > dtn:  # For Upcoming
            return time.date_long
        else:
            return time.relative

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output: list[str] = []
        if self.state is not None:
            output.append(f"`{self.state.emote}")

            if isinstance(self.time, str):
                output.append(self.time)
            else:
                if self.state != GS.SCHEDULED:
                    output.append(self.state.shorthand)
            output.append("` ")

        hm_n = self.home.name
        aw_n = self.away.name

        if self.home_score is None or self.away_score is None:
            time = timed_events.Timestamp(self.kickoff).time_hour
            output.append(f" {time} [{hm_n} v {aw_n}]({self.url})")
        else:
            # Penalty Shootout
            if self.penalties_home is not None:
                pens = f" (p: {self.penalties_home} - {self.penalties_away}) "
                sco = min(self.home_score, self.away_score)
                score = f"[{sco} - {sco}]({self.url})"
                output.append(f"{hm_n} {score}{pens}{aw_n}")
            else:
                output.append(self.bold_markdown)
        return "".join(output)

    @property
    def state(self) -> GS | None:
        """Get a GameState value from stored _time"""
        if isinstance(self.time, str):
            if "+" in self.time:
                return GS.STOPPAGE_TIME
            return GS.LIVE
        return self.time

    @property
    def score(self) -> str:
        """Return "X - Y", or 'vs' if scores are None"""
        if self.home_score is None:
            return "vs"
        return f"{self.home_score} - {self.away_score}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.name} {self.score} {self.away.name}"

    async def base_embed(self) -> discord.Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        if self.competition:
            embed = await self.competition.base_embed()
        else:
            embed = discord.Embed()

        embed.url = self.url
        if self.state:
            embed.colour = self.state.colour
        embed.set_author(name=self.score_line)
        embed.timestamp = self.kickoff
        embed.description = ""

        if self.infobox is not None:
            embed.add_field(name="Match Info", value=self.infobox)

        if self.time is None:
            return embed

        if self.time == GS.SCHEDULED:
            time = timed_events.Timestamp(self.kickoff).time_relative
            embed.description = f"Kickoff: {time}"
        elif self.time == GS.POSTPONED:
            embed.description = "This match has been postponed."

        if self.competition:
            embed.set_footer(text=f"{self.time} - {self.competition.title}")
        else:
            embed.set_footer(text=self.time)
        return embed

    async def get_head_to_head(
        self, page: Page, btn: Optional[str] = None
    ) -> list[str]:
        """Return a list of Fixtures matching head to head criteria"""
        url = f"{self.url}/#/h2h"
        await page.goto(url, timeout=5000)
        await page.wait_for_selector(".h2h", timeout=5000)
        if btn is not None:
            await page.locator(btn).click(force=True)

        tree = html.fromstring(await page.inner_html(".h2h"))

        game: html.HtmlElement
        xpath = './/div[@class="rows" or @class="section__title"]'

        output: list[str] = []
        for row in tree.xpath(xpath):
            if "section__title" in row.classes:
                header = row.xpath(".//text()")[0]
                output.append(f"\n**{header}**\n")
                continue

            for game in row:
                xpath = './/span[contains(@class, "homeParticipant")]//text()'
                home = "".join(game.xpath(xpath)).strip().title()

                xpath = './/span[contains(@class, "awayParticipant")]//text()'
                away = "".join(game.xpath(xpath)).strip().title()

                # Compare HOME team of H2H fixture to base fixture.
                xpath = './/span[contains(@class, "date")]/text()'
                k_o = game.xpath(xpath)[0].strip()
                k_o = datetime.datetime.strptime(k_o, "%d.%m.%y")
                k_o = timed_events.Timestamp(k_o).relative

                try:
                    tms = game.xpath('.//span[@class="h2h__result"]//text()')
                    tms = f"{tms[0]} - {tms[1]}"
                    # Directly set the private var to avoid the score setter.
                    output.append(f"{k_o} {home} {tms} {away}")
                except ValueError:
                    txt = game.xpath('.//span[@class="h2h__result"]//text()')
                    logger.error("ValueError trying to split string, %s", txt)
                    output.append(f"{k_o} {home} {txt} {away}")
        return output

    async def get_photos(self, page: Page) -> list[MatchPhoto]:
        """Get a list of Photos from a Fixture"""
        await page.goto(f"{self.url}#/photos")
        body = page.locator(".section")
        await body.wait_for()
        tree = html.fromstring(await body.inner_html())
        images = tree.xpath('.//div[@class="photoreportInner"]')
        photos: list[MatchPhoto] = []
        for i in images:
            url = "".join(i.xpath(".//img/@src"))
            desc = "".join(i.xpath('.//div[@class="liveComment"]/text()'))
            photos.append(MatchPhoto(url=url, description=desc))
        return photos

    async def get_stats(
        self, page: Page, btn: Optional[str] = None
    ) -> list[MatchStat]:
        """Get the statistics for a match"""
        url = f"{self.url}#/match-summary/match-statistics/"

        if btn is not None:
            await page.locator(btn).click(force=True)

        await page.goto(url, timeout=5000)
        await page.wait_for_selector(".section", timeout=5000)
        src = await page.inner_html(".section")

        stats: list[MatchStat] = []
        xpath = './/div[@class="stat__category"]'
        for i in html.fromstring(src).xpath(xpath):
            try:
                home = i.xpath('.//div[@class="stat__homeValue"]/text()')[0]
                stat = i.xpath('.//div[@class="stat__categoryName"]/text()')[0]
                away = i.xpath('.//div[@class="stat__awayValue"]/text()')[0]
                stats.append(MatchStat(home=home, label=stat, away=away))
            except IndexError:
                continue
        return stats

    async def get_table(
        self, page: Page, button: Optional[str] = None
    ) -> Optional[bytes]:
        """Get table from fixture"""
        if self.url is None:
            raise AttributeError("Fixture has no URL for get_table")

        url = self.url.rstrip("/") + "/#/standings"
        return await self._get_table(page, url, button)

    # High Cost lookups.
    async def refresh(self, page: Page) -> None:
        """Perform an intensive full lookup for a fixture"""
        # TODO: Nuke Ciruclar
        from .competitions import Competition

        if self.url is None:
            raise AttributeError(f"Can't refres - no url\n {self.__dict__}")

        try:
            await page.goto(self.url, timeout=5000)
            await page.locator(".container__detail").wait_for(timeout=5000)
            tree = html.fromstring(await page.content())
        except PWTimeout:
            return None

        # Some of these will only need updating once per match
        if self.kickoff is None:
            xpath = ".//div[contains(@class, 'startTime')]/div/text()"
            k_o = "".join(tree.xpath(xpath))
            k_o = datetime.datetime.strptime(k_o, "%d.%m.%Y %H:%M")
            k_o = k_o.astimezone()
            self.kickoff = k_o

        if None in [self.referee, self.stadium]:
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')

            if ref := "".join([i for i in text if "referee" in i.casefold()]):
                self.referee = ref.strip().replace("Referee:", "")

            if venue := "".join([i for i in text if "venue" in i.casefold()]):
                self.stadium = venue.strip().replace("Venue:", "")

        if self.competition is None or self.competition.url is None:
            xpath = './/span[contains(@class, "__country")]//a/@href'
            href = "".join(tree.xpath(xpath))

            xpath = './/span[contains(@class, "__country")]/text()'
            country = "".join(tree.xpath(xpath)).strip()

            xpath = './/span[contains(@class, "__country")]/a/text()'
            name = "".join(tree.xpath(xpath)).strip()

            comp_id = href.rsplit("/", maxsplit=1)[0] if href else None
            comp = Competition(comp_id, name, country, href)
            self.competition = comp

        # Grab infobox
        xpath = (
            './/div[contains(@class, "infoBoxModule")]'
            '/div[contains(@class, "info__")]/text()'
        )
        if infobox := tree.xpath(xpath):
            self.infobox = "".join(infobox)

        self.events = parse_events(self, tree)
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')
