"""Abstract Base Class for Flashscore Items"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import typing

import discord
from lxml import html
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeoutError

from ext.utils import embed_utils

from .competitions import Competition
from .constants import FLASHSCORE, LOGO_URL
from .fixture import Fixture
from .gamestate import GameState
from .players import Player, TopScorer
from .team import Team, save_team

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]


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


@dataclasses.dataclass(slots=True)
class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""

    name: str
    id: typing.Optional[str]  # pylint: disable=C0103
    url: typing.Optional[str]

    logo_url: typing.Optional[str] = None
    embed_colour: typing.Optional[discord.Colour | int] = None

    def __init__(
        self,
        fsid: typing.Optional[str],
        name: str,
        url: typing.Optional[str],
    ) -> None:
        self.id = fsid
        self.name = name
        self.url = url

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

    async def get_scorers(
        self, page: Page, interaction: Interaction
    ) -> list[TopScorer]:
        """Get a list of TopScorer objects for the Flashscore Item"""
        link = f"{self.url}/standings/"

        # Example link "#/nunhS7Vn/top_scorers"
        # This requires a competition ID, annoyingly.
        if link not in page.url:
            logger.info("Forcing page change %s -> %s", page.url, link)
            await page.goto(link)

        top_scorer_button = page.locator("a", has_text="Top Scorers")
        await top_scorer_button.wait_for(timeout=5000)

        if await top_scorer_button.get_attribute("aria-current") != "page":
            await top_scorer_button.click()

        tab_class = page.locator("#tournament-table-tabs-and-content")
        await tab_class.wait_for()

        btn = page.locator(".topScorers__showMore")
        while await btn.count():
            await btn.last.click()

        raw = await tab_class.inner_html()
        tree = html.fromstring(raw)

        scorers: list[TopScorer] = []

        rows = tree.xpath('.//div[@class="ui-table__body"]/div')

        for i in rows:
            xpath = "./div[1]//text()"
            name = "".join(i.xpath(xpath))

            xpath = "./div[1]//@href"
            url = FLASHSCORE + "".join(i.xpath(xpath))

            scorer = TopScorer(player=Player(None, name, url))
            xpath = "./span[1]//text()"
            scorer.rank = int("".join(i.xpath(xpath)).strip("."))

            xpath = './/span[contains(@class,"flag")]/@title'
            scorer.player.country = i.xpath(xpath)

            xpath = './/span[contains(@class, "--goals")]/text()'
            try:
                scorer.goals = int("".join(i.xpath(xpath)))
            except ValueError:
                pass

            xpath = './/span[contains(@class, "--gray")]/text()'
            try:
                scorer.assists = int("".join(i.xpath(xpath)))
            except ValueError:
                pass

            team_url = FLASHSCORE + "".join(i.xpath("./a/@href"))
            team_id = team_url.split("/")[-2]

            tmn = "".join(i.xpath("./a/text()"))

            if (team := interaction.client.get_team(team_id)) is None:
                team_link = "".join(i.xpath(".//a/@href"))
                team = Team(team_id, tmn, team_link)

                comp_id = url.split("/")[-2]
                team.competition = interaction.client.get_competition(comp_id)
            else:
                if team.name != tmn:
                    logger.info("Overrode team name %s -> %s", team.name, tmn)
                    team.name = tmn
                    await save_team(interaction.client, team)

            scorer.team = team
            scorers.append(scorer)
        return scorers
