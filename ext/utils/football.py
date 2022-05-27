"""A Utility tool for fetching and structuring data from the Flashscore Website"""
from __future__ import annotations  # Cyclic Type Hinting

import datetime
from asyncio import Semaphore, to_thread
from dataclasses import dataclass, field
from enum import Enum
from itertools import zip_longest
from json import JSONDecodeError, loads
from sys import stderr
from traceback import print_exception
from typing import List, TYPE_CHECKING, NoReturn, Dict, Literal, Type, Optional
from urllib.parse import quote, quote_plus

from discord import Embed, Interaction, Message, Colour
from discord.ui import View, Select
from lxml import html
from pyppeteer.errors import TimeoutError, ElementHandleError
from pyppeteer.page import Page

from ext.utils.browser_utils import screenshot
from ext.utils.embed_utils import rows_to_embeds, get_colour
from ext.utils.image_utils import stitch_vertical
from ext.utils.timed_events import Timestamp
from ext.utils.transfer_tools import get_flag
from ext.utils.view_utils import ObjectSelectView, FuncButton, MultipleSelect, Stop, add_page_buttons

if TYPE_CHECKING:
    from core import Bot

FLASHSCORE = 'http://www.flashscore.com'
INJURY_EMOJI = "<:injury:682714608972464187>"

# How long before data should be re-fetched.
IMAGE_UPDATE_RATE_LIMIT = datetime.timedelta(minutes=1)
LIST_UPDATE_RATE_LIMIT = datetime.timedelta(minutes=1)


# TODO: Team dropdown on Competitions
# TODO: Kill get_ in favour of properties with self.bot.browser + cached


# Helper Methods
async def delete_ads(page: Page) -> NoReturn:
    """Delete all ads on a page"""
    for x in ['.//div[@class="seoAdWrapper"]', './/div[@class="banner--sticky"]', './/div[@class="box_over_content"]',
              './/div[@class="ot-sdk-container"]', './/div[@class="adsenvelope"]', './/div[@id="onetrust-consent-sdk"]',
              './/div[@id="lsid-window-mask"]', './/div[contains(@class, "isSticky")]',
              './/div[contains(@class, "rollbar")]',
              './/div[contains(@id,"box-over-content")]', './/div[contains(@class, "adsenvelope")]',
              './/div[contains(@class, "extraContent")]', './/div[contains(@class, "selfPromo")]',
              './/div[contains(@class, "otPlaceholder")]']:
        elements = await page.xpath(x)
        for element in elements:
            try:
                await page.evaluate("""(element) => element.parentNode.removeChild(element)""", element)
            except ElementHandleError:  # If no exist.
                continue


class MatchEvent:
    """An object representing an event happening in a football fixture from Flashscore"""
    __slots__ = {"note": "any additional data about the match event",
                 "description": "match commentary about the event",
                 "player": "The player the match event is about",
                 "team": "Which team the match event is about",
                 "time": "A GameTime object representing the time of the event"}
    note: str
    description: str
    player: Player
    team: Team
    time: GameTime

    # If this is object is empty, consider it false.
    def __bool__(self) -> bool:
        return bool(self.__dict__)

    def __str__(self) -> str:
        return str(self.__dict__)

    def __repr__(self) -> str:
        return f"Event({self.__dict__})"


class Substitution(MatchEvent):
    """A substitution event for a fixture"""
    __slots__ = ["player_off"]
    player_off: Player

    def __init__(self):
        super().__init__()

    def __str__(self) -> str:
        off = "?" if not hasattr(self, "player_off") else self.player_off.markdown
        on = "?" if self.player_on is None else self.player_on.markdown
        team = "" if self.team is None else self.team.markdown
        return f"`🔄 {self.time.value}`: 🔻 {off} 🔺 {on} ({team})"

    def __repr__(self) -> str:
        return f"Substitution({self.__dict__})"

    @property
    def player_on(self) -> Optional[Player]:
        """player_on is an alias to player."""
        return getattr(self, 'player', None)


class Goal(MatchEvent):
    """A Generic Goal Event"""
    __slots__ = ["assist"]
    assist: Player

    def __str__(self) -> str:
        player = "" if self.player is None else self.player.markdown
        ass = f" (assist: {self.assist.markdown})" if self.assist else ""
        note = f" {self.note}" if self.note else ""
        return f"`⚽ {self.time.value}`: {player}{ass}{note} ({self.team.name})"

    def __repr__(self) -> str:
        return f"Goal({self.__dict__})"


class OwnGoal(Goal):
    """An own goal event"""

    def __str__(self) -> str:
        note = " " + self.note if self.note else ""
        player = "" if self.player is None else self.player.markdown + " "
        return f"`⚽ {self.time.value}`: {player}(Own Goal){note} {self.team.name}"

    def __repr__(self) -> str:
        return f"OwnGoal({self.__dict__})"


class Penalty(Goal):
    """A Penalty Event"""
    missed: bool

    @property
    def shootout(self) -> bool:
        """If it ends with a ', it was during regular time"""
        return not self.time.value.endswith("'")

    def __str__(self) -> str:
        time = "" if self.shootout else f" {self.time.value}"
        player = "" if self.player is None else self.player.markdown
        emoji = "⚽" if self.missed is False else "❌"
        return f"`{emoji}{time}`: {player} ({self.team.name})"

    def __repr__(self) -> str:
        return f"Penalty({self.__dict__})"


class RedCard(MatchEvent):
    """An object representing the event of a dismissal of a player"""
    __slots__ = ['second_yellow']
    second_yellow: bool

    def __str__(self) -> str:
        note = f' {self.note}' if self.note and 'Yellow card / Red card' not in self.note else ''
        player = "" if self.player is None else self.player.markdown
        emoji = '🟨🟥' if self.second_yellow else '🟥'
        return f'`{emoji} {self.time}`: {player}{note} ({self.team.name})'

    def __repr__(self) -> str:
        return f'RedCard({self.__dict__})'


class Booking(MatchEvent):
    """An object representing the event of a player being given a yellow card"""

    def __str__(self) -> str:
        note = f' {self.note}' if self.note and 'Yellow Card' not in self.note else ''
        player = "" if self.player is None else self.player.markdown
        return f'`🟨 {self.time}`: {player}{note} ({self.team.name})'

    def __repr__(self) -> str:
        return f"Booking({self.__dict__})"


class VAR(MatchEvent):
    """An Object Representing the event of a Video Assistant Referee Review Decision"""
    __slots__ = ["in_progress"]
    in_progress: bool

    def __str__(self) -> str:
        note = f' | {self.note}' if self.note else ''
        p = ": " + self.player.markdown if self.player else ""
        ip = " **DECISION IN PROGRESS**" if self.in_progress else ""
        return f'`📹 {self.time.value}`: VAR Review{p}{note}{ip} ({self.team.name})'

    def __repr__(self) -> str:
        return f'VAR({self.__dict__})'


class EventType(Enum):
    """An Enum representing an EventType for ticker events"""

    def __init__(self, value: str, colour: Colour, db_fields: List, valid_events: Type[MatchEvent]):
        self._value_ = value
        self.colour = colour
        self.db_fields = db_fields
        self.valid_events = valid_events

    # Goals
    GOAL = "Goal", Colour.dark_green(), ["goal"], Goal | VAR
    VAR_GOAL = "VAR Goal", Colour.og_blurple(), ["var"], VAR
    GOAL_OVERTURNED = "Goal Overturned", Colour.og_blurple(), ["var"], VAR

    # Cards
    RED_CARD = "Red Card", Colour.red(), ["var"], RedCard | VAR
    VAR_RED_CARD = "VAR Red Card", Colour.og_blurple(), ["var"], VAR
    RED_CARD_OVERTURNED = "Red Card Overturned", Colour.og_blurple(), ["var"], VAR

    # State Changes
    DELAYED = "Match Delayed", Colour.orange(), ["delayed"], type(None)
    INTERRUPTED = "Match Interrupted", Colour.dark_orange(), ["delayed"], type(None)
    CANCELLED = "Match Cancelled", Colour.red(), ["delayed"], type(None)
    POSTPONED = "Match Postponed", Colour.red(), ["delayed"], type(None)
    ABANDONED = "Match Abandoned", Colour.red(), ["full_time"], type(None)
    RESUMED = "Match Resumed", Colour.light_gray(), ["kick_off"], type(None)

    # Period Changes
    KICK_OFF = "Kick Off", Colour.green(), ["kick_off"], type(None)
    HALF_TIME = "Half Time", 0x00ffff, ["half_time"], type(None)
    SECOND_HALF_BEGIN = "Second Half", Colour.light_gray(), ["second_half_begin"], type(None)
    PERIOD_BEGIN = "Period #PERIOD#", Colour.light_gray(), ["second_half_begin"], type(None)
    PERIOD_END = "Period #PERIOD# Ends", Colour.light_gray(), ["half_time"], type(None)

    FULL_TIME = "Full Time", Colour.teal(), ["full_time"], type(None)
    FINAL_RESULT_ONLY = "Final Result", Colour.teal(), ["final_result_only"], type(None)
    SCORE_AFTER_EXTRA_TIME = "Score After Extra Time", Colour.teal(), ["full_time"], type(None)

    NORMAL_TIME_END = "End of normal time", Colour.greyple(), ["extra_time"], type(None)
    EXTRA_TIME_BEGIN = "ET: First Half", Colour.lighter_grey(), ["extra_time"], type(None)
    HALF_TIME_ET_BEGIN = "ET: Half Time", Colour.light_grey(), ["half_time", "extra_time"], type(None)
    HALF_TIME_ET_END = "ET: Second Half", Colour.dark_grey(), ["second_half_begin", "extra_time"], type(None)
    EXTRA_TIME_END = "ET: End of Extra Time", Colour.darker_gray(), ["extra_time"], type(None)

    PENALTIES_BEGIN = "Penalties Begin", Colour.dark_gold(), ["penalties"], type(None)
    PENALTY_RESULTS = "Penalty Results", Colour.gold(), ["penalties"], type(None)


class GameState(Enum):
    """An Enum representing the various possibilities of game state"""

    def __new__(cls, *args, **kwargs):
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, shorthand: str, emote: str, colour: Colour) -> None:
        self.shorthand: str = shorthand
        self.emote: str = emote
        self.colour: Colour = colour

    # Black
    SCHEDULED = ("sched", "⚫", 0x010101)
    AWAITING = ("soon", "⚫", 0x010101)
    FINAL_RESULT_ONLY = ("FRO", "⚫", 0x010101)

    # Red
    POSTPONED = ("PP", "🔴", 0xFF0000)
    ABANDONED = ("Abn", "🔴", 0xFF0000)
    CANCELLED = ("Canc", "🔴", 0xFF0000)
    WALKOVER = ("WO", "🔴", 0xFF0000)

    # Orange
    DELAYED = ("Del", "🟠", 0xff6700)
    INTERRUPTED = ("Int", "🟠", 0xff6700)

    # Green
    LIVE = ("Live", "🟢", 0x00FF00)

    # Yellow
    HALF_TIME = ("HT", "🟡", 0xFFFF00)

    # Purple
    EXTRA_TIME = ("ET", "🟣", 0x9932CC)
    STOPPAGE_TIME = ("+", "🟣", 0x9932CC)

    # Brown
    BREAK_TIME = ("Break", "🟤", 0xA52A2A)

    # Blue
    PENALTIES = ("PSO", "🔵", 0x4285F4)

    # White
    FULL_TIME = ("FT", '⚪', 0xffffff)
    AFTER_PENS = ("Pen", '⚪', 0xffffff)
    AFTER_EXTRA_TIME = ("AET", '⚪', 0xffffff)
    AWARDED = ("Awrd", '⚪', 0xffffff)


class GameTime:
    """A class representing a time of the game, with a wrapped state"""

    def __init__(self, value: str | GameState) -> None:
        # Value can either be a GameState Enum, or a string representing the time in the match.
        self.value: str | GameState = value

    def __repr__(self) -> str:
        return f"GameTime({self.__dict__})"

    def __eq__(self, other) -> bool:
        if not hasattr(other, "state"):
            return False

        try:
            return self.state == other.state
        except (AttributeError, AssertionError):
            return False

    @property
    def state(self) -> GameState:
        """Return the state of the game."""
        match self.value:
            case self.value if hasattr(self.value, 'colour'):
                return self.value
            case _:
                if "+" in self.value:
                    return GameState.STOPPAGE_TIME
                elif self.value.endswith("'") or self.value.isdigit():
                    return GameState.LIVE
                else:
                    print("GameTime.state Could not get state from self.value", self.value)


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""
    __slots__ = ['id', 'url', 'name', 'bot', 'embed_colour', 'logo_url']

    def __init__(self, bot: 'Bot'):
        self.bot: Bot = bot

    id: str
    url: str
    name: str
    embed_colour: Colour

    @property
    def markdown(self) -> str:
        """Shorthand for FSR mark-down link"""
        return self.name if self.url is None else f"[{self.name}]({self.link})"

    @property
    def link(self) -> str:
        """Alias to self.url, polymorph for subclasses."""
        return getattr(self, 'url', None)

    @property
    async def base_embed(self) -> Embed:
        """A discord Embed representing the flashscore search result"""
        e: Embed = Embed(title=self.title if hasattr(self, 'title') else self.name, url=self.link)

        if hasattr(self, "logo_url"):
            if "flashscore" in self.logo_url:
                logo = self.logo_url
            else:
                logo = "http://www.flashscore.com/res/image/data/" + self.logo_url.replace("'", "")  # Erroneous '

            if not hasattr(self, "embed_colour"):
                self.embed_colour = await get_colour(logo)

            e.colour = self.embed_colour
            e.set_thumbnail(url=logo)
        return e

    async def parse_games(self, link: str, page: Page) -> List[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(link)
            await _page.waitForXPath('.//div[@class="sportName soccer"]', {"timeout": 5000})
            tree = html.fromstring(await _page.content())
        except TimeoutError:
            return []
        finally:
            if page is None:
                await _page.close()

        fixtures: List[Fixture] = []
        comp = self if isinstance(self, Competition) else None
        for i in tree.xpath('.//div[contains(@class,"sportName soccer")]/div'):
            try:
                fx_id = i.xpath("./@id")[0].split("_")[-1]
                url = "http://www.flashscore.com/match/" + fx_id
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

            fixture = Fixture(self.bot)
            fixture.competition = comp
            fixture.id = fx_id
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
            for string, gs in [('Pen', GameState.AFTER_PENS), ('Postp', GameState.POSTPONED),
                               ('AET', GameState.AFTER_EXTRA_TIME), ('FRO', GameState.FINAL_RESULT_ONLY),
                               ('WO', GameState.WALKOVER), ('Awrd', GameState.AWARDED), ('Postp', GameState.POSTPONED),
                               ('Abn', GameState.ABANDONED)]:

                if parsed.endswith(string):
                    parsed = parsed.replace(string, '')
                    state = gs

            dtn = datetime.datetime.now()
            for string, fmt in [(parsed, '%d.%m.%Y.'),
                                (parsed, '%d.%m.%Y'),
                                (f"{dtn.year}.{parsed}", '%Y.%d.%m. %H:%M'),
                                (f"{dtn.year}.{dtn.day}.{dtn.month}.{parsed}", '%Y.%d.%m.%H:%M')]:
                try:
                    fixture.kickoff = datetime.datetime.strptime(string, fmt)
                    break
                except ValueError:
                    continue
            else:
                print(f"parse_games: Couldn't get kickoff from string '{parsed}'")

            if state is None:
                if fixture.kickoff > datetime.datetime.now():
                    state = GameState.SCHEDULED
                else:
                    state = GameState.FULL_TIME

            match state:
                case GameState():
                    fixture.time = GameTime(state)
                case datetime.datetime:
                    fixture.time = GameTime(GameState.FULL_TIME if fixture.kickoff < dtn else GameState.SCHEDULED)
                case _:
                    if "'" in parsed or "+" in parsed or parsed.isdigit():
                        fixture.time = GameTime(parsed)
                    else:
                        print('state not handled in parse_games', state, parsed)
            fixtures.append(fixture)
        return fixtures

    async def fixtures(self, page: Page = None) -> List[Fixture]:
        """Get all upcoming fixtures related to the FlashScoreItem"""
        return await self.parse_games(self.link + '/fixtures', page)

    async def results(self, page: Page = None) -> List[Fixture]:
        """Get recent results for the FlashScore Item"""
        return await self.parse_games(self.link + '/results', page)


@dataclass
class NewsItem:
    """A generic item representing a News Article for a team."""
    title: str
    url: str
    blurb: str
    source: str
    time: datetime.datetime
    image_url: str
    base_embed: Embed

    @property
    def embed(self) -> Embed:
        """Return an Embed representing the News Article"""
        e = self.base_embed
        e.title = self.title
        e.url = self.url

        if self.image_url:
            e.set_image(url=self.image_url)

        e.description = self.blurb
        e.set_footer(text=self.source)
        e.timestamp = self.time
        return e


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""
    # Constant
    emoji: str = '👕'
    __slots__ = 'competition', 'logo_url', '_players', '_players_timestamp'

    competition: Competition
    logo_url: str
    _players: List[Player]
    _players_timestamp: datetime.datetime

    def __str__(self) -> str:
        comp = self.competition.title if self.competition else ""
        return f"{self.name} ({comp})"

    def __eq__(self, other) -> bool:
        """Multiple ways of checking equivalency"""
        if hasattr(other, "id"):
            if self.id:
                return self.id == other.id
            elif self.competition:
                if self.competition == other.competition:
                    return self.name == other.name
        return False

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
    async def by_id(cls, bot: 'Bot', team_id: str, page: Page = None) -> Optional[Team]:
        """Create a Team object from it's Flashscore ID"""
        _page = await bot.browser.newPage() if page is None else page
        try:
            await _page.goto("http://flashscore.com/?r=3:" + team_id)
            url = await _page.evaluate("() => window.location.href")
            obj = cls(bot)
            obj.url = url
            obj.id = team_id
            return obj
        except TimeoutError:
            return None
        finally:
            if page is None:
                await _page.close()

    async def save_to_db(self) -> NoReturn:
        """Save the Team to the Bot Database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO fs_teams (id, name, logo_url, url) 
                    VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.id, self.name, self.logo_url, self.url)
        finally:
            await self.bot.db.release(connection)
        self.bot.teams.append(self)

    async def get_news(self, page: Page = None) -> List[Embed]:
        """Get a list of news articles related to a team in embed format"""
        _page = await self.bot.browser.newPage() if page is None else page
        try:
            await _page.goto(self.link + "/news")
            await _page.waitForXPath('.//div[@class="matchBox"]', {"timeout": 5000})
            tree = html.fromstring(await _page.content())
        except TimeoutError:
            return []
        finally:
            if page is None:
                await _page.close()

        items = []
        base_embed = await self.base_embed
        for i in tree.xpath('.//div[@id="tab-match-newsfeed"]'):
            title = "".join(i.xpath('.//div[@class="rssNews__title"]/text()'))
            image = "".join(i.xpath('.//img/@src'))
            url = "http://www.flashscore.com" + "".join(i.xpath('.//a[@class="rssNews__titleAndPerex"]/@href'))
            blurb = "".join(i.xpath('.//div[@class="rssNews__perex"]/text()'))
            provider = "".join(i.xpath('.//div[@class="rssNews__provider"]/text()')).split(',')
            time = datetime.datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
            source = provider[-1].strip()
            items.append(NewsItem(title, url, blurb, source, time, image_url=image, base_embed=base_embed).embed)
        return items

    async def players(self, page: Page = None) -> List[Player]:
        """Get a list of players for a Team"""
        # Check Cache
        now = datetime.datetime.now()
        if hasattr(self, "_players_timestamp"):
            if now - self._players_timestamp < LIST_UPDATE_RATE_LIMIT:
                return self._players

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/squad")
            await _page.waitForXPath('.//div[@class="sportName soccer"]', {"timeout": 5000})
            tree = html.fromstring(await _page.content())
        except TimeoutError:
            return []
        finally:
            if page is None:
                await _page.close()

        # tab += 1  # tab is Indexed at 0 but xpath indexes from [1]
        rows = tree.xpath(f'.//div[contains(@class, "squad-table")][contains(@id, "overall-all-table")]'
                          f'//div[contains(@class,"profileTable__row")]')

        players = []
        position: str = ""

        for i in rows:
            pos = ''.join(i.xpath('./div/text()')).strip()
            if pos:  # The way the data is structured contains a header row with the player's position.
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

            href = ''.join(i.xpath('.//div[contains(@class, "cell--name")]/a/@href')).split('/')
            # Set ID & 'url' from returned href.
            if href:
                player.id = href[-1]
                player.url = href[-2]

            player.country = i.xpath('.//span[contains(@class,"flag")]/@title')

            for attr, xp in [("number", "jersey"), ("age", "cell--age"), ("goals", "cell--goal"),
                             ("apps", "matchesPlayed"), ("yellows", "yellowCard"), ("reds", "redCard")]:
                try:
                    setattr(player, attr, ''.join(i.xpath(f'.//div[contains(@class, "{xp}"]/text()')))
                except ValueError:
                    pass

            player.injury = ''.join(i.xpath('.//span[contains(@title,"Injury")]/@title'))
            players.append(player)
        self._players_timestamp = now
        self._players = players
        return players

    def view(self, interaction: Interaction, page: Page) -> TeamView:
        """Return a view representing this Team"""
        return TeamView(self.bot, interaction, self.id, page)


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""
    __slots__ = {'logo_url': "A link to a logo representing the competition",
                 'country': "The country or region the Competition takes place in",
                 '_table': "A string containing a link to a cached version of the table of the Competition",
                 '_table_timestamp': "A timestamp of when the table was last cached",
                 '_scorers': "A dict containing a cached version of the competition's top scorers",
                 '_scorers_timestamp': "A timestamp of when the scorers were last cached",
                 'score_embeds': "A list of Embed objects representing this competition's score data"}
    # Constant
    emoji: str = '🏆'

    # Passed
    logo_url: str
    country: str

    # Livescores
    score_embeds: List[Embed]

    # Cached
    _table: str
    _table_timestamp: datetime.datetime
    _scorers: List[Player]
    _scorers_timestamp: datetime.datetime

    # Cached Timestamps for cache

    def __str__(self) -> str:
        return self.title

    def __hash__(self) -> hash:
        return hash(str(self))

    def __eq__(self, other) -> bool:
        if hasattr(other, "id"):
            if self.id and other.id:
                return other.id == self.id
        if hasattr(other, "name"):
            return other.name in self.name and self.country == other.country
        else:
            return other == self.title

    @classmethod
    async def by_link(cls, bot: 'Bot', link: str) -> Competition:
        """Create a Competition Object from a flashscore url"""
        page = await bot.browser.newPage()

        try:
            await page.goto(link)
            await page.waitForXPath(".//div[@class='heading']", {"timeout": 5000})
            tree = html.fromstring(await page.content())
        except TimeoutError:
            raise
        finally:
            await page.close()

        try:
            country = tree.xpath('.//h2[@class="breadcrumb"]//a/text()')[-1].strip()
            name = tree.xpath('.//div[@class="heading__name"]//text()')[0].strip()
        except IndexError:
            print(f'Error fetching Competition country/league by_link - {link}')
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
    async def live_score_embed(self) -> Embed:
        """Base Embed but with image"""
        e = await self.base_embed
        return e.set_image(url=getattr(self, '_table', None))

    @property
    def link(self) -> str:
        """Long form URL"""

        def fmt(string: str) -> str:
            """Format team/league into flashscore naming conventions."""
            string = string.lower()
            string = string.replace(' ', '-')
            string = string.replace('.', '')
            return string

        if not hasattr(self, 'url'):
            return f"https://www.flashscore.com/soccer/{fmt(self.country)}/{fmt(self.name)}"
        elif self.url and "://" not in self.url:
            if self.country:
                return f"https://www.flashscore.com/soccer/{fmt(self.country)}/{self.url}"
            elif self.id:
                return f"http://flashscore.com/?r=2:{self.id}"

    async def save_to_db(self) -> NoReturn:
        """Save the competition to the bot database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO fs_competitions (id, country, name, logo_url, url) 
                    VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.id, self.country, self.name, self.logo_url, self.url)
        finally:
            await self.bot.db.release(connection)
        self.bot.competitions.append(self)

    async def get_table(self, page: Page = None) -> Optional[str]:
        """Fetch the table from a flashscore Competition and return it as a BytesIO object"""
        now = datetime.datetime.now()
        if hasattr(self, '_table_timestamp'):
            if now - self._table_timestamp < IMAGE_UPDATE_RATE_LIMIT:
                return self._table

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/standings/")
            await _page.waitForXPath('.//div[contains(@class, "tableWrapper")]', {"timeout": 5000})
            await delete_ads(_page)
            data = await screenshot(_page, './/div[contains(@class, "tableWrapper")]')
            if data:
                image = await self.bot.dump_image(self.bot, data)
                if image:
                    self._table = image
                    self._table_timestamp = now
                return self._table
        except TimeoutError:
            return None
        finally:
            if page is None:
                await _page.close()

    async def scorers(self, page: Page = None) -> List[Player]:
        """Fetch a list of scorers from a Flashscore Competition page returned as a list of Player Objects"""
        now = datetime.datetime.now()
        if hasattr(self, '_scorers_timestamp'):
            if now - self._scorers_timestamp < LIST_UPDATE_RATE_LIMIT:
                return self._scorers

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/standings")
            await delete_ads(_page)
            await _page.waitForXPath('.//div[@class="tabs__group"]', {"timeout": 5000})
            nav = await _page.xpath('.//a[contains(@href, "top_scorers")]')  # Click to go to scorers tab

            for x in nav:
                print("Clicking on a top_scorers element")
                await x.click()
                print("clicked on it, waiting for shit to appear")
                await _page.waitForXPath('.//div[contains(@class, "topScorers__row")]', {"timeout": 5000})
                print("Found top scorers row.")

            while True:
                print("Searching for show more buttons")
                more = await _page.xpath('.//div[contains(@class, "showMore")]')  # Click to go to scorers tab
                for x in more:
                    await x.click()
                    print("clicked a show more button")
                else:
                    print("found no more show more buttons")
                    break
        except TimeoutError:
            pass
        finally:
            tree = html.fromstring(await _page.content())
            print("Screenshotting scorers page.")
            ss = await screenshot(_page, ".//body")
            await self.bot.dump_image(self.bot, ss)
            await _page.screenshot(fullPage=True)
            if page is None:
                await _page.close()

        scorers = []
        for i in tree.xpath('.//div[contains(@class,"table__body")]/div'):
            print("competition scorers | ROW DATA", i.xpath('.//text()'))
            player = Player(self.bot)
            player.competition = self
            player.rank = "".join(i.xpath('.//span[contains(@class, "--sorting")]/text()')).strip('.')

            if not player.rank:
                continue

            player.country = ''.join(i.xpath('.//span[contains(@class,"flag")]/@title')).strip()

            print("country", player.country)

            player.name = "".join(i.xpath('.//span[contains(@class, "--Player")]/a/text()'))
            print("name", player.name)

            player.url = "".join(i.xpath('.//span[contains(@class, "--Player")]/a/@href'))
            print("url", player.url)

            goals = "".join(i.xpath('.//span[contains(@class, "--goals")]/text()'))
            print("goals", player.goals)

            assists = "".join(i.xpath('.//span[contains(@class, "--gray")]/text()'))
            print("assists", player.assists)

            try:
                player.goals = int(goals)
            except ValueError:
                pass
            try:
                player.assists = int(assists)
            except ValueError:
                pass
            print("team url", "".join(i.xpath('./a/@href')))
            team_id = "".join(i.xpath('./a/@href')).split('/')[-1]
            print("team_id", team_id)

            team = self.bot.get_team(team_id)
            if team is None:
                team = Team(self.bot)
                team.id = team_id
                team.competition = self
                team.name = "".join(i.xpath('.//a/text()'))
                print("did not find", team_id, "in bot.teams", team.name)

            player.team = team

            scorers.append(player)

        if not scorers:
            return self._scorers

        print("DEBUG, Scorers list for", self.name, "\n", scorers)
        # Cache Values
        self._scorers = scorers
        self._scorers_timestamp = now
        return scorers

    def view(self, interaction: Interaction, page: Page) -> CompetitionView:
        """Return a view representing this Competition"""
        return CompetitionView(self.bot, interaction, self.id, page)


class Fixture(FlashScoreItem):
    """An object representing a Fixture from the Flashscore Website"""
    __slots__ = {'expires': "When to remove the fixture from bot.games stored cache",
                 'kickoff': "Kickoff time of the fixture",
                 'competition': "The competition the fixture is being played in",
                 'referee': "The referee of the fixture",
                 'stadium': "The Stadium the fixture is being played at",
                 'home': "The Home Team of the fixture",
                 'away': "The Away Team of the fixture",
                 'periods': "The number of periods of the fixture for special games",
                 'breaks': "How many breaks have happened in the fixture so far",
                 '_score_home': "The number of goals scored by the fixture's home Team",
                 '_score_away': "The number of goals scored by the fixture's away Team",
                 '_cards_home': "The number of red cards of the fixture's home Team",
                 '_cards_away': "The number of red cards of the fixture's away Team",
                 'events': "MatchEvents for a fixture",
                 'penalties_home': "The number of penalties scored by the fixture's home team",
                 'penalties_away': "The number of penalties scored by the fixture's away team",
                 'attendance': "The attendance of the fixture",
                 'infobox': "Additional information about a fixture",
                 '_time': "Last cached GameTime of the fixture",
                 '_formation': "A cached formation of the fixture",
                 '_formation_timestamp': "A timestamp representing when the fixture's formation was last cached",
                 '_h2h': "The cached head to head data of the fixture",
                 '_h2h_timestamp': "A timestamp representing when the head to head data of the fixture was last cached",
                 '_summary': "A cached summary of the fixture",
                 '_summary_timestamp': "A timestamp representing when the summary was of the fixture was last cached",
                 '_table': "A cached table of the fixture",
                 '_table_timestamp': "A timestamp representing when the table of the fixture was last cached",
                 '_stats': "A cached stats page of the fixture",
                 '_stats_timestamp': "A timestamp representing when the stats of the fixture were last cached",
                 'images': "A List of images from the fixture"}

    # Scores Loop Expiration
    expires: int

    # Set and forget
    kickoff: datetime.datetime
    competition: Competition
    referee: str
    stadium: str

    # Participants
    home: Team
    away: Team

    # Usually non-changing.
    periods: int
    breaks: int

    # Dynamic data
    _time: GameTime
    _score_home: int
    _score_away: int
    _cards_home: int
    _cards_away: int

    events: List[MatchEvent]

    # Data not always present
    penalties_home: int
    penalties_away: int
    attendance: int
    infobox: str

    images: List[str]

    # Cached Image lookups
    _formation: str
    _formation_timestamp: datetime.datetime

    _summary: str
    _summary_timestamp: datetime.datetime

    _table: str
    _table_timestamp: datetime.datetime

    _stats: str
    _stats_timestamp: datetime.datetime

    _h2h: dict
    _h2h_timestamp: datetime.datetime

    @property
    def emoji(self) -> str:
        """Property used for dropdowns."""
        return '⚽'

    def __eq__(self, other) -> bool:
        if self.id is None:
            return self.url == other.url
        else:
            return self.id == other.id

    def __str__(self) -> str:

        match self.time.state:
            case GameState.LIVE | GameState.STOPPAGE_TIME | GameState.EXTRA_TIME:
                time = self.time.value
            case GameState():
                time = self.ko_relative
            case _:
                time = self.time.state

        return f"{time}: {self.bold_markdown}"

    @property
    def score_home(self) -> int:
        """Get the score of the home team"""
        return getattr(self, '_score_home', None)

    @property
    def score_away(self) -> int:
        """Get the current score of the away team"""
        return getattr(self, '_score_away', None)

    def _update_score(self, variable: str, value: int):
        """Set a score value."""
        if value is None:
            return

        old_value: int = getattr(self, variable, None)
        setattr(self, variable, value)

        if value == old_value or old_value is None:
            return

        try:
            # Update competition's table.
            self.bot.loop.create_task(self.competition.get_table())
            event = EventType.GOAL if value > old_value else EventType.VAR_GOAL
            self.bot.dispatch("fixture_event", event, self, home=bool(variable == '_score_home'))
        except AttributeError:
            return  # So much stuff will fuck up if we let this go through

    @score_home.setter
    def score_home(self, value: int) -> NoReturn:
        """Set the score of the home team"""
        self._update_score("_score_home", value)

    @score_away.setter
    def score_away(self, value: int) -> NoReturn:
        """Set the score of the away team"""
        self._update_score("_score_away", value)

    def _update_cards(self, variable: str, value: int):
        """Set a team's cards."""
        if value is None:
            return

        old_value: int = getattr(self, variable, None)
        setattr(self, variable, value)

        if value == old_value or old_value is None:
            return

        event = EventType.RED_CARD if value > old_value else EventType.VAR_RED_CARD
        self.bot.dispatch("fixture_event", event, self, home=bool(variable == '_cards_home'))
        return

    @property
    def cards_home(self) -> int:
        """Get the current number of red cards of the Home team"""
        return getattr(self, "_cards_home", None)

    @property
    def cards_away(self) -> int:
        """Get the number of red cards of the away team"""
        return getattr(self, "_cards_away", None)

    @cards_home.setter
    def cards_home(self, value: int) -> None:
        """Update red cards & dispatch event."""
        self._update_cards("_cards_home", value)

    @cards_away.setter
    def cards_away(self, value: int) -> None:
        """Update red cards & dispatch event."""
        self._update_cards("_cards_away", value)

    async def fixtures(self, page: Page = None) -> List[Fixture]:
        """Fixture objects do not have fixtures."""
        raise NotImplementedError

    @property
    def time(self) -> GameTime:
        """Get the current GameTime of a fixture"""
        return getattr(self, '_time', None)

    @time.setter
    def time(self, game_time: GameTime) -> None:
        """Update the time of the event"""
        if hasattr(self, "_time"):
            old_state = self._time.state
            new_state = game_time.state
            if old_state.value != new_state.value:
                self.dispatch_events(old_state, new_state)
        setattr(self, '_time', game_time)
        return

    def dispatch_events(self, old: GameState, new: GameState) -> None:
        """Dispatch events to the ticker"""
        match old, new:
            case _, GameState.STOPPAGE_TIME:
                return
            case _, GameState.AFTER_EXTRA_TIME:
                return self.bot.dispatch("fixture_event", EventType.SCORE_AFTER_EXTRA_TIME, self)
            case _, GameState.PENALTIES:
                return self.bot.dispatch("fixture_event", EventType.PENALTIES_BEGIN, self)
            case _, GameState.AFTER_PENS:
                return self.bot.dispatch("fixture_event", EventType.PENALTY_RESULTS, self)
            case _, GameState.INTERRUPTED:
                return self.bot.dispatch("fixture_event", EventType.INTERRUPTED, self)
            case _, GameState.CANCELLED:
                return self.bot.dispatch("fixture_event", EventType.CANCELLED, self)
            case _, GameState.POSTPONED:
                return self.bot.dispatch("fixture_event", EventType.POSTPONED, self)
            case _, GameState.DELAYED:
                return self.bot.dispatch("fixture_event", EventType.DELAYED, self)
            case _, GameState.ABANDONED:
                return self.bot.dispatch("fixture_event", EventType.ABANDONED, self)

            # New State is LIVE
            case GameState.SCHEDULED | GameState.DELAYED, GameState.LIVE:  # Match has resumed
                return self.bot.dispatch("fixture_event", EventType.KICK_OFF, self)
            case GameState.INTERRUPTED, GameState.LIVE:
                return self.bot.dispatch("fixture_event", EventType.RESUMED, self)
            case GameState.HALF_TIME, GameState.LIVE:
                return self.bot.dispatch("fixture_event", EventType.SECOND_HALF_BEGIN, self)
            case GameState.BREAK_TIME, GameState.LIVE:
                return self.bot.dispatch("fixture_event", EventType.PERIOD_BEGIN, self)

            # Half Time is fired at both regular Half time, and ET Half time.
            case GameState.EXTRA_TIME, GameState.HALF_TIME:
                return self.bot.dispatch("fixture_event", EventType.HALF_TIME_ET_BEGIN, self)
            case _, GameState.HALF_TIME:
                return self.bot.dispatch("fixture_event", EventType.HALF_TIME, self)

            # Break Time fires After regular time ends & before penalties
            case GameState.EXTRA_TIME, GameState.BREAK_TIME:
                return self.bot.dispatch("fixture_event", EventType.EXTRA_TIME_END, self)
            case _, GameState.BREAK_TIME:
                self.breaks += 1
                event = EventType.PERIOD_END if hasattr(self, 'periods') else EventType.NORMAL_TIME_END
                return self.bot.dispatch("fixture_event", event, self)

            case GameState.HALF_TIME, GameState.EXTRA_TIME:
                return self.bot.dispatch("fixture_event", EventType.HALF_TIME_ET_END, self)
            case _, GameState.EXTRA_TIME:
                return self.bot.dispatch("fixture_event", EventType.EXTRA_TIME_BEGIN, self)

            # End of Game
            case GameState.EXTRA_TIME, GameState.FULL_TIME:
                return self.bot.dispatch("fixture_event", EventType.SCORE_AFTER_EXTRA_TIME, self)
            case GameState.SCHEDULED | GameState.HALF_TIME, GameState.FULL_TIME:
                return self.bot.dispatch("fixture_event", EventType.FINAL_RESULT_ONLY, self)
            case _, GameState.FULL_TIME:
                return self.bot.dispatch("fixture_event", EventType.FULL_TIME, self)

        print(f'    Unhandled State change: {self.url}', old, "->", new, f"@ {self.time}")

    async def base_embed(self) -> Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e: Embed = Embed(title=self.score_line, url=self.link, colour=self.time.state.colour)
        e.set_author(name=self.competition.title)
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)

        if self.time is None:
            return e
        match self.time.state:
            case GameState.SCHEDULED:
                e.description = f"Kickoff: {Timestamp(self.kickoff).time_relative}"
            case GameState.POSTPONED:
                e.description = "This match has been postponed."
            case _:
                e.set_footer(text=str(self.time.state))
        return e

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if not hasattr(self, 'kickoff'):
            return ""

        now = datetime.datetime.now()
        if self.kickoff.date == now.date:  # If the match is today, return HH:MM
            return Timestamp(self.kickoff).time_hour
        elif self.kickoff.year != now.year:  # if a different year, return DD/MM/YYYY
            return Timestamp(self.kickoff).date
        elif self.kickoff > now:  # For Upcoming
            return Timestamp(self.kickoff).date_long
        else:
            return Timestamp(self.kickoff).date_relative

    @property
    def link(self) -> str:
        """Alias to self.url"""
        return self.url

    @property
    def score(self) -> str:
        """Concatenate scores into home - away format"""
        return "vs" if self.score_home is None else f"{self.score_home} - {self.score_away}"

    @property
    def bold_score(self) -> str:
        """Embolden the winning team of a fixture"""
        if self.score_home is None or self.score_away is None or self.time.state == GameState.SCHEDULED:
            return f"{self.home.name} vs {self.away.name}"

        hb, ab = ('**', '') if self.score_home > self.score_away else ('', '**')
        hb, ab = ("", "") if self.score_home == self.score_away else (hb, ab)
        return f"{hb}{self.home.name} {self.score_home}{hb} - {ab}{self.score_away} {self.away.name}{ab}"

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold winning team, have score only link."""
        if self.score_home is None or self.score_away is None or self.time.state == GameState.SCHEDULED:
            return f"{self.home.name} vs {self.away.name}"

        hb, ab = ('**', '') if self.score_home > self.score_away else ('', '**')
        hb, ab = ("", "") if self.score_home == self.score_away else (hb, ab)
        return f"{hb}{self.home.name}{hb} [{self.score_home} - {self.score_away}]({self.link}) {ab}{self.away.name}{ab}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.name} {self.score if self.score_home is not None else 'vs'} {self.away.name}"

    @property
    def live_score_text(self) -> str:
        """Return a string representing the score and any red cards of the fixture"""
        if hasattr(self, 'kickoff'):
            # In the past we just show the hour
            if self.kickoff < datetime.datetime.now():
                ko = Timestamp(self.kickoff).time_hour
            else:  # For scheduled games, show a countdown.
                ko = Timestamp(self.kickoff).time_relative
        else:
            ko = ""

        # Penalty Shootout
        if hasattr(self, "penalties_home"):
            ph, pa = self.penalties_home, self.penalties_away
            s = min(self.score_home, self.score_away)
            s = f"{s} - {s}"
            return f"{self.time} {ko} {self.home.name} [{ph} - {pa}]({self.link}) {self.away.name} (FT: {s})"

        if hasattr(self, "_score_home"):
            h_c = f"`{self.cards_home * '🟥'}` " if self.cards_home else ""
            a_c = f" `{self.cards_away * '🟥'}`" if self.cards_away else ""
            return f"{self.time} {h_c}{self.bold_markdown}{a_c}"

        return f"{self.time} {ko} {self.home.name} [vs]({self.link}) {self.away.name}"

    async def get_badge(self, team: Literal['home', 'away']) -> str:
        """Fetch an image of a Team's Logo or Badge as a BytesIO object"""
        logo = getattr(getattr(self, team), 'logo_url', '')  # if self.away.logo_url / self.home.logo_url
        if logo:  # Not empty string
            return logo

        page = await self.bot.browser.newPage()
        try:
            await page.goto(self.link)
            await page.waitForXPath(f'.//div[contains(@class, "tlogo-{team}")]//img', {"timeout": 5000})
            tree = html.fromstring(await page.content())
        except TimeoutError:
            return ""
        finally:
            await page.close()

        potential_badges = "".join(tree.xpath(f'.//div[contains(@class, "tlogo-{team}")]//img/@src'))
        return potential_badges[0]

    async def get_table(self, page: Page = None) -> str:
        """Fetch an image of the league table appropriate to the fixture as a bytesIO object"""
        now = datetime.datetime.now()
        if hasattr(self, '_table_timestamp'):
            if now - self._table_timestamp < IMAGE_UPDATE_RATE_LIMIT:
                return self._table

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/#standings/table/overall")
            await _page.waitForXPath('.//div[contains(@class, "tableWrapper")]', {"timeout": 5000})
            await delete_ads(_page)
            data = await screenshot(_page, './/div[contains(@class, "tableWrapper")]/parent::div')
            if data:
                table = await self.bot.dump_image(self.bot, data)

                if table:
                    self._table = table
                    self._table_timestamp = now

            return self._table
        except TimeoutError:
            return getattr(self, "_table", None)
        finally:
            if page is None:
                await _page.close()

    async def get_stats(self, page: Page = None) -> Optional[str]:
        """Get an image of a list of statistics pertaining to the fixture as a BytesIO object"""
        now = datetime.datetime.now()
        if hasattr(self, '_stats_timestamp'):
            if now - self._stats_timestamp < IMAGE_UPDATE_RATE_LIMIT:
                return self._stats

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/#match-summary/match-statistics/0")
            await _page.waitForXPath(".//div[@class='section']", {"timeout": 5000})
            await delete_ads(_page)
            data = await screenshot(_page, ".//div[contains(@class, 'statRow')]")
            self._stats = await self.bot.dump_image(self.bot, data)
            self._stats_timestamp = now
            return self._stats
        except TimeoutError:
            return getattr(self, "_stats", None)
        finally:
            if page is None:
                await _page.close()

    async def get_formation(self, page: Page = None) -> Optional[str]:
        """Get the formations used by both teams in the fixture"""
        now = datetime.datetime.now()
        if hasattr(self, '_formation'):
            if now - self._formation_timestamp < IMAGE_UPDATE_RATE_LIMIT:
                return self._formation

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/#match-summary/lineups")
            await _page.waitForXPath('.//div[contains(@class, "fieldWrap")]', {"timeout": 5000})
            await delete_ads(_page)
            fm = await screenshot(_page, './/div[contains(@class, "fieldWrap")]')
            lineup = await screenshot(_page, './/div[contains(@class, "lineUp")]')
            valid_images = [i for i in [fm, lineup] if i]
            if valid_images:
                data = await to_thread(stitch_vertical, valid_images)
                self._formation = await self.bot.dump_image(self.bot, data)
                self._formation_timestamp = now
                return self._formation
        except TimeoutError:
            return getattr(self, "_formation", None)
        finally:
            if page is None:
                await _page.close()

    async def get_summary(self, page: Page = None) -> Optional[str]:
        """Fetch the summary of a Fixture"""
        now = datetime.datetime.now()
        if hasattr(self, '_summary_timestamp'):
            if now - self._summary_timestamp < IMAGE_UPDATE_RATE_LIMIT:
                return self._summary

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/#standings/table/overall")
            await _page.waitForXPath(".//div[contains(@class, 'verticalSections')]", {"timeout": 5000})
            await delete_ads(_page)
            data = await screenshot(_page, ".//div[contains(@class, 'verticalSections')]")
            if data:
                self._summary = await self.bot.dump_image(self.bot, data)
                self._summary_timestamp = now
                return self._summary
        except TimeoutError:
            return getattr(self, '_summary', None)
        finally:
            if page is None:
                await _page.close()

    async def head_to_head(self, page: Page = None) -> Optional[dict]:
        """Get results of recent games related to the two teams in the fixture"""
        now = datetime.datetime.now()
        if hasattr(self, '_h2h'):
            if now - self._h2h_timestamp < IMAGE_UPDATE_RATE_LIMIT:
                return self._h2h

        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link + "/#/h2h/overall")
            await _page.waitForXPath(".//div[@class='h2h']", {"timeout": 5000})
            tree = html.fromstring(await _page.content())
        except TimeoutError:
            return getattr(self, '_h2h', None)
        finally:
            if page is None:
                await _page.close()

        games: Dict[str, List[Fixture]] = {}

        for i in tree.xpath('.//div[contains(@class, "section")]'):
            header = ''.join(i.xpath('.//div[contains(@class, "title")]//text()')).strip().title()
            if not header:
                continue

            fixtures = i.xpath('.//div[contains(@class, "_row")]')
            fx_list = []
            for game in fixtures[:5]:  # Last 5 only.
                fx = Fixture(self.bot)
                # TODO: Click Each H2H fixture and get new window url.

                home = ''.join(game.xpath('.//span[contains(@class, "homeParticipant")]//text()')).strip().title()
                away = ''.join(game.xpath('.//span[contains(@class, "awayParticipant")]//text()')).strip().title()

                # Compare HOME team of H2H fixture to base fixture.
                match home:
                    case home if home in self.home.name:
                        fx.home = self.home
                    case home if home in self.away.name:
                        fx.home = self.away
                    case _:
                        for t in self.bot.teams:
                            if home in t.name:
                                fx.home = t
                                break
                        else:
                            fx.home = Team(self.bot)
                            fx.home.name = home

                match away:
                    case away if away in self.home.name:
                        fx.away = self.away
                    case away if away in self.away.name:
                        fx.away = self.away
                    case _:
                        for t in self.bot.teams:
                            if away in t.name:
                                fx.away = t
                                break
                        else:
                            fx.away = Team(self.bot)
                            fx.away.name = home

                kickoff = game.xpath('.//span[contains(@class, "date")]/text()')[0].strip()

                try:
                    kickoff = datetime.datetime.strptime(kickoff, "%d.%m.%y")
                except ValueError:
                    print("football.py: head_to_head", kickoff, "format is not %d.%m.%y")
                fx.kickoff = kickoff
                score_home, score_away = game.xpath('.//span[contains(@class, "regularTime")]//text()')[0].split(':')
                fx.score_home, fx.score_away = int(score_home.strip()), int(score_away.strip())

                fx_list.append(fx)
            games.update({header: fx_list})
        self._h2h_timestamp = now
        self._h2h = games
        return self._h2h

    async def get_preview(self, page: Page = None) -> str:
        """Fetch information about upcoming match from Flashscore"""
        _page = await self.bot.browser.newPage() if page is None else page

        try:
            await _page.goto(self.link)
            await _page.waitForXPath('.//div[contains(@class, "previewOpenBlock")]/div//text()', {"timeout": 5000})

            while True:
                more = await _page.xpath('.//div[contains(@class, "showMore")]')  # Click to go to scorers tab
                for x in more:
                    await x.click()
                else:
                    break

            tree = html.fromstring(await _page.content())
        except TimeoutError:
            return 'Timed out waiting for summary'
        finally:
            if page is None:
                await _page.close()

        preview_lines = tree.xpath('.//div[@class="previewLine"]')

        preview = ""
        r = f"**🙈 Referee**: {self.referee}" if self.referee else ""
        s = f"**🥅 Venue**: {self.stadium}" if self.stadium else ""
        if any([r, s]):
            preview += "####" + " | ".join([i for i in [r, s] if i]) + "\n\n"

        if preview_lines:
            preview += "# Match Preview\n\n"
        for block in preview_lines:
            this_block = "* " + ''.join(block.xpath('.//text()')) + "\n"
            preview += this_block

        _ = tree.xpath('.//div[contains(text(), "Will not play")]/following-sibling::div//div[@class="lf__side"]')
        if _:
            nph, npa = _
            preview += "\n\n\n## Absent Players\n"

            home = []
            for _ in nph:
                ij = ''.join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                home.append(player)

            away = []
            for _ in npa:
                ij = ''.join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                away.append(player)

            rows = list(zip_longest(home, away))
            preview += f"{self.home.name}|{self.away.name}\n--:|:--\n"
            for a, b in rows:
                preview += f"{a} | {b}\n"

        _ = tree.xpath('.//div[contains(text(), "Questionable")]/following-sibling::div//div[@class="lf__side"]')
        if _:
            nph, npa = _
            preview += "\n\n\n## Potentially Absent Players\n"

            home = []
            for _ in nph:
                ij = ''.join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                home.append(player)

            away = []
            for _ in npa:
                ij = ''.join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                away.append(player)

            rows = list(zip_longest(home, away))
            preview += f"{self.home.name}|{self.away.name}\n--:|:--\n"
            for a, b in rows:
                preview += f"{'*-*' if a is None else a} | {'*-*' if b is None else b}\n"

        h2h = await self.head_to_head(page)
        if h2h:
            preview += "\n## Head to Head"
            for cat, games in h2h.items():
                preview += f"\n#### {cat}\n"
                for game in games:
                    preview += f"* {game.bold_score}\n"

        tv = tree.xpath('.//div[contains(@class, "broadcast")]/div/a')
        if tv:
            preview += "\n## Television Coverage\n\n"
            tv_list = ["[" + ''.join(_.xpath('.//text()')) + "](" + ''.join(_.xpath('.//@href')) + ")" for _ in tv]
            preview += ", ".join(tv_list)

        return preview

    async def refresh(self, page: Page = None) -> NoReturn:
        """Perform an intensive full lookup for a fixture"""

        for i in range(3):  # retry up to 3 times.
            _page = await self.bot.browser.newPage() if page is None else page
            try:
                await _page.goto(self.link)
                await _page.waitForXPath(".//div[@class='container__detail']", {"timeout": 5000})
                tree = html.fromstring(await _page.content())
                break
            except TimeoutError:
                continue
            except Exception as err:
                print(f'Retry ({i}) Error refreshing fixture {self.home.name} v {self.away.name}: {type(err)}')
                continue
            finally:
                if page is None:
                    await _page.close()
        else:
            return

        # Some of these will only need updating once per match
        if not hasattr(self, 'kickoff'):
            try:
                ko = ''.join(tree.xpath(".//div[contains(@class, 'startTime')]/div/text()"))
                self.kickoff = datetime.datetime.strptime(ko, "%d.%m.%Y %H:%M")
            except ValueError:
                pass

        if not hasattr(self, 'referee') or not hasattr(self, 'stadium'):
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')
            ref = ''.join([i for i in text if "referee" in i.lower()]).strip().replace('Referee:', '')
            venue = ''.join([i for i in text if "venue" in i.lower()]).strip().replace('Venue:', '')
            if ref:
                self.referee = ref
            if venue:
                self.stadium = venue

        if not hasattr(self, 'competition') or self.competition.url is None:
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
        ib = tree.xpath('.//div[contains(@class, "infoBoxModule")]/div[contains(@class, "info__")]/text()')
        if ib:
            self.infobox = ''.join(ib)
            if self.infobox.startswith('Format:'):
                fmt = self.infobox.split(': ')[-1]
                periods = fmt.split('x')[0]
                self.periods = int(periods)

        events = []

        for i in tree.xpath('.//div[contains(@class, "verticalSections")]/div'):
            team_detection = i.attrib['class']

            # Detection of Teams
            match team_detection:
                case team_detection if "Header" in team_detection:
                    parts = [x.strip() for x in i.xpath('.//text()')]
                    if "Penalties" in parts:
                        try:
                            _, self.penalties_home, _, self.penalties_away = parts
                        except ValueError:
                            _, pen_string = parts
                            self.penalties_home, self.penalties_away = pen_string.split(' - ')
                    continue
                case team_detection if "home" in team_detection:
                    team = self.home
                case team_detection if "away" in team_detection:
                    team = self.away
                case team_detection if "empty" in team_detection:
                    continue  # No events in half signifier.
                case _:
                    print(f"No team found for team_detection {team_detection}")
                    continue

            node = i.xpath('./div[contains(@class, "incident")]')[0]  # event_node
            icon = ''.join(node.xpath('.//div[contains(@class, "incidentIcon")]//svg/@class')).strip()
            title = ''.join(node.xpath('.//div[contains(@class, "incidentIcon")]//@title')).strip()
            description = title.replace('<br />', ' ')
            icon_desc = ''.join(node.xpath('.//div[contains(@class, "incidentIcon")]//svg//text()')).strip()

            match (icon, icon_desc):
                # Missed Penalties
                case ("penaltyMissed-ico", _) | (_, "Penalty missed"):
                    event = Penalty()
                    event.missed = True
                case (_, "Penalty"):
                    event = Penalty()
                case (_, "Own goal") | ("footballOwnGoal-ico", _):
                    event = OwnGoal()
                case (_, "Goal") | ("footballGoal-ico", _):
                    event = Goal()
                    if icon_desc and icon_desc.lower() != "goal":
                        print("unhandled icon_desc for goal", icon_desc)
                # Red card
                case (_, "Red Card") | ("card-ico", _):
                    event = RedCard()
                    if icon_desc != "Red Card":
                        event.note = icon_desc

                # Second Yellow
                case (_, "Yellow card / Red card") | ("redYellowCard-ico", _):
                    event = RedCard()
                    event.second_yellow = True
                    if "card / Red" not in icon_desc:
                        event.note = icon_desc
                # Single Yellow
                case ("yellowCard-ico", _):
                    event = Booking()
                    event.note = icon_desc
                case (_, "Substitution - In") | ("substitution-ico", _):
                    event = Substitution()
                    p = Player(self.bot)
                    p.name = "".join(node.xpath('.//div[contains(@class, "incidentSubOut")]/a/text()')).strip()
                    p.url = "".join(node.xpath('.//div[contains(@class, "incidentSubOut")]/a/@href')).strip()
                    event.player_off = p
                case ("var-ico", _):
                    event = VAR()
                    icon_desc = icon_desc if icon_desc else ''.join(node.xpath('./div//text()')).strip()
                    if icon_desc:
                        event.note = icon_desc
                case ("varLive-ico", _):
                    event = VAR()
                    event.in_progress = True
                    event.note = icon_desc
                case _:
                    event = MatchEvent()
                    print("Wanna sort out the case statement?", icon, "|", icon_desc)

            event.team = team

            # Data not always present.
            name = ''.join(node.xpath('.//a[contains(@class, "playerName")]//text()')).strip()
            if name:
                p = Player(self.bot)
                p.name = name
                p.url = ''.join(node.xpath('.//a[contains(@class, "playerName")]//@href')).strip()
                event.player = p

            assist = ''.join(node.xpath('.//div[contains(@class, "assist")]//text()'))
            if assist:
                p = Player(self.bot)
                p.name = assist.strip('()')
                p.url = ''.join(node.xpath('.//div[contains(@class, "assist")]//@href'))
                event.assist = p

            if description:
                event.description = description

            event.time = GameTime(''.join(node.xpath('.//div[contains(@class, "timeBox")]//text()')).strip())
            events.append(event)

        self.events = events
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')
        if self.images:
            print("FIXTURE IMAGES DETECTED")
            print(self.images)

    def view(self, interaction: Interaction, page: Page) -> FixtureView:
        """Return a view representing this Fixture"""
        return FixtureView(self.bot, interaction, self.id, page)


class Player(FlashScoreItem):
    """An object representing a player from flashscore."""
    __slots__ = {'number': "Player's squad number",
                 'position': "Player's squad position",
                 'country': "List or single nationality of player",
                 'team': "Team object, the player's team",
                 'competition': "Competition object representing the team the player is playing in",
                 'age': "The player's age",
                 'apps': "Number of appearances for the player's team, used on top scorers commands",
                 'goals': "Number of goals scored by the player, used on top_scorers commands",
                 'assists': "Number of assists by the player, used on top_scorers commands",
                 'rank': "Ranking in a top scorers chart",
                 'yellows': "Number of yellow cards the player has received",
                 'reds': "Number of red cards the player has received",
                 'injury': "The player's injury"}

    number: int
    position: str
    country: str | List[str]
    team: Team
    competition: Competition
    age: int
    apps: int
    goals: int
    assists: int
    rank: int  # Top Scorers Ranking
    yellows: int
    reds: int
    injury: str

    def __bool__(self) -> bool:
        return bool(self.__dict__)

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return get_flag(self.country)

    @property
    def link(self) -> str:
        """Alias to self.url"""
        if "http://" in self.url:
            return self.url
        else:
            return f"http://www.flashscore.com/{self.url}"

    @property
    def squad_row(self) -> str:
        """String for Team Lineup."""
        num = f"`{str(self.number).rjust(2)}`: " if self.number != 0 else ""
        inj = f" - {INJURY_EMOJI} {self.injury}" if self.injury else ""
        return f"{num}{self.flag} {self.markdown} ({self.position}{inj})"

    @property
    def scorer_row(self) -> str:
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        out = ""
        if self.rank:
            out += f"`{str(self.rank).rjust(3, ' ')}`"

        out += f"{self.flag} **{self.markdown}** "

        if self.team:
            out += self.team.markdown

        out += f" {self.goals} Goal{'s' if self.goals != 1 else ''}"

        if self.assists > 0:
            out += f" ({self.assists} Assist{'s' if self.assists != 1 else ''})"
        return out

    @property
    def assist_row(self) -> str:
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        out = f"{self.flag} [**{self.name}**]({self.link}) "

        if self.team:
            out += f"{self.team.markdown} "

        out += f" ({self.assists} Assist{'s' if self.assists != 1 else ''})"
        if self.goals and self.goals > 0:
            out += f"{self.goals} Goal{'s' if self.goals != 1 else ''}"
        return out

    @property
    def injury_row(self) -> str:
        """Return a string with player & their injury"""
        return f"{self.flag} {self.markdown} ({self.position}): {INJURY_EMOJI} {self.injury}"

    async def fixtures(self, page: Page = None) -> List[Fixture]:
        """Get from player's team instead."""
        return await self.team.fixtures(page)


class ViewErrorHandling(object):
    """Mixin to handle View Errors."""

    async def on_error(self, error, item, _: Interaction) -> NoReturn:
        """Extended Error Logging."""
        print(f'[SCORES.PY] Ignoring exception in view {self} for item {item}:', file=stderr)
        print_exception(error.__class__, error, error.__traceback__, file=stderr)


class FixtureView(View, ViewErrorHandling):
    """The View sent to users about a fixture."""

    def __init__(self, bot: 'Bot', interaction: Interaction, fixture_id: str, page: Page) -> NoReturn:
        self.fixture_id: str = fixture_id
        self.interaction: Interaction = interaction
        self.bot = bot

        self.page = page
        super().__init__()

        # Pagination
        self.pages: List[Embed] = []
        self.index: int = 0
        self.semaphore: Semaphore = Semaphore()

        # Button Disabling
        self._disabled = None

    @property
    def fixture(self) -> Fixture:
        """Always fetch the latest version of the fixture"""
        return self.bot.get_fixture(self.fixture_id)

    async def on_timeout(self) -> Message:
        """Cleanup"""
        if self.page and not self.page.isClosed():
            await self.page.close()
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.bot.user.id

    async def update(self, content: str = "", mode: str = "") -> Message:
        """Update the view for the user"""
        embed = self.pages[self.index]
        async with self.semaphore:
            self.clear_items()
            for _ in [FuncButton(label="Stats", func=self.push_stats, emoji="📊"),
                      FuncButton(label="Table", func=self.push_table),
                      FuncButton(label="Lineups", func=self.push_lineups),
                      FuncButton(label="Summary", func=self.push_summary),
                      FuncButton(label="H2H", func=self.push_head_to_head, emoji="⚔"),
                      Stop()
                      ]:
                _.disabled = True if mode == _.label else False
                self.add_item(_)
            return await self.bot.reply(self.interaction, content=content, view=self, embed=embed)

    async def push_stats(self) -> Message:
        """Push Stats to View"""
        self.index = 0

        embed = await self.fixture.base_embed()
        embed.description = f"{Timestamp().time_relative}\n"
        image = await self.fixture.get_stats(page=self.page)
        if image:
            embed.set_image(url=image)
        embed.description += "No Stats Found" if image is None else ""
        self.pages = [embed]
        self._disabled = "Stats"
        return await self.update()

    async def push_lineups(self) -> Message:
        """Push Lineups to View"""
        self.index = 0

        embed = await self.fixture.base_embed()
        embed.description = f"{Timestamp().time_relative}\n"
        image = await self.fixture.get_formation(page=self.page)
        if image:
            embed.set_image(url=image)
        embed.description += "No Lineups Found" if image is None else ""
        self.pages = [embed]
        self._disabled = "Lineups"
        return await self.update()

    async def push_table(self) -> Message:
        """Push Fixture's Table to View"""
        self.index = 0

        embed = await self.fixture.base_embed()
        embed.description = f"{Timestamp().time_relative}\n"
        image = await self.fixture.get_table(page=self.page)
        if image:
            embed.set_image(url=image)
        embed.description += "No Table Found" if image is None else ""
        self.pages = [embed]
        self._disabled = "Table"
        return await self.update()

    async def push_summary(self) -> Message:
        """Push Summary to View"""
        self.index = 0

        embed = await self.fixture.base_embed()
        embed.description = f"{Timestamp().time_relative}\n"
        image = await self.fixture.get_summary(page=self.page)
        if image:
            embed.set_image(url=image)
        embed.description += "No Summary Found" if image is None else ""
        embed.title = f"{self.fixture.home.name} {self.fixture.score} {self.fixture.away.name}"
        self.pages = [embed]
        self._disabled = "Summary"
        return await self.update()

    async def push_head_to_head(self) -> Message:
        """Push Head-to-Head to View"""
        self.index = 0
        fixtures = await self.fixture.head_to_head(page=self.page)
        embed = await self.fixture.base_embed()

        if fixtures is None:
            embed.description = "Could not find any head to head data"
        else:
            for k, v in fixtures.items():
                x = "\n".join([f"{i.time.relative_time} [{i.bold_score}]({i.url})" for i in v])
                embed.add_field(name=k, value=x, inline=False)
        self.pages = [embed]
        self._disabled = "Head To Head"
        return await self.update()


class CompetitionView(View, ViewErrorHandling):
    """The view sent to a user about a Competition"""

    def __init__(self, bot: 'Bot', interaction: Interaction, comp_id: str, page: Page) -> NoReturn:
        super().__init__()
        self.bot: Bot = bot
        self.page: Page = page
        self._comp_id: str = comp_id
        self.semaphore: Semaphore = Semaphore()
        self.interaction: Interaction = interaction

        # Embed and internal index.
        self.pages: List[Embed] = []
        self.index: int = 0

        # Button Disabling
        self._disabled: str = ""

        # Player Filtering
        self._nationality_filter: str = ""
        self._team_filter: str = ""
        self._filter_mode: str = "goals"

    @property
    def competition(self) -> Competition:
        """Always fetch the latest version of the competition"""
        return self.bot.get_competition(self._comp_id)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.bot.user.id

    async def on_timeout(self) -> Message:
        """Cleanup"""
        if self.page and not self.page.isClosed():
            await self.page.close()
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = "") -> Message:
        """Update the view for the Competition"""
        async with self.semaphore:
            self.clear_items()

            if self._filter_mode:
                # Generate New Dropdowns.
                players = await self.filter_players()

                # List of Unique team names as Option()s
                teams = sorted(set([('👕', i.team.name, str(i.team.link)) for i in players]), key=lambda x: x[1])[:25]

                if teams:
                    sel = MultipleSelect(placeholder="Filter by Team...", options=teams, attribute='team_filter', row=2)
                    if self._team_filter:
                        sel.placeholder = f"Teams: {', '.join(self._team_filter)}"
                    self.add_item(sel)

                # List of Unique nationalities as Option()s
                flags = sorted(set([(get_flag(i.country), i.country, "") for i in players]), key=lambda x: x[1])[:25]

                if flags:
                    ph = "Filter by Nationality..."
                    sel = MultipleSelect(placeholder=ph, options=flags, attribute='nationality_filter', row=3)
                    if self._nationality_filter:
                        sel.placeholder = f"Countries:{', '.join(self._nationality_filter)}"
                    self.add_item(sel)

            for button in [FuncButton(label="Table", func=self.push_table, emoji="🥇", row=4),
                           FuncButton(label="Scorers", func=self.push_scorers, emoji='⚽', row=4),
                           FuncButton(label="Fixtures", func=self.push_fixtures, emoji='📆', row=4),
                           FuncButton(label="Results", func=self.push_results, emoji='⚽', row=4)]:
                button.disabled = True if self._disabled == button.label else False
                self.add_item(button)

            try:
                embed = self.pages[self.index]
            except IndexError:
                embed = next(iter(self.pages), None)

            return await self.bot.reply(self.interaction, content=content, view=self, embed=embed)

    async def filter_players(self) -> List[Player]:
        """Filter player list according to dropdowns."""
        embed = await self.competition.base_embed
        players = await self.competition.scorers(page=self.page)
        all_players = players

        if self._nationality_filter:
            players = [i for i in players if i.country in self._nationality_filter]
        if self._team_filter:
            players = [i for i in players if i.team.name in self._team_filter]

        match self._filter_mode:
            case "goals":
                srt = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
                embed.title = f"≡ Top Scorers for {embed.title}"
                rows = [i.scorer_row for i in srt]
            case "assists":
                srt = sorted([i for i in players if i.assists > 0], key=lambda x: x.assists, reverse=True)
                embed.title = f"≡ Top Assists for {embed.title}"
                rows = [i.assist_row for i in srt]
            case _:
                print("INVALID _filter_mode in COMPETITION_VIEW", self._filter_mode)
                rows = []

        if not rows:
            rows = [f'```yaml\nNo Top Scorer Data Available matching your filters```']

        embeds = rows_to_embeds(embed, rows)
        self.pages = embeds
        return all_players

    async def push_table(self) -> Message:
        """Push Team's Table for a Competition to View"""
        img = await self.competition.get_table(page=self.page)

        embed = await self.competition.base_embed
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition}"
        if img:
            embed.set_image(url=img)
            embed.description = Timestamp().long
        else:
            embed.description = "No Table Found"

        self.index = 0
        self.pages = [embed]
        self._filter_mode = None
        self._disabled = "Table"
        return await self.update()

    async def push_scorers(self) -> Message:
        """PUsh the Scorers Embed to Competition View"""
        self.index = 0
        self._filter_mode = "goals"
        self._disabled = "Scorers"
        self._nationality_filter = None
        self._team_filter = None
        return await self.update()

    async def push_assists(self) -> Message:
        """PUsh the Scorers Embed to View"""
        self.index = 0
        self._filter_mode = "assists"
        self._disabled = "Assists"
        self._nationality_filter = None
        self._team_filter = None
        return await self.update()

    async def push_fixtures(self) -> Message:
        """Push upcoming competition fixtures to View"""
        rows = await self.competition.fixtures(page=self.page)
        rows = [str(i) for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.competition.base_embed
        embed.title = f"≡ Fixtures for {self.competition}"

        self.index = 0
        self.pages = rows_to_embeds(embed, rows)
        self._disabled = "Fixtures"
        self._filter_mode = None
        return await self.update()

    async def push_results(self) -> Message:
        """Push results fixtures to View"""
        rows = await self.competition.results(page=self.page)
        rows = [str(i) for i in rows] if rows else ["No Results Found"]

        embed = await self.competition.base_embed
        embed.title = f"≡ Results for {self.competition.title}"

        self.index = 0
        self.pages = rows_to_embeds(embed, rows)
        self._disabled = "Results"
        self._filter_mode = None
        return await self.update()


class TeamView(View, ViewErrorHandling):
    """The View sent to a user about a Team"""

    def __init__(self, bot: 'Bot', interaction: Interaction, team_id: str, page: Page, parent: View = None):
        super().__init__()
        self.bot: Bot = bot
        self.page: Page = page
        self.team_id: str = team_id
        self.interaction: interaction = interaction
        self.parent: View = parent

        # Pagination
        self.semaphore: Semaphore = Semaphore()
        self.pages = []
        self.index = 0
        self.value = None

        # Specific Selection
        self.league_select: List[Competition] | False = False

        # Disable buttons when changing pages.
        # Page buttons have their own callbacks so cannot be directly passed to update
        self._disabled: str = ""

    @property
    def team(self) -> Team:
        """Always return the latest version of the team"""
        return self.bot.get_team(self.team_id)

    async def on_timeout(self) -> Message:
        """Cleanup"""
        if self.page and not self.page.isClosed():
            await self.page.close()
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = "") -> Message:
        """Update the view for the user"""
        async with self.semaphore:
            self.clear_items()
            if self.league_select:
                self.add_item(LeagueTableSelect(leagues=self.league_select))
                self.league_select = []
            else:
                add_page_buttons(self)

                for _ in [FuncButton(label="Squad", func=self.push_squad),
                          FuncButton(label="Injuries", func=self.push_injuries, emoji=INJURY_EMOJI),
                          FuncButton(label="Scorers", func=self.push_scorers, emoji='⚽'),
                          FuncButton(label="Table", func=self.select_table, row=3),
                          FuncButton(label="Fixtures", func=self.push_fixtures, row=3),
                          FuncButton(label="Results", func=self.push_results, row=3),
                          FuncButton(label="News", func=self.push_news, row=3, emoji='📰'),
                          ]:
                    _.disabled = True if self._disabled == _.label else False
                    self.add_item(_)

            embed = self.pages[self.index] if self.pages else None
            return await self.bot.reply(self.interaction, content=content, view=self, embed=embed)

    async def push_news(self) -> Message:
        """Push News to View"""
        self.pages = await self.team.get_news()
        self.index = 0
        self._disabled = "News"
        return await self.update()

    async def push_squad(self) -> Message:
        """Push the Squad Embed to the team View"""
        players = await self.team.players(page=self.page)
        p = [i.squad_row for i in sorted(players, key=lambda x: x.number)]

        # Data must be fetched before embed url is updated.
        embed = await self.team.base_embed
        self.index = 0
        self.pages = rows_to_embeds(embed, p)
        self._disabled = "Squad"
        return await self.update()

    async def push_injuries(self) -> Message:
        """Push the Injuries Embed to the team View"""
        embed = await self.team.base_embed
        players = await self.team.players(page=self.page)
        players = [i.injury_row for i in players if i.injury] if players else ['No injuries found']
        embed.description = "\n".join(players)
        self.index = 0
        self.pages = [embed]
        self._disabled = "Injuries"
        return await self.update()

    async def push_scorers(self) -> Message:
        """Push the Scorers Embed to the team View"""
        embed = await self.team.base_embed
        players = await self.team.players(page=self.page)
        rows = [i.scorer_row for i in sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)]

        self.index = 0
        self.pages = rows_to_embeds(embed, rows)
        self._disabled = "Scorers"
        return await self.update()

    async def select_table(self) -> Message:
        """Select Which Table to push from"""
        self.index = 0
        all_fixtures = await self.team.fixtures(self.page)

        comps: List[Competition] = list(set(x.competition for x in all_fixtures))
        comps = [x for x in comps if x.name != "Club Friendly"]  # Discard this.
        if len(comps) == 1:
            return await self.push_table(comps[0])

        self.league_select = comps

        leagues = [f"• {x.flag} {x.markdown}" for x in comps]

        e = await self.team.base_embed
        e.description = "**Use the dropdown to select a table**:\n\n " + "\n".join(leagues)
        self.pages = [e]
        return await self.update()

    async def push_table(self, res: Competition) -> Message:
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.team.base_embed
        img = await res.get_table(self.page)

        embed.title = f"≡ Table for {res.title}"
        if img:
            embed.set_image(url=img)
            embed.description = Timestamp().long
        else:
            embed.description = f"No Table found."

        self.pages = [embed]
        self._disabled = "Table"
        return await self.update()

    async def push_fixtures(self) -> Message:
        """Push upcoming fixtures to Team View"""
        rows = await self.team.fixtures(page=self.page)
        rows = [i.markdown for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.team.base_embed
        embed.title = f"≡ Fixtures for {self.team.name}"

        self.index = 0
        self.pages = rows_to_embeds(embed, rows)
        self._disabled = "Fixtures"
        return await self.update()

    async def push_results(self) -> Message:
        """Push results fixtures to View"""
        rows = await self.team.results(page=self.page)
        rows = [i.bold_markdown for i in rows] if rows else ["No Results Found :("]
        embed = await self.team.base_embed
        embed.title = f"≡ Results for {self.team.name}" if embed.title else "≡ Results "

        self.index = 0
        self.pages = rows_to_embeds(embed, rows)
        self._disabled = "Results"
        return await self.update()


class LeagueTableSelect(Select):
    """Push a Specific League Table"""
    def __init__(self, leagues: List[Competition]) -> None:
        self.objects = leagues
        super().__init__(placeholder="Select which league to get table from...")
        for num, league in enumerate(self.objects):
            self.add_option(label=league.title, emoji='🏆', description=league.link, value=str(num))

    async def callback(self, interaction: Interaction) -> Message:
        """Upon Item Selection do this"""
        v: TeamView = self.view
        await interaction.response.defer()
        return await v.push_table(self.objects[int(self.values[0])])


@dataclass
class Stadium:
    """An object representing a football Stadium from football ground map.com"""
    bot: Bot
    url: str = ""
    name: str = ""
    team: str = ""
    league: str = ""
    country: str = ""
    team_badge: str = ""

    image: str = ""
    current_home: List[str] = field(default_factory=list)
    former_home: List[str] = field(default_factory=list)
    map_link: str = None
    address: str = "Link to map"
    capacity: str = ""
    cost: str = ""
    website: str = ""
    attendance_record: str = ""

    async def fetch_more(self) -> NoReturn:
        """Fetch more data about a target stadium"""
        async with self.bot.session.get(self.url) as resp:
            src = await resp.read()
            src = src.decode('ISO-8859-1')
            tree = html.fromstring(src)
        self.image = ''.join(tree.xpath('.//div[@class="page-img"]/img/@src'))

        # Teams
        try:
            v = tree.xpath('.//tr/th[contains(text(), "Former home")]/following-sibling::td')[0]
            t = [f"[{x}]({y})" for x, y in list(zip(v.xpath('.//a/text()'), v.xpath('.//a/@href'))) if "/team/" in y]
            self.former_home = t
        except IndexError:
            pass

        try:
            v = tree.xpath('.//tr/th[contains(text(), "home to")]/following-sibling::td')[0]
            t = [f"[{x}]({y})" for x, y in list(zip(v.xpath('.//a/text()'), v.xpath('.//a/@href'))) if "/team/" in y]
            self.current_home = t
        except IndexError:
            pass

        self.map_link = ''.join(tree.xpath('.//figure/img/@src'))
        self.address = ''.join(tree.xpath('.//tr/th[contains(text(), "Address")]/following-sibling::td//text()'))
        self.capacity = ''.join(tree.xpath('.//tr/th[contains(text(), "Capacity")]/following-sibling::td//text()'))
        self.cost = ''.join(tree.xpath('.//tr/th[contains(text(), "Cost")]/following-sibling::td//text()'))
        self.website = ''.join(tree.xpath('.//tr/th[contains(text(), "Website")]/following-sibling::td//text()'))
        self.attendance_record = ''.join(
            tree.xpath('.//tr/th[contains(text(), "Record attendance")]/following-sibling::td//text()'))

    def __str__(self) -> str:
        return f"**{self.name}** ({self.country}: {self.team})"

    @property
    async def to_embed(self) -> Embed:
        """Create a discord Embed object representing the information about a football stadium"""
        e: Embed = Embed(title=self.name, url=self.url)
        e.set_footer(text="FootballGroundMap.com")

        await self.fetch_more()
        if self.team_badge:
            e.colour = await get_colour(self.team_badge)
            e.set_thumbnail(url=self.team_badge)

        if self.image:
            e.set_image(url=self.image.replace(' ', '%20'))

        if self.current_home:
            e.add_field(name="Home to", value=", ".join(self.current_home), inline=False)

        if self.former_home:
            e.add_field(name="Former home to", value=", ".join(self.former_home), inline=False)

        # Location
        if self.map_link:
            e.add_field(name="Location", value=f"[{self.address}]({self.map_link})", inline=False)
        elif self.address != "Link to map":
            e.add_field(name="Location", value=self.address, inline=False)

        # Misc Data.
        e.description = ""
        for x, y in [("Capacity", self.capacity), ("Record Attendance", self.attendance_record),
                     ("Cost", self.cost), ("Website", self.website)]:
            if x:
                e.description += f"{x}: {y}\n"
        return e


async def get_stadiums(bot: 'Bot', query: str) -> List[Stadium]:
    """Fetch a list of Stadium objects matching a user query"""
    async with bot.session.get(f'https://www.footballgroundmap.com/search/{quote_plus(query)}') as resp:
        tree = html.fromstring(await resp.text())

    stadiums: List[Stadium] = []

    for i in tree.xpath(".//div[@class='using-grid'][1]/div[@class='grid']/div"):
        team = ''.join(i.xpath('.//small/preceding-sibling::a//text()')).title()
        badge = i.xpath('.//img/@src')[0]
        comp_info = i.xpath('.//small/a//text()')

        if not comp_info:
            continue

        country = comp_info.pop(0)
        league = comp_info[0] if comp_info else None

        sub_nodes = i.xpath('.//small/following-sibling::a')
        for s in sub_nodes:
            stad = Stadium(bot)
            stad.name = ''.join(s.xpath('.//text()')).title()
            stad.url = ''.join(s.xpath('./@href'))

            if query.lower() not in stad.name.lower() + team.lower():
                continue  # Filtering.

            if stad not in stadiums:
                stad.team = team
                stad.team_badge = badge
                stad.country = country
                stad.league = league
                stadiums.append(stad)

    return stadiums


async def fs_search(bot: 'Bot', interaction: Interaction, query: str, competitions: bool = False, teams: bool = False) \
        -> Competition | Team | Message:
    """Fetch a list of items from flashscore matching the user's query"""
    _query_raw = query

    for r in ["'", "[", "]", "#", '<', '>']:  # Fucking morons.
        query = query.replace(r, "")

    query = quote(query)
    # One day we could probably expand upon this if we ever figure out what the other variables are.
    async with bot.session.get(f"https://s.flashscore.com/search/?q={query}&l=1&s=1&f=1%3B1&pid=2&sid=1") as resp:
        res = await resp.text(encoding="utf-8")
        match resp.status:
            case 200:
                pass
            case _:
                print(f"HTTP {resp.status} error in fs_search")
                return await bot.error(interaction, f"HTTP Error {resp.status} when searching flashscore.")

    # Un-fuck FS JSON reply.
    res = res.lstrip('cjs.search.jsonpCallback(').rstrip(");")
    try:
        res = loads(res)
    except JSONDecodeError:
        print(f"Json error attempting to decode query: {query}\n", res, f"\nString that broke it: {_query_raw}")
        raise AssertionError('Something you typed broke the search query. Please only specify a team or league name.')

    results: List[Competition | Team] = []

    for i in res['results']:
        match i['participant_type_id']:
            case 0:
                if teams:
                    continue

                comp = bot.get_competition(i['id'])
                if not comp:
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
                if competitions:
                    continue

                team = bot.get_team(i['id'])
                if not team:
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
        return await bot.error(interaction, f"🚫 No results found for {query}")
    if len(results) == 1:
        return results[0]

    view = ObjectSelectView(bot, interaction, [('🏆', str(i), i.link) for i in results], timeout=30)
    await view.update()
    await view.wait()

    return None if view.value is None else results[view.value]
