"""A Utility tool for fetching and structuring data from Flashscore"""
from __future__ import annotations
import asyncio  # Cyclic Type Hinting

import logging
from datetime import datetime, timezone
from urllib.parse import quote

import discord
from lxml import html
from playwright.async_api import Page

from ext.toonbot_utils.gamestate import GameState
from ext.utils import embed_utils, flags, timed_events
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


def parse_events(fixture: Fixture, tree) -> list[m_evt.MatchEvent]:
    """Get a list of match events"""

    events = []
    logger.info("parsing match events on %s", fixture.url)
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
                    logger.error("ValueError splitting pens %s", text)
                    logger.error(fixture.url)
                    _, pen_string = text
                    h, a = pen_string.split(" - ")
                    fixture.penalties_home = h
                    fixture.penalties_away = a
            else:
                logger.info("Header Row on parse_events %s", text)

            continue

        try:
            # event node -- if we can't find one, we can't parse one.
            node = i.xpath('./div[contains(@class, "incident")]')[0]
        except IndexError:
            continue

        svg_text = "".join(node.xpath(".//svg//text()")).strip()
        svg_class = "".join(node.xpath(".//svg/@class")).strip()
        sub_i = "".join(node.xpath(".//div[@class='smv__subIncident']/text()"))

        logger.info("text: %s, class: %s", svg_text, svg_class)
        if sub_i:
            logger.info("sub_incident: %s", sub_i)

        # Try to figure out what kind of event this is.
        if svg_class == "soccer":
            # This is a goal.

            if sub_i == "(Penalty)":
                event = m_evt.Penalty()

            elif sub_i:
                logger.info("Unhandled goal sub_incident", sub_i)
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
            logger.error("Match Event Not Handled correctly.")
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
                p = Player(forename, surname, s_url)
                event.player_off = p

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

                p = Player(forename, surname, a_url)
                event.assist = p

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

    logger.info("TODO: Fetch team IDs & urls on %s", object.url)

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
            return f"[{self.name or 'Unknown Item'}]({self.url})"
        return self.name or "Unknown Item"

    @property
    def title(self) -> str:
        return self.name or "Unknown Item"

    async def base_embed(self) -> discord.Embed:
        """A discord Embed representing the flashscore search result"""

        e = discord.Embed()
        e.set_author(name=self.title, icon_url=self.logo_url)
        e.description = ""

        if self.logo_url is not None:
            if "flashscore" in self.logo_url:
                logo = self.logo_url
            else:
                logo = LOGO_URL + self.logo_url.replace("'", "")  # Extraneous

            if logo:
                if (clr := self.embed_colour) is None:
                    clr = await embed_utils.get_colour(logo)
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
    def from_fixture_html(cls, bot: Bot, tree, home: bool = True) -> Team:

        attr = "home" if home else "away"

        xpath = f".//div[contains(@class, 'duelParticipant__{attr}')]"
        div = tree.xpath(xpath)
        if not div:
            raise LookupError("Cannot find team on page.")

        div = div[0]  # Only One

        # Get Name
        xp = ".//a[contains(@class, 'participant__participantName')]/"
        name = "".join(div.xpath(xp + "text()"))
        url = "".join(div.xpath(xp + "@href"))

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
                bot.teams.append(team)

        if team.logo_url is None:
            logo = div.xpath('.//img[@class="participant__image"]/@src')
            logo = "".join(logo)
            if logo:
                team.logo_url = FLASHSCORE + logo

        return team

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

        if name and country and not url:
            nom = name.casefold().replace(" ", "-").replace(".", "")
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = FLASHSCORE + f"/football/{ctr}/{nom}"
        elif url and country and FLASHSCORE not in url:
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = f"{FLASHSCORE}/{ctr}/{url}/"
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
        return flags.get_flag(self.country)

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country:
            return f"{self.country.upper()}: {self.name}"
        else:
            return self.name


# Do up to N fixtures at a time
semaphore = asyncio.Semaphore(2)


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

    async def fetch_data(self, bot: Bot):
        logger.info("Entered Fetch_data on url %s", self.url)
        if self.url is None:
            return

        # TODO: Flesh this out to actually try and find the team's IDs.
        # DO all set and forget shit.

        async with semaphore:
            page = await bot.browser.new_page()
            try:
                await page.goto(self.url)

                # We are now on the fixture's page. Hooray.
                loc = page.locator(".duelParticipant")
                await loc.wait_for(timeout=2500)
                tree = html.fromstring(await page.content())
            finally:
                await page.close()
        logger.info("Got page on url %s", self.url)
        # Handle Teams

        self.home = Team.from_fixture_html(bot, tree)
        self.away = Team.from_fixture_html(bot, tree, home=False)

        # TODO: Fetch Competition Info
        div = tree.xpath(".//span[@class='tournamentHeader__country']")
        logger.info("Fetching competition...")
        if div:
            div = div[0]

            url = "".join(div.xpath(".//@href"))
            comp_id = url.split("/")[-2]
            country = "".join(div.xpath("./text()"))
            name = "".join(div.xpath(".//a/text()"))

            logger.info("Competition comp_id=%s, url=%s", url, comp_id)
            if country:
                country.split(":")[0]

            if (comp := bot.get_competition(comp_id)) is not None:
                logger.info("Found matching comp for %s", comp_id)
            else:
                for i in bot.competitions:
                    if i.url and url in i.url:
                        comp = i
                        break
                else:
                    url = FLASHSCORE + url
                    comp = Competition(comp_id, name, country, url)

            self.competition = comp

        # TODO: Referee, Stadium
        if None in [self.referee, self.stadium]:
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')

            if ref := "".join([i for i in text if "referee" in i.casefold()]):
                self.referee = ref.strip().replace("Referee:", "")

            if venue := "".join([i for i in text if "venue" in i.casefold()]):
                self.stadium = venue.strip().replace("Venue:", "")

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
        t = timed_events.Timestamp(self.kickoff).relative
        return f"{t}: {self.bold_markdown}"

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

        ts = timed_events.Timestamp(self.kickoff)
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

        def parse_cards(cards: typing.Optional[int]) -> str:
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
            time = timed_events.Timestamp(self.kickoff).time_hour
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

    async def base_embed(self) -> discord.Embed:
        """Return a preformatted discord embed for a generic Fixture"""
        if self.competition:
            e = await self.competition.base_embed()
        else:
            e = discord.Embed()

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
                time = timed_events.Timestamp(self.kickoff).time_relative
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
    interaction: discord.Interaction[Bot],
    query: str,
    mode: typing.Literal["comp", "team"],
) -> list[Competition | Team]:
    """Fetch a list of items from flashscore matching the user's query"""
    replace = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))
    query = quote(replace)

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

    # Type IDs: 1 - Team | Tournament, 2 - Team, 3 - Player 4 - PlayerInTeam
    url = (
        f"https://s.livesport.services/api/v2/search/?q={query}"
        f"&lang-id={lang_id}&type-ids=1,2,3,4&sport-ids=1"
    )

    async with bot.session.get(url) as resp:
        match resp.status:
            case 200:
                res = typing.cast(dict, await resp.json())
            case _:
                err = f"HTTP {resp.status} error while searching flashscore"
                raise LookupError(err)

    results: list[Competition | Team] = []
    for x in res:
        for t in x["participantTypes"]:
            match t["name"]:
                case "National" | "Team":
                    if mode == "comp":
                        continue

                    if not (team := bot.get_team(x["id"])):

                        team = Team(x["id"], x["name"], x["url"])
                        try:
                            team.logo_url = x["images"][0]["path"]
                        except IndexError:
                            pass
                        team.gender = x["gender"]["name"]
                        await save_team(interaction, team)
                    results.append(team)
                case "TournamentTemplate":
                    if mode == "team":
                        continue

                    if not (comp := bot.get_competition(x["id"])):
                        ctry = x["defaultCountry"]["name"]
                        nom = x["name"]
                        comp = Competition(x["id"], nom, ctry, x["url"])
                        try:
                            comp.logo_url = x["images"][0]["path"]
                        except IndexError:
                            pass
                        await save_comp(interaction, comp)
                    results.append(comp)
                case _:
                    continue  # This is a player, we don't want those.

    if not results:
        raise LookupError("Flashscore Search: No results found for %s", query)
    return results


# DB Management
async def save_team(interaction: discord.Interaction[Bot], t: Team) -> None:
    """Save the Team to the Bot Database"""
    sql = """INSERT INTO fs_teams (id, name, logo_url, url)
             VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
    async with interaction.client.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(sql, t.id, t.name, t.logo_url, t.url)
    interaction.client.teams.append(t)


async def save_comp(
    interaction: discord.Interaction[Bot], c: Competition
) -> None:
    """Save the competition to the bot database"""
    sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
                 VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING"""
    async with interaction.client.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(sql, c.id, c.country, c.name, c.logo_url, c.url)
    interaction.client.competitions.append(c)
