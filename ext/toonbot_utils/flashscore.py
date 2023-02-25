"""A Utility tool for fetching and structuring data from Flashscore"""
from __future__ import annotations  # Cyclic Type Hinting

import logging
from asyncio import Semaphore
from datetime import datetime, timezone
from io import BytesIO
from typing import TYPE_CHECKING, Optional, ClassVar

from discord import Embed, Interaction, Colour
from discord.app_commands import Choice
from lxml import html
from playwright.async_api import Page

from ext.toonbot_utils.gamestate import GameState
from ext.utils.embed_utils import get_colour
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp

import ext.toonbot_utils.matchevents as m_evt

if TYPE_CHECKING:
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
async def lg_ac(interaction: Interaction[Bot], cur: str) -> list[Choice[str]]:
    """Autocomplete from list of stored leagues"""
    bot = interaction.client
    cur = cur.lower()

    matches = [i for i in bot.competitions if cur in i.title.lower()]
    choices = [Choice(name=i.title[:100], value=i.id) for i in matches if i.id]
    return choices[:25]


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""

    bot: ClassVar[Bot]

    def __init__(
        self, fsid: Optional[str], name: Optional[str], url: Optional[str]
    ) -> None:
        self.id: Optional[str] = fsid
        self.name: Optional[str] = name
        self.url: Optional[str] = url
        self.embed_colour: Colour | int
        self.logo_url: str

    def __hash__(self) -> int:
        return hash(repr(self))

    def __repr__(self) -> str:
        return f"FlashScoreItem({self.__dict__})"

    def __eq__(self, other: FlashScoreItem):
        if None not in [self.id, other]:
            return self.id == other.id

        if None not in [self.url, other]:
            return self.url == other.url

    @property
    def markdown(self) -> str:
        """Shorthand for FSR mark-down link"""
        if self.url is not None:
            return f"[{self.name or 'Unknown Item'}]({self.url})"
        return self.name or "Unknown Item"

    @property
    def title(self) -> str:
        return self.name or "Unknown Item"

    async def base_embed(self) -> Embed:
        """A discord Embed representing the flashscore search result"""

        e: Embed = Embed(title=self.title, url=self.url)
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
                        comp = Competition(None, league, country, None)
                continue

            xp = './/div[contains(@class,"event__participant")]/text()'
            home, away = i.xpath(xp)

            # TODO: Fetch team ID & URL
            home = Team(None, home.strip(), None)
            away = Team(None, away.strip(), None)

            fixture = Fixture(home, away, fx_id, url)
            fixture.competition = comp

            # score
            try:
                xp = './/div[contains(@class,"event__score")]//text()'
                score_home, score_away = i.xpath(xp)

                fixture.score_home = int(score_home.strip())
                fixture.score_away = int(score_away.strip())
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

                    if ko > datetime.now(tz=timezone.utc):
                        state = GameState.SCHEDULED
                    else:
                        state = GameState.FULL_TIME
                    break
                except ValueError:
                    continue
            else:
                logger.error(f"Failed to convert {parsed} to datetime.")

            # Bypass time setter by directly changing _private val.
            if isinstance(state, GameState):
                fixture.time = state
            else:
                if "'" in parsed or "+" in parsed or parsed.isdigit():
                    fixture.time = parsed
                else:
                    logger.error(f'state "{state}" ({parsed}) not handled.')
            fixtures.append(fixture)
        return fixtures


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""

    __slots__ = {
        "competition": "The competition the team belongs to",
        "logo_url": "A link to a logo representing the competition",
        "gender": "The Gender that this team is comprised of",
    }

    # Constant
    emoji: ClassVar[str] = "👕"

    def __init__(
        self, fs_id: Optional[str], name: str, url: Optional[str]
    ) -> None:

        # Example URL:
        # https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        # https://www.flashscore.com/?r=3:jLsL0hAF

        if fs_id is None and url:
            url = url.split("/")[-1]
        elif url is None and name and fs_id:
            url = FLASHSCORE + f"/team/{url}/{fs_id}"
        elif fs_id and not url:
            url = f"https://www.flashscore.com/?r=3:{id}"

        super().__init__(fs_id, name, url)

        self.name: str
        self.gender: str
        self.competition: Optional[Competition]

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
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

    async def fixtures(self) -> list[Fixture]:
        """Get all upcoming fixtures related to the FlashScoreItem"""
        if self.url is None:
            return []
        return await self.parse_games(self.url + "/fixtures/")

    async def results(self) -> list[Fixture]:
        """Get recent results for the FlashScore Item"""
        if self.url is None:
            return []
        return await self.parse_games(self.url + "/results/")

    async def news(self) -> list[Embed]:
        """Get a list of news articles related to a team in embed format"""
        page = await self.bot.browser.new_page()
        try:
            await page.goto(f"{self.url}/news", timeout=5000)
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
                await page.goto(f"{self.url}/squad", timeout=5000)
                await page.locator(".squad-table.profileTable").wait_for()
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
        position: str = "?"

        for i in rows:
            # A header row with the player's position.
            if pos := "".join(i.xpath("./div/text()")).strip():
                try:
                    position = pos.strip("s")
                except IndexError:
                    position = pos
                continue  # There will not be additional data.

            xpath = './/div[contains(@class, "cell--name")]/a/'
            link = "".join(i.xpath(xpath + "@href"))
            name = "".join(i.xpath(xpath + "text()"))
            try:  # Name comes in reverse order.
                surname, forename = name.split(" ", 1)
                name = f"{forename} {surname}"
            except ValueError:
                pass

            player = Player(name, link)
            player.team = self
            player.position = position

            # Set ID & 'url' from returned href.
            xpath = './/div[contains(@class, "cell--name")]/a/@href'
            if href := "".join(i.xpath(xpath)).split("/"):
                player.id = href[-1]
                player.url = href[-2]

            xpath = './/span[contains(@class,"flag")]/@title'
            player.country = i.xpath(xpath)

            xpath = './/span[contains(@class,"jersey")]/text()'
            player.squad_number = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"cell--age")]/text()'
            player.age = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"cell--goal")]/text()'
            player.goals = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"matchesPlayed")]/text()'
            player.appearances = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"yellowCard")]/text()'
            player.yellows = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"redCard")]/text()'
            player.reds = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@title,"Injury")]/@title'
            player.injury = "".join(i.xpath(xpath))
            players.append(player)
        return players


class Player(FlashScoreItem):
    """An object representing a player from flashscore."""

    def __init__(self, name: Optional[str], url: Optional[str]) -> None:

        super().__init__(None, url=url, name=name)

        self.squad_number: Optional[int]
        self.position: Optional[str]
        self.country: list[str]
        self.team: Optional[Team]
        self.competition: Optional[Competition]
        self.age: Optional[int]
        self.appearances: Optional[int]
        self.goals: Optional[int]
        self.assists: Optional[int]
        self.rank: Optional[int]
        self.yellows: Optional[int]
        self.reds: Optional[int]
        self.injury: Optional[str]

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return get_flag(self.country) or ""

    @property
    def link(self) -> str:
        """Alias to self.url"""
        if self.url is None:
            return ""

        if "https://" in self.url:
            return self.url
        else:
            return FLASHSCORE + self.url

    @property
    def squad_row(self) -> str:
        """String for Team Lineup."""
        match self.squad_number:
            case 0, None:
                output = ["`  `:"]
            case _:
                output = [f"`{str(self.squad_number).rjust(2)}`:"]

        output += self.flag
        output.append(self.markdown)

        if self.position is not None:
            output.append(self.position)

        if self.injury is not None:
            output += [INJURY_EMOJI, self.injury]

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


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji: ClassVar[str] = "🏆"

    def __init__(
        self,
        fsid: Optional[str],
        name: Optional[str],
        country: Optional[str],
        url: Optional[str],
    ) -> None:

        # https://www.flashscore.com/?r=1:jLsL0hAF

        if name and country and not url:
            nom = name.lower()
            nom = name.replace(" ", "-").replace(".", "")
            ctr = country.lower()
            ctr = country.replace(" ", "-").replace(".", "")
            url = FLASHSCORE + f"football/{ctr}/{nom}"
        elif fsid and not url:
            url = f"https://www.flashscore.com/?r=2:{url}"
            # This might also be 1?

        super().__init__(fsid, url, name)

        self.logo_url: Optional[str]

        self.name: str
        self.country: str
        self.score_embeds: list[Embed] = []

        # Table Imagee
        self.table: Optional[str]

    def __str__(self) -> str:
        return self.title

    @classmethod
    async def by_link(cls, bot: Bot, link: str) -> Competition:
        """Create a Competition Object from a flashscore url"""

        async with semaphore:
            page = await bot.browser.new_page()
            try:
                await page.goto(link, timeout=5000)
                await page.wait_for_selector(".heading")
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

        try:
            xp = './/h2[@class="breadcrumb"]//a/text()'
            country = "".join(tree.xpath(xp)).strip()

            xp = './/div[@class="heading__name"]//text()'
            name = tree.xpath(xp)[0].strip()
        except IndexError:
            name = "Unidentified League"
            country = "Unidentified Country"

        # TODO: Extract the ID from the URL
        comp = cls(None, name, country, link)

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

    async def fixtures(self) -> list[Fixture]:
        """Get all upcoming fixtures related to the FlashScoreItem"""
        if self.url is None:
            return []
        return await self.parse_games(self.url + "/fixtures/")

    async def results(self) -> list[Fixture]:
        """Get recent results for the FlashScore Item"""
        if self.url is None:
            return []
        return await self.parse_games(self.url + "/results/")

    async def get_table(self) -> Optional[str]:
        """Fetch the table from a flashscore Competition and return it as
        a BytesIO object"""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.url}/standings/", timeout=5000)
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
                await page.goto(f"{self.url}/standings/", timeout=5000)

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

            xp = './/div[contains(@class, "--player")]//text()'
            name = "".join(i.xpath(xp))

            xp = './/div[contains(@class, "--player")]//@href'
            url = FLASHSCORE + "".join(i.xpath(xp))

            player = Player(name, url)
            player.rank = rank

            xp = './/span[contains(@class,"flag")]/@title'
            player.country = i.xpath(xp)

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
                team_name = "".join(i.xpath(".//a/text()"))
                team_link = "".join(i.xpath(".//a/@href"))
                team = Team(team_id, team_name, team_link)
                team.competition = self

            player.team = team

            scorers.append(player)
        return scorers

    @property
    def table_link(self) -> str:
        """Return [Click To View Table](url) or empty string if not found"""
        return f"\n[View Table]({self._table})" if self._table else ""


class Fixture:
    """An object representing a Fixture from the Flashscore Website"""

    emoji: ClassVar[str] = "⚽"

    def __init__(
        self, home: Team, away: Team, fs_id: Optional[str], url: Optional[str]
    ) -> None:

        if fs_id and not url:
            url = f"https://www.flashscore.com/?r=5:{fs_id}"

        self.url: Optional[str] = url
        self.fs_id: Optional[str] = fs_id

        self.away = away
        self.cards_away: Optional[int] = None
        self.score_away: Optional[int] = None
        self.penalties_away: Optional[int] = None

        self.home = home
        self.cards_home: Optional[int] = None
        self.score_home: Optional[int] = None
        self.penalties_home: Optional[int] = None

        self.time: str | GameState
        self.kickoff: datetime
        self.ordinal: Optional[int] = None

        self.attendance: Optional[int] = None
        self.breaks: int = 0
        self.competition: Optional[Competition] = None
        self.events: list[m_evt.MatchEvent] = []
        self.infobox: Optional[str] = None
        self.images: Optional[list[str]] = None

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
    def state(self) -> GameState:
        """Get a GameState value from stored _time"""
        if isinstance(self.time, str):
            if "+" in self.time:
                return GameState.STOPPAGE_TIME
            else:
                return GameState.LIVE
        else:
            return self.time

    @property
    def upcoming(self) -> str:
        """Format for upcoming games in /fixtures command"""
        return f"{Timestamp(self.kickoff).relative}: {self.bold_markdown}"

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
        if self.score_home is None or self.score_away is None:
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
        if self.score_home is None or self.score_away is None:
            return f"[{self.home.name} vs {self.away.name}]({self.url})"

        home = self.home.name
        away = self.away.name
        # Embolden Winner
        if self.score_home > self.score_away:
            home = f"**{home}**"
        if self.score_away > self.score_home:
            away = f"**{away}**"

        def parse_cards(cards: Optional[int]) -> str:
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
        return f"{home} {hc}[{sh} - {sa}]({self.url}){ac} {away}"

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output = []
        if self.time is not None:
            output.append(f"`{self.state.emote}")

        if isinstance(self.time, str):
            output.append(f"{self.time}`")
        else:
            output.append(f"{self.state.shorthand}`")

        h = self.home.name
        a = self.away.name

        if self.score_home is None or self.score_away is None:
            time = Timestamp(self.kickoff).time_hour
            output.append(f"{time} [{h} v {a}]({self.url})")
        else:
            # Penalty Shootout
            if self.penalties_home is not None:
                pens = f" (p: {self.penalties_home} - {self.penalties_away}) "
                s = min(self.score_home, self.score_away)

                output.append(f"{h} [{s} - {s}]({self.url}){pens}{a}")
            else:
                output.append(self.bold_markdown)
        return " ".join(output)

    @property
    def autocomplete(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        if self.competition:
            cmp = self.competition.title
            return f"⚽ {self.home.name} {self.score} {self.away.name} ({cmp})"
        return f"⚽ {self.home.name} {self.score} {self.away.name}"

    async def base_embed(self) -> Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        e: Embed = (
            await self.competition.base_embed()
            if self.competition
            else Embed()
        )
        e.url = self.url
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

        if self.competition:
            e.set_footer(text=f"{self.time} - {self.competition.title}")
        else:
            e.set_footer(text=self.time)
        return e

    # This function Generates Event Objects from the etree.
    def parse_events(self, tree) -> list[m_evt.MatchEvent]:
        """Get a list of match events"""

        events = []

        for i in tree.xpath(
            './/div[contains(@class, "verticalSections")]/div'
        ):
            # Detection of Teams
            team_detection = i.attrib["class"]
            if "Header" in team_detection:
                parts = [x.strip() for x in i.xpath(".//text()")]
                if "Penalties" in parts:
                    try:
                        self.penalties_home = parts[1]
                        self.penalties_away = parts[3]
                    except ValueError:
                        _, pen_string = parts
                        h, a = pen_string.split(" - ")
                        self.penalties_home = h
                        self.penalties_away = a
                continue
            elif "home" in team_detection:
                team = self.home
            elif "away" in team_detection:
                team = self.away
            elif "empty" in team_detection:
                continue  # No events in half signifier.
            else:
                logging.error(
                    f"No team found for team_detection {team_detection}"
                )
                continue

            node = i.xpath('./div[contains(@class, "incident")]')[
                0
            ]  # event_node
            xpath = './/div[contains(@class, "incidentIcon")]//@title'
            title = "".join(node.xpath(xpath)).strip()
            description = title.replace("<br />", " ")

            xpath = './/div[contains(@class, "incidentIcon")]//svg//text()'
            icon_desc = "".join(node.xpath(xpath)).strip()

            xpath = './/div[contains(@class, "incidentIcon")]//svg/@class'
            match (icon := "".join(node.xpath(xpath)).strip()).lower():
                # Goal types
                case "footballGoal-ico" | "soccer":
                    match icon_desc.lower():
                        case "goal" | "":
                            event = m_evt.Goal()
                        case "penalty":
                            event = m_evt.Penalty()
                        case _:
                            logging.error(
                                f"[GOAL] icon: <{icon}> unhandled"
                                f"icon_desc: <{icon_desc}> on {self.url}"
                            )
                            continue
                case "footballowngoal-ico" | "soccer footballowngoal-ico":
                    event = m_evt.OwnGoal()
                case "penaltymissed-ico":
                    event = m_evt.Penalty(missed=True)
                # Card Types
                case "yellowcard-ico" | "card-ico yellowcard-ico":
                    event = m_evt.Booking()
                    event.note = icon_desc
                case "redyellowcard-ico":
                    event = m_evt.SecondYellow()
                    if "card / Red" not in icon_desc:
                        event.note = icon_desc
                case "redcard-ico" | "card-ico redcard-ico":
                    event = m_evt.RedCard()
                    if icon_desc != "Red Card":
                        event.note = icon_desc
                case "card-ico":
                    event = m_evt.Booking()
                    if icon_desc != "Yellow Card":
                        event.note = icon_desc
                # Substitutions
                case "substitution-ico" | "substitution":
                    event = m_evt.Substitution()

                    xpath = './/div[contains(@class, "incidentSubOut")]/a/'
                    s_name = "".join(node.xpath(xpath + "text()")).strip()
                    s_link = "".join(node.xpath(xpath + "@href")).strip()

                    event.player_off = Player(s_name, s_link)
                # VAR types
                case "var-ico" | "var":
                    event = m_evt.VAR()
                    if not icon_desc:
                        icon_desc = "".join(
                            node.xpath("./div//text()")
                        ).strip()
                    if icon_desc:
                        event.note = icon_desc
                case "varlive-ico" | "var varlive-ico":
                    event = m_evt.VAR(in_progress=True)
                    event.note = icon_desc
                case _:  # Backup checks.
                    match icon_desc.strip().lower():
                        case "penalty" | "penalty kick":
                            event = m_evt.Penalty()
                        case "penalty missed":
                            event = m_evt.Penalty(missed=True)
                        case "own goal":
                            event = m_evt.OwnGoal()
                        case "goal":
                            event = m_evt.Goal()
                            if icon_desc and icon_desc.lower() != "goal":
                                logging.error(
                                    f"[GOAL] unh icon_desc: {icon_desc}"
                                )
                                continue
                        # Red card
                        case "red card":
                            event = m_evt.RedCard()
                        # Second Yellow
                        case "yellow card / red card":
                            event = m_evt.SecondYellow()
                        case "warning":
                            event = m_evt.Booking()
                        # Substitution
                        case "substitution - in":
                            event = m_evt.Substitution()

                            trg = "incidentSubOut"
                            xpath = f'.//div[contains(@class, "{trg}")]/a/'
                            s_name = "".join(node.xpath(xpath + "text()"))
                            s_name = s_name.strip()
                            s_link = "".join(node.xpath(xpath + "@href"))

                            event.player_off = Player(s_name, s_link)
                        case _:
                            logging.error(
                                f"Match Event (icon: {icon})\n"
                                f"icon_desc: {icon_desc}\n{self.url}"
                            )
                            continue

            event.team = team

            # Data not always present.
            xpath = './/a[contains(@class, "playerName")]//text()'
            if p_name := "".join(node.xpath(xpath)).strip():
                xpath = './/a[contains(@class, "playerName")]//@href'
                p_url = "".join(node.xpath(xpath)).strip()
                event.player = Player(p_name, p_url)

            if isinstance(event, m_evt.Goal):
                xpath = './/div[contains(@class, "assist")]//text()'
                if assist := "".join(node.xpath(xpath)):
                    xpath = './/div[contains(@class, "assist")]//@href'
                    a_url = "".join(node.xpath(xpath))

                    assist = assist.strip("()")
                    p = Player(assist, a_url)
                    event.assist = p

            if description:
                event.description = description

            xpath = './/div[contains(@class, "timeBox")]//text()'
            event.time = "".join(node.xpath(xpath)).strip()
            events.append(event)
        return events

    # High Cost lookups.
    async def refresh(self, bot: Bot) -> None:
        """Perform an intensive full lookup for a fixture"""

        if self.url is None:
            args = self.__dict__
            raise ValueError("Can't refresh fixutre with no url\n%1", args)

        async with semaphore:
            page = await bot.browser.new_page()

            try:
                await page.goto(self.url, timeout=5000)
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

        if self.competition is None or self.competition.url is None:
            xpath = './/span[contains(@class, "__country")]//a/@href'
            href = "".join(tree.xpath(xpath))

            xpath = './/span[contains(@class, "__country")]/text()'
            country = "".join(tree.xpath(xpath)).strip()

            xpath = './/span[contains(@class, "__country")]/a/text()'
            name = "".join(tree.xpath(xpath)).strip()

            if href:
                comp_id = href.split("/")[-1]
                comp = bot.get_competition(comp_id)
            else:
                for c in bot.competitions:
                    if c.name.lower() == name.lower():
                        if c.country.lower() == country.lower():
                            comp = c
                            break
                else:
                    comp = None

            if not comp:
                comp = Competition(None, name, country, href)
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

        self.events = self.parse_events(tree)
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')


class NewsItem:
    """A generic item representing a News Article for a team."""

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
        e = self.team_embed if self.team_embed else Embed()
        e.title = self.title
        e.url = self.url
        e.set_image(url=self.image_url)
        e.description = self.blurb
        e.set_footer(text=self.source)
        e.timestamp = self.time
        return e
