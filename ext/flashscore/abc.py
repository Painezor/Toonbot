"""Abstract Base Class for Flashscore Items"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from git import TYPE_CHECKING
from lxml import html
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeoutError

from ext.utils import embed_utils


if TYPE_CHECKING:
    from .fixture import Fixture

from .constants import ADS, FLASHSCORE, LOGO_URL
from .news import NewsArticle
from .players import FSPlayer, TopScorer

logger = logging.getLogger("ext.flashscore.abc")

javascript = "ads => ads.forEach(x => x.remove());"


class FSObject:
    """A generic object representing the result of a Flashscore search"""

    name: str
    id: Optional[str]  # pylint: disable=C0103
    url: Optional[str]

    logo_url: Optional[str] = None
    embed_colour: Optional[discord.Colour | int] = None

    def __init__(
        self, fsid: Optional[str], name: str, url: Optional[str]
    ) -> None:
        self.id = fsid  # pylint: disable=C0103
        self.name = name
        self.url = url

    def __hash__(self) -> int:
        return hash(repr(self))

    def __repr__(self) -> str:
        return f"FlashScoreItem({self.__dict__})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FSObject):
            return False
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

    async def get_logo(self, page: Page) -> None:
        """Re-Cache the logo of this item."""
        if self.logo_url is None:
            logo = page.locator("img.heading__logo")
            logo_url = await logo.get_attribute("src")
            if logo_url is not None:
                logo_url = FLASHSCORE + logo_url
                self.logo_url = logo_url

    async def fixtures(self, page: Page) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        if self.url is None:
            raise AttributeError
        url = self.url + "/fixtures/"
        if page.url != url:
            try:
                await page.goto(url, timeout=3000)
            except PWTimeoutError:
                logger.error("Timed out loading page %s", page.url)
                return []
        return await self.parse_games(page)

    async def results(self, page: Page) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        if self.url is None:
            raise AttributeError
        url = self.url + "/results/"
        if page.url != url:
            try:
                await page.goto(url, timeout=3000)
            except PWTimeoutError:
                logger.error("Timed out loading page %s", page.url)
                return []
        return await self.parse_games(page)

    async def parse_games(self, page: Page) -> list[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
        from .fixture import Fixture  # TODO: Uncircular.
        from .competitions import Competition
        from .team import Team

        await (loc := page.locator("#live-table")).wait_for()
        htm = html.fromstring(await loc.inner_html())

        comp = self if isinstance(self, Competition) else None
        fixtures: list[Fixture] = []
        for i in htm.xpath('.//div[contains(@class, "sportName soccer")]/div'):
            if "event__header" in i.classes:
                xpath = './/div[contains(@class, "event__title")]//text()'
                country, league = i.xpath(xpath)
                league = league.casefold().split(" -")[0]
                comp = Competition(None, league, country, None)
                continue

            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
            except IndexError:
                continue

            url = f"{FLASHSCORE}/match/{fx_id}"

            xpath = './/div[contains(@class,"event__participant")]/text()'
            home, away = i.xpath(xpath)

            # TODO: Fetch team ID & URL
            home = Team(None, home.strip(), None)
            away = Team(None, away.strip(), None)

            fx = Fixture(home, away, fx_id, url)
            fx.competition = comp

            fx.win = "".join(i.xpath(".//div[@class='formIcon']/@title"))
            # score
            fx.set_score(i)
            fx.set_time(i)
            fixtures.append(fx)
        return fixtures

    async def get_news(self, page: Page) -> list[NewsArticle]:
        """Fetch a list of NewsArticles for Pagination"""
        await page.goto(f"{self.url}/news", timeout=5000)
        locator = page.locator(".rssNews")
        await locator.wait_for()

        articles: list[NewsArticle] = []
        for i in await locator.all():
            articles.append(NewsArticle(html.fromstring(await i.inner_html())))
        return articles

    async def _get_table(
        self, page: Page, url: str, button: Optional[str] = None
    ) -> Optional[bytes]:
        """Get the table from a flashscore page"""
        await page.goto(url, timeout=5000)

        if button:
            loc = page.locator("button")
            await loc.click(force=True)

        # Chaining Locators is fucking aids.
        # Thank you for coming to my ted talk.
        inner = page.locator(".tableWrapper, .draw__wrapper")
        outer = page.locator("div", has=inner)
        table_div = page.locator("div", has=outer).last

        try:
            await table_div.wait_for(state="visible", timeout=5000)
        except PWTimeoutError:
            # Entry point not handled on fixtures from leagues.
            logger.error("Failed to find standings on %s", page.url)
            return None

        await page.eval_on_selector_all(ADS, javascript)
        return await table_div.screenshot(type="png")

    async def get_table(
        self, page: Page, button: Optional[str] = None
    ) -> Optional[bytes]:
        """Get the table for an object"""
        if self.url is None:
            raise AttributeError("url is None on %s", self.name)
        url = self.url.rstrip("/") + "/standings"
        return await self._get_table(page, url, button)

    async def get_scorers(self, page: Page) -> list[TopScorer]:
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
        rows = tree.xpath('.//div[@class="ui-table__body"]/div')
        return [parse_scorer(i) for i in rows]


def parse_scorer(node: html.HtmlElement) -> TopScorer:
    """Turn an xpath node into a TopScorer Object"""
    from .team import Team

    xpath = "./div[1]//text()"
    name = "".join(node.xpath(xpath))

    xpath = "./div[1]//@href"
    url = FLASHSCORE + "".join(node.xpath(xpath))

    scorer = TopScorer(FSPlayer(None, name, url))
    xpath = "./span[1]//text()"
    scorer.rank = int("".join(node.xpath(xpath)).strip("."))

    xpath = './/span[contains(@class,"flag")]/@title'
    scorer.player.country = node.xpath(xpath)

    xpath = './/span[contains(@class, "--goals")]/text()'
    try:
        scorer.goals = int("".join(node.xpath(xpath)))
    except ValueError:
        pass

    xpath = './/span[contains(@class, "--gray")]/text()'
    try:
        scorer.assists = int("".join(node.xpath(xpath)))
    except ValueError:
        pass

    team_url = FLASHSCORE + "".join(node.xpath("./a/@href"))
    team_id = team_url.split("/")[-2]

    tmn = "".join(node.xpath("./a/text()"))
    team_link = "".join(node.xpath(".//a/@href"))
    tm = Team(team_id, tmn, team_link)

    scorer.team = tm
    return scorer
