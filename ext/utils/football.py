"""A Utility tool for fetching and structuring data from the Flashscore Website"""
import asyncio
import datetime
import json
import typing
import urllib.parse
from importlib import reload
from inspect import getframeinfo, currentframe
from io import BytesIO
from json import JSONDecodeError

import aiohttp
import discord
from lxml import html

from ext.utils import embed_utils, timed_events, view_utils
from ext.utils import transfer_tools, image_utils, browser

reload(transfer_tools)
reload(image_utils)
reload(browser)

ADS = ['.//div[@class="seoAdWrapper"]', './/div[@class="banner--sticky"]', './/div[@class="box_over_content"]',
       './/div[@class="ot-sdk-container"]', './/div[@class="adsenvelope"]', './/div[@id="onetrust-consent-sdk"]',
       './/div[@id="lsid-window-mask"]', './/div[contains(@class, "isSticky")]', './/div[contains(@class, "rollbar")]',
       './/div[contains(@id,"box-over-content")]', './/div[contains(@class, "adsenvelope")]',
       './/div[contains(@class, "extraContent")]', './/div[contains(@class, "selfPromo")]',
       './/div[contains(@class, "otPlaceholder")]']


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

    def __str__(self):
        return f"`🔄 {self.time}`: 🔻 {self.player_off} 🔺 {self.player} ({self.team})"


class Goal(MatchEvent):
    """A Generic Goal Event"""

    def __init__(self):
        super().__init__()
        self.assist = None

    def __str__(self):
        ass = "" if self.assist is None else " " + self.assist
        note = "" if self.note is None else " " + self.note
        return f"`⚽ {self.time}`: {self.player}{ass}{note}"


class OwnGoal(Goal):
    """An own goal event"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        note = "" if self.note is None else " " + self.note
        return f"`⚽ {self.time}`: {self.player} (Own Goal) {note}"


class Penalty(Goal):
    """A Penalty Event"""

    def __init__(self, shootout=False, missed=False):
        super().__init__()
        self.shootout = shootout
        self.missed = missed

    def __str__(self):
        icon = "⚽" if self.missed is False else "❌"
        time = "" if self.shootout is True else " " + self.time
        return f"`{icon}{time}`: {self.player}"


class RedCard(MatchEvent):
    """An object representing the event of a dismissal of a player"""

    def __init__(self, second_yellow=False):
        super().__init__()
        self.second_yellow = second_yellow

    def __str__(self):
        ico = "🟨🟥" if self.second_yellow else "🟥"
        note = " " + self.note if self.note else ""
        note = "" if "Yellow card / Red card" in note else note
        return f"`{ico} {self.time}`: {self.player}{note}"


class Booking(MatchEvent):
    """An object representing the event of a player being given a yellow card"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        note = " " + self.note if self.note else ""
        note = "" if "Yellow Card" in note else note
        return f"`🟨 {self.time}`: {self.player}{note}"


class VAR(MatchEvent):
    """An Object Representing the event of a Video Assistant Referee Review Decision"""

    def __init__(self):
        super().__init__()

    def __str__(self):
        note = " " + self.note if self.note is not None else ""
        return f"`📹 {self.time}`: VAR Review: {self.player}{note}"


class Fixture:
    """An object representing a Fixture from the Flashscore Website"""

    def __init__(self, time: typing.Union[str, datetime.datetime], home: str, away: str, **kwargs):
        # Meta Data
        self.state = None
        self.url = None
        self.is_televised = None
        self.emoji = '⚽'

        # Match Data
        self.time = time
        self.home = home
        self.away = away
        self.country = None
        self.league = None
        self.infobox = None

        # Fixes for really weird shit.
        self.breaks = 0
        self.periods = 2
        self.period_length = 45

        # Initialise some vars...
        self.score_home = None
        self.score_away = None
        self.events = None
        self.penalties_home = None
        self.penalties_away = None
        self.home_cards = None
        self.away_cards = None

        # Refreshable Vars
        self.stats_image = None
        self.stats_timestamp = None
        self.table_image = None
        self.table_timestamp = None
        self.formation_image = None
        self.formation_timestamp = None
        self.summary_image = None
        self.summary_timestamp = None

        # Match Thread Bot specific vars
        self.kickoff = None
        self.referee = None
        self.stadium = None
        self.attendance = None
        self.comp_link = None
        self.images = None
        self.table = None
        self.__dict__.update(kwargs)
    
    def __repr__(self):
        return f"Fixture({self.__dict__})"
    
    def __str__(self):
        return f"{self.relative_time}: [{self.bold_score}{self.tv}]({self.url})"
    
    @classmethod
    async def by_id(cls, match_id, page):
        """Create a fixture object from the flashscore match ID"""
        url = "http://www.flashscore.com/match/" + match_id
        await browser.fetch(page, url, xpath=".//div[@class='team spoiler-content']")
        tree = html.fromstring(await page.content())
        
        home = "".join(tree.xpath('.//div[contains(@class, "tname-home")]//a/text()')).strip()
        away = "".join(tree.xpath('.//div[contains(@class, "tname-away")]//a/text()')).strip()
        ko = "".join(tree.xpath(".//div[@id='utime']/text()")).strip()
        ko = datetime.datetime.strptime(ko, "%d.%m.%Y %H:%M")
        
        country_league = "".join(tree.xpath('.//span[@class="description__country"]//text()'))
        comp_link_raw = "".join(tree.xpath('.//span[@class="description__country"]//a/@onclick'))
        country, competition = country_league.split(':')
        country = country.strip()
        competition = competition.strip()
        comp_link = "http://www.flashscore.com" + comp_link_raw.split("'")[1]
        
        return cls(url=url, home=home, away=away, time=ko, kickoff=ko, league=competition, comp_link=comp_link,
                   country=country)

    @property
    def tv(self):
        """Return an emoji if the fixture is televised"""
        return '📺' if self.is_televised else ""
    
    @property
    async def base_embed(self) -> discord.Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e = discord.Embed()
        e.title = f"≡ {self.bold_score}"
        e.url = self.url
        
        e.set_author(name=f"{self.country}: {self.league}")
        if isinstance(self.time, datetime.datetime):
            if self.time > datetime.datetime.now():
                e.description = f"Kickoff: {timed_events.Timestamp(self.time).time_relative}"
        elif self.time == "Postponed":
            e.description = "This match has been postponed."
        else:
            if not isinstance(self.time, datetime.datetime):
                e.set_footer(text=self.time)
            e.timestamp = datetime.datetime.now(datetime.timezone.utc)

        e.colour = self.colour[1]
        return e

    @property
    def event_footer(self):
        """A string containing Country: League and time"""
        return f"{self.country}: {self.league} | {self.time}"

    @property
    def reddit_time(self):
        """Standard Markdown Timestamps for Reddit"""
        if not isinstance(self.time, datetime.datetime):
            return self.time

        dtn = datetime.datetime.now()
        return self.time.strftime('%a %d %b') if self.time < dtn else self.time.strftime('%a %d %b %H:%M')

    @property
    def relative_time(self):
        """Discord Native TimeStamping"""
        if not isinstance(self.time, datetime.datetime):
            if self.time.endswith("'"):
                return self.time

            try:
                return timed_events.Timestamp(datetime.datetime.strptime(self.time, "%d.%m.%Y")).date
            except ValueError:
                if self.time.endswith("'"):
                    print(f'-------------\nfootball.py\nCould not make relative timestamp for '
                          f'{type(self.time)}: {self.time} {self.url}\n-------------')
                return self.time

        if self.time - datetime.timedelta(days=1) < datetime.datetime.now():
            return timed_events.Timestamp(self.time).date
        else:
            return timed_events.Timestamp(self.time).datetime

    @property
    def score(self) -> str:
        """Concatenate scores into home - away format"""
        return "vs" if self.score_home is None else f"{self.score_home} - {self.score_away}"

    @property
    def bold_score(self) -> str:
        """Embolden the winning team of a fixture"""
        if self.score_home is None or self.score_home == "-":
            return f"{self.home} vs {self.away}"

        hb, ab = ('**', '') if self.score_home > self.score_away else ('', '**')
        hb, ab = ("", "") if self.score_home == self.score_away else (hb, ab)
        return f"{hb}{self.home} {self.score_home}{hb} - {ab}{self.score_away} {self.away}{ab}"

    @property
    def live_score_text(self) -> str:
        """Return a preformatted string showing the score and any red cards of the fixture"""
        if self.state == "ht":
            time = "HT"
        elif self.state == "fin":
            time = "FT"
        elif self.state == "postponed":
            time = "PP"
        elif self.state == "after extra time":
            time = "AET"
        else:
            try:
                time = timed_events.Timestamp(self.time)
            except AttributeError:
                time = self.time

        _ = '\🟥'
        h_c = f"{self.home_cards * _} " if self.home_cards else ""
        a_c = f" {self.away_cards * _}" if self.away_cards else ""

        if self.state in ['after pens', "penalties"]:
            actual_score = min([self.score_home, self.score_away])
            time = "After Pens" if self.state == "after pens" else "PSO"

            return f"\\{self.colour[0]} {time} {self.home} {self.penalties_home} - {self.penalties_away} {self.away} " \
                   f"(FT: {actual_score} - {actual_score})"

        return f"\\{self.colour[0]} {time} {h_c}{self.bold_score}{a_c}"

    @property
    def scores_row(self):
        """Row for the .scores command"""
        return f"[{self.live_score_text}]({self.url})"

    # For discord.
    @property
    def full_league(self) -> str:
        """Return full information about the Country and Competition of the fixture"""
        return f"{self.country.upper()}: {self.league}"

    @property
    def colour(self) -> typing.Tuple:
        """Return a tuple of (Emoji, 0xFFFFFF Colour code) based on the Meta-State of the Game"""
        if isinstance(self.time, datetime.datetime) or self.state == "sched":
            return "⚫", 0x010101  # Upcoming Games = Black

        if self.state == "live":
            if "+" in self.time:
                return "🟣", 0x9932CC  # Purple
            else:
                return "🟢", 0x0F9D58  # Green

        elif self.state in ["fin", "after extra time", "after pens"]:
            return "⚪", 0xffffff  # White

        elif self.state in ["postponed", 'cancelled', 'abandoned']:
            return "🔴", 0xFF0000  # Red

        elif self.state in ["delayed", "interrupted"]:
            return "🟠", 0xff6700  # Orange

        elif self.state == "break time":
            return "🟤", 0xA52A2A  # Brown

        elif self.state == "ht":
            return "🟡", 0xFFFF00  # Yellow

        elif self.state == "extra time":
            return "🟣", 0x9932CC  # Purple

        elif self.state == "break time":
            return "🔵", 0x4285F4  # Blue

        elif self.state == "awaiting":
            return "⚪", 0xFFFFFF  # White

        elif self.state == "penalties":
            return "🔵", 0x4285F4  # Blue

        else:
            print("Football.py: Unhandled state:", self.state, self.home, self.away, self.url)
            return "🔴", 0xFF0000  # Red

    async def get_badge(self, page, team) -> BytesIO or None:
        """Fetch an image of a Team's Logo or Badge as a BytesIO object"""
        return await browser.fetch(page, self.url, f'.//div[contains(@class, "tlogo-{team}")]//img', screenshot=True)

    async def get_table(self, page) -> BytesIO or None:
        """Fetch an image of the league table appropriate to the fixture as a bytesIO object"""
        xp = './/div[contains(@class, "tableWrapper")]'
        link = self.url + "/#standings/table/overall"
        return await browser.fetch(page, link, xp, delete=ADS, screenshot=True)

    async def get_stats(self, page) -> BytesIO or None:
        """Get an image of a list of statistics pertaining to the fixture as a BytesIO object"""
        xp = ".//div[starts-with(@class, 'statRow')]"
        link = self.url + "/#match-summary/match-statistics/0"
        return await browser.fetch(page, link, xp, delete=ADS, screenshot=True)

    async def get_formation(self, page) -> BytesIO or None:
        """Get the formations used by both teams in the fixture"""
        xp = './/div[starts-with(@class, "fieldWrap")]'
        formation = await browser.fetch(page, self.url + "/#match-summary/lineups", xp, delete=ADS, screenshot=True)
        xp = './/div[starts-with(@class, "lineUp")]'
        lineup = await browser.fetch(page, self.url + "/#match-summary/lineups", xp, delete=ADS, screenshot=True)

        if formation is None and lineup is None:
            return None

        valid_images = [i for i in [formation, lineup] if i is not None]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, image_utils.stitch_vertical, valid_images)

    async def get_summary(self, page) -> BytesIO or None:
        """Fetch the summary of a Fixture"""
        xp = ".//div[starts-with(@class, 'verticalSections')]"
        summary = await browser.fetch(page, self.url + "#match-summary", xp, delete=ADS, screenshot=True)
        return summary
    
    async def head_to_head(self, page) -> typing.Dict:
        """Get results of recent games related to the two teams in the fixture"""
        xp = ".//div[@id='tab-h2h-overall']"
        await browser.fetch(page, self.url + "/#h2h/overall", xp, delete=ADS)
        tree = html.fromstring(await page.content())
        games = {}
        for i in tree.xpath('.//div[starts-with(@class, "h2h")]//div[starts-with(@class, "section")]'):
            header = "".join(i.xpath('.//div[starts-with(@class, "title")]//text()')).strip().title()
            
            fixtures = i.xpath('.//div[starts-with(@class, "row_")]')
            fx_list = []
            
            for game in fixtures[:5]:  # Last 5 only.
                url = None  # TODO: Figure this out...
                home = "".join(game.xpath('.//span[starts-with(@class, "homeParticipant")]/text()')).strip().title()
                away = "".join(game.xpath('.//span[starts-with(@class, "awayParticipant")]/text()')).strip().title()
                time = game.xpath('.//span[starts-with(@class, "date")]/text()')[0]
                try:
                    time = datetime.datetime.strptime(time, "%d.%m.%y")
                except ValueError:
                    f = getframeinfo(currentframe())
                    print(f.filename, f.lineno)
                    print(time, "format is not %d.%m.%y")

                score_home, score_away = game.xpath('.//span[starts-with(@class, "regularTime")]//text()')[0].split(':')

                score_home, score_away = int(score_home.strip()), int(score_away.strip())

                fx = Fixture(home=home, away=away, time=time, score_home=score_home, score_away=score_away, url=url)
                fx_list.append(fx)
            games.update({header: fx_list})

        return games

    async def refresh(self, page, for_reddit=False):
        """Perform an intensive full lookup for a fixture"""
        xp = ".//div[@id='utime']"

        for i in range(3):
            try:
                await browser.fetch(page, self.url, xp)
            except Exception as err:
                print(f'Retry ({i}) Error refreshing fixture {self.home} v {self.away}: {type(err)}')

        tree = html.fromstring(await page.content())
        
        # Some of these will only need updating once per match
        if self.kickoff is None:
            try:
                ko = "".join(tree.xpath(".//div[@id='utime']/text()"))
                ko = datetime.datetime.strptime(ko, "%d.%m.%Y %H:%M")
            except ValueError:
                ko = ""
            self.kickoff = ko
        
        if self.referee is None:
            text = tree.xpath('.//div[@class="content"]//text()')
            ref = "".join([i for i in text if "referee" in i.lower()]).strip().replace('Referee:', '')
            venue = "".join([i for i in text if "venue" in i.lower()]).strip().replace('Venue:', '')
            
            self.referee = ref
            self.stadium = venue
        
        if self.country is None or self.league is None:
            country_league = "".join(tree.xpath('.//span[@class="description__country"]//text()'))
            comp_link_raw = "".join(tree.xpath('.//span[@class="description__country"]//a/@onclick'))
            country, competition = country_league.split(':')
            country = country.strip()
            competition = competition.strip()
            comp_link = "http://www.flashscore.com" + comp_link_raw.split("'")[1]
            self.country = country
            self.league = competition
            self.comp_link = comp_link

        if for_reddit:
            scores = tree.xpath('.//div[start-with(@class, "score")]//span//text()')
            self.score_home = int(scores[0])
            self.score_away = int(scores[1])
            self.formation_image = await self.get_formation(page)
            self.table_image = await self.get_table(page)

        # Grab infobox
        ib = tree.xpath('.//div[contains(@class, "infoBoxModule")]/div[starts-with(@class, "info__")]/text()')
        if ib:
            self.infobox = "".join(ib)
            if self.infobox.startswith('Format:'):
                fmt = self.infobox.split(': ')[-1]
                periods, length = fmt.split('x')
                self.periods = int(periods)
                length = length.split(' mins')[0].split(' minutes')[0].strip()
                self.period_length = int(length)
        else:
            self.infobox = None

        event_rows = tree.xpath('.//div[starts-with(@class, "verticalSections")]/div')
        events = []
        after_pen_header = False

        for i in event_rows:
            event_class = i.attrib['class']
            # Detection for penalty mode, discard headers.
            if "Header" in event_class:
                parts = [x.strip() for x in i.xpath('.//text()')]
                if "Penalties" in parts:
                    self.penalties_home = parts[1]
                    self.penalties_away = parts[3]
                    after_pen_header = True
                continue
            
            # Detection of Teams
            if "home" in event_class:
                team = self.home
            elif "away" in event_class:
                team = self.away
            elif "empty" in event_class:
                continue  # No events in half signifier.
            else:
                team = None

            e_n = i.xpath('./div[starts-with(@class, "incident_")]')[0]  # event_node

            icon = "".join(e_n.xpath('.//div[starts-with(@class, "incidentIcon")]//svg/@class')).strip()
            event_desc = "".join(e_n.xpath('.//div[starts-with(@class, "incidentIcon")]//@title')).strip()
            icon_desc = "".join(e_n.xpath('.//div[starts-with(@class, "incidentIcon")]//svg//text()')).strip()

            # Data not always present.
            player = "".join(e_n.xpath('.//a[starts-with(@class, "playerName")]//text()')).strip()

            if "goal" in icon.lower():
                if "own" in icon.lower():
                    event = OwnGoal()
                else:
                    if after_pen_header:
                        event = Penalty(shootout=True)
                    elif "Penalty" in icon_desc:
                        event = Penalty()
                    else:
                        event = Goal()

            elif icon.startswith("penaltyMissed"):
                event = Penalty(shootout=True, missed=True) if after_pen_header else Penalty(missed=True)

            elif "arrowUp" in icon:
                event = Substitution()
                event.player_on = "".join(e_n.xpath('.//div/a[starts-with(@class, "playerName")]//text()')).strip()
                event.player_off = "".join(e_n.xpath('.//div[starts-with(@class, "incidentSubOut")]/a/text()')).strip()

            elif icon.startswith("redYellow"):
                event = RedCard(second_yellow=True)
                if icon_desc:
                    event.note = icon_desc

            elif icon.startswith("redCard") or icon.startswith("card"):
                event = RedCard()
                if icon_desc:
                    event.note = icon_desc

            elif icon.startswith("yellowCard"):
                event = Booking()
                if icon_desc:
                    event.note = icon_desc
            
            elif icon.startswith("var"):
                event = VAR()
                if icon_desc:
                    event.note = icon_desc
                else:
                    maybe_note = "".join(e_n.xpath('./div//text()')).strip()
                    if maybe_note:
                        event.note = maybe_note

            else:
                event = MatchEvent()
                print(self.url)
                print('Undeclared event type for', icon)

            assist = "".join(e_n.xpath('.//div[starts-with(@class, "assist")]//text()'))
            if assist:
                event.assist = assist

            try:
                description = e_n.attrib['title']
                event.description = description.replace('<br />', ' ')
            except KeyError:
                pass

            event.team = team
            event.player = player
            event.time = "".join(e_n.xpath('.//div[starts-with(@class, "timeBox")]//text()')).strip()
            if event_desc:
                event_desc = event_desc.replace('<br />', ' ')
                event.full_description = event_desc

            events.append(event)

        self.events = events

        # TODO: Fetching images
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')
        # TODO: fetching statistics


class Player:
    """An object representing a player from flashscore."""

    def __init__(self, **kwargs):
        self.number = None
        self.name = None
        self.apps = None
        self.flag = None
        self.country = None
        self.url = None
        self.assists = None
        self.position = None
        self.injury = None
        self.goals = None
        self.team = None
        self.team_url = None
        self.__dict__.update(kwargs)

    def __bool__(self):
        return bool(self.__dict__)

    @property
    def squad_row(self):
        """String for Team Lineup."""
        out = ""
        if self.number is not None:
            out += f"`{str(self.number).rjust(2)}`: "

        inj = f" - <:injury:682714608972464187> {self.injury}" if self.injury else ""

        out += f"{self.flag} [{self.name}]({self.url}) ({self.position}{inj})"
        return out

    @property
    def scorer_row(self):
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        out = ""
        if hasattr(self, 'rank'):
            out += f"`{self.rank.rjust(3, ' ')}`"

        out += f"{self.flag} **[{self.name}]({self.url})** "

        if self.team is not None:
            out += f"([{self.team}]({self.team_url})) "

        out += f"{self.goals} Goal{'s' if self.goals != 1 else ''}"

        if self.assists is not None and self.assists > 0:
            out += f" ({self.assists} Assist{'s' if self.assists != 1 else ''})"
        return out

    @property
    def assist_row(self):
        """Return a preformatted string showing information about a Player's Goals & Assists"""
        out = f"{self.flag} [**{self.name}**]({self.url}) "

        if self.team is not None:
            out += f"([{self.team}]({self.team_url})) "

        out += f" ({self.assists} Assist{'s' if self.assists != 1 else ''})"
        if self.goals is not None and self.goals > 0:
            out += f"{self.goals} Goal{'s' if self.goals != 1 else ''}"

        return out

    @property
    def injury_row(self):
        """Return a string with player & their injury"""
        return f"{self.flag} [{self.name}]({self.url}) ({self.position}): <:injury:682714608972464187> {self.injury}"


class FlashScoreSearchResult:
    """A generic object representing the result of a Flashscore search"""

    def __init__(self, **kwargs):
        self.url = None
        self.title = None
        self.logo_url = None
        self.participant_type_id = None
        self.__dict__.update(**kwargs)
        self.emoji = None

    async def get_logo(self, page):
        """Fetch any logo representing the target object"""
        if self.logo_url is not None and "http" in self.logo_url:
            return  # Only need to fetch once.

        try:
            logo = await page.xpath('.//div[contains(@class,"logo")]')
            logo = logo[0]
        except IndexError:
            return

        logo_raw = await page.evaluate("el => window.getComputedStyle(el).backgroundImage", logo)
        self.logo_url = logo_raw.strip("url(").strip(")").strip('"')
    
    @property
    async def base_embed(self) -> discord.Embed:
        """A discord Embed representing the flashscore search result"""
        e = discord.Embed()
        
        if isinstance(self, Team):
            try:
                e.title = self.title.split('(')[0]
            except AttributeError:
                pass
        else:
            try:
                ctry, league = self.title.split(': ')
                e.title = f"{ctry}: {league}"
            except (ValueError, AttributeError):
                pass
        
        if self.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + self.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.url = self.url
        return e

    async def get_fixtures(self, page, subpage=""):
        """Get all upcoming fixtures related to the Flashscore search result"""
        await browser.fetch(page, self.url + subpage, './/div[@class="sportName soccer"]')
        tree = html.fromstring(await page.content())
        await self.get_logo(page)

        # Iterate through to generate data.
        league, country = None, None
        fixtures = []

        for i in tree.xpath('.//div[contains(@class,"sportName soccer")]/div'):
            try:
                fixture_id = i.xpath("./@id")[0].split("_")[-1]
                url = "http://www.flashscore.com/match/" + fixture_id
            except IndexError:
                cls = i.xpath('./@class')
                # This (might be) a header row.
                if "event__header" in str(cls):
                    country, league = i.xpath('.//div[contains(@class, "event__title")]//text()')
                    league = league.split(' - ')[0]
                continue

            # score
            home, away = i.xpath('.//div[contains(@class,"event__participant")]/text()')

            try:
                score_home, score_away = i.xpath('.//div[contains(@class,"event__score")]//text()')
                score_home = int(score_home.strip())
                score_away = int(score_away.strip())
            except ValueError:
                score_home, score_away = None, None

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
                        # Fixtures: Year Correction - if in Past, increase by one year.
                        if time < datetime.datetime.now():
                            time = time.replace(year=time.year + 1)
    
            is_televised = True if i.xpath(".//div[contains(@class,'tv')]") else False
            fixture = Fixture(time, home.strip(), away.strip(), score_home=score_home, score_away=score_away,
                              is_televised=is_televised,
                              country=country.strip(), league=league.strip(), url=url)
            fixtures.append(fixture)
        return fixtures


class Competition(FlashScoreSearchResult):
    """An object representing a Competition on Flashscore"""

    def __init__(self, **kwargs):
        self.country_name = ""
        self.url = ""
        super().__init__(**kwargs)
        self.__dict__.update(**kwargs)
        self.emoji = '🏆'

        if "://" not in self.url:
            self.url = f"https://www.flashscore.com/soccer/{self.country_name.lower().replace(' ', '-')}/{self.url}"

    @classmethod
    async def by_id(cls, comp_id, page):
        """Create a Competition object based on the Flashscore ID of the competition"""
        url = "http://flashscore.com/?r=2:" + comp_id
        await browser.fetch(page, url, ".//div[@class='team spoiler-content']")
        tree = html.fromstring(await page.content())

        country = tree.xpath('.//h2[@class="tournament"]/a[2]//text()')[0].strip()
        league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
        title = f"{country.upper()}: {league}"
        obj = cls(url=url, title=title)
        await obj.get_logo(page)
        return obj

    @classmethod
    async def by_link(cls, link, page):
        """Create a Competition Object from a flashscore url"""
        assert "flashscore" in link[:25].lower(), "Invalid URL provided. Please make sure this is a flashscore link."
        assert link.count('/') > 3, "Invalid URL provided. Please make sure this is a flashscore link to a competition."

        await browser.fetch(page, link, xpath=".//div[@class='team spoiler-content']")
        tree = html.fromstring(await page.content())

        try:
            country = tree.xpath('.//h2[@class="breadcrumb"]//a/text()')[-1].strip()
            league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
            title = f"{country.upper()}: {league}"
        except IndexError:
            print(f'Error fetching Competition country/league by_link - {link}')
            title = "Unidentified League"

        comp = cls(url=link, title=title)
        await comp.get_logo(page)
        return comp

    async def get_table(self, page) -> BytesIO:
        """Fetch the table from a flashscore page and return it as a BytesIO object"""
        await self.get_logo(page)
        xp = './/div[contains(@class, "tableWrapper")]/parent::div'
        table_image = await browser.fetch(page, self.url + "/standings/", xp, delete=ADS, screenshot=True)
        return table_image

    async def get_scorers(self, page) -> typing.List[Player]:
        """Fetch a list of scorers from a Flashscore Competition page returned as a list of Player Objects"""
        xp = ".//div[@class='tabs__group']"
        clicks = ['a[href$="top_scorers"]', 'div[class^="showMore"]']
        await self.get_logo(page)

        uri = self.url + "/standings"
        await browser.fetch(page, uri, xp, clicks=clicks, delete=ADS, debug=True)

        tree = html.fromstring(await page.content())
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
                        print(f"Unable to fetch scorer info for row on get_scorers for {uri}")
                        continue

            country = "".join(i.xpath('.//span[contains(@class,"flag")]/@title')).strip()
            flag = transfer_tools.get_flag(country)
            players.append(Player(rank=rank, flag=flag, name=name, url=player_link, team=tm, team_url=team_link,
                                  country=country, goals=int(goals), assists=int(assists)))
        return players


class Team(FlashScoreSearchResult):
    """An object representing a Team from Flashscore"""

    def __init__(self, **kwargs):
        self.name = None
        self.id = None
        super().__init__(**kwargs)
        self.__dict__.update(**kwargs)
        self.emoji = '👕'

        if "://" not in self.url:
            # Example Team URL: https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
            self.url = f"https://www.flashscore.com/team/{self.url}/{self.id}"

    @classmethod
    async def by_id(cls, team_id, page):
        """Create a Team object from it's Flashscore ID"""
        url = "http://flashscore.com/?r=3:" + team_id
        await browser.fetch(page, url, "body")
        url = await page.evaluate("() => window.location.href")
        return cls(url=url, id=team_id)

    async def get_players(self, page) -> typing.List[Player]:
        """Get a list of players for a Team"""
        xp = './/div[contains(@class,"playerTable")]'
        await browser.fetch(page, self.url + "/squad", xp)
        tree = html.fromstring(await page.content())
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

            pl = Player()
            pl.position = position

            name = "".join(i.xpath('.//div[contains(@class,"")]/a/text()'))
            try:  # Name comes in reverse order.
                surname, forename = name.split(' ', 1)
                name = f"{forename} {surname}"
            except ValueError:
                if name:
                    pl.name = name
                else:
                    continue
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
            url = "".join(i.xpath('.//div[contains(@class,"")]/a/@href'))
            pl.url = f"http://www.flashscore.com{url}" if url else ""
            players.append(pl)
        return players


class Stadium:
    """An object representing a football Stadium from footballgroundmap.com"""

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
    async def to_embed(self) -> discord.Embed:
        """Create a discord Embed object representing the information about a football stadium"""
        e = discord.Embed()
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


async def get_stadiums(query) -> typing.List[Stadium]:
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
        ctry_league = i.xpath('.//small/a//text()')
        
        if not ctry_league:
            continue
            
        country = ctry_league[0]
        try:
            league = ctry_league[1]
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


async def get_fs_results(bot, query) -> typing.List[FlashScoreSearchResult]:
    """Fetch a list of items from flashscore matching the user's query"""
    qry_debug = query

    for r in ["'", "[", "]", "#", '<', '>']:  # Fucking morons.
        query = query.replace(r, "")

    query = urllib.parse.quote(query)
    # One day we could probably expand upon this if we figure out what the other variables are.
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
    return [Team(**i) if i['participant_type_id'] == 1 else Competition(**i) for i in filtered]


async def fs_search(ctx, query) -> FlashScoreSearchResult or None:
    """Search using the aiohttp to fetch a single object matching the user's query"""
    search_results = await get_fs_results(ctx.bot, query)
    search_results = [i for i in search_results if isinstance(i, Competition)]  # Filter out non-leagues

    if not search_results:
        return None

    view = view_utils.ObjectSelectView(ctx.author, [('🏆', i.title, i.url) for i in search_results])
    view.message = await ctx.bot.reply(ctx, f"Fetching matches for {query}...", view=view)
    await view.update()
    await view.wait()

    return None if view.value is None else search_results[view.value]
