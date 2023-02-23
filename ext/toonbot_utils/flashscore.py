"""A Utility tool for fetching and structuring data from Flashscore"""
from __future__ import annotations  # Cyclic Type Hinting

import logging
from asyncio import Semaphore
from datetime import datetime, timezone
from io import BytesIO
from typing import TYPE_CHECKING, Literal, Optional, ClassVar

from discord import Embed, Interaction, Colour
from discord.app_commands import Choice
from lxml import html
from playwright.async_api import Page

from ext.toonbot_utils.gamestate import GameState
from ext.toonbot_utils.matchevents import EventType
from ext.toonbot_utils.matchevents import parse_events
from ext.utils.embed_utils import get_colour
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from ext.toonbot_utils.matchevents import MatchEvent
    from core import Bot

# TODO: Figure out caching system for high intensity lookups

logger = logging.getLogger("flashscore")

ADS = (
    ".ads-envelope, "
    ".bannerEnvelope, "
    ".banner--sticky, "
    ".extraContent, "
    ".seoAdWrapper, "
    ".isSticky, "
    ".ot-sdk-container, "
    ".otPlaceholder, "
    ".onetrust-consent-sdk, "
    ".rollbar, "
    ".selfPromo, "
    "#box-over-content, "
    "#box-over-content-detail, "
    "#box-over-content-a,"
    "#lsid-window-mask"
)

FLASHSCORE = "https://www.flashscore.com"
LOGO_URL = FLASHSCORE + "/res/image/data/"
INJURY_EMOJI = "<:injury:682714608972464187>"
DEFAULT_LEAGUES = [
    "WORLD: Friendly international",
    "EUROPE: Champions League",
    "EUROPE: Euro",
    "EUROPE: Europa League",
    "EUROPE: UEFA Nations League",
    "ENGLAND: Premier League",
    "ENGLAND: Championship",
    "ENGLAND: League One",
    "ENGLAND: FA Cup",
    "ENGLAND: EFL Cup",
    "FRANCE: Ligue 1",
    "FRANCE: Coupe de France",
    "GERMANY: Bundesliga",
    "ITALY: Serie A",
    "NETHERLANDS: Eredivisie",
    "SCOTLAND: Premiership",
    "SPAIN: Copa del Rey",
    "SPAIN: LaLiga",
    "USA: MLS",
]
WORLD_CUP_LEAGUES = [
    "EUROPE: World Cup",
    "ASIA: World Cup",
    "AFRICA: World Cup",
    "NORTH & CENTRAL AMERICA: World Cup",
    "SOUTH AMERICA: World Cup",
]

semaphore = Semaphore(5)


# Competition Autocomplete
async def lg_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete from list of stored leagues"""
    bot: Bot = interaction.client
    matches = [
        i
        for i in bot.competitions
        if current.lower() in i.title.lower() and i.id is not None
    ]
    return [Choice(name=i.title[:100], value=i.id) for i in list(matches)[:25]]


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""

    bot: ClassVar[Bot]

    __slots__ = ["id", "url", "name", "embed_colour", "logo_url"]

    def __init__(
        self, fsid: str = None, name: str = None, link: str = None
    ) -> None:
        self.id: Optional[str] = fsid
        self.url: Optional[str] = link
        self.name: Optional[str] = name
        self.embed_colour: Optional[Colour] = None
        self.logo_url: Optional[str] = None

    def __hash__(self) -> hash:
        return hash(repr(self))

    def __repr__(self) -> repr:
        return f"FlashScoreItem({self.__dict__})"

    def __eq__(self, other: FlashScoreItem):
        if None not in [self.id, other]:
            return self.id == other.id

        if None not in [self.link, other]:
            return self.link == other.link

        if hasattr(self, "title") and hasattr(other, "title"):
            return self.title == other.title

    @property
    def markdown(self) -> str:
        """Shorthand for FSR mark-down link"""
        name = "Unknown" if self.name is None else self.name
        if self.link is not None:
            return f"[{name}]({self.link})"
        return name

    @property
    def link(self) -> str:
        """Alias to self.url, polymorph for subclasses."""
        return self.url

    async def base_embed(self) -> Embed:
        """A discord Embed representing the flashscore search result"""

        title = self.title if hasattr(self, "title") else self.name
        e: Embed = Embed(title=title, url=self.link)
        e.description = ""
        if self.logo_url is not None:
            if "flashscore" in self.logo_url:
                logo = self.logo_url
            else:
                logo = LOGO_URL + self.logo_url.replace("'", "")  # Extraneous

            if logo:
                if (clr := self.embed_colour) is None:
                    clr = await get_colour(logo)
                    self.embed_colour = clr
                e.colour = clr
                e.set_thumbnail(url=logo)
        return e

    async def parse_games(self, link: str) -> list[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(link, timeout=5000)
                await page.wait_for_selector(".sportName.soccer", timeout=5000)
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        fixtures: list[Fixture] = []
        comp = self if isinstance(self, Competition) else None

        xp = '..//div[contains(@class, "sportName soccer")]/div'
        if not (games := tree.xpath(xp)):
            raise LookupError(f"No fixtures found on {link}")

        for i in games:
            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
                url = FLASHSCORE + "/match/" + fx_id
            except IndexError:
                # This (might be) a header row.
                if "event__header" in i.classes:
                    xp = './/div[contains(@class, "event__title")]//text()'
                    country, league = i.xpath(xp)
                    league = league.split(" - ")[0]

                    for x in self.bot.competitions:
                        lg = league.lower().split(" -")[0]
                        ctr = country.lower()
                        if x.name.lower() == lg and x.country.lower() == ctr:
                            comp = x
                            break
                    else:
                        comp = Competition()
                        comp.country = country
                        comp.name = league
                continue

            fixture = Fixture(fx_id)
            fixture.competition = comp
            fixture.url = url

            # score
            xp = './/div[contains(@class,"event__participant")]/text()'
            home, away = i.xpath(xp)
            fixture.home = Team(name=home.strip())
            fixture.away = Team(name=away.strip())

            try:
                xp = './/div[contains(@class,"event__score")]//text()'
                score_home, score_away = i.xpath(xp)
                # Directly access the private var, so we don't dispatch events.
                fixture._score_home = int(score_home.strip())
                fixture._score_away = int(score_away.strip())
            except ValueError:
                pass
            state = None

            # State Corrections
            parsed = "".join(i.xpath('.//div[@class="event__time"]//text()'))
            override = "".join([i for i in parsed if i.isalpha()])
            parsed = parsed.replace(override, "")
            match override:
                case "":
                    pass
                case "AET":
                    state = GameState.AFTER_EXTRA_TIME
                case "Pen":
                    state = GameState.AFTER_PENS
                case "Postp":
                    state = GameState.POSTPONED
                case "FRO":
                    state = GameState.FINAL_RESULT_ONLY
                case "WO":
                    state = GameState.WALKOVER
                case "Awrd":
                    state = GameState.AWARDED
                case "Postp":
                    state = GameState.POSTPONED
                case "Abn":
                    state = GameState.ABANDONED

            dtn = datetime.now(tz=timezone.utc)
            for string, fmt in [
                (parsed, "%d.%m.%Y."),
                (parsed, "%d.%m.%Y"),
                (f"{dtn.year}.{parsed}", "%Y.%d.%m. %H:%M"),
                (
                    f"{dtn.year}.{dtn.day}.{dtn.month}.{parsed}",
                    "%Y.%d.%m.%H:%M",
                ),
            ]:
                try:
                    ko = datetime.strptime(string, fmt)
                    fixture.kickoff = ko.astimezone()
                    break
                except ValueError:
                    continue
            else:
                logger.error(f"Failed to convert {parsed} to datetime.")

            if state is None:
                if fixture.kickoff > datetime.now(tz=timezone.utc):
                    state = GameState.SCHEDULED
                else:
                    state = GameState.FULL_TIME

            # Bypass time setter by directly changing _private val.
            if isinstance(state, GameState):
                fixture._time = state
            elif isinstance(state, datetime):
                if fixture.kickoff < dtn:
                    fixture._time = GameState.FULL_TIME
                else:
                    fixture._time = GameState.SCHEDULED
            else:
                if "'" in parsed or "+" in parsed or parsed.isdigit():
                    fixture._time = parsed
                else:
                    logger.error(f'state "{state}" ({parsed}) not handled.')
            fixtures.append(fixture)
        return fixtures

    async def fixtures(self) -> list[Fixture]:
        """Get all upcoming fixtures related to the FlashScoreItem"""
        return await self.parse_games(self.link + "/fixtures/")

    async def results(self) -> list[Fixture]:
        """Get recent results for the FlashScore Item"""
        return await self.parse_games(self.link + "/results/")


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""

    __slots__ = {
        "competition": "The competition the team belongs to",
        "logo_url": "A link to a logo representing the competition",
    }

    # Constant
    emoji: ClassVar[str] = "👕"

    def __init__(
        self, fs_id: str = None, name: str = None, link: str = None, **kwargs
    ) -> None:

        super().__init__(fs_id, name, link)
        self.competition: Competition | None = kwargs.pop("competition", None)

    def __str__(self) -> str:
        output = self.name

        if self.competition is not None:
            output = f"{output} ({self.competition.title})"

        return output

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        match len(self.name.split(" ")):
            case 1:
                return "".join(self.name[:3]).upper()
            case _:
                return "".join([i for i in self.name if i.isupper()])

    @property
    def link(self) -> str:
        """Long form forced url"""
        if self.url is None:
            return ""
        if "://" in self.url:
            return self.url

        # Example URL:
        # https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        return FLASHSCORE + f"/team/{self.url}/{self.id}"

    async def save_to_db(self) -> None:
        """Save the Team to the Bot Database"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO fs_teams (id, name, logo_url, url)
                       VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
                await connection.execute(
                    sql, self.id, self.name, self.logo_url, self.url
                )
        self.bot.teams.append(self)

    async def news(self) -> list[Embed]:
        """Get a list of news articles related to a team in embed format"""
        page = await self.bot.browser.new_page()
        try:
            await page.goto(f"{self.link}/news", timeout=5000)
            await page.locator(".matchBox").wait_for()
            tree = html.fromstring(await page.content())
        finally:
            await page.close()

        items = []
        base_embed = await self.base_embed()
        for i in tree.xpath('.//div[@id="tab-match-newsfeed"]'):
            article = NewsItem(team_embed=base_embed.copy())

            xpath = './/div[@class="rssNews__title"]/text()'
            article.title = "".join(i.xpath(xpath))
            article.image_url = "".join(i.xpath(".//img/@src"))

            xpath = './/a[@class="rssNews__titleAndPerex"]/@href'
            article.url = FLASHSCORE + "".join(i.xpath(xpath))

            xpath = './/div[@class="rssNews__perex"]/text()'
            article.blurb = "".join(i.xpath(xpath))

            xpath = './/div[@class="rssNews__provider"]/text()'
            provider = "".join(i.xpath(xpath)).split(",")

            article.time = datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
            article.source = provider[-1].strip()
            items.append(article.embed)
        return items

    async def players(self) -> list[Player]:
        """Get a list of players for a Team"""
        # Check Cache
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                for x in range(3):
                    try:
                        await page.goto(f"{self.link}/squad", timeout=5000)
                        break
                    except TimeoutError:
                        continue
                else:
                    return []

                try:
                    sel = ".squad-table.profileTable"
                    await page.wait_for_selector(sel, timeout=5000)
                except TimeoutError:
                    return []

                if await (btn := page.locator('text="Total"')).count():
                    await btn.click()

                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        # tab += 1  # tab is Indexed at 0 but xpath indexes from [1]
        rows = tree.xpath(
            './/div[contains(@class, "squad-table")]'
            '[contains(@id, "overall-all-table")]'
            '//div[contains(@class,"profileTable__row")]'
        )

        players = []
        position: str = None

        for i in rows:
            # A header row with the player's position.
            if pos := "".join(i.xpath("./div/text()")).strip():
                try:
                    position = pos.strip("s")
                except IndexError:
                    position = pos
                continue  # There will not be additional data.

            player = Player()
            player.team = self
            player.position = position

            xpath = './/div[contains(@class, "cell--name")]/a/text()'
            name = "".join(i.xpath(xpath))
            try:  # Name comes in reverse order.
                surname, forename = name.split(" ", 1)
                name = f"{forename} {surname}"
            except ValueError:
                pass
            player.name = name

            # Set ID & 'url' from returned href.
            xpath = './/div[contains(@class, "cell--name")]/a/@href'
            if href := "".join(i.xpath(xpath)).split("/"):
                player.id = href[-1]
                player.url = href[-2]

            xpath = './/span[contains(@class,"flag")]/@title'
            player.country = "".join(i.xpath(xpath))

            xpath = './/span[contains(@class,"jersey")]/text()'
            player.number = "".join(i.xpath(xpath))

            xpath = './/span[contains(@class,"cell--age")]/text()'
            player.age = "".join(i.xpath(xpath))

            xpath = './/span[contains(@class,"cell--goal")]/text()'
            player.goals = "".join(i.xpath(xpath))

            xpath = './/span[contains(@class,"matchesPlayed")]/text()'
            player.apps = "".join(i.xpath(xpath))

            xpath = './/span[contains(@class,"yellowCard")]/text()'
            player.yellows = "".join(i.xpath(xpath))

            xpath = './/span[contains(@class,"redCard")]/text()'
            player.reds = "".join(i.xpath(xpath))

            xpath = './/span[contains(@title,"Injury")]/@title'
            player.injury = "".join(i.xpath(xpath))
            players.append(player)
        return players


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""

    __slots__ = {
        "country": "The country or region of the Competition",
        "score_embeds": "list of embeds of competition's score data",
        "_table": "A link to the table image.",
    }
    # Constant
    emoji: ClassVar[str] = "🏆"

    def __init__(
        self, fsid: str = None, link: str = None, name: str = None, **kwargs
    ) -> None:
        super().__init__(fsid=fsid, link=link, name=name)
        self.country: Optional[str] = kwargs.pop("country", None)
        self.logo_url: Optional[str] = kwargs.pop("logo_url", None)
        self.score_embeds: list[Embed] = []

        # Table Imagee
        self._table: str = None

    def __str__(self) -> str:
        return self.title

    @classmethod
    async def by_link(cls, bot: Bot, link: str) -> Competition:
        """Create a Competition Object from a flashscore url"""

        async with semaphore:
            try:
                page = await bot.browser.new_page()
                await page.goto(link, timeout=5000)

                await page.wait_for_selector(".heading")
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        try:
            xp = './/h2[@class="breadcrumb"]//a/text()'
            country = tree.xpath(xp)[-1].strip()

            xp = './/div[@class="heading__name"]//text()'
            name = tree.xpath(xp)[0].strip()
        except IndexError:
            name = "Unidentified League"
            country = None

        comp = cls()
        comp.url = link
        comp.country = country
        comp.name = name

        logo = tree.xpath('.//div[contains(@class,"__logo")]/@style')

        try:
            comp.logo_url = logo[0].split("(")[1].strip(")")
        except IndexError:
            if ".png" in logo:
                comp.logo_url = logo

        return comp

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return get_flag(self.country)

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        return f"{self.country.upper()}: {self.name}"

    @property
    def link(self) -> str:
        """Long form URL"""

        def fmt(string: str) -> str:
            """Format team/league into flashscore naming conventions."""
            string = string.lower()
            string = string.replace(" ", "-")
            string = string.replace(".", "")
            return string

        if not self.url:
            if self.country:
                name = fmt(self.name)
                return FLASHSCORE + f"football/{fmt(self.country)}/{name}"
        elif "://" not in self.url:
            if self.country:
                return FLASHSCORE + f"/football/{fmt(self.country)}/{self.url}"

        if self.id:
            return f"https://flashscore.com/?r=2:{self.id}"

    async def save_to_db(self) -> None:
        """Save the competition to the bot database"""
        async with self.bot.database.acquire(timeout=60) as c:
            async with c.transaction():
                q = """INSERT INTO fs_competitions
                       (id, country, name, logo_url, url)
                       VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING"""
                await c.execute(
                    q,
                    self.id,
                    self.country,
                    self.name,
                    self.logo_url,
                    self.url,
                )
        self.bot.competitions.append(self)

    async def table(self) -> Optional[str]:
        """Fetch the table from a flashscore Competition and return it as
        a BytesIO object"""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.link}/standings/", timeout=5000)
                if await (btn := page.locator("text=I Accept")).count():
                    await btn.click()

                loc = "#tournament-table-tabs-and-content > div:last-of-type"
                if not await (tbl := page.locator(loc)).count():
                    return None

                js = "ads => ads.forEach(x => x.remove());"
                await page.eval_on_selector_all(ADS, js)

                image = BytesIO(await tbl.screenshot())
                self._table = await self.bot.dump_image(image)
                return self._table
            finally:
                await page.close()

    async def scorers(self) -> list[Player]:
        """Fetch a list of scorers from a Flashscore Competition page
        returned as a list of Player Objects"""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.link}/standings/", timeout=5000)

                await page.wait_for_selector(".tabs__group", timeout=5000)
                top_scorers_button = page.locator("a.top_scorers")
                await top_scorers_button.wait_for(timeout=5000)
                await top_scorers_button.click()

                btn = page.locator(".showMore")
                for x in range(await (btn).count()):
                    await btn.nth(x).click()
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        scorers = []
        for i in tree.xpath('.//div[contains(@class,"table__body")]/div'):

            xp = './/span[contains(@class, "--sorting")]/text()'
            try:
                rank = int("".join(i.xpath(xp)).strip("."))
            except ValueError:
                continue

            player = Player(competition=self, rank=rank)

            xp = './/span[contains(@class,"flag")]/@title'
            player.country = "".join(i.xpath(xp)).strip()

            xp = './/div[contains(@class, "--player")]//text()'
            player.name = "".join(i.xpath(xp))

            xp = './/div[contains(@class, "--player")]//@href'
            player.url = FLASHSCORE + "".join(i.xpath(xp))

            xp = './/span[contains(@class, "--goals")]/text()'
            try:
                player.goals = int("".join(i.xpath(xp)))
            except ValueError:
                pass

            xp = './/span[contains(@class, "--gray")]/text()'
            try:
                player.assists = int("".join(i.xpath(xp)))
            except ValueError:
                pass

            team_url = FLASHSCORE + "".join(i.xpath("./a/@href"))
            team_id = team_url.split("/")[-2]

            if (team := self.bot.get_team(team_id)) is None:
                team = Team(self.bot, fs_id=team_id, competition=self)
                team.name = "".join(i.xpath(".//a/text()"))

            player.team = team

            scorers.append(player)
        return scorers

    @property
    def table_link(self) -> str:
        """Return [Click To View Table](url) or empty string if not found"""
        return f"\n[View Table]({self._table})" if self._table else ""


class Fixture(FlashScoreItem):
    """An object representing a Fixture from the Flashscore Website"""

    __slots__ = [
        "kickoff",
        "competition",
        "referee",
        "stadium",
        "home",
        "away",
        "periods",
        "breaks",
        "_score_home",
        "_score_away",
        "_cards_home",
        "_cards_away",
        "events",
        "penalties_home",
        "penalties_away",
        "attendance",
        "infobox",
        "_time",
        "images",
        "ordinal",
    ]

    emoji: ClassVar[str] = "⚽"

    def __init__(self, fs_id: str = None) -> None:
        super().__init__(fs_id)

        self.away: Optional[Team] = None
        self._cards_away: Optional[int] = None
        self._score_away: Optional[int] = None
        self.penalties_away: Optional[int] = None

        self.home: Optional[Team] = None
        self._cards_home: Optional[int] = None
        self._score_home: Optional[int] = None
        self.penalties_home: Optional[int] = None
        self._time: str | GameState = None

        self.attendance: Optional[int] = None
        self.breaks: int = 0
        self.competition: Optional[Competition] = None
        self.events: list[MatchEvent] = []
        self.infobox: Optional[str] = None
        self.images: Optional[list[str]] = None
        self.kickoff: Optional[datetime] = None
        self.ordinal: Optional[int] = None

        self.periods: Optional[int] = None
        self.referee: Optional[str] = None
        self.stadium: Optional[str] = None

    def __str__(self) -> str:
        match self.time:
            case (
                GameState.LIVE | GameState.STOPPAGE_TIME | GameState.EXTRA_TIME
            ):
                time = self.state.name
            case GameState():
                time = self.ko_relative
            case _:
                time = self.time

        return f"{time}: {self.bold_markdown}"

    def active(self, ordinal: int) -> bool:
        """Is this game still valid"""
        if self.ordinal is None:
            if self.kickoff is None:
                self.ordinal = ordinal
            else:
                self.ordinal = self.kickoff.toordinal()
        return bool(ordinal <= self.ordinal)

    @property
    def time(self) -> str | GameState:
        """Get the current GameTime of a fixture"""
        return self._time

    @property
    def state(self) -> GameState:
        """Get a GameState value from stored _time"""
        if isinstance(self._time, str):
            if "+" in self._time:
                return GameState.STOPPAGE_TIME
            else:
                return GameState.LIVE
        else:
            return self._time

    @property
    def upcoming(self) -> str:
        """Format for upcoming games in /fixtures command"""
        return f"{Timestamp(self.kickoff).relative}: {self.bold_markdown}"

    @time.setter
    def time(self, new_time: str | GameState) -> None:
        """Update the time of the event"""
        if isinstance(new_time, str):
            if isinstance(self._time, GameState):
                self.dispatch_events(self._time, new_time)
        else:
            if new_time != self._time:
                self.dispatch_events(self._time, new_time)
        self._time = new_time

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if self.kickoff is None:
            return ""

        if self.kickoff.date == (now := datetime.now(tz=timezone.utc)).date:
            # If the match is today, return HH:MM
            return Timestamp(self.kickoff).time_hour
            # if a different year, return DD/MM/YYYY
        elif self.kickoff.year != now.year:
            return Timestamp(self.kickoff).date
        elif self.kickoff > now:  # For Upcoming
            return Timestamp(self.kickoff).date_long
        else:
            return Timestamp(self.kickoff).date_relative

    @property
    def score(self) -> str:
        """Return "X - Y", or 'vs' if scores are None"""
        if self.score_home is None:
            return "vs"
        else:
            return f"{self.score_home} - {self.score_away}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.name} {self.score} {self.away.name}"

    @property
    def bold_score(self) -> str:
        """Embolden the winning team of a fixture"""
        if None in [self.score_home, self.time]:
            return f"{self.home.name} vs {self.away.name}"
        if self.time == GameState.SCHEDULED:
            return f"{self.home.name} vs {self.away.name}"

        home = f"{self.home.name} {self.score_home}"
        away = f"{self.score_away} {self.away.name}"

        if self.score_home > self.score_away:
            home = f"**{home}**"
        elif self.score_away > self.score_home:
            away = f"**{away}**"

        return f"{home} - {away}"

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold **winning** team, with
        [score](as markdown link)."""
        if None in [self.score_home, self.time]:
            return f"[{self.home.name} vs {self.away.name}]({self.link})"
        if self.time == GameState.SCHEDULED:
            return f"[{self.home.name} vs {self.away.name}]({self.link})"

        home = self.home.name
        away = self.away.name
        # Embolden Winner
        if self.score_home > self.score_away:
            home = f"**{home}**"
        if self.score_away > self.score_home:
            away = f"**{away}**"

        def parse_cards(cards: int) -> str:
            """Get a number of icons matching number of cards"""
            match cards:
                case 0 | None:
                    return ""
                case 1:
                    return "`🟥` "
                case _:
                    return f"`🟥 x{cards}` "

        sh, sa = self.score_home, self.score_away
        hc = parse_cards(self.cards_home)
        ac = parse_cards(self.cards_away)
        return f"{home} {hc}[{sh} - {sa}]({self.link}){ac} {away}"

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output = []
        if self._time is not None:
            output.append(f"`{self.state.emote}")

            match self.time:
                case (
                    GameState.STOPPAGE_TIME
                    | GameState.EXTRA_TIME
                    | GameState.LIVE
                ):
                    output.append(f"{self.state.value}`")
                case _:
                    output.append(f"{self.state.shorthand}`")

        h = self.home.name
        a = self.away.name

        # Penalty Shootout
        if self.penalties_home is not None:
            ph, pa = self.penalties_home, self.penalties_away
            s = min(self.score_home, self.score_away)

            output.append(f"{h} [{s} - {s}]({self.link}) (p: {ph} - {pa}) {a}")
            return " ".join(output)

        if self._score_home is None:
            time = Timestamp(self.kickoff).time_hour
            output.append(f"{time} [{h} v {a}]({self.link})")
        else:
            output.append(self.bold_markdown)
        return " ".join(output)

    @property
    def autocomplete(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        title = self.competition.title
        return f"⚽ {self.home.name} {self.score} {self.away.name} ({title})"

    def _update_score(
        self, variable: Literal["_score_home", "_score_away"], value: int
    ):
        """Set a score value."""
        if value is None:
            return

        old_value = getattr(self, variable, None)
        setattr(self, variable, value)
        if old_value in [value, None]:
            return

        event = EventType.GOAL if value > old_value else EventType.VAR_GOAL

        is_home = bool(variable == "_score_home")
        self.bot.dispatch("fixture_event", event, self, home=is_home)

    @property
    def score_home(self) -> int:
        """Get the score of the home team"""
        return self._score_home

    @score_home.setter
    def score_home(self, value: int) -> None:
        """Set the score of the home team"""
        self._update_score("_score_home", value)

    @property
    def score_away(self) -> int:
        """Get the current score of the away team"""
        return self._score_away

    @score_away.setter
    def score_away(self, value: int) -> None:
        """Set the score of the away team"""
        self._update_score("_score_away", value)

    def _update_cards(self, variable: str, value: int):
        """Set a team's cards."""
        if value is None:
            return

        old_value = getattr(self, variable, None)
        setattr(self, variable, value)
        if old_value in [value, None]:
            return

        if value > old_value:
            event = EventType.RED_CARD
        else:
            event = EventType.VAR_RED_CARD

        home = bool(variable == "_cards_home")
        self.bot.dispatch("fixture_event", event, self, home=home)
        return

    @property
    def cards_home(self) -> int:
        """Get the current number of red cards of the Home team"""
        return self._cards_home

    @property
    def cards_away(self) -> int:
        """Get the number of red cards of the away team"""
        return self._cards_away

    @cards_home.setter
    def cards_home(self, value: int) -> None:
        """Update red cards & dispatch event."""
        self._update_cards("_cards_home", value)

    @cards_away.setter
    def cards_away(self, value: int) -> None:
        """Update red cards & dispatch event."""
        self._update_cards("_cards_away", value)

    async def base_embed(self) -> Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e: Embed = await self.competition.base_embed()
        e.url = self.link
        e.colour = self.state.colour
        e.set_author(name=self.score_line)
        e.timestamp = self.kickoff
        e.description = ""

        if self.infobox is not None:
            e.add_field(name="Match Info", value=self.infobox)

        if self.time is None:
            return e

        match self.time:
            case GameState.SCHEDULED:
                time = Timestamp(self.kickoff).time_relative
                e.description = f"Kickoff: {time}"
            case GameState.POSTPONED:
                e.description = "This match has been postponed."
        e.set_footer(text=f"{self.time} - {self.competition.title}")
        return e

    # Dispatcher
    def dispatch_events(self, old: GameState, new: GameState) -> None:
        """Dispatch events to the ticker"""
        fix = "fixture_event"
        dispatch = self.bot.dispatch
        match new:
            case GameState.ABANDONED:
                return dispatch(fix, EventType.ABANDONED, self)
            case GameState.AFTER_EXTRA_TIME:
                return dispatch(fix, EventType.SCORE_AFTER_EXTRA_TIME, self)
            case GameState.AFTER_PENS:
                return dispatch(fix, EventType.PENALTY_RESULTS, self)
            case GameState.BREAK_TIME:
                match old:
                    # Break Time = after regular time & before penalties
                    case GameState.EXTRA_TIME:
                        return dispatch(fix, EventType.EXTRA_TIME_END, self)
                    case _:
                        self.breaks += 1
                        if self.periods is not None:
                            event = EventType.PERIOD_END
                        else:
                            event = EventType.NORMAL_TIME_END
                        return dispatch(fix, event, self)
            case GameState.CANCELLED:
                return dispatch(fix, EventType.CANCELLED, self)
            case GameState.DELAYED:
                return dispatch(fix, EventType.DELAYED, self)
            case GameState.EXTRA_TIME:
                match old:
                    case GameState.HALF_TIME:
                        return dispatch(fix, EventType.HALF_TIME_ET_END, self)
                    case _:
                        return dispatch(fix, EventType.EXTRA_TIME_BEGIN, self)
            case GameState.FULL_TIME:
                match old:
                    case GameState.EXTRA_TIME:
                        return dispatch(
                            fix, EventType.SCORE_AFTER_EXTRA_TIME, self
                        )
                    case GameState.SCHEDULED | GameState.HALF_TIME:
                        return dispatch(fix, EventType.FINAL_RESULT_ONLY, self)
                    case _:
                        return dispatch(fix, EventType.FULL_TIME, self)
            case GameState.HALF_TIME:
                # Half Time is fired at regular Half time & ET Half time.
                if old == GameState.EXTRA_TIME:
                    return dispatch(fix, EventType.HALF_TIME_ET_BEGIN, self)
                else:
                    return dispatch(fix, EventType.HALF_TIME, self)
            case GameState.INTERRUPTED:
                return dispatch(fix, EventType.INTERRUPTED, self)
            case GameState.LIVE:
                match old:
                    case GameState.SCHEDULED | GameState.DELAYED:
                        # Match has resumed
                        return dispatch(fix, EventType.KICK_OFF, self)
                    case GameState.INTERRUPTED:
                        return dispatch(fix, EventType.RESUMED, self)
                    case GameState.HALF_TIME:
                        return dispatch(fix, EventType.SECOND_HALF_BEGIN, self)
                    case GameState.BREAK_TIME:
                        return dispatch(fix, EventType.PERIOD_BEGIN, self)
            case GameState.PENALTIES:
                return dispatch(fix, EventType.PENALTIES_BEGIN, self)
            case GameState.POSTPONED:
                return dispatch(fix, EventType.POSTPONED, self)
            case GameState.STOPPAGE_TIME:
                return

        logger.error(f"Handle State: {old} -> {new} {self.url} @ {self.time}")

    # High Cost lookups.
    async def refresh(self) -> None:
        """Perform an intensive full lookup for a fixture"""

        async with semaphore:
            page = await self.bot.browser.new_page()

            try:
                await page.goto(self.link, timeout=5000)
                await page.locator(".container__detail").wait_for(timeout=5000)
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        # Some of these will only need updating once per match
        if self.kickoff is None:
            xpath = ".//div[contains(@class, 'startTime')]/div/text()"
            ko = "".join(tree.xpath(xpath))
            self.kickoff = datetime.strptime(ko, "%d.%m.%Y %H:%M").astimezone()

        if None in [self.referee, self.stadium]:
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')
            if ref := "".join([i for i in text if "referee" in i.lower()]):
                self.referee = ref.strip().replace("Referee:", "")
            if venue := "".join([i for i in text if "venue" in i.lower()]):
                self.stadium = venue.strip().replace("Venue:", "")

        if None in [self.competition, self.competition.url]:
            xpath = './/span[contains(@class, "__country")]//a/@href'
            href = "".join(tree.xpath(xpath))

            xpath = './/span[contains(@class, "__country")]/text()'
            country = "".join(tree.xpath(xpath)).strip()

            xpath = './/span[contains(@class, "__country")]/a/text()'
            name = "".join(tree.xpath(xpath)).strip()

            if href:
                comp_id = href.split("/")[-1]
                comp = self.bot.get_competition(comp_id)
            else:
                for c in self.bot.competitions:
                    if c.name.lower() == name.lower():
                        if c.country.lower() == country.lower():
                            comp = c
                            break
                else:
                    comp = None

            if not comp:
                comp = Competition()
                comp.name = name
                comp.country = country
                comp.url = href

            self.competition = comp

        # Grab infobox
        xpath = (
            './/div[contains(@class, "infoBoxModule")]'
            '/div[contains(@class, "info__")]/text()'
        )
        if infobox := tree.xpath(xpath):
            self.infobox = "".join(infobox)
            if self.infobox.startswith("Format:"):
                self.periods = int(self.infobox.split(": ")[-1].split("x")[0])

        self.events = parse_events(self, tree)
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')


class Player(FlashScoreItem):
    """An object representing a player from flashscore."""

    __slots__ = (
        "number",
        "position",
        "country",
        "team",
        "competition",
        "age",
        "apps",
        "goals",
        "assists",
        "rank",
        "yellows",
        "reds",
        "injury",
    )

    def __init__(
        self, fs_id: str = None, name: str = None, link: str = None, **kwargs
    ) -> None:

        super().__init__(fs_id, link=link, name=name)

        self.number: int | None = kwargs.pop("number", None)
        self.position: str | None = kwargs.pop("position", None)
        self.country: list[str] | None = kwargs.pop("country", None)
        self.team: Team | None = kwargs.pop("team", None)
        self.competition: Competition | None = kwargs.pop("competition", None)
        self.age: int | None = kwargs.pop("age", None)
        self.apps: int | None = kwargs.pop("apps", None)
        self.goals: int | None = kwargs.pop("goals", None)
        self.assists: int | None = kwargs.pop("assists", None)
        self.rank: int | None = kwargs.pop("rank", None)
        self.yellows: int | None = kwargs.pop("yellows", None)
        self.reds: int | None = kwargs.pop("reds", None)
        self.injury: str | None = kwargs.pop("injury", None)

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return get_flag(self.country)

    @property
    def link(self) -> str:
        """Alias to self.url"""
        if "https://" in self.url:
            return self.url
        else:
            return FLASHSCORE + self.url

    @property
    def squad_row(self) -> str:
        """String for Team Lineup."""
        match self.number:
            case 0, None:
                output = ["`  `:"]
            case _:
                output = [f"`{str(self.number).rjust(2)}`:"]

        if self.flag:
            output.append(self.flag)
        output.append(self.markdown)

        if self.position is not None:
            output.append(self.position)

        if self.injury is not None:
            output.append(INJURY_EMOJI)
            output.append(self.injury)

        return " ".join(output)

    @property
    def scorer_row(self) -> str:
        """Return a preformatted string showing information about
        Player's Goals & Assists"""
        rank = "" if self.rank is None else (str(self.rank).rjust(3, " "))
        team = "" if self.team is None else self.team.markdown + " "

        match self.goals:
            case None:
                gol = ""
            case 1:
                gol = "1 Goal "
            case _:
                gol = f"{self.goals} Goals "

        match self.assists:
            case None:
                ass = ""
            case 1:
                ass = "1 Assist"
            case _:
                ass = f"{self.assists} Assists"
        return f"{rank} {self.flag} **{self.markdown}** {team}{gol}{ass}"

    @property
    def assist_row(self) -> str:
        """Return a preformatted string showing information about
        Player's Goals & Assists"""
        tm = "" if self.team is None else self.team.markdown + " "
        match self.goals:
            case None:
                gol = ""
            case 1:
                gol = "1 Goal "
            case _:
                gol = f"{self.goals} Goals "

        match self.assists:
            case None:
                ass = ""
            case 1:
                ass = "1 Assist"
            case _:
                ass = f"{self.assists} Assists"
        return f"{self.flag} **{self.markdown}** {tm}{ass}{gol}"

    @property
    def injury_row(self) -> str:
        """Return a string with player & their injury"""
        if self.injury is None:
            return ""
        pos = f"({self.position})" if self.position is not None else ""
        return f"{self.flag} {self.markdown} {pos} {INJURY_EMOJI}{self.injury}"

    @property
    async def fixtures(self) -> list[Fixture]:
        """Get from player's team instead."""
        if self.team is None:
            return []
        return await self.team.fixtures()


class NewsItem:
    """A generic item representing a News Article for a team."""

    __slots__ = [
        "title",
        "url",
        "blurb",
        "source",
        "image_url",
        "team_embed",
        "time",
    ]

    def __init__(self, **kwargs) -> None:
        self.title: Optional[str] = kwargs.pop("title", None)
        self.url: Optional[str] = kwargs.pop("url", None)
        self.blurb: Optional[str] = kwargs.pop("blurb", None)
        self.source: Optional[str] = kwargs.pop("source", None)
        self.time: Optional[datetime] = kwargs.pop("time", None)
        self.image_url: Optional[str] = kwargs.pop("image_url", None)
        self.team_embed: Optional[Embed] = kwargs.pop("team_embed", None)

    @property
    def embed(self) -> Embed:
        """Return an Embed representing the News Article"""
        e = self.team_embed
        e.title = self.title
        e.url = self.url
        e.set_image(url=self.image_url)
        e.description = self.blurb
        e.set_footer(text=self.source)
        e.timestamp = self.time
        return e
