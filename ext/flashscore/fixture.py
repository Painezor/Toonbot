"""Submodule for handling Fixtures"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from lxml import html
from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel

from ext.utils import timed_events

from .abc import BaseFixture, Participant, BaseTeam
from .constants import FLASHSCORE
from .gamestate import GameState as GS
from .matchevents import IncidentParser, MatchIncident
from .news import HasNews
from .photos import MatchPhoto
from .table import HasTable
from .tv import TVListing

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .cache import FlashscoreCache
    from .competitions import Competition
    from .team import Team

logger = logging.getLogger("flashscore.fixture")


class HasFixtures:
    url: str | None = None

    async def fixtures(
        self, page: Page, cache: FlashscoreCache | None = None
    ) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        if self.url is None:
            raise AttributeError
        url = self.url + "/fixtures/"
        if page.url != url:
            try:
                await page.goto(url, timeout=5000)
            except PWTimeout:
                logger.error("Timed out loading page %s", url)
                return []
        return await self.parse_games(page, cache)

    async def results(
        self, page: Page, cache: FlashscoreCache | None = None
    ) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        if self.url is None:
            raise AttributeError
        url = self.url + "/results/"
        if page.url != url:
            try:
                await page.goto(url, timeout=5000)
            except PWTimeout:
                logger.error("Timed out loading page %s", url)
                return []
        return await self.parse_games(page, cache)

    async def parse_games(
        self, page: Page, cache: FlashscoreCache | None = None
    ) -> list[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
        from .competitions import Competition
        from .team import Team

        await (loc := page.locator("#live-table")).wait_for()
        htm = html.fromstring(await loc.inner_html())
        fixtures: list[Fixture] = []
        comp = None
        for i in htm.xpath('.//div[contains(@class, "sportName soccer")]/div'):
            if "event__header" in i.classes:
                xpath = './/div[contains(@class, "event__title")]//text()'
                country, league = i.xpath(xpath)
                league = league.split(" -")[0]

                if cache:
                    comp = cache.get_competition(title=f"{country}: {league}")

                if not comp:
                    comp = Competition(name=league, country=str(country))
                continue

            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
            except IndexError:
                continue

            url = f"{FLASHSCORE}/match/{fx_id}"

            xpath = './/div[contains(@class,"event__participant")]/text()'

            home, away = [
                Participant(team=Team(name=n.strip())) for n in i.xpath(xpath)
            ]
            fx = Fixture(home=home, away=away, id=fx_id, url=url)
            fx.competition = comp

            # score
            fx.set_score(i)
            fx.set_time(i)
            fixtures.append(fx)
        return fixtures


class Fixture(BaseFixture, HasNews, HasTable):
    """An object representing a Fixture from the Flashscore Website"""

    incidents: list[MatchIncident] = []

    @classmethod
    def from_mobi(cls, node: html.HtmlElement, id_: str) -> Fixture | None:
        link = "".join(node.xpath(".//a/@href"))
        url = FLASHSCORE + link

        xpath = "./text()"
        teams = [str(i.strip()) for i in node.xpath(xpath) if i.strip()]

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

        home = Participant(team=BaseTeam(name=home_name))
        away = Participant(team=BaseTeam(name=away_name))
        return Fixture(home=home, away=away, id=id_, url=url)

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

        if "'" in time or "+" in time or time.isdigit():
            self.time = time
            return
        logger.error('state "%s" (%s) not handled.', state, time)

    def set_score(self, node: html.HtmlElement) -> None:
        """Parse & set scoreline from parse_fixtures"""
        try:
            xpath = './/div[contains(@class,"event__score")]//text()'
            home, away = node.xpath(xpath)
            self.home.score = int(home.strip())
            self.away.score = int(away.strip())
        except ValueError:
            pass

    async def get_head_to_head(
        self, page: Page, btn: str | None = None
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
        await page.goto(f"{self.url}/#/photos")
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
        self, page: Page, btn: str | None = None
    ) -> list[MatchStat]:
        """Get the statistics for a match"""
        url = f"{self.url}/#/match-summary/match-statistics/"

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

    async def fetch(
        self, page: Page, cache: FlashscoreCache | None = None
    ) -> None:
        """Fetch all data for a fixture"""
        if self.url is None:
            logger.error("url is None on fixture %s", self.name)
            return

        await page.goto(self.url)
        loc = page.locator(".duelParticipant")
        await loc.wait_for(timeout=2500)
        tree = html.fromstring(await page.content())
        teams = self._parse_teams(tree, cache)
        self.home.team = teams[0]
        self.away.team = teams[1]

        if self.kickoff is None:
            xpath = ".//div[contains(@class, 'startTime')]/div/text()"
            k_o = "".join(tree.xpath(xpath))
            k_o = datetime.datetime.strptime(k_o, "%d.%m.%Y %H:%M")
            k_o = k_o.astimezone()
            self.kickoff = k_o

        # Infobox
        xpath = (
            './/div[contains(@class, "infoBoxModule")]'
            '/div[contains(@class, "info__")]/text()'
        )
        if infobox := tree.xpath(xpath):
            self.infobox = "".join(infobox)

        self.incidents = IncidentParser(self, tree).incidents
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')

        mls = tree.xpath('.//div[@class="mi__item"]')
        for i in mls:
            label = "".join(i.xpath('./span[@class="mi__item__name"]//text()'))
            label = label.strip(":").casefold()

            value = "".join(i.xpath('./span[@class="mi__item__val"]//text()'))

            if "referee" in label:
                self.referee = value
            elif "venue" in label:
                self.stadium = value
            elif "attendance" in label:
                self.attendance = int(value.replace(" ", ""))

            else:
                logger.info("Fixture, extra data found %s %s", label, value)

        tv = tree.xpath('.//div[@class="br__broadcasts"]//a')
        channels: list[TVListing] = []
        for i in tv:
            link = "".join(i.xpath(".//@href"))
            name = "".join(i.xpath(".//text()"))
            channels.append(TVListing(name=name, link=link))
        self.tv = channels

        div = tree.xpath(".//span[@class='tournamentHeader__country']")[0]
        comp_url = FLASHSCORE + "".join(div.xpath(".//@href")).rstrip("/")
        self.competition = await self.fetch_competition(page, comp_url, cache)

    def _parse_teams(
        self, tree: html.HtmlElement, cache: FlashscoreCache | None
    ) -> tuple[Team, Team]:
        from .team import Team

        teams: list[Team] = []
        for attr in ["home", "away"]:
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
            if cache is None or (team := cache.get_team(team_id)) is None:
                team = Team(id=team_id, name=name, url=FLASHSCORE + url)

            team.name = name
            logo = div.xpath('.//img[@class="participant__image"]/@src')
            logo = "".join(logo)
            if logo:
                team.logo_url = FLASHSCORE + logo
            teams.append(team)
        return tuple(teams)

    async def fetch_competition(
        self,
        page: Page,
        url: str,
        cache: FlashscoreCache | None = None,
    ) -> Competition | None:
        """Go to a competition's page and fetch it directly."""
        from .competitions import Competition

        if cache:
            comp = cache.get_competition(url=url)
        else:
            comp = None

        await page.goto(url)
        selector = page.locator(".container__heading")

        try:
            await selector.wait_for()
        except PWTimeout:
            logger.error("Could not find .heading on %s", url)
            return comp

        tree = html.fromstring(await selector.inner_html())
        country = str(tree.xpath(".//a[@class='breadcrumb__link']/text()")[-1])

        # Name Correction
        name = "".join(tree.xpath('.//div[@class="heading__name"]/text()'))

        try:
            xpath = ".//span[contains(@title, 'My Leagues')]/@class"
            mylg = tree.xpath(xpath)[0]
            mylg = [i for i in mylg.rsplit(maxsplit=1) if "_" in i][-1]
            comp_id = mylg.rsplit("_", maxsplit=1)[-1]
            if comp is None and cache:
                comp = cache.get_competition(id=comp_id)
        except IndexError:
            comp_id = comp = None
            logger.error("Could not find mylg on %s", url)

        if comp is None:
            comp = Competition(id=comp_id, name=name, url=url, country=country)
        else:
            comp.url = url
            comp.country = country
            comp.name = name

        if img := tree.xpath('.//img[contains(@class, "heading__logo")]/@src'):
            comp.logo_url = FLASHSCORE + img[-1]
        return comp


class MatchStat(BaseModel):
    home: str
    label: str
    away: str
