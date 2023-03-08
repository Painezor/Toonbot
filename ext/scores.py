"""This Cog Grabs data from Flashscore and outputs the latest scores to user
-configured live score channels"""
from __future__ import annotations
import asyncio

import logging
import collections
from datetime import datetime, timezone, timedelta
import importlib
import itertools
import typing

import discord
from discord.ext import commands, tasks
from lxml import html, etree

import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils.gamestate import GameState
from ext.toonbot_utils.matchevents import EventType

from ext.utils import view_utils, embed_utils
from ext.fixtures import CompetitionTransformer

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


class ScoreChannel:
    """A livescore channel object, containing it's properties."""

    bot: typing.ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.messages: list[discord.Message | None] = []
        self.leagues: set[fs.Competition] = set()

    def generate_embeds(self) -> list[discord.Embed]:
        """Have each Competition generate it's livescore embeds"""
        embeds = []

        for i in self.leagues:
            embeds += i.score_embeds

        if not embeds:
            return [
                discord.Embed(
                    title="No Games Found", description=NO_GAMES_FOUND
                )
            ]
        return embeds

    async def get_leagues(self) -> set[fs.Competition]:
        """Fetch target leagues for the ScoreChannel from the database"""
        sql = """SELECT url FROM scores_leagues WHERE channel_id = $1"""

        async with self.bot.db.acquire(timeout=60) as c:
            async with c.transaction():
                records = await c.fetch(sql, self.channel.id)

        for r in records:
            comp = self.bot.get_competition(r["url"])
            if comp is None:
                continue

            self.leagues.add(comp)
        return self.leagues

    async def update(self) -> list[discord.Message | None]:
        """Edit a live-score channel to have the latest scores"""
        if self.channel.is_news():
            return []

        if not self.leagues:
            await self.get_leagues()

        embeds = self.generate_embeds()

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

        embed.description = f"Tracked leagues for {ch.mention}```yaml\n"
        leagues = sorted(self.sc.leagues, key=lambda x: x.title)
        self.pages = embed_utils.paginate(leagues)
        self.add_page_buttons()

        leagues: list[fs.Competition]
        leagues = [i.url for i in self.pages[self.index] if i.url is not None]

        embed.description += "\n".join([str(i.url) for i in leagues])

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

        await interaction.response.defer()

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

            self.add_option(label=lg.title, description=lg.url, value=lg.url)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When a league is selected"""
        await interaction.response.defer()
        view = view_utils.Confirmation(
            interaction,
            "Remove",
            "Cancel",
            discord.ButtonStyle.red,
        )

        lg_text = "```yaml\n" + "\n".join(sorted(self.values)) + "```"
        c = self.view.sc.channel.mention

        e = discord.Embed(title="LiveScores", colour=discord.Colour.red())
        e.description = f"Remove these leagues from {c}? ```yaml\n{lg_text}```"
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
        msg = f"Removed {m} tracked leagues: ```yaml\n{lg_text}```"
        e = discord.Embed(description=msg, colour=discord.Colour.red())

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
        await self.load_database()
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

    # Database load: Leagues & Teams
    async def load_database(self) -> None:
        """Load all stored leagues and competitions into the bot"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * from fs_competitions"""
                comps = await connection.fetch(sql)
                teams = await connection.fetch("""SELECT * from fs_teams""")

        for c in comps:
            if self.bot.get_competition(c["id"]) is None:
                cm = fs.Competition(c["id"], c["name"], c["country"], c["url"])
                cm.logo_url = c["logo_url"]
                self.bot.competitions.append(cm)

        for t in teams:
            if self.bot.get_team(t["id"]) is None:
                team = fs.Team(t["id"], t["name"], t["url"])
                team.logo_url = t["logo_url"]
                self.bot.teams.append(team)

    # Database load: ScoreChannels
    async def update_cache(self) -> list[ScoreChannel]:
        """Grab the most recent data for all channel configurations"""

        sql = """SELECT * FROM scores_leagues"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        # Generate {channel_id: [league1, league2, league3, …]}

        comps = self.bot.competitions

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

            try:
                comp = next(i for i in comps if i.url == r["url"])
            except StopIteration:
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
            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    await connection.executemany(sql, bad)
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

        for comp in comps.copy():
            e = (await comp.base_embed()).copy()

            flt = [i for i in self.bot.games if i.competition == comp]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [i.live_score_text for i in fix]

            table = f"\n[View Table]({comp.table})" if comp.table else ""
            rte = embed_utils.rows_to_embeds
            comp.score_embeds = rte(e, ls_txt, 50, footer=table)

        for sc in self.bot.score_channels.copy():
            await sc.update()

    @score_loop.before_loop
    async def clear_old_scores(self):
        """Purge old messages from livescore channels before starting up."""
        await self.bot.wait_until_ready()

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

        match new:
            case GameState.ABANDONED:
                return send_event(evt, EventType.ABANDONED, fx)
            case GameState.AFTER_EXTRA_TIME:
                return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fx)
            case GameState.AFTER_PENS:
                return send_event(evt, EventType.PENALTY_RESULTS, fx)
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
            case GameState.CANCELLED:
                return send_event(evt, EventType.CANCELLED, fx)
            case GameState.DELAYED:
                return send_event(evt, EventType.DELAYED, fx)
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
            case GameState.INTERRUPTED:
                return send_event(evt, EventType.INTERRUPTED, fx)
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

    # Core Loop
    async def fetch_games(self) -> list[fs.Fixture]:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            match resp.status:
                case 200:
                    bt = bytearray(await resp.text(), encoding="utf-8")
                    tree = html.fromstring(bytes(bt))
                case _:
                    rs = resp.reason
                    st = resp.status
                    logger.error("%s %s during score loop", st, rs)
                    return []

        data = tree.xpath('.//div[@id="score-data"]')[0]
        chunks = etree.tostring(data).decode("utf8").split("<br/>")

        # Generic
        competition = None
        comps = self.bot.competitions

        for game in chunks:
            try:
                tree = html.fromstring(game)
                # Document is empty because of trailing </div>
            except etree.ParserError:
                continue

            # Check if the chunk to be parsed has is a header.
            # If it is, we need to create a new competition object.
            # TODO: Handle Competition Fetching & Team Fetching from Flashscore
            if competition_name := "".join(tree.xpath(".//h4/text()")).strip():
                # Loop over bot.competitions to see if we can find the right
                # Competition object for base_embed.

                if exact := [i for i in comps if i.title == competition_name]:
                    competition = exact[0]
                else:
                    country, name = competition_name.rsplit(":", 1)
                    # Partial Matches
                    partial = [x for x in comps if x.title in competition_name]
                    for ss in ["women", "u18"]:  # Filter…
                        if ss in competition_name.casefold():
                            partial = [
                                i for i in partial if ss in i.name.casefold()
                            ]

                    if partial:
                        partial.sort(key=lambda x: len(x.name))
                        competition = partial[0]
                    else:

                        if country:
                            country = country.strip()
                        if name:
                            name = name.strip()
                        competition = fs.Competition(None, name, country, None)
                        self.bot.competitions.append(competition)

            try:
                link = "".join(tree.xpath(".//a/@href"))
                match_id = link.split("/")[-2]
                url = fs.FLASHSCORE + link
            except IndexError:
                continue

            f = "fixture_event"  # Just a string for dispatching events.

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
                        logger.error("Fetch games found %s", teams)
                        continue

                home = fs.Team(None, home_name, None)
                away = fs.Team(None, away_name, None)
                fx = fs.Fixture(home, away, match_id, url)
                rf_task = self.bot.loop.create_task(fx.fetch_data(self.bot))
                self.tasks.add(rf_task)
                rf_task.add_done_callback(self.tasks.discard)
                self.bot.games.append(fx)

                old_state = None
            else:
                old_state = fx.state

            # Set the competition of the fixture
            if fx.competition is None:
                fx.competition = competition

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
                            self.bot.dispatch(f, t, fx, home=True)
                        fx.home_cards = home_cards

                if away_cards is not None:
                    if away_cards != fx.away_cards:
                        if fx.away_cards is not None:
                            if away_cards > fx.away_cards:
                                t = EventType.RED_CARD
                            else:
                                t = EventType.VAR_RED_CARD
                            self.bot.dispatch(f, t, fx, home=False)
                        fx.away_cards = away_cards

            # The time block can be 1 element or 2 elements long.
            # Element 1 is either a time of day HH:MM (e.g. 20:45)
            # or a time of the match (e.g. 41')

            # If Element 2 exists, it is a declaration:
            # Cancelled, Postponed, Delayed, or similar.
            time = tree.xpath("./span/text()")

            state = "".join(tree.xpath("./a/@class")).strip()

            # First, we check to see if we need to,
            # and can update the fixture's kickoff

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
                override = "".join([i for i in a_score if not i.isdigit()])
                h_score = int(h_score)
                a_score = int("".join([i for i in a_score if i.isdigit()]))

                if fx.home_score != h_score:
                    if fx.home_score is not None:
                        if h_score > fx.home_score:
                            ev = EventType.GOAL
                        else:
                            ev = EventType.VAR_GOAL
                        self.bot.dispatch(f, ev, fx, home=True)
                    fx.home_score = h_score

                if fx.away_score != a_score:
                    if fx.away_score is not None:
                        if a_score > fx.away_score:
                            ev = EventType.GOAL
                        else:
                            ev = EventType.VAR_GOAL
                        self.bot.dispatch(f, ev, fx, home=False)
                    fx.away_score = a_score
            else:
                override = None

            if override:
                try:
                    fx.time = {
                        "aet": GameState.AFTER_EXTRA_TIME,
                        "pen": GameState.AFTER_PENS,
                        "wo": GameState.WALKOVER,
                    }[override.casefold()]
                except KeyError:
                    logger.error(f"Unhandled override: {override}")
            else:
                # From the link of the score, we can gather info about the time
                # valid states are: sched, live, fin
                match len(time), state:
                    case 1, "live":
                        match time[0]:
                            case "Half Time":
                                fx.time = GameState.HALF_TIME
                            case "Break Time":
                                fx.time = GameState.BREAK_TIME
                            case "Penalties":
                                fx.time = GameState.PENALTIES
                            case "Extra Time":
                                fx.time = GameState.EXTRA_TIME
                            case "Live":
                                fx.time = GameState.FINAL_RESULT_ONLY
                            case _:
                                if "'" not in time[0]:
                                    logger.error("1 part time %1", time)
                                fx.time = time[0]
                    case 1, "sched":
                        fx.time = GameState.SCHEDULED
                    case 1, "fin":
                        fx.time = GameState.FULL_TIME
                    case 2, _:
                        # If we have a 2 part item, the second part will
                        # provide additional information
                        match time[-1]:
                            case "Cancelled":
                                fx.time = GameState.CANCELLED
                            case "Postponed":
                                fx.time = GameState.POSTPONED
                            case "Delayed":
                                fx.time = GameState.DELAYED
                            case "Interrupted":
                                fx.time = GameState.INTERRUPTED
                            case "Abandoned":
                                fx.time = GameState.ABANDONED
                            case "Extra Time":
                                fx.time = GameState.EXTRA_TIME
                            case _:
                                logger.error(f"2 part time found {time}")

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

        sql = """INSERT INTO scores_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, sc.channel.id, competition.url)

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
