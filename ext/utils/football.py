"""A Utility tool for fetching and structuring data from the Flashscore Website"""
import asyncio
import datetime
import itertools
import json
import sys
import traceback
import typing
import urllib.parse
from copy import deepcopy
from importlib import reload
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

FSURL = 'http://www.flashscore.com'
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


class Fixture:
    """An object representing a Fixture from the Flashscore Website"""

    def __init__(self, time: typing.Union[str, datetime.datetime], home: str, away: str, **kwargs):
        # Meta Data
        self.state = None
        self.url = None
        self.emoji = '⚽'

        # Match Data
        self.time = time
        self.home = home
        self.away = away
        self.country = None
        self.league = None
        self.comp_link = None

        # Half Tracking
        self.breaks = 0
        self.periods = 2
        self.infobox = None

        # Initialise some vars...
        self.score_home = None
        self.score_away = None
        self.penalties_home = None
        self.penalties_away = None
        self.events = None
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
        self.preview = None
        self.referee = None
        self.kickoff = None
        self.attendance = None
        self.stadium = None
        self.images = None
        self.__dict__.update(kwargs)
    
    def __repr__(self):
        return f"Fixture({self.__dict__})"
    
    def __str__(self):
        return f"{self.relative_time}: [{self.bold_score}]({self.url})"
    
    @classmethod
    async def by_id(cls, match_id, page):
        """Create a fixture object from the flashscore match ID"""
        url = "http://www.flashscore.com/match/" + match_id

        src = await browser.fetch(page, url, xpath=".//div[@class='team spoiler-content']")
        tree = html.fromstring(src)

        ko = "".join(tree.xpath(".//div[contains(@class, 'startTime')]/div/text()"))
        ko = datetime.datetime.strptime(ko, "%d.%m.%Y %H:%M")

        home = "".join(tree.xpath('.//div[contains(@class, "Participant__home")]//a/text()')).strip()
        away = "".join(tree.xpath('.//div[contains(@class, "Participant__away")]//a/text()')).strip()
        fix = cls(url=url, home=home, away=away, time=ko)
        return fix
    
    @property
    async def base_embed(self) -> discord.Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e = discord.Embed()
        e.title = f"{self.home} {self.score} {self.away}"
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
        return f"{self.country}: {self.league}"

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

        _ = '🟥'
        h_c = f"`{self.home_cards * _}` " if self.home_cards else ""
        a_c = f" `{self.away_cards * _}`" if self.away_cards else ""

        if self.state in ['after pens', "penalties"]:
            actual_score = min([self.score_home, self.score_away])
            time = "After Pens" if self.state == "after pens" else "PSO"
            _ = self.colour[0]
            if self.penalties_home is not None:
                ph, pa = self.penalties_home, self.penalties_away
                return f"`{_}` {time} {self.home} {ph} - {pa} {self.away} (FT: {actual_score} - {actual_score})"
            else:
                return f"`{_}` {time} {self.home} {self.score_home} - {self.score_away} {self.away}"

        return f"`{self.colour[0]}` {time} {h_c}{self.bold_score}{a_c}"

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
        xp = ".//div[contains(@class, 'statRow')]"
        link = self.url + "/#match-summary/match-statistics/0"
        return await browser.fetch(page, link, xp, delete=ADS, screenshot=True)

    async def get_formation(self, page) -> BytesIO or None:
        """Get the formations used by both teams in the fixture"""
        xp = './/div[contains(@class, "fieldWrap")]'
        formation = await browser.fetch(page, self.url + "/#match-summary/lineups", xp, delete=ADS, screenshot=True)
        xp = './/div[contains(@class, "lineUp")]'
        lineup = await browser.fetch(page, self.url + "/#match-summary/lineups", xp, delete=ADS, screenshot=True)

        if formation is None and lineup is None:
            return None

        valid_images = [i for i in [formation, lineup] if i is not None]

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, image_utils.stitch_vertical, valid_images)

    async def get_summary(self, page) -> BytesIO or None:
        """Fetch the summary of a Fixture"""
        xp = ".//div[contains(@class, 'verticalSections')]"
        summary = await browser.fetch(page, self.url + "#match-summary", xp, delete=ADS, screenshot=True)
        return summary
    
    async def head_to_head(self, page) -> typing.Dict:
        """Get results of recent games related to the two teams in the fixture"""
        xp = ".//div[@class='h2h']"
        src = await browser.fetch(page, self.url + "/#h2h/overall", xp, delete=ADS)
        tree = html.fromstring(src)
        games = {}
        _ = tree.xpath('.//div[contains(@class, "section")]')
        for i in _:
            header = "".join(i.xpath('.//div[contains(@class, "title")]//text()')).strip().title()
            if not header:
                continue

            fixtures = i.xpath('.//div[contains(@class, "_row")]')
            fx_list = []
            for game in fixtures[:5]:  # Last 5 only.
                url = game.xpath(".//@onclick")
                home = "".join(game.xpath('.//span[contains(@class, "homeParticipant")]//text()')).strip().title()
                away = "".join(game.xpath('.//span[contains(@class, "awayParticipant")]//text()')).strip().title()
                time = game.xpath('.//span[contains(@class, "date")]/text()')[0].strip()

                try:
                    time = datetime.datetime.strptime(time, "%d.%m.%y")
                except ValueError:
                    print("football.py: head_to_head", time, "format is not %d.%m.%y")

                score_home, score_away = game.xpath('.//span[contains(@class, "regularTime")]//text()')[0].split(':')
                score_home, score_away = int(score_home.strip()), int(score_away.strip())

                fx = Fixture(home=home, away=away, time=time, score_home=score_home, score_away=score_away, url=url)
                fx_list.append(fx)
            games.update({header: fx_list})

        return games

    async def get_preview(self, page):
        """Fetch information about upcoming match from Flashscore"""
        xp = './/div[contains(@class, "previewOpenBlock")]/div//text()'

        clicks = ['div[class$="showMore"]']

        src = await browser.fetch(page, self.url, xp, clicks=clicks)
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
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FSURL + ''.join(_.xpath('.//a/@href'))}) {ij}"
                home.append(player)

            away = []
            for _ in npa:
                ij = "".join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FSURL + ''.join(_.xpath('.//a/@href'))}) {ij}"
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
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FSURL + ''.join(_.xpath('.//a/@href'))}) {ij}"
                home.append(player)

            away = []
            for _ in npa:
                ij = "".join(_.xpath('.//div[contains(@class, "scratchLabel")]/text()'))
                player = f"[{''.join(_.xpath('.//a//text()'))}]({FSURL + ''.join(_.xpath('.//a/@href'))}) {ij}"
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

        if self.table_image:
            preview += f"\n## Current Standings\n[Table]({self.table_image})"

        tv = tree.xpath('.//div[contains(@class, "broadcast")]/div/a')
        if tv:
            preview += "\n## Television Coverage\n\n"
            tv_list = ["[" + "".join(_.xpath('.//text()')) + "](" + "".join(_.xpath('.//@href')) + ")" for _ in tv]
            preview += ", ".join(tv_list)

        return preview

    async def refresh(self, page, for_reddit=False):
        """Perform an intensive full lookup for a fixture"""
        xp = ".//div[@id='utime']"

        for i in range(3):
            try:
                src = await browser.fetch(page, self.url, xp)
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
                print(f"Could not convert string {self.kickoff} to stftime string.")

        if not hasattr(self, 'referee'):
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')
            ref = "".join([i for i in text if "referee" in i.lower()]).strip().replace('Referee:', '')
            venue = "".join([i for i in text if "venue" in i.lower()]).strip().replace('Venue:', '')
            if ref:
                self.referee = ref
            if venue:
                self.stadium = venue

        if self.country is None or self.league is None:
            self.country = "".join(tree.xpath('.//span[contains(@class, "__country")]/text()')).strip()
            self.league = "".join(tree.xpath('.//span[contains(@class, "__country")]/a/text()')).strip()
            _ = "".join(tree.xpath('.//span[contains(@class, "__country")]//a/@href'))
            self.comp_link = "http://www.flashscore.com" + _

        if for_reddit:
            self.formation_image = await self.get_formation(page)
            self.table_image = await self.get_table(page)
            self.preview = await self.get_preview(page)

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
            elif "arrowUp" in icon:
                event = Substitution()
                event.player_off = "".join(node.xpath('.//div[contains(@class, "incidentSubOut")]/a/text()')).strip()
                try:
                    event.player_on = node.xpath('.//a[contains(@class, "playerName")]/text()')[0].strip()
                except IndexError:
                    event.player_on = ""
                if "Substitution" not in icon_desc:
                    event.note = icon_desc
                    print(f"Substitution | icon_desc: {icon_desc}\n{p}")
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
                print(self.url, 'Undeclared event type for', icon)

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

    def view(self, ctx, page):
        """Return a view representing this Fixture"""
        return FixtureView(ctx, self, page)


class FixtureView(discord.ui.View):
    """The View sent to users about a fixture."""

    def __init__(self, ctx, fixture: Fixture, page):
        self.fixture = fixture
        self.ctx = ctx
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
        except discord.HTTPException:
            pass

        self.stop()
        await self.page.close()

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.ctx.author.id

    async def update(self):
        """Update the view for the user"""
        embed = self.pages[self.index]
        async with self.semaphore:
            self.clear_items()
            buttons = [view_utils.Button(label="Stats", func=self.push_stats, emoji="📊"),
                       view_utils.Button(label="Table", func=self.push_table),
                       view_utils.Button(label="Lineups", func=self.push_lineups),
                       view_utils.Button(label="Summary", func=self.push_summary),
                       view_utils.Button(label="H2H", func=self.push_head_to_head, emoji="⚔"),
                       view_utils.StopButton()
                       ]

            for _ in buttons:
                _.disabled = True if self._current_mode == _.label else False
                self.add_item(_)

            try:
                await self.message.edit(content="", view=self, embed=embed)
            except discord.HTTPException:
                return await self.on_timeout()
        await self.wait()

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.fixture.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)

    async def push_stats(self):
        """Push Stats to View"""
        self._current_mode = "Stats"

        dtn = datetime.datetime.now()
        ts = self.fixture.stats_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_stats(page=self.page)
            self.fixture.stats_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.stats_timestamp = datetime.datetime.now()

        image = self.fixture.stats_image
        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
        if self.page.url.startswith("http"):
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
        ts = self.fixture.formation_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_formation(page=self.page)
            self.fixture.formation_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.formation_timestamp = datetime.datetime.now()

        image = self.fixture.formation_image

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
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
        ts = self.fixture.table_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_table(page=self.page)
            self.fixture.table_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.table_timestamp = datetime.datetime.now()

        image = self.fixture.table_image

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
        if self.page.url.startswith("http"):
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
        ts = self.fixture.summary_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_summary(page=self.page)
            self.fixture.summary_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.summary_timestamp = datetime.datetime.now()

        image = self.fixture.summary_image

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
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
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        for k, v in fixtures.items():
            x = "\n".join([f"{i.relative_time} [{i.bold_score}]({i.url})" for i in v])
            embed.add_field(name=k, value=x, inline=False)
        self.pages = [embed]
        await self.update()


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
        src = await browser.fetch(page, self.url + subpage, './/div[@class="sportName soccer"]')

        if src is None:
            return None

        tree = html.fromstring(src)

        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            self.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if ".png" in _:
                self.logo_url = _
            else:
                print(f"Failed to extract logo Url from: {_}")

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

            fixture = Fixture(time, home.strip(), away.strip(), score_home=score_home, score_away=score_away,
                              country=country.strip(), league=league.strip(), url=url)
            fixtures.append(fixture)
        return fixtures

    def view(self, ctx, page):
        """This should always be polymorphed."""
        return discord.ui.View()

    async def pick_recent_game(self, ctx, message, page, upcoming=False):
        """Choose from recent games from team"""
        subpage = "/fixtures" if upcoming else "/results"
        items = await self.get_fixtures(page, subpage)

        _ = [("⚽", f"{i.home} {i.score} {i.away}", f"{i.country.upper()}: {i.league}") for i in items]

        e = discord.Embed()
        e.colour = discord.Colour.red()
        e.description = f"No recent games found for {self.title}"
        if not _:
            await message.edit(embed=e)
            return None

        view = view_utils.ObjectSelectView(ctx, objects=_, timeout=30)
        _ = "an upcoming" if upcoming else "a recent"
        await message.edit(content=f'⏬ Please choose {_} game.', view=view)
        view.message = message

        await view.update()
        await view.wait()

        if view.value is None:
            return None

        return items[view.value]


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
        src = await browser.fetch(page, url, ".//div[@class='team spoiler-content']")
        tree = html.fromstring(src)

        country = tree.xpath('.//h2[@class="tournament"]/a[2]//text()')[0].strip()
        league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
        title = f"{country.upper()}: {league}"
        obj = cls(url=url, title=title, country=country, league=league)
        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            obj.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if _:
                print(f"Invalid logo_url: {_}")
        return obj

    @classmethod
    async def by_link(cls, link, page):
        """Create a Competition Object from a flashscore url"""
        assert "flashscore" in link[:25].lower(), "Invalid URL provided. Please make sure this is a flashscore link."
        assert link.count('/') > 3, "Invalid URL provided. Please make sure this is a flashscore link to a competition."

        src = await browser.fetch(page, link, xpath=".//div[@class='team spoiler-content']")
        tree = html.fromstring(src)

        try:
            country = tree.xpath('.//h2[@class="breadcrumb"]//a/text()')[-1].strip()
            league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
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
            else:
                print(f"Failed to extract logo Url from: {_}")

        return comp

    async def get_table(self, page) -> BytesIO:
        """Fetch the table from a flashscore page and return it as a BytesIO object"""
        xp = './/div[contains(@class, "tableWrapper")]/parent::div'
        table_image = await browser.fetch(page, self.url + "/standings/", xp, delete=ADS, screenshot=True)
        tree = html.fromstring(await page.content())

        _ = tree.xpath('.//div[contains(@class,"__logo")]/@style')
        try:
            self.logo_url = _[0].split("(")[1].strip(')')
        except IndexError:
            if ".png" in _:
                self.logo_url = _
            else:
                print(f"Failed to extract logo Url from: {_}")

        return table_image

    async def get_scorers(self, page) -> typing.List[Player]:
        """Fetch a list of scorers from a Flashscore Competition page returned as a list of Player Objects"""
        xp = ".//div[@class='tabs__group']"
        clicks = ['a[href$="top_scorers"]', 'div[class^="showMore"]']
        uri = self.url + "/standings"
        src = await browser.fetch(page, uri, xp, clicks=clicks, delete=ADS)

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
            else:
                print(f"Failed to extract logo Url from: {_}")

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
            players.append(Player(rank=rank, flag=flag, name=name, url=player_link, team=tm, team_url=team_link,
                                  country=country, goals=int(goals), assists=int(assists)))
        return players

    def view(self, ctx, page):
        """Return a view representing this Competition"""
        return CompetitionView(ctx, self, page)


class CompetitionView(discord.ui.View):
    """The view sent to a user about a Competition"""

    def __init__(self, ctx, competition: Competition, page):
        super().__init__()
        self.page = page
        self.ctx = ctx
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

    async def on_error(self, error, item, interaction):
        """Error logging"""
        print(f"Error in Competition View\n"
              f"Invoked with: {self.ctx.message.content}"
              f"Competition Info:\n"
              f"{self.competition.__dict__}\n"
              f"View Children")
        for x in self.children:
            print(x.__dict__)
        raise error

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.ctx.author.id

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except (discord.HTTPException, AttributeError):
            pass

        await self.page.close()
        self.stop()

    async def update(self):
        """Update the view for the Competition"""
        if self.message is None:
            return await self.on_timeout()

        async with self.semaphore:
            self.clear_items()
            if self.filter_mode is not None:
                await self.filter_players()

            if self.pages and len(self.pages) > 1:
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

            if self.filter_mode is not None:
                all_players = [('👕', str(i.team), str(i.team_url)) for i in self.players]
                teams = set(all_players)
                teams = sorted(teams, key=lambda x: x[1])  # Sort by second Value.

                if teams and len(teams) < 26:
                    _ = "Filter by Team..."
                    _ = view_utils.MultipleSelect(placeholder=_, options=teams, attribute='team_filter', row=2)
                    _.row = 2
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

            items = [view_utils.Button(label="Table", func=self.push_table, emoji="🥇", row=4),
                     view_utils.Button(label="Scorers", func=self.push_scorers, emoji='⚽', row=4),
                     view_utils.Button(label="Fixtures", func=self.push_fixtures, emoji='📆', row=4),
                     view_utils.Button(label="Results", func=self.push_results, emoji='⚽', row=4),
                     view_utils.StopButton(row=4)
                     ]

            for _ in items:
                _.disabled = True if self._current_mode == _.label else False
                self.add_item(_)

            try:
                embed = self.pages[self.index]
            except IndexError:
                embed = None if self.index == 0 else self.pages[0]

            try:
                await self.message.edit(content="", view=self, embed=embed)
            except discord.HTTPException:
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
            self.table_image = await image_utils.dump_image(self.ctx, img)
            self.table_timestamp = datetime.datetime.now()

        embed = await self.get_embed()
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition.title}"
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
        embed.title = f"≡ Fixtures for {self.competition.title}"
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Fixtures"
        self.filter_mode = None
        await self.update()

    async def push_results(self):
        """Push results fixtures to View"""
        rows = await self.competition.get_fixtures(page=self.page, subpage='/results')
        rows = [str(i) for i in rows] if rows else ["No Results Found :("]

        embed = await self.get_embed()
        embed.title = f"≡ Results for {self.competition.title}"
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Results"
        self.filter_mode = None
        await self.update()


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
        src = await browser.fetch(page, self.url + "/squad", xp)

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

    def view(self, ctx, page):
        """Return a view representing this Team"""
        return TeamView(ctx, self, page)


class TeamView(discord.ui.View):
    """The View sent to a user about a Team"""

    def __init__(self, ctx, team: Team, page):
        super().__init__()
        self.page = page  # Browser Page
        self.team = team
        self.ctx = ctx
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
        except discord.NotFound:
            pass

        self.stop()
        await self.page.close()

    async def on_error(self, error, item, interaction):
        """Extended Error Logging."""
        print(self.ctx.message.content)
        print(f'Ignoring exception in view {self} for item {item}:', file=sys.stderr)
        traceback.print_exception(error.__class__, error, error.__traceback__, file=sys.stderr)

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.ctx.author.id

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.team.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)  # Do not mutate.

    async def get_players(self):
        """Grab the list of players"""
        self.players = await self.team.get_players(page=self.page) if not self.players else self.players
        return self.players

    async def update(self):
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

                buttons = [view_utils.Button(label="Squad", func=self.push_squad),
                           view_utils.Button(label="Injuries", func=self.push_injuries, emoji=INJURY_EMOJI),
                           view_utils.Button(label="Scorers", func=self.push_scorers, emoji='⚽'),
                           view_utils.Button(label="Table", func=self.select_table, row=3),
                           view_utils.Button(label="Fixtures", func=self.push_fixtures, row=3),
                           view_utils.Button(label="Results", func=self.push_results, row=3),
                           view_utils.StopButton(row=0)
                           ]

                for _ in buttons:
                    _.disabled = True if self._current_mode == _.label else False
                    self.add_item(_)

            embed = self.pages[self.index] if self.pages else None
            try:
                await self.message.edit(content="", view=self, embed=embed)
            except discord.HTTPException:
                return await self.on_timeout()
        await self.wait()

    async def push_squad(self):
        """Push the Squad Embed to the team View"""
        players = await self.get_players()
        srt = sorted(players, key=lambda x: x.number)
        p = [i.squad_row for i in srt]

        # Data must be fetched before embed url is updated.
        embed = await self.get_embed()
        embed.title = f"≡ Squad for {self.team.title}"
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
        embed.title = f"≡ Injuries for {self.team.title}"
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
        embed.title = f"≡ Top Scorers for {self.team.title}"

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
        [_.append(x) for x in all_fixtures if x.full_league not in [y.full_league for y in _]]

        if len(_) == 1:
            return await self.push_table(_[0])

        self._currently_selecting = _

        leagues = [f"• [{x.full_league}]({x.url})" for x in _]
        self.pages[0].description = "**Use the dropdown to select a table**:\n\n " + "\n".join(leagues)
        await self.update()

    async def push_table(self, res):
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.get_embed()
        ts, dtn = self.table_timestamp, datetime.datetime.now()
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await res.get_table(self.page)
            if img is not None:
                self.table_image = await image_utils.dump_image(self.ctx, img)
                self.table_timestamp = datetime.datetime.now()

        embed.title = f"≡ Table for {res.full_league}"
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
        embed.title = f"≡ Fixtures for {self.team.title}" if embed.title else "≡ Fixtures "
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Fixtures"
        await self.update()

    async def push_results(self):
        """Push results fixtures to View"""
        rows = await self.team.get_fixtures(page=self.page, subpage='/results')
        rows = [str(i) for i in rows] if rows else ["No Results Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Results for {self.team.title}" if embed.title else "≡ Results "
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Results"
        await self.update()


class LeagueTableSelect(discord.ui.Select):
    """Push a Specific League Table"""

    def __init__(self, objects):
        self.objects = objects
        super().__init__(placeholder="Select which league to get table from...")
        for num, _ in enumerate(objects):
            self.add_option(label=_.full_league, emoji='🏆', description=_.url, value=str(num))

    async def callback(self, interaction):
        """Upon Item Selection do this"""
        await interaction.response.defer()
        await self.view.push_table(self.objects[int(self.values[0])])


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


async def fs_search(ctx, message, query) -> FlashScoreSearchResult or None:
    """Search using the aiohttp to fetch a single object matching the user's query"""
    search_results = await get_fs_results(ctx.bot, query)
    search_results = [i for i in search_results if isinstance(i, Competition)]  # Filter out non-leagues

    if not search_results:
        return None

    if len(search_results) == 1:
        return search_results[0]

    view = view_utils.ObjectSelectView(ctx.author, [('🏆', i.title, i.url) for i in search_results], timeout=30)
    view.message = message

    await view.update()
    await view.wait()

    return None if view.value is None else search_results[view.value]
