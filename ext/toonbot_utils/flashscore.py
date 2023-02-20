"""A Utility tool for fetching and structuring data from the Flashscore Website"""
from __future__ import annotations  # Cyclic Type Hinting

import builtins
import logging
from asyncio import Semaphore
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from json import loads
from typing import TYPE_CHECKING, Literal, Optional, ClassVar
from urllib.parse import quote

from discord import Embed, Interaction, Message, Colour
from discord.app_commands import Choice
from lxml import html
from playwright.async_api import Page, TimeoutError

from ext.toonbot_utils.gamestate import GameState, GameTime
from ext.toonbot_utils.matchevents import EventType
from ext.toonbot_utils.matchevents import parse_events
from ext.utils.embed_utils import get_colour
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import ObjectSelectView

if TYPE_CHECKING:
    from ext.toonbot_utils.matchevents import MatchEvent
    from core import Bot

# TODO: Figure out caching system for high intensity lookups
# TODO: Team dropdown on Competitions

ADS = ('.ads-envelope, '
       '.bannerEnvelope, '
       '.banner--sticky, '
       '.extraContent, '
       '.seoAdWrapper, '
       '.isSticky, '
       '.ot-sdk-container, '
       '.otPlaceholder, '
       '.onetrust-consent-sdk, '
       '.rollbar, '
       '.selfPromo, '
       '#box-over-content, '
       '#box-over-content-detail, '
       '#box-over-content-a,'
       '#lsid-window-mask'
       )

FLASHSCORE = 'https://www.flashscore.com'
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
    "USA: MLS"
]
WORLD_CUP_LEAGUES = [
    "EUROPE: World Cup",
    "ASIA: World Cup",
    "AFRICA: World Cup",
    "NORTH & CENTRAL AMERICA: World Cup",
    "SOUTH AMERICA: World Cup"
]

semaphore = Semaphore(5)


# Competition Autocomplete
async def lg_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete from list of stored leagues"""
    bot: Bot = interaction.client
    matches = [i for i in bot.competitions if current.lower() in i.title.lower() and i.id is not None]
    return [Choice(name=i.title[:100], value=i.id) for i in list(matches)[:25]]


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""
    bot: ClassVar[Bot] = None

    __slots__ = ['id', 'url', 'name', 'embed_colour', 'logo_url']

    def __init__(self, bot: Bot, flashscore_id: str = None, name: str = None, link: str = None):
        self.id: Optional[str] = flashscore_id
        self.url: Optional[str] = link
        self.name: Optional[str] = name
        self.embed_colour: Optional[Colour] = None
        self.logo_url: Optional[str] = None

        self.__class__.bot = bot

    def __hash__(self) -> hash:
        return hash(repr(self))

    def __repr__(self) -> repr:
        return f"FlashScoreItem(id:{self.id} url: {self.url}, {self.name}, {self.logo_url})"

    def __eq__(self, other: FlashScoreItem):
        if None not in [self.id, other]:
            return self.id == other.id

        if None not in [self.link, other]:
            return self.link == other.link

        if hasattr(self, 'title') and hasattr(other, 'title'):
            return self.title == other.title

    @property
    def markdown(self) -> str:
        """Shorthand for FSR mark-down link"""
        name = 'Unidentified FlashScoreItem' if self.name is None else self.name
        if self.link is not None:
            return f"[{name}]({self.link})"
        return name

    @property
    def link(self) -> str:
        """Alias to self.url, polymorph for subclasses."""
        return self.url

    @property
    async def base_embed(self) -> Embed:
        """A discord Embed representing the flashscore search result"""
        e: Embed = Embed(title=self.title if hasattr(self, 'title') else self.name, url=self.link)
        e.description = ""
        if self.logo_url is not None:
            if "flashscore" in self.logo_url:
                logo = self.logo_url
            else:
                logo = "https://www.flashscore.com/res/image/data/" + self.logo_url.replace("'", "")  # Extraneous '

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
                for x in range(3):
                    try:
                        await page.goto(link, timeout=5000)
                        break
                    except TimeoutError:
                        return await self.parse_games(link)
                else:
                    return []

                try:
                    await page.wait_for_selector('.sportName.soccer', timeout=5000)
                except TimeoutError:
                    return []

                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        fixtures: list[Fixture] = []
        comp = self if isinstance(self, Competition) else None

        if not (games := tree.xpath('..//div[contains(@class, "sportName soccer")]/div')):
            raise LookupError(f'No fixtures found on {link}')

        for i in games:
            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
                url = "https://www.flashscore.com/match/" + fx_id
            except IndexError:
                # This (might be) a header row.
                if "event__header" in i.classes:
                    country, league = i.xpath('.//div[contains(@class, "event__title")]//text()')
                    league = league.split(' - ')[0]

                    for x in self.bot.competitions:
                        if x.name.lower() == league.lower().split(' -')[0] and x.country.lower() == country.lower():
                            comp = x
                            break
                    else:
                        comp = Competition(self.bot)
                        comp.country = country
                        comp.name = league
                continue

            fixture = Fixture(self.bot, fx_id)
            fixture.competition = comp
            fixture.url = url

            # score
            home, away = i.xpath('.//div[contains(@class,"event__participant")]/text()')
            fixture.home = Team(self.bot)
            fixture.home.name = home.strip()
            fixture.away = Team(self.bot)
            fixture.away.name = away.strip()

            try:
                score_home, score_away = i.xpath('.//div[contains(@class,"event__score")]//text()')

                # Directly access the private var, so we don't dispatch events.
                fixture._score_home = int(score_home.strip())
                fixture._score_away = int(score_away.strip())
            except ValueError:
                pass

            parsed = ''.join(i.xpath('.//div[@class="event__time"]//text()'))
            state = None

            # State Corrections
            override = "".join([i for i in parsed if i.isalpha()])
            parsed = parsed.replace(override, '')

            match override:
                case '':
                    pass
                case 'AET':
                    state = GameState.AFTER_EXTRA_TIME
                case 'Pen':
                    state = GameState.AFTER_PENS
                case 'Postp':
                    state = GameState.POSTPONED
                case 'FRO':
                    state = GameState.FINAL_RESULT_ONLY
                case 'WO':
                    state = GameState.WALKOVER
                case 'Awrd':
                    state = GameState.AWARDED
                case 'Postp':
                    state = GameState.POSTPONED
                case 'Abn':
                    state = GameState.ABANDONED

            dtn = datetime.now(tz=timezone.utc)
            for string, fmt in [(parsed, '%d.%m.%Y.'),
                                (parsed, '%d.%m.%Y'),
                                (f"{dtn.year}.{parsed}", '%Y.%d.%m. %H:%M'),
                                (f"{dtn.year}.{dtn.day}.{dtn.month}.{parsed}", '%Y.%d.%m.%H:%M')]:
                try:
                    fixture.kickoff = datetime.strptime(string, fmt).astimezone()
                    break
                except ValueError:
                    continue
            else:
                logging.error(f'Unable to convert string {parsed} into datetime object.')

            if state is None:
                if fixture.kickoff > datetime.now(tz=timezone.utc):
                    state = GameState.SCHEDULED
                else:
                    state = GameState.FULL_TIME

            match state:
                case GameState():
                    fixture.time = GameTime(state)
                case datetime():
                    fixture.time = GameTime(GameState.FULL_TIME if fixture.kickoff < dtn else GameState.SCHEDULED)
                case _:
                    if "'" in parsed or "+" in parsed or parsed.isdigit():
                        fixture.time = GameTime(parsed)
                    else:
                        logging.error(f'state "{state}" not handled in parse_games {parsed}')
            fixtures.append(fixture)
        return fixtures

    async def fixtures(self) -> list[Fixture]:
        """Get all upcoming fixtures related to the FlashScoreItem"""
        return await self.parse_games(self.link + '/fixtures/')

    async def results(self) -> list[Fixture]:
        """Get recent results for the FlashScore Item"""
        return await self.parse_games(self.link + '/results/')


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""
    __slots__ = {'competition': 'The competition the team belongs to',
                 'logo_url': "A link to a logo representing the competition"}

    # Constant
    emoji: ClassVar[str] = '👕'

    def __init__(self, bot: Bot, flashscore_id: str = None, name: str = None, link: str = None, **kwargs):
        super().__init__(bot, flashscore_id, name, link)
        self.competition: Optional[Competition] = kwargs.pop('competition', None)

    def __str__(self) -> str:
        output = self.name

        if self.competition is not None:
            output = f"{output} ({self.competition.title})"

        return output

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        match len(self.name.split(' ')):
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

        # Example Team URL: https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        return f"https://www.flashscore.com/team/{self.url}/{self.id}"

    @classmethod
    async def by_id(cls, bot: Bot, team_id: str) -> Optional[Team]:
        """Create a Team object from it's Flashscore ID"""
        async with semaphore:
            page = await bot.browser.new_page()
            try:
                await page.goto(f"https://flashscore.com/?r=3:{team_id}", timeout=5000)
                url = await page.evaluate("() => window.location.href")
                obj = cls(bot, link=url, flashscore_id=team_id)
                return obj
            finally:
                await page.close()

    async def save_to_db(self) -> None:
        """Save the Team to the Bot Database"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO fs_teams (id, name, logo_url, url) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.id, self.name, self.logo_url, self.url)
        self.bot.teams.append(self)

    async def news(self) -> list[Embed]:
        """Get a list of news articles related to a team in embed format"""
        page = await self.bot.browser.new_page()
        try:
            for x in range(3):
                try:
                    await page.goto(f"{self.link}/news", timeout=5000)
                    break
                except TimeoutError:
                    continue
            else:
                return []

            try:
                await page.wait_for_selector('.matchBox', timeout=5000)
            except TimeoutError:
                return []

            tree = html.fromstring(await page.content())
        finally:
            await page.close()

        items = []
        base_embed = await self.base_embed
        for i in tree.xpath('.//div[@id="tab-match-newsfeed"]'):
            article = NewsItem(team_embed=deepcopy(base_embed))
            article.title = "".join(i.xpath('.//div[@class="rssNews__title"]/text()'))
            article.image_url = "".join(i.xpath('.//img/@src'))
            article.url = "https://www.flashscore.com" + "".join(i.xpath('.//a[@class="rssNews__titleAndPerex"]/@href'))
            article.blurb = "".join(i.xpath('.//div[@class="rssNews__perex"]/text()'))
            provider = "".join(i.xpath('.//div[@class="rssNews__provider"]/text()')).split(',')

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
                    await page.wait_for_selector('.squad-table.profileTable', timeout=5000)
                except TimeoutError:
                    return []

                if await (btn := page.locator('text="Total"')).count():
                    await btn.click()

                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        # tab += 1  # tab is Indexed at 0 but xpath indexes from [1]
        rows = tree.xpath(f'.//div[contains(@class, "squad-table")][contains(@id, "overall-all-table")]'
                          f'//div[contains(@class,"profileTable__row")]')

        players = []
        position: str = None

        for i in rows:
            if pos := ''.join(i.xpath('./div/text()')).strip():  # A header row with the player's position.
                try:
                    position = pos.strip('s')
                except IndexError:
                    position = pos
                continue  # There will not be additional data.

            player = Player(self.bot)
            player.team = self
            player.position = position

            name = ''.join(i.xpath('.//div[contains(@class, "cell--name")]/a/text()'))
            try:  # Name comes in reverse order.
                surname, forename = name.split(' ', 1)
                name = f"{forename} {surname}"
            except ValueError:
                pass
            player.name = name

            # Set ID & 'url' from returned href.
            if href := ''.join(i.xpath('.//div[contains(@class, "cell--name")]/a/@href')).split('/'):
                player.id = href[-1]
                player.url = href[-2]

            player.country = "".join(i.xpath('.//span[contains(@class,"flag")]/@title'))
            player.number = ''.join(i.xpath('.//span[contains(@class,"jersey")]/text()'))
            player.age = ''.join(i.xpath('.//span[contains(@class,"cell--age")]/text()'))
            player.goals = ''.join(i.xpath('.//span[contains(@class,"cell--goal")]/text()'))
            player.apps = ''.join(i.xpath('.//span[contains(@class,"matchesPlayed")]/text()'))
            player.yellows = ''.join(i.xpath('.//span[contains(@class,"yellowCard")]/text()'))
            player.reds = ''.join(i.xpath('.//span[contains(@class,"redCard")]/text()'))
            player.injury = ''.join(i.xpath('.//span[contains(@title,"Injury")]/@title'))
            players.append(player)
        return players


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""
    __slots__ = {'country': "The country or region the Competition takes place in",
                 'score_embeds': "A list of Embed objects representing this competition's score data",
                 '_table': 'A link to the table image.'}
    # Constant
    emoji: ClassVar[str] = '🏆'

    def __init__(self, bot: Bot, flashscore_id: str = None, link: str = None, name: str = None, **kwargs) -> None:
        super().__init__(bot, flashscore_id=flashscore_id, link=link, name=name)
        self.country: Optional[str] = kwargs.pop('country', None)
        self.logo_url: Optional[str] = kwargs.pop('logo_url', None)
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
            country = tree.xpath('.//h2[@class="breadcrumb"]//a/text()')[-1].strip()
            name = tree.xpath('.//div[@class="heading__name"]//text()')[0].strip()
        except IndexError:
            name = "Unidentified League"
            country = None

        comp = cls(bot)
        comp.url = link
        comp.country = country
        comp.name = name

        logo = tree.xpath('.//div[contains(@class,"__logo")]/@style')

        try:
            comp.logo_url = logo[0].split("(")[1].strip(')')
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
            string = string.replace(' ', '-')
            string = string.replace('.', '')
            return string

        if not self.url:
            if self.country:
                return f"https://www.flashscore.com/football/{fmt(self.country)}/{fmt(self.name)}"
        elif "://" not in self.url:
            if self.country:
                return f"https://www.flashscore.com/football/{fmt(self.country)}/{self.url}"

        if self.id:
            return f"https://flashscore.com/?r=2:{self.id}"

    async def save_to_db(self) -> None:
        """Save the competition to the bot database"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO fs_competitions (id, country, name, logo_url, url) 
                    VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.id, self.country, self.name, self.logo_url, self.url)
        self.bot.competitions.append(self)

    async def table(self) -> Optional[str]:
        """Fetch the table from a flashscore Competition and return it as a BytesIO object"""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                for x in range(3):
                    try:
                        await page.goto(f"{self.link}/standings/", timeout=5000)
                        break
                    except TimeoutError:
                        continue
                else:
                    return None

                if await (btn := page.locator('text=I Accept')).count():
                    await btn.click()

                if not await (tbl := page.locator('#tournament-table-tabs-and-content > div:last-of-type')).count():
                    return None

                await page.eval_on_selector_all(ADS, "ads => ads.forEach(x => x.remove());")
                self._table = await self.bot.dump_image(BytesIO(await tbl.screenshot()))
                return self._table
            finally:
                await page.close()

    async def scorers(self) -> list[Player]:
        """Fetch a list of scorers from a Flashscore Competition page returned as a list of Player Objects"""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                for x in range(3):
                    try:
                        await page.goto(f"{self.link}/standings/", timeout=5000)
                        break
                    except TimeoutError:
                        continue
                else:
                    return []

                try:
                    await page.wait_for_selector('.tabs__group', timeout=5000)
                    top_scorers_button = page.locator('a.top_scorers')
                    await top_scorers_button.wait_for(timeout=5000)
                    await top_scorers_button.click()
                except TimeoutError:
                    return []

                for x in range(10):
                    locator = page.locator('.showMore')
                    if await locator.count():
                        await locator.click()  # Click to go to scorers tab
                        continue
                    break
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        scorers = []
        for i in tree.xpath('.//div[contains(@class,"table__body")]/div'):
            try:
                rank = int("".join(i.xpath('.//span[contains(@class, "--sorting")]/text()')).strip('.'))
            except ValueError:
                continue

            player = Player(self.bot, competition=self, rank=rank)
            player.country = ''.join(i.xpath('.//span[contains(@class,"flag")]/@title')).strip()
            player.name = "".join(i.xpath('.//div[contains(@class, "--player")]//text()'))
            player.url = FLASHSCORE + "".join(i.xpath('.//div[contains(@class, "--player")]//@href'))

            try:
                player.goals = int("".join(i.xpath('.//span[contains(@class, "--goals")]/text()')))
            except ValueError:
                pass

            try:
                player.assists = int("".join(i.xpath('.//span[contains(@class, "--gray")]/text()')))
            except ValueError:
                pass

            team_url = FLASHSCORE + "".join(i.xpath('./a/@href'))
            team_id = team_url.split('/')[-2]

            if (team := self.bot.get_team(team_id)) is None:
                team = Team(self.bot, flashscore_id=team_id, competition=self)
                team.name = "".join(i.xpath('.//a/text()'))

            player.team = team

            scorers.append(player)
        return scorers

    @property
    def table_link(self) -> str:
        """Return [Click To View Table](url) or empty string if not found"""
        return f"\n[View Table]({self._table})" if self._table else ''


class Fixture(FlashScoreItem):
    """An object representing a Fixture from the Flashscore Website"""
    __slots__ = 'kickoff', 'competition', 'referee', 'stadium', 'home', 'away', 'periods', 'breaks', '_score_home', \
                '_score_away', '_cards_home', '_cards_away', 'events', 'penalties_home', 'penalties_away', \
                'attendance', 'infobox', '_time', 'images', 'ordinal'

    emoji: ClassVar[str] = '⚽'

    def __init__(self, bot: Bot, flashscore_id: str = None) -> None:
        super().__init__(bot, flashscore_id=flashscore_id)

        self.away: Optional[Team] = None
        self._cards_away: Optional[int] = None
        self._score_away: Optional[int] = None
        self.penalties_away: Optional[int] = None

        self.home: Optional[Team] = None
        self._cards_home: Optional[int] = None
        self._score_home: Optional[int] = None
        self.penalties_home: Optional[int] = None
        self._time: Optional[GameTime] = None

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
        match self.time.state:
            case GameState.LIVE | GameState.STOPPAGE_TIME | GameState.EXTRA_TIME:
                time = self.time.value
            case GameState():
                time = self.ko_relative
            case _:
                time = self.time.state

        return f"{time}: {self.bold_markdown}"

    def active(self, ordinal: int) -> bool:
        """Is this game still valid"""
        if ordinal == self.ordinal:
            return True

        if self.ordinal is None:
            if self.kickoff is None:
                self.ordinal = ordinal
            else:
                self.ordinal = self.kickoff.toordinal()
            return True

        if self.ordinal + 1 > ordinal:
            return False

        match self.time.state:
            case GameState.POSTPONED | GameState.CANCELLED:
                return False
            case GameState.AFTER_PENS | GameState.FINAL_RESULT_ONLY | GameState.FULL_TIME | GameState.AFTER_EXTRA_TIME:
                return False
        return True

    @property
    def time(self) -> GameTime:
        """Get the current GameTime of a fixture"""
        return self._time

    @property
    def upcoming(self) -> str:
        """Format for upcoming games in /fixtures command"""
        return f"{Timestamp(self.kickoff).relative}: {self.bold_markdown}"

    @time.setter
    def time(self, game_time: GameTime) -> None:
        """Update the time of the event"""
        if self._time is not None:
            if (old_state := self._time.state) != (new_state := game_time.state):
                self.dispatch_events(old_state, new_state)
        self._time = game_time

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if self.kickoff is None:
            return ""

        if self.kickoff.date == (now := datetime.now(tz=timezone.utc)).date:  # If the match is today, return HH:MM
            return Timestamp(self.kickoff).time_hour
        elif self.kickoff.year != now.year:  # if a different year, return DD/MM/YYYY
            return Timestamp(self.kickoff).date
        elif self.kickoff > now:  # For Upcoming
            return Timestamp(self.kickoff).date_long
        else:
            return Timestamp(self.kickoff).date_relative

    @property
    def score(self) -> str:
        """Return "X - Y", or 'vs' if scores are None"""
        return "vs" if self.score_home is None else f"{self.score_home} - {self.score_away}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.name} {self.score} {self.away.name}"

    @property
    def bold_score(self) -> str:
        """Embolden the winning team of a fixture"""
        if None in [self.score_home, self.time] or self.time.state == GameState.SCHEDULED:
            return f"{self.home.name} vs {self.away.name}"

        hb = '**' if self.score_home > self.score_away else ''
        ab = '**' if self.score_home < self.score_away else ''
        return f"{hb}{self.home.name} {self.score_home}{hb} - {ab}{self.score_away} {self.away.name}{ab}"

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold **winning** team, with [score](as markdown link)."""
        if None in [self.score_home, self.time] or self.time.state == GameState.SCHEDULED:
            return f"[{self.home.name} vs {self.away.name}]({self.link})"

        home = f"**{self.home.name}**" if self.score_home > self.score_away else self.home.name
        away = f"**{self.away.name}**" if self.score_away > self.score_home else self.away.name

        def parse_cards(cards: int) -> str:
            """Get a number of icons matching number of cards"""
            match cards:
                case 0 | None:
                    return ""
                case 1:
                    return '`🟥` '
                case _:
                    return f'`🟥 x{cards}` '

        sh, sa = self.score_home, self.score_away
        return f"{home} {parse_cards(self.cards_home)}[{sh} - {sa}]({self.link}){parse_cards(self.cards_away)} {away}"

    @property
    def live_score_text(self) -> str:
        """Return a string representing the score and any red cards of the fixture"""
        output = []
        if self._time is not None:
            output.append(f"`{self.time.state.emote}")

            match self.time.state:
                case GameState.STOPPAGE_TIME | GameState.EXTRA_TIME | GameState.LIVE:
                    output.append(f"{self.time.value}`")
                case _:
                    output.append(f"{self.time.state.shorthand}`")

        # Penalty Shootout
        if self.penalties_home is not None:
            ph, pa = self.penalties_home, self.penalties_away
            s = min(self.score_home, self.score_away)
            output.append(f"{self.home.name} [{s} - {s}]({self.link}) (p: {ph} - {pa}) {self.away.name}")
            return ' '.join(output)

        if self._score_home is None:
            output.append(f"{Timestamp(self.kickoff).time_hour} [{self.home.name} v {self.away.name}]({self.link})")
        else:
            output.append(self.bold_markdown)
        return ' '.join(output)

    @property
    def autocomplete(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        return f"⚽ {self.home.name} {self.score} {self.away.name} ({self.competition.title})"

    def _update_score(self, variable: Literal['_score_home', '_score_away'], value: int):
        """Set a score value."""
        if value is None:
            return

        setattr(self, variable, value)
        if (old_value := getattr(self, variable, None)) in [value, None]:
            return

        event = EventType.GOAL if value > old_value else EventType.VAR_GOAL
        self.bot.dispatch("fixture_event", event, self, home=bool(variable == '_score_home'))

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
        setattr(self, variable, value)
        if (old_value := getattr(self, variable, None)) in [value, None]:
            return

        event = EventType.RED_CARD if value > old_value else EventType.VAR_RED_CARD
        self.bot.dispatch("fixture_event", event, self, home=bool(variable == '_cards_home'))
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

    @property
    async def base_embed(self) -> Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e: Embed = await self.competition.base_embed
        e.url = self.link
        e.colour = self.time.state.colour
        e.set_author(name=self.score_line)
        e.timestamp = self.kickoff

        if self.infobox is not None:
            e.add_field(name="Match Info", value=self.infobox)

        if self.time is None:
            return e

        match self.time.state:
            case GameState.SCHEDULED:
                e.description = f"Kickoff: {Timestamp(self.kickoff).time_relative}"
            case GameState.POSTPONED:
                e.description = "This match has been postponed."
            case _:
                e.set_footer(text=self.time.state.shorthand)
        return e

    # Dispatcher
    def dispatch_events(self, old: GameState, new: GameState) -> None:
        """Dispatch events to the ticker"""

        match new:
            case GameState.ABANDONED:
                return self.bot.dispatch("fixture_event", EventType.ABANDONED, self)
            case GameState.AFTER_EXTRA_TIME:
                return self.bot.dispatch("fixture_event", EventType.SCORE_AFTER_EXTRA_TIME, self)
            case GameState.AFTER_PENS:
                return self.bot.dispatch("fixture_event", EventType.PENALTY_RESULTS, self)
            case GameState.BREAK_TIME:
                match old:
                    # Break Time fires After regular time ends & before penalties
                    case GameState.EXTRA_TIME:
                        return self.bot.dispatch("fixture_event", EventType.EXTRA_TIME_END, self)
                    case _:
                        self.breaks += 1
                        event = EventType.PERIOD_END if self.periods is not None else EventType.NORMAL_TIME_END
                        return self.bot.dispatch("fixture_event", event, self)
            case GameState.CANCELLED:
                return self.bot.dispatch("fixture_event", EventType.CANCELLED, self)
            case GameState.DELAYED:
                return self.bot.dispatch("fixture_event", EventType.DELAYED, self)
            case GameState.EXTRA_TIME:
                match old:
                    case GameState.HALF_TIME:
                        return self.bot.dispatch("fixture_event", EventType.HALF_TIME_ET_END, self)
                    case _:
                        return self.bot.dispatch("fixture_event", EventType.EXTRA_TIME_BEGIN, self)
            case GameState.FULL_TIME:
                match old:
                    case GameState.EXTRA_TIME:
                        return self.bot.dispatch("fixture_event", EventType.SCORE_AFTER_EXTRA_TIME, self)
                    case GameState.SCHEDULED | GameState.HALF_TIME:
                        return self.bot.dispatch("fixture_event", EventType.FINAL_RESULT_ONLY, self)
                    case _:
                        return self.bot.dispatch("fixture_event", EventType.FULL_TIME, self)
            case GameState.HALF_TIME:
                # Half Time is fired at both regular Half time, and ET Half time.
                event = EventType.HALF_TIME_ET_BEGIN if old == GameState.EXTRA_TIME else EventType.HALF_TIME
                return self.bot.dispatch("fixture_event", event, self)
            case GameState.INTERRUPTED:
                return self.bot.dispatch("fixture_event", EventType.INTERRUPTED, self)
            case GameState.LIVE:
                match old:
                    case GameState.SCHEDULED | GameState.DELAYED:  # Match has resumed
                        return self.bot.dispatch("fixture_event", EventType.KICK_OFF, self)
                    case GameState.INTERRUPTED:
                        return self.bot.dispatch("fixture_event", EventType.RESUMED, self)
                    case GameState.HALF_TIME:
                        return self.bot.dispatch("fixture_event", EventType.SECOND_HALF_BEGIN, self)
                    case GameState.BREAK_TIME:
                        return self.bot.dispatch("fixture_event", EventType.PERIOD_BEGIN, self)
            case GameState.PENALTIES:
                return self.bot.dispatch("fixture_event", EventType.PENALTIES_BEGIN, self)
            case GameState.POSTPONED:
                return self.bot.dispatch("fixture_event", EventType.POSTPONED, self)
            case GameState.STOPPAGE_TIME:
                return

        logging.error(f'Unhandled State change: {self.url} {old} -> {new} @ {self.time}')

    # High Cost lookups.
    async def refresh(self) -> None:
        """Perform an intensive full lookup for a fixture"""

        async with semaphore:
            page = await self.bot.browser.new_page()

            try:
                for i in range(3):  # retry up to 3 times.
                    try:
                        await page.goto(self.link, timeout=5000)
                        break
                    except TimeoutError:
                        continue
                else:
                    return
                try:
                    await page.wait_for_selector(".container__detail", timeout=5000)
                except TimeoutError:
                    return
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        # Some of these will only need updating once per match
        if self.kickoff is None:
            ko = ''.join(tree.xpath(".//div[contains(@class, 'startTime')]/div/text()"))
            self.kickoff = datetime.strptime(ko, "%d.%m.%Y %H:%M").astimezone()

        if None in [self.referee, self.stadium]:
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')
            if ref := ''.join([i for i in text if "referee" in i.lower()]).strip().replace('Referee:', ''):
                self.referee = ref
            if venue := ''.join([i for i in text if "venue" in i.lower()]).strip().replace('Venue:', ''):
                self.stadium = venue

        if None in [self.competition, self.competition.url]:
            href = ''.join(tree.xpath('.//span[contains(@class, "__country")]//a/@href'))
            country = ''.join(tree.xpath('.//span[contains(@class, "__country")]/text()')).strip()
            name = ''.join(tree.xpath('.//span[contains(@class, "__country")]/a/text()')).strip()

            if href:
                comp_id = href.split('/')[-1]
                comp = self.bot.get_competition(comp_id)
            else:
                for c in self.bot.competitions:
                    if c.name.lower() == name.lower() and c.country.lower() == country.lower():
                        comp = c
                        break
                else:
                    comp = None

            if not comp:
                comp = Competition(self.bot)
                comp.name = name
                comp.country = country
                comp.url = href

            self.competition = comp

        # Grab infobox
        if ib := tree.xpath('.//div[contains(@class, "infoBoxModule")]/div[contains(@class, "info__")]/text()'):
            self.infobox = ''.join(ib)
            if self.infobox.startswith('Format:'):
                self.periods = int(self.infobox.split(': ')[-1].split('x')[0])

        self.events = parse_events(self, tree)
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')


class Player(FlashScoreItem):
    """An object representing a player from flashscore."""
    __slots__ = ('number', 'position', 'country', 'team', 'competition', 'age', 'apps', 'goals', 'assists', 'rank',
                 'yellows', 'reds', 'injury')

    def __init__(self, bot: Bot, flashscore_id: str = None, name: str = None, link: str = None, **kwargs) -> None:

        super().__init__(bot, flashscore_id=flashscore_id, link=link, name=name)

        self.number: Optional[int] = kwargs.pop('number', None)
        self.position: Optional[str] = kwargs.pop('position', None)
        self.country: Optional[list[str]] = kwargs.pop('country', None)
        self.team: Optional[Team] = kwargs.pop('team', None)
        self.competition: Optional[Competition] = kwargs.pop('competition', None)
        self.age: Optional[int] = kwargs.pop('age', None)
        self.apps: Optional[int] = kwargs.pop('apps', None)
        self.goals: Optional[int] = kwargs.pop('goals', None)
        self.assists: Optional[int] = kwargs.pop('assists', None)
        self.rank: Optional[int] = kwargs.pop('rank', None)
        self.yellows: Optional[int] = kwargs.pop('yellows', None)
        self.reds: Optional[int] = kwargs.pop('reds', None)
        self.injury: Optional[str] = kwargs.pop('injury', None)

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
            return f"https://www.flashscore.com{self.url}"

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

        return ' '.join(output)

    @property
    def scorer_row(self) -> str:
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        r = '' if self.rank is None else (str(self.rank).rjust(3, ' '))
        tm = '' if self.team is None else self.team.markdown + ' '

        match self.goals:
            case None:
                gol = ''
            case 1:
                gol = "1 Goal "
            case _:
                gol = f"{self.goals} Goals "

        match self.assists:
            case None:
                ass = ''
            case 1:
                ass = "1 Assist"
            case _:
                ass = f"{self.assists} Assists"
        return f"{r} {self.flag} **{self.markdown}** {tm}{gol}{ass}"

    @property
    def assist_row(self) -> str:
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        tm = '' if self.team is None else self.team.markdown + ' '
        match self.goals:
            case None:
                gol = ''
            case 1:
                gol = "1 Goal "
            case _:
                gol = f"{self.goals} Goals "

        match self.assists:
            case None:
                ass = ''
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


async def search(interaction: Interaction, query: str, mode: Literal['comp', 'team'], get_recent: bool = False) \
        -> Competition | Team | Message:
    """Fetch a list of items from flashscore matching the user's query"""
    query = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))

    bot: Bot = interaction.client

    query = quote(query)
    # One day we could probably expand upon this if we ever figure out what the other variables are.
    async with bot.session.get(f"https://s.flashscore.com/search/?q={query}&l=1&s=1&f=1%3B1&pid=2&sid=1") as resp:
        match resp.status:
            case 200:
                res = await resp.text(encoding="utf-8")
            case _:
                raise ConnectionError(f"HTTP {resp.status} error in fs_search")

    # Un-fuck FS JSON reply.
    res = loads(res.lstrip('cjs.search.jsonpCallback(').rstrip(");"))

    results: list[Competition | Team] = []

    for i in res['results']:
        match i['participant_type_id']:
            case 0:
                if mode == "team":
                    continue

                if not (comp := bot.get_competition(i['id'])):
                    comp = Competition(bot)
                    comp.country = i['country_name']
                    comp.id = i['id']
                    comp.url = i['url']
                    comp.logo_url = i['logo_url']
                    name = i['title'].split(': ')
                    try:
                        name.pop(0)  # Discard COUNTRY
                    except IndexError:
                        pass
                    comp.name = name[0]
                    await comp.save_to_db()
                results.append(comp)

            case 1:
                if mode == "comp":
                    continue

                if not (team := bot.get_team(i['id'])):
                    team = Team(bot)
                    team.name = i['title']
                    team.url = i['url']
                    team.id = i['id']
                    team.logo_url = i['logo_url']
                    await team.save_to_db()
                results.append(team)
            case _:
                continue

    if not results:
        return await interaction.client.error(interaction, f"Flashscore Search: No results found for {query}")

    if len(results) == 1:
        fsr = next(results)
    else:
        view = ObjectSelectView(interaction, [('🏆', str(i), i.link) for i in results], timeout=30)
        await view.update()
        await view.wait()
        if view.value is None:
            return None
        fsr = results[view.value]

    if not get_recent:
        return fsr

    if not (items := await fsr.results()):
        return await interaction.client.error(interaction, f"No recent games found for {fsr.title}")

    view = ObjectSelectView(interaction, objects=[("⚽", i.score_line, f"{i.competition}") for i in items])
    await view.update()
    await view.wait()

    if view.value is None:
        raise builtins.TimeoutError('Timed out waiting for you to select a recent game.')

    return items[view.value]


class NewsItem:
    """A generic item representing a News Article for a team."""
    __slots__ = ['title', 'url', 'blurb', 'source', 'image_url', 'team_embed', 'time']

    def __init__(self, **kwargs) -> None:
        self.title: Optional[str] = kwargs.pop('title', None)
        self.url: Optional[str] = kwargs.pop('url', None)
        self.blurb: Optional[str] = kwargs.pop('blurb', None)
        self.source: Optional[str] = kwargs.pop('source', None)
        self.time: Optional[datetime] = kwargs.pop('time', None)
        self.image_url: Optional[str] = kwargs.pop('image_url', None)
        self.team_embed: Optional[Embed] = kwargs.pop('team_embed', None)

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
