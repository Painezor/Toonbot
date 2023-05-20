"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import logging
from pydantic import BaseModel
from typing import TYPE_CHECKING, TypeAlias, cast

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
else:
    Interaction = discord.Interaction

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
        EVT.SECOND_HALF_BEGIN: Colour.light_grey(),
        EVT.FULL_TIME: Colour.teal(),
        EVT.FINAL_RESULT_ONLY: Colour.teal(),
        EVT.SCORE_AFTER_EXTRA_TIME: Colour.teal(),
        EVT.PERIOD_BEGIN: Colour.light_grey(),
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
        EVT.RESUMED: Colour.light_grey(),
        # Penalties
        EVT.PENALTIES_BEGIN: Colour.gold(),
        EVT.PENALTY_RESULTS: Colour.dark_gold(),
    }

    def __init__(self, event: TickerEvent, extended: bool = False) -> None:
        try:
            clr = self.EMBED_COLOURS[event.event_type]
        except KeyError:
            logger.error("Failed to get event colour", event.event_type)
            clr = Colour.blurple()

        super().__init__(colour=clr)
        self.event = event

        self.url = event.fixture.url
        self.title = event.fixture.score_line
        self.description = ""

        self.event_to_header()
        self.comp_to_footer()

        if event.event_type == EVT.PENALTY_RESULTS:
            self.handle_pens()

        if extended:
            rev = reversed(event.fixture.incidents)

            if self.event.event_type in [EVT.GOAL, EVT.VAR_GOAL]:
                evt = next(i for i in rev if i.svg_class == "soccer")
                self.description = self.parse_incident(evt)

            elif self.event.event_type is EVT.RED_CARD:
                evt = next(i for i in rev if i.svg_class == "redCard-ico")

                self.description = self.parse_incident(evt)

            else:
                evt = None

            if evt is not None and evt.description:
                self.description += f"\n\n> {evt.description}"

        if (info := event.fixture.infobox) is not None:
            self.add_field(name="Match Info", value=f"```yaml\n{info}```")

        if extended:
            self.write_all()

    def event_to_header(self) -> None:
        name = self.event.event_type.value
        if self.event.team:
            name = f"{name} ({self.event.team.name})"
            self.set_author(name=name, icon_url=self.event.team.logo_url)
        else:
            self.set_author(name=name)

    def comp_to_footer(self) -> None:
        if comp := self.event.fixture.competition:
            self.set_footer(text=comp.title, icon_url=comp.logo_url)
            self.set_thumbnail(url=comp.logo_url)

    def parse_incident(self, incident: fs.MatchIncident) -> str:
        """Get a string representation of the match incident"""

        key = incident.svg_class.rsplit(maxsplit=1)[-1].strip()
        try:
            emote = {
                "card": fs.YELLOW_CARD_EMOJI,
                "card-ico": fs.YELLOW_CARD_EMOJI,
                "footballOwnGoal-ico": f"{fs.GOAL_EMOJI}OG",
                "red-yellow-card": fs.RED_CARD_EMOJI + fs.YELLOW_CARD_EMOJI,
                "soccer": fs.GOAL_EMOJI,
                "substitution": fs.INBOUND_EMOJI,
                "var": fs.VAR_EMOJI,
                "warning": fs.WARNING_EMOJI,
                "yellowCard-ico": fs.YELLOW_CARD_EMOJI,
            }[key]
        except KeyError:
            logger.error("missing emote for %s", key)
            emote = ""

        output = f"`{incident.time}` {emote}"

        if incident.team is not None:
            output += f" {incident.team.tag}"

        if incident.player:
            output += f" [{incident.player.name}]({incident.player.url})"

        if incident.note:
            output += f" ({incident.note})"

        if incident.assist:
            output += f" ([{incident.assist.name}]({incident.assist.url})"
        return output

    def handle_pens(self) -> None:
        """Add fields to the embed with the results of the penalties"""
        fix = self.event.fixture
        fxe = fix.incidents

        pens = [i for i in fxe if "Penalty" in i.type and "'" not in i.time]

        for j in [fix.home.team, fix.away.team]:
            if value := [self.parse_incident(i) for i in pens if i.team == j]:
                self.add_field(name=j.name, value="\n".join(value))

    def write_all(self) -> None:
        evts = self.event.fixture.incidents
        self.description = "\n".join(self.parse_incident(i) for i in evts)


class TickerEventView(view_utils.BaseView):
    def __init__(self, event: TickerEvent) -> None:
        super().__init__(None, timeout=None)
        self.remove_item(self._stop)  # Hide the stop button.
        self.event: TickerEvent = event

    @discord.ui.button(label="Show all events", emoji="ℹ")
    async def callback(
        self, interaction: Interaction, btn: discord.ui.Button[TickerEventView]
    ) -> None:
        """Send an emphemeral list of all events to the invoker"""
        temb = TickerEmbed(self.event)
        temb.write_all()
        try:
            await interaction.response.send_message(embed=temb, ephemeral=True)
        except Exception as err:
            logger.error("Failed to send extenderview", exc_info=True)
            raise err


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(
        self,
        bot: Bot,
        fixture: fs.Fixture,
        event_type: EVT,
        channels: list[discord.TextChannel],
        team: fs.Team | None = None,
    ) -> None:
        self.bot: Bot = bot
        self.fixture: fs.Fixture = fixture
        self.event_type: EVT = event_type
        self.channels: list[discord.TextChannel] = channels
        self.team: fs.Team | None = team

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

        self.messages: dict[discord.TextChannel, Message] = {}
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
        view = TickerEventView(self)

        for chan in self.channels:
            # Send messages
            if chan not in self.messages:
                try:
                    message = await chan.send(embed=embed, view=view)
                except discord.Forbidden:
                    _ = """DELETE FROM ticker_channels WHERE channel_id = $1"""
                    await self.bot.db.execute(_, chan.id)
                    self.channels.remove(chan)
                    continue
            else:
                message = self.messages[chan]
                message = await message.edit(embed=embed, view=view)
            self.messages[chan] = message

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        if self.event_type == EVT.KICK_OFF:
            return await self._dispatch()

        # Handle Match Events with no game events.
        for count in range(5):
            page = await self.bot.browser.new_page()
            try:
                await self.fixture.fetch(page)
            finally:
                await page.close()

            if all(i.player is not None for i in self.fixture.incidents):
                break

            await self._dispatch()
            await asyncio.sleep(count + 1 * 60)

        await self._dispatch()


class Config(view_utils.DropdownPaginator):
    """Match Event Ticker View"""

    _db_table = "ticker_settings"
    channel: discord.TextChannel
    leagues: list[fs.Competition] = []
    settings: TickerSettings

    def __init__(
        self,
        invoker: User,
        channel: discord.TextChannel,
        leagues: list[fs.Competition],
        settings: TickerSettings,
    ):
        self.channel = channel
        self.leagues = leagues
        self.leagues.sort(key=lambda i: i.title)
        self.settings = settings

        options: list[discord.SelectOption] = []
        for i in self.leagues:
            if i.url is None:
                continue

            flag = flags.get_flag(i.country)
            opt = discord.SelectOption(label=i.title, value=i.url, emoji=flag)
            opt.description = i.url
            options.append(opt)

        embed = Embed(colour=Colour.dark_teal())
        embed.set_author(name="Match Event Ticker config")
        embed.description = f"Tracked leagues for {self.channel.mention}\n"

        # Permission Checks
        missing: list[str] = []
        perms = self.channel.permissions_for(self.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        # Handle Empty
        rows: list[str] = []
        for i in self.leagues:
            rows.append(f"{flags.get_flag(i.country)} [{i.name}]({i.url})")

        if not rows:
            rows += [f"{self.channel.mention} has no tracked leagues."]

        super().__init__(invoker, embed, rows, options)

        self.stg.options = self.generate_settings()

    @classmethod
    async def start(
        cls, bot: Bot, channel: discord.TextChannel, invoker: User
    ) -> Config:
        sql = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
        stg = await bot.db.fetchrow(sql, channel.id)
        sql = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
        records = await bot.db.fetch(sql, channel.id)
        leagues = [bot.cache.get_competition(url=r["url"]) for r in records]
        leagues_ = [i for i in leagues if i is not None]
        settings = TickerSettings.parse_obj(stg)
        return Config(invoker, channel, leagues_, settings)

    def generate_settings(self) -> list[discord.SelectOption]:
        """Generate Dropdown for settings configuration"""

        options: list[discord.SelectOption] = []
        for k, val in iter(self.settings):
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
    async def stg(self, itr: Interaction, sel: Select[Config]) -> None:
        """Regenerate view and push to message"""
        embed = Embed(title="Settings updated", colour=Colour.dark_teal())
        embed.description = ""
        embed_utils.user_to_footer(embed, itr.user)

        async with itr.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                for i in sel.values:  # List of DB Fields.
                    old = getattr(self.settings, i)
                    setattr(self.settings, i, not old)

                    alias = i.replace("_", " ").title()
                    embed.description += f"{alias}: {not old}\n"
                    sql = f"""UPDATE {self._db_table} SET {i} = NOT {i}
                            WHERE channel_id = $1"""
                    await connection.execute(sql, self.channel.id)

        sel.options = self.generate_settings()
        return await itr.response.edit_message(embed=embed, view=self)

    @discord.ui.select(placeholder="Remove Leagues", row=1)
    async def dropdown(self, itr: Interaction, sel: Select[Config]) -> None:
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

        rsp = view.interaction.response

        if not view.value:
            # Return to normal viewing
            embed = self.embeds[self.index]
            return await rsp.edit_message(embed=embed, view=self)

        # Remove from the database
        _ = """DELETE from ticker_leagues WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.channel.id, x) for x in sel.values]
        await itr.client.db.executemany(_, rows, timeout=60)

        # Remove from the parent channel's tracked leagues
        for i in sel.values:
            league = next(j for j in self.leagues if j.url == i)
            self.leagues.remove(league)

        # Send Confirmation Followup
        embed = Embed(title="Ticker", colour=Colour.red())
        ment = self.channel.mention
        embed.description = f"Removed {ment} tracked leagues:\n{lg_text}"
        embed_utils.user_to_footer(embed, itr.user)
        await itr.followup.send(embed=embed)

        # Reinstantiate the view
        cfg = Config(itr.user, self.channel, self.leagues, self.settings)
        try:
            cfg.index = self.index
            embed = cfg.embeds[cfg.index]
        except IndexError:
            cfg.index = self.index - 1
            embed = cfg.embeds[cfg.index]
        await rsp.edit_message(view=view, embed=embed)

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
            embed = self.embeds[self.index]
            await view_itr.response.edit_message(embed=embed, view=self)
            return

        db = interaction.client.db
        sql = """DELETE FROM ticker_leagues WHERE channel_id = $1"""
        await db.execute(sql, self.channel.id)

        sql = """INSERT INTO ticker_leagues (channel_id, url)
            VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        args = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]
        await db.executemany(sql, args)

        self.leagues.clear()
        for i in fs.DEFAULT_LEAGUES:
            comp = interaction.client.cache.get_competition(url=i)
            if comp:
                self.leagues.append(comp)

        embed = Embed(title="Ticker: Tracked Leagues Reset")
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)

        # Reinstantiate the view
        user = interaction.user
        cfg = Config(user, self.channel, self.leagues, self.settings)
        await view_itr.response.edit_message(view=view, embed=cfg.embeds[0])

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
            embed = self.embeds[self.index]
            await view_itr.response.edit_message(embed=embed, view=self)
            return

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
        self.workers: asyncio.Queue[Page] = asyncio.Queue(5)

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        for _ in range(WORKER_COUNT):
            page = await self.bot.browser.new_page()
            await self.workers.put(page)

    async def cog_unload(self) -> None:
        while not self.workers.empty():
            page = await self.workers.get()
            await page.close()

    async def create(
        self,
        interaction: Interaction,
        channel: discord.TextChannel,
    ) -> Config | None:
        """Send a dialogue to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        invalidate = await self.bot.db.fetchrow(sql, channel.id)

        if invalidate:
            err = "🚫 You cannot create a ticker in a livescores channel."
            embed = Embed(colour=Colour.red(), description=err)
            await interaction.response.edit_message(embed=embed)
            return None

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
        return await Config.start(self.bot, channel, interaction.user)

    async def refresh_table(self, comp: fs.Competition) -> None:
        """Refresh table for object"""
        if "friendly" in comp.name.casefold():
            return  # No.

        page = await self.workers.get()
        try:
            image = await comp.get_table(page)
        finally:
            await self.workers.put(page)

        if image is None:
            return

        file = discord.File(fp=io.BytesIO(image), filename="table.png")
        channel = self.bot.get_channel(874655045633843240)
        if not isinstance(channel, discord.TextChannel):
            return None

        url = (await channel.send(file=file)).attachments[0].url
        self.bot.dispatch("table_update", comp, url)

    @commands.Cog.listener()
    async def on_fixture_event(
        self,
        event_type: EVT,
        fixture: fs.Fixture,
        team: fs.Team | None = None,
    ) -> None:
        """Event handler for when something occurs during a fixture."""
        if fixture.competition is None:
            return

        # Update the competition's Table on certain events.
        fields = {
            EVT.KICK_OFF: ["kick_offs"],
            EVT.GOAL: ["goals"],
            EVT.VAR_GOAL: ["vars", "goals"],
            EVT.RED_CARD: ["red_cards"],
            EVT.VAR_RED_CARD: ["vars", "red_cards"],
            EVT.HALF_TIME: ["half_times"],
            EVT.SECOND_HALF_BEGIN: ["second_halfs"],
            EVT.FULL_TIME: ["full_times"],
            EVT.NORMAL_TIME_END: ["full_times"],
            EVT.SCORE_AFTER_EXTRA_TIME: ["full_times"],
            EVT.EXTRA_TIME_BEGIN: ["extra_times"],
            EVT.EXTRA_TIME_END: ["extra_times"],
            EVT.ET_HT_BEGIN: ["half_times", "extra_times"],
            EVT.ET_HT_END: ["extra_times", "second_halfs"],
            EVT.PENALTIES_BEGIN: ["penalties"],
            EVT.PENALTY_RESULTS: ["penalties"],
            EVT.FINAL_RESULT_ONLY: ["final_results"],
        }[event_type]

        sql = """
            SELECT ticker_settings.channel_id
            FROM ticker_settings INNER JOIN ticker_leagues
            ON ticker_settings.channel_id = ticker_leagues.channel_id WHERE
            url = $1 AND """ + " AND ".join(
            f"{i} IS TRUE" for i in fields
        )

        records = await self.bot.db.fetch(sql, fixture.competition.url)
        bad: list[int] = []
        chans: list[discord.TextChannel] = []
        for i in records:
            chan = self.bot.get_channel(i["channel_id"])
            if not isinstance(chan, discord.TextChannel):
                continue

            if chan.is_news():
                continue

            chans.append(chan)

        DEBUG_CHANNEL = self.bot.get_channel(1107975381501353994)
        if isinstance(DEBUG_CHANNEL, discord.TextChannel):
            chans.append(DEBUG_CHANNEL)

        if bad:
            logger.error("Got %s bad text channels in ticker", len(bad))

        if not chans:
            return

        TickerEvent(self.bot, fixture, event_type, chans, team)

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
        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        sql = "SELECT channel_id FROM ticker_channels WHERE channel_id = $1"
        record = await self.bot.db.fetchrow(sql, channel.id)

        if record is None:
            view = await self.create(interaction, channel)

            if view is None:
                return
        else:
            view = await Config.start(self.bot, channel, interaction.user)
        emb = view.embeds[0]
        await interaction.response.send_message(view=view, embed=emb)

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

        sql = "SELECT channel_id FROM ticker_channels WHERE channel_id = $1"
        record = await self.bot.db.fetchrow(sql, channel.id)

        if record is None:
            view = await self.create(interaction, channel)

            if view is None:
                return

        embed = Embed(title="Ticker: Tracked League Added")
        embed.description = f"{channel.mention}\n\n{competition.url}"
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.response.send_message(embed=embed)

        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        await self.bot.db.execute(sql, channel.id, competition.url, timeout=60)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: GuildChannel) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        await self.bot.db.execute(sql, channel.id, timeout=60)


async def setup(bot: Bot) -> None:
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(TickerCog(bot))
