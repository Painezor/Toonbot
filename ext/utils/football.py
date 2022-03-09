"""A Utility tool for fetching and structuring data from the Flashscore Website"""
from __future__ import annotations  # Cyclic Type Hinting

import asyncio
import datetime
import itertools
import json
import sys
import traceback
import urllib.parse
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from io import BytesIO
from json import JSONDecodeError
from typing import Union, List, Tuple, Dict

import aiohttp
from discord import Embed, HTTPException, NotFound, Colour, Interaction
from discord.ui import View, Select
from lxml import html
from pyppeteer.page import Page

from ext.utils import embed_utils, timed_events, view_utils, transfer_tools, image_utils

ADS = ['.//div[@class="seoAdWrapper"]', './/div[@class="banner--sticky"]', './/div[@class="box_over_content"]',
       './/div[@class="ot-sdk-container"]', './/div[@class="adsenvelope"]', './/div[@id="onetrust-consent-sdk"]',
       './/div[@id="lsid-window-mask"]', './/div[contains(@class, "isSticky")]', './/div[contains(@class, "rollbar")]',
       './/div[contains(@id,"box-over-content")]', './/div[contains(@class, "adsenvelope")]',
       './/div[contains(@class, "extraContent")]', './/div[contains(@class, "selfPromo")]',
       './/div[contains(@class, "otPlaceholder")]']

FLASHSCORE = 'http://www.flashscore.com'
INJURY_EMOJI = "<:injury:682714608972464187>"

# How many minutes a user has to wait between refreshes of the table within a command.
IMAGE_UPDATE_RATE_LIMIT = 1


class MatchEvent:
    """An object representing an event happening in a football fixture from Flashscore"""

    def __init__(self):
        self.note = ""
        self.player = None
        self.team = None
        self.time = None

    # If this is object is empty, consider it false.
    def __bool__(self):
        return bool([i for i in self.__dict__ if self.__dict__[i] is not None])

    def __str__(self):
        return str(self.__dict__)

    def __repr__(self):
        return f"Event({self.__dict__})"


class Substitution(MatchEvent):
    """A substitution event for a fixture"""

    def __init__(self):
        super().__init__()
        self.player_off = None
        self.player_on = None

    def __str__(self):
        if self.player_off is None or not self.player_off:
            self.player_off = "?"
        if self.player_on is None or not self.player_on:
            self.player_on = "?"

        return f"`🔄 {self.time}`: 🔻 {self.player_off} 🔺 {self.player_on} ({self.team})"

    def __repr__(self):
        return f"Substitution({self.__dict__})"


class Goal(MatchEvent):
    """A Generic Goal Event"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        ass = " " + self.assist if hasattr(self, 'assist') else ""
        note = " " + self.note if hasattr(self, 'note') else ""
        return f"`⚽ {self.time}`: {self.player}{ass}{note}"

    def __repr__(self):
        return f"Goal({self.__dict__})"


class OwnGoal(Goal):
    """An own goal event"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        note = " " + self.note if hasattr(self, 'note') else ""
        return f"`⚽ {self.time}`: {self.player} (Own Goal) {note}"

    def __repr__(self):
        return f"OwnGoal({self.__dict__})"


class Penalty(Goal):
    """A Penalty Event"""

    def __init__(self, missed=False):
        super().__init__()
        self.missed = missed

    @property
    def shootout(self):
        """If it ends with a ', it was during regular time"""
        return False if self.time.endswith('\'') else True

    def __str__(self):
        icon = "⚽" if self.missed is False else "❌"
        time = "" if self.shootout is True else " " + self.time
        return f"`{icon}{time}`: {self.player}"

    def __repr__(self):
        return f"Penalty({self.__dict__})"


class RedCard(MatchEvent):
    """An object representing the event of a dismissal of a player"""

    def __init__(self, second_yellow=False):
        super().__init__()
        self.second_yellow = second_yellow

    def __str__(self):
        ico = "🟨🟥" if self.second_yellow else "🟥"
        note = " " + self.note if hasattr(self, "note") and "Yellow card / Red card" not in self.note else ""
        return f"`{ico} {self.time}`: {self.player}{note}"

    def __repr__(self):
        return f"RedCard({self.__dict__})"


class Booking(MatchEvent):
    """An object representing the event of a player being given a yellow card"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        note = " " + self.note if hasattr(self, "note") and "Yellow Card" not in self.note else ""
        return f"`🟨 {self.time}`: {self.player}{note}"

    def __repr__(self):
        return f"Booking({self.__dict__})"


class VAR(MatchEvent):
    """An Object Representing the event of a Video Assistant Referee Review Decision"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        note = " " + self.note if hasattr(self, "note") else ""
        return f"`📹 {self.time}`: VAR Review: {self.player}{note}"

    def __repr__(self):
        return f"VAR({self.__dict__})"


@dataclass
class GameTime:
    """A class representing a game state"""

    def __init__(self, value: Union[str, datetime.datetime], fixture: Fixture):
        self.value = value
        self.fixture = fixture

    @property
    def state(self) -> str:
        """Return the state of the game."""
        if isinstance(self.value, datetime.datetime):
            if self.value < datetime.datetime.now() or self.fixture.score_home != 0 or self.fixture.score_away != 0:
                return "Full Time"
            return timed_events.Timestamp(self.value).datetime
        elif "+" in self.value:
            return "Stoppage Time"
        elif self.value.endswith("'") or self.value == "Live":
            return "Live"
        elif self.value.startswith("Extra Time"):
            return "Extra Time"
        elif self.value in ["Interrupted", "Delayed", "Half Time", "Postponed", "Cancelled", "after pens", "Awaiting",
                            "Abandoned", "Break Time", "Penalties"]:
            return self.value
        elif self.value == "fin":
            return "Full Time"
        elif self.value == "after extra time":
            return "AET"
        else:
            print("Unhandled GameTime state for value", self.value)

    def __str__(self):
        """Return the actual time of the game."""
        if self.state == "Full Time":
            return "FT"
        if isinstance(self.value, datetime.datetime):
            return self.relative_time
        elif self.value.isdigit():
            return self.value
        elif "+" in self.value:  # Stoppage Time
            return self.value
        elif "'" in self.value or self.value == "Live":  # Live
            return self.value
        elif self.value.startswith("Extra Time"):
            return self.value.replace("Extra Time", "")
        elif self.value == "Break Time":
            return "Break"
        elif self.value == "Half Time":
            return "HT"
        elif self.value == "Postponed":
            return "PP"
        elif self.value == "Cancelled":
            return "Cancelled"
        elif self.value == "Awaiting":
            return "soon"
        elif self.value == "Penalties":
            return "PSO"
        elif self.value in ["Interrupted", "Delayed", "Abandoned"]:
            return self.value
        else:
            print("GameTime: Unhandled value -> time", self.value)
            return self.value

    @property
    def emote(self) -> str:
        """Colour coded icons for livescore page."""
        if self.state == "Live":
            return "🟢"
        if self.state in ["fin", "after extra time", "after pens"]:
            return "⚪"  # white Circle
        elif self.state in ["Postponed", 'cancelled', 'abandoned']:
            return "🔴"  # red
        elif self.state in ["Delayed", "Interrupted", "Cancelled", "Abandoned"]:
            return "🟠"  # Orange
        elif self.state == "Half Time":
            return "🟡"  # Yellow
        elif self.state in ["Extra Time", "Stoppage Time"]:
            return "🟣"  # Purple
        elif self.state == "Break Time":
            return "🟤"  # Brown
        elif self.state == "PSO":
            return "🔵"  # Blue
        elif isinstance(self.value, datetime.datetime) or self.state in ["sched", "Awaiting"] or self.state is None:
            return "⚫"  # Black
        else:
            print("Football.py: emote Unhandled state:", self.state)
            return "🔴"  # Red

    @property
    def embed_colour(self) -> int | Colour:
        """Get a colour for fixture embeds with this game state"""
        if isinstance(self.value, datetime.datetime) or self.state in ["sched", "awaiting"]:
            return 0x010101  # Black
        elif self.state in ["fin", "after extra time", "after pens"]:
            return 0xffffff  # White
        elif self.state in ["Postponed", 'Cancelled', 'abandoned']:
            return 0xFF0000  # Red
        elif self.state in ["Delayed", "Interrupted"]:
            return 0xff6700  # Orange
        elif self.state == "Half Time":
            return 0xFFFF00  # Yellow
        elif self.state in ["Extra Time", "Stoppage Time"]:
            return 0x9932CC  # Purple
        elif self.state == "Break":
            return 0xA52A2A  # Brown
        elif self.state == "penalties":
            return 0x4285F4  # Blue
        elif self.state == "Live":
            return 0x00FF00  # Green
        else:
            print("Football.py: embed_colour Unhandled state:", self.state)
            return 0xFF0000  # Red

    @property
    def relative_time(self):
        """Discord Native TimeStamping"""
        if not isinstance(self.value, datetime.datetime):
            return self.value
        return timed_events.Timestamp(self.value).time_relative

    @property
    def reddit_time(self):
        """Standard Markdown Timestamps for Reddit"""
        if not isinstance(self.value, datetime.datetime):
            return self.value

        dtn = datetime.datetime.now()
        return self.value.strftime('%a %d %b') if self.value < dtn else self.value.strftime('%a %d %b %H:%M')


@dataclass
class FlashScoreSearchResult:
    """A generic object representing the result of a Flashscore search"""
    name: str = None
    url: str = None
    logo_url: str = None
    id: str = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @property
    def markdown(self):
        """Shorthand for FSR mark-down link"""
        return f"[{self.name}]({self.link})"

    @property
    def link(self):
        """Alias to self.url, polymorph for subclasses."""
        return self.url

    @property
    async def base_embed(self) -> Embed:
        """A discord Embed representing the flashscore search result"""
        e = Embed()

        if isinstance(self, Team):
            try:
                e.title = self.name.split('(')[0]
            except AttributeError:
                pass
        else:
            try:
                e.title = str(self)
            except (ValueError, AttributeError):
                pass

        if self.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + self.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        return e

    async def get_fixtures(self, page, subpage=""):
        """Get all upcoming fixtures related to the Flashscore search result"""
        src = await page.browser.fetch(page, self.link + subpage, './/div[@class="sportName soccer"]')

        if src is None:
            return None

        tree = html.fromstring(src)

        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            self.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if ".png" in _:
                self.logo_url = _

        # Iterate through to generate data.
        comp = None
        fixtures = []

        for i in tree.xpath('.//div[contains(@class,"sportName soccer")]/div'):
            fixture = Fixture(competition=comp)
            try:
                fx_id = i.xpath("./@id")[0]
                fixture.id = fx_id.split("_")[-1]
                fixture.url = "http://www.flashscore.com/match/" + fixture.id
            except IndexError:
                # This (might be) a header row.
                if "event__header" in i.classes:
                    country, league = i.xpath('.//div[contains(@class, "event__title")]//text()')
                    league = league.split(' - ')[0]
                    comp = Competition(country=country, name=league)
                continue

            # score
            home, away = i.xpath('.//div[contains(@class,"event__participant")]/text()')
            fixture.home = home.strip()
            fixture.away = away.strip()

            try:
                score_home, score_away = i.xpath('.//div[contains(@class,"event__score")]//text()')
                fixture.score_home = int(score_home.strip())
                fixture.score_away = int(score_away.strip())
            except ValueError:
                pass

            time = "".join(i.xpath('.//div[@class="event__time"]//text()'))
            for x in ["Pen", 'AET', 'FRO', 'WO']:
                time = time.replace(x, '')

            if "'" in time:
                time = f"⚽ LIVE! {time}"
            elif not time:
                time = "?"
            elif "Postp" in time:
                time = "⏸ Postponed "
            elif "Abn" in time:
                time = "🚫 Abandoned"
            elif "Awrd" in time:
                try:
                    time = datetime.datetime.strptime(time.strip('Awrd'), '%d.%m.%Y')
                except ValueError:
                    time = datetime.datetime.strptime(time.strip('Awrd'), '%d.%m. %H:%M')
                time = time.strftime("%d.%m.%Y")
                time = f"{time} 🚫 FF"  # Forfeit
            else:
                try:  # Should be dd.mm hh:mm or dd.mm.yyyy

                    time = datetime.datetime.strptime(time, '%d.%m.%Y')
                    if time.year != datetime.datetime.now().year:
                        time = time.strftime("%d.%m.%Y")
                except ValueError:
                    dtn = datetime.datetime.now()
                    try:
                        time = datetime.datetime.strptime(f"{dtn.year}.{time}", '%Y.%d.%m. %H:%M')
                    except ValueError:
                        time = datetime.datetime.strptime(f"{dtn.year}.{dtn.day}.{dtn.month}.{time}", '%Y.%d.%m.%H:%M')

                    if subpage == "/fixtures":
                        # Fixtures: Year Correction - if in the Past, increase by one year.
                        if time < datetime.datetime.now():
                            time = time.replace(year=time.year + 1)
            fixture.time = GameTime(time, fixture=fixture)
            fixtures.append(fixture)
        return fixtures

    def view(self, interaction: Interaction, page):
        """This should always be subject to polymorphism."""
        return View()

    async def pick_recent_game(self, interaction: Interaction, page, upcoming=False):
        """Choose from recent games from FlashScore Object"""
        subpage = "/fixtures" if upcoming else "/results"
        items = await self.get_fixtures(page, subpage)

        _ = [("⚽", f"{i.home} {i.score} {i.away}", f"{i.competition}") for i in items]

        if not _:
            await interaction.client.error(interaction, f"No recent games found")
            return None

        view = view_utils.ObjectSelectView(interaction, objects=_, timeout=30)
        _ = "an upcoming" if upcoming else "a recent"
        await view.update(content=f'⏬ Please choose {_} game.')
        await view.wait()

        if view.value is None:
            return None

        return items[view.value]


@dataclass
class Team(FlashScoreSearchResult):
    """An object representing a Team from Flashscore"""
    name: str = None
    id: str = None
    url: str = None
    logo_url: str = None

    @property
    def emoji(self):
        """Emoji for Select dropdowns"""
        return '👕'

    @property
    def link(self):
        """Long form forced url"""
        if self.url is not None and "://" not in self.url:
            # Example Team URL: https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
            return f"https://www.flashscore.com/team/{self.url}/{self.id}"
        else:
            return self.url

    @classmethod
    async def by_id(cls, team_id: str, page: Page):
        """Create a Team object from it's Flashscore ID"""
        url = "http://flashscore.com/?r=3:" + team_id
        await page.browser.fetch(page, url, "body")
        url = await page.evaluate("() => window.location.href")
        return cls(url=url, id=team_id)

    async def get_players(self, page: Page) -> List[Player]:
        """Get a list of players for a Team"""
        xp = './/div[contains(@class,"playerTable")]'
        src = await page.browser.fetch(page, self.link + "/squad", xp)

        if src is None:
            return []

        tree = html.fromstring(src)
        # tab += 1  # tab is Indexed at 0 but xpath indexes from [1]
        rows = tree.xpath(f'.//div[contains(@class, "squad-table")][contains(@id, "overall-all-table")]'
                          f'//div[contains(@class,"profileTable__row")]')

        players = []
        position = ""

        for i in rows:
            pos = "".join(i.xpath('./div/text()')).strip()
            if pos:  # The way the data is structured contains a header row with the player's position.
                try:
                    position = pos.strip('s')
                except IndexError:
                    position = pos
                continue  # There will not be additional data.

            pl = Player(team=self, position=position)
            name = "".join(i.xpath('.//div[contains(@class,"")]/a/text()'))
            try:  # Name comes in reverse order.
                surname, forename = name.split(' ', 1)
                name = f"{forename} {surname}"
            except ValueError:
                pass

            pl.name = name
            pl.country = "".join(i.xpath('.//span[contains(@class,"flag")]/@title'))
            pl.flag = transfer_tools.get_flag(pl.country)

            number = "".join(i.xpath('.//div[@class="tableTeam__squadNumber"]/text()'))
            try:
                pl.number = int(number)
            except ValueError:
                pl.number = 00

            try:
                age, _, g, _, _ = i.xpath(
                    './/div[@class="playerTable__icons playerTable__icons--squad"]//div/text()')
                pl.age = age
                pl.goals = int(g)
            except ValueError:
                continue

            injury = "".join(i.xpath('.//span[contains(@title,"Injury")]/@title'))
            pl.injury = injury
            pl.url = f"http://www.flashscore.com" + "".join(i.xpath('.//div[contains(@class,"")]/a/@href'))
            players.append(pl)
        return players

    def view(self, interaction: Interaction, page):
        """Return a view representing this Team"""
        return TeamView(interaction, self, page)


@dataclass
class Competition(FlashScoreSearchResult):
    """An object representing a Competition on Flashscore"""
    name: str = None
    country: str = None
    logo_url: str = None
    url: str = None
    fixtures: Dict[str, Fixture] = field(default_factory=defaultdict)

    def __init__(self, **kwargs):
        # Aliases
        self.name = kwargs.get("league", "")
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)

    async def update_fixture(self, bot, new_fixture: Fixture):
        """Update one of the competition's fixtures"""
        # url = new_fixture.url
        # self.fixtures[url].set_score(bot, new_fixture.score_home)
        # self.fixtures[url].set_score(bot, new_fixture.score_away, home=False)
        # self.fixtures[url].update_time(new_fixture.time)

        # Set Red Cards
        # fx.set_cards(self.bot, new_fixture.home_cards)
        # fx.set_cards(self.bot, new_fixture.away_cards, home=False)

    @classmethod
    async def by_id(cls, comp_id, page):
        """Create a Competition object based on the Flashscore ID of the competition"""
        url = "http://flashscore.com/?r=2:" + comp_id
        src = await page.browser.fetch(page, url, ".//div[@class='team spoiler-content']")
        tree = html.fromstring(src)

        country = tree.xpath('.//h2[@class="tournament"]/a[2]//text()')[0].strip()
        league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
        obj = cls(url=url, country=country, league=league)
        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            obj.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if _:
                print(f"Invalid logo_url: {_}")
        return obj

    def __str__(self):
        return f"{self.country.upper()}: {self.name}"

    @property
    def emoji(self):
        """Emoji for Select Dropdowns"""
        return '🏆'

    @property
    def link(self):
        """Long form URL"""
        if self.url is not None and "://" not in self.url:
            return f"https://www.flashscore.com/soccer/{self.country.lower().replace(' ', '-')}/{self.url}"
        else:
            return self.url

    @classmethod
    async def by_link(cls, link, page):
        """Create a Competition Object from a flashscore url"""
        assert "flashscore" in link[:25].lower(), "Invalid URL provided. Please make sure this is a flashscore link."
        assert link.count('/') > 3, "Invalid URL provided. Please make sure this is a flashscore link to a competition."

        src = await page.browser.fetch(page, link, xpath=".//div[@class='team spoiler-content']")
        tree = html.fromstring(src)

        try:
            country = tree.xpath('.//h2[@class="breadcrumb"]//a/text()')[-1].strip()
            league = tree.xpath('.//div[@class="heading__name"]//text()')[0].strip()
            title = f"{country.upper()}: {league}"
        except IndexError:
            print(f'Error fetching Competition country/league by_link - {link}')
            title = "Unidentified League"

        comp = cls(url=link, title=title)
        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')

        try:
            comp.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if ".png" in _:
                comp.logo_url = _

        return comp

    async def get_table(self, page) -> BytesIO:
        """Fetch the table from a flashscore page and return it as a BytesIO object"""
        xp = './/div[contains(@class, "tableWrapper")]/parent::div'
        table_image = await page.browser.fetch(page, self.link + "/standings/", xp, delete=ADS, screenshot=True)
        tree = html.fromstring(await page.content())

        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            self.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if ".png" in _:
                self.logo_url = _

        return table_image

    async def get_scorers(self, page) -> List[Player]:
        """Fetch a list of scorers from a Flashscore Competition page returned as a list of Player Objects"""
        xp = ".//div[@class='tabs__group']"
        clicks = ['a[href$="top_scorers"]', 'div[class^="showMore"]']
        uri = self.link + "/standings"
        src = await page.browser.fetch(page, uri, xp, clicks=clicks, delete=ADS)

        if src is None:
            return []

        try:
            tree = html.fromstring(src)
        except Exception as e:
            print(f'GET_SCORERS ERROR LOG: Tried to access get_scorers of competition {uri}')
            raise e

        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            self.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if ".png" in _:
                self.logo_url = _

        hdr = tree.xpath('.//div[contains(@class,"table__headerCell")]/div/@title')
        if "Team" in hdr:
            return []

        rows = tree.xpath('.//div[contains(@class,"table__body")]/div')

        players = []
        for i in rows:
            items = i.xpath('.//text()')
            items = [i.strip() for i in items if i.strip()]
            links = i.xpath(".//a/@href")
            try:
                player_link, team_link = ["http://www.flashscore.com" + i for i in links]
            except ValueError:
                player_link, team_link = ("http://www.flashscore.com" + links[0], "") if links else ("", "")

            try:
                rank, name, tm, goals, assists = items
            except ValueError:
                try:
                    rank, name, tm, goals, assists = items + [0]
                except ValueError:
                    try:
                        rank, name, goals, tm, assists = items + ["", 0]
                    except ValueError:
                        continue

            country = "".join(i.xpath('.//span[contains(@class,"flag")]/@title')).strip()
            flag = transfer_tools.get_flag(country)
            team = Team(name=tm, url=team_link)
            players.append(Player(competition=self, rank=rank, flag=flag, name=name, url=player_link, team=team,
                                  country=country, goals=int(goals), assists=int(assists)))
        return players

    def view(self, interaction: Interaction, page):
        """Return a view representing this Competition"""
        return CompetitionView(interaction, self, page)


@dataclass
class Fixture:
    """An object representing a Fixture from the Flashscore Website"""
    # Unique Identification
    id: str = None
    url: str = None

    # Scores Loop Expiration
    expires: int = None

    # Set and forget
    competition: Competition = None
    referee: str = None
    kickoff: str = None
    stadium: str = None

    # Participants
    home: Team = None
    away: Team = None

    # Dynamic data
    time: GameTime = None
    score_home: int = 0
    score_away: int = 0
    home_cards: int = None
    away_cards: int = None

    events: List[MatchEvent] = field(default_factory=list)

    penalties_home: int = None
    penalties_away: int = None
    infobox: str = None
    attendance: int = None

    images: dict = None  # {'stats': {'image': "http..", 'last_refresh': datetime}, formations: {}, photos:{}, table:{}}

    state: str = None  # Being deprecated.

    # Usually non-changing.
    periods: int = 2
    breaks: int = 0

    # Dispatched Events
    dispatched: dict = field(default_factory=dict)

    # Image lookups
    table: Tuple[str, datetime.datetime] = (None, None)
    stats: Tuple[str, datetime.datetime] = (None, None)
    formation: Tuple[str, datetime.datetime] = (None, None)

    @property
    def emoji(self):
        """Property used for dropdowns."""
        return '⚽'

    def __eq__(self, other):
        if self.id is not None:
            return self.id == other.id
        else:
            return self.url == other.url

    def __str__(self):
        return f"{self.time.relative_time}: [{self.bold_score}]({self.link})"

    def set_cards(self, bot, new_value: int, home=True):
        """Update red cards & dispatch event."""
        if new_value is None:
            return

        target_var = "home_cards" if home else "away_cards"
        old_value = getattr(self, target_var)
        if new_value == old_value:
            return

        if new_value == old_value or None in [old_value, new_value]:
            return

        event = "red_card" if new_value > old_value else "var_red_card"
        bot.dispatch("fixture_event", event, self, home=home)
        setattr(self, target_var, new_value)

    def set_score(self, bot, new_value, home=True):
        """Update scores & dispatch goal events"""
        target_var = "score_home" if home else "score_away"
        old_value = getattr(self, target_var)
        if new_value == old_value or None in [old_value, new_value]:
            return

        event = "goal" if new_value > old_value else "var_goal"
        bot.dispatch("fixture_event", event, self, home=home)
        setattr(self, target_var, new_value)

    def update_time(self, game_time: GameTime):
        """Update the time of the event"""
        if game_time != self.time:
            print(f"TIME CHANGE: {self.time} -> {game_time}")
            self.time = game_time

    def update_state(self, bot, new_state):
        """Set event state & dispatch appropriate events."""
        if self.state == new_state or self.state is None:
            return

        old_state = self.state
        self.state = new_state

        if new_state == "awaiting":
            return  # discard.

        if new_state == "live":
            if old_state in ["sched", "delayed"]:
                return bot.dispatch("fixture_event", "kick_off", self)
            elif old_state == "ht":
                return bot.dispatch("fixture_event", "half_time", self)
            elif old_state == "interrupted":
                return bot.dispatch("fixture_event", "resumed", self)
            elif old_state == "break time":
                return bot.dispatch("fixture_event", f"start_of_period_{self.breaks + 1}", self)
        elif new_state in ["interrupted", "abandoned", "postponed", "cancelled", "delayed"]:
            return bot.dispatch("fixture_event", new_state, self)
        elif new_state == "sched":
            if old_state in ["delayed", "postponed"]:
                return bot.dispatch("fixture_event", "postponed", self)
        elif new_state == "fin":
            if old_state in ["sched", "fin", "ht", "awaiting"]:
                return bot.dispatch("fixture_event", "final_result_only", self)
            elif old_state == "live":
                return bot.dispatch("fixture_event", "full_time", self)
            elif old_state == "extra time":
                return bot.dispatch("fixture_event", "score_after_extra_time", self)
        elif new_state == "after extra time":
            return bot.dispatch("fixture_event", "score_after_extra_time", self)
        elif new_state == "after pens":
            return bot.dispatch("fixture_event", "penalty_results", self)
        elif new_state == "ht":
            mode = "ht_et_begin" if old_state == "extra time" else "half_time"
            return bot.dispatch("fixture_event", mode, self)
        elif new_state == "break time":
            self.breaks += 1
            if old_state == "live":
                event = "end_of_normal_time" if self.periods == 2 else f"end_of_period{self.breaks}"
                return bot.dispatch("fixture_event", event, self)
            elif old_state == "extra time":
                return bot.dispatch("fixture_event", "end_of_extra_time", self)
        elif new_state == "extra time":
            if old_state == "break time":
                return bot.dispatch("fixture_event", "extra_time_begins", self)
            elif old_state == "ht":
                return bot.dispatch("fixture_event", "ht_et_end", self)
            elif old_state == "live":
                return bot.dispatch("fixture_event", "extra_time_begins", self)
        elif new_state == "penalties":
            return bot.dispatch("fixture_event", "penalties_begin", self)

        print(f'Unhandled State change: {self.url} | {old_state} -> {new_state}')

    @classmethod
    async def by_id(cls, match_id, page):
        """Create a fixture object from the flashscore match ID"""
        fixture = cls(id=match_id)
        url = "http://www.flashscore.com/match/" + match_id
        fixture.url = url
        src = await page.browser.bot.fetch(page, url, xpath=".//div[@class='team spoiler-content']")
        tree = html.fromstring(src)

        ko = "".join(tree.xpath(".//div[contains(@class, 'startTime')]/div/text()"))
        fixture.time = GameTime(datetime.datetime.strptime(ko, "%d.%m.%Y %H:%M"), fixture=fixture)

        fixture.home = "".join(tree.xpath('.//div[contains(@class, "Participant__home")]//a/text()')).strip()
        fixture.away = "".join(tree.xpath('.//div[contains(@class, "Participant__away")]//a/text()')).strip()
        return fixture

    @property
    def link(self):
        """Alias to self.url"""
        return self.url

    @property
    async def base_embed(self) -> Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e = Embed(title=f"{self.home} {self.score} {self.away}", url=self.link, colour=self.time.embed_colour)
        e.set_author(name=f"{self.competition.country}: {self.competition.name}")
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)

        if isinstance(self.time, datetime.datetime):
            if self.time > datetime.datetime.now():
                e.description = f"Kickoff: {timed_events.Timestamp(self.time).time_relative}"
        elif self.time == "Postponed":
            e.description = "This match has been postponed."
        else:
            if not isinstance(self.time, datetime.datetime):
                e.set_footer(text=self.state)
        return e

    @property
    def event_footer(self):
        """A string containing Country: League and time"""
        return f"{self.competition.country}: {self.competition.name}"

    @property
    def score(self) -> str:
        """Concatenate scores into home - away format"""
        return "vs" if self.score_home is None else f"{self.score_home} - {self.score_away}"

    @property
    def bold_score(self) -> str:
        """Embolden the winning team of a fixture"""
        if self.score_home is None or self.score_away is None:
            return f"{self.home} vs {self.away}"

        hb, ab = ('**', '') if self.score_home > self.score_away else ('', '**')
        hb, ab = ("", "") if self.score_home == self.score_away else (hb, ab)
        return f"{hb}{self.home} {self.score_home}{hb} - {ab}{self.score_away} {self.away}{ab}"

    @property
    def live_score_text(self) -> str:
        """Return a preformatted string showing the score and any red cards of the fixture"""
        if self.penalties_home is not None:
            state = "After Pens" if self.state == "after pens" else "PSO"
            _ = self.time.emote

            ph, pa = self.penalties_home, self.penalties_away
            s = min(self.score_home, self.score_away)
            s = f"{s} - {s}"
            return f"`{_}` {state} {self.home} {ph} - {pa} {self.away} (FT: {s})"

        _ = '🟥'
        h_c = f"`{self.home_cards * _}` " if self.home_cards is not None else ""
        a_c = f" `{self.away_cards * _}`" if self.away_cards is not None else ""
        return f"`{self.time.emote}` {self.time} {h_c}[{self.bold_score}]({self.link}){a_c}"

    async def get_badge(self, page, team) -> BytesIO or None:
        """Fetch an image of a Team's Logo or Badge as a BytesIO object"""
        xp = f'.//div[contains(@class, "tlogo-{team}")]//img'
        return await page.browser.fetch(page, self.link, xp, screenshot=True)

    async def get_table(self, page) -> BytesIO or None:
        """Fetch an image of the league table appropriate to the fixture as a bytesIO object"""
        xp = './/div[contains(@class, "tableWrapper")]'
        link = self.link + "/#standings/table/overall"
        return await page.browser.fetch(page, link, xp, delete=ADS, screenshot=True)

    async def get_stats(self, page) -> BytesIO or None:
        """Get an image of a list of statistics pertaining to the fixture as a BytesIO object"""
        xp = ".//div[contains(@class, 'statRow')]"
        link = self.link + "/#match-summary/match-statistics/0"
        return await page.browser.fetch(page, link, xp, delete=ADS, screenshot=True)

    async def get_formation(self, page) -> BytesIO or None:
        """Get the formations used by both teams in the fixture"""
        xp = './/div[contains(@class, "fieldWrap")]'
        fm = await page.browser.fetch(page, self.link + "/#match-summary/lineups", xp, delete=ADS, screenshot=True)
        xp = './/div[contains(@class, "lineUp")]'
        lineup = await page.browser.fetch(page, self.link + "/#match-summary/lineups", xp, delete=ADS, screenshot=True)

        valid_images = [i for i in [fm, lineup] if i is not None]
        if not valid_images:
            return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, image_utils.stitch_vertical, valid_images)

    async def get_summary(self, page) -> BytesIO or None:
        """Fetch the summary of a Fixture"""
        xp = ".//div[contains(@class, 'verticalSections')]"
        summary = await page.browser.fetch(page, self.link + "#match-summary", xp, delete=ADS, screenshot=True)
        return summary

    async def head_to_head(self, page) -> dict:
        """Get results of recent games related to the two teams in the fixture"""
        xp = ".//div[@class='h2h']"
        src = await page.browser.fetch(page, self.link + "/#h2h/overall", xp, delete=ADS)
        tree = html.fromstring(src)
        games = {}

        for i in tree.xpath('.//div[contains(@class, "section")]'):
            header = "".join(i.xpath('.//div[contains(@class, "title")]//text()')).strip().title()
            if not header:
                continue

            fixtures = i.xpath('.//div[contains(@class, "_row")]')
            fx_list = []
            for game in fixtures[:5]:  # Last 5 only.
                fx = Fixture()
                fx.url = game.xpath(".//@onclick")
                fx.home = "".join(game.xpath('.//span[contains(@class, "homeParticipant")]//text()')).strip().title()
                fx.away = "".join(game.xpath('.//span[contains(@class, "awayParticipant")]//text()')).strip().title()
                time = game.xpath('.//span[contains(@class, "date")]/text()')[0].strip()

                try:
                    time = datetime.datetime.strptime(time, "%d.%m.%y")
                except ValueError:
                    print("football.py: head_to_head", time, "format is not %d.%m.%y")
                fx.time = GameTime(time, fixture=fx)
                score_home, score_away = game.xpath('.//span[contains(@class, "regularTime")]//text()')[0].split(':')
                fx.score_home, fx.score_away = int(score_home.strip()), int(score_away.strip())

                fx_list.append(fx)
            games.update({header: fx_list})

        return games

    async def get_preview(self, page):
        """Fetch information about upcoming match from Flashscore"""
        xp = './/div[contains(@class, "previewOpenBlock")]/div//text()'

        clicks = ['div[class$="showMore"]']

        src = await page.browser.fetch(page, self.link, xp, clicks=clicks)
        tree = html.fromstring(src)

        preview_lines = tree.xpath('.//div[@class="previewLine"]')

        preview = ""

        r = f"**🙈 Referee**: {self.referee}" if hasattr(self, 'referee') else ""
        s = f"**🥅 Venue**: {self.stadium}" if hasattr(self, 'stadium') else ""
        if any([r, s]):
            preview += "####" + " | ".join([i for i in [r, s] if i]) + "\n\n"

        if preview_lines:
            preview += "# Match Preview\n\n"
        for block in preview_lines:
            this_block = "* " + "".join(block.xpath('.//text()')) + "\n"
            preview += this_block

        _ = tree.xpath('.//div[contains(text(), "Will not play")]/following-sibling::div//div[@class="lf__side"]')
        if _:
            nph, npa = _
            preview += "\n\n\n## Absent Players\n"

            home = []
            for _ in nph:
                ij = "".join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                home.append(player)

            away = []
            for _ in npa:
                ij = "".join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                away.append(player)

            rows = list(itertools.zip_longest(home, away))
            preview += f"{self.home}|{self.away}\n--:|:--\n"
            for a, b in rows:
                preview += f"{a} | {b}\n"

        _ = tree.xpath('.//div[contains(text(), "Questionable")]/following-sibling::div//div[@class="lf__side"]')
        if _:
            nph, npa = _
            preview += "\n\n\n## Potentially Absent Players\n"

            home = []
            for _ in nph:
                ij = "".join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                home.append(player)

            away = []
            for _ in npa:
                ij = "".join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FLASHSCORE + ''.join(_.xpath('.//a/@href'))}) {ij}"
                away.append(player)

            rows = list(itertools.zip_longest(home, away))
            preview += f"{self.home}|{self.away}\n--:|:--\n"
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
            tv_list = ["[" + "".join(_.xpath('.//text()')) + "](" + "".join(_.xpath('.//@href')) + ")" for _ in tv]
            preview += ", ".join(tv_list)

        return preview

    async def refresh(self, page, max_retry=3):
        """Perform an intensive full lookup for a fixture"""
        xp = ".//div[@id='utime']"

        for i in range(max_retry):
            try:
                src = await page.browser.fetch(page, self.link, xp)
                tree = html.fromstring(src)
                break
            except Exception as err:
                print(f'Retry ({i}) Error refreshing fixture {self.home} v {self.away}: {type(err)}')
        else:
            return

        # Some of these will only need updating once per match
        if self.kickoff is None:
            try:
                ko = "".join(tree.xpath(".//div[contains(@class, 'startTime')]/div/text()"))
                ko = datetime.datetime.strptime(ko, "%d.%m.%Y %H:%M")
            except ValueError:
                ko = ""
            try:
                self.kickoff = ko.strftime('%H:%M on %a %d %b %Y')
            except AttributeError:
                print(f"Could not convert string {self.kickoff} to strf time string.")

        if not hasattr(self, 'referee'):
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')
            ref = "".join([i for i in text if "referee" in i.lower()]).strip().replace('Referee:', '')
            venue = "".join([i for i in text if "venue" in i.lower()]).strip().replace('Venue:', '')
            if ref:
                self.referee = ref
            if venue:
                self.stadium = venue

        if self.competition.country is None or self.competition.name is None:
            self.competition.country = "".join(tree.xpath('.//span[contains(@class, "__country")]/text()')).strip()
            self.competition.name = "".join(tree.xpath('.//span[contains(@class, "__country")]/a/text()')).strip()
            _ = "".join(tree.xpath('.//span[contains(@class, "__country")]//a/@href'))
            self.competition.url = "http://www.flashscore.com" + _

        # Grab infobox
        ib = tree.xpath('.//div[contains(@class, "infoBoxModule")]/div[contains(@class, "info__")]/text()')
        if ib:
            self.infobox = "".join(ib)
            if self.infobox.startswith('Format:'):
                fmt = self.infobox.split(': ')[-1]
                periods = fmt.split('x')[0]
                self.periods = int(periods)

        event_rows = tree.xpath('.//div[contains(@class, "verticalSections")]/div')
        events = []
        penalty_note = False

        for i in event_rows:
            event_class = i.attrib['class']
            # Detection for penalty mode, discard headers.
            if "Header" in event_class:
                parts = [x.strip() for x in i.xpath('.//text()')]
                if "Penalties" in parts:
                    try:
                        _, self.penalties_home, _, self.penalties_away = parts
                    except ValueError:
                        _, pen_string = parts
                        try:
                            self.penalties_home, self.penalties_away = pen_string.split(' - ')
                        except ValueError:
                            print(f"Too many parts for Penalties Parts split, found: {parts}, split: {pen_string}")
                    penalty_note = True
                continue

            # Detection of Teams
            if "home" in event_class:
                team = self.home
            elif "away" in event_class:
                team = self.away
            elif "empty" in event_class:
                continue  # No events in half signifier.
            else:
                print(f"No team found for event_class {event_class}")
                team = None

            node = i.xpath('./div[contains(@class, "incident")]')[0]  # event_node
            icon = "".join(node.xpath('.//div[contains(@class, "incidentIcon")]//svg/@class')).strip()
            _ = "".join(node.xpath('.//div[contains(@class, "incidentIcon")]//@title')).strip()
            event_desc = _.replace('<br />', ' ')
            icon_desc = "".join(node.xpath('.//div[contains(@class, "incidentIcon")]//svg//text()')).strip()

            p = f"icon: {icon}\nevent_desc: {event_desc}\n============================="

            if "goal" in icon.lower():
                if "Own" in icon:
                    event = OwnGoal()
                else:
                    _ = True if penalty_note else False
                    event = Penalty() if "penalty" in icon_desc.lower() else Goal()

                    if icon_desc:
                        if "Goal" not in icon_desc and "Penalty" not in icon_desc:
                            print(f"Goal | icon_desc: {icon_desc}\n{p}")

            elif "penaltyMissed" in icon:
                event = Penalty(missed=True)
                if icon_desc and icon_desc != "Penalty missed":
                    event.note = icon_desc
                    print(f"Penalty Miss | icon_desc: {icon_desc}\n{p}")
            elif "substitution" in icon:
                event = Substitution()
                event.player_off = "".join(node.xpath('.//div[contains(@class, "incidentSubOut")]/a/text()')).strip()
                try:
                    event.player_on = node.xpath('.//a[contains(@class, "playerName")]/text()')[0].strip()
                except IndexError:
                    event.player_on = ""
            elif "yellowCard" in icon:
                event = Booking()
                if icon_desc and "Yellow Card" not in icon_desc:
                    event.note = icon_desc
            elif "redYellow" in icon:
                event = RedCard(second_yellow=True)
                if "card / Red" not in icon_desc:
                    event.note = icon_desc
            elif "redCard" in icon or icon.startswith("card"):
                event = RedCard()
                if icon_desc != "Red Card":
                    event.note = icon_desc
            elif "var" in icon:
                event = VAR()
                icon_desc = icon_desc if icon_desc else "".join(node.xpath('./div//text()')).strip()
                if icon_desc:
                    event.note = icon_desc
            else:
                event = MatchEvent()
                print(self.link, 'Undeclared event type for', icon)

            # Data not always present.
            event.player = "".join(node.xpath('.//a[contains(@class, "playerName")]//text()')).strip()
            _ = "".join(node.xpath('.//div[contains(@class, "assist")]//text()'))
            if _:
                event.assist = _

            event.team = team
            event.time = "".join(node.xpath('.//div[contains(@class, "timeBox")]//text()')).strip()
            if event_desc:
                event.full_description = event_desc

            events.append(event)

        self.events = events
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')

    def view(self, interaction: Interaction, page):
        """Return a view representing this Fixture"""
        return FixtureView(interaction, self, page)


@dataclass
class Player:
    """An object representing a player from flashscore."""
    url: str = None
    id: str = None

    number: int = 0
    name: str = None
    position: str = None
    country: Union[str, List[str]] = None

    team: Team = None

    apps: int = 0
    goals: int = 0
    assists: int = 0

    injury: str = None

    def __init__(self, **kwargs):
        self.flag = None
        self.__dict__.update(kwargs)

    def __bool__(self):
        return bool(self.__dict__)

    @property
    def link(self):
        """Alias to self.url"""
        return self.url

    @property
    def squad_row(self):
        """String for Team Lineup."""
        out = ""
        if self.number is not None:
            out += f"`{str(self.number).rjust(2)}`: "

        inj = f" - <:injury:682714608972464187> {self.injury}" if self.injury else ""

        out += f"{self.flag} [{self.name}]({self.link}) ({self.position}{inj})"
        return out

    @property
    def scorer_row(self):
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        out = ""
        if hasattr(self, 'rank'):
            out += f"`{self.rank.rjust(3, ' ')}`"

        out += f"{self.flag} **[{self.name}]({self.link})** "

        if self.team is not None:
            out += f"([{self.team.name}]({self.team.link})) "

        out += f"{self.goals} Goal{'s' if self.goals != 1 else ''}"

        if self.assists is not None and self.assists > 0:
            out += f" ({self.assists} Assist{'s' if self.assists != 1 else ''})"
        return out

    @property
    def assist_row(self):
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        out = f"{self.flag} [**{self.name}**]({self.link}) "

        if self.team is not None:
            out += f"([{self.team.name}]({self.team.link})) "

        out += f" ({self.assists} Assist{'s' if self.assists != 1 else ''})"
        if self.goals is not None and self.goals > 0:
            out += f"{self.goals} Goal{'s' if self.goals != 1 else ''}"

        return out

    @property
    def injury_row(self):
        """Return a string with player & their injury"""
        return f"{self.flag} [{self.name}]({self.link}) ({self.position}): <:injury:682714608972464187> {self.injury}"


class FixtureView(View):
    """The View sent to users about a fixture."""

    def __init__(self, interaction: Interaction, fixture: Fixture, page):
        self.fixture = fixture
        self.interaction = interaction
        self.message = None

        self.page = page
        super().__init__()

        # Pagination
        self.pages = []
        self.index = 0
        self.base_embed = None
        self.semaphore = asyncio.Semaphore()

        # Button Disabling
        self._current_mode = None

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except HTTPException:
            pass

        self.stop()
        await self.page.close()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content=""):
        """Update the view for the user"""
        embed = self.pages[self.index]
        async with self.semaphore:
            self.clear_items()
            buttons = [view_utils.FuncButton(label="Stats", func=self.push_stats, emoji="📊"),
                       view_utils.FuncButton(label="Table", func=self.push_table),
                       view_utils.FuncButton(label="Lineups", func=self.push_lineups),
                       view_utils.FuncButton(label="Summary", func=self.push_summary),
                       view_utils.FuncButton(label="H2H", func=self.push_head_to_head, emoji="⚔"),
                       view_utils.StopButton()
                       ]

            for _ in buttons:
                _.disabled = True if self._current_mode == _.label else False
                self.add_item(_)

            if self.message is None:
                i = self.interaction
                self.message = await i.client.reply(i, content=content, view=self, embed=embed)
            else:
                await self.message.edit(content=content, view=self, embed=embed)

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.fixture.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)

    async def push_stats(self):
        """Push Stats to View"""
        self._current_mode = "Stats"
        self.index = 0

        dtn = datetime.datetime.now()
        image, ts = self.fixture.stats
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            image = await self.fixture.get_stats(page=self.page)
            self.fixture.stats = (await image_utils.dump_image(self.interaction, image), dtn)

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else Embed.Empty)
        embed.url = self.page.url
        embed.description += "No Stats Found" if image is None else ""
        embed.title = f"{self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_lineups(self):
        """Push Lineups to View"""
        self._current_mode = "Lineups"
        self.index = 0

        dtn = datetime.datetime.now()
        image, ts = self.fixture.formation
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            image = await self.fixture.get_formation(page=self.page)
            self.fixture.formation = (await image_utils.dump_image(self.interaction, image), dtn)

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else Embed.Empty)
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        embed.description += "No Lineups Found" if image is None else ""
        embed.title = f"≡ Lineups for {self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_table(self):
        """Push Table to View"""
        self._current_mode = "Table"
        self.index = 0

        dtn = datetime.datetime.now()
        image, ts = self.fixture.table
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            image = await self.fixture.get_table(page=self.page)
            self.fixture.table = (await image_utils.dump_image(self.interaction, image), dtn)

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else Embed.Empty)
        embed.url = self.page.url
        embed.description += "No Table Found" if image is None else ""
        embed.title = f"{self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_summary(self):
        """Push Summary to View"""
        self._current_mode = "Summary"
        self.index = 0

        dtn = datetime.datetime.now()
        image, ts = self.fixture.summary
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            image = await self.fixture.get_summary(page=self.page)
            self.fixture.summary = (await image_utils.dump_image(self.interaction, image), dtn)

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else Embed.Empty)
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        embed.description += "No Summary Found" if image is None else ""
        embed.title = f"{self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_head_to_head(self):
        """Push Head-to-Head to View"""
        self._current_mode = "Head To Head"
        self.index = 0
        fixtures = await self.fixture.head_to_head(page=self.page)

        embed = await self.get_embed()
        embed.title = f"{self.fixture.home} {self.fixture.score} {self.fixture.away}"
        embed.url = self.page.url
        for k, v in fixtures.items():
            x = "\n".join([f"{i.time.relative_time} [{i.bold_score}]({i.url})" for i in v])
            embed.add_field(name=k, value=x, inline=False)
        self.pages = [embed]
        await self.update()


class CompetitionView(View):
    """The view sent to a user about a Competition"""

    def __init__(self, interaction: Interaction, competition: Competition, page):
        super().__init__()
        self.page = page
        self.interaction = interaction
        self.competition = competition
        self.message = None
        self.players = []
        self.semaphore = asyncio.Semaphore()

        # Embed and internal index.
        self.base_embed = None
        self.pages = []
        self.index = 0

        # Button Disabling
        self._current_mode = None

        # Player Filtering
        self.nationality_filter = None
        self.team_filter = None
        self.filter_mode = "goals"

        # Rate Limiting
        self.table_timestamp = None
        self.table_image = None

    async def on_error(self, error, item, interaction: Interaction):
        """Error logging"""
        print(f"Error in Competition View\n"
              f"Competition Info:\n"
              f"{self.competition.__dict__}\n"
              f"View Children")
        for x in self.children:
            print(x.__dict__)
        raise error

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except (HTTPException, AttributeError):
            pass

        self.stop()
        await self.page.close()

    async def update(self, content=""):
        """Update the view for the Competition"""
        if self.message is None:
            return await self.on_timeout()

        async with self.semaphore:
            self.clear_items()
            if self.filter_mode is not None:
                await self.filter_players()

            if self.pages and len(self.pages) > 1:
                self.add_item(view_utils.PreviousButton(disabled=True if self.index == 0 else False))
                self.add_item(view_utils.PageButton(label=f"Page {self.index + 1} of {len(self.pages)}",
                                                    disabled=True if len(self.pages) == 1 else False))
                self.add_item(view_utils.NextButton(disabled=True if self.index == len(self.pages) - 1 else False))

            if self.filter_mode is not None:
                all_players = [('👕', str(i.team), str(i.team.link)) for i in self.players]
                teams = set(all_players)
                teams = sorted(teams, key=lambda x: x[1])  # Sort by second Value.

                if teams and len(teams) < 26:
                    _ = "Filter by Team..."
                    _ = view_utils.MultipleSelect(placeholder=_, options=teams, attribute='team_filter', row=2)
                    if self.team_filter is not None:
                        _.placeholder = f"Teams: {', '.join(self.team_filter)}"
                    self.add_item(_)

                flags = set([(transfer_tools.get_flag(i.country, unicode=True), i.country, "") for i in self.players])
                flags = sorted(flags, key=lambda x: x[1])  # Sort by second Value.

                if flags and len(flags) < 26:
                    ph = "Filter by Nationality..."
                    _ = view_utils.MultipleSelect(placeholder=ph, options=flags, attribute='nationality_filter', row=3)
                    if self.nationality_filter is not None:
                        _.placeholder = f"Countries:{', '.join(self.nationality_filter)}"
                    self.add_item(_)

            items = [view_utils.FuncButton(label="Table", func=self.push_table, emoji="🥇", row=4),
                     view_utils.FuncButton(label="Scorers", func=self.push_scorers, emoji='⚽', row=4),
                     view_utils.FuncButton(label="Fixtures", func=self.push_fixtures, emoji='📆', row=4),
                     view_utils.FuncButton(label="Results", func=self.push_results, emoji='⚽', row=4),
                     view_utils.StopButton(row=4)
                     ]

            for _ in items:
                _.disabled = True if self._current_mode == _.label else False
                self.add_item(_)

            try:
                embed = self.pages[self.index]
            except IndexError:
                embed = None if self.index == 0 else self.pages[0]

            if self.message is None:
                i = self.interaction
                self.message = await i.client.reply(i, content=content, view=self, embed=embed)
            try:
                await self.message.edit(content=content, view=self, embed=embed)
            except HTTPException:
                return
        await self.wait()

    async def filter_players(self):
        """Filter player list according to dropdowns."""
        embed = await self.get_embed()
        players = await self.get_players()

        if self.nationality_filter is not None:
            players = [i for i in players if i.country in self.nationality_filter]
        if self.team_filter is not None:
            players = [i for i in players if i.team in self.team_filter]

        if self.filter_mode == "goals":
            srt = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
            embed.title = f"≡ Top Scorers for {embed.title}"
            rows = [i.scorer_row for i in srt]
        elif self.filter_mode == "assists":
            srt = sorted([i for i in players if i.assists > 0], key=lambda x: x.assists, reverse=True)
            embed.title = f"≡ Top Assists for {embed.title}"
            rows = [i.assist_row for i in srt]
        else:
            rows = []

        if not rows:
            rows = [f'```yaml\nNo Top Scorer Data Available matching your filters```']

        embeds = embed_utils.rows_to_embeds(embed, rows, rows_per=None)
        self.pages = embeds

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.competition.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)

    async def get_players(self):
        """Grab the list of players"""
        self.players = await self.competition.get_scorers(page=self.page) if not self.players else self.players
        return self.players

    async def push_table(self):
        """Push Table to View"""
        dtn = datetime.datetime.now()
        ts = self.table_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.competition.get_table(page=self.page)
            self.table_image = await image_utils.dump_image(self.interaction, img)
            self.table_timestamp = datetime.datetime.now()

        embed = await self.get_embed()
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition}"
        if self.table_image is not None:
            embed.set_image(url=self.table_image)
            embed.description = timed_events.Timestamp().long
        else:
            embed.description = "No Table Found"

        self.pages = [embed]
        self.index = 0
        self._current_mode = "Table"
        self.filter_mode = None
        await self.update()

    async def push_scorers(self):
        """PUsh the Scorers Embed to View"""
        self.index = 0
        self.filter_mode = "goals"
        self._current_mode = "Scorers"
        self.nationality_filter = None
        self.team_filter = None
        await self.update()

    async def push_assists(self):
        """PUsh the Scorers Embed to View"""
        self.index = 0
        self.filter_mode = "assists"
        self._current_mode = "Assists"
        self.nationality_filter = None
        self.team_filter = None
        await self.update()

    async def push_fixtures(self):
        """Push upcoming competition fixtures to View"""
        rows = await self.competition.get_fixtures(page=self.page, subpage='/fixtures')
        rows = [str(i) for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Fixtures for {self.competition}"
        embed.timestamp = Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Fixtures"
        self.filter_mode = None
        await self.update()

    async def push_results(self):
        """Push results fixtures to View"""
        rows = await self.competition.get_fixtures(page=self.page, subpage='/results')
        rows = [str(i) for i in rows] if rows else ["No Results Found"]

        embed = await self.get_embed()
        embed.title = f"≡ Results for {self.competition}"
        embed.timestamp = Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Results"
        self.filter_mode = None
        await self.update()


class TeamView(View):
    """The View sent to a user about a Team"""

    def __init__(self, interaction: Interaction, team: Team, page):
        super().__init__()
        self.page = page  # Browser Page
        self.team = team
        self.interaction = interaction
        self.message = None

        # Pagination
        self.semaphore = asyncio.Semaphore()
        self.pages = []
        self.index = 0
        self.value = None
        self._current_mode = None

        # Specific Selection
        self._currently_selecting = []

        # Fetch Once Objects
        self.base_embed = None
        self.players = None

        # Image Rate Limiting.
        self.table_image = None
        self.table_timestamp = None

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except NotFound:
            pass

        self.stop()
        await self.page.close()

    async def on_error(self, error, item, interaction):
        """Extended Error Logging."""
        print(f'Ignoring exception in view {self} for item {item}:', file=sys.stderr)
        traceback.print_exception(error.__class__, error, error.__traceback__, file=sys.stderr)
        print(self.interaction.message)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.team.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)  # Do not mutate.

    async def get_players(self):
        """Grab the list of players"""
        self.players = await self.team.get_players(page=self.page) if not self.players else self.players
        return self.players

    async def update(self, content=""):
        """Update the view for the user"""
        async with self.semaphore:

            self.clear_items()

            if self._currently_selecting:
                self.add_item(LeagueTableSelect(objects=self._currently_selecting))
                self._currently_selecting = []
            else:
                if len(self.pages) > 0:
                    _ = view_utils.PreviousButton()
                    _.disabled = True if self.index == 0 else False
                    self.add_item(_)

                    _ = view_utils.PageButton()
                    _.label = f"Page {self.index + 1} of {len(self.pages)}"
                    _.disabled = True if len(self.pages) == 1 else False
                    self.add_item(_)

                    _ = view_utils.NextButton()
                    _.disabled = True if self.index == len(self.pages) - 1 else False
                    self.add_item(_)

                buttons = [view_utils.FuncButton(label="Squad", func=self.push_squad),
                           view_utils.FuncButton(label="Injuries", func=self.push_injuries, emoji=INJURY_EMOJI),
                           view_utils.FuncButton(label="Scorers", func=self.push_scorers, emoji='⚽'),
                           view_utils.FuncButton(label="Table", func=self.select_table, row=3),
                           view_utils.FuncButton(label="Fixtures", func=self.push_fixtures, row=3),
                           view_utils.FuncButton(label="Results", func=self.push_results, row=3),
                           view_utils.StopButton(row=0)
                           ]

                for _ in buttons:
                    _.disabled = True if self._current_mode == _.label else False
                    self.add_item(_)

            embed = self.pages[self.index] if self.pages else None

            if self.message is None:
                i = self.interaction
                self.message = await i.client.reply(i, content=content, view=self, embed=embed)
            else:
                await self.message.edit(content=content, view=self, embed=embed)

    async def push_squad(self):
        """Push the Squad Embed to the team View"""
        players = await self.get_players()
        srt = sorted(players, key=lambda x: x.number)
        p = [i.squad_row for i in srt]

        # Data must be fetched before embed url is updated.
        embed = await self.get_embed()
        embed.title = f"≡ Squad for {self.team.name}"
        embed.url = self.page.url
        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, p)
        self._current_mode = "Squad"
        await self.update()

    async def push_injuries(self):
        """Push the Injuries Embed to the team View"""
        embed = await self.get_embed()
        players = await self.get_players()
        players = [i.injury_row for i in players if i.injury]
        players = players if players else ['No injuries found']
        embed.title = f"≡ Injuries for {self.team.name}"
        embed.url = self.page.url
        embed.description = "\n".join(players)
        self.index = 0
        self.pages = [embed]
        self._current_mode = "Injuries"
        await self.update()

    async def push_scorers(self):
        """Push the Scorers Embed to the team View"""
        embed = await self.get_embed()
        players = await self.get_players()
        srt = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
        embed.title = f"≡ Top Scorers for {self.team.name}"

        rows = [i.scorer_row for i in srt]

        embed.url = self.page.url
        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows, rows_per=None)
        self._current_mode = "Scorers"
        await self.update()

    async def select_table(self):
        """Select Which Table to push from"""
        self.pages, self.index = [await self.get_embed()], 0
        all_fixtures = await self.team.get_fixtures(self.page)
        _ = []
        [_.append(x) for x in all_fixtures if str(x.competition) not in [str(y.competition) for y in _]]

        if len(_) == 1:
            return await self.push_table(_[0])

        self._currently_selecting = _

        leagues = [f"• [{x.competition}]({x.link})" for x in _]
        self.pages[0].description = "**Use the dropdown to select a table**:\n\n " + "\n".join(leagues)
        await self.update()

    async def push_table(self, res):
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.get_embed()
        ts, dtn = self.table_timestamp, datetime.datetime.now()
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await res.get_table(self.page)
            if img is not None:
                self.table_image = await image_utils.dump_image(self.interaction, img)
                self.table_timestamp = datetime.datetime.now()

        embed.title = f"≡ Table for {res.competition}"
        if self.table_image is not None and self.table_image:
            embed.set_image(url=self.table_image)
            embed.description = timed_events.Timestamp().long
        else:
            embed.description = f"No Table found."
        embed.url = self.page.url
        self.pages = [embed]
        self._current_mode = "Table"
        await self.update()

    async def push_fixtures(self):
        """Push upcoming fixtures to View"""
        rows = await self.team.get_fixtures(page=self.page, subpage='/fixtures')
        rows = [str(i) for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Fixtures for {self.team.name}" if embed.title else "≡ Fixtures "
        embed.timestamp = Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Fixtures"
        await self.update()

    async def push_results(self):
        """Push results fixtures to View"""
        rows = await self.team.get_fixtures(page=self.page, subpage='/results')
        rows = [str(i) for i in rows] if rows else ["No Results Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Results for {self.team.name}" if embed.title else "≡ Results "
        embed.timestamp = Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Results"
        await self.update()


class LeagueTableSelect(Select):
    """Push a Specific League Table"""

    def __init__(self, objects):
        self.objects = objects
        super().__init__(placeholder="Select which league to get table from...")
        for num, _ in enumerate(objects):
            self.add_option(label=str(_.competition), emoji='🏆', description=_.link, value=str(num))

    async def callback(self, interaction):
        """Upon Item Selection do this"""
        await interaction.response.defer()
        await self.view.push_table(self.objects[int(self.values[0])])


class Stadium:
    """An object representing a football Stadium from football ground map.com"""

    def __init__(self, url, name, team, league, country, team_badge):
        self.url = url
        self.name = name.title()
        self.team = team
        self.league = league
        self.country = country
        self.team_badge = team_badge

        # These will be created if fetch_more is triggered
        self.image = None
        self.current_home = None
        self.former_home = None
        self.map_link = None
        self.address = None
        self.capacity = None
        self.cost = None
        self.website = None
        self.attendance_record = None

    async def fetch_more(self):
        """Fetch more data about a target stadium"""
        async with aiohttp.ClientSession() as cs:
            async with cs.get(self.url) as resp:
                src = await resp.read()
                src = src.decode('ISO-8859-1')
                tree = html.fromstring(src)
        self.image = "".join(tree.xpath('.//div[@class="page-img"]/img/@src'))

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

        self.map_link = "".join(tree.xpath('.//figure/img/@src'))
        self.address = "".join(tree.xpath('.//tr/th[contains(text(), "Address")]/following-sibling::td//text()'))
        self.capacity = "".join(tree.xpath('.//tr/th[contains(text(), "Capacity")]/following-sibling::td//text()'))
        self.cost = "".join(tree.xpath('.//tr/th[contains(text(), "Cost")]/following-sibling::td//text()'))
        self.website = "".join(tree.xpath('.//tr/th[contains(text(), "Website")]/following-sibling::td//text()'))
        self.attendance_record = "".join(
            tree.xpath('.//tr/th[contains(text(), "Record attendance")]/following-sibling::td//text()'))

    def __str__(self):
        return f"**{self.name}** ({self.country}: {self.team})"

    @property
    async def to_embed(self) -> Embed:
        """Create a discord Embed object representing the information about a football stadium"""
        e = Embed()
        e.set_footer(text="FootballGroundMap.com")
        e.title = self.name
        e.url = self.url

        await self.fetch_more()
        try:  # Check not ""
            e.colour = await embed_utils.get_colour(self.team_badge)
        except AttributeError:
            pass

        if self.image is not None:
            e.set_image(url=self.image.replace(' ', '%20'))

        if self.current_home is not None:
            e.add_field(name="Home to", value=", ".join(self.current_home), inline=False)

        if self.former_home is not None:
            e.add_field(name="Former home to", value=", ".join(self.former_home), inline=False)

        # Location
        address = self.address if self.address else "Link to map"
        if self.map_link is not None:
            e.add_field(name="Location", value=f"[{address}]({self.map_link})", inline=False)
        elif self.address:
            e.add_field(name="Location", value=address, inline=False)

        # Misc Data.
        e.description = f"Capacity: {self.capacity}\n" if self.capacity else ""
        e.description += f"Record Attendance: {self.attendance_record}\n" if self.attendance_record else ""
        e.description += f"Cost: {self.cost}\n" if self.cost else ""
        e.description += f"Website: {self.website}\n" if self.website else ""
        return e


async def get_stadiums(query) -> List[Stadium]:
    """Fetch a list of Stadium objects matching a user query"""
    qry = urllib.parse.quote_plus(query)

    async with aiohttp.ClientSession() as cs:
        async with cs.get(f'https://www.footballgroundmap.com/search/{qry}') as resp:
            tree = html.fromstring(await resp.text())

    results = tree.xpath(".//div[@class='using-grid'][1]/div[@class='grid']/div")

    stadiums = []

    for i in results:
        team = "".join(i.xpath('.//small/preceding-sibling::a//text()')).title()
        team_badge = i.xpath('.//img/@src')[0]
        comp_info = i.xpath('.//small/a//text()')

        if not comp_info:
            continue

        country = comp_info[0]
        try:
            league = comp_info[1]
        except IndexError:
            league = ""

        sub_nodes = i.xpath('.//small/following-sibling::a')
        for s in sub_nodes:
            name = "".join(s.xpath('.//text()')).title()
            url = "".join(s.xpath('./@href'))

            if query.lower() not in name.lower() and query.lower() not in team.lower():
                continue  # Filtering.

            if not any(c.name == name for c in stadiums) and not any(c.url == url for c in stadiums):
                stadiums.append(Stadium(url=url, name=name, team=team, team_badge=team_badge,
                                        country=country, league=league))

    return stadiums


async def get_fs_results(bot, query) -> List[FlashScoreSearchResult]:
    """Fetch a list of items from flashscore matching the user's query"""
    qry_debug = query

    for r in ["'", "[", "]", "#", '<', '>']:  # Fucking morons.
        query = query.replace(r, "")

    query = urllib.parse.quote(query)
    # One day we could probably expand upon this if we ever figure out what the other variables are.
    async with bot.session.get(f"https://s.flashscore.com/search/?q={query}&l=1&s=1&f=1%3B1&pid=2&sid=1") as resp:
        res = await resp.text(encoding="utf-8")
        assert resp.status == 200, f"Server returned a {resp.status} error, please try again later."

    # Un-fuck FS JSON reply.
    res = res.lstrip('cjs.search.jsonpCallback(').rstrip(");")
    try:
        res = json.loads(res, encoding='utf-8')
    except JSONDecodeError:
        print(f"Json error attempting to decode query: {query}\n", res, f"\nString that broke it: {qry_debug}")
        raise AssertionError('Something you typed broke the search query. Please only specify a team or league name.')

    try:
        filtered = [i for i in res['results'] if i['participant_type_id'] in (0, 1)]
    except KeyError:
        return []

    output = []
    for i in filtered:
        if i['participant_type_id'] == 1:
            obj = Team()
        else:
            obj = Competition()
            obj.country = i['country_name']
        obj.name = i['title']
        obj.id = i['id']
        obj.url = i['url']
        obj.logo_url = i['url']
        output.append(obj)
    return output


async def fs_search(interaction: Interaction, query) -> FlashScoreSearchResult or None:
    """Search using the aiohttp to fetch a single object matching the user's query"""
    search_results = await get_fs_results(interaction.client, query)
    search_results = [i for i in search_results if isinstance(i, Competition)]  # Filter out non-leagues

    if not search_results:
        return None

    if len(search_results) == 1:
        return search_results[0]

    view = view_utils.ObjectSelectView(interaction, [('🏆', str(i), i.link) for i in search_results], timeout=30)
    await view.update()
    await view.wait()

    return None if view.value is None else search_results[view.value]
