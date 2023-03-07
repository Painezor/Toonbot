"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import typing
import logging
import asyncpg

from playwright.async_api import TimeoutError as pw_TimeoutError

import discord
from discord.ext import commands
from ext.fixtures import CompetitionTransformer

import ext.toonbot_utils.flashscore as fs

from ext.toonbot_utils.gamestate import GameState
import ext.toonbot_utils.matchevents as m_evt
from ext.utils import embed_utils, view_utils

if typing.TYPE_CHECKING:
    from core import Bot


class IsLiveScoreError(Exception):
    """Raise this when someone tries to create a ticker
    in a livescore channel."""


_ticker_tasks = set()

logger = logging.getLogger("ticker.py")


async def get_table(bot: Bot, link: str):

    page = await bot.browser.new_page()
    await page.goto(link, timeout=5000)

    # Chaining Locators is fucking aids.
    # Thank you for coming to my ted talk.
    inner = page.locator(".tableWrapper")
    outer = page.locator("div", has=inner)
    table_div = page.locator("div", has=outer).last

    try:
        await table_div.wait_for(state="visible", timeout=5000)
    except pw_TimeoutError:
        return ""

    js = "ads => ads.forEach(x => x.remove());"
    await page.eval_on_selector_all(fs.ADS, js)

    image = await table_div.screenshot(type="png")
    await page.close()
    return await bot.dump_image(io.BytesIO(image))


async def lg_ac(
    interaction: discord.Interaction[Bot], cur: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete from list of stored leagues"""
    cur = cur.casefold()

    choices = []
    for i in interaction.client.competitions:
        if not i.id:
            continue

        if cur in i.title.casefold():
            name = i.title[:100]
            choices.append(discord.app_commands.Choice(name=name, value=i.id))

        if len(choices) == 25:
            break
    return choices


# TODO: Migrate Event embed generation to the individual Events
class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    bot: typing.ClassVar[Bot]

    def __init__(
        self,
        fixture: fs.Fixture,
        event_type: m_evt.EventType,
        channels: list[TickerChannel],
        long: bool,
        home: typing.Optional[bool] = None,
    ) -> None:

        self.fixture: fs.Fixture = fixture
        self.event_type: m_evt.EventType = event_type
        self.channels: list[TickerChannel] = channels
        self.long: bool = long
        self.home: typing.Optional[bool] = home

        # For exact event.
        self.event: typing.Optional[m_evt.MatchEvent] = None

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

    async def embed(self) -> discord.Embed:
        """The embed for the fixture event."""
        e = await self.fixture.base_embed()
        e = e.copy()

        e.title = self.fixture.score_line
        e.url = self.fixture.url
        e.colour = self.event_type.colour
        e.description = ""

        # Fix Breaks.
        b = self.fixture.breaks
        m = self.event_type.value.replace("#PERIOD#", f"{b + 1}")

        {
            None: e.set_author(name=m),
            True: e.set_author(name=f"{m} ({self.fixture.home.name})"),
            False: e.set_author(name=f"{m} ({self.fixture.away.name})"),
        }[self.home]

        if self.event_type == m_evt.EventType.PENALTY_RESULTS:
            ph = self.fixture.penalties_home
            pa = self.fixture.penalties_away
            if ph is None or pa is None:
                e.description = self.fixture.score_line
            else:
                h, a = ("**", "") if ph > pa else ("", "**")
                score = f"{ph} - {pa}"
                home = f"{h}{self.fixture.home.name}{h}"
                away = f"{a}{self.fixture.away.name}{a}"
                e.description = f"{home} {score} {away}\n"

            pens = []
            for i in self.fixture.events:
                if not isinstance(i, m_evt.Penalty):
                    continue
                if not i.shootout:
                    continue
                pens.append(i)

            # iterate through everything after penalty header
            for team in set(i.team for i in pens):
                if value := [str(i) for i in pens if i.team == team]:
                    e.add_field(name=team, value="\n".join(value))

        # Append our event
        if self.event is not None:
            e.description += str(self.event)
            if self.event.description:
                e.description += f"\n\n> {self.event.description}"

        # Append extra info
        if (ib := self.fixture.infobox) is not None:
            e.add_field(name="Match Info", value=f"```yaml\n{ib}```")

        comp = self.fixture.competition
        c = f" | {comp.title}" if comp else ""

        if isinstance(self.fixture.time, GameState):
            if self.fixture.state:
                sh = self.fixture.state.shorthand
                e.set_footer(text=f"{sh}{c}")
        else:
            e.set_footer(text=f"{self.fixture.time}{c}")
        self._embed = e
        return e

    async def full_embed(self) -> discord.Embed:
        """Extended Embed with all events for Extended output event_type"""
        e = await self.embed()
        e.description = ""

        if self.event is not None and len(self.fixture.events) > 1:
            e.description += "\n```yaml\n--- Previous Events ---```"

        desc = []
        for i in self.fixture.events:
            if isinstance(i, m_evt.Substitution):
                continue  # skip subs, they're just spam.

            # Penalty Shootouts are handled in self.embed,
            # we don't need to duplicate.
            if isinstance(i, m_evt.Penalty) and i.shootout:
                continue

            if str(i) not in e.description:  # Dupes bug.
                desc.append(str(i))

        e.description += "\n".join(desc)

        self._full_embed = e
        return e

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        if not self.channels:
            return  # This should never happen.

        # Handle Match Events with no game events.
        if self.event_type == m_evt.EventType.KICK_OFF:
            e = await self.embed()
            for x in self.channels:
                await x.output(self, e)
            return  # Done.

        index: typing.Optional[int] = None
        for x in range(5):
            await self.fixture.refresh(self.bot)

            # Figure out which event we're supposed to be using
            # (Either newest event, or Stored if refresh)
            if index is None:
                team = {
                    None: None,
                    False: self.fixture.away,
                    True: self.fixture.home,
                }[self.home]

                events = self.fixture.events
                if team is not None:
                    t = team.name
                    evt = filter(lambda i: i.team and i.team.name == t, events)
                    events = list(evt)

                valid: typing.Type[
                    m_evt.MatchEvent
                ] = self.event_type.valid_events
                if valid and events:
                    events.reverse()
                    try:
                        ev = [i for i in events if isinstance(i, valid)][0]
                        self.event = ev
                        index = self.fixture.events.index(self.event)
                    except IndexError:
                        ev = "\n".join(set(str(type(i)) for i in events))
                        logger.error("Can't find %s in %s", valid, ev)
                        logger.error(f"Event is {self.event_type}")

            else:
                try:
                    self.event = self.fixture.events[index]
                except IndexError:
                    self.event = None
                    break

            if self.long and index:
                evts = self.fixture.events[: index + 1]
                if all(i.player is not None for i in evts):
                    break
            else:
                if self.event and self.event.player:
                    break

            full = await self.full_embed() if self.long else None
            short = await self.embed()

            for ch in self.channels:
                await ch.output(self, short, full)

            await asyncio.sleep(x + 1 * 60)

        full = await self.full_embed() if self.long else None
        short = await self.embed()
        for ch in self.channels:
            await ch.output(self, short, full)


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    bot: typing.ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: list[str] = []
        self.settings: dict = {}
        self.dispatched: dict[TickerEvent, discord.Message] = {}

    # Send messages
    async def output(
        self,
        event: TickerEvent,
        e: discord.Embed,
        full_embed: typing.Optional[discord.Embed] = None,
    ) -> typing.Optional[discord.Message]:
        """Send the appropriate embed to this channel"""
        # Check if we need short or long embed.
        # For each stored db_field value,
        # we check against our own settings field.
        if not self.settings:
            await self.get_settings()

        for x in event.event_type.db_fields:
            if not self.settings[x]:
                e = e
                break
        else:
            e = full_embed if full_embed is not None else e

        try:
            try:
                message = self.dispatched[event]
                if message.embeds[0].description != e.description:
                    # Save on ratelimiting by checking.
                    message = await message.edit(embed=e)
            except KeyError:
                message = await self.channel.send(embed=e)
        except discord.HTTPException:
            return None

        self.dispatched[event] = message
        return message

    # Database management.
    async def get_settings(self) -> dict:
        """Retrieve the settings of the TickerChannel from the database"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                stg = await connection.fetchrow(
                    """SELECT * FROM ticker_settings WHERE channel_id = $1""",
                    self.channel.id,
                )
                leagues = await connection.fetch(
                    """SELECT * FROM ticker_leagues WHERE channel_id = $1""",
                    self.channel.id,
                )

        if stg is not None:
            for k, v in stg.items():
                if k == "channel_id":
                    continue
                self.settings[k] = v

        self.leagues = [r["league"] for r in leagues]
        return self.settings

    async def create_ticker(self) -> TickerChannel:
        """Create a ticker for the target channel"""
        guild = self.channel.guild.id

        rows = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]

        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():

                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

                invalidate = await connection.fetchrow(q, self.channel.id)
                if invalidate:
                    raise IsLiveScoreError

                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild)

                q = """INSERT INTO ticker_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, guild, self.channel.id)

                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)
                        ON CONFLICT DO NOTHING"""
                await connection.execute(qq, self.channel.id)

                qqq = """INSERT INTO ticker_leagues (channel_id, url)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.executemany(qqq, rows)
        return self

    async def remove_leagues(self, leagues: list[str]) -> list[str]:
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from ticker_leagues
                 WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.channel.id, x) for x in leagues]
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues


class ToggleButton(discord.ui.Button):
    """A Button to toggle the ticker settings."""

    view: TickerConfig

    def __init__(self, db_key: str, value: bool | None, row: int = 0):
        self.value: bool | None = value
        self.db_key: str = db_key

        if value is None:
            emoji = "🔴"  # None (Off)
            style = discord.ButtonStyle.red
        elif value:
            emoji = "🔵"
            style = discord.ButtonStyle.blurple
        else:
            emoji = "🟢"
            style = discord.ButtonStyle.green

        title = db_key.replace("_", " ").title()

        if title == "Goal":
            title = "Goals"
        elif title == "Red Card":
            title = "Red Cards"
        elif title == "Var":
            title = "VAR Reviews"
        elif title == "Penalties":
            title = "Penalty Shootouts"
        super().__init__(label=title, emoji=emoji, row=row, style=style)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Set view value to button value"""

        await interaction.response.defer()

        # Rotate between the three values.
        new_value = {True: None, False: True, None: False}[self.value]

        bot = interaction.client
        sql = f"""UPDATE ticker_settings SET {self.db_key} = $1
               WHERE channel_id = $2"""
        ch = self.view.tc.channel.id
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, new_value, ch)

        self.view.tc.settings[self.db_key] = new_value
        return await self.view.update()


class ResetLeagues(discord.ui.Button):
    """Button to reset a ticker back to the default leagues"""

    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(
            label="Reset to default leagues", style=discord.ButtonStyle.primary
        )

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Click button reset leagues"""
        await interaction.response.defer()

        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        rows = [(self.view.tc.channel.id, x) for x in fs.DEFAULT_LEAGUES]
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        self.view.tc.leagues = fs.DEFAULT_LEAGUES

        ch = self.view.tc.channel.mention
        e = discord.Embed(colour=discord.Colour.red())
        e.description = f"Tracked leagues for {ch} reset"
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        await interaction.followup.send(embed=e)
        return await self.view.update()


class DeleteTicker(discord.ui.Button):
    """Button to delete a ticker entirely"""

    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=discord.ButtonStyle.red)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Click button delete ticker"""

        await interaction.response.defer()
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.view.tc.channel.id)
        interaction.client.ticker_channels.remove(self.view.tc)

        e = discord.Embed(colour=discord.Colour.red())

        ch = self.view.tc.channel.mention
        e.description = f"The Ticker for {ch} was deleted."
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        await interaction.followup.send(embed=e)
        return await interaction.edit_original_response(embed=e, view=None)


class RemoveLeague(discord.ui.Select):
    """Dropdown to remove leagues from a match event ticker."""

    view: TickerConfig

    def __init__(self, leagues: list[str], row: int = 2) -> None:
        leagues = sorted(set(leagues))
        super().__init__(
            placeholder="Remove tracked league(s)",
            row=row,
            max_values=len(leagues),
        )
        # No idea how we're getting duplicates here but fuck it I don't care.
        for lg in leagues:
            self.add_option(label=lg)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When a league is selected, delete channel / league row from DB"""

        await interaction.response.defer()
        return await self.view.remove_leagues(self.values)


class TickerConfig(view_utils.BaseView):
    """Match Event Ticker View"""

    interaction: discord.Interaction[Bot]
    bot: Bot

    def __init__(
        self, interaction: discord.Interaction[Bot], tc: TickerChannel
    ):
        super().__init__(interaction)
        self.tc: TickerChannel = tc

    async def remove_leagues(
        self, leagues: list[str]
    ) -> discord.InteractionMessage:
        """Bulk remove leagues from a ticker channel"""
        # Ask user to confirm their choice.
        i = self.interaction
        view = view_utils.Confirmation(
            i, "Remove", "Cancel", discord.ButtonStyle.red
        )
        lg_text = "```yaml\n" + "\n".join(sorted(leagues)) + "```"

        ch = self.tc.channel

        e = discord.Embed(title="Transfer Ticker", colour=discord.Colour.red())
        e.description = f"Remove these leagues from {ch.mention}?\n{lg_text}"
        await self.interaction.edit_original_response(embed=e, view=view)
        await view.wait()

        if not view.value:
            return await self.update(content="No leagues were removed")

        await self.tc.remove_leagues(leagues)
        return await self.update(
            content=f"Removed {ch.mention} tracked leagues: {lg_text}"
        )

    async def creation_dialogue(self) -> bool:
        """Send a dialogue to check if the user wishes
        to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        if self.tc.channel.id in [
            i.channel.id for i in self.bot.score_channels
        ]:
            err = "You cannot create a ticker in a livescores channel."
            await self.bot.error(self.interaction, err)
            return False

        c = self.tc.channel.mention
        btn = discord.ButtonStyle.green
        view = view_utils.Confirmation(
            self.interaction, "Create ticker", "Cancel", btn
        )
        notkr = f"{c} does not have a ticker, would you like to create one?"
        await self.interaction.edit_original_response(content=notkr, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {c}"
            self.stop()
            view.clear_items()
            await self.bot.error(self.interaction, txt)
            return False

        try:
            await self.tc.create_ticker()
        except IsLiveScoreError:
            err = "You cannot add tickers to a livescores channel."
            await self.bot.error(self.interaction, err)
            return False

        self.bot.ticker_channels.append(self.tc)
        await self.update(content=f"A ticker was created for {c}")
        return True

    async def update(
        self, content: typing.Optional[str] = None
    ) -> discord.InteractionMessage:
        """Regenerate view and push to message"""
        self.clear_items()

        if not self.tc.settings:
            await self.tc.get_settings()

        c = discord.Colour.dark_teal()
        embed = discord.Embed(colour=c, title="Match Event Ticker config")

        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        t = "Button Colour Key\nRed: Off, Green: On, Blue: Extended"
        embed.set_footer(text=t)

        missing = []

        ch = self.tc.channel
        perms = ch.permissions_for(ch.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = (
                "```yaml\nThis ticker channel will not work currently"
                f"I am missing the following permissions.\n{missing}```"
            )
            embed.add_field(name="Missing Permissions", value=v)

        edit = self.interaction.edit_original_response
        if not self.tc.leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            embed.description = f"{ch.mention} has no tracked leagues."
            return await edit(content=content, embed=embed, view=self)

        header = f"Tracked leagues for {ch.mention}```yaml\n"

        rows = sorted(self.tc.leagues)
        embeds = embed_utils.rows_to_embeds(embed, rows, 10, header, "```")

        self.pages = embeds

        self.add_page_buttons()

        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = self.pages[-1]

        if len(self.tc.leagues) > 25:
            # Get everything after index * 25 (page len), then up to
            # 25 items from that page.
            remove_list = self.tc.leagues[self.index * 25 :][:25]
        else:
            remove_list = self.tc.leagues

        if remove_list:
            self.add_item(RemoveLeague(remove_list, row=1))

        count = 0
        for k, v in self.tc.settings.items():
            # We don't need a button for channel_id,
            # it's just the database key.
            if k == "channel_id":
                continue
            row = 2 + count // 5
            self.add_item(ToggleButton(db_key=k, value=v, row=row))

            count += 1

        return await edit(content=content, embed=embed, view=self)


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        TickerEvent.bot = bot
        TickerChannel.bot = bot

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        await self.update_cache()

    async def update_cache(self) -> None:
        """Store a list of all Ticker Channels into the bot"""
        sql = """SELECT DISTINCT channel_id FROM transfers_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        for r in records:
            ch = self.bot.get_channel(r["channel_id"])
            if ch is None:
                continue
            ch = typing.cast(discord.TextChannel, ch)

            tc = TickerChannel(ch)
            await tc.get_settings()
            self.bot.ticker_channels.append(tc)

    @commands.Cog.listener()
    async def on_fixture_event(
        self,
        event_type: m_evt.EventType,
        fixture: fs.Fixture,
        home: typing.Optional[bool] = None,
    ) -> typing.Optional[TickerEvent]:
        """Event handler for when something occurs during a fixture."""
        # Update the competition's Table on certain events.
        if not fixture.competition:
            return

        flds = event_type.db_fields
        c: str = ", ".join(flds)
        not_nulls = " AND ".join([f"({x} IS NOT NULL)" for x in flds])
        sql = f"""SELECT {c}, ticker_settings.channel_id FROM ticker_settings
                  LEFT JOIN ticker_leagues ON ticker_settings.channel_id =
                  ticker_leagues.channel_id WHERE {not_nulls}
                  AND (link = $1::text)"""

        url = fixture.competition.url
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, url)

        if records:
            match event_type:
                case m_evt.EventType.GOAL | m_evt.EventType.FULL_TIME:
                    url = f"{fixture.competition.url}/standings/"
                    fixture.competition.table = await get_table(self.bot, url)

        channels: list[TickerChannel] = []
        long: bool = False

        r: asyncpg.Record
        score_channels = [i.channel.id for i in self.bot.score_channels]
        tickers = self.bot.ticker_channels.copy()

        for r in records:
            # Validate this channel is suitable for message output.
            ch_id = r["channel_id"]
            if ch_id in score_channels:
                continue

            channel = self.bot.get_channel(ch_id)
            if channel is None:
                continue

            channel = typing.cast(discord.TextChannel, channel)

            if channel.is_news():
                continue

            perms = channel.permissions_for(channel.guild.me)
            if not perms.send_messages or not perms.embed_links:
                continue

            if all(x for x in r):
                long = True

            try:
                tc = next(i for i in tickers if i.channel.id == channel.id)
            except StopIteration:
                tc = TickerChannel(channel)
                self.bot.ticker_channels.append(tc)
            channels.append(tc)

        if channels:
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
        interaction: discord.Interaction[Bot],
        channel: typing.Optional[discord.TextChannel],
    ) -> discord.InteractionMessage:
        """View the config of this channel's Match Event Ticker"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            ch = interaction.channel
            if ch is None:
                raise
            channel = typing.cast(discord.TextChannel, ch)

        # Validate channel is a ticker channel.
        tkrs = self.bot.ticker_channels
        try:
            tc = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            tc = TickerChannel(channel)

            success = await TickerConfig(interaction, tc).creation_dialogue()
            if success:
                self.bot.ticker_channels.append(tc)
        return await TickerConfig(interaction, tc).update()

    @ticker.command()
    @discord.app_commands.describe(
        competition="Search for a league by name", channel="Add to which channel?"
    )
    async def add_league(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
        channel: typing.Optional[discord.TextChannel] = None,
    ) -> discord.InteractionMessage:
        """Add a league to your Match Event Ticker"""

        await interaction.response.defer(thinking=True)

        if channel is None:
            ch = interaction.channel
            if ch is None:
                raise

            channel = typing.cast(discord.TextChannel, ch)

        tkrs = self.bot.ticker_channels
        try:
            t_chan = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            t_chan = TickerChannel(channel)

            suc = await TickerConfig(interaction, t_chan).creation_dialogue()
            if not suc:
                return self.bot.error(interaction, "Ticker creation cancelled")

            self.bot.ticker_channels.append(t_chan)

        if competition.url is None:
            raise ValueError("%s has no url", competition)

        # Find the Competition Object.
        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id, competition.url)

        t_chan.leagues.append(competition.url)

        txt = f"Added {competition.url} to {channel.mention} tracked leagues"
        return await TickerConfig(interaction, t_chan).update(txt)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        for x in self.bot.ticker_channels.copy():
            if x.channel.id == channel.id:
                self.bot.ticker_channels.remove(x)


async def setup(bot: Bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(Ticker(bot))
