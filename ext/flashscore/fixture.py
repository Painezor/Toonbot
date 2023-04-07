"""Submodule for handling Fixtures"""
from __future__ import annotations

import datetime
import logging
import typing

import discord
from lxml import html
from playwright.async_api import Page, TimeoutError as pw_TimeoutError

from ext.utils import timed_events

from .abc import FlashScoreItem
from .competitions import Competition
from .constants import FLASHSCORE
from .gamestate import GameState
from .matchevents import MatchEvent, parse_events
from .team import Team


if typing.TYPE_CHECKING:
    from core import Bot


logger = logging.getLogger("flashscore.fixture")


async def parse_games(
    bot: Bot, object_: FlashScoreItem, sub_page: str
) -> list[Fixture]:
    """Parse games from raw HTML from fixtures or results function"""
    page: Page = await bot.browser.new_page()

    if object_.url is None:
        raise ValueError(f"No URL found in {object_}")
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
        self.id: typing.Optional[str] = fs_id  # pylint: disable=C0103

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
            if not cards:
                return ""
            if cards == 1:
                return "`🟥` "
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