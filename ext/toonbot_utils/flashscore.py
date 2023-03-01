"""A Utility tool for fetching and structuring data from Flashscore"""
from __future__ import annotations  # Cyclic Type Hinting

import logging
from asyncio import Semaphore
from datetime import datetime, timezone
from typing import Optional

from discord import Embed, Colour
from lxml import html
from playwright.async_api import Page

from ext.toonbot_utils.gamestate import GameState
from ext.utils.embed_utils import get_colour
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp

import ext.toonbot_utils.matchevents as m_evt

import typing

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
INBOUND_EMOJI = "<:inbound:1079808760194814014>"
OUTBOUND_EMOJI = "<:outbound:1079808772559609928>"
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


def parse_events(fixture: Fixture, tree) -> list[m_evt.MatchEvent]:
    """Get a list of match events"""

    events = []

    for i in tree.xpath('.//div[contains(@class, "verticalSections")]/div'):
        # Detection of Teams
        team_detection = i.attrib["class"]
        if "Header" in team_detection:
            pens = [x.strip() for x in i.xpath(".//text()")]
            if "Penalties" in pens:
                try:
                    fixture.penalties_home = pens[1]
                    fixture.penalties_away = pens[3]
                except IndexError:
                    logger.error("ValueError splitting pens %s", pens)
                    _, pen_string = pens
                    h, a = pen_string.split(" - ")
                    fixture.penalties_home = h
                    fixture.penalties_away = a
            continue
        elif "home" in team_detection:
            team = fixture.home
        elif "away" in team_detection:
            team = fixture.away
        elif "empty" in team_detection:
            continue  # No events in half signifier.
        else:
            logging.error(f"No team found for team_detection {team_detection}")
            continue

        node = i.xpath('./div[contains(@class, "incident")]')[0]  # event_node
        xpath = './/div[contains(@class, "incidentIcon")]//@title'
        title = "".join(node.xpath(xpath)).strip()
        description = title.replace("<br />", " ")

        xpath = './/div[contains(@class, "incidentIcon")]//svg//text()'
        icon_desc = "".join(node.xpath(xpath)).strip()

        xpath = './/div[contains(@class, "incidentIcon")]//svg/@class'

        icon = "".join(node.xpath(xpath)).strip()
        # TODO: Un-nest the match.

        if "footballOwnGoal-ico" in icon:
            event = m_evt.OwnGoal()

        elif icon_desc == "Penalty":
            event = m_evt.Penalty()

        elif "warning" in icon:
            if "Penalty missed" in icon_desc:
                event = m_evt.Penalty(missed=True)
            else:
                logger.info("icon: %s, icon_desc: %s", icon, icon_desc)
                event = m_evt.MatchEvent()  # Use the Generic

        # cards
        elif "Yellow card / Red card" in icon_desc:
            event = m_evt.SecondYellow()

        elif "yellowCard-ico" in icon:
            event = m_evt.Booking()
            event.note = icon_desc

        elif "substitution" in icon:
            event = m_evt.Substitution()

            trg = "incidentSubOut"
            xpath = f'.//div[contains(@class, "{trg}")]/a/'
            s_name = "".join(node.xpath(xpath + "text()"))
            s_name = s_name.strip()
            s_link = "".join(node.xpath(xpath + "@href"))

            s_link = FLASHSCORE + s_link

            try:
                surname, forename = s_name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, s_name
            p = Player(forename, surname, s_link)
            event.player_off = p

        else:
            logger.info("icon: %s, icon_desc: %s", icon, icon_desc)
            match icon.casefold():
                # Goal types
                case "footballgoal-ico" | "soccer":
                    match icon_desc.casefold():
                        case "goal" | "":
                            event = m_evt.Goal()
                        case _:
                            logging.error(
                                f"[GOAL] icon: <{icon}> unhandled"
                                f"icon_desc: <{icon_desc}> on {fixture.url}"
                            )
                            continue
                case "penaltymissed-ico":
                    event = m_evt.Penalty(missed=True)
                # Card Types
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
                    match icon_desc.strip().casefold():
                        case "goal":
                            event = m_evt.Goal()
                            if icon_desc and icon_desc.casefold() != "goal":
                                logging.error(
                                    f"[GOAL] unh icon_desc: {icon_desc}"
                                )
                                continue
                        # Red card
                        case "red card":
                            event = m_evt.RedCard()
                        case "warning":
                            event = m_evt.Booking()
                        case _:
                            logging.error(
                                f"Match Event (icon: {icon})\n"
                                f"icon_desc: {icon_desc}\n{fixture.url}"
                            )
                            continue

        event.team = team

        # Data not always present.
        xpath = './/a[contains(@class, "playerName")]//text()'
        if p_name := "".join(node.xpath(xpath)).strip():
            xpath = './/a[contains(@class, "playerName")]//@href'
            p_url = "".join(node.xpath(xpath)).strip()

            try:
                surname, forename = p_name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, p_name
            event.player = Player(forename, surname, p_url)

        if isinstance(event, m_evt.Goal):
            xpath = './/div[contains(@class, "assist")]//text()'
            if assist := "".join(node.xpath(xpath)):
                xpath = './/div[contains(@class, "assist")]//@href'
                a_url = "".join(node.xpath(xpath))

                assist = assist.strip("()")

                try:
                    surname, forename = assist.split(" ", 1)
                except ValueError:
                    forename, surname = None, assist

                p = Player(forename, surname, a_url)
                event.assist = p

        if description:
            event.description = description

        xpath = './/div[contains(@class, "timeBox")]//text()'
        event.time = "".join(node.xpath(xpath)).strip()
        events.append(event)
    return events


async def parse_games(
    bot: Bot, object: FlashScoreItem, sub_page: str
) -> list[Fixture]:
    """Parse games from raw HTML from fixtures or results function"""
    page: Page = await bot.browser.new_page()
    try:
        if not object.url:
            raise ValueError(f"No URL found on FSItem {object}")
        await page.goto(object.url + sub_page, timeout=5000)
        loc = page.locator(".sportName.soccer")
        await loc.wait_for()
        tree = html.fromstring(await page.content())
    finally:
        await page.close()

    fixtures: list[Fixture] = []

    if isinstance(object, Competition):
        comp = object
    else:
        comp = Competition(None, "Unknown", "Unknown", None)

    xp = './/div[contains(@class, "sportName soccer")]/div'
    if not (games := tree.xpath(xp)):
        raise LookupError(f"No fixtures found on {object.url + sub_page}")

    for i in games:
        try:
            fx_id = i.xpath("./@id")[0].split("_")[-1]
            url = f"{FLASHSCORE}/match/{fx_id}"
        except IndexError:
            # This (might be) a header row.
            if "event__header" in i.classes:
                xp = './/div[contains(@class, "event__title")]//text()'
                country, league = i.xpath(xp)
                league = league.split(" - ")[0]

                ctr = country.casefold()
                lg = league.casefold().split(" -")[0]

                for x in bot.competitions:
                    if not x.country or x.country.casefold() != ctr:
                        continue

                    if x.name.casefold() != lg:
                        continue

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

        fixture.win = "".join(i.xpath(".//div[@class='formIcon']/@title"))

        # score
        try:
            xp = './/div[contains(@class,"event__score")]//text()'
            score_home, score_away = i.xpath(xp)

            fixture.home_score = int(score_home.strip())
            fixture.away_score = int(score_away.strip())
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
                fixture.kickoff = ko.astimezone(timezone.utc)

                if fixture.kickoff > datetime.now(tz=timezone.utc):
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


class FlashScoreItem:
    """A generic object representing the result of a Flashscore search"""

    bot: typing.ClassVar[Bot]

    def __init__(
        self, fsid: Optional[str], name: str, url: Optional[str]
    ) -> None:
        self.id: Optional[str] = fsid
        self.name: str = name
        self.url: Optional[str] = url
        self.embed_colour: Optional[Colour | int] = None
        self.logo_url: Optional[str] = None

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

        e: Embed = Embed()
        e.set_author(name=self.title, icon_url=self.logo_url)
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
        self, fs_id: Optional[str], name: str, url: Optional[str]
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

        self.gender: Optional[str] = None
        self.competition: Optional[Competition] = None

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        match len(self.name.rsplit(" ")):
            case 1:
                return "".join(self.name[:3]).upper()
            case _:
                return "".join([i for i in self.name if i.isupper()])


class Player:
    """An object representing a player from flashscore."""

    def __init__(
        self, forename: Optional[str], surname: str, url: Optional[str]
    ) -> None:

        # Main. Forename will not always be present.
        self.forename: Optional[str] = forename
        self.surname: str = surname
        self.url: Optional[str] = url

        # Attrs
        self.squad_number: Optional[int] = None
        self.position: Optional[str] = None
        self.country: list[str] = []
        self.age: Optional[int] = None

        # Misc Objects.
        self.team: Optional[Team] = None
        self.competition: Optional[Competition] = None

        # Dynamic Attrs
        self.appearances: Optional[int] = None
        self.goals: Optional[int] = None
        self.assists: Optional[int] = None
        self.yellows: Optional[int] = None
        self.reds: Optional[int] = None
        self.injury: Optional[str] = None

    @property
    def name(self) -> str:
        if self.forename is None:
            return self.surname
        else:
            return f"{self.forename} {self.surname}"

    @property
    def markdown(self) -> str:
        if self.url is None:
            return self.name
        else:
            return f"[{self.name}]({self.url})"

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return get_flag(self.country) or ""


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji: typing.ClassVar[str] = "🏆"

    def __init__(
        self,
        fsid: Optional[str],
        name: str,
        country: Optional[str],
        url: Optional[str],
    ) -> None:

        if name and country:
            nom = name.casefold().replace(" ", "-").replace(".", "")
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = FLASHSCORE + f"/football/{ctr}/{nom}"
        elif url and country and FLASHSCORE not in url:
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = f"{FLASHSCORE}/{ctr}/{url}/"
            logger.error("Test replacement %s", url)
        elif fsid:
            # https://www.flashscore.com/?r=1:jLsL0hAF ??
            url = f"https://www.flashscore.com/?r=2:{url}"

        super().__init__(fsid, name, url)

        self.logo_url: Optional[str] = None
        self.country: Optional[str] = country
        self.score_embeds: list[Embed] = []

        # Table Imagee
        self.table: Optional[str] = None

    def __str__(self) -> str:
        return self.title

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
        if not self.country:
            return ""
        return get_flag(self.country)

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country:
            return f"{self.country.upper()}: {self.name}"
        else:
            return self.name


class Fixture:
    """An object representing a Fixture from the Flashscore Website"""

    emoji: typing.ClassVar[str] = "⚽"

    def __init__(
        self, home: Team, away: Team, fs_id: Optional[str], url: Optional[str]
    ) -> None:

        if fs_id and not url:
            url = f"https://www.flashscore.com/?r=5:{fs_id}"

        if url and FLASHSCORE not in url:
            logger.info("Invalid url %s", url)

        self.url: Optional[str] = url
        self.id: Optional[str] = fs_id

        self.away: Team = away
        self.away_cards: Optional[int] = None
        self.away_score: Optional[int] = None
        self.penalties_away: Optional[int] = None

        self.home: Team = home
        self.home_cards: Optional[int] = None
        self.home_score: Optional[int] = None
        self.penalties_home: Optional[int] = None

        self.time: Optional[str | GameState] = None
        self.kickoff: Optional[datetime] = None
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

        # Hacky but works for results
        self.win: Optional[str] = None

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

    def active(self, ordinal: int) -> bool:
        """Is this game still valid"""
        if self.ordinal is None:
            if self.kickoff is None:
                self.ordinal = ordinal
            else:
                self.ordinal = self.kickoff.toordinal()
        return bool(ordinal <= self.ordinal)

    @property
    def state(self) -> GameState | None:
        """Get a GameState value from stored _time"""
        if isinstance(self.time, str):
            if "+" in self.time:
                return GameState.STOPPAGE_TIME
            else:
                if int(self.time.strip("'")) < 90:
                    return GameState.LIVE
                else:
                    return GameState.EXTRA_TIME
        else:
            return self.time

    @property
    def upcoming(self) -> str:
        """Format for upcoming games in /fixtures command"""
        return f"{Timestamp(self.kickoff).relative}: {self.bold_markdown}"

    @property
    def finished(self) -> str:
        if self.win:
            logger.info(f"Found Win on fixture {self.win}")
        return f"{self.ko_relative}: {self.bold_markdown}"

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if self.kickoff is None:
            return ""

        ts = Timestamp(self.kickoff)
        if self.kickoff.date == (now := datetime.now(tz=timezone.utc)).date:
            # If the match is today, return HH:MM
            return ts.time_hour
        elif self.kickoff.year != now.year:
            # if a different year, return DD/MM/YYYY
            return ts.date
        elif self.kickoff > now:  # For Upcoming
            return ts.date_long
        else:
            return ts.relative

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

        def parse_cards(cards: Optional[int]) -> str:
            """Get a number of icons matching number of cards"""
            match cards:
                case 0 | None:
                    return ""
                case 1:
                    return "`🟥` "
                case _:
                    return f"`🟥 x{cards}` "

        sh, sa = self.home_score, self.away_score
        hc = parse_cards(self.home_cards)
        ac = parse_cards(self.away_cards)
        return f"{home} {hc}[{sh} - {sa}]({self.url}){ac} {away}"

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output = []
        if self.state is not None:
            output.append(f"`{self.state.emote}")

        if isinstance(self.time, str):
            output.append(f"{self.time}`")
        else:
            if self.state:
                if self.state != GameState.SCHEDULED:
                    output.append(f"{self.state.shorthand}`")
                else:
                    output.append("`")

        h = self.home.name
        a = self.away.name

        if self.home_score is None or self.away_score is None:
            time = Timestamp(self.kickoff).time_hour
            output.append(f"{time} [{h} v {a}]({self.url})")
        else:
            # Penalty Shootout
            if self.penalties_home is not None:
                pens = f" (p: {self.penalties_home} - {self.penalties_away}) "
                s = min(self.home_score, self.away_score)

                output.append(f"{h} [{s} - {s}]({self.url}){pens}{a}")
            else:
                output.append(self.bold_markdown)
        return " ".join(output)

    @property
    def ac_row(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        if self.competition:
            cmp = self.competition.title
            out = f"⚽ {self.home.name} {self.score} {self.away.name} ({cmp})"
        else:
            out = f"⚽ {self.home.name} {self.score} {self.away.name}"
        return out.casefold()

    async def base_embed(self) -> Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        if self.competition:
            e = await self.competition.base_embed()
        else:
            e = Embed()

        e.url = self.url
        if self.state:
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
                comp_id = href.split("/")[-1]
                comp = bot.get_competition(comp_id)
            else:
                ctr = country.casefold()
                nom = name.casefold()

                for c in bot.competitions:
                    if not c.country or c.country.casefold() != ctr:
                        continue

                    if c.name.casefold() != nom:
                        continue

                    comp = c
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
                self.periods = int(self.infobox.split(": ")[-1].split("x")[0])

        self.events = parse_events(self, tree)
        self.images = tree.xpath('.//div[@class="highlight-photo"]//img/@src')
