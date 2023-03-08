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

NOPERMS = (
    "```yaml\nThis ticker channel will not work currently"
    "I am missing the following permissions.\n"
)

semaphore = asyncio.Semaphore(2)


async def get_table(bot: Bot, link: str):

    async with semaphore:
        page = await bot.browser.new_page()
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

            js = "ads => ads.forEach(x => x.remove());"
            await page.eval_on_selector_all(fs.ADS, js)

            image = await table_div.screenshot(type="png")
        finally:
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


# TODO: League AC to transformer.
# TODO: Populate url field.
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
        self.leagues: set[fs.Competition] = set()
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

        sql = """UPDATE ticker_leagues SET url = $1 WHERE league = $2"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            for r in leagues:
                if comp := self.bot.get_competition(r["league"]):
                    if r["url"] is None:
                        url = comp.url
                        if url is None:
                            continue
                        await connection.execute(sql, url, r["league"])
                    self.leagues.add(comp)
        return self.settings


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

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM ticker_leagues WHERE channel_id = $1"""
                await connection.execute(sql, self.view.tc.channel.id)

                sql = """INSERT INTO ticker_leagues (channel_id, url)
                    VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                r = [(self.view.tc.channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql, r)

        for x in fs.DEFAULT_LEAGUES:
            if (comp := interaction.client.get_competition(x)) is None:
                continue
            self.view.tc.leagues.add(comp)

        e = discord.Embed(title="Ticker: Tracked Leagues Reset")
        e.description = self.view.tc.channel.mention
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

    def __init__(self, leagues: list[fs.Competition], row: int = 2) -> None:
        ph = "Remove tracked league(s)"
        super().__init__(placeholder=ph, row=row, max_values=len(leagues))

        for lg in leagues:
            if lg.url is None:
                continue

            self.add_option(label=lg.title, description=lg.url, value=lg.url)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When a league is selected, delete channel / league row from DB"""

        await interaction.response.defer()

        view = view_utils.Confirmation(
            interaction, "Remove", "Cancel", discord.ButtonStyle.red
        )

        lg_text = "```yaml\n" + "\n".join(sorted(self.values)) + "```"
        c = self.view.tc.channel.mention

        e = discord.Embed(title="Transfer Ticker", colour=discord.Colour.red())
        e.description = f"Remove these leagues from {c}?\n{lg_text}"
        await self.view.interaction.edit_original_response(embed=e, view=view)
        await view.wait()

        if not view.value:
            return await self.view.update()

        sql = """DELETE from ticker_leagues
                 WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.view.tc.channel.id, x) for x in self.values]
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        for i in self.view.tc.leagues.copy():
            if i.url in self.values:
                self.view.tc.leagues.remove(i)

        m = self.view.tc.channel.mention
        msg = f"Removed {m} tracked leagues: ```yaml\n{lg_text}```"
        e = discord.Embed(description=msg, colour=discord.Colour.red())

        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        await self.view.interaction.followup.send(content=msg)
        return await self.view.update()


class TickerConfig(view_utils.BaseView):
    """Match Event Ticker View"""

    interaction: discord.Interaction[Bot]
    bot: Bot

    def __init__(
        self, interaction: discord.Interaction[Bot], tc: TickerChannel
    ):
        super().__init__(interaction)
        self.tc: TickerChannel = tc

    async def update(self) -> discord.InteractionMessage:
        """Regenerate view and push to message"""
        self.clear_items()

        if not self.tc.settings:
            await self.tc.get_settings()

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "Match Event Ticker config"

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
            v = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=v)

        edit = self.interaction.edit_original_response
        if not self.tc.leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            embed.description = f"{ch.mention} has no tracked leagues."
            return await edit(embed=embed, view=self)

        embed.description = f"Tracked leagues for {ch.mention}```yaml\n"
        leagues = sorted(self.tc.leagues, key=lambda x: x.title)

        self.pages = embed_utils.paginate(leagues)
        self.add_page_buttons()

        leagues: list[fs.Competition]
        leagues = [i.url for i in self.pages[self.index] if i.url is not None]

        embed.description += "\n".join([str(i.url) for i in leagues])

        self.add_item(RemoveLeague(leagues, row=1))

        count = 0
        for k, v in self.tc.settings.items():
            # We don't need a button for channel_id,
            # it's just the database key.
            if k == "channel_id":
                continue
            row = 2 + count // 5
            self.add_item(ToggleButton(db_key=k, value=v, row=row))

            count += 1

        return await edit(embed=embed, view=self)


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        TickerEvent.bot = bot
        TickerChannel.bot = bot

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        await self.update_cache()

    async def create(
        self,
        interaction: discord.Interaction[Bot],
        channel: discord.TextChannel,
    ) -> discord.InteractionMessage:
        """Send a dialogue to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():

                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

                invalidate = await connection.fetchrow(q, channel.id)
            if invalidate:
                err = "You cannot create a ticker in a livescores channel."
                return await self.bot.error(interaction, err)

        c = channel.mention
        btn = discord.ButtonStyle.green
        view = view_utils.Confirmation(
            interaction, "Create ticker", "Cancel", btn
        )
        notkr = f"{c} does not have a ticker, would you like to create one?"
        await interaction.edit_original_response(content=notkr, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {c}"
            return await self.bot.error(interaction, txt)

        guild = channel.guild.id

        rows = [(channel.id, x) for x in fs.DEFAULT_LEAGUES]

        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild)

                q = """INSERT INTO ticker_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, guild, channel.id)

                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)
                        ON CONFLICT DO NOTHING"""
                await connection.execute(qq, channel.id)

                qqq = """INSERT INTO ticker_leagues (channel_id, url)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.executemany(qqq, rows)

        tc = TickerChannel(channel)
        self.bot.ticker_channels.append(tc)
        return await TickerConfig(interaction, tc).update()

    async def update_cache(self) -> list[TickerChannel]:
        """Store a list of all Ticker Channels into the bot"""
        sql = """SELECT DISTINCT channel_id FROM transfers_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        bad = set()
        for r in records:
            ch = self.bot.get_channel(r["channel_id"])
            if ch is None:
                bad.add(r["channel_id"])
                continue

            ch = typing.cast(discord.TextChannel, ch)

            tc = TickerChannel(ch)
            await tc.get_settings()
            self.bot.ticker_channels.append(tc)

        sql = """DELETE FROM ticker_channelss WHERE channel_id = $1"""
        if self.bot.ticker_channels:
            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    await connection.executemany(sql, bad)
        return self.bot.ticker_channels

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
                  AND (url = $1::text)"""

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
            channel = typing.cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        tkrs = self.bot.ticker_channels
        try:
            tc = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            return await self.create(interaction, channel)

        return await TickerConfig(interaction, tc).update()

    @ticker.command()
    @discord.app_commands.describe(
        competition="Search for a league by name",
        channel="Add to which channel?",
    )
    async def add_league(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
        channel: typing.Optional[discord.TextChannel],
    ) -> discord.InteractionMessage:
        """Add a league to your Match Event Ticker"""

        if competition.title == "WORLD: Club Friendly":
            err = "You can't add club friendlies as a competition, sorry."
            raise ValueError(err)

        if competition.url is None:
            raise LookupError("%s url is None", competition)

        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        chn = self.bot.ticker_channels
        try:
            tc = next(i for i in chn if i.channel.id == channel.id)
        except StopIteration:
            return await self.create(interaction, channel)

        # Find the Competition Object.
        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id, competition.url)

        tc.leagues.add(competition)
        e = discord.Embed(title="Ticker: Tracked League Added")
        e.description = f"{tc.channel.mention}\n\n{competition.url}"
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        return await interaction.edit_original_response(embed=e)

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
