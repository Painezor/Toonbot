"""Helper Cog that works with Scores & Tickers Cogs"""
from __future__ import annotations

import asyncio
import datetime
from logging import getLogger
from typing import TYPE_CHECKING, TypeAlias

import discord
from discord.ext import commands, tasks
from lxml import etree, html
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeout

import ext.flashscore as fs
from ext.flashscore.gamestate import GameState

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]

logger = getLogger("ScoreLoop")

CURRENT_DATETIME_OFFSET = 2  # Hour difference between us and flashscore
MAX_RECURSION = 5
MAX_SCORE_WORKERS = 1


def get_half_time_change(old: str) -> str:
    if old == GameState.EXTRA_TIME.value:
        return "et_ht_start"
    return "half_time"


def get_break_time_change(old: str) -> str:
    if old == GameState.EXTRA_TIME.value:
        return "et_end"
    return "normal_time_end"


def get_extra_time_change(old: str) -> str:
    if old == GameState.HALF_TIME.value:
        return "et_ht_end"
    return "et_start"


def get_live_change(old: str) -> str:
    return {
        GameState.SCHEDULED.value: "kickoff",
        GameState.DELAYED.value: "kickoff",
        GameState.INTERRUPTED.value: "fixture_resumed",
        GameState.STOPPAGE_TIME.value: "second_half",
        GameState.HALF_TIME.value: "second_half",
        GameState.BREAK_TIME.value: "period_begin",
    }[old]


def get_full_time_change(old: str) -> str:
    try:
        return {
            GameState.EXTRA_TIME.value: "aet_result",
            GameState.SCHEDULED.value: "final_result",
            GameState.HALF_TIME.value: "final_result",
        }[old]
    except KeyError:
        return "full_time"


def get_event_type(new: GameState | None, old: GameState | None) -> str | None:
    """Conver a new / old difference to an EventType"""
    if old is None:
        return
    if new is None:
        return

    nval = new.value
    oval = old.value

    if nval == oval:
        return

    if nval in [GameState.AWAITING.value, GameState.STOPPAGE_TIME.value]:
        return

    # I'm pretty sure this is a fucking warcrime.
    try:
        return {
            GameState.ABANDONED.value: "fixture_abandoned",
            GameState.AFTER_EXTRA_TIME.value: "aet_result",
            GameState.AFTER_PENS.value: "penalty_results",
            GameState.AWARDED.value: "fixture_awarded",
            GameState.BREAK_TIME.value: get_break_time_change(oval),
            GameState.CANCELLED.value: "fixture_cancelled",
            GameState.DELAYED.value: "fixture_delayed",
            GameState.EXTRA_TIME.value: get_extra_time_change(oval),
            GameState.FULL_TIME.value: get_full_time_change(oval),
            GameState.HALF_TIME.value: get_half_time_change(oval),
            GameState.INTERRUPTED.value: "fixture_interrupted",
            GameState.LIVE.value: get_live_change(oval),
            GameState.PENALTIES.value: "penalties_start",
            GameState.POSTPONED.value: "fixture_postponed",
            GameState.WALKOVER.value: "fixture_cancelled",
        }[nval]
    except KeyError:
        logger.error("New State Change Not Handled: %s -> %s", oval, nval)


class ScoreLoop(commands.Cog):
    """Fetching of LiveScores"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.tasks: set[asyncio.Task[None]] = set()
        self.score_workers: asyncio.Queue[Page] = asyncio.Queue()

        self._pending: list[fs.Fixture] = []

    async def cog_load(self) -> None:
        """Start the scores loop"""
        self.scores: asyncio.Task[None] = self.score_loop.start()
        await self.bot.cache.cache_competitions()
        await self.bot.cache.cache_teams()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.scores.cancel()

        for i in self.tasks:
            i.cancel()

        self.bot.cache.games.clear()

        while not self.score_workers.empty():
            page = await self.score_workers.get()
            await page.close()

    @tasks.loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        hours = CURRENT_DATETIME_OFFSET
        offset = datetime.timezone(datetime.timedelta(hours=hours))
        now = datetime.datetime.now(offset)
        bad_time = now - datetime.timedelta(hours=24)

        for i in self.bot.cache.games:
            if i.kickoff is not None:
                if i.kickoff < bad_time:
                    self.bot.cache.games.remove(i)

        await self.parse_games()
        if self._pending:
            await self.handle_pending_fixtures()

            # Destroy all of our workers
            while not self.score_workers.empty():
                page = await self.score_workers.get()
                await page.close()
            logger.info("Finished parsing scores")

        self.bot.dispatch("scores_ready", now)

    async def handle_pending_fixtures(self, recursion: int = 0) -> None:
        """Fetch all data for a fixture"""

        recur = "" if not recursion else f"retry #{recursion}"
        logger.info("Batch Fetching %s fixtures %s", len(self._pending), recur)

        async def spawn_worker() -> None:
            """Create a worker object"""
            page = await self.bot.browser.new_page()
            await self.score_workers.put(page)

        # Bulk spawn our workers.
        # We use recursion so don't remake.
        if not recursion:
            num_workers = min(len(self._pending), MAX_SCORE_WORKERS)
            await asyncio.gather(*[spawn_worker() for _ in range(num_workers)])

        failed: list[fs.Fixture] = []
        success: list[fs.Fixture] = []

        async def do_fixture(fixture: fs.Fixture) -> None:
            """Get worker, fetch page, release worker"""
            page = await self.score_workers.get()
            try:
                await fixture.fetch(page, cache=self.bot.cache)
            except PWTimeout:
                failed.append(fixture)
            else:
                success.append(fixture)
            finally:
                await self.score_workers.put(page)

        await asyncio.gather(*[do_fixture(i) for i in self._pending])

        save: list[fs.abc.BaseCompetition | None] = []
        teams: list[fs.abc.BaseTeam] = []

        for item in success:
            teams += [item.home.team, item.away.team]
            if item.competition not in save:
                save.append(item.competition)

        # Bulk Save data.
        await self.bot.cache.save_competitions([i for i in save if i])
        await self.bot.cache.save_teams(teams)

        self._pending = failed
        if failed and recursion < MAX_RECURSION:
            return await self.handle_pending_fixtures(recursion + 1)

    # Core Loop
    def handle_cards(
        self, fix: fs.abc.BaseFixture, tree: html.HtmlElement
    ) -> None:
        """Handle the Cards of a fixture"""
        if not (cards := tree.xpath("./img/@class")):
            return

        cards = [i.replace("rcard-", "") for i in cards]

        try:
            home, away = [int(card) for card in cards]
        except ValueError:
            if len(tree.xpath("./text()")) == 2:
                home, away = int(cards[0]), None
            else:
                home, away = None, int(cards[0])

        if home and home != fix.home.cards:
            evt = "red_card" if home > fix.home.cards else "var_red_card"
            self.bot.dispatch(evt, fix, team=fix.home.team)
            fix.home.cards = home

        if away and away != fix.away.cards:
            evt = "red_card" if away > fix.away.cards else "var_red_card"
            self.bot.dispatch(evt, fix, team=fix.away.team)
            fix.away.cards = away

    def handle_kickoff(
        self, fix: fs.abc.BaseFixture, tree: html.HtmlElement, state: str
    ) -> None:
        """Set the kickoff of a fixture by parsing data"""
        if fix.kickoff:
            return

        try:
            time = tree.xpath("./span/text()")[0]
        except IndexError:
            return

        if ":" not in time:
            return

        # We use the parsed data to create a 'cleaner' datetime object, with
        # no second or microsecond and set the day to today. This unfucks our
        # Embed Comparisons in the dispatch, since if we have micros, the time
        # stamp will constantly be changing, making for a fucked embed.
        now = discord.utils.utcnow()
        offset = datetime.timedelta(hours=CURRENT_DATETIME_OFFSET)
        _ = datetime.datetime.strptime(time, "%H:%M") - offset
        _ = now.replace(hour=_.hour, minute=_.minute, second=0, microsecond=0)

        # If the game appears to be in the past
        # but has not kicked off yet, add a day.
        if now.timestamp() > _.timestamp() and state == "sched":
            _ += datetime.timedelta(days=1)
        fix.kickoff = _

    def handle_score(
        self, fix: fs.abc.BaseFixture, tree: html.HtmlElement
    ) -> str | None:
        """Parse Score and return overrides if they exist."""
        home, away = tree.xpath("string(.//a/text())").split(":")

        override = None
        if away == "-":
            return

        override = "".join([i for i in away if not i.isdigit()])

        hsc = int(home)
        asc = int("".join([i for i in away if i.isdigit()]))

        if fix.home.score != hsc:
            if fix.home.score is not None:
                evt = "goal" if hsc > fix.home.score else "var_goal"
                self.bot.dispatch(evt, fix, team=fix.home.team)
            fix.home.score = hsc

        if fix.away.score != asc:
            if fix.away.score is not None:
                evt = "goal" if asc > fix.away.score else "var_goal"
                self.bot.dispatch(evt, fix, team=fix.away.team)
            fix.away.score = asc

        return override

    async def fetch_mobi_html(self) -> list[str]:
        """Get the raw HTML for our games split into chunks"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                logger.error("%s: %s", resp.status, resp.url)
                return []
            bt_a = bytearray(await resp.text(), encoding="utf-8")
            tree = html.fromstring(bytes(bt_a))

        data = tree.xpath('.//div[@id="score-data"]')[0]
        return etree.tostring(data).decode("utf8").split("<br/>")

    def handle_time(
        self, fix: fs.abc.BaseFixture, time: str, tree: html.HtmlElement
    ) -> None:
        """Handle the parsing of time based on collected data."""
        if ":" in time:
            return  # This is a kickoff.

        try:
            fix.time = {
                # 1 Parter
                "Break Time": GameState.BREAK_TIME,
                "Extra Time": GameState.EXTRA_TIME,
                "Half Time": GameState.HALF_TIME,
                "Live": GameState.FINAL_RESULT_ONLY,
                "Penalties": GameState.PENALTIES,
                # 2 Parters
                "Abandoned": GameState.ABANDONED,
                "Cancelled": GameState.CANCELLED,
                "Delayed": GameState.DELAYED,
                "Interrupted": GameState.INTERRUPTED,
                "Postponed": GameState.POSTPONED,
                # Overrides
                "Awaiting": GameState.AWAITING,
                "aet": GameState.AFTER_EXTRA_TIME,
                "fin": GameState.FULL_TIME,
                "pen": GameState.AFTER_PENS,
                "sched": GameState.SCHEDULED,
                "wo": GameState.WALKOVER,
            }[time]
        except KeyError:
            for i in (time := tree.xpath("./span/text()")):
                if "'" in i or ":" in i:
                    fix.time = i
                    break
            else:
                logger.error("Time Not unhandled: %s", time)

    def get_fixture_from_cache(
        self, tree: html.HtmlElement
    ) -> tuple[fs.abc.BaseFixture, GameState | None]:
        """Fetch the fixture from the cache"""
        link = "".join(tree.xpath(".//a/@href"))
        match_id = link.split("/")[-2]

        fix = self.bot.cache.get_game(match_id)
        if fix:
            return fix, fix.state

        fix = fs.abc.BaseFixture.from_mobi(tree, match_id)
        if fix is None:
            raise LookupError
        fix = fs.Fixture.parse_obj(fix)

        self._pending.append(fix)
        self.bot.cache.games.append(fix)
        return fix, None

    async def parse_games(self) -> None:
        """
        Grab current scores from flashscore using aiohttp
        Returns a list of fixtures and dildos that need a full parse
        """
        chunks = await self.fetch_mobi_html()

        for game in chunks:
            try:
                tree = html.fromstring(game)
                fix, old_state = self.get_fixture_from_cache(tree)
            except (etree.ParserError, IndexError, LookupError):
                # Document is empty because of trailing </div>
                # Or state is AWAITING
                continue

            # Handling red cards is done relatively simply, do this first.
            self.handle_cards(fix, tree)

            time = self.handle_score(fix, tree)
            state = "".join(tree.xpath("./a/@class")).strip()
            if not time and state in ["sched", "fin"]:
                time = state
            else:
                try:
                    time = str(tree.xpath("./span/text()")[-1])
                except IndexError:
                    time = "Awaiting"

            self.handle_kickoff(fix, tree, state)
            self.handle_time(fix, time, tree)
            e_type = get_event_type(fix.state, old_state)
            if e_type is not None:
                self.bot.dispatch(e_type, fix)


async def setup(bot: Bot) -> None:
    """Load the score loop cog into the bot"""
    await bot.add_cog(ScoreLoop(bot))
