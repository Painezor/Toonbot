"""Abstract Base Class for Flashscore Items"""
from __future__ import annotations

import datetime
import logging
import typing

import asyncpg
import discord
from lxml import html
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeoutError

from ext.utils import embed_utils, flags, timed_events

from .constants import (
    COMPETITION_EMOJI,
    FLASHSCORE,
    GOAL_EMOJI,
    LOGO_URL,
    RED_CARD_EMOJI,
    TEAM_EMOJI,
)
from .team import SquadMember, FSTransfer, TFOpts
from .gamestate import GameState
from .matchevents import MatchEvent

if typing.TYPE_CHECKING:
    from core import Bot
    from .players import TopScorer

    Interaction: typing.TypeAlias = discord.Interaction[Bot]


logger = logging.getLogger("ext.flashscore.abc")


def find(value: str, cache: set[Competition]) -> typing.Optional[Competition]:
    """Retrieve a competition from the ones stored in the bot."""
    for i in cache:
        if i.id == value:
            return i

        if i.title.casefold() == value.casefold():
            return i

        if i.url is not None:
            if i.url.rstrip("/") == value.rstrip("/"):
                return i

    # Fallback - Get First Partial match.
    for i in cache:
        if i.url is not None and "http" in value:
            if value in i.url:
                logger.info("Partial url: %s to %s (%s)", value, i.id, i.title)
                return i
    return None


class HasFixtures:
    """A Flashscore Item that has Fixtures that can be fetched"""

    url: typing.Optional[str]

    async def fixtures(
        self, page: Page, cache: set[Competition]
    ) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        return await self.parse_games(page, cache, upcoming=True)

    async def results(
        self, page: Page, cache: set[Competition]
    ) -> list[Fixture]:
        """Get a list of upcoming Fixtures for the FS Item"""
        return await self.parse_games(page, cache, upcoming=False)

    async def parse_games(
        self, page: Page, cache: set[Competition], upcoming: bool
    ) -> list[Fixture]:
        """Parse games from raw HTML from fixtures or results function"""
        # Avoid Circular importing
        sub_page = "/fixtures/" if upcoming else "/results/"

        if self.url is None:
            logger.error("No URL found on %s", self)
            return []

        url = self.url + sub_page

        if page.url != url:
            try:
                await page.goto(url, timeout=3000)
            except PWTimeoutError:
                logger.error("Timed out loading page %s", page.url)
                return []

        loc = page.locator("#live-table")
        await loc.wait_for()
        tree = html.fromstring(await page.content())

        fixtures: list[Fixture] = []

        if isinstance(self, Competition):
            comp = self
        else:
            comp = Competition(None, "Unknown", "Unknown", None)

        xpath = './/div[contains(@class, "sportName soccer")]/div'

        games = tree.xpath(xpath)
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

                    comp = find(f"{ctr.upper()}: {league}", cache)
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

            dtn = datetime.datetime.now(tz=datetime.timezone.utc)
            for string, fmt in [
                (time, "%d.%m.%Y."),
                (time, "%d.%m.%Y"),
                (f"{dtn.year}.{time}", "%Y.%d.%m. %H:%M"),
                (f"{dtn.year}.{dtn.day}.{dtn.month}.{time}", "%Y.%d.%m.%H:%M"),
            ]:
                try:
                    k_o = datetime.datetime.strptime(string, fmt)
                    fixture.kickoff = k_o.astimezone(datetime.timezone.utc)

                    if fixture.kickoff < dtn:
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

    name: str
    id: typing.Optional[str]  # pylint: disable=C0103
    url: typing.Optional[str]

    logo_url: typing.Optional[str] = None
    embed_colour: typing.Optional[discord.Colour | int] = None

    def __init__(
        self,
        fsid: typing.Optional[str],
        name: str,
        url: typing.Optional[str],
    ) -> None:
        self.id = fsid
        self.name = name
        self.url = url

    def __hash__(self) -> int:
        return hash(repr(self))

    def __repr__(self) -> str:
        return f"FlashScoreItem({self.__dict__})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FlashScoreItem):
            return False
        if self.id is None:
            return self.title == other.title
        return self.id == other.id

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

    async def get_scorers(
        self, page: Page, interaction: Interaction
    ) -> list[TopScorer]:
        """Get a list of TopScorer objects for the Flashscore Item"""
        link = f"{self.url}/standings/"

        from .players import Player, TopScorer  # pylint: disable=C0415

        # Example link "#/nunhS7Vn/top_scorers"
        # This requires a competition ID, annoyingly.
        if link not in page.url:
            logger.info("Forcing page change %s -> %s", page.url, link)
            await page.goto(link)

        top_scorer_button = page.locator("a", has_text="Top Scorers")
        await top_scorer_button.wait_for(timeout=5000)

        if await top_scorer_button.get_attribute("aria-current") != "page":
            await top_scorer_button.click()

        tab_class = page.locator("#tournament-table-tabs-and-content")
        await tab_class.wait_for()

        btn = page.locator(".topScorers__showMore")
        while await btn.count():
            await btn.last.click()

        raw = await tab_class.inner_html()
        tree = html.fromstring(raw)

        scorers: list[TopScorer] = []

        rows = tree.xpath('.//div[@class="ui-table__body"]/div')

        for i in rows:
            xpath = "./div[1]//text()"
            name = "".join(i.xpath(xpath))

            xpath = "./div[1]//@href"
            url = FLASHSCORE + "".join(i.xpath(xpath))

            scorer = TopScorer(player=Player(None, name, url))
            xpath = "./span[1]//text()"
            scorer.rank = int("".join(i.xpath(xpath)).strip("."))

            xpath = './/span[contains(@class,"flag")]/@title'
            scorer.player.country = i.xpath(xpath)

            xpath = './/span[contains(@class, "--goals")]/text()'
            try:
                scorer.goals = int("".join(i.xpath(xpath)))
            except ValueError:
                pass

            xpath = './/span[contains(@class, "--gray")]/text()'
            try:
                scorer.assists = int("".join(i.xpath(xpath)))
            except ValueError:
                pass

            team_url = FLASHSCORE + "".join(i.xpath("./a/@href"))
            team_id = team_url.split("/")[-2]

            tmn = "".join(i.xpath("./a/text()"))

            if (team := interaction.client.get_team(team_id)) is None:
                team_link = "".join(i.xpath(".//a/@href"))
                team = Team(team_id, tmn, team_link)

                comp_id = url.split("/")[-2]
                team.competition = interaction.client.get_competition(comp_id)
            else:
                if team.name != tmn:
                    logger.info("Overrode team name %s -> %s", team.name, tmn)
                    team.name = tmn
                    await team.save(interaction.client)

            scorer.team = team
            scorers.append(scorer)
        return scorers


class Competition(FlashScoreItem, HasFixtures):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji = COMPETITION_EMOJI

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

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Competition:
        """Generate a Competition from an asyncpg.Record"""
        i = record
        comp = Competition(i["id"], i["name"], i["country"], i["url"])
        comp.logo_url = i["logo_url"]
        return comp

    def __str__(self) -> str:
        return self.title

    def __hash__(self) -> int:
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
    def flag(self) -> typing.Optional[str]:
        """Get the flag using transfer_tools util"""
        if self.country is None:
            return None
        return flags.get_flag(self.country)

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        return self.name

    async def save(self, bot: Bot) -> None:
        """Save the competition to the bot database"""
        sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
            VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
            (country, name, logo_url, url) =
            (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
            """

        cpm = self  # Line Too Long.
        async with bot.db.acquire(timeout=60) as conn:
            async with conn.transaction():
                await conn.execute(
                    sql, cpm.id, cpm.country, cpm.name, cpm.logo_url, cpm.url
                )
        bot.competitions.add(cpm)
        logger.info("saved competition. %s %s %s", cpm.name, cpm.id, cpm.url)


class Fixture(FlashScoreItem):
    """An object representing a Fixture from the Flashscore Website"""

    emoji = GOAL_EMOJI

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

        super().__init__(fs_id, f"{home.name}:{away.name}", url)

        self.away: Team = away
        self.away_cards: typing.Optional[int] = None
        self.away_score: typing.Optional[int] = None
        self.penalties_away: typing.Optional[int] = None

        self.home: Team = home
        self.home_cards: typing.Optional[int] = None
        self.home_score: typing.Optional[int] = None
        self.penalties_home: typing.Optional[int] = None

        self.time: typing.Optional[str | GameState] = None
        self.kickoff: typing.Optional[datetime.datetime] = None
        self.ordinal: typing.Optional[int] = None

        self.attendance: typing.Optional[int] = None
        self.breaks: int = 0
        self.competition: typing.Optional[Competition] = None
        self.events: list[MatchEvent] = []
        self.infobox: typing.Optional[str] = None
        self.images: typing.Optional[list[str]] = None

        self.periods: typing.Optional[int] = None
        self.referee: typing.Optional[str] = None
        self.stadium: typing.Optional[str] = None

        # Hacky but works for results
        self.win: typing.Optional[str] = None

    def __str__(self) -> str:
        gs = GameState
        if self.time in [gs.LIVE, gs.STOPPAGE_TIME, gs.EXTRA_TIME]:
            time = self.state.name if self.state else None
        elif isinstance(self.time, GameState):
            time = self.ko_relative
        else:
            time = self.time

        return f"{time}: {self.bold_markdown}"

    @property
    def state(self) -> GameState | None:
        """Get a GameState value from stored _time"""
        if isinstance(self.time, str):
            if "+" in self.time:
                return GameState.STOPPAGE_TIME
            return GameState.LIVE
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
        dtn = datetime.datetime.now(tz=datetime.timezone.utc)
        if self.kickoff.date == dtn.date:
            # If the match is today, return HH:MM
            return time.time_hour
        elif self.kickoff.year != dtn.year:
            # if a different year, return DD/MM/YYYY
            return time.date
        elif self.kickoff > dtn:  # For Upcoming
            return time.date_long
        else:
            return time.relative

    @property
    def score(self) -> str:
        """Return "X - Y", or 'vs' if scores are None"""
        if self.home_score is None:
            return "vs"
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
            if not cards:
                return ""
            if cards == 1:
                return f"`{RED_CARD_EMOJI}` "
            return f"`{RED_CARD_EMOJI} x{cards}` "

        h_s, a_s = self.home_score, self.away_score
        h_c = parse_cards(self.home_cards)
        a_c = parse_cards(self.away_cards)
        return f"{home} {h_c}[{h_s} - {a_s}]({self.url}){a_c} {away}"

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output: list[str] = []
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

        if self.time == GameState.SCHEDULED:
            time = timed_events.Timestamp(self.kickoff).time_relative
            embed.description = f"Kickoff: {time}"
        elif self.time == GameState.POSTPONED:
            embed.description = "This match has been postponed."

        if self.competition:
            embed.set_footer(text=f"{self.time} - {self.competition.title}")
        else:
            embed.set_footer(text=self.time)
        return embed

    # High Cost lookups.
    async def refresh(self, bot: Bot) -> None:
        """Perform an intensive full lookup for a fixture"""
        from .matchevents import parse_events  # pylint disable=C0415

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
            k_o = datetime.datetime.strptime(k_o, "%d.%m.%Y %H:%M")
            k_o = k_o.astimezone()
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


class Team(FlashScoreItem, HasFixtures):
    """An object representing a Team from Flashscore"""

    competition: typing.Optional[Competition] = None
    gender: typing.Optional[str] = None
    logo_url: typing.Optional[str] = None

    emoji = TEAM_EMOJI

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
            url = f"https://www.flashscore.com/?r=3:{fs_id}"

        super().__init__(fs_id, name, url)

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Team:
        """Retrieve a Team object from an asyncpg Record"""
        team = Team(record["id"], record["name"], record["url"])
        team.logo_url = record["logo_url"]
        return team

    @classmethod
    async def from_fixture_html(
        cls, bot: Bot, tree: typing.Any, home: bool = True
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
            await team.save(bot)

        return team

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        if len(self.name.split()) == 1:
            return "".join(self.name[:3]).upper()
        return "".join([i for i in self.name if i.isupper()])

    async def get_squad(
        self, page: Page, btn_name: typing.Optional[str] = None
    ) -> list[SquadMember]:
        """Get all squad members for a tournament"""
        from .players import Player  # pylint: disable=C0415

        url = f"{self.url}/squad"

        if page.url != url:
            await page.goto(url, timeout=300)

        loc = page.locator(".lineup")
        await loc.wait_for(timeout=300)

        if btn_name is not None:
            btn = page.locator(btn_name)
            await btn.wait_for(timeout=300)
            await btn.click(force=True)

        # to_click refers to a button press.
        tree = html.fromstring(await loc.inner_html())

        def parse_row(row: typing.Any, position: str) -> SquadMember:
            xpath = './/div[contains(@class, "cell--name")]/a/@href'
            link = FLASHSCORE + "".join(row.xpath(xpath))

            xpath = './/div[contains(@class, "cell--name")]/a/text()'
            name = "".join(row.xpath(xpath)).strip()
            try:  # Name comes in reverse order.
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            player = Player(forename, surname, link)
            xpath = './/div[contains(@class,"flag")]/@title'
            player.country = [str(x.strip()) for x in row.xpath(xpath) if x]
            xpath = './/div[contains(@class,"cell--age")]/text()'
            if age := "".join(row.xpath(xpath)).strip():
                player.age = int(age)

            member = SquadMember(player=player, position=position)
            xpath = './/div[contains(@class,"jersey")]/text()'
            member.squad_number = int("".join(row.xpath(xpath)) or 0)

            xpath = './/div[contains(@class,"cell--goal")]/text()'
            if goals := "".join(row.xpath(xpath)).strip():
                member.goals = int(goals)

            xpath = './/div[contains(@class,"matchesPlayed")]/text()'
            if appearances := "".join(row.xpath(xpath)).strip():
                member.appearances = int(appearances)

            xpath = './/div[contains(@class,"yellowCard")]/text()'
            if yellows := "".join(row.xpath(xpath)).strip():
                member.yellows = int(yellows)

            xpath = './/div[contains(@class,"redCard")]/text()'
            if reds := "".join(row.xpath(xpath)).strip():
                member.reds = int(reds)

            xpath = './/div[contains(@title,"Injury")]/@title'
            member.injury = "".join(row.xpath(xpath)).strip()
            return member

        # Grab All Players.
        members: list[SquadMember] = []
        for i in tree.xpath('.//div[@class="lineup__rows"]'):
            # A header row with the player's position.
            xpath = "./div[@class='lineup__title']/text()"
            position = "".join(i.xpath(xpath)).strip()
            pl_rows = i.xpath('.//div[@class="lineup__row"]')
            members += [parse_row(i, position) for i in pl_rows]
        return members

    async def get_transfers(
        self, page: Page, type_: TFOpts, cache: list[Team]
    ) -> list[FSTransfer]:
        """Get a list of transfers for the team retrieved from flashscore"""
        from .players import Player  # pylint disable=C0415

        if page.url != (url := f"{self.url}/transfers/"):
            await page.goto(url, timeout=500)
            await page.wait_for_selector("section#transfers", timeout=500)

        filters = page.locator("button.filter__filter")

        for i in range(await filters.count()):
            if i == {"All": 0, "Arrivals": 1, "Departures": 2}[type_]:
                await filters.nth(i).click(force=True)

            show_more = page.locator("Show more")
            for _ in range(20):
                if await show_more.count():
                    await show_more.click()

        tree = html.fromstring(await page.inner_html(".transferTab"))

        output: list[FSTransfer] = []
        for i in tree.xpath('.//div[@class="transferTab__row"]'):
            xpath = './/div[contains(@class, "team--from")]/div/a'
            name = "".join(i.xpath(xpath + "/text()"))
            link = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))

            try:
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            trans = FSTransfer()
            player = Player(forename, surname, link)
            player.country = i.xpath('.//span[@class="flag"]/@title')
            trans.player = player

            xpath = './/div[@class="transferTab__season"]/text()'
            _ = "".join(i.xpath(xpath))
            trans.date = datetime.datetime.strptime(_, "%d.%m.%Y")

            _ = "".join(i.xpath(".//svg[1]/@class"))
            trans.direction = "in" if "icon--in" in _ else "out"

            _ = i.xpath('.//div[@class="transferTab__text"]/text()')
            trans.type = "".join(_)

            xpath = './/div[contains(@class, "team--to")]/div/a'
            if team_name := "".join(i.xpath(xpath + "/text()")):
                tm_lnk = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))

                team_id = tm_lnk.split("/")[-2]

                try:
                    team = next(i for i in cache if i.id == team_id)
                except StopIteration:
                    team = Team(team_id, team_name, tm_lnk)

                trans.team = team
            output.append(trans)
        return output

    async def save(self, bot: Bot) -> None:
        """Save the Team to the Bot Database"""
        sql = """INSERT INTO fs_teams (id, name, logo_url, url)
                VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE SET
                (name, logo_url, url)
                = (EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
                """
        async with bot.db.acquire(timeout=60) as conn:
            async with conn.transaction():
                await conn.execute(
                    sql, self.id, self.name, self.logo_url, self.url
                )
        bot.teams.append(self)
