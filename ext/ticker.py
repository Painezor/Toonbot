"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import logging
from pydantic import BaseModel
from typing import TYPE_CHECKING, ClassVar, TypeAlias, cast

import discord
from discord import Colour, Embed, Message
from discord.abc import GuildChannel
from discord.ext import commands
from discord.ui import Select

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


class TickerSettings(BaseModel):
    channel_id: int
    goals: bool
    kick_offs: bool
    full_times: bool
    half_times: bool
    second_halfs: bool
    red_cards: bool
    final_results: bool
    delays: bool
    vars: bool
    extra_times: bool
    penalties: bool

    @property
    def var_goal(self) -> bool:
        return self.vars and self.goals

    @property
    def var_red_card(self) -> bool:
        return self.vars and self.red_cards

    @property
    def ht_et_start(self) -> bool:
        return self.half_times and self.extra_times

    @property
    def et_2h_start(self) -> bool:
        return self.extra_times and self.second_halfs


class TickerEmbed(Embed):
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

    def __init__(self, event: TickerEvent, extended: bool = False) -> None:
        try:
            super().__init__(colour=self.EMBED_COLOURS[event.event_type])
        except KeyError:
            logger.error("Failed to init event type", event.event_type)

        self.event = event

        self.url = event.fixture.url
        self.title = event.fixture.score_line
        self.description = ""

        name = event.event_type.value
        if event.incident and not extended:
            if event.event_type == EVT.PENALTY_RESULTS:
                self.handle_pens()

            self.description = str(event.incident)
            if event.incident.description:
                self.description += f"\n\n> {event.incident.description}"

            if event.team:
                self.set_thumbnail(url=event.team.logo_url)
                name = f"{name} ({event.team.name})"
            elif event.fixture.competition:
                self.set_thumbnail(url=event.fixture.competition.logo_url)

        self.set_author(name=name)

        if (info := event.fixture.infobox) is not None:
            self.add_field(name="Match Info", value=f"```yaml\n{info}```")

        if extended:
            self.extend()

    def handle_pens(self) -> None:
        """Add fields to the embed with the results of the penalties"""
        self.clear_fields()

        fix = self.event.fixture
        fxe = fix.incidents
        pens = [i for i in fxe if isinstance(i, fs.Penalty) and i.shootout]

        teams = [fix.home.team.name, fix.away.team.name]
        for j in teams:
            if value := [str(i) for i in pens if i.team and i.team.name == j]:
                self.add_field(name=j, value="\n".join(value))

    def extend(self) -> None:
        self.description = ""
        for i in self.event.fixture.incidents:
            # We only want the other events, not ourself.
            if isinstance(i, fs.Penalty) and i.shootout:
                continue
            if isinstance(i, fs.Substitution):
                continue  # skip subs, they're just spam.

            if str(i) not in self.description:
                self.description += f"\n{str(i)}"


class ExtenderView(discord.ui.View):
    def __init__(self, embed: TickerEmbed) -> None:
        super().__init__()
        self.emb = embed

    @discord.ui.button(label="All", emoji="ℹ")
    async def callback(self, interaction: Interaction, _) -> None:
        """Send an emphemeral list of all events to the invoker"""
        await interaction.response.send_message(embed=self.emb, ephemeral=True)


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(
        self,
        fixture: fs.Fixture,
        event_type: EVT,
        channels: list[TickerChannel],
        team: fs.Team | None = None,
    ) -> None:
        self.fixture: fs.Fixture = fixture
        self.event_type: EVT = event_type
        self.channels: list[TickerChannel] = channels
        self.team: fs.Team | None = team

        self.bot = self.channels[0].bot

        # For exact event.
        self.incident: fs.MatchIncident | None = None

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

        self.messages: dict[TickerChannel, Message]  # guild.id, message.id
        self._cached: Embed | None = None

        self.full: Embed

    async def _dispatch(self) -> None:
        """Send to the appropriate channel and let them handle it."""
        embed = TickerEmbed(self)

        if self._cached is not None:
            if self._cached.description == embed.description:
                return

        self._cached = embed

        logging.info("Ticker Event %s channels", len(self.channels))
        for chan in self.channels:
            # Send messages
            if chan not in self.messages:
                if self.fixture.incidents:
                    view = ExtenderView(TickerEmbed(self, extended=True))
                    message = await chan.channel.send(embed=embed, view=view)
                else:
                    message = await chan.channel.send(embed=embed)
            else:
                message = self.messages[chan]
                # Save on ratelimiting by checking.
                if message.embeds:
                    if message.embeds[0].description == embed.description:
                        return
                message = await message.edit(embed=embed)
            self.messages[chan] = message

    def find_index(self) -> int | None:
        """Attempt to find the index of the event we're looking for"""
        events = self.fixture.incidents.copy()  # Let's not reverse our actual
        if self.team is not None:
            events = [i for i in events if i.team == self.team]

        valid = self.event_type.valid_events
        if valid and events:
            events.reverse()
            try:
                evt = next(i for i in events if isinstance(i, valid))
                self.incident = evt
                return self.fixture.incidents.index(self.incident)
            except StopIteration:
                evt = "\n".join(set(str(type(i)) for i in events))
                logger.error("Can't find %s in %s", valid, evt)
                logger.error("Event is %s", self.event_type)

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        if self.event_type == EVT.KICK_OFF:
            return await self._dispatch()

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
                index = self.find_index()

            else:
                try:
                    self.incident = self.fixture.incidents[index]
                except IndexError:
                    self.incident = None
                    break

            if index:
                # Get everything up to (:index) and including (+1) this event
                evts = self.fixture.incidents[: index + 1]
                if all(i.player is not None for i in evts):
                    break

            await self._dispatch()
            await asyncio.sleep(count + 1 * 60)

        await self._dispatch()


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    bot: ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: list[fs.Competition] = []
        self.dispatched: dict[TickerEvent, discord.Message] = {}

        # Settings
        self.settings: TickerSettings

    @property
    def id(self) -> int:  # pylint: disable=C0103
        """Pass Access to Parent"""
        return self.channel.id

    @property
    def mention(self) -> str:
        """Pass Access to Parent"""
        return self.channel.mention

    # Database management.
    async def configure_channel(self) -> None:
        """Retrieve the settings of the TickerChannel from the database"""
        sql = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
        stg = await self.bot.db.fetchrow(sql, self.channel.id)
        sql = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
        leagues = await self.bot.db.fetch(sql, self.channel.id)

        self.settings = TickerSettings.parse_obj(stg)

        fs = self.bot.flashscore
        leagues = [fs.get_competition(url=r["url"]) for r in leagues]
        self.leagues = [i for i in leagues if i]


class TickerConfig(view_utils.DropdownPaginator):
    """Match Event Ticker View"""

    _db_table = "ticker_settings"

    def __init__(self, invoker: User, tc: TickerChannel):
        self.channel: TickerChannel = tc

        options: list[discord.SelectOption] = []
        tc.leagues.sort(key=lambda i: i.title)
        for i in tc.leagues:
            if i.url is None:
                continue

            opt = discord.SelectOption(label=i.title, value=i.url)
            opt.description = i.url
            flag = flags.get_flag(i.country)
            opt.emoji = flag
            options.append(opt)

        embed = Embed(colour=Colour.dark_teal())
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
        if not (comps := tc.leagues):
            rows = [f"{tc.mention} has no tracked leagues."]
        else:
            rows = [f"{flags.get_flag(i.country)} {i.markdown}" for i in comps]
        super().__init__(invoker, embed, rows, options)
        self.settings.options = self.generate_settings()

    def generate_settings(self) -> list[discord.SelectOption]:
        """Generate Dropdown for settings configuration"""

        options: list[discord.SelectOption] = []
        for k, val in iter(self.channel.settings):
            if k == "channel_id":
                continue

            emoji = "🟢" if val else "🔴"
            name = k.replace("_", " ").title()
            opt = discord.SelectOption(label=name, emoji=emoji, value=k)

            ena = "enabled" if val else "disabled"
            opt.description = f"{name} events are currently {ena}"
            options.append(opt)
        return options

    @discord.ui.select(placeholder="Change Settings", row=2)
    async def settings(
        self, itr: Interaction, sel: Select[TickerConfig]
    ) -> None:
        """Regenerate view and push to message"""
        embed = Embed(title="Settings updated", colour=Colour.dark_teal())
        embed.description = ""
        embed_utils.user_to_footer(embed, itr.user)

        async with itr.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                for i in sel.values:  # List of DB Fields.
                    old = getattr(self.channel.settings, i)
                    setattr(self.channel.settings, i, not old)

                    alias = i.replace("_", " ").title()
                    embed.description += f"{alias}: {not old}\n"
                    sql = f"""UPDATE {self._db_table} SET {i} = NOT {i}
                            WHERE channel_id = $2"""
                    await connection.execute(sql, self.channel.id)

        sel.options = self.generate_settings()
        return await itr.response.edit_message(embed=embed, view=self)

    @discord.ui.select(placeholder="Remove Leagues", row=1)
    async def dropdown(
        self, itr: Interaction, sel: Select[TickerConfig]
    ) -> None:
        """When a league is selected, delete channel / league row from DB"""

        # Ask User to confirm their selection of data destruction
        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lg_text = "\n".join(sorted(sel.values))
        ment = self.channel.mention
        embed = Embed(title="Ticker", colour=Colour.red())
        embed.description = f"Remove these leagues from {ment}?\n{lg_text}"

        await itr.response.edit_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            # Return to normal viewing
            embed = self.pages[self.index]
            return await itr.response.edit_message(embed=embed, view=self)

        # Remove from the database
        _ = """DELETE from ticker_leagues WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.channel.id, x) for x in sel.values]
        await itr.client.db.executemany(_, rows, timeout=60)

        # Remove from the parent channel's tracked leagues
        for i in sel.values:
            league = next(j for j in self.channel.leagues if j.url == i)
            self.channel.leagues.remove(league)

        # Send Confirmation Followup
        embed = Embed(title="Ticker", colour=Colour.red())
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

        embed = Embed(title="Ticker", colour=Colour.red())
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

        db = interaction.client.db
        sql = """DELETE FROM ticker_leagues WHERE channel_id = $1"""
        await db.execute(sql, self.channel.id)

        sql = """INSERT INTO ticker_leagues (channel_id, url)
            VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        args = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]
        await db.executemany(sql, args)

        self.channel.leagues.clear()
        for i in fs.DEFAULT_LEAGUES:
            comp = interaction.client.flashscore.get_competition(url=i)
            if comp:
                self.channel.leagues.append(comp)

        embed = Embed(title="Ticker: Tracked Leagues Reset")
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
        embed = Embed(colour=Colour.red())
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

        embed = Embed(colour=Colour.red())
        embed.description = f"The Ticker for {ment} was deleted."
        embed_utils.user_to_footer(embed, interaction.user)
        await view_itr.response.edit_message(embed=embed, view=None)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        await interaction.client.db.execute(sql, self.channel.id, timeout=60)


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

    @commands.command(name="ticker")
    async def tkr(self, ctx: commands.Context[Bot]) -> None:
        """Debug command - get the current number of ticker channels."""
        await ctx.send(f"{len(self.channels)} Ticker Channels found.")

    async def create(
        self,
        interaction: Interaction,
        channel: discord.TextChannel,
    ) -> TickerChannel | None:
        """Send a dialogue to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        invalidate = await self.bot.db.fetchrow(sql, channel.id)

        if invalidate:
            err = "🚫 You cannot create a ticker in a livescores channel."
            embed = Embed(colour=Colour.red(), description=err)
            reply = interaction.response.edit_message
            return await reply(embed=embed)

        ment = channel.mention
        view = view_utils.Confirmation(interaction.user, "Create", "Cancel")
        view.true.style = discord.ButtonStyle.blurple

        embed = Embed(title="Create a ticker")
        embed.description = f"{ment} has no ticker, create one?"
        await interaction.response.send_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = Embed(colour=Colour.red())
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
        records = await self.bot.db.fetch(sql)

        bad: list[int] = []

        for i in records:
            chan = self.bot.get_channel(i["channel_id"])
            if not isinstance(chan, discord.TextChannel):
                bad.append(i["channel_id"])
                continue

            tkrchan = TickerChannel(chan)
            await tkrchan.configure_channel()
            self.channels.append(tkrchan)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        if self.channels:
            await self.bot.db.executemany(sql, bad)
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
        team: fs.Team | None = None,
    ) -> TickerEvent | None:
        """Event handler for when something occurs during a fixture."""
        # Update the competition's Table on certain events.
        chans = [i for i in self.channels if fixture.competition in i.leagues]
        # TODO: Rebuild as an SQL Fetch.
        chans = [
            i
            for i in chans
            if {
                EVT.KICK_OFF: i.settings.kick_offs,
                EVT.GOAL: i.settings.goals,
                EVT.VAR_GOAL: i.settings.var_goal,
                EVT.RED_CARD: i.settings.red_cards,
                EVT.VAR_RED_CARD: i.settings.var_red_card,
                EVT.HALF_TIME: i.settings.half_times,
                EVT.SECOND_HALF_BEGIN: i.settings.second_halfs,
                EVT.FULL_TIME: i.settings.full_times,
                EVT.NORMAL_TIME_END: i.settings.full_times,
                EVT.SCORE_AFTER_EXTRA_TIME: i.settings.full_times,
                EVT.EXTRA_TIME_BEGIN: i.settings.extra_times,
                EVT.EXTRA_TIME_END: i.settings.extra_times,
                EVT.ET_HT_BEGIN: i.settings.ht_et_start,
                EVT.ET_HT_END: i.settings.et_2h_start,
                EVT.PENALTIES_BEGIN: i.settings.penalties,
                EVT.PENALTY_RESULTS: i.settings.penalties,
                EVT.FINAL_RESULT_ONLY: i.settings.final_results,
            }[event_type]
        ]

        if not chans:
            return

        TickerEvent(fixture, event_type, chans, team)

        if event_type == EVT.GOAL and fixture.competition:
            await self.refresh_table(fixture.competition)

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
            err = "🚫 You can't add club friendlies as a competition, sorry."
            embed = Embed(colour=Colour.red(), description=err)
            return await interaction.response.send_message(embed=embed)

        if competition.url is None:
            err = "🚫 Invalid competition selected. Error logged."
            embed = Embed(colour=Colour.red(), description=err)
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

        embed = Embed(title="Ticker: Tracked League Added")
        embed.description = f"{tkr_chan.channel.mention}\n\n{competition.url}"
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.response.send_message(embed=embed)

        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        await self.bot.db.execute(sql, channel.id, timeout=60)
        tkr_chan.leagues.append(competition)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: GuildChannel) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        await self.bot.db.execute(sql, channel.id, timeout=60)
        self.channels = [i for i in self.channels if i.id != channel.id]


async def setup(bot: Bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(TickerCog(bot))
