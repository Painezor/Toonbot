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


# TODO: make to_refresh an Asyncio.Queue
# TODO: Nuke override and just directly replace the time.
class ScoreLoop(commands.Cog):
    """Fetching of LiveScores"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.tasks: set[asyncio.Task[None]] = set()
        self.score_workers: asyncio.Queue[Page] = asyncio.Queue()
        self._last_ordinal: int = 0

    async def cog_load(self) -> None:
        """Start the scores loop"""
        self.bot.scores = self.score_loop.start()  # pylint: disable=E1101

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        if self.bot.scores is not None:
            self.bot.scores.cancel()

        for i in self.tasks:
            i.cancel()

        self.bot.games.clear()

        while not self.score_workers.empty():
            page = await self.score_workers.get()
            await page.close()

    @tasks.loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        hours = CURRENT_DATETIME_OFFSET
        offset = datetime.timezone(datetime.timedelta(hours=hours))
        now = datetime.datetime.now(offset)
        ordinal = now.toordinal()

        if self._last_ordinal != ordinal:
            self.bot.games.clear()
            self._last_ordinal = ordinal

        need_refresh = await self.parse_games()
        if need_refresh:
            self.bot.loop.create_task(self.bulk_fixtures(need_refresh))
        self.bot.dispatch("scores_ready", now)

    async def handle_teams(
        self, fixture: fs.Fixture, tree: html.HtmlElement
    ) -> None:
        """Fetch the teams from the fixture and look them up in our cache."""
        home, away = await fs.Team.from_fixture_html(tree)
        try:
            home = next(i for i in self.bot.teams if i.id == home.id)
        except StopIteration:
            pass
        fixture.home = home

        try:
            away = next(i for i in self.bot.teams if i.id == away.id)
        except StopIteration:
            pass

        fixture.away = away
        await self.bot.save_teams([home, away])

    async def fetch_competition(
        self, page: Page, url: str
    ) -> fs.Competition | None:
        """Go to a competition's page and fetch it directly."""
        await page.goto(url)
        selector = page.locator(".heading")

        try:
            await selector.wait_for()
        except PWTimeout:
            logger.error("Could not find .heading on %s", url)
            return

        tree = html.fromstring(await selector.inner_html())

        country = tree.xpath(".//a[@class='breadcrumb__link']")[-1]

        mylg = tree.xpath(".//span[contains(@title, 'Add this')]/@class")[0]
        mylg = [i for i in mylg.rsplit(maxsplit=1) if "_" in i][-1]
        comp_id = mylg.rsplit("_", maxsplit=1)[-1]

        src = None

        try:
            # Name Correction
            name_loc = page.locator(".heading__name").first
            logo_url = page.locator(".heading__logo").first

            name = await name_loc.text_content(timeout=1000)
            if name is None:
                logger.error("Failed to find name on %s", url)
                return
            src = await logo_url.get_attribute("src", timeout=1000)
        except PWTimeout:
            logger.error("Timed out heading__logo %s", url)
            return

        if (comp := self.bot.get_competition(comp_id)) is None:
            comp = fs.Competition(comp_id, name, country, url)

        if src is not None:
            comp.logo_url = fs.FLASHSCORE + src

        await self.bot.save_competitions([comp])
        return comp

    async def fetch_fixture(
        self, fixture: fs.Fixture, page: Page, force: bool = False
    ) -> None:
        """Fetch all data for a fixture"""
        if fixture.url is None:
            logger.error("url is None on fixture %s", fixture.name)
            return

        await asyncio.sleep(0)
        await page.goto(fixture.url)
        loc = page.locator(".duelParticipant")
        await loc.wait_for(timeout=2500)
        tree = html.fromstring(await page.content())

        div = tree.xpath(".//span[@class='tournamentHeader__country']")[0]

        url = fs.FLASHSCORE + "".join(div.xpath(".//@href")).rstrip("/")
        country = "".join(div.xpath("./text()"))

        mls = tree.xpath('.//div[@class="ml__item"]')
        for i in mls:
            label = "".join(i.xpath('./span[@class="mi__item__name]/text()'))
            label = label.strip(":")

            value = "".join(i.xpath('/span[@class="mi__item__val"]/text()'))

            if "referee" in label.lower():
                fixture.referee = value
            elif "venue" in label.lower():
                fixture.stadium = value
            else:
                logger.info("Fixture, extra data found %s %s", label, value)

        # TODO: Log TV Data

        if country:
            country = country.split(":", maxsplit=1)[0]

        name = "".join(div.xpath(".//a/text()"))

        if not force:
            if comp := self.bot.get_competition(url):
                fixture.competition = comp
                return

            if comp := self.bot.get_competition(f"{country}: {name}"):
                fixture.competition = comp
                return

        fixture.competition = await self.fetch_competition(page, url)

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
                await self.fetch_fixture(fixture, page)
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
            return

        await self.bulk_fixtures(failed, recursion + 1)

    # Core Loop
    def handle_cards(self, fix: fs.Fixture, tree: html.HtmlElement) -> None:
        """Handle the Cards of a fixture"""
        cards = tree.xpath("./img/@class")
        cards = [i.replace("rcard-", "") for i in cards]

        try:
            home, away = [int(card) for card in cards]
        except ValueError:
            if len(tree.xpath("./text()")) == 2:
                home, away = int(cards[0]), None
            else:
                home, away = None, int(cards[0])

        if home and home != fix.home_cards:
            evt = EVT.RED_CARD if home > fix.home_cards else EVT.VAR_RED_CARD
            self.bot.dispatch(FXE, evt, fix, home=True)
            fix.home_cards = home

        if away and away != fix.away_cards:
            evt = EVT.RED_CARD if away > fix.away_cards else EVT.VAR_RED_CARD
            self.bot.dispatch(FXE, evt, fix, home=False)
            fix.away_cards = away

    def handle_kickoff(
        self, fix: fs.Fixture, tree: html.HtmlElement, state: str
    ) -> None:
        """Set the kickoff of a fixture by parsing data"""
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
        fix.ordinal = _.toordinal()

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

        if fix.home_score != hsc:
            if fix.home_score is not None:
                evt = EVT.GOAL if hsc > fix.home_score else EVT.VAR_GOAL
                self.bot.dispatch(FXE, evt, fix, home=True)
            fix.home_score = hsc

        if fix.away_score != asc:
            if fix.away_score is not None:
                evt = EVT.GOAL if asc > fix.away_score else EVT.VAR_GOAL
                self.bot.dispatch(FXE, evt, fix, home=False)
            fix.away_score = asc

        if override:
            logger.info("Got Override -> %s", override)
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

    async def parse_games(self) -> list[fs.Fixture]:
        """
        Grab current scores from flashscore using aiohttp
        Returns a list of fixtures that need a full parse
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
            fix = next((i for i in self.bot.games if i.id == match_id), None)
            if fix is None:
                fix = fs.Fixture.from_mobi(tree, match_id)
                if fix is None:
                    continue

                to_fetch.append(fix)
                self.bot.games.add(fix)
                await asyncio.sleep(0)
                old_state = None
            else:
                old_state = fix.state

            # Handling red cards is done relatively simply, do this first.
            self.handle_cards(fix, tree)

            override = self.handle_score(fix, tree)
            # First, we check to see if we need to,
            # and can update the fixture's kickoff
            state = "".join(tree.xpath("./a/@class")).strip()
            if override is None and state in ["sched", "fin"]:
                override = state

            # The time block can be 1 element or 2 elements long.
            # Element 1 is either a time of day HH:MM (e.g. 20:45)
            # or a time of the match (e.g. 41')

            # If Element 2 exists, it is a state override:
            # Cancelled, Postponed, Delayed, or similar.
            time = tree.xpath("./span/text()")

            if fix.kickoff is None:
                self.handle_kickoff(fix, tree, state)

            # What we now need to do, is figure out the "state" of the game.
            # Things may then get … more difficult. Often, the score of a
            # fixture contains extra data.
            # So, we update the match score, and parse additional states
            if override:
                try:
                    fix.time = {
                        "aet": fs.GameState.AFTER_EXTRA_TIME,
                        "fin": fs.GameState.FULL_TIME,
                        "pen": fs.GameState.AFTER_PENS,
                        "sched": fs.GameState.SCHEDULED,
                        "wo": fs.GameState.WALKOVER,
                    }[override.casefold()]
                except KeyError:
                    logger.error("Unhandled override: %s", override)
            else:
                # From the link of the score, we can gather info about the time
                # valid states are: sched, live, fin
                sub_t = time[-1]
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
                    }[str(sub_t)]
                except KeyError:
                    for i in time:
                        if "'" in i or ":" in i:
                            fix.time = i
                            break
                    else:
                        logger.error("Time Not unhandled: %s", time)

            new_state = fix.state
            e_type = fs.get_event_type(new_state, old_state)
            self.bot.dispatch("fixture_event", e_type, fix)
        return to_fetch

    @discord.app_commands.command()
    @discord.app_commands.guilds(250252535699341312)
    async def parse_fixture(self, interaction: Interaction, url: str) -> None:
        """[DEBUG] Force parse a fixture."""
        home = away = fs.Team(None, "debug", None)
        fixture = fs.Fixture(home, away, None, url)

        page = await self.bot.browser.new_page()
        try:
            await self.fetch_fixture(fixture, page, force=True)
        finally:
            await page.close()

        comp = fixture.competition
        if comp is None:
            embed = discord.Embed(title="Parsing Failed")
            embed.colour = discord.Colour.red()
        else:
            embed = discord.Embed(title=comp.title, description="Parsed.")
            embed.colour = discord.Colour.green()
            embed.set_thumbnail(url=comp.logo_url)
        return await interaction.response.send_message(embed=embed)


async def setup(bot: Bot) -> None:
    """Load the score loop cog into the bot"""
    await bot.add_cog(ScoreLoop(bot))
