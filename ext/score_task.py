"""Helper Cog that works with Scores & Tickers Cogs"""
from __future__ import annotations

import asyncio
import datetime
from logging import getLogger
from typing import TYPE_CHECKING, TypeAlias

import discord
from discord.ext import commands, tasks
from lxml import html, etree
from playwright.async_api import Page, TimeoutError as PWTimeout

from ext import flashscore as fs

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]

logger = getLogger("ScoreLoop")

EVT = fs.EventType
MAX_SCORE_WORKERS = 5
CURRENT_DATETIME_OFFSET = 2  # Hour difference between us and flashscore
FXE = "fixture_event"  # Just a string for dispatching events.


class ScoreLoop(commands.Cog):
    """Fetching of LiveScores"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.tasks: set[asyncio.Task[None]] = set()
        self.score_workers: asyncio.Queue[Page] = asyncio.Queue()
        self._last_ordinal: int = 0

    async def cog_load(self) -> None:
        """Start the scores loop"""
        self.scores: asyncio.Task[None] = self.score_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.scores.cancel()

        for i in self.tasks:
            i.cancel()

        self.bot.flashscore.games.clear()

        while not self.score_workers.empty():
            page = await self.score_workers.get()
            await page.close()

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: Interaction, _
    ) -> None:
        """The transformers save comps/teams to their extras, so we can
        update them as they're found."""
        cache = interaction.client.flashscore
        if "comps" in interaction.extras:
            await cache.save_competitions(interaction.extras["comps"])
        if "teams" in interaction.extras:
            await cache.save_competitions(interaction.extras["teams"])

    @tasks.loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        hours = CURRENT_DATETIME_OFFSET
        offset = datetime.timezone(datetime.timedelta(hours=hours))
        now = datetime.datetime.now(offset)
        ordinal = now.toordinal()

        if self._last_ordinal != ordinal:
            self.bot.flashscore.games.clear()
            self._last_ordinal = ordinal

        need_refresh = await self.parse_games()
        if need_refresh:
            self.bot.loop.create_task(self.bulk_fixtures(need_refresh))
        self.bot.dispatch("scores_ready", now)

    async def handle_teams(
        self, fixture: fs.Fixture, tree: html.HtmlElement
    ) -> None:
        """Fetch the teams from the fixture and look them up in our cache."""
        home, away = await self.bot.flashscore.teams_from_fixture(tree)
        fixture.home.team = home
        fixture.away.team = away

    async def bulk_fixtures(
        self, fixtures: list[fs.Fixture], recursion: int = 0
    ) -> None:
        """Fetch all data for a fixture"""

        recur = "" if not recursion else f"retry #{recursion}"
        logger.info("Batch Fetching %s fixtures %s", len(fixtures), recur)

        async def spawn_worker() -> None:
            """Create a worker object"""
            page = await self.bot.browser.new_page()
            await self.score_workers.put(page)

        # Bulk spawn our workers.
        # We use recursion so don't remake.
        if not recursion:
            num_workers = min(len(fixtures), MAX_SCORE_WORKERS)
            await asyncio.gather(*[spawn_worker() for _ in range(num_workers)])

        failed: list[fs.Fixture] = []

        async def do_fixture(fixture: fs.Fixture) -> None:
            """Get worker, fetch page, release worker"""
            page = await self.score_workers.get()
            try:
                await fixture.fetch(page, cache=self.bot.flashscore)
            except PWTimeout:
                failed.append(fixture)
            finally:
                await self.score_workers.put(page)

        await asyncio.gather(*[do_fixture(i) for i in fixtures])

        if not failed:
            # Destroy all of our workers
            while not self.score_workers.empty():
                page = await self.score_workers.get()
                await page.close()

            # Bulk Save our competitions.
            cmps = list(set(i.competition for i in fixtures if i.competition))
            await self.bot.flashscore.save_competitions(cmps)
            return

        await self.bulk_fixtures(failed, recursion + 1)

    # Core Loop
    def handle_cards(self, fix: fs.Fixture, tree: html.HtmlElement) -> None:
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
            evt = EVT.RED_CARD if home > fix.home.cards else EVT.VAR_RED_CARD
            self.bot.dispatch(FXE, evt, fix, home=True)
            fix.home.cards = home

        if away and away != fix.away.cards:
            evt = EVT.RED_CARD if away > fix.away.cards else EVT.VAR_RED_CARD
            self.bot.dispatch(FXE, evt, fix, home=False)
            fix.away.cards = away

    def handle_kickoff(
        self, fix: fs.Fixture, tree: html.HtmlElement, state: str
    ) -> None:
        """Set the kickoff of a fixture by parsing data"""
        if fix.kickoff:
            return

        time = tree.xpath("./span/text()")[0]
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
        self, fix: fs.Fixture, tree: html.HtmlElement
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
                evt = EVT.GOAL if hsc > fix.home.score else EVT.VAR_GOAL
                self.bot.dispatch(FXE, evt, fix, home=True)
            fix.home.score = hsc

        if fix.away.score != asc:
            if fix.away.score is not None:
                evt = EVT.GOAL if asc > fix.away.score else EVT.VAR_GOAL
                self.bot.dispatch(FXE, evt, fix, home=False)
            fix.away.score = asc

        return override

    async def fetch_games(self) -> list[str]:
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
        self, fix: fs.Fixture, time: str, tree: html.HtmlElement
    ) -> None:
        """Handle the parsing of time based on collected data."""
        try:
            fix.time = {
                # 1 Parter
                "Break Time": fs.GameState.BREAK_TIME,
                "Extra Time": fs.GameState.EXTRA_TIME,
                "Half Time": fs.GameState.HALF_TIME,
                "Live": fs.GameState.FINAL_RESULT_ONLY,
                "Penalties": fs.GameState.PENALTIES,
                # 2 Parters
                "Abandoned": fs.GameState.ABANDONED,
                "Cancelled": fs.GameState.CANCELLED,
                "Delayed": fs.GameState.DELAYED,
                "Interrupted": fs.GameState.INTERRUPTED,
                "Postponed": fs.GameState.POSTPONED,
                # Overrides
                "aet": fs.GameState.AFTER_EXTRA_TIME,
                "fin": fs.GameState.FULL_TIME,
                "pen": fs.GameState.AFTER_PENS,
                "sched": fs.GameState.SCHEDULED,
                "wo": fs.GameState.WALKOVER,
            }[time]
        except KeyError:
            for i in (time := tree.xpath("./span/text()")):
                if "'" in i or ":" in i:
                    fix.time = i
                    break
            else:
                logger.error("Time Not unhandled: %s", time)

    async def parse_games(self) -> list[fs.Fixture]:
        """
        Grab current scores from flashscore using aiohttp
        Returns a list of fixtures and dildos that need a full parse
        """
        chunks = await self.fetch_games()

        to_fetch: list[fs.Fixture] = []

        for game in chunks:
            try:
                tree = html.fromstring(game)
            except etree.ParserError:
                continue  # Document is empty because of trailing </div>

            link = "".join(tree.xpath(".//a/@href"))
            try:
                match_id = link.split("/")[-2]
            except IndexError:
                # Awaiting.
                continue

            # Set & forget: Competition, Teams
            fix = self.bot.flashscore.get_game(match_id)
            if fix is None:
                fix = fs.Fixture.from_mobi(tree, match_id)
                if fix is None:
                    continue

                to_fetch.append(fix)
                self.bot.flashscore.games.append(fix)
                await asyncio.sleep(0)
                old_state = None
            else:
                old_state = fix.state

            # Handling red cards is done relatively simply, do this first.
            self.handle_cards(fix, tree)

            time = self.handle_score(fix, tree)
            state = "".join(tree.xpath("./a/@class")).strip()
            if time is None and state in ["sched", "fin"]:
                time = state
            else:
                try:
                    time = str(tree.xpath("./span/text()")[-1])
                except IndexError:
                    logger.error("Error on time[-1] for %s", fix.score_line)
                    continue

            self.handle_kickoff(fix, tree, state)
            self.handle_time(fix, time, tree)
            e_type = fs.get_event_type(fix.state, old_state)
            self.bot.dispatch("fixture_event", e_type, fix)
        return to_fetch


async def setup(bot: Bot) -> None:
    """Load the score loop cog into the bot"""
    await bot.add_cog(ScoreLoop(bot))
