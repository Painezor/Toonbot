"""A Utility tool for fetching and structuring data from Flashscore"""
from __future__ import annotations  # Cyclic Type Hinting

from datetime import datetime, timezone

import logging
import typing

from urllib.parse import quote

import discord
from lxml import html
from playwright.async_api import Page, TimeoutError as pw_TimeoutError

from ext.toonbot_utils.gamestate import GameState
from ext.utils import embed_utils, flags, timed_events
import ext.toonbot_utils.matchevents as m_evt

if typing.TYPE_CHECKING:
    from core import Bot

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
    ".rollbar, "
    ".selfPromo, "
    "#box-over-content, "
    "#box-over-content-detail, "
    "#box-over-content-a, "
    "#lsid-window-mask, "
    "#onetrust-consent-sdk"
)

FLASHSCORE = "https://www.flashscore.com"
LOGO_URL = FLASHSCORE + "/res/image/data/"
INJURY_EMOJI = "<:injury:682714608972464187>"
INBOUND_EMOJI = "<:inbound:1079808760194814014>"
OUTBOUND_EMOJI = "<:outbound:1079808772559609928>"
DEFAULT_LEAGUES = [
    "https://www.flashscore.com/football/europe/champions-league/",
    "https://www.flashscore.com/football/europe/euro/",
    "https://www.flashscore.com/football/europe/europa-league/",
    "https://www.flashscore.com/football/europe/uefa-nations-league/",
    "https://www.flashscore.com/football/england/premier-league/",
    "https://www.flashscore.com/football/england/championship/",
    "https://www.flashscore.com/football/england/league-one/",
    "https://www.flashscore.com/football/england/fa-cup/",
    "https://www.flashscore.com/football/england/efl-cup/",
    "https://www.flashscore.com/football/france/ligue-1/",
    "https://www.flashscore.com/football/france/coupe-de-france/",
    "https://www.flashscore.com/football/germany/bundesliga/",
    "https://www.flashscore.com/football/italy/serie-a/",
    "https://www.flashscore.com/football/netherlands/eredivisie/",
    "https://www.flashscore.com/football/spain/copa-del-rey/",
    "https://www.flashscore.com/football/spain/laliga/",
    "https://www.flashscore.com/football/usa/mls/",
]


def parse_events(fixture: Fixture, tree) -> list[m_evt.MatchEvent]:
    """Get a list of match events"""

    events = []
    for i in tree.xpath('.//div[contains(@class, "verticalSections")]/div'):
        # Detection of Teams
        team_detection = i.attrib["class"]
        if "Header" in team_detection:
            text = [x.strip() for x in i.xpath(".//text()")]
            if "Penalties" in text:
                try:
                    fixture.penalties_home = text[1]
                    fixture.penalties_away = text[3]
                    logger.info("Parsed a 2 part penalties OK!!")
                except IndexError:
                    # If Penalties are still in progress, it's actually
                    # in format ['Penalties', '1 - 2']
                    _, pen_string = text
                    home, away = pen_string.split(" - ")
                    fixture.penalties_home = home
                    fixture.penalties_away = away
            continue

        try:
            # event node -- if we can't find one, we can't parse one.
            node = i.xpath('./div[contains(@class, "incident")]')[0]
        except IndexError:
            continue

        svg_text = "".join(node.xpath(".//svg//text()")).strip()
        svg_class = "".join(node.xpath(".//svg/@class")).strip()
        sub_i = "".join(node.xpath(".//div[@class='smv__subIncident']/text()"))

        # Try to figure out what kind of event this is.
        if svg_class == "soccer":
            # This is a goal.

            if sub_i == "(Penalty)":
                event = m_evt.Penalty()

            elif sub_i:
                logger.info("Unhandled goal sub_incident %s", sub_i)
                event = m_evt.Goal()

            else:
                event = m_evt.Goal()

        elif "footballOwnGoal-ico" in svg_class:
            event = m_evt.OwnGoal()

        elif "Penalty missed" in sub_i:
            event = m_evt.Penalty(missed=True)

        # cards
        elif (
            "Yellow card / Red card" in svg_text
            or "redyellowcard-ico" in svg_class.casefold()
        ):
            event = m_evt.SecondYellow()

        elif "redCard-ico" in svg_class:
            event = m_evt.RedCard()

        elif "yellowCard-ico" in svg_class:
            event = m_evt.Booking()

        elif "card-ico" in svg_class:
            event = m_evt.Booking()
            logger.info("Fallback case reached, card-ico")

        # VAR
        elif "var" in svg_class:
            event = m_evt.VAR()
            if svg_class != "var":
                logger.info("var has svg_clas %s", svg_class)

        # Subs
        elif "substitution" in svg_class:
            event = m_evt.Substitution()

        else:
            logger.info("parsing match events on %s", fixture.url)
            logger.error("Match Event Not Handled correctly.")
            logger.info("text: %s, class: %s", svg_text, svg_class)
            if sub_i:
                logger.info("sub_incident: %s", sub_i)

            event = m_evt.MatchEvent()

        # Event Player.
        xpath = './/a[contains(@class, "playerName")]//text()'
        if p_name := "".join(node.xpath(xpath)).strip():
            xpath = './/a[contains(@class, "playerName")]//@href'
            p_url = "".join(node.xpath(xpath)).strip()
            if p_url:
                p_url = FLASHSCORE + p_url

            try:
                surname, forename = p_name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, p_name
            event.player = Player(forename, surname, p_url)

        # Subbed off player.
        if isinstance(event, m_evt.Substitution):
            xpath = './/div[contains(@class, "incidentSubOut")]/a/'
            if s_name := "".join(node.xpath(xpath + "text()")):
                s_name = s_name.strip()

                s_url = "".join(node.xpath(xpath + "@href"))
                if s_url:
                    s_url = FLASHSCORE + s_url

                try:
                    surname, forename = s_name.rsplit(" ", 1)
                except ValueError:
                    forename, surname = None, s_name
                player = Player(forename, surname, s_url)
                event.player_off = player

        # Assist of a goal.
        elif isinstance(event, m_evt.Goal):
            xpath = './/div[contains(@class, "assist")]//text()'
            if a_name := "".join(node.xpath(xpath)):
                a_name = a_name.strip("()")

                xpath = './/div[contains(@class, "assist")]//@href'

                a_url = "".join(node.xpath(xpath))
                if a_url:
                    a_url = FLASHSCORE + a_url

                try:
                    surname, forename = a_name.rsplit(" ", 1)
                except ValueError:
                    forename, surname = None, a_name

                player = Player(forename, surname, a_url)
                event.assist = player

        if "home" in team_detection:
            event.team = fixture.home
        elif "away" in team_detection:
            event.team = fixture.away

        xpath = './/div[contains(@class, "timeBox")]//text()'
        time = "".join(node.xpath(xpath)).strip()
        event.time = time
        event.note = svg_text

        # Description of the event.
        xpath = './/div[contains(@class, "incidentIcon")]//@title'
        title = "".join(node.xpath(xpath)).strip()
        description = title.replace("<br />", " ")
        event.description = description

        events.append(event)
    return events


async def parse_games(
    bot: Bot, object_: FlashScoreItem, sub_page: str
) -> list[Fixture]:
    """Parse games from raw HTML from fixtures or results function"""
    page: Page = await bot.browser.new_page()

    if object_.url is None:
        raise ValueError("No URL found in %s", object_)
    try:
        await page.goto(object_.url + sub_page, timeout=5000)
        loc = page.locator("#live-table")
        await loc.wait_for()
        tree = html.fromstring(await page.content())
    except pw_TimeoutError:
        logger.error("Timed out parsing games on %s", object_.url + sub_page)
        return []
    finally:
        await page.close()

    fixtures: list[Fixture] = []

    if isinstance(object_, Competition):
        comp = object_
    else:
        comp = Competition(None, "Unknown", "Unknown", None)

    xpath = './/div[contains(@class, "sportName soccer")]/div'
    if not (games := tree.xpath(xpath)):
        return []

    for i in games:
        try:
            fx_id = i.xpath("./@id")[0].split("_")[-1]
            url = f"{FLASHSCORE}/match/{fx_id}"
        except IndexError:
            # This (might be) a header row.
            if "event__header" in i.classes:
                xpath = './/div[contains(@class, "event__title")]//text()'
                country, league = i.xpath(xpath)
                league = league.split(" - ")[0]

                ctr = country.casefold()
                league = league.casefold().split(" -")[0]

                comp = bot.get_competition(f"{ctr.upper()}: {league}")
                if comp is None:
                    comp = Competition(None, league, country, None)
            continue

        xpath = './/div[contains(@class,"event__participant")]/text()'
        home, away = i.xpath(xpath)

        # TODO: Fetch team ID & URL
        home = Team(None, home.strip(), None)
        away = Team(None, away.strip(), None)

        fixture = Fixture(home, away, fx_id, url)
        fixture.competition = comp

        fixture.win = "".join(i.xpath(".//div[@class='formIcon']/@title"))

        # score
        try:
            xpath = './/div[contains(@class,"event__score")]//text()'
            score_home, score_away = i.xpath(xpath)

            fixture.home_score = int(score_home.strip())
            fixture.away_score = int(score_away.strip())
        except ValueError:
            pass
        state = None

        # State Corrections
        time = "".join(i.xpath('.//div[@class="event__time"]//text()'))
        override = "".join([i for i in time if i.isalpha()])
        time = time.replace(override, "")

        if override:
            try:
                state = {
                    "Abn": GameState.ABANDONED,
                    "AET": GameState.AFTER_EXTRA_TIME,
                    "Awrd": GameState.AWARDED,
                    "FRO": GameState.FINAL_RESULT_ONLY,
                    "Pen": GameState.AFTER_PENS,
                    "Postp": GameState.POSTPONED,
                    "WO": GameState.WALKOVER,
                }[override]
            except KeyError:
                logger.error("missing state for override %s", override)

        dtn = datetime.now(tz=timezone.utc)
        for string, fmt in [
            (time, "%d.%m.%Y."),
            (time, "%d.%m.%Y"),
            (f"{dtn.year}.{time}", "%Y.%d.%m. %H:%M"),
            (f"{dtn.year}.{dtn.day}.{dtn.month}.{time}", "%Y.%d.%m.%H:%M"),
        ]:
            try:
                k_o = datetime.strptime(string, fmt)
                fixture.kickoff = k_o.astimezone(timezone.utc)

                if fixture.kickoff > datetime.now(tz=timezone.utc):
                    state = GameState.SCHEDULED
                else:
                    state = GameState.FULL_TIME
                break
            except ValueError:
                continue
        else:
            logger.error("Failed to convert %s to datetime.", time)

        # Bypass time setter by directly changing _private val.
        if isinstance(state, GameState):
            fixture.time = state
        else:
            if "'" in time or "+" in time or time.isdigit():
                fixture.time = time
            else:
                logger.error('state "%s" (%s) not handled.', state, time)
        fixtures.append(fixture)
    return fixtures


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""

    def __init__(
        self,
        fsid: typing.Optional[str],
        name: str,
        url: typing.Optional[str],
    ) -> None:
        self.id: typing.Optional[str] = fsid
        self.name: str = name
        self.url: typing.Optional[str] = url
        self.embed_colour: typing.Optional[discord.Colour | int] = None
        self.logo_url: typing.Optional[str] = None

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
            return f"[{self.title or 'Unknown Item'}]({self.url})"
        return self.name or "Unknown Item"

    @property
    def title(self) -> str:
        """Alias to name, or Unknown Item if not found"""
        return self.name or "Unknown Item"

    async def base_embed(self) -> discord.Embed:
        """A discord Embed representing the flashscore search result"""
        embed = discord.Embed()
        embed.description = ""
        if self.logo_url is not None:
            if "flashscore" in self.logo_url:
                logo = self.logo_url
            else:
                logo = LOGO_URL + self.logo_url.replace("'", "")  # Extraneous

            if logo:
                if (clr := self.embed_colour) is None:
                    clr = await embed_utils.get_colour(logo)
                    self.embed_colour = clr
                embed.colour = clr
            embed.set_author(name=self.title, icon_url=logo, url=self.url)
        else:
            embed.set_author(name=self.title, url=self.url)
        return embed


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""

    __slots__ = {
        "competition": "The competition the team belongs to",
        "logo_url": "A link to a logo representing the competition",
        "gender": "The Gender that this team is comprised of",
    }

    # Constant
    emoji: typing.ClassVar[str] = "👕"

    def __init__(
        self, fs_id: typing.Optional[str], name: str, url: typing.Optional[str]
    ) -> None:

        # Example URL:
        # https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        # https://www.flashscore.com/?r=3:jLsL0hAF

        if fs_id is None and url:
            fs_id = url.split("/")[-1]
        elif url and fs_id and FLASHSCORE not in url:
            url = f"{FLASHSCORE}/team/{url}/{fs_id}"
        elif fs_id and not url:
            url = f"https://www.flashscore.com/?r=3:{id}"

        super().__init__(fs_id, name, url)

        self.gender: typing.Optional[str] = None
        self.competition: typing.Optional[Competition] = None

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    @classmethod
    async def from_fixture_html(
        cls, bot: Bot, tree, home: bool = True
    ) -> Team:
        """Parse a team from the HTML of a flashscore FIxture"""
        attr = "home" if home else "away"

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

        if (team := bot.get_team(team_id)) is not None:
            if team.name != name:
                team.name = name
        else:
            for i in bot.teams:
                if i.url and url in i.url:
                    team = i
                    break
            else:
                team = Team(team_id, name, FLASHSCORE + url)

        if team.logo_url is None:
            logo = div.xpath('.//img[@class="participant__image"]/@src')
            logo = "".join(logo)
            if logo:
                team.logo_url = FLASHSCORE + logo

        if team not in bot.teams:
            await save_team(bot, team)

        return team

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        if len(self.name.split()) == 1:
            return "".join(self.name[:3]).upper()
        else:
            return "".join([i for i in self.name if i.isupper()])


class Player:
    """An object representing a player from flashscore."""

    def __init__(
        self,
        forename: typing.Optional[str],
        surname: str,
        url: typing.Optional[str],
    ) -> None:

        # Main. Forename will not always be present.
        self.forename: typing.Optional[str] = forename
        self.surname: str = surname
        self.url: typing.Optional[str] = url

        # Attrs
        self.squad_number: typing.Optional[int] = None
        self.position: typing.Optional[str] = None
        self.country: list[str] = []
        self.age: typing.Optional[int] = None

        # Misc Objects.
        self.team: typing.Optional[Team] = None
        self.competition: typing.Optional[Competition] = None

        # Dynamic Attrs
        self.appearances: typing.Optional[int] = None
        self.goals: typing.Optional[int] = None
        self.assists: typing.Optional[int] = None
        self.yellows: typing.Optional[int] = None
        self.reds: typing.Optional[int] = None
        self.injury: typing.Optional[str] = None

        # From top scorers pages.
        self.rank: typing.Optional[int] = None

    @property
    def name(self) -> str:
        """FirstName Surname or just Surname if no Forename is found"""
        if self.forename is None:
            return self.surname
        else:
            return f"{self.forename} {self.surname}"

    @property
    def markdown(self) -> str:
        """Return [name](url)"""
        if self.url is None:
            return self.name
        else:
            return f"[{self.name}]({self.url})"

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return flags.get_flag(self.country) or ""


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji: typing.ClassVar[str] = "🏆"

    def __init__(
        self,
        fsid: typing.Optional[str],
        name: str,
        country: typing.Optional[str],
        url: typing.Optional[str],
    ) -> None:

        # Sanitise inputs.
        if country is not None and ":" in country:
            country = country.split(":")[0]

        if url is not None:
            url = url.rstrip("/")

        if name and country and not url:
            nom = name.casefold().replace(" ", "-").replace(".", "")
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = FLASHSCORE + f"/football/{ctr}/{nom}"
        elif url and country and FLASHSCORE not in url:
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = f"{FLASHSCORE}/football/{ctr}/{url}"
        elif fsid and not url:
            # https://www.flashscore.com/?r=1:jLsL0hAF ??
            url = f"https://www.flashscore.com/?r=2:{url}"

        super().__init__(fsid, name, url)

        self.logo_url: typing.Optional[str] = None
        self.country: typing.Optional[str] = country
        self.score_embeds: list[discord.Embed] = []

        # Table Imagee
        self.table: typing.Optional[str] = None

    def __str__(self) -> str:
        return self.title

    def __hash__(self):
        return hash((self.title, self.id, self.url))

    def __eq__(self, other: typing.Any) -> bool:
        if other is None:
            return False

        if self.title == other.title:
            return True
        if self.id is not None and self.id == other.id:
            return True
        return self.url == other.url

    @classmethod
    async def by_link(cls, bot: Bot, link: str) -> Competition:
        """Create a Competition Object from a flashscore url"""
        page = await bot.browser.new_page()
        try:
            await page.goto(link, timeout=5000)
            await page.locator(".heading").wait_for()
            tree = html.fromstring(await page.content())
        finally:
            await page.close()

        try:
            xpath = './/h2[@class="breadcrumb"]//a/text()'
            country = "".join(tree.xpath(xpath)).strip()

            xpath = './/div[@class="heading__name"]//text()'
            name = tree.xpath(xpath)[0].strip()
        except IndexError:
            name = "Unidentified League"
            country = "Unidentified Country"

        # TODO: Extract the ID from the URL
        comp = cls(None, name, country, link)

        logo = tree.xpath('.//div[contains(@class,"__logo")]/@style')

        try:
            comp.logo_url = LOGO_URL + logo[0].split("(")[1].strip(")")
        except IndexError:
            if ".png" in logo:
                comp.logo_url = logo

        return comp

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        if not self.country:
            return ""
        return flags.get_flag(self.country)

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        else:
            return self.name


class Fixture:
    """An object representing a Fixture from the Flashscore Website"""

    emoji: typing.ClassVar[str] = "⚽"

    def __init__(
        self,
        home: Team,
        away: Team,
        fs_id: typing.Optional[str],
        url: typing.Optional[str],
    ) -> None:

        if fs_id and not url:
            url = f"https://www.flashscore.com/?r=5:{fs_id}"

        if url and FLASHSCORE not in url:
            logger.info("Invalid url %s", url)

        self.url: typing.Optional[str] = url
        self.id: typing.Optional[str] = fs_id

        self.away: Team = away
        self.away_cards: typing.Optional[int] = None
        self.away_score: typing.Optional[int] = None
        self.penalties_away: typing.Optional[int] = None

        self.home: Team = home
        self.home_cards: typing.Optional[int] = None
        self.home_score: typing.Optional[int] = None
        self.penalties_home: typing.Optional[int] = None

        self.time: typing.Optional[str | GameState] = None
        self.kickoff: typing.Optional[datetime] = None
        self.ordinal: typing.Optional[int] = None

        self.attendance: typing.Optional[int] = None
        self.breaks: int = 0
        self.competition: typing.Optional[Competition] = None
        self.events: list[m_evt.MatchEvent] = []
        self.infobox: typing.Optional[str] = None
        self.images: typing.Optional[list[str]] = None

        self.periods: typing.Optional[int] = None
        self.referee: typing.Optional[str] = None
        self.stadium: typing.Optional[str] = None

        # Hacky but works for results
        self.win: typing.Optional[str] = None

    def __str__(self) -> str:
        match self.time:
            case (
                GameState.LIVE | GameState.STOPPAGE_TIME | GameState.EXTRA_TIME
            ):
                time = self.state.name if self.state else None
            case GameState():
                time = self.ko_relative
            case _:
                time = self.time

        return f"{time}: {self.bold_markdown}"

    @property
    def state(self) -> GameState | None:
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
        time = timed_events.Timestamp(self.kickoff).relative
        return f"{time}: {self.bold_markdown}"

    @property
    def finished(self) -> str:
        """Kickoff: Markdown"""
        if self.win:
            logger.info("Found Win on fixture %s", self.win)
        return f"{self.ko_relative}: {self.bold_markdown}"

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if self.kickoff is None:
            return ""

        time = timed_events.Timestamp(self.kickoff)
        if self.kickoff.date == (now := datetime.now(tz=timezone.utc)).date:
            # If the match is today, return HH:MM
            return time.time_hour
        elif self.kickoff.year != now.year:
            # if a different year, return DD/MM/YYYY
            return time.date
        elif self.kickoff > now:  # For Upcoming
            return time.date_long
        else:
            return time.relative

    @property
    def score(self) -> str:
        """Return "X - Y", or 'vs' if scores are None"""
        if self.home_score is None:
            return "vs"
        else:
            return f"{self.home_score} - {self.away_score}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.name} {self.score} {self.away.name}"

    @property
    def bold_score(self) -> str:
        """Embolden the winning team of a fixture"""
        if self.home_score is None or self.away_score is None:
            return f"{self.home.name} vs {self.away.name}"

        home = f"{self.home.name} {self.home_score}"
        away = f"{self.away_score} {self.away.name}"

        if self.home_score > self.away_score:
            home = f"**{home}**"
        elif self.away_score > self.home_score:
            away = f"**{away}**"

        return f"{home} - {away}"

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold **winning** team, with
        [score](as markdown link)."""
        if self.home_score is None or self.away_score is None:
            return f"[{self.home.name} vs {self.away.name}]({self.url})"

        home = self.home.name
        away = self.away.name
        # Embolden Winner
        if self.home_score > self.away_score:
            home = f"**{home}**"
        if self.away_score > self.home_score:
            away = f"**{away}**"

        def parse_cards(cards: typing.Optional[int]) -> str:
            """Get a number of icons matching number of cards"""
            match cards:
                case 0 | None:
                    return ""
                case 1:
                    return "`🟥` "
                case _:
                    return f"`🟥 x{cards}` "

        h_s, a_s = self.home_score, self.away_score
        h_c = parse_cards(self.home_cards)
        a_c = parse_cards(self.away_cards)
        return f"{home} {h_c}[{h_s} - {a_s}]({self.url}){a_c} {away}"

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output = []
        if self.state is not None:
            output.append(f"`{self.state.emote}")

            if isinstance(self.time, str):
                output.append(self.time)
            else:
                if self.state != GameState.SCHEDULED:
                    output.append(self.state.shorthand)
            output.append("` ")

        hm_n = self.home.name
        aw_n = self.away.name

        if self.home_score is None or self.away_score is None:
            time = timed_events.Timestamp(self.kickoff).time_hour
            output.append(f" {time} [{hm_n} v {aw_n}]({self.url})")
        else:
            # Penalty Shootout
            if self.penalties_home is not None:
                pens = f" (p: {self.penalties_home} - {self.penalties_away}) "
                sco = min(self.home_score, self.away_score)
                score = f"[{sco} - {sco}]({self.url})"
                output.append(f"{hm_n} {score}{pens}{aw_n}")
            else:
                output.append(self.bold_markdown)
        return "".join(output)

    @property
    def ac_row(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        if self.competition:
            cmp = self.competition.title
            out = f"⚽ {self.home.name} {self.score} {self.away.name} ({cmp})"
        else:
            out = f"⚽ {self.home.name} {self.score} {self.away.name}"
        return out

    async def base_embed(self) -> discord.Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        if self.competition:
            embed = await self.competition.base_embed()
        else:
            embed = discord.Embed()

        embed.url = self.url
        if self.state:
            embed.colour = self.state.colour
        embed.set_author(name=self.score_line)
        embed.timestamp = self.kickoff
        embed.description = ""

        if self.infobox is not None:
            embed.add_field(name="Match Info", value=self.infobox)

        if self.time is None:
            return embed

        match self.time:
            case GameState.SCHEDULED:
                time = timed_events.Timestamp(self.kickoff).time_relative
                embed.description = f"Kickoff: {time}"
            case GameState.POSTPONED:
                embed.description = "This match has been postponed."

        if self.competition:
            embed.set_footer(text=f"{self.time} - {self.competition.title}")
        else:
            embed.set_footer(text=self.time)
        return embed

    # High Cost lookups.
    async def refresh(self, bot: Bot) -> None:
        """Perform an intensive full lookup for a fixture"""

        if self.url is None:
            raise AttributeError(f"Can't refres - no url\n {self.__dict__}")

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
            k_o = "".join(tree.xpath(xpath))
            k_o = datetime.strptime(k_o, "%d.%m.%Y %H:%M").astimezone()
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

            if href:
                comp_id = href.rsplit("/", maxsplit=1)[0]
                comp = bot.get_competition(comp_id)
            else:
                ctr = country.casefold()
                nom = name.casefold()

                for i in bot.competitions:
                    if not i.country or i.country.casefold() != ctr:
                        continue

                    if i.name.casefold() != nom:
                        continue

                    comp = i
                    break
                else:
                    comp = None

            if comp is None:
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
                info = self.infobox.rsplit(": ", maxsplit=1)[-1]
                self.periods = int(info.split("x", maxsplit=1)[0])

        self.events = parse_events(self, tree)
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')


# slovak - 7
# Hebrew - 17
# Slovenian - 24
# Estonian - 26
# Indonesian - 35
# Catalan - 43
# Georgian - 44

locales = {
    discord.Locale.american_english: 1,  # 'en-US'
    discord.Locale.british_english: 1,  # 'en-GB' flashscore.co.uk
    discord.Locale.bulgarian: 40,  # 'bg'
    discord.Locale.chinese: 19,  # 'zh-CN'
    discord.Locale.taiwan_chinese: 19,  # 'zh-TW'
    discord.Locale.french: 16,  # 'fr'    flashscore.fr
    discord.Locale.croatian: 14,  # 'hr'  # Could also be 25?
    discord.Locale.czech: 2,  # 'cs'
    discord.Locale.danish: 8,  # 'da'
    discord.Locale.dutch: 21,  # 'nl'
    discord.Locale.finnish: 18,  # 'fi'
    discord.Locale.german: 4,  # 'de'
    discord.Locale.greek: 11,  # 'el'
    discord.Locale.hindi: 1,  # 'hi'
    discord.Locale.hungarian: 15,  # 'hu'
    discord.Locale.italian: 6,  # 'it'
    discord.Locale.japanese: 42,  # 'ja'
    discord.Locale.korean: 38,  # 'ko'
    discord.Locale.lithuanian: 27,  # 'lt'
    discord.Locale.norwegian: 23,  # 'no'
    discord.Locale.polish: 3,  # 'pl'
    discord.Locale.brazil_portuguese: 20,  # 'pt-BR'   # Could also be 31
    discord.Locale.romanian: 9,  # 'ro'
    discord.Locale.russian: 12,  # 'ru'
    discord.Locale.spain_spanish: 13,  # 'es-ES'
    discord.Locale.swedish: 28,  # 'sv-SE'
    discord.Locale.thai: 1,  # 'th'
    discord.Locale.turkish: 10,  # 'tr'
    discord.Locale.ukrainian: 41,  # 'uk'
    discord.Locale.vietnamese: 37,  # 'vi'
}


async def search(
    query: str,
    mode: typing.Literal["comp", "team"],
    interaction: typing.Optional[discord.Interaction[Bot]] = None,
    bot: typing.Optional[Bot] = None,
) -> list[Competition | Team]:
    """Fetch a list of items from flashscore matching the user's query"""
    replace = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))
    query = quote(replace)

    if interaction is not None:
        bot = interaction.client

        try:
            lang_id = locales[interaction.locale]
        except KeyError:
            try:
                if interaction.guild_locale is None:
                    lang_id = 1
                else:
                    lang_id = locales[interaction.guild_locale]
            except KeyError:
                lang_id = 1
    else:
        lang_id = 1

    # Type IDs: 1 - Team | Tournament, 2 - Team, 3 - Player 4 - PlayerInTeam
    url = (
        f"https://s.livesport.services/api/v2/search/?q={query}"
        f"&lang-id={lang_id}&type-ids=1,2,3,4&sport-ids=1"
    )

    if bot is None:
        raise AttributeError("Pass either bot or Interaction")

    async with bot.session.get(url) as resp:
        if resp.status != 200:
            err = f"{resp.status} error searching flashscore {query}"
            raise LookupError(err)
        res = typing.cast(dict, await resp.json())

    results: list[Competition | Team] = []

    for i in res:
        if i["participantTypes"] is None:
            if i["type"]["name"] == "TournamentTemplate":
                id_ = i["id"]
                name = i["name"]
                ctry = i["defaultCountry"]["name"]
                url = i["url"]

                comp = bot.get_competition(id_)

                if comp is None:
                    comp = Competition(id_, name, ctry, url)
                    await save_comp(bot, comp)

                if i["images"]:
                    logo_url = i["images"][0]["path"]
                    comp.logo_url = logo_url

                results.append(comp)
            else:
                types = i["participantTypes"]
                logging.info("unhandled particpant types %s", types)
        else:
            for type_ in i["participantTypes"]:
                match type_["name"]:
                    case "National" | "Team":
                        if mode == "comp":
                            continue

                        if not (team := bot.get_team(i["id"])):

                            team = Team(i["id"], i["name"], i["url"])
                            try:
                                team.logo_url = i["images"][0]["path"]
                            except IndexError:
                                pass
                            team.gender = i["gender"]["name"]
                            await save_team(bot, team)
                        results.append(team)
                    case "TournamentTemplate":
                        if mode == "team":
                            continue

                        if not (comp := bot.get_competition(i["id"])):
                            ctry = i["defaultCountry"]["name"]
                            nom = i["name"]
                            comp = Competition(i["id"], nom, ctry, i["url"])
                            try:
                                comp.logo_url = i["images"][0]["path"]
                            except IndexError:
                                pass
                            await save_comp(bot, comp)
                            results.append(comp)
                    case _:
                        continue  # This is a player, we don't want those.

    return results


# DB Management
async def save_team(bot: Bot, team: Team) -> None:
    """Save the Team to the Bot Database"""
    sql = """INSERT INTO fs_teams (id, name, logo_url, url)
             VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE SET
             (name, logo_url, url)
             = (EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
             """
    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(
                sql, team.id, team.name, team.logo_url, team.url
            )
    bot.teams.append(team)


async def save_comp(bot: Bot, comp: Competition) -> None:
    """Save the competition to the bot database"""
    sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
             VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
             (country, name, logo_url, url) =
             (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
             """

    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(
                sql, comp.id, comp.country, comp.name, comp.logo_url, comp.url
            )
    bot.competitions.add(comp)
    logger.info("saved competition. %s %s %s", comp.name, comp.id, comp.url)
