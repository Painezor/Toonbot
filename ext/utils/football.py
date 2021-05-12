import asyncio
import datetime
import json
import typing
import urllib.parse
from importlib import reload
from io import BytesIO
from json import JSONDecodeError

import aiohttp
import discord
from lxml import html

from ext.utils import embed_utils
from ext.utils import transfer_tools, image_utils, pyppeteer

reload(transfer_tools)
reload(image_utils)
reload(pyppeteer)

ADS = ['.//div[@class="seoAdWrapper"]', './/div[@class="banner--sticky"]', './/div[@class="box_over_content"]',
       './/div[@class="ot-sdk-container"]', './/div[@class="adsenvelope"]', './/div[@id="onetrust-consent-sdk"]',
       './/div[@id="lsid-window-mask"]', './/div[contains(@class, "isSticky")]', './/div[contains(@class, "rollbar")]',
       './/div[contains(@id,"box-over-content")]', './/div[contains(@class, "adsenvelope")]',
       './/div[contains(@class, "extraContent")]', './/div[contains(@class, "selfPromo")]',
       './/div[contains(@class, "otPlaceholder")]']


class MatchEvent:
    def __init__(self):
        pass
    
    # If this is object is empty, consider it false.
    def __bool__(self):
        return bool(self.__dict__)
    
    def __str__(self):
        return str(self.__dict__)
    
    def __repr__(self):
        return f"Event({self.__dict__})"


class Fixture:
    def __init__(self, time: typing.Union[str, datetime.datetime], home: str, away: str, **kwargs):
        self.time = time
        self.home = home
        self.away = away
        self.country = None
        self.league = None
        
        # Initialise some vars...
        self.score_home = None
        self.score_away = None
        self.events = None
        self.penalties_home = None
        self.penalties_away = None
        
        # Match Thread Bot specific vars
        self.kickoff = None
        self.referee = None
        self.stadium = None
        self.attendance = None
        self.formation = None
        self.comp_link = None
        self.images = None
        self.table = None
        self.__dict__.update(kwargs)
    
    def __repr__(self):
        return f"Fixture({self.__dict__})"
    
    def __str__(self):
        if hasattr(self, "url"):
            return f"`{self.formatted_time}:` [{self.bold_score}{self.tv}]({self.url})"
        else:
            return f"`{self.formatted_time}:` {self.bold_score}{self.tv}"
    
    @classmethod
    async def by_id(cls, match_id, page):
        url = "http://www.flashscore.com/match/" + match_id
        await pyppeteer.fetch(page, url, xpath=".//div[@class='team spoiler-content']")
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
        return '📺' if hasattr(self, "is_televised") and self.is_televised else ""
    
    @property
    async def base_embed(self) -> discord.Embed:
        e = discord.Embed()
        e.title = f"≡ {self.bold_score}"
        e.url = self.url
        
        e.set_author(name=f"{self.country}: {self.league}")
        if isinstance(self.time, datetime.datetime):
            e.timestamp = self.time
            if self.time > datetime.datetime.now():
                e.set_footer(text=f"Kickoff in {self.time - datetime.datetime.now()}")
        elif self.time == "Postponed":
            e.set_footer(text="This match has been postponed.")
            e.colour = discord.Color.red()
        else:
            e.set_footer(text=self.time)
            e.timestamp = datetime.datetime.now()
        
        e.colour = self.state_colour[1]
        return e
    
    @property
    def formatted_time(self):
        if isinstance(self.time, datetime.datetime):
            if self.time < datetime.datetime.now():  # in the past -> result
                return self.time.strftime('%a %d %b')
            else:
                return self.time.strftime('%a %d %b %H:%M')
        else:
            return self.time
    
    @property
    def score(self) -> str:
        if self.score_home is not None:
            return f"{self.score_home} - {self.score_away}"
        return "vs"
    
    @property
    def bold_score(self) -> str:
        if self.score_home is not None and self.score_home != "-":
            # Embolden Winner.
            if self.score_home > self.score_away:
                return f"**{self.home} {self.score_home}** - {self.score_away} {self.away}"
            elif self.score_home < self.score_away:
                return f"{self.home} {self.score_home} - **{self.score_away} {self.away}**"
            else:
                return f"{self.home} {self.score_home} - {self.score_away} {self.away}"
        else:
            return f"{self.home} vs {self.away}"
    
    @property
    def live_score_text(self) -> str:
        if self.state == "ht":
            self.time = "HT"
        if self.state == "fin":
            self.time = "FT"
            
        h_c = "`" + self.home_cards * '🟥' + "` " if self.home_cards else ""
        a_c = " `" + self.away_cards * '🟥' + "`" if self.away_cards else ""
    
        return f"`{self.state_colour[0]}` {self.time} {h_c}{self.bold_score}{a_c}"
    
    # For discord.
    @property
    def full_league(self) -> str:
        return f"{self.country.upper()}: {self.league}"
    
    @property
    def state_colour(self) -> typing.Tuple:
        if isinstance(self.time, datetime.datetime):
            return "", discord.Embed.Empty  # Non-live matches
        
        if hasattr(self, "state"):
            if self.state == "live":
                if self.time == "Extra Time":
                    return "⚪", 0xFFFFFF  # White
                elif "+" in self.time:
                    return "🟣", 0x9932CC  # Purple
                else:
                    return "🟢", 0x0F9D58  # Green
            
            if self.state == "fin":
                return "🔵", 0x4285F4  # Blue
            
            if self.state in ["Postponed", 'Cancelled', 'Abandoned']:
                return "🔴", 0xFF0000  # Red
            
            if self.state in ["Delayed", "Interrupted"]:
                return "🟠", 0xff6700  # Orange
            
            if self.state == "sched":
                return "⚫", 0x010101  # Black
            
            if self.state == "ht":
                return "🟡", 0xFFFF00  # Yellow
            
            else:
                print("Unhandled state:", self.state, self.home, self.away, self.url)
                return "🔴", 0xFF0000  # Red
        
        else:
            return "⚫", 0x010101  # Black
    
    async def get_badge(self, page, team) -> BytesIO:
        return await pyppeteer.fetch(page, self.url, f'.//div[contains(@class, tlogo-{team})]//img', screenshot=True)
    
    async def get_table(self, page) -> BytesIO:
        xp = './/div[contains(@class, "tableWrapper")]'
        link = self.url + "/#standings/table/overall"
        return await pyppeteer.fetch(page, link, xp, deletes=ADS, screenshot=True)
    
    async def get_stats(self, page) -> BytesIO:
        xp = ".//div[@id='detail']"
        link = self.url + "/#match-summary/match-statistics/0"
        return await pyppeteer.fetch(page, link, xp, deletes=ADS, screenshot=True)
    
    async def get_formation(self, page) -> BytesIO:
        xp = './/div[starts-with(@class, "fieldWrap")]'
        formation = await pyppeteer.fetch(page, self.url + "/#match-summary/lineups", xp, deletes=ADS, screenshot=True)
        xp = './/div[starts-with(@class, "lineUp")]'
        lineup = await pyppeteer.fetch(page, self.url + "/#match-summary/lineups", xp, deletes=ADS, screenshot=True)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, image_utils.stitch_vertical, [formation, lineup])
    
    async def get_summary(self, page) -> BytesIO:
        xp = ".//div[@id='summary-content']"
        return await pyppeteer.fetch(page, self.url + "#match-summary", xp, deletes=ADS, screenshot=True)
    
    async def head_to_head(self, page) -> typing.Dict:
        xp = ".//div[@id='tab-h2h-overall']"
        await pyppeteer.fetch(page, self.url + "/#h2h/overall", xp, deletes=ADS)
        tree = html.fromstring(await page.content())
        games = {}
        for i in tree.xpath('.//div[starts-with(@class, "h2h")]//div[starts-with(@class, "section")]'):
            header = "".join(i.xpath('.//div[starts-with(@class, "title")]//text()')).strip().title()
            
            fixtures = i.xpath('.//div[starts-with(@class, "row_")]')
            fx_list = []
            
            for game in fixtures[:5]:  # Last 5 only.
                try:
                    game_id = game.xpath('.//@onclick')[0].split('(')[-1].split(',')[0].strip('\'').split('_')[-1]
                    url = "http://www.flashscore.com/match/" + game_id
                except IndexError:
                    url = None
                    
                home = "".join(game.xpath('.//span[starts-with(@class, "homeParticipant")]/text()')).strip().title()
                away = "".join(game.xpath('.//span[starts-with(@class, "awayParticipant")]/text()')).strip().title()
                time = game.xpath('.//span[starts-with(@class, "date")]/text()')[0]
                score_home, score_away = game.xpath('.//span[starts-with(@class, "regularTime")]//text()')[0].split(':')
                
                score_home, score_away = int(score_home.strip()), int(score_away.strip())
                
                fx = Fixture(home=home, away=away, time=time, score_home=score_home, score_away=score_away, url=url)
                print(fx)
                
                fx_list.append(fx)
            games.update({header: fx_list})
        
        return games
    
    async def refresh(self, page, for_discord=True):  # This is a very intensive, full lookup
        xp = ".//div[@id='utime']"
        
        for i in range(3):
            try:
                await pyppeteer.fetch(page, self.url, xp)
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
        
        if not for_discord:
            scores = tree.xpath('.//div[start-with(@class, "score")]//span//text()')
            self.score_home = int(scores[0])
            self.score_away = int(scores[1])
            self.formation = await self.get_formation(page)
            self.table = await self.get_table(page)
        
        event_rows = tree.xpath('.//div[starts-with(@class, "verticalSections")]/div')
        events = []
        pens = False
        
        for i in event_rows:
            event_class = i.attrib['class']
            event = MatchEvent()
            
            # Detection for penalty mode, discard headers.
            if "Header" in event_class:
                parts = [x.strip() for x in i.xpath('.//text()')]
                if "Penalties" in parts:
                    self.penalties_home = parts[1]
                    self.penalties_away = parts[3]
                    pens = True
                continue
            
            # Detection of Teams
            if "home" in event_class:
                event.team = self.home
            elif "away" in event_class:
                event.team = self.away
            elif "empty" in event_class:
                continue  # No events in half signifier.
            else:
                print('no team detected within event_class', event_class)
                
            e_n = i.xpath('./div[starts-with(@class, "incident_")]')[0]  # event_node
            
            event.time = "".join(e_n.xpath('.//div[starts-with(@class, "timeBox")]//text()')).strip()
            icon = "".join(e_n.xpath('.//div[starts-with(@class, "incidentIcon")]//svg/@class')).strip()
            event_desc = "".join(e_n.xpath('.//div[starts-with(@class, "incidentIcon")]/div/@title')).strip()
            if event_desc:
                event_desc = event_desc.replace('<br />', ' ')
                event.full_description = event_desc
            icon_desc = "".join(e_n.xpath('.//div[starts-with(@class, "incidentIcon")]//svg//text()')).strip()
            
            if "goal" in icon.lower():
                if "own" in icon.lower():
                    event.type = "Own Goal"
                else:
                    event.type = "PSO: Scored" if pens else "Goal"
                    if "Penalty" in icon_desc:
                        event.note = "(p)"
                        
            elif icon.startswith("penaltyMissed"):
                event.type = "PSO: Missed" if pens else "Penalty MIss"
            
            elif "arrowUp" in icon:
                event.type = "Substitution"
                sub_off = "".join(e_n.xpath('./div[starts-with(@class, "incidentSubOut")]/a/text()')).strip()
                if sub_off:
                    event.player_off = sub_off
            elif icon.startswith("redYellow"):
                event.type = "Second Yellow"
                if icon_desc:
                    event.note = icon_desc
                
            elif icon.startswith("redCard"):
                event.type = "Dismissal"
                if icon_desc:
                    event.note = icon_desc

            elif icon.startswith("yellowCard"):
                event.type = "Booking"
                if icon_desc:
                    event.note = icon_desc
            
            elif icon.startswith("var"):
                event.type = "VAR"
                if icon_desc:
                    event.note = icon_desc
                else:
                    maybe_note = "".join(e_n.xpath('./div/div/text()')).strip()
                    if maybe_note:
                        event.note = maybe_note
            
            else:
                if icon.startswith("card"):
                    if icon_desc == "Red Card":
                        event.type = "Dismissal"
                else:
                    print(self.url)
                    print('Undeclared event type for', icon)
            
            # Data not always present.
            player = "".join(e_n.xpath('.//a[starts-with(@class, "playerName")]/div/text()')).strip()
            event.player = player
                
            assist = "".join(e_n.xpath('.//div[starts-with(@class, "assist")]/a/text()'))
            if assist:
                event.assist = assist
            
            try:
                description = e_n.attrib['title']
                event.description = description.replace('<br />', ' ')
            except KeyError:
                pass
            
                events.append(event)
        self.events = events
        
        # TODO: Fetching images
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')
        # TODO: fetching statistics


class Player:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        
    def __bool__(self):
        return bool(self.__dict__)
    
    @property
    def scorer_row(self):
        g =  f"`{self.rank.rjust(3, ' ')}` {self.flag} [**{self.name}**]({self.link}) " \
               f"**{self.goals} Goals**"
        if self.assists > 0:
            g += f" ({self.assists} Assists)"
        return g


class FlashScoreSearchResult:
    def __init__(self, **kwargs):
        self.logo_url = None
        self.__dict__.update(**kwargs)
        
    async def get_logo(self, page):
        try:
            logo = await page.xpath('.//div[contains(@class,"logo")]')
            logo = logo[0]
        except IndexError:
            return

        logo_raw = await page.evaluate("el => window.getComputedStyle(el).backgroundImage", logo)
        self.logo_url = logo_raw.strip("url(").strip(")").strip('"')
    
    @property
    async def base_embed(self) -> discord.Embed:
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
        e.url = self.link
        e.timestamp = datetime.datetime.now()
        return e
    
    async def get_fixtures(self, page, subpage=""):
        await pyppeteer.fetch(page, self.link + subpage, './/div[@class="sportName soccer"]')
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
            try:
                score_home, score_away = i.xpath('.//div[contains(@class,"event__scores")]/span/text()')
            except ValueError:
                score_home, score_away = None, None
            else:
                score_home = int(score_home.strip())
                score_away = int(score_away.strip())
    
            home, away = i.xpath('.//div[contains(@class,"event__participant")]/text()')
    
            time = "".join(i.xpath('.//div[@class="event__time"]//text()'))
    
            for x in ["Pen", 'AET', 'FRO', 'WO']:
                time = time.replace(x, '')
    
            if "'" in time:
                time = f"⚽ LIVE! {time}"
            elif not time:
                time = "?"
            elif "Postp" in time:
                time = "🚫 Postponed "
            elif "Awrd" in time:
                try:
                    time = datetime.datetime.strptime(time.strip('Awrd'), '%d.%m.%Y')
                except ValueError:
                    time = datetime.datetime.strptime(time.strip('Awrd'), '%d.%m. %H:%M')
                time = time.strftime("%d/%m/%Y")
                time = f"{time} 🚫 FF"  # Forfeit
            else:  # Should be dd.mm hh:mm or dd.mm.yyyy
                try:
                    time = datetime.datetime.strptime(time, '%d.%m.%Y')
                    if time.year != datetime.datetime.now().year:
                        time = time.strftime("%d/%m/%Y")
                except ValueError:
                    dtn = datetime.datetime.now()
                    try:
                        time = datetime.datetime.strptime(f"{dtn.year}.{time}", '%Y.%d.%m. %H:%M')
                    except ValueError:
                        time = datetime.datetime.strptime(f"{dtn.year}.{dtn.day}.{dtn.month}.{time}", '%Y.%d.%m.%H:%M')
    
            is_televised = True if i.xpath(".//div[contains(@class,'tv')]") else False
            fixture = Fixture(time, home.strip(), away.strip(), score_home=score_home, score_away=score_away,
                              is_televised=is_televised,
                              country=country.strip(), league=league.strip(), url=url)
            fixtures.append(fixture)
        return fixtures


class Competition(FlashScoreSearchResult):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    @classmethod
    async def by_id(cls, comp_id, page):
        url = "http://flashscore.com/?r=2:" + comp_id
        await pyppeteer.fetch(page, url, ".//div[@class='team spoiler-content']")
        tree = html.fromstring(await page.content())
        
        country = tree.xpath('.//h2[@class="tournament"]/a[2]//text()')[0].strip()
        league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
        title = f"{country.upper()}: {league}"
        return cls(url=url, title=title)
    
    @classmethod
    async def by_link(cls, link, page):
        
        try:
            await pyppeteer.fetch(page, link, xpath=".//div[@class='team spoiler-content']")
        except Exception as err:
            raise err
        
        tree = html.fromstring(await page.content())
        
        try:
            country = tree.xpath('.//h2[@class="breadcrumb"]//a/text()')[-1].strip()
            league = tree.xpath('.//div[@class="teamHeader__name"]//text()')[0].strip()
            title = f"{country.upper()}: {league}"
        except IndexError:
            print(f'Error fetching Competition country/league by_link - {link}')
            title = "Unidentified League"

        return cls(url=link, title=title)
    
    @property
    def link(self):
        if "https://" in self.url:
            return self.url
        ctry = self.country_name.lower().replace(' ', '-')
        return f"https://www.flashscore.com/soccer/{ctry}/{self.url}"
    
    async def get_table(self, page) -> BytesIO:
        xp = './/div[contains(@class, "tableWrapper")]/parent::div'
        table_image = await pyppeteer.fetch(page, self.link + "/standings/", xp, deletes=ADS, screenshot=True)
        await self.get_logo(page)
        return table_image
    
    async def get_scorers(self, page) -> typing.List[Player]:
        xp = ".//div[@class='tabs__group']"
        clicks = ['a[href$="top_scorers"]', 'div[class^="showMore"]']
        await pyppeteer.fetch(page, self.link + "/standings", xp, clicks=clicks, deletes=ADS,   debug=True)
        await self.get_logo(page)
    
        tree = html.fromstring(await page.content())
        rows = tree.xpath('.//div[contains(@class,"rows")]/div')
        
        players = []
        
        for i in rows:
            items = i.xpath('.//text()')
            items = [i.strip() for i in items if i.strip()]
            links = i.xpath(".//a/@href")
            
            player_link, team_link = ["http://www.flashscore.com/" + i for i in links]
            
            rank, name, tm, goals, assists = items
            
            country = "".join(i.xpath('.//span[contains(@class,"flag")]/@title')).strip()
            flag = transfer_tools.get_flag(country)
            players.append(Player(rank=rank, flag=flag, name=name, link=player_link, team=tm, team_link=team_link,
                                  goals=int(goals), assists=int(assists)))
        await self.get_logo(page)
        return players


class Team(FlashScoreSearchResult):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    @classmethod
    async def by_id(cls, team_id, page):
        url = "http://flashscore.com/?r=3:" + team_id
        await pyppeteer.fetch(page, url, "body")
        url = await page.evaluate("() => window.location.href")
        return cls(url=url, id=team_id)
    
    @property
    def link(self):
        if "://" in self.url:
            return self.url
        # Example Team URL: https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        return f"https://www.flashscore.com/team/{self.url}/{self.id}"
    
    async def get_players(self, page, tab=0) -> typing.List[Player]:
        xp = './/div[contains(@class,"playerTable")]'
        await pyppeteer.fetch(page, self.link + "/squad", xp)
        tree = html.fromstring(await page.content())
        tab += 1  # tab is Indexed at 0 but xpath indexes from [1]
        rows = tree.xpath(f'.//div[contains(@class, "playerTable")][{tab}]//div[contains(@class,"profileTable__row")]')
        
        players = []
        position = ""
        for i in rows:
            pos = "".join(i.xpath('./text()')).strip()
            if pos:  # The way the data is structured contains a header row with the player's position.
                try:
                    position = pos.strip('s')
                except IndexError:
                    position = pos
                continue  # There will not be additional data.
            
            name = "".join(i.xpath('.//div[contains(@class,"")]/a/text()'))
            try:  # Name comes in reverse order.
                player_split = name.split(' ', 1)
                name = f"{player_split[1]} {player_split[0]}"
            except IndexError:
                pass
            
            country = "".join(i.xpath('.//span[contains(@class,"flag")]/@title'))
            flag = transfer_tools.get_flag(country)
            number = "".join(i.xpath('.//div[@class="tableTeam__squadNumber"]/text()'))
            try:
                age, apps, g, y, r = i.xpath(
                    './/div[@class="playerTable__icons playerTable__icons--squad"]//div/text()')
            except ValueError:
                age = "".join(i.xpath('.//div[@class="playerTable__icons playerTable__icons--squad"]//div/text()'))
                apps = g = y = r = 0
            injury = "".join(i.xpath('.//span[contains(@class,"absence injury")]/@title'))
            if injury:
                injury = f"<:injury:682714608972464187> " + injury  # I really shouldn't hard code emojis.
            
            link = "".join(i.xpath('.//div[contains(@class,"")]/a/@href'))
            link = f"http://www.flashscore.com{link}" if link else ""
            
            try:
                number = int(number)
            except ValueError:
                number = 00
            
            pl = Player(name=name, number=number, country=country, link=link, position=position,
                        age=age, apps=apps, goals=int(g), yellows=y, reds=r, injury=injury, flag=flag)
            players.append(pl)
        return players
    
    async def get_competitions(self, page) -> typing.List[str]:
        xp = './/div[contains(@class, "subTabs")]'
        await pyppeteer.fetch(page, self.link + '/squad', xp)
        tree = html.fromstring(await page.content())
        options = tree.xpath('.//div[contains(@class, "subTabs")]/div/text()')
        options = [i.strip() for i in options]
        return options


class Goal:
    def __init__(self, embed, home, away, competition, title, **kwargs):
        self.embed = embed
        self.home = home
        self.away = away
        self.competition = competition
        self.title = title
        self.__dict__.update(kwargs)
    
    @property
    def fixture(self) -> str:
        return f"{self.home} vs {self.away}"
    
    @property
    def clean_link(self) -> str:
        return self.embed.split('src=\'')[1].split("?s=2")[0].replace('\\', '')
    
    @property
    def markdown_link(self) -> str:
        return f"[{self.title}]({self.clean_link})"


class Stadium:
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
        async with aiohttp.ClientSession() as cs:
            async with cs.get(self.url) as resp:
                tree = html.fromstring(await resp.text())
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
        e = discord.Embed()
        e.set_author(name="FootballGroundMap.com", url="http://www.footballgroundmap.com")
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
            link = "".join(s.xpath('./@href'))
            
            if query.lower() not in name.lower() and query.lower() not in team.lower():
                continue  # Filtering.
            
            if not any(c.name == name for c in stadiums) and not any(c.url == link for c in stadiums):
                stadiums.append(Stadium(url=link, name=name, team=team, team_badge=team_badge,
                                        country=country, league=league))
                
    return stadiums


async def get_fs_results(query) -> typing.List[FlashScoreSearchResult]:
    qry_debug = query
    
    for r in ["'", "[", "]", "#", '<', '>']:  # Fucking morons.
        query = query.replace(r, "")
    
    query = urllib.parse.quote(query)
    async with aiohttp.ClientSession() as cs:
        # One day we could probably expand upon this if we figure out what the other variables are.
        async with cs.get(f"https://s.flashscore.com/search/?q={query}&l=1&s=1&f=1%3B1&pid=2&sid=1") as resp:
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


async def fs_search(ctx, query):
    search_results = await get_fs_results(query)
    search_results = [i for i in search_results if i.participant_type_id == 0]  # Filter out non-leagues
    item_list = [i.title for i in search_results]
    index = await embed_utils.page_selector(ctx, item_list)
    
    if index is None:
        if not search_results:
            await ctx.bot.reply(ctx, text=f"🚫 No leagues found for {query}, channel not modified.")
        else:
            await ctx.bot.reply(ctx, text=f"🚫 Timed out waiting for you to reply, channel not modified.")
        return None  # Timeout or abort.
    elif index == "cancelled":
        return None
    
    return search_results[index]
