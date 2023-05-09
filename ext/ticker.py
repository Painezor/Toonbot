"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import logging
from typing import TYPE_CHECKING, ClassVar, TypeAlias, cast

import discord
from discord import Colour
from discord.abc import GuildChannel
from discord.ext import commands

import ext.flashscore as fs
from ext.utils import embed_utils, view_utils, flags

if TYPE_CHECKING:
    from core import Bot
    from playwright.async_api import Page

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member

_ticker_tasks: set[asyncio.Task[None]] = set()

logger = logging.getLogger("ticker.py")

NOPERMS = (
    "```yaml\nThis ticker channel will not work currently"
    "I am missing the following permissions.\n"
)

# Number of permanent instances to fetch tables.
EVT = fs.EventType
WORKER_COUNT = 2

# Colour for embed for EventTypes
EMBED_COLOURS = {
    # Goals
    EVT.GOAL: Colour.green(),
    EVT.VAR_GOAL: Colour.dark_green(),
    # Red Cards
    EVT.RED_CARD: Colour.red(),
    EVT.VAR_RED_CARD: Colour.dark_red(),
    # Start/Stop Game
    EVT.KICK_OFF: Colour.light_embed(),
    EVT.HALF_TIME: Colour.dark_teal(),
    EVT.SECOND_HALF_BEGIN: Colour.light_gray(),
    EVT.FULL_TIME: Colour.teal(),
    EVT.FINAL_RESULT_ONLY: Colour.teal(),
    EVT.SCORE_AFTER_EXTRA_TIME: Colour.teal(),
    EVT.PERIOD_BEGIN: Colour.light_gray(),
    EVT.PERIOD_END: Colour.dark_teal(),
    EVT.NORMAL_TIME_END: Colour.dark_magenta(),
    EVT.EXTRA_TIME_BEGIN: Colour.magenta(),
    EVT.ET_HT_BEGIN: Colour.dark_magenta(),
    EVT.ET_HT_END: Colour.dark_purple(),
    EVT.EXTRA_TIME_END: Colour.purple(),
    # Interruptions
    EVT.ABANDONED: Colour.orange(),
    EVT.CANCELLED: Colour.orange(),
    EVT.DELAYED: Colour.orange(),
    EVT.INTERRUPTED: Colour.dark_orange(),
    EVT.POSTPONED: Colour.dark_orange(),
    EVT.RESUMED: Colour.light_gray(),
    # Penalties
    EVT.PENALTIES_BEGIN: Colour.gold(),
    EVT.PENALTY_RESULTS: Colour.dark_gold(),
}


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(
        self,
        fixture: fs.Fixture,
        event_type: EVT,
        channels: list[TickerChannel],
        home: bool | None = None,
    ) -> None:
        self.fixture: fs.Fixture = fixture
        self.event_type: EVT = event_type
        self.channels: list[TickerChannel] = channels
        self.home: bool | None = home

        self.bot = self.channels[0].bot

        # For exact event.
        self.event: fs.MatchIncident | None = None

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

        self.full: discord.Embed
        self.short: discord.Embed

    async def short_embed(self) -> discord.Embed:
        """The Embed for this match event"""
        embed = discord.Embed(colour=EMBED_COLOURS[self.event_type])
        embed.url = self.fixture.url
        embed.title = self.fixture.score_line
        embed.description = ""

        name = self.event_type.value
        if self.event:
            embed.description = str(self.event)
            if self.event.description:
                embed.description += f"\n\n> {self.event.description}"
            if self.home is True:
                embed.set_thumbnail(url=self.fixture.home.team.logo_url)
                name = f"{name} ({self.fixture.home.team.name})"
            elif self.home is False:
                embed.set_thumbnail(url=self.fixture.away.team.logo_url)
                name = f"{name} ({self.fixture.away.team.name})"
        embed.set_author(name=name)

        comp = self.fixture.competition
        c_name = f" | {comp.title}" if comp else ""

        if self.fixture.state:
            short = self.fixture.state.shorthand
            embed.set_footer(text=f"{short}{c_name}")
        else:
            embed.set_footer(text=f"{self.fixture.time}{c_name}")

        if self.event_type == EVT.PENALTY_RESULTS:
            self.handle_pens(embed)

        if (info := self.fixture.infobox) is not None:
            embed.add_field(name="Match Info", value=f"```yaml\n{info}```")
        return embed

    def handle_pens(self, embed: discord.Embed) -> None:
        """Add a field to the embed with the results of the penalties"""
        fxe = self.fixture.events
        pens = [i for i in fxe if isinstance(i, fs.Penalty) and i.shootout]

        for team in [self.fixture.home.team, self.fixture.away.team]:
            if value := [str(i) for i in pens if i.team == team]:
                embed.add_field(name=team, value="\n".join(value))

    async def extended(self) -> discord.Embed:
        """The Extended Embed for this match event"""
        embed = await self.short_embed()
        embed = embed.copy()
        if embed.description is None:
            embed.description = ""

        if self.event is not None and len(self.fixture.events) > 1:
            embed.description += "\n```yaml\n--- Previous Events ---```"

        for i in self.fixture.events:
            # We only want the other events, not ourself.
            if i == self.event:
                continue
            elif isinstance(i, fs.Penalty) and i.shootout:
                continue
            elif isinstance(i, fs.Substitution):
                continue  # skip subs, they're just spam.

            if str(i) not in embed.description:
                embed.description += f"\n{str(i)}"
        return embed

    async def dispatch(self) -> None:
        """Send to the appropriate channel and let them handle it."""
        self.full = await self.extended()
        self.short = await self.short_embed()

        logging.info(
            "Dispatching Ticker Event to %s channels", len(self.channels)
        )
        for chan in self.channels:
            await chan.output(self)

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        if self.event_type == EVT.KICK_OFF:
            return await self.dispatch()

        # Handle Match Events with no game events.
        index: int | None = None
        for count in range(5):
            page = await self.bot.browser.new_page()
            try:
                await self.fixture.refresh(page)
            finally:
                await page.close()

            # Figure out which event we're supposed to be using
            # (Either newest event, or Stored if refresh)
            if index is None:
                participant = {
                    None: None,
                    True: self.fixture.home,
                    False: self.fixture.away,
                }[self.home]

                events = self.fixture.events
                if participant is not None:
                    events = [i for i in events if i.team == participant.team]

                valid = self.event_type.valid_events
                if valid and events:
                    events.reverse()
                    try:
                        evt = next(i for i in events if isinstance(i, valid))
                        self.event = evt
                        index = self.fixture.events.index(self.event)
                    except StopIteration:
                        evt = "\n".join(set(str(type(i)) for i in events))
                        logger.error("Can't find %s in %s", valid, evt)
                        logger.error("Event is %s", self.event_type)

            else:
                try:
                    self.event = self.fixture.events[index]
                except IndexError:
                    self.event = None
                    break

            if index:
                evts = self.fixture.events[: index + 1]
                if all(i.is_done() for i in evts):
                    break
            else:
                if self.event and self.event.is_done():
                    break

            await self.dispatch()
            await asyncio.sleep(count + 1 * 60)

        await self.dispatch()


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    bot: ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: list[fs.Competition] = []
        self.dispatched: dict[TickerEvent, discord.Message] = {}

        # Settings
        self.goals: bool | None = None
        self.kick_offs: bool | None = None
        self.full_times: bool | None = None
        self.half_times: bool | None = None
        self.second_halfs: bool | None = None
        self.red_cards: bool | None = None
        self.final_results: bool | None = None
        self.penalties: bool | None = None
        self.delays: bool | None = None
        self.vars: bool | None = None
        self.extra_times: bool | None = None

    @property
    def id(self) -> int:  # pylint: disable=C0103
        """Pass Access to Parent"""
        return self.channel.id

    @property
    def mention(self) -> str:
        """Pass Access to Parent"""
        return self.channel.mention

    # Send messages
    async def output(self, event: TickerEvent) -> None:
        """Send the appropriate embed to this channel"""
        # Check if we need short or long embed.
        # For each stored db_field value,
        # we check against our own settings field.
        try:
            if all(
                {
                    EVT.KICK_OFF: [self.kick_offs],
                    EVT.GOAL: [self.goals],
                    EVT.VAR_GOAL: [self.goals, self.vars],
                    EVT.RED_CARD: [self.red_cards],
                    EVT.VAR_RED_CARD: [self.red_cards, self.vars],
                    EVT.HALF_TIME: [self.half_times],
                    EVT.SECOND_HALF_BEGIN: [self.second_halfs],
                    EVT.FULL_TIME: [self.full_times],
                    EVT.NORMAL_TIME_END: [self.full_times],
                    EVT.SCORE_AFTER_EXTRA_TIME: [self.full_times],
                    EVT.EXTRA_TIME_BEGIN: [self.extra_times],
                    EVT.EXTRA_TIME_END: [self.extra_times],
                    EVT.ET_HT_BEGIN: [self.extra_times, self.half_times],
                    EVT.ET_HT_END: [self.extra_times, self.second_halfs],
                    EVT.PENALTIES_BEGIN: [self.penalties],
                    EVT.PENALTY_RESULTS: [self.penalties],
                    EVT.FINAL_RESULT_ONLY: [self.final_results],
                }[event.event_type]
            ):
                embed = event.full
            else:
                embed = event.short
        except KeyError:
            logger.error("%s missing in output", event.event_type)
            embed = event.short

        try:
            try:
                message = self.dispatched[event]
                # Save on ratelimiting by checking.
                if message.embeds:
                    if message.embeds[0].description == embed.description:
                        return
                message = await message.edit(embed=embed)
            except KeyError:
                message = await self.channel.send(embed=embed)
        except discord.HTTPException:
            cog = self.bot.get_cog(TickerCog.__cog_name__)
            assert isinstance(cog, TickerCog)
            cog.channels.remove(self)
            return

        self.dispatched[event] = message

    # Database management.
    async def configure_channel(self) -> None:
        """Retrieve the settings of the TickerChannel from the database"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
                stg = await connection.fetchrow(sql, self.channel.id)
                sql = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
                leagues = await connection.fetch(sql, self.channel.id)

        if stg is not None:
            for k, value in stg.items():
                if k == "channel_id":
                    continue
                setattr(self, k, value)

        for r in leagues:
            if comp := self.bot.flashscore.get_competition(url=r["url"]):
                self.leagues.append(comp)
                continue
            logger.error("Could not find comp %s", r)


class TickerConfig(view_utils.DropdownPaginator):
    """Match Event Ticker View"""

    def __init__(self, invoker: User, tc: TickerChannel):
        self.channel: TickerChannel = tc

        options: list[discord.SelectOption] = []
        _ = filter(lambda i: i.url is not None, tc.leagues)
        comps = list(sorted(_, key=lambda x: x.title))
        for i in comps:
            assert i.url is not None  # Already Filtered.
            opt = discord.SelectOption(label=i.title, value=i.url)
            opt.description = i.url
            flag = flags.get_flag(i.country)
            opt.emoji = flag
            options.append(opt)

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.set_author(name="Match Event Ticker config")
        embed.description = f"Tracked leagues for {tc.mention}\n"

        # Permission Checks
        missing: list[str] = []
        perms = tc.channel.permissions_for(tc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        # Handle Empty
        if not comps:
            rows = [f"{tc.mention} has no tracked leagues."]
        else:
            rows = [f"{flags.get_flag(i.country)} {i.markdown}" for i in comps]
        super().__init__(invoker, embed, rows, options)
        self.settings.options = self.generate_settings()

    def generate_settings(self) -> list[discord.SelectOption]:
        """Generate Dropdown for settings configuration"""

        options: list[discord.SelectOption] = []
        for k in [
            "goals",
            "kick_offs",
            "full_times",
            "half_times",
            "second_halfs",
            "red_cards",
            "final_results",
            "penalties",
            "delays",
            "vars",
            "extra_times",
        ]:
            value = getattr(self.channel, k)
            emoji = {None: "🔴", True: "🔵", False: "🟢"}[value]
            name = k.replace("_", " ").title()
            opt = discord.SelectOption(label=name, emoji=emoji, value=k)

            if value is None:
                opt.description = f"{name} events are currently disabled"
            elif value:
                opt.description = f"{name} events send extended output"
            else:
                opt.description = f"{name} events send short output"
            options.append(opt)
        return options

    @discord.ui.select(placeholder="Change Settings", row=2)
    async def settings(
        self, itr: Interaction, sel: discord.ui.Select[TickerConfig]
    ) -> None:
        """Regenerate view and push to message"""
        embed = discord.Embed(title="Settings updated")
        embed.description = ""
        embed.colour = discord.Colour.dark_teal()
        embed_utils.user_to_footer(embed, itr.user)

        rotate = {None: "Disabled", True: "Extended", False: "Short"}
        async with itr.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                for i in sel.values:  # List of DB Fields.
                    old = getattr(self.channel, i)
                    new = {True: None, False: True, None: False}[old]
                    setattr(self.channel, i, new)

                    val = rotate[new]
                    key = i.replace("_", " ").title()
                    embed.description += f"{key}: {val}\n"
                    sql = f"""UPDATE ticker_settings SET {i} = $1
                            WHERE channel_id = $2"""
                    await connection.execute(sql, val, self.channel.id)

        sel.options = self.generate_settings()
        return await itr.response.edit_message(embed=embed, view=self)

    @discord.ui.select(placeholder="Remove Leagues", row=1)
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[TickerConfig]
    ) -> None:
        """When a league is selected, delete channel / league row from DB"""

        # Ask User to confirm their selection of data destruction
        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lg_text = "\n".join(sorted(sel.values))
        ment = self.channel.mention
        embed = discord.Embed(title="Ticker", colour=discord.Colour.red())
        embed.description = f"Remove these leagues from {ment}?\n{lg_text}"

        await itr.response.edit_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            # Return to normal viewing
            embed = self.pages[self.index]
            return await itr.response.edit_message(embed=embed, view=self)

        # Remove from the database
        sql = """DELETE from ticker_leagues
                 WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.channel.id, x) for x in sel.values]
        async with itr.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        # Remove from the parent channel's tracked leagues
        for i in sel.values:
            league = next(j for j in self.channel.leagues if j.url == i)
            self.channel.leagues.remove(league)

        # Send Confirmation Followup
        embed = discord.Embed(title="Ticker", colour=discord.Colour.red())
        ment = self.channel.mention
        embed.description = f"Removed {ment} tracked leagues:\n{lg_text}"
        embed_utils.user_to_footer(embed, itr.user)
        await itr.followup.send(embed=embed)

        # Reinstantiate the view
        view = TickerConfig(itr.user, self.channel)
        try:
            embed = view.pages[self.index]
            view.index = self.index
        except IndexError:
            view.index = self.index - 1
            embed = view.pages[view.index]
        return await itr.response.edit_message(view=view, embed=embed)

    @discord.ui.button(row=3, label="Reset Leagues")
    async def reset(self, interaction: Interaction, _) -> None:
        """Click button reset leagues"""
        # Ask User to confirm their selection of data destruction
        view = view_utils.Confirmation(interaction.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        embed = discord.Embed(title="Ticker", colour=discord.Colour.red())
        ment = self.channel.mention
        embed.description = f"Reset leagues to default {ment}?\n"

        await interaction.response.edit_message(embed=embed, view=view)
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            # Return to normal viewing
            embed = self.pages[self.index]
            await view_itr.response.edit_message(embed=embed, view=self)
            return

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM ticker_leagues WHERE channel_id = $1"""
                await connection.execute(sql, self.channel.id)

                sql = """INSERT INTO ticker_leagues (channel_id, url)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""

                cid = self.channel.id
                args = [(cid, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql, args)

        self.channel.leagues.clear()
        for i in fs.DEFAULT_LEAGUES:
            comp = interaction.client.flashscore.get_competition(url=i)
            if comp is None:
                logger.info("Reset: Could not add default league %s", comp)
                continue
            self.channel.leagues.append(comp)

        embed = discord.Embed(title="Ticker: Tracked Leagues Reset")
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)

        # Reinstantiate the view
        view = TickerConfig(interaction.user, self.channel)
        await view_itr.response.edit_message(view=view, embed=view.pages[0])

    @discord.ui.button(row=3, label="Delete", style=discord.ButtonStyle.red)
    async def delete(self, interaction: Interaction, _) -> None:
        """Click button delete ticker"""
        view = view_utils.Confirmation(interaction.user, "Confirm", "Cancel")
        view.true.style = discord.ButtonStyle.red

        ment = self.channel.mention
        embed = discord.Embed(colour=discord.Colour.red())
        embed.description = (
            f"Are you sure you wish to delete the ticker from {ment}?"
            "\n\nThis action cannot be undone."
        )
        await interaction.response.edit_message(view=view, embed=embed)

        view_itr = view.interaction
        if not view.value:
            # Return to normal viewing
            embed = self.pages[self.index]
            await view_itr.response.edit_message(embed=embed, view=self)
            return

        cog = interaction.client.get_cog(TickerCog.__cog_name__)
        assert isinstance(cog, TickerCog)
        cog.channels.remove(self.channel)

        embed = discord.Embed(colour=discord.Colour.red())
        embed.description = f"The Ticker for {ment} was deleted."
        embed_utils.user_to_footer(embed, interaction.user)
        await view_itr.response.edit_message(embed=embed, view=None)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.channel.id)


class TickerCog(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        TickerChannel.bot = bot
        self.workers: asyncio.Queue[Page] = asyncio.Queue(5)
        self.channels: list[TickerChannel] = []

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        for _ in range(WORKER_COUNT):
            page = await self.bot.browser.new_page()
            await self.workers.put(page)

        await self.update_cache()

    async def cog_unload(self) -> None:
        while not self.workers.empty():
            page = await self.workers.get()
            await page.close()

    async def create(
        self,
        interaction: Interaction,
        channel: discord.TextChannel,
    ) -> TickerChannel | None:
        """Send a dialogue to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                invalidate = await connection.fetchrow(sql, channel.id)
        if invalidate:
            err = "🚫 You cannot create a ticker in a livescores channel."
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = err
            reply = interaction.response.edit_message
            return await reply(embed=embed)

        ment = channel.mention
        view = view_utils.Confirmation(interaction.user, "Create", "Cancel")
        view.true.style = discord.ButtonStyle.blurple

        embed = discord.Embed(title="Create a ticker")
        embed.description = f"{ment} has no ticker, create one?"
        await interaction.response.send_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"❌ Cancelled ticker creation for {ment}"
            reply = view.interaction.response.edit_message
            await reply(embed=embed, view=None)
            return None

        guild = channel.guild.id

        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild)

                sql = """INSERT INTO ticker_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild, channel.id)

                sql3 = """INSERT INTO ticker_settings (channel_id) VALUES ($1)
                        ON CONFLICT DO NOTHING"""
                await connection.execute(sql3, channel.id)

                sql4 = """INSERT INTO ticker_leagues (channel_id, url)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                rows = [(channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql4, rows)

        chan = TickerChannel(channel)
        await chan.configure_channel()
        self.channels.append(chan)
        return chan

    async def update_cache(self) -> list[TickerChannel]:
        """Store a list of all Ticker Channels into the bot"""
        self.channels.clear()
        sql = """SELECT DISTINCT channel_id FROM ticker_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        bad: set[int] = set()
        for i in records:
            chan = self.bot.get_channel(i["channel_id"])
            if chan is None:
                bad.add(i["channel_id"])
                continue

            chan = cast(discord.TextChannel, chan)

            tkrchan = TickerChannel(chan)
            await tkrchan.configure_channel()
            self.channels.append(tkrchan)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        if self.channels:
            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    for _id in bad:
                        await connection.execute(sql, _id)
            logger.info("Deleted %s bad Ticker channels", len(bad))
        return self.channels

    async def refresh_table(self, competition: fs.Competition) -> None:
        """Refresh table for object"""
        page = await self.workers.get()
        try:
            image = await competition.get_table(page)
            if image is not None:
                table = io.BytesIO(image)
                url = await self.bot.dump_image(table)
                competition.table = url
        finally:
            await self.workers.put(page)

    @commands.Cog.listener()
    async def on_fixture_event(
        self,
        event_type: EVT,
        fixture: fs.Fixture,
        home: bool | None = None,
    ) -> TickerEvent | None:
        """Event handler for when something occurs during a fixture."""
        # Update the competition's Table on certain events.
        channels: list[TickerChannel] = []
        for i in self.channels:
            if fixture.competition in i.leagues:
                channels.append(i)

        evt = EVT

        # TODO: Figure out how to turn this into a dict.
        for i in channels.copy():
            try:
                if (
                    None
                    in {
                        evt.KICK_OFF: [i.kick_offs],
                        evt.GOAL: [i.goals],
                        evt.VAR_GOAL: [i.goals, i.vars],
                        evt.RED_CARD: [i.red_cards],
                        evt.VAR_RED_CARD: [i.red_cards, i.vars],
                        evt.HALF_TIME: [i.half_times],
                        evt.SECOND_HALF_BEGIN: [i.second_halfs],
                        evt.FULL_TIME: [i.full_times],
                        evt.NORMAL_TIME_END: [i.full_times],
                        evt.SCORE_AFTER_EXTRA_TIME: [i.full_times],
                        evt.EXTRA_TIME_BEGIN: [i.extra_times],
                        evt.EXTRA_TIME_END: [i.extra_times],
                        evt.ET_HT_BEGIN: [i.extra_times, i.half_times],
                        evt.ET_HT_END: [i.extra_times, i.second_halfs],
                        evt.PENALTIES_BEGIN: [i.penalties],
                        evt.PENALTY_RESULTS: [i.penalties],
                        evt.FINAL_RESULT_ONLY: [i.final_results],
                    }[event_type]
                ):
                    channels.remove(i)
            except KeyError:
                logger.info("Unhandled Event Type %s", event_type)

        if not channels:
            return

        if event_type == evt.GOAL and fixture.competition:
            await self.refresh_table(fixture.competition)

        return TickerEvent(fixture, event_type, channels, home)

    ticker = discord.app_commands.Group(
        name="ticker",
        description="match event ticker",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @ticker.command()
    @discord.app_commands.describe(channel="Manage which channel?")
    async def manage(
        self,
        interaction: Interaction,
        channel: discord.TextChannel | None,
    ) -> None:
        """View the config of this channel's Match Event Ticker"""
        if not self.channels:
            await self.update_cache()

        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        try:
            tkrs = self.channels
            chan = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            chan = await self.create(interaction, channel)
            if chan is None:
                return

        view = TickerConfig(interaction.user, chan)
        await interaction.response.send_message(view=view, embed=view.pages[0])

    @ticker.command()
    @discord.app_commands.describe(
        competition="Search for a league by name",
        channel="Add to which channel?",
    )
    async def add_league(
        self,
        interaction: Interaction,
        competition: fs.cmp_tran,
        channel: discord.TextChannel | None,
    ) -> None:
        """Add a league to your Match Event Ticker"""

        if competition.title == "WORLD: Club Friendly":
            embed = discord.Embed(colour=discord.Colour.red())
            err = "🚫 You can't add club friendlies as a competition, sorry."
            embed.description = err
            return await interaction.response.send_message(embed=embed)

        if competition.url is None:
            embed = discord.Embed(colour=discord.Colour.red())
            err = "🚫 Invalid competition selected. Error logged."
            embed.description = err
            logger.error("%s url is None", competition)
            return await interaction.response.send_message(embed=embed)

        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        tickers = self.channels
        try:
            tkr_chan = next(i for i in tickers if i.channel.id == channel.id)
        except StopIteration:
            tkr_chan = await self.create(interaction, channel)

            if tkr_chan is None:
                return

        embed = discord.Embed(title="Ticker: Tracked League Added")
        embed.description = f"{tkr_chan.channel.mention}\n\n{competition.url}"
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.response.send_message(embed=embed)

        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id, competition.url)

        tkr_chan.leagues.append(competition)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: GuildChannel) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        for i in self.channels.copy():
            if i.channel.id == channel.id:
                self.channels.remove(i)


async def setup(bot: Bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(TickerCog(bot))
