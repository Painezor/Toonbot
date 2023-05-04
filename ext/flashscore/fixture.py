"""Submodule for handling Fixtures"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

from lxml import html
from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel, validator

from ext.utils import timed_events

from .constants import FLASHSCORE, GOAL_EMOJI, RED_CARD_EMOJI
from .gamestate import GameState as GS
from .matchevents import parse_events
from .news import HasNews
from .table import HasTable

if TYPE_CHECKING:
    from playwright.async_api import Page

    from .cache import FlashscoreCache
    from .competitions import Competition
    from .matchevents import MatchIncident
    from .team import Team

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


class FixtureParticipant(BaseModel):
    team: Team

    cards: int = 0
    score: int | None = None
    pens: int | None = None


class Fixture(BaseModel, HasNews, HasTable):
    """An object representing a Fixture from the Flashscore Website"""

    emoji = GOAL_EMOJI

    # Required
    home: FixtureParticipant
    away: FixtureParticipant

    # Optional
    id: str | None = None
    kickoff: datetime.datetime | None = None
    time: str | GS | None = None
    competition: Competition | None = None
    url: str | None = None

    # Match Events
    events: list[MatchIncident] = []

    # Extra data
    attendance: int | None = None
    infobox: str | None = None
    images: list[MatchPhoto] = []
    referee: str | None = None
    stadium: str | None = None

    @property
    def logo_url(self) -> str | None:
        if self.competition is not None:
            return self.competition.logo_url

    @property
    def name(self) -> str:
        return f"{self.home.team.name} v {self.away.team.name}"

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.score_line}"

    @validator("logo_url", always=True)
    def mk_logo_url(cls, value: str, values: dict[str, Any]) -> str | None:
        if "competition" in values:
            return values["competition"].logo_url

    @validator("home", "away", always=True)
    def partcipantify(cls, value: Team) -> FixtureParticipant:
        return FixtureParticipant(team=value)

    @classmethod
    def from_mobi(cls, node: html.HtmlElement, id_: str) -> Fixture | None:
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

        home = FixtureParticipant(team=Team(name=str(home_name)))
        away = FixtureParticipant(team=Team(name=str(away_name)))
        return cls(home=home, away=away, id=id_, url=url)

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
            home, away = node.xpath(xpath)
            self.home.score = int(home.strip())
            self.away.score = int(away.strip())
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
        out = f"⚽ {self.home.team.name} {self.score} {self.away.team.name}"
        if self.competition:
            out += f" ({self.competition.title})"
        return out

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold **winning** team, with
        [score](as markdown link)."""
        home = self.home.team
        away = self.away.team
        if self.home.score is None or self.away.score is None:
            return f"[{home.name} vs {away.name}]({self.url})"

        # Embolden Winner
        if self.home.score > self.away.score:
            home = f"**{home}**"
        elif self.away.score > self.home.score:
            away = f"**{away}**"

        def parse_cards(cards: int | None) -> str:
            """Get a number of icons matching number of cards"""
            if not cards:
                return ""
            if cards == 1:
                return f"`{RED_CARD_EMOJI}` "
            return f"`{RED_CARD_EMOJI} x{cards}` "

        h_s, a_s = self.home.score, self.away.score
        h_c = parse_cards(self.home.cards)
        a_c = parse_cards(self.away.cards)
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

        hm_n = self.home.team.name
        aw_n = self.away.team.name

        if self.home.score is None or self.away.score is None:
            time = timed_events.Timestamp(self.kickoff).time_hour
            output.append(f" {time} [{hm_n} v {aw_n}]({self.url})")
        else:
            # Penalty Shootout
            if self.home.pens is not None:
                pens = f" (p: {self.home.pens} - {self.away.pens}) "
                sco = min(self.home.score, self.away.score)
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
        if self.home.score is None:
            return "vs"

        if self.home.pens:
            ph = self.home.pens
            pa = self.away.pens
            return f"({self.home.score}) ({ph}) - ({pa}) {self.away.score}"

        return f"{self.home.score} - {self.away.score}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.team.name} {self.score} {self.away.team.name}"

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
        self, page: Page, btn: str | None = None
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

    @property
    def table_url(self) -> str:
        if self.url is None:
            raise AttributeError("Fixture has no URL for get_table")
        return self.url.rstrip("/") + "/#/standings"

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

        div = tree.xpath(".//span[@class='tournamentHeader__country']")[0]

        url = FLASHSCORE + "".join(div.xpath(".//@href")).rstrip("/")
        country = "".join(div.xpath("./text()"))

        mls = tree.xpath('.//div[@class="ml__item"]')
        for i in mls:
            label = "".join(i.xpath('./span[@class="mi__item__name]/text()'))
            label = label.strip(":")

            value = "".join(i.xpath('/span[@class="mi__item__val"]/text()'))

            if "referee" in label.lower():
                self.referee = value
            elif "venue" in label.lower():
                self.stadium = value
            else:
                logger.info("Fixture, extra data found %s %s", label, value)

        if country:
            country = country.split(":", maxsplit=1)[0]

        if cache:
            comp = cache.get_competition(url)
            if comp is not None:
                self.competition = comp
                return

        self.competition = await self.fetch_competition(page, url, cache)

    async def fetch_competition(
        self,
        page: Page,
        url: str,
        cache: FlashscoreCache | None = None,
    ) -> Competition | None:
        """Go to a competition's page and fetch it directly."""
        await page.goto(url)
        selector = page.locator(".container__heading")

        try:
            await selector.wait_for()
        except PWTimeout:
            logger.error("Could not find .heading on %s", url)
            return

        tree = html.fromstring(await selector.inner_html())
        country = tree.xpath(".//a[@class='breadcrumb__link']")[-1]

        mylg = tree.xpath(".//span[contains(@title, 'Add this')]/@class")[0]
        mylg = [i for i in mylg.rsplit(maxsplit=1) if "_" in i][-1]
        comp_id = mylg.rsplit("_", maxsplit=1)[-1]

        src = None

        try:
            # Name Correction
            name_loc = page.locator(".heading__name").first
            logo_url = page.locator(".heading__logo").first

            name = await name_loc.text_content(timeout=1000)
            if name is None:
                logger.error("Failed to find name on %s", url)
                return
            src = await logo_url.get_attribute("src", timeout=1000)
        except PWTimeout:
            logger.error("Timed out heading__logo %s", url)
            return

        comp = cache.get_competition(comp_id) if cache else None

        if comp is None:
            comp = Competition(id=comp_id, name=name, country=country, url=url)

        if src is not None:
            comp.logo_url = FLASHSCORE + src

        return comp

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
            comp = Competition(
                id=comp_id, name=name, country=country, url=href
            )
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


class HasFixtures:
    url: str | None = None

    async def fixtures(self, page: Page) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        if self.url is None:
            raise AttributeError
        url = self.url + "/fixtures/"
        if page.url != url:
            try:
                await page.goto(url, timeout=3000)
            except PWTimeout:
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
            except PWTimeout:
                logger.error("Timed out loading page %s", page.url)
                return []
        return await self.parse_games(page)

    async def parse_games(self, page: Page) -> list[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
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
                comp = Competition(name=league, country=country)
                continue

            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
            except IndexError:
                continue

            url = f"{FLASHSCORE}/match/{fx_id}"

            xpath = './/div[contains(@class,"event__participant")]/text()'

            home, away = [
                FixtureParticipant(team=Team(name=n.strip()))
                for n in i.xpath(xpath)
            ]
            fx = Fixture(home=home, away=away, id=fx_id, url=url)
            fx.competition = comp

            # score
            fx.set_score(i)
            fx.set_time(i)
            fixtures.append(fx)
        return fixtures
