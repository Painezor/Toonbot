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
from ext.utils import embed_utils

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]

logger = getLogger("ScoreLoop")

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

        need_refresh = await self.fetch_games()
        if need_refresh:
            self.bot.loop.create_task(self.bulk_fixtures(need_refresh))

        # Used for ordinal checking,
        # Discard yesterday's games.
        comps = set(i.competition for i in self.bot.games if i.competition)

        for comp in comps:
            embed = await comp.base_embed()
            embed = embed.copy()

            flt = [i for i in self.bot.games if i.competition == comp]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [i.live_score_text for i in fix]
            table = f"\n[View Table]({comp.table})" if comp.table else ""
            embeds = embed_utils.rows_to_embeds(embed, ls_txt, 50, table)
            comp.score_embeds = embeds

        self.bot.dispatch("scores_ready")

    async def fetch_fixture(
        self, fixture: fs.Fixture, page: Page, force: bool = False
    ) -> None:
        """Fetch all data for a fixture"""
        if fixture.url is None:
            logger.error("url is None on fixture %s", fixture.name)
            return

        await asyncio.sleep(0)
        await page.goto(fixture.url)
        # We are now on the fixture's page. Hooray.
        loc = page.locator(".duelParticipant")
        await loc.wait_for(timeout=2500)
        tree = html.fromstring(await page.content())

        # Handle Teams
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

        await page.goto(url)
        selector = page.locator(".heading")

        try:
            await selector.wait_for()
        except PWTimeout:
            logger.error("Could not find .heading on %s", url)
            return

        tree = html.fromstring(await selector.inner_html())

        mylg = tree.xpath(".//span[contains(@title, 'Add this')]/@class")[0]
        mylg = [i for i in mylg.rsplit(maxsplit=1) if "_" in i][-1]
        comp_id = mylg.rsplit("_", maxsplit=1)[-1]

        src = None

        try:
            # Name Correction
            name_loc = page.locator(".heading__name").first
            logo_url = page.locator(".heading__logo").first

            maybe_name = await name_loc.text_content(timeout=1000)
            if maybe_name is not None:
                name = maybe_name
            src = await logo_url.get_attribute("src", timeout=1000)
        except PWTimeout:
            logger.error("Timed out heading__logo %s", url)
            return

        if (comp := self.bot.get_competition(comp_id)) is None:
            comp = fs.Competition(comp_id, name, country, url)

        if src is not None:
            comp.logo_url = fs.FLASHSCORE + src

        await self.bot.save_competitions([comp])
        fixture.competition = comp

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
    async def fetch_games(self) -> list[fs.Fixture]:
        """
        Grab current scores from flashscore using aiohttp
        Returns a list of fixtures that need a full parse
        """
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                logger.error("%s: %s", resp.status, resp.url)
                return []
            bt_a = bytearray(await resp.text(), encoding="utf-8")
            tree = html.fromstring(bytes(bt_a))

        data = tree.xpath('.//div[@id="score-data"]')[0]
        chunks = etree.tostring(data).decode("utf8").split("<br/>")

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
            cards = tree.xpath("./img/@class")
            if cards := [i.replace("rcard-", "") for i in cards]:
                try:
                    home_cards, away_cards = [int(card) for card in cards]
                except ValueError:
                    if len(tree.xpath("./text()")) == 2:
                        home_cards, away_cards = int(cards[0]), None
                    else:
                        home_cards, away_cards = None, int(cards[0])

                if home_cards is not None:
                    if home_cards != fix.home_cards:
                        if fix.home_cards is not None:
                            if home_cards > fix.home_cards:
                                sub_t = fs.EventType.RED_CARD
                            else:
                                sub_t = fs.EventType.VAR_RED_CARD
                            self.bot.dispatch(FXE, sub_t, fix, home=True)
                        fix.home_cards = home_cards

                if away_cards is not None:
                    if away_cards != fix.away_cards:
                        if fix.away_cards is not None:
                            if away_cards > fix.away_cards:
                                sub_t = fs.EventType.RED_CARD
                            else:
                                sub_t = fs.EventType.VAR_RED_CARD
                            self.bot.dispatch(FXE, sub_t, fix, home=False)
                        fix.away_cards = away_cards

            # The time block can be 1 element or 2 elements long.
            # Element 1 is either a time of day HH:MM (e.g. 20:45)
            # or a time of the match (e.g. 41')

            # If Element 2 exists, it is a declaration:
            # Cancelled, Postponed, Delayed, or similar.
            time = tree.xpath("./span/text()")

            # First, we check to see if we need to,
            # and can update the fixture's kickoff
            state = "".join(tree.xpath("./a/@class")).strip()
            if state in ["sched", "fin"]:
                override = state
            else:
                override = None

            if time and fix.kickoff is None:
                if ":" in time[0]:
                    time = time[0]

                    offset = datetime.timedelta(hours=CURRENT_DATETIME_OFFSET)
                    k_o = datetime.datetime.strptime(time, "%H:%M") - offset

                    # We use the parsed data to create a 'cleaner'
                    # datetime object, with no second or microsecond
                    # And set the day to today.
                    now = discord.utils.utcnow()
                    k_o = now.replace(
                        hour=k_o.hour,
                        minute=k_o.minute,
                        second=0,
                        microsecond=0,
                    )  # Discard micros

                    # If the game appears to be in the past
                    # but has not kicked off yet, add a day.
                    if now.timestamp() > k_o.timestamp() and state == "sched":
                        k_o += datetime.timedelta(days=1)
                    fix.kickoff = k_o
                    fix.ordinal = k_o.toordinal()

            # What we now need to do, is figure out the "state" of the game.
            # Things may then get … more difficult. Often, the score of a
            # fixture contains extra data.
            # So, we update the match score, and parse additional states

            score_line = "".join(tree.xpath(".//a/text()")).split(":")
            h_s, a_s = score_line

            if a_s != "-":
                maybe_ovr = "".join([i for i in a_s if not i.isdigit()])
                if maybe_ovr:
                    override = maybe_ovr

                h_score: int = int(h_s)
                a_score: int = int("".join([i for i in a_s if i.isdigit()]))

                if fix.home_score != h_score:
                    if fix.home_score is not None:
                        if h_score > fix.home_score:
                            evt = fs.EventType.GOAL
                        else:
                            evt = fs.EventType.VAR_GOAL
                        self.bot.dispatch(FXE, evt, fix, home=True)
                    fix.home_score = h_score

                if fix.away_score != a_score:
                    if fix.away_score is not None:
                        if a_score > fix.away_score:
                            evt = fs.EventType.GOAL
                        else:
                            evt = fs.EventType.VAR_GOAL
                        self.bot.dispatch(FXE, evt, fix, home=False)
                    fix.away_score = a_score

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
            elif len(time) == 1:
                # From the link of the score, we can gather info about the time
                # valid states are: sched, live, fin
                sub_t = time[0]
                try:
                    fix.time = {
                        "Break Time": fs.GameState.BREAK_TIME,
                        "Extra Time": fs.GameState.EXTRA_TIME,
                        "Half Time": fs.GameState.HALF_TIME,
                        "Live": fs.GameState.FINAL_RESULT_ONLY,
                        "Penalties": fs.GameState.PENALTIES,
                    }[str(sub_t)]
                except KeyError:
                    if "'" not in sub_t and ":" not in sub_t:
                        logger.error("1 part time unhandled: %s", sub_t)
                    else:
                        fix.time = sub_t
            elif len(time) == 2:
                sub_t = time[-1]

                try:
                    fix.time = {
                        "Abandoned": fs.GameState.ABANDONED,
                        "Cancelled": fs.GameState.CANCELLED,
                        "Delayed": fs.GameState.DELAYED,
                        "Extra Time": fs.GameState.EXTRA_TIME,
                        "Interrupted": fs.GameState.INTERRUPTED,
                        "Postponed": fs.GameState.POSTPONED,
                    }[sub_t]
                except KeyError:
                    logger.error("2 part time unhandled: %s", time)

            if old_state is not None:
                new_state = fix.state
                e_type = fs.get_event_type(new_state, old_state)
                if e_type is not None:
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
