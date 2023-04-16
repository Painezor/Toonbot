"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import logging
from typing import Optional, TYPE_CHECKING, ClassVar, TypeAlias, cast

import discord
from discord.abc import GuildChannel
from discord.ext import commands
from playwright.async_api import TimeoutError as pw_TimeoutError

import ext.flashscore as fs
from ext.utils import embed_utils, view_utils

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
WORKER_COUNT = 2


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(
        self,
        fixture: fs.Fixture,
        event_type: fs.EventType,
        channels: list[TickerChannel],
        long: bool = False,
        home: Optional[bool] = None,
    ) -> None:
        self.fixture: fs.Fixture = fixture
        self.event_type: fs.EventType = event_type
        self.channels: list[TickerChannel] = channels
        self.long: bool = long
        self.home: Optional[bool] = home

        self.initial_embed: Optional[discord.Embed] = None

        self.bot = self.channels[0].bot

        # For exact event.
        self.event: Optional[fs.MatchEvent] = None

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

    async def embed(self) -> discord.Embed:
        """The embed for the fixture event."""
        if self.initial_embed is None:
            embed = await self.fixture.base_embed()

            embed.title = self.fixture.score_line
            embed.url = self.fixture.url
            embed.colour = self.event_type.colour
            embed.description = ""

            txt = self.event.__class__.__name__

            if self.home is None:
                embed.set_author(name=txt)
            elif self.home is True:
                embed.set_author(name=f"{txt} ({self.fixture.home.name})")
            else:
                embed.set_author(name=f"{txt} ({self.fixture.away.name})")

            comp = self.fixture.competition
            c_name = f" | {comp.title}" if comp else ""

            if isinstance(self.fixture.time, fs.GameState):
                if self.fixture.state:
                    short = self.fixture.state.shorthand
                    embed.set_footer(text=f"{short}{c_name}")
            else:
                embed.set_footer(text=f"{self.fixture.time}{c_name}")

            if self.event_type == fs.EventType.PENALTY_RESULTS:
                p_h = self.fixture.penalties_home
                p_a = self.fixture.penalties_away
                if p_h is None or p_a is None:
                    embed.description = self.fixture.score_line
                else:
                    hom, awa = ("**", "") if p_h > p_a else ("", "**")
                    score = f"{p_h} - {p_a}"
                    home = f"{hom}{self.fixture.home.name}{hom}"
                    away = f"{awa}{self.fixture.away.name}{awa}"
                    embed.description = f"{home} {score} {away}\n"

            self.initial_embed = embed
        else:
            embed = self.initial_embed

        # Fix Breaks.
        if self.event_type == fs.EventType.PENALTY_RESULTS:
            p_h = self.fixture.penalties_home
            p_a = self.fixture.penalties_away

            pens: list[fs.MatchEvent] = []
            for i in self.fixture.events:
                if not isinstance(i, fs.Penalty):
                    continue
                if not i.shootout:
                    continue
                pens.append(i)

            # iterate through everything after penalty header
            for team in set(i.team for i in pens):
                if value := [str(i) for i in pens if i.team == team]:
                    embed.add_field(name=team, value="\n".join(value))

        # Append our event
        if self.event is not None:
            embed.description = f"{embed.description}{str(self.event)}"
            if self.event.description:
                embed.description += f"\n\n> {self.event.description}"

        # Append extra info
        if (info := self.fixture.infobox) is not None:
            embed.add_field(name="Match Info", value=f"```yaml\n{info}```")
        return embed

    async def full_embed(self) -> discord.Embed:
        """Extended Embed with all events for Extended output event_type"""
        embed = await self.embed()
        embed.description = str(embed.description)

        if self.event is not None and len(self.fixture.events) > 1:
            embed.description += "\n```yaml\n--- Previous Events ---```"

        desc: list[str] = []
        for i in self.fixture.events:
            if i == self.event:
                continue

            if isinstance(i, fs.Substitution):
                continue  # skip subs, they're just spam.

            # Penalty Shootouts are handled in self.embed,
            # we don't need to duplicate.
            if isinstance(i, fs.Penalty) and i.shootout:
                continue

            if str(i) not in embed.description:  # Dupes bug.
                desc.append(str(i))

        embed.description += "\n".join(desc)
        return embed

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        if not self.channels:
            return  # This should never happen.

        # Handle Match Events with no game events.
        if self.event_type == fs.EventType.KICK_OFF:
            embed = await self.embed()
            for i in self.channels:
                await i.output(self, embed)
            return  # Done.

        index: Optional[int] = None
        for count in range(5):
            await self.fixture.refresh(self.bot)

            # Figure out which event we're supposed to be using
            # (Either newest event, or Stored if refresh)
            if index is None:
                if self.home is None:
                    team = None
                elif self.home is True:
                    team = self.fixture.home
                else:
                    team = self.fixture.away

                events = self.fixture.events
                teamed: list[fs.MatchEvent] = []
                if team is not None:
                    for i in events:
                        if not i.team:
                            continue

                        if team.name == i.team.name:
                            teamed.append(i)
                    events = teamed

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

            if self.long and index:
                evts = self.fixture.events[: index + 1]
                if all(i.is_done() for i in evts):
                    break
            else:
                if self.event and self.event.is_done():
                    break

            full = await self.full_embed() if self.long else None
            short = await self.embed()

            for chan in self.channels:
                await chan.output(self, short, full)

            await asyncio.sleep(count + 1 * 60)

        full = await self.full_embed() if self.long else None
        short = await self.embed()
        for chan in self.channels:
            await chan.output(self, short, full)


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    bot: ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: set[fs.Competition] = set()
        self.dispatched: dict[TickerEvent, discord.Message] = {}

        # Settings
        self.goals: Optional[bool] = None
        self.kick_offs: Optional[bool] = None
        self.full_times: Optional[bool] = None
        self.half_times: Optional[bool] = None
        self.second_halfs: Optional[bool] = None
        self.red_cards: Optional[bool] = None
        self.final_results: Optional[bool] = None
        self.penalties: Optional[bool] = None
        self.delays: Optional[bool] = None
        self.vars: Optional[bool] = None
        self.extra_times: Optional[bool] = None

    @property
    def id(self) -> int:  # pylint: disable=C0103
        """Pass Access to Parent"""
        return self.channel.id

    @property
    def mention(self) -> str:
        """Pass Access to Parent"""
        return self.channel.mention

    # Send messages
    async def output(
        self,
        event: TickerEvent,
        short_embed: discord.Embed,
        full_embed: Optional[discord.Embed] = None,
    ) -> Optional[discord.Message]:
        """Send the appropriate embed to this channel"""
        # Check if we need short or long embed.
        # For each stored db_field value,
        # we check against our own settings field.

        type_ = event.event_type

        embed = short_embed
        if full_embed is None or type_ == fs.EventType.KICK_OFF:
            pass

        elif type_ == fs.EventType.GOAL:
            if self.goals is True:
                embed = full_embed

        elif type_ == fs.EventType.HALF_TIME:
            if self.half_times is True:
                embed = full_embed

        elif type_ == fs.EventType.SECOND_HALF_BEGIN:
            if self.second_halfs is True:
                embed = full_embed

        elif type_ == fs.EventType.FULL_TIME:
            if self.full_times is True:
                embed = full_embed

        elif type_ == fs.EventType.FINAL_RESULT_ONLY:
            if self.final_results is True:
                embed = full_embed

        elif type_ == fs.EventType.PENALTY_RESULTS:
            if self.penalties is True:
                embed = full_embed

        else:
            logger.error("unhandled embed decision for evt %s", type_)

        try:
            try:
                message = self.dispatched[event]
                # Save on ratelimiting by checking.
                if message.embeds:
                    if message.embeds[0].description == embed.description:
                        return None
                message = await message.edit(embed=embed)
            except KeyError:
                message = await self.channel.send(embed=embed)
        except discord.HTTPException:
            return None

        self.dispatched[event] = message
        return message

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

        for record in leagues:
            if comp := self.bot.get_competition(record["url"].rstrip("/")):
                self.leagues.add(comp)
            else:
                logger.error("Could not find comp %s", record)


class TickerConfig(view_utils.DropdownPaginator):
    """Match Event Ticker View"""

    def __init__(self, invoker: User, tc: TickerChannel):
        self.channel: TickerChannel = tc

        options: list[discord.SelectOption] = []
        _ = filter(lambda i: i.url is not None, tc.leagues)
        leagues = list(sorted(_, key=lambda x: x.title))
        for i in leagues:
            assert i.url is not None  # Already Filtered.
            opt = discord.SelectOption(label=i.title, value=i.url)
            opt.description = i.url
            opt.emoji = i.flag
            options.append(opt)

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "Match Event Ticker config"
        embed.description = f"Tracked leagues for {tc.mention}\n\n```"

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
        if not (rows := [f"{i.flag} {i.markdown}" for i in leagues]):
            rows = [f"{tc.mention} has no tracked leagues."]

        super().__init__(invoker, embed, rows, options, footer="```")

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

        tuples: list[tuple[str, bool | None, int]] = []
        for i in sel.values:  # List of DB Fields.
            old = getattr(self.channel, i)
            new = {True: None, False: True, None: False}[old]
            setattr(self.channel, i, new)

            newset = {None: "Disabled", True: "Extended", False: "Short"}[new]
            embed.description += f"{i.replace('_', ' '.title())}: {newset}\n"
            tuples.append((i, new, self.channel.id))

        sql = """UPDATE ticker_settings SET $1 = $2 WHERE channel_id = $3"""
        async with itr.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, tuples)

        return await itr.response.edit_message(embed=embed, view=self)

    @discord.ui.select(placeholder="Remove Leagues", row=1)
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[TickerConfig]
    ) -> None:
        """When a league is selected, delete channel / league row from DB"""

        # Ask User to confirm their selection of data destruction
        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lg_text = "```yaml\n" + "\n".join(sorted(sel.values)) + "```"
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
            if (comp := interaction.client.get_competition(i)) is None:
                logger.info("Reset: Could not add default league %s", comp)
                continue
            self.channel.leagues.add(comp)

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

        interaction.client.ticker_channels.remove(self.channel)

        embed = discord.Embed(colour=discord.Colour.red())
        embed.description = f"The Ticker for {ment} was deleted."
        embed_utils.user_to_footer(embed, interaction.user)
        await view_itr.response.edit_message(embed=embed, view=None)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.channel.id)


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        TickerChannel.bot = bot
        self.workers: asyncio.Queue[Page] = asyncio.Queue(5)

    async def get_table(self, link: str):
        """Fetch the table for a competition from"""
        page = await self.workers.get()

        try:
            await page.goto(link, timeout=5000)

            # Chaining Locators is fucking stupid.
            # Thank you for coming to my ted talk.
            inner = page.locator(".tableWrapper")
            outer = page.locator("div", has=inner)
            table_div = page.locator("div", has=outer).last

            try:
                await table_div.wait_for(state="visible", timeout=5000)
            except pw_TimeoutError:
                return ""

            javascript = "ads => ads.forEach(x => x.remove());"
            await page.eval_on_selector_all(fs.ADS, javascript)

            image = await table_div.screenshot(type="png")
        finally:
            await self.workers.put(page)

        return await self.bot.dump_image(io.BytesIO(image))

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        await self.update_cache()
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
    ) -> Optional[TickerChannel]:
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
            await reply(embed=embed)
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
        self.bot.ticker_channels.append(chan)
        return chan

    async def update_cache(self) -> list[TickerChannel]:
        """Store a list of all Ticker Channels into the bot"""
        self.bot.ticker_channels.clear()
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
            self.bot.ticker_channels.append(tkrchan)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        if self.bot.ticker_channels:
            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    for _id in bad:
                        await connection.execute(sql, _id)
            logger.info("Deleted %s bad Ticker channels", len(bad))
        return self.bot.ticker_channels

    @commands.Cog.listener()
    async def on_fixture_event(
        self,
        event_type: fs.EventType,
        fixture: fs.Fixture,
        home: Optional[bool] = None,
    ) -> Optional[TickerEvent]:
        """Event handler for when something occurs during a fixture."""
        # Update the competition's Table on certain events.

        if not fixture.competition:
            return

        url = fixture.competition.url

        if url is None:
            return

        channels: list[TickerChannel] = []
        for i in self.bot.ticker_channels:
            if fixture.competition in i.leagues:
                channels.append(i)

        long = False

        evt = fs.EventType

        if event_type == evt.KICK_OFF:
            channels = [i for i in channels if i.kick_offs is not None]

        elif event_type == evt.GOAL:
            channels = [i for i in channels if i.goals is not None]

            if channels:
                fixture.competition.table = await self.get_table(url)

            long: bool = any([i.goals is True for i in channels])

        elif event_type == evt.VAR_GOAL:
            channels = [i for i in channels if None not in [i.goals, i.vars]]

            long: bool = any([all([i.goals, i.vars]) for i in channels])

        elif event_type == evt.RED_CARD:
            channels = [i for i in channels if i.red_cards is not None]

            long: bool = any([i.red_cards is True for i in channels])

        elif event_type == evt.VAR_RED_CARD:
            channels = [
                i for i in channels if None not in [i.red_cards, i.vars]
            ]

            long: bool = any([all([i.red_cards, i.vars]) for i in channels])

        elif event_type == evt.HALF_TIME:
            channels = [i for i in channels if i.half_times is not None]

            long: bool = any([i.half_times is True for i in channels])

        elif event_type == evt.SECOND_HALF_BEGIN:
            channels = [i for i in channels if i.second_halfs is not None]

            long: bool = any([i.second_halfs is True for i in channels])

        elif event_type in [
            evt.FULL_TIME,
            evt.NORMAL_TIME_END,
            evt.SCORE_AFTER_EXTRA_TIME,
        ]:
            channels = [i for i in channels if i.goals is not None]

            if channels:
                fixture.competition.table = await self.get_table(url)

            long: bool = any([i.full_times is True for i in channels])

        elif event_type in [evt.EXTRA_TIME_BEGIN, evt.EXTRA_TIME_END]:
            channels = [i for i in channels if i.extra_times is not None]

            long: bool = any([i.extra_times is True for i in channels])

        elif event_type == evt.HALF_TIME_ET_BEGIN:
            channels = [i for i in channels if i.extra_times is not None]
            channels = [i for i in channels if i.half_times is not None]

            for i in channels:
                if i.extra_times is True and i.half_times is True:
                    long = True
                    break

        elif event_type == evt.HALF_TIME_ET_END:
            channels = [i for i in channels if i.extra_times is not None]
            channels = [i for i in channels if i.second_halfs is not None]

            for i in channels:
                if i.extra_times is True and i.second_halfs is True:
                    long = True
                    break

        elif event_type in [evt.PENALTIES_BEGIN, evt.PENALTY_RESULTS]:
            channels = [i for i in channels if i.penalties is not None]

            long: bool = any([i.penalties is True for i in channels])

        elif event_type == evt.FINAL_RESULT_ONLY:
            channels = [i for i in channels if i.final_results is not None]

            long: bool = any([i.final_results is True for i in channels])

        else:
            logger.info("Ticker -- Unhandled Event Type %s", event_type)

        if not channels:
            return
        return TickerEvent(fixture, event_type, channels, long, home)

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
        channel: Optional[discord.TextChannel],
    ) -> None:
        """View the config of this channel's Match Event Ticker"""
        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        try:
            tkrs = self.bot.ticker_channels
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
        competition: fs.comp_trnsf,
        channel: Optional[discord.TextChannel],
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

        tickers = self.bot.ticker_channels
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

        tkr_chan.leagues.add(competition)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: GuildChannel) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        for i in self.bot.ticker_channels.copy():
            if i.channel.id == channel.id:
                self.bot.ticker_channels.remove(i)


async def setup(bot: Bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(Ticker(bot))
