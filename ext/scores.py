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


# Do up to N fixtures at a time
semaphore = asyncio.Semaphore(2)


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

        async with self.bot.db.acquire(timeout=60) as c:
            async with c.transaction():
                records = await c.fetch(sql, self.channel.id)

        for r in records:
            if (comp := self.bot.get_competition(r["url"])) is None:
                if (comp := self.bot.get_competition(r["league"])) is None:
                    logger.error("Failed fetching comp %s", r)
                    continue

            self.leagues.add(comp)
        return self.leagues

    async def update(self) -> list[discord.Message | None]:
        """Edit a live-score channel to have the latest scores"""
        if self.channel.is_news():
            return []

        if not self.leagues:
            await self.get_leagues()

        embeds = []
        for i in self.leagues:
            embeds += i.score_embeds

        if not embeds:
            e = discord.Embed(title="No Games Found")
            e.description = NO_GAMES_FOUND
            embeds = [e]

        # Stack embeds to max size for individual message.
        stacked = embed_utils.stack_embeds(embeds)

        # Zip the lists into tuples to simultaneously iterate
        # Limit to 5 max

        tuples = list(itertools.zip_longest(self.messages, stacked))[:5]

        message: discord.Message | None

        # Zip longest will give (, None) in slot [0] // self.messages
        # if we do not have enough messages for the embeds.
        count = 0
        for message, embeds in tuples:
            try:
                # Suppress Message's embeds until they're needed again.
                if message is None and embeds is None:
                    continue

                if message is None:
                    # No message exists in cache,
                    # or we need an additional message.
                    m = await self.channel.send(embeds=embeds)
                    self.messages.append(m)
                    continue
            except discord.Forbidden:
                # If we don't have permissions to send Messages in the channel,
                # remove it and stop iterating.
                self.bot.score_channels.remove(self)
                return []
            except discord.HTTPException:
                continue

            try:
                if embeds is None:
                    if not message.flags.suppress_embeds:
                        m = await message.edit(suppress=True)
                        self.messages[count] = m
                    continue

                cnt = collections.Counter
                new = cnt([i.description for i in embeds])
                old = cnt([i.description for i in message.embeds])
                if not old == new:
                    m = await message.edit(embeds=embeds, suppress=False)
                    self.messages[count] = m
            except discord.NotFound:
                self.bot.score_channels.remove(self)
                return []
            except discord.HTTPException:
                continue
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
        self.sc: ScoreChannel = channel

    async def update(self) -> discord.InteractionMessage:
        """Push the newest version of view to message"""
        self.clear_items()

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "LiveScores config"

        missing = []

        ch = self.sc.channel
        perms = ch.permissions_for(ch.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")
        if not perms.manage_messages:
            missing.append("manage_messages")

        if missing:
            v = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=v)

        edit = self.interaction.edit_original_response
        if not self.sc.leagues:
            self.add_item(ResetLeagues())
            embed.description = f"{ch.mention} has no tracked leagues."
            return await edit(embed=embed, view=self)

        embed.description = f"Tracked leagues for {ch.mention}\n```yaml\n"
        leagues = sorted(self.sc.leagues, key=lambda x: x.title)
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
                await connection.execute(sql, self.view.sc.channel.id)

                sql = """INSERT INTO scores_leagues (channel_id, url)
                         VALUES ($1, $2)"""
                r = [(self.view.sc.channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql, r)

        for x in fs.DEFAULT_LEAGUES:
            if (comp := interaction.client.get_competition(x)) is None:
                continue
            self.view.sc.leagues.add(comp)

        e = discord.Embed(title="LiveScores: Tracked Leagues Reset")
        e.description = self.view.sc.channel.mention
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        await self.view.interaction.followup.send(embed=e)
        return await self.view.update()


class RemoveLeague(discord.ui.Select):
    """Button to bring up the remove leagues dropdown."""

    view: ScoresConfig

    def __init__(self, leagues: list[fs.Competition], row: int = 4) -> None:
        ph = "Remove tracked league(s)"
        super().__init__(placeholder=ph, row=row, max_values=len(leagues))

        for lg in leagues:
            if lg.url is None:
                continue

            opt = discord.SelectOption(label=lg.title, value=lg.url)
            opt.description = lg.url
            opt.emoji = lg.flag
            self.add_option(label=lg.title, description=lg.url, value=lg.url)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When a league is selected"""
        await interaction.response.defer()

        red = discord.ButtonStyle.red
        intr = self.view.interaction
        view = view_utils.Confirmation(intr, "Remove", "Cancel", red)

        lg_text = "```yaml\n" + "\n".join(sorted(self.values)) + "```"
        c = self.view.sc.channel.mention

        e = discord.Embed(title="LiveScores", colour=discord.Colour.red())
        e.description = f"Remove these leagues from {c}? {lg_text}"
        await self.view.interaction.edit_original_response(embed=e, view=view)
        await view.wait()

        if not view.value:
            return await self.view.update()

        sql = """DELETE from scores_leagues
                 WHERE (channel_id, url) = ($1, $2)"""

        rows = [(self.view.sc.channel.id, x) for x in self.values]

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        for i in self.view.sc.leagues.copy():
            if i.url in self.values:
                self.view.sc.leagues.remove(i)

        m = self.view.sc.channel.mention
        msg = f"Removed {m} tracked leagues: \n{lg_text}"
        e = discord.Embed(description=msg, colour=discord.Colour.red())
        e.title = "LiveScores"
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
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

    async def cog_load(self) -> None:
        """Load our database into the bot"""
        self.bot.scores = self.score_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        if self.bot.scores is not None:
            self.bot.scores.cancel()

        [i.cancel() for i in self.tasks]

        self.bot.score_channels.clear()
        self.bot.games.clear()
        self.bot.teams.clear()
        self.bot.competitions.clear()

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

        for r in records:
            channel = self.bot.get_channel(r["channel_id"])

            if not isinstance(channel, discord.TextChannel):
                bad.add(r["channel_id"])
                continue

            if channel.is_news():
                bad.add(r["channel_id"])
                continue

            comp = self.bot.get_competition(str(r["url"]).rstrip("/"))
            if not comp:
                logger.error("Could not get_competition for %s", r)
                continue

            try:
                sc = next(i for i in chans if i.channel.id == r["channel_id"])
            except StopIteration:
                sc = ScoreChannel(channel)
                chans.append(sc)

            sc.leagues.add(comp)

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
        now = datetime.now(tz=timezone(timedelta(hours=1)))
        ordinal = now.toordinal()

        # Discard yesterday's games.
        self.bot.games = [g for g in self.bot.games if g.active(ordinal)]

        comps = set(i.competition for i in self.bot.games if i.competition)

        for comp in comps:
            e = await comp.base_embed()
            e = e.copy()

            flt = [i for i in self.bot.games if i.competition == comp]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [i.live_score_text for i in fix]

            table = f"\n[View Table]({comp.table})" if comp.table else ""
            rte = embed_utils.rows_to_embeds
            comp.score_embeds = rte(e, ls_txt, 50, footer=table)

        logger.info("Made score embeds for %s comps", len(comps))

        for sc in self.bot.score_channels.copy():
            await sc.update()

    @score_loop.before_loop
    async def clear_old_scores(self):
        """Purge old messages from livescore channels before starting up."""
        await self.bot.wait_until_ready()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * from fs_competitions"""
                comps = await connection.fetch(sql)
                teams = await connection.fetch("""SELECT * from fs_teams""")

        for c in comps:
            if self.bot.get_competition(c["id"]) is None:
                cm = fs.Competition(c["id"], c["name"], c["country"], c["url"])
                cm.logo_url = c["logo_url"]
                self.bot.competitions.add(cm)

        for t in teams:
            if self.bot.get_team(t["id"]) is None:
                team = fs.Team(t["id"], t["name"], t["url"])
                team.logo_url = t["logo_url"]
                self.bot.teams.append(team)

        if not self.bot.score_channels:
            await self.update_cache()

        def bot(m):
            return m.author.id == self.bot.application_id

        rsn = "Clearing Score Channel"
        for x in self.bot.score_channels:
            try:
                await x.channel.purge(reason=rsn, check=bot, limit=20)
            except discord.HTTPException:
                pass

    def dispatch_states(self, fx: fs.Fixture, old: GameState) -> None:
        """Dispatch events to the ticker"""
        evt = "fixture_event"
        send_event = self.bot.dispatch

        new = fx.state

        if old == new or old is None:
            return

        if new == GameState.ABANDONED:
            return send_event(evt, EventType.ABANDONED, fx)
        elif new == GameState.AFTER_EXTRA_TIME:
            return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fx)
        elif new == GameState.AFTER_PENS:
            return send_event(evt, EventType.PENALTY_RESULTS, fx)
        elif new == GameState.CANCELLED:
            return send_event(evt, EventType.CANCELLED, fx)
        elif new == GameState.DELAYED:
            return send_event(evt, EventType.DELAYED, fx)
        elif new == GameState.INTERRUPTED:
            return send_event(evt, EventType.INTERRUPTED, fx)
        match new:
            case GameState.BREAK_TIME:
                match old:
                    # Break Time = after regular time & before penalties
                    case GameState.EXTRA_TIME:
                        return send_event(evt, EventType.EXTRA_TIME_END, fx)
                    case _:
                        fx.breaks += 1
                        if fx.periods is not None:
                            event = EventType.PERIOD_END
                        else:
                            event = EventType.NORMAL_TIME_END
                        return send_event(evt, event, fx)

            case GameState.EXTRA_TIME:
                match old:
                    case GameState.HALF_TIME:
                        return send_event(evt, EventType.HALF_TIME_ET_END, fx)
                    case _:
                        return send_event(evt, EventType.EXTRA_TIME_BEGIN, fx)
            case GameState.FULL_TIME:
                match old:
                    case GameState.EXTRA_TIME:
                        return send_event(
                            evt,
                            EventType.SCORE_AFTER_EXTRA_TIME,
                            fx,
                        )
                    case GameState.SCHEDULED | GameState.HALF_TIME:
                        return send_event(evt, EventType.FINAL_RESULT_ONLY, fx)
                    case _:
                        return send_event(evt, EventType.FULL_TIME, fx)
            case GameState.HALF_TIME:
                # Half Time is fired at regular Half time & ET Half time.
                if old == GameState.EXTRA_TIME:
                    return send_event(evt, EventType.HALF_TIME_ET_BEGIN, fx)
                else:
                    return send_event(evt, EventType.HALF_TIME, fx)
            case GameState.LIVE:
                match old:
                    case GameState.SCHEDULED | GameState.DELAYED:
                        # Match has resumed
                        return send_event(evt, EventType.KICK_OFF, fx)
                    case GameState.INTERRUPTED:
                        return send_event(evt, EventType.RESUMED, fx)
                    case GameState.HALF_TIME:
                        return send_event(evt, EventType.SECOND_HALF_BEGIN, fx)
                    case GameState.BREAK_TIME:
                        return send_event(evt, EventType.PERIOD_BEGIN, fx)
            case GameState.PENALTIES:
                return send_event(evt, EventType.PENALTIES_BEGIN, fx)
            case GameState.POSTPONED:
                return send_event(evt, EventType.POSTPONED, fx)
            case GameState.STOPPAGE_TIME:
                return

        logger.error(f"Handle State: {old} -> {new} {fx.url} @ {fx.time}")

    async def fetch_data(self, fixture: fs.Fixture):
        if fixture.url is None:
            logger.error("url is None on fixture %s", fixture)
            return

        # DO all set and forget shit.

        async with semaphore:
            # Release so we don't block heartbeat
            await asyncio.sleep(0)
            page = await self.bot.browser.new_page()
            try:
                await page.goto(fixture.url)

                # We are now on the fixture's page. Hooray.
                loc = page.locator(".duelParticipant")
                await loc.wait_for(timeout=2500)
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

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
            country = country.split(":")[0]

        if comp := self.bot.get_competition(url):
            fixture.competition = comp
            return

        elif comp := self.bot.get_competition(f"{country.upper()}: {name}"):
            fixture.competition = comp
            return

        fs_id = None
        async with semaphore:
            page = await self.bot.browser.new_page()
            src = None
            await page.goto(url + "/standings")
            try:
                bar = page.locator("text=Overall").last
                logger.info("Current Page URL is %s", page.url)
                await bar.wait_for(timeout=3000)
            except pw_TimeoutError:
                await page.goto(url + "/draw")
                logger.info("Current Page URL is %s", page.url)
                bar = page.locator("text=Draw").last
                await bar.wait_for(timeout=3000)

            try:
                logger.info("found %s matching elements", await bar.count())
                sublink = await bar.get_attribute("href")
                logger.info("href is %s", sublink)
                if sublink is not None:
                    fs_id = sublink.split("/")[1]

                    if fs_id == "football":
                        logger.error("bad comp_id %s from %s", fs_id, sublink)
                    else:
                        logger.info("Good comp_id %s from %s", fs_id, sublink)

                    # Name Correction
                    name_loc = page.locator(".heading__name").first
                    logo_url = page.locator(".heading__logo").first

                    maybe_name = await name_loc.text_content()
                    if maybe_name is not None:
                        name = maybe_name
                    src = await logo_url.get_attribute("src", timeout=1000)
            except pw_TimeoutError:
                logger.error("Timed out heading__logo %s", url)
            finally:
                await page.close()

        logger.info("cant get_competition %s", url)
        comp = fs.Competition(fs_id, name, country, url)
        if src is not None:
            comp.logo_url = fs.FLASHSCORE + src

        if fs_id is not None and fs_id != "football":
            await fs.save_comp(self.bot, comp)
        else:
            self.bot.competitions.add(comp)
        fixture.competition = comp

    # Core Loop
    async def fetch_games(self) -> list[fs.Fixture]:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                rs = resp.reason
                st = resp.status
                logger.error("%s %s during score loop", st, rs)
                return []
            bt = bytearray(await resp.text(), encoding="utf-8")
            tree = html.fromstring(bytes(bt))

        data = tree.xpath('.//div[@id="score-data"]')[0]
        chunks = etree.tostring(data).decode("utf8").split("<br/>")

        for game in chunks:
            try:
                tree = html.fromstring(game)
                # Document is empty because of trailing </div>
            except etree.ParserError:
                continue

            # Check if the chunk to be parsed has is a header.
            # If it is, we need to create a new competition object.
            if comp_tag := tree.xpath(".//h4/text()"):
                logger.info("comp tag is %s", comp_tag)

            link = "".join(tree.xpath(".//a/@href"))
            match_id = link.split("/")[-2]
            url = fs.FLASHSCORE + link

            # Set & forget: Competition, Teams
            if (fx := self.bot.get_fixture(match_id)) is None:
                # These values never need to be updated.
                xp = "./text()"
                teams = [i.strip() for i in tree.xpath(xp) if i.strip()]

                if teams[0].startswith("updates"):  # ???
                    teams[0] = teams[0].replace("updates", "")

                if len(teams) == 1:
                    teams = teams[0].split(" - ")

                match len(teams):
                    case 2:
                        home_name, away_name = teams
                    case 3:
                        match teams:
                            case _, "La Duchere", _:
                                home_name = f"{teams[0]} {teams[1]}"
                                away_name = teams[2]
                            case _, _, "La Duchere":
                                home_name = teams[0]
                                away_name = f"{teams[1]} {teams[2]}"
                            case "Banik Most", _, _:
                                home_name = f"{teams[0]} {teams[1]}"
                                away_name = teams[2]
                            case _, "Banik Most", _:
                                home_name = teams[0]
                                away_name = f"{teams[1]} {teams[2]}"
                            case _:
                                logger.error("Fetch games found %s", teams)
                                continue
                    case _:
                        logger.error("Fetch games found teams %s", teams)
                        continue

                home = fs.Team(None, home_name, None)
                away = fs.Team(None, away_name, None)
                fx = fs.Fixture(home, away, match_id, url)
                self.bot.games.append(fx)

                await self.bot.loop.create_task(self.fetch_data(fx))
                await asyncio.sleep(0)

                old_state = None
            else:
                old_state = fx.state

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
                    if home_cards != fx.home_cards:
                        if fx.home_cards is not None:
                            if home_cards > fx.home_cards:
                                t = EventType.RED_CARD
                            else:
                                t = EventType.VAR_RED_CARD
                            self.bot.dispatch(FXE, t, fx, home=True)
                        fx.home_cards = home_cards

                if away_cards is not None:
                    if away_cards != fx.away_cards:
                        if fx.away_cards is not None:
                            if away_cards > fx.away_cards:
                                t = EventType.RED_CARD
                            else:
                                t = EventType.VAR_RED_CARD
                            self.bot.dispatch(FXE, t, fx, home=False)
                        fx.away_cards = away_cards

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

            if time and fx.kickoff is None:
                if ":" in time[0]:
                    time = time[0]
                    ko = datetime.strptime(time, "%H:%M") - timedelta(hours=1)

                    # We use the parsed data to create a 'cleaner'
                    # datetime object, with no second or microsecond
                    # And set the day to today.
                    now = datetime.now(tz=timezone.utc)
                    ko = now.replace(
                        hour=ko.hour, minute=ko.minute, second=0, microsecond=0
                    )  # Discard micros

                    # If the game appears to be in the past
                    # but has not kicked off yet, add a day.
                    if now.timestamp() > ko.timestamp() and state == "sched":
                        ko += timedelta(days=1)
                    fx.kickoff = ko
                    fx.ordinal = ko.toordinal()

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

                if fx.home_score != h_score:
                    if fx.home_score is not None:
                        if h_score > fx.home_score:
                            ev = EventType.GOAL
                        else:
                            ev = EventType.VAR_GOAL
                        self.bot.dispatch(FXE, ev, fx, home=True)
                    fx.home_score = h_score

                if fx.away_score != a_score:
                    if fx.away_score is not None:
                        if a_score > fx.away_score:
                            ev = EventType.GOAL
                        else:
                            ev = EventType.VAR_GOAL
                        self.bot.dispatch(FXE, ev, fx, home=False)
                    fx.away_score = a_score

            if override:
                try:
                    fx.time = {
                        "aet": GameState.AFTER_EXTRA_TIME,
                        "fin": GameState.FULL_TIME,
                        "pen": GameState.AFTER_PENS,
                        "sched": GameState.SCHEDULED,
                        "wo": GameState.WALKOVER,
                    }[override.casefold()]
                except KeyError:
                    logger.error(f"Unhandled override: {override}")
            elif len(time) == 1:
                # From the link of the score, we can gather info about the time
                # valid states are: sched, live, fin
                t = time[0]
                if t == "Live":
                    fx.time = GameState.FINAL_RESULT_ONLY
                elif t == "Half Time":
                    fx.time = GameState.HALF_TIME
                elif t == "Break Time":
                    fx.time = GameState.BREAK_TIME
                elif t == "Extra Time":
                    fx.time = GameState.EXTRA_TIME
                elif t == "Penalties":
                    fx.time = GameState.PENALTIES
                else:
                    if "'" not in t and ":" not in t:
                        logger.error("1 part time %s", t)
                    else:
                        fx.time = t
            elif len(time) == 2:
                t = time[-1]
                if t == "Cancelled":
                    fx.time = GameState.CANCELLED
                elif t == "Postponed":
                    fx.time = GameState.POSTPONED
                elif t == "Delayed":
                    fx.time = GameState.DELAYED
                elif t == "Interrupted":
                    fx.time = GameState.INTERRUPTED
                elif t == "Abandoned":
                    fx.time = GameState.ABANDONED
                elif t == "Extra Time":
                    fx.time = GameState.EXTRA_TIME
                else:
                    logger.error(f"2 part time {time}")

            if old_state is not None:
                self.dispatch_states(fx, old_state)
        return self.bot.games

    livescores = discord.app_commands.Group(
        guild_only=True,
        name="livescores",
        description="Create & manage livescores channels",
        default_permissions=discord.Permissions(manage_channels=True),
    )

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
            sc = next(i for i in chans if i.channel.id == channel.id)
        except StopIteration:
            sc = ScoreChannel(channel)
            self.bot.score_channels.append(sc)

        return await ScoresConfig(interaction, sc).update()

    @livescores.command()
    @discord.app_commands.describe(name="Enter a name for the channel")
    async def create(
        self, interaction: discord.Interaction[Bot], name: str = "⚽live-scores"
    ) -> discord.InteractionMessage:
        """Create a live-scores channel for your server."""
        await interaction.response.defer(thinking=True)

        assert interaction.guild is not None
        # command is flagged as guild_only.

        u = interaction.user
        guild = interaction.guild

        reason = f"{u} ({u.id}) created a live-scores channel."
        topic = "Live Scores from around the world"

        try:
            channel = await guild.create_text_channel(
                name, reason=reason, topic=topic
            )
        except discord.Forbidden:
            err = "I need manage_channels permissions to make a channel."
            return await self.bot.error(interaction, err)

        ow_ = discord.PermissionOverwrite
        ow = {
            guild.default_role: ow_(send_messages=False),
            guild.me: ow_(send_messages=True),
        }

        try:
            channel = await channel.edit(overwrites=ow)
        except discord.Forbidden:
            pass

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                    ON CONFLICT DO NOTHING"""
                await connection.execute(q, interaction.guild.id)
                q = """INSERT INTO scores_channels (guild_id, channel_id)
                    VALUES ($1, $2)"""
                await connection.execute(q, channel.guild.id, channel.id)

        self.bot.score_channels.append(sc := ScoreChannel(channel))

        try:
            await sc.channel.send(
                f"{interaction.user.mention} Welcome to your new livescores "
                "channel.\n Use `/livescores add_league` to add new leagues,"
                " and `/livescores manage` to remove them"
            )
            msg = f"{channel.mention} created successfully."
        except discord.Forbidden:
            msg = f"{channel.mention} created, but I need send_messages perms."
        await interaction.followup.send(msg)

        reset = ScoresConfig(interaction, sc).add_item(ResetLeagues())
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
            raise LookupError("%s url is None", competition)

        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        chn = self.bot.score_channels
        try:
            sc = next(i for i in chn if i.channel.id == channel.id)
        except StopIteration:
            err = f"{channel.mention} is not a live-scores channel."
            raise ValueError(err)

        sql = """INSERT INTO scores_leagues (channel_id, url, league)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""

        url = competition.url
        title = competition.title
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, sc.channel.id, url, title)

        sc.leagues.add(competition)
        e = discord.Embed(title="LiveScores: Tracked League Added")
        e.description = f"{sc.channel.mention}\n\n{competition.url}"
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        return await interaction.edit_original_response(embed=e)

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

        for c in self.bot.score_channels.copy():
            if channel.id == c.channel.id:
                self.bot.score_channels.remove(c)


async def setup(bot: Bot):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
