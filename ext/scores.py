"""This Cog Grabs data from Flashscore and outputs the latest scores to user
-configured live score channels"""
from __future__ import annotations

import asyncio
import collections
import importlib
import itertools
import logging
import typing
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from lxml import etree, html
from playwright.async_api import TimeoutError as pw_TimeoutError

import ext.toonbot_utils.flashscore as fs
from ext.fixtures import CompetitionTransformer
from ext.toonbot_utils.gamestate import GameState
from ext.toonbot_utils.matchevents import EventType
from ext.utils import embed_utils, view_utils

if typing.TYPE_CHECKING:
    from core import Bot

logger = logging.getLogger("scores")

# Constants.
NO_GAMES_FOUND = (
    "No games found for your tracked leagues today!\n\nYou can "
    "add more leagues with `/livescores add`"
)

NOPERMS = (
    "\n```yaml\nThis livescores channel will not work currently, "
    "I am missing the following permissions.\n"
)

FXE = "fixture_event"  # Just a string for dispatching events.


class ScoreChannel:
    """A livescore channel object, containing it's properties."""

    bot: typing.ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.messages: list[discord.Message | None] = []
        self.leagues: set[fs.Competition] = set()

    async def get_leagues(self) -> set[fs.Competition]:
        """Fetch target leagues for the ScoreChannel from the database"""
        sql = """SELECT * FROM scores_leagues WHERE channel_id = $1"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)

        for i in records:
            if (comp := self.bot.get_competition(i["url"])) is None:
                league = i["league"].rstrip("/")
                if (comp := self.bot.get_competition(league)) is None:
                    logger.error("Failed fetching comp %s", league)
                    continue

            self.leagues.add(comp)
        return self.leagues

    async def update(self) -> list[discord.Message | None]:
        """Edit a live-score channel to have the latest scores"""
        if self.channel.is_news():
            self.bot.score_channels.remove(self)
            return []

        if not self.leagues:
            await self.get_leagues()

        embeds = []
        for i in self.leagues:
            embeds += i.score_embeds

        if not embeds:
            embed = discord.Embed(title="No Games Found")
            embed.description = NO_GAMES_FOUND
            embeds = [embed]

        # Stack embeds to max size for individual message.
        stacked = embed_utils.stack_embeds(embeds)

        # Zip the lists into tuples to simultaneously iterate
        # Limit to 5 max

        tuples = list(itertools.zip_longest(self.messages, stacked))[:5]

        message: discord.Message | None

        # Zip longest will give (, None) in slot [0] // self.messages
        # if we do not have enough messages for the embeds.

        if not tuples:
            logger.error("Something went wrong in score loop, no tuples.")

        count = 0
        for message, embeds in tuples:
            try:
                # Suppress Message's embeds until they're needed again.
                if message is None and embeds is None:
                    continue

                if message is None:
                    # No message exists in cache,
                    # or we need an additional message.
                    new_msg = await self.channel.send(embeds=embeds)
                    self.messages.append(new_msg)
                    continue

                if embeds is None:
                    if not message.flags.suppress_embeds:
                        new_msg = await message.edit(suppress=True)
                        self.messages[count] = new_msg
                    continue

                cnt = collections.Counter
                new = cnt([i.description for i in embeds])
                old = cnt([i.description for i in message.embeds])
                if old != new:
                    new_msg = await message.edit(embeds=embeds, suppress=False)
                    self.messages[count] = new_msg
            except (discord.Forbidden, discord.NotFound):
                # If we don't have permissions to send Messages in the channel,
                # remove it and stop iterating
                self.bot.score_channels.remove(self)
                return []
            except discord.HTTPException as err:
                logger.error("Scores err: Error %s (%s)", err.status, err.text)
                return []
            finally:
                count += 1
        return self.messages


class ScoresConfig(view_utils.BaseView):
    """Generic Config View"""

    interaction: discord.Interaction[Bot]

    def __init__(
        self, interaction: discord.Interaction[Bot], channel: ScoreChannel
    ) -> None:
        super().__init__(interaction)
        self.chan: ScoreChannel = channel

    async def update(self) -> discord.InteractionMessage:
        """Push the newest version of view to message"""
        self.clear_items()

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "LiveScores config"

        missing = []

        chan = self.chan.channel
        perms = chan.permissions_for(chan.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")
        if not perms.manage_messages:
            missing.append("manage_messages")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        edit = self.interaction.edit_original_response
        if not self.chan.leagues:
            self.add_item(ResetLeagues())
            embed.description = f"{chan.mention} has no tracked leagues."
            return await edit(embed=embed, view=self)

        embed.description = f"Tracked leagues for {chan.mention}\n```yaml\n"
        leagues = sorted(self.chan.leagues, key=lambda x: x.title)
        self.pages = embed_utils.paginate(leagues)
        self.add_page_buttons()

        leagues: list[fs.Competition]
        lg_txt = [i.title for i in self.pages[self.index] if i.url is not None]

        embed.description += "\n".join([str(i) for i in lg_txt])
        embed.description += "```"
        self.add_item(RemoveLeague(leagues, row=1))

        return await edit(embed=embed, view=self)


class ResetLeagues(discord.ui.Button):
    """Button to reset a live score channel back to the default leagues"""

    view: ScoresConfig

    def __init__(self) -> None:
        super().__init__(
            label="Reset to default leagues", style=discord.ButtonStyle.primary
        )

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Click button reset leagues"""

        try:
            await interaction.response.defer()
        except discord.errors.InteractionResponded:
            pass

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM scores_leagues WHERE channel_id = $1"""
                await connection.execute(sql, self.view.chan.channel.id)

                sql = """INSERT INTO scores_leagues (channel_id, url)
                         VALUES ($1, $2)"""
                ch_id = self.view.chan.channel.id
                args = [(ch_id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql, args)

        for league in fs.DEFAULT_LEAGUES:
            if (comp := interaction.client.get_competition(league)) is None:
                logger.error("Failed to get default league %s", league)
                continue
            self.view.chan.leagues.add(comp)

        embed = discord.Embed(title="LiveScores: Tracked Leagues Reset")
        embed.description = self.view.chan.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await self.view.interaction.followup.send(embed=embed)
        return await self.view.update()


class RemoveLeague(discord.ui.Select):
    """Button to bring up the remove leagues dropdown."""

    view: ScoresConfig

    def __init__(self, leagues: list[fs.Competition], row: int = 4) -> None:
        place = "Remove tracked league(s)"
        super().__init__(placeholder=place, row=row, max_values=len(leagues))

        for i in leagues:
            if i.url is None:
                continue

            opt = discord.SelectOption(label=i.title, value=i.url)
            opt.description = i.url
            opt.emoji = i.flag
            self.add_option(label=i.title, description=i.url, value=i.url)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When a league is selected"""
        await interaction.response.defer()

        red = discord.ButtonStyle.red
        intr = self.view.interaction
        view = view_utils.Confirmation(intr, "Remove", "Cancel", red)

        lg_text = "```yaml\n" + "\n".join(sorted(self.values)) + "```"
        ment = self.view.chan.channel.mention

        embed = discord.Embed(title="LiveScores", colour=discord.Colour.red())
        embed.description = f"Remove these leagues from {ment}? {lg_text}"

        edit = self.view.interaction.edit_original_response
        await edit(embed=embed, view=view)
        await view.wait()

        if not view.value:
            return await self.view.update()

        sql = """DELETE from scores_leagues
                 WHERE (channel_id, url) = ($1, $2)"""

        rows = [(self.view.chan.channel.id, x) for x in self.values]

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        for i in self.view.chan.leagues.copy():
            if i.url in self.values:
                self.view.chan.leagues.remove(i)

        ment = self.view.chan.channel.mention
        msg = f"Removed {ment} tracked leagues: \n{lg_text}"
        embed = discord.Embed(description=msg, colour=discord.Colour.red())
        embed.title = "LiveScores"
        embed_utils.user_to_footer(embed, interaction.user)
        await self.view.interaction.followup.send(content=msg)
        return await self.view.update()


class Scores(commands.Cog):
    """Live Scores channel module"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        importlib.reload(fs)
        ScoreChannel.bot = bot

        # Weak refs.
        self.tasks: set[asyncio.Task] = set()

        # Day Change tracking
        self.last_ordinal: int = 0

        # Worker Pool of pages.
        self.score_workers = asyncio.Queue(5)

    async def cog_load(self) -> None:
        """Load our database into the bot"""
        self.bot.scores = self.score_loop.start()

        for _ in range(5):
            page = await self.bot.browser.new_page()
            await self.score_workers.put(page)

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        if self.bot.scores is not None:
            self.bot.scores.cancel()

        for i in self.tasks:
            i.cancel()

        self.bot.score_channels.clear()
        self.bot.games.clear()
        self.bot.teams.clear()
        self.bot.competitions.clear()

        while not self.score_workers.empty():
            page = await self.score_workers.get()
            await page.close()

    # Database load: ScoreChannels
    async def update_cache(self) -> list[ScoreChannel]:
        """Grab the most recent data for all channel configurations"""

        sql = """SELECT * FROM scores_leagues"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        # Generate {channel_id: [league1, league2, league3, …]}
        chans = self.bot.score_channels
        bad = set()

        for i in records:
            channel = self.bot.get_channel(i["channel_id"])

            if not isinstance(channel, discord.TextChannel):
                bad.add(i["channel_id"])
                continue

            if channel.is_news():
                bad.add(i["channel_id"])
                continue

            comp = self.bot.get_competition(str(i["url"]).rstrip("/"))
            if not comp:
                logger.error("Could not get_competition for %s", i)
                continue

            try:
                chn = next(j for j in chans if j.channel.id == i["channel_id"])
            except StopIteration:
                chn = ScoreChannel(channel)
                chans.append(chn)

            chn.leagues.add(comp)

        # Cleanup Old.
        sql = """DELETE FROM scores_channels WHERE channel_id = $1"""
        if chans:
            for i in bad:
                async with self.bot.db.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute(sql, i)
        return chans

    # Core Loop
    @tasks.loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        if not self.bot.score_channels:
            await self.update_cache()

        try:
            self.bot.games = await self.fetch_games()
        except ConnectionError:
            logger.warning("Connection Error fetching games from Flashscore")
            return

        # Used for ordinal checking,
        now = datetime.now(tz=timezone(timedelta(hours=2)))
        ordinal = now.toordinal()

        # Discard yesterday's games.
        games: list[fs.Fixture] = self.bot.games

        if self.last_ordinal != ordinal:
            logger.info("Day changed %s -> %s", self.last_ordinal, ordinal)
            for i in games:
                if i.kickoff is None:
                    continue

                if ordinal > i.kickoff.toordinal():
                    logger.info("Removing old game %s", i.score_line)
                    self.bot.games.remove(i)
            self.last_ordinal = ordinal

        comps = set(i.competition for i in self.bot.games if i.competition)

        for comp in comps:
            embed = await comp.base_embed()
            embed = embed.copy()

            flt = [i for i in self.bot.games if i.competition == comp]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [i.live_score_text for i in fix]

            table = f"\n[View Table]({comp.table})" if comp.table else ""
            rte = embed_utils.rows_to_embeds
            comp.score_embeds = rte(embed, ls_txt, 50, footer=table)

        for channel in self.bot.score_channels.copy():
            await channel.update()

    @score_loop.before_loop
    async def clear_old_scores(self):
        """Purge old messages from livescore channels before starting up."""
        await self.bot.wait_until_ready()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * from fs_competitions"""
                comps = await connection.fetch(sql)
                teams = await connection.fetch("""SELECT * from fs_teams""")

        for i in comps:
            if self.bot.get_competition(i["id"]) is None:
                comp = fs.Competition.from_record(i)
                self.bot.competitions.add(comp)

        for i in teams:
            if self.bot.get_team(i["id"]) is None:
                team = fs.Team.from_record(i)
                self.bot.teams.append(team)

        if not self.bot.score_channels:
            await self.update_cache()

        def is_me(message):
            return message.author.id == self.bot.application_id

        rsn = "Clearing Score Channel"
        for i in self.bot.score_channels:
            try:
                await i.channel.purge(reason=rsn, check=is_me, limit=20)
            except discord.HTTPException:
                pass

    def dispatch_states(self, fix: fs.Fixture, old: GameState) -> None:
        """Dispatch events to the ticker"""
        evt = "fixture_event"
        send_event = self.bot.dispatch

        new = fix.state

        if old == new or old is None:
            return

        if new == GameState.ABANDONED:
            return send_event(evt, EventType.ABANDONED, fix)
        elif new == GameState.AFTER_EXTRA_TIME:
            return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fix)
        elif new == GameState.AFTER_PENS:
            return send_event(evt, EventType.PENALTY_RESULTS, fix)
        elif new == GameState.CANCELLED:
            return send_event(evt, EventType.CANCELLED, fix)
        elif new == GameState.DELAYED:
            return send_event(evt, EventType.DELAYED, fix)
        elif new == GameState.INTERRUPTED:
            return send_event(evt, EventType.INTERRUPTED, fix)
        elif new == GameState.BREAK_TIME:
            if old == GameState.EXTRA_TIME:
                # Break Time = after regular time & before penalties
                return send_event(evt, EventType.EXTRA_TIME_END, fix)
            fix.breaks += 1
            if fix.periods is not None:
                return send_event(evt, EventType.PERIOD_END, fix)
            else:
                return send_event(evt, EventType.NORMAL_TIME_END, fix)
        elif new == GameState.EXTRA_TIME:
            if old == GameState.HALF_TIME:
                return send_event(evt, EventType.HALF_TIME_ET_END, fix)
            return send_event(evt, EventType.EXTRA_TIME_BEGIN, fix)
        elif new == GameState.FULL_TIME:
            if old == GameState.EXTRA_TIME:
                return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fix)
            elif old in [GameState.SCHEDULED, GameState.HALF_TIME]:
                return send_event(evt, EventType.FINAL_RESULT_ONLY, fix)
            return send_event(evt, EventType.FULL_TIME, fix)
        elif new == GameState.HALF_TIME:
            # Half Time is fired at regular Half time & ET Half time.
            if old == GameState.EXTRA_TIME:
                return send_event(evt, EventType.HALF_TIME_ET_BEGIN, fix)
            else:
                return send_event(evt, EventType.HALF_TIME, fix)
        elif new == GameState.LIVE:
            if old in [GameState.SCHEDULED, GameState.DELAYED]:
                return send_event(evt, EventType.KICK_OFF, fix)
            elif old == GameState.INTERRUPTED:
                return send_event(evt, EventType.RESUMED, fix)
            elif old == GameState.HALF_TIME:
                return send_event(evt, EventType.SECOND_HALF_BEGIN, fix)
            elif old == GameState.BREAK_TIME:
                return send_event(evt, EventType.PERIOD_BEGIN, fix)
        elif new == GameState.PENALTIES:
            return send_event(evt, EventType.PENALTIES_BEGIN, fix)
        elif new == GameState.POSTPONED:
            return send_event(evt, EventType.POSTPONED, fix)
        elif new == GameState.STOPPAGE_TIME:
            return

        logger.error("States: %s -> %s %s @ %s", old, new, fix.url, fix.time)

    async def fetch_fixture(self, fixture: fs.Fixture, force: bool = False):
        """Fetch all data for a fixture"""
        if fixture.url is None:
            logger.error("url is None on fixture %s", fixture)
            return

        # DO all set and forget shit.

        # Release so we don't block heartbeat
        await asyncio.sleep(0)
        page = await self.score_workers.get()
        try:
            await page.goto(fixture.url)

            # We are now on the fixture's page. Hooray.
            loc = page.locator(".duelParticipant")
            await loc.wait_for(timeout=2500)
            tree = html.fromstring(await page.content())
        finally:
            await self.score_workers.put(page)

        # Handle Teams
        fixture.home = await fs.Team.from_fixture_html(self.bot, tree)
        fixture.away = await fs.Team.from_fixture_html(
            self.bot, tree, home=False
        )

        div = tree.xpath(".//span[@class='tournamentHeader__country']")

        div = div[0]

        url = fs.FLASHSCORE + "".join(div.xpath(".//@href")).rstrip("/")
        country = "".join(div.xpath("./text()"))
        name = "".join(div.xpath(".//a/text()"))

        if None in [fixture.referee, fixture.stadium]:
            text = tree.xpath('.//div[@class="mi__data"]/span/text()')

            if ref := "".join([i for i in text if "referee" in i.casefold()]):
                fixture.referee = ref.strip().replace("Referee:", "")

            if venue := "".join([i for i in text if "venue" in i.casefold()]):
                fixture.stadium = venue.strip().replace("Venue:", "")

        if country:
            country = country.split(":", maxsplit=1)[0]

        if not force:

            if comp := self.bot.get_competition(url):
                fixture.competition = comp
                return

            elif comp := self.bot.get_competition(f"{country}: {name}"):
                fixture.competition = comp
                return

        fs_id = None

        page = await self.score_workers.get()
        src = None

        try:
            await page.goto(url + "/standings")

            if await page.locator("strong", has_text="Error:").count():
                logger.error("Errored on standings page, using draw fallback")
                await page.goto(url + "/draw")
                await page.wait_for_url("**draw/#/**")
            else:
                await page.wait_for_url("**standings/#/**")

            if "#" in page.url:
                fs_id = page.url.split("/")[-1]

                if fs_id in ["live", "table", "overall"]:
                    logger.info("Bad ID from %s", page.url)

            else:
                t_bar = page.locator(".tabs__tab")
                logger.info("Current page url %s", page.url)
                logger.info("found %s matching tabs", await t_bar.count())
                for elem in await t_bar.all():
                    sublink = await elem.get_attribute("href")
                    if sublink is not None:
                        fs_id = sublink.split("/")[1]

                        if fs_id in ["football", "live", "overall"]:
                            logger.error("bad id from %s", sublink)
                        else:
                            logger.info("++ id %s from %s", fs_id, sublink)
                            break

            # Name Correction
            name_loc = page.locator(".heading__name").first
            logo_url = page.locator(".heading__logo").first

            maybe_name = await name_loc.text_content(timeout=100)
            if maybe_name is not None:
                name = maybe_name
            src = await logo_url.get_attribute("src", timeout=100)
        except pw_TimeoutError:
            logger.error("Timed out heading__logo %s", url)
        finally:
            await self.score_workers.put(page)

        comp = fs.Competition(fs_id, name, country, url)
        if src is not None:
            comp.logo_url = fs.FLASHSCORE + src

        if fs_id is not None and fs_id not in ["football", "overall"]:
            await fs.save_comp(self.bot, comp)
        else:
            self.bot.competitions.add(comp)
        fixture.competition = comp

    # Core Loop
    async def fetch_games(self) -> list[fs.Fixture]:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                reason = resp.reason
                status = resp.status
                logger.error("%s %s during score loop", status, reason)
                return []
            bt_a = bytearray(await resp.text(), encoding="utf-8")
            tree = html.fromstring(bytes(bt_a))

        data = tree.xpath('.//div[@id="score-data"]')[0]
        chunks = etree.tostring(data).decode("utf8").split("<br/>")

        for game in chunks:
            try:
                tree = html.fromstring(game)
                # Document is empty because of trailing </div>
            except etree.ParserError:
                continue

            link = "".join(tree.xpath(".//a/@href"))
            try:
                match_id = link.split("/")[-2]
                url = fs.FLASHSCORE + link
            except IndexError:
                # Awaiting.
                continue

            # Set & forget: Competition, Teams
            if (fix := self.bot.get_fixture(match_id)) is None:
                # These values never need to be updated.
                xpath = "./text()"
                teams = [i.strip() for i in tree.xpath(xpath) if i.strip()]

                if teams[0].startswith("updates"):
                    # Awaiting Updates.
                    teams[0] = teams[0].replace("updates", "")

                if len(teams) == 1:
                    teams = teams[0].split(" - ")

                if len(teams) == 2:
                    home_name, away_name = teams

                elif len(teams) == 3:
                    if teams[1] == "La Duchere":
                        home_name = f"{teams[0]} {teams[1]}"
                        away_name = teams[2]
                    elif teams[2] == "La Duchere":
                        home_name = teams[0]
                        away_name = f"{teams[1]} {teams[2]}"

                    elif teams[0] == "Banik Most":
                        home_name = f"{teams[0]} {teams[1]}"
                        away_name = teams[2]
                    elif teams[1] == "Banik Most":
                        home_name = teams[0]
                        away_name = f"{teams[1]} {teams[2]}"
                    else:
                        logger.error("Fetch games found %s", teams)
                        continue
                else:
                    logger.error("Fetch games found teams %s", teams)
                    continue

                home = fs.Team(None, home_name, None)
                away = fs.Team(None, away_name, None)
                fix = fs.Fixture(home, away, match_id, url)

                try:
                    crt = self.bot.loop.create_task
                    task = crt(
                        self.fetch_fixture(fix), name=f"fetchdata {fix.id}"
                    )
                    task.add_done_callback(self.tasks.discard)
                except pw_TimeoutError:
                    logger.error("Timeout Error on %s", fix.url)
                    continue  # If a fucky happens.

                self.bot.games.append(fix)
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
                                sub_t = EventType.RED_CARD
                            else:
                                sub_t = EventType.VAR_RED_CARD
                            self.bot.dispatch(FXE, sub_t, fix, home=True)
                        fix.home_cards = home_cards

                if away_cards is not None:
                    if away_cards != fix.away_cards:
                        if fix.away_cards is not None:
                            if away_cards > fix.away_cards:
                                sub_t = EventType.RED_CARD
                            else:
                                sub_t = EventType.VAR_RED_CARD
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
                    k_o = datetime.strptime(time, "%H:%M") - timedelta(hours=2)

                    # We use the parsed data to create a 'cleaner'
                    # datetime object, with no second or microsecond
                    # And set the day to today.
                    now = datetime.now(tz=timezone.utc)
                    k_o = now.replace(
                        hour=k_o.hour,
                        minute=k_o.minute,
                        second=0,
                        microsecond=0,
                    )  # Discard micros

                    # If the game appears to be in the past
                    # but has not kicked off yet, add a day.
                    if now.timestamp() > k_o.timestamp() and state == "sched":
                        k_o += timedelta(days=1)
                    fix.kickoff = k_o
                    fix.ordinal = k_o.toordinal()

            # What we now need to do, is figure out the "state" of the game.
            # Things may then get … more difficult. Often, the score of a
            # fixture contains extra data.
            # So, we update the match score, and parse additional states

            score_line = "".join(tree.xpath(".//a/text()")).split(":")
            h_score, a_score = score_line

            if a_score != "-":
                maybe_ovr = "".join([i for i in a_score if not i.isdigit()])
                if maybe_ovr:
                    override = maybe_ovr

                h_score = int(h_score)
                a_score = int("".join([i for i in a_score if i.isdigit()]))

                if fix.home_score != h_score:
                    if fix.home_score is not None:
                        if h_score > fix.home_score:
                            evt = EventType.GOAL
                        else:
                            evt = EventType.VAR_GOAL
                        self.bot.dispatch(FXE, evt, fix, home=True)
                    fix.home_score = h_score

                if fix.away_score != a_score:
                    if fix.away_score is not None:
                        if a_score > fix.away_score:
                            evt = EventType.GOAL
                        else:
                            evt = EventType.VAR_GOAL
                        self.bot.dispatch(FXE, evt, fix, home=False)
                    fix.away_score = a_score

            if override:
                try:
                    fix.time = {
                        "aet": GameState.AFTER_EXTRA_TIME,
                        "fin": GameState.FULL_TIME,
                        "pen": GameState.AFTER_PENS,
                        "sched": GameState.SCHEDULED,
                        "wo": GameState.WALKOVER,
                    }[override.casefold()]
                except KeyError:
                    logger.error("Unhandled override: %s", override)
            elif len(time) == 1:
                # From the link of the score, we can gather info about the time
                # valid states are: sched, live, fin
                sub_t = time[0]
                try:
                    fix.time = {
                        "Break Time": GameState.BREAK_TIME,
                        "Extra Time": GameState.EXTRA_TIME,
                        "Half Time": GameState.HALF_TIME,
                        "Live": GameState.FINAL_RESULT_ONLY,
                        "Penalties": GameState.PENALTIES,
                    }[sub_t]
                except KeyError:
                    if "'" not in sub_t and ":" not in sub_t:
                        logger.error("1 part time unhandled: %s", sub_t)
                    else:
                        fix.time = sub_t
            elif len(time) == 2:
                sub_t = time[-1]

                try:
                    fix.time = {
                        "Abandoned": GameState.ABANDONED,
                        "Cancelled": GameState.CANCELLED,
                        "Delayed": GameState.DELAYED,
                        "Extra Time": GameState.EXTRA_TIME,
                        "Interrupted": GameState.INTERRUPTED,
                        "Postponed": GameState.POSTPONED,
                    }[sub_t]
                except KeyError:
                    logger.error("2 part time unhandled: %s", time)

            if old_state is not None:
                self.dispatch_states(fix, old_state)
        return self.bot.games

    livescores = discord.app_commands.Group(
        guild_only=True,
        name="livescores",
        description="Create & manage livescores channels",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @discord.app_commands.command()
    @discord.app_commands.guilds(250252535699341312)
    async def parse_fixture(
        self, interaction: discord.Interaction[Bot], url: str
    ) -> discord.InteractionMessage:
        """[DEBUG] Force parse a fixture."""
        await interaction.response.defer(thinking=True)

        home = away = fs.Team(None, "debug", None)
        fixture = fs.Fixture(home, away, None, url)
        await self.fetch_fixture(fixture, force=True)

        edit = interaction.edit_original_response
        comp = fixture.competition
        if comp is None:
            embed = discord.Embed(title="Parsing Failed")
            embed.colour = discord.Colour.red()
        else:
            embed = discord.Embed(title=comp.title, description="Parsed.")
            embed.colour = discord.Colour.green()
            embed.set_thumbnail(url=comp.logo_url)
        return await edit(embed=embed)

    @livescores.command()
    @discord.app_commands.describe(channel="Target Channel")
    async def manage(
        self,
        interaction: discord.Interaction[Bot],
        channel: typing.Optional[discord.TextChannel],
    ) -> discord.InteractionMessage:
        """View or Delete tracked leagues from a live-scores channel."""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                row = await connection.fetchrow(sql, channel.id)

        if not row:
            err = f"{channel.mention} is not a live-scores channel."
            return await self.bot.error(interaction, err)

        chans = self.bot.score_channels
        try:
            chan = next(i for i in chans if i.channel.id == channel.id)
        except StopIteration:
            chan = ScoreChannel(channel)
            self.bot.score_channels.append(chan)

        return await ScoresConfig(interaction, chan).update()

    @livescores.command()
    @discord.app_commands.describe(name="Enter a name for the channel")
    async def create(
        self, interaction: discord.Interaction[Bot], name: str = "⚽live-scores"
    ) -> discord.InteractionMessage:
        """Create a live-scores channel for your server."""
        await interaction.response.defer(thinking=True)

        assert interaction.guild is not None
        # command is flagged as guild_only.

        user = interaction.user
        guild = interaction.guild

        reason = f"{user} ({user.id}) created a live-scores channel."
        topic = "Live Scores from around the world"

        try:
            channel = await guild.create_text_channel(
                name, reason=reason, topic=topic
            )
        except discord.Forbidden:
            err = "I need manage_channels permissions to make a channel."
            return await self.bot.error(interaction, err)

        dow = discord.PermissionOverwrite
        ow_ = {
            guild.default_role: dow(send_messages=False),
            guild.me: dow(send_messages=True),
        }

        try:
            channel = await channel.edit(overwrites=ow_)
        except discord.Forbidden:
            pass

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                    ON CONFLICT DO NOTHING"""
                await connection.execute(sql, interaction.guild.id)
                sql = """INSERT INTO scores_channels (guild_id, channel_id)
                    VALUES ($1, $2)"""
                await connection.execute(sql, channel.guild.id, channel.id)

        self.bot.score_channels.append(chan := ScoreChannel(channel))

        try:
            await chan.channel.send(
                f"{interaction.user.mention} Welcome to your new livescores "
                "channel.\n Use `/livescores add_league` to add new leagues,"
                " and `/livescores manage` to remove them"
            )
            msg = f"{channel.mention} created successfully."
        except discord.Forbidden:
            msg = f"{channel.mention} created, but I need send_messages perms."
        await interaction.followup.send(msg)

        reset = ScoresConfig(interaction, chan).add_item(ResetLeagues())
        return await reset.children[0].callback(interaction)

    @livescores.command()
    @discord.app_commands.describe(
        competition="league name to search for or direct flashscore link",
        channel="Target Channel",
    )
    async def add_league(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
        channel: typing.Optional[discord.TextChannel],
    ) -> discord.InteractionMessage:
        """Add a league to an existing live-scores channel"""

        if competition.title == "WORLD: Club Friendly":
            err = "You can't add club friendlies as a competition, sorry."
            raise ValueError(err)

        if competition.url is None:
            raise LookupError(
                f"{competition} url is None",
            )

        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        score_chans = self.bot.score_channels
        try:
            chan = next(i for i in score_chans if i.channel.id == channel.id)
        except StopIteration:
            embed = discord.Embed(colour=discord.Colour.red())
            ment = channel.mention
            embed.description = f"{ment} is not a live-scores channel."
            return await interaction.edit_original_response(embed=embed)

        sql = """INSERT INTO scores_leagues (channel_id, url, league)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""

        url = competition.url
        title = competition.title
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, chan.channel.id, url, title)

        chan.leagues.add(competition)
        embed = discord.Embed(title="LiveScores: Tracked League Added")
        embed.description = f"{chan.channel.mention}\n\n{competition.url}"
        embed_utils.user_to_footer(embed, interaction.user)
        return await interaction.edit_original_response(embed=embed)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Remove all of a channel's stored data upon deletion"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM scores_channels WHERE channel_id = $1"""
                await connection.execute(sql, channel.id)

        for i in self.bot.score_channels.copy():
            if channel.id == i.channel.id:
                self.bot.score_channels.remove(i)


async def setup(bot: Bot):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
