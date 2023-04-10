"""Abstract Base Class for Flashscore Items"""
from __future__ import annotations

import datetime
import logging
import typing

import discord
from playwright.async_api import Page, TimeoutError as PWTimeoutError
from lxml import html

from ext.utils import embed_utils

from .constants import FLASHSCORE, LOGO_URL
from .competitions import Competition
from .fixture import Fixture
from .team import Team
from .gamestate import GameState


logger = logging.getLogger("ext.flashscore.abc")


def find(value: str, cache: set[Competition]) -> typing.Optional[Competition]:
    """Retrieve a competition from the ones stored in the bot."""
    if value is None:
        return None

    for i in cache:
        if i.id == value:
            return i

        if i.title.casefold() == value.casefold():
            return i

        if i.url is not None:
            if i.url.rstrip("/") == value.rstrip("/"):
                return i

    # Fallback - Get First Partial match.
    for i in cache:
        if i.url is not None and "http" in value:
            if value in i.url:
                logger.info("Partial url: %s to %s (%s)", value, i.id, i.title)
                return i
    return None


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""

    def __init__(
        self,
        fsid: typing.Optional[str],
        name: str,
        url: typing.Optional[str],
    ) -> None:
        self.id: typing.Optional[str] = fsid  # pylint: disable=C0103
        self.name: str = name
        self.url: typing.Optional[str] = url
        self.embed_colour: typing.Optional[discord.Colour | int] = None
        self.logo_url: typing.Optional[str] = None

    def __hash__(self) -> int:
        return hash(repr(self))

    def __repr__(self) -> str:
        return f"FlashScoreItem({self.__dict__})"

    def __eq__(self, other: FlashScoreItem) -> bool:
        if self.id is None:
            return self.title == other.title
        return self.id == other.id

    @property
    def markdown(self) -> str:
        """Shorthand for FSR mark-down link"""
        if self.url is not None:
            return f"[{self.title or 'Unknown Item'}]({self.url})"
        return self.name or "Unknown Item"

    @property
    def title(self) -> str:
        """Alias to name, or Unknown Item if not found"""
        return self.name or "Unknown Item"

    async def base_embed(self) -> discord.Embed:
        """A discord Embed representing the flashscore search result"""
        embed = discord.Embed()
        embed.description = ""
        if self.logo_url is not None:
            if "flashscore" in self.logo_url:
                logo = self.logo_url
            else:
                logo = LOGO_URL + self.logo_url.replace("'", "")  # Extraneous

            if logo:
                if (clr := self.embed_colour) is None:
                    clr = await embed_utils.get_colour(logo)
                    self.embed_colour = clr
                embed.colour = clr
            embed.set_author(name=self.title, icon_url=logo, url=self.url)
        else:
            embed.set_author(name=self.title, url=self.url)
        return embed

    async def fixtures(
        self, page: Page, cache: set[Competition]
    ) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        return await self.parse_games(page, cache, upcoming=True)

    async def results(
        self, page: Page, cache: set[Competition]
    ) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        return await self.parse_games(page, cache, upcoming=False)

    async def parse_games(
        self, page: Page, cache: set[Competition], upcoming: bool
    ) -> list[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
        sub_page = "/fixtures/" if upcoming else "/results/"

        if self.url is None:
            logger.error("No URL found on %s", self)
            return []

        try:
            await page.goto(self.url + sub_page, timeout=5000)
            loc = page.locator("#live-table")
            await loc.wait_for()
            tree = html.fromstring(await page.content())
        except PWTimeoutError:
            logger.error("Timed out parsing games on %s", self.url + sub_page)
            return []

        fixtures: list[Fixture] = []

        if isinstance(self, Competition):
            comp = self
        else:
            comp = Competition(None, "Unknown", "Unknown", None)

        xpath = './/div[contains(@class, "sportName soccer")]/div'

        games = tree.xpath(xpath)
        for i in games:
            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
                url = f"{FLASHSCORE}/match/{fx_id}"
            except IndexError:
                # This (might be) a header row.
                if "event__header" in i.classes:
                    xpath = './/div[contains(@class, "event__title")]//text()'
                    country, league = i.xpath(xpath)
                    league = league.split(" - ")[0]

                    ctr = country.casefold()
                    league = league.casefold().split(" -")[0]

                    comp = find(f"{ctr.upper()}: {league}", cache)
                    if comp is None:
                        comp = Competition(None, league, country, None)
                continue

            xpath = './/div[contains(@class,"event__participant")]/text()'
            home, away = i.xpath(xpath)

            # TODO: Fetch team ID & URL
            home = Team(None, home.strip(), None)
            away = Team(None, away.strip(), None)

            fixture = Fixture(home, away, fx_id, url)
            fixture.competition = comp

            fixture.win = "".join(i.xpath(".//div[@class='formIcon']/@title"))

            # score
            try:
                xpath = './/div[contains(@class,"event__score")]//text()'
                score_home, score_away = i.xpath(xpath)

                fixture.home_score = int(score_home.strip())
                fixture.away_score = int(score_away.strip())
            except ValueError:
                pass
            state = None

            # State Corrections
            time = "".join(i.xpath('.//div[@class="event__time"]//text()'))
            override = "".join([i for i in time if i.isalpha()])
            time = time.replace(override, "")

            if override:
                try:
                    state = {
                        "Abn": GameState.ABANDONED,
                        "AET": GameState.AFTER_EXTRA_TIME,
                        "Awrd": GameState.AWARDED,
                        "FRO": GameState.FINAL_RESULT_ONLY,
                        "Pen": GameState.AFTER_PENS,
                        "Postp": GameState.POSTPONED,
                        "WO": GameState.WALKOVER,
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
                    fixture.kickoff = k_o.astimezone(datetime.timezone.utc)

                    if fixture.kickoff < dtn:
                        state = GameState.SCHEDULED
                    else:
                        state = GameState.FULL_TIME
                    break
                except ValueError:
                    continue
            else:
                logger.error("Failed to convert %s to datetime.", time)

            # Bypass time setter by directly changing _private val.
            if isinstance(state, GameState):
                fixture.time = state
            else:
                if "'" in time or "+" in time or time.isdigit():
                    fixture.time = time
                else:
                    logger.error('state "%s" (%s) not handled.', state, time)
            fixtures.append(fixture)
        return fixtures
