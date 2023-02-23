"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

from asyncio import sleep, Semaphore
from typing import Optional, TYPE_CHECKING, Type, ClassVar

from asyncpg import ForeignKeyViolationError
from discord import (
    Colour,
    ButtonStyle,
    Embed,
    HTTPException,
    Permissions,
    Interaction,
    TextChannel,
    Message,
)
from discord.app_commands import Group, describe, autocomplete
from discord.ext.commands import Cog
from discord.ui import Select, Button

from ext.toonbot_utils.flashscore import (
    Fixture,
    Competition,
    DEFAULT_LEAGUES,
    lg_ac,
)
from ext.toonbot_utils.flashscore_search import fs_search
from ext.toonbot_utils.gamestate import GameState
from ext.toonbot_utils.matchevents import (
    MatchEvent,
    Penalty,
    Substitution,
    EventType,
)
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.view_utils import add_page_buttons, Confirmation, BaseView

if TYPE_CHECKING:
    from core import Bot
    from asyncpg import Record


class IsLiveScoreError(Exception):
    """Raise this when someone tries to create a ticker
    in a livescore channel."""


semaphore = Semaphore(value=5)

_ticker_tasks = set()


# TODO: Migrate Event embed generation to the individual Events
class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    bot: ClassVar[Bot] = None

    def __init__(
        self,
        fixture: Fixture,
        event_type: EventType,
        channels: list[TickerChannel],
        long: bool,
        home: bool = None,
    ) -> None:

        self.fixture: Fixture = fixture
        self.event_type: EventType = event_type
        self.channels: list[TickerChannel] = channels
        self.long: bool = long
        self.home: Optional[bool] = home

        # Cache for shorter retrieval
        self.embed: Optional[Embed] = None
        self.full_embed: Optional[Embed] = None

        # For exact event.
        self.event: Optional[MatchEvent] = None

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

    async def _embed(self) -> Embed:
        """The embed for the fixture event."""
        e = await self.fixture.base_embed()
        e.title = self.fixture.score_line
        e.url = self.fixture.url
        e.colour = self.event_type.colour
        e.description = ""

        # Fix Breaks.
        b = self.fixture.breaks
        m = self.event_type.value.replace("#PERIOD#", f"{b + 1}")

        match self.home:
            case None:
                e.set_author(name=m)
            case True:
                e.set_author(name=f"{m} ({self.fixture.home.name})")
            case False:
                e.set_author(name=f"{m} ({self.fixture.away.name})")

        match self.event_type:
            case EventType.PENALTY_RESULTS:
                ph = self.fixture.penalties_home
                pa = self.fixture.penalties_away
                if None in [ph, pa]:
                    e.description = self.fixture.score_line
                else:
                    h, a = ("**", "") if ph > pa else ("", "**")
                    score = f"{ph} - {pa}"
                    home = f"{h}{self.fixture.home.name}{h}"
                    away = f"{a}{self.fixture.away.name}{a}"
                    e.description = f"{home} {score} {away}\n"

                ev = self.fixture.events
                pens = [i for i in ev if isinstance(i, Penalty) and i.shootout]
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

        c = self.fixture.competition.name
        if isinstance(self.fixture.time, GameState):
            sh = self.fixture.state.shorthand
            e.set_footer(text=f"{sh} | {c}")
        else:
            e.set_footer(text=f"{self.fixture.time} | {c}")
        self.embed = e
        return e

    async def _full_embed(self) -> Embed:
        """Extended Embed with all events for Extended output event_type"""
        e = await self._embed()

        if self.event is not None and len(self.fixture.events) > 1:
            e.description += "\n```yaml\n--- Previous Events ---```"

        desc = []
        for i in self.fixture.events:
            if isinstance(i, Substitution):
                continue  # skip subs, they're just spam.

            # Penalty Shootouts are handled in self.embed,
            # we don't need to duplicate.
            if isinstance(i, Penalty) and i.shootout:
                continue

            if str(i) not in e.description:  # Dupes bug.
                desc.append(str(i))

        e.description += "\n".join(desc)

        self.full_embed = e
        return e

    async def event_loop(self) -> list[Message]:
        """The Fixture event's internal loop"""
        if not self.channels:
            return  # This should never happen.

        # Handle Match Events with no game events.
        if self.event_type == EventType.KICK_OFF:
            for x in self.channels:
                await x.dispatch(self)
            return []  # Done.

        index: Optional[int] = None
        for x in range(5):
            async with semaphore:
                await self.fixture.refresh()

            # Figure out which event we're supposed to be using
            # (Either newest event, or Stored if refresh)
            if index is None:
                if self.home:
                    team = self.fixture.home
                else:
                    team = self.fixture.away

                events = self.fixture.events
                if team is not None:
                    events = [i for i in events if i.team.name == team.name]

                valid: Type[MatchEvent] = self.event_type.valid_events
                if valid and events:
                    events.reverse()
                    self.event = [i for i in events if isinstance(i, valid)][0]
                    index = self.fixture.events.index(self.event)
            else:
                try:
                    self.event = self.fixture.events[index]
                except IndexError:
                    self.event = None
                    break

            if self.long and index:
                if all(
                    i.player is not None
                    for i in self.fixture.events[: index + 1]
                ):
                    break

            try:
                if self.event.player is not None:
                    break
            except AttributeError:
                break

            await sleep(x + 1 * 120)

        if self.long:
            await self._full_embed()
        else:
            await self._embed()

        for ch in self.channels:
            await ch.dispatch(self)


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    bot: ClassVar[Bot] = None

    def __init__(self, channel: int) -> None:
        self.channel: int = channel
        self.leagues: list[str] = []
        self.settings: dict = {}
        self.dispatched: dict[TickerEvent, Message] = {}

    # Send messages
    async def dispatch(self, event: TickerEvent) -> Optional[Message]:
        """Send the appropriate embed to this channel"""
        # Check if we need short or long embed.
        # For each stored db_field value,
        # we check against our own settings field.
        ch = self.bot.get_channel(self.channel)
        if ch is None:
            return

        if not self.settings:
            await self.get_settings()

        for x in event.event_type.db_fields:
            if not self.settings[x]:
                e = event.embed
                break
        else:
            e = event.full_embed

        try:
            try:
                message = self.dispatched[event]
                if message.embeds[0].description != e.description:
                    # Save on ratelimiting by checking.
                    message = await message.edit(embed=e)
            except KeyError:
                message = await ch.send(embed=e)
        except HTTPException:
            return None

        self.dispatched[event] = message
        return message

    # Database management.
    async def get_settings(self) -> dict:
        """Retrieve the settings of the TickerChannel from the database"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                stg = await connection.fetchrow(
                    """SELECT * FROM ticker_settings WHERE channel_id = $1""",
                    self.channel,
                )
                leagues = await connection.fetch(
                    """SELECT * FROM ticker_leagues WHERE channel_id = $1""",
                    self.channel,
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
        guild = self.bot.get_channel(self.channel).guild.id
        async with self.bot.database.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                invalidate = await connection.fetchrow(q, self.channel)
                if invalidate:
                    raise IsLiveScoreError
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild)
                q = """INSERT INTO ticker_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, guild, self.channel)
                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)
                        ON CONFLICT DO NOTHING"""
                await connection.execute(qq, self.channel)
                qqq = """INSERT INTO ticker_leagues (channel_id, league)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.executemany(
                    qqq, [(self.channel, x) for x in DEFAULT_LEAGUES]
                )
        return self

    async def delete_ticker(self) -> None:
        """Delete the ticker for this channel from the database"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(
                    """DELETE FROM ticker_channels WHERE channel_id = $1""",
                    self.channel,
                )
        self.bot.ticker_channels.remove(self)

    async def add_leagues(self, leagues: list[str]) -> list[str]:
        """Add a league to the TickerChannel's Tracked Leagues"""
        leagues = [i for i in leagues if i != "WORLD: Club Friendly"]

        sql = """INSERT INTO ticker_leagues (channel_id, league)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(
                    sql, [(self.channel, x) for x in leagues]
                )

        self.leagues += leagues
        return self.leagues

    async def remove_leagues(self, leagues: list[str]) -> list[str]:
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from ticker_leagues
                 WHERE (channel_id, league) = ($1, $2)"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(
                    sql, [(self.channel, x) for x in leagues]
                )

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def reset_leagues(self) -> list[str]:
        """Reset the Ticker Channel to the list of default leagues."""
        sql = """INSERT INTO ticker_leagues (channel_id, league)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(
                    sql, [(self.channel, x) for x in DEFAULT_LEAGUES]
                )

        self.leagues = DEFAULT_LEAGUES
        return self.leagues

    async def toggle_setting(
        self, db_key: str, new_value: Optional[bool]
    ) -> dict:
        """Toggle a database setting"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = f"""UPDATE ticker_settings SET {db_key} = $1
                     WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.channel)

        self.settings[db_key] = new_value
        return self.settings

    # View representing the channel
    def view(self, interaction: Interaction) -> TickerConfig:
        """Get a view representing this TickerChannel"""
        return TickerConfig(interaction, self)


class ToggleButton(Button):
    """A Button to toggle the ticker settings."""

    def __init__(self, db_key: str, value: Optional[bool], row: int = 0):
        self.value: Optional[bool] = value
        self.db_key: str = db_key

        if value is None:
            emoji = "🔴"  # None (Off)
            style = ButtonStyle.red
        else:
            emoji = (
                "🔵" if value else "''''🟢"
            )  # Extended (True), Normal (False)
            style = ButtonStyle.blurple if value else ButtonStyle.green

        title = db_key.replace("_", " ").title()

        match title:
            case "Goal":
                title = "Goals"
            case "Delayed":
                title = "Delayed"
            case "Red Card":
                title = "Red Cards"
            case "Var":
                title = "VAR Reviews"
            case "Penalties":
                title = "Penalty Shootouts"
        super().__init__(label=title, emoji=emoji, row=row, style=style)

    async def callback(self, interaction: Interaction) -> Message:
        """Set view value to button value"""

        await interaction.response.defer()

        match self.value:
            case True:
                new_value = None
            case False:
                new_value = True
            case _:
                new_value = False

        await self.view.tc.toggle_setting(self.db_key, new_value)
        return await self.view.update()


class ResetLeagues(Button):
    """Button to reset a ticker back to the default leagues"""

    def __init__(self) -> None:
        super().__init__(
            label="Reset to default leagues", style=ButtonStyle.primary
        )

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""

        await interaction.response.defer()
        await self.view.tc.reset_leagues()

        bot: Bot = interaction.client
        ch = bot.get_channel(self.view.tc.channel)
        return await self.view.update(
            content=f"Tracked leagues for {ch.mention} reset"
        )


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button delete ticker"""

        await interaction.response.defer()
        await self.view.tc.delete_ticker()

        bot: Bot = interaction.client
        ch = bot.get_channel(self.view.tc.channel)

        e = Embed(
            colour=Colour.red(),
            description=f"The Ticker for {ch.mention} was deleted.",
        )
        return await bot.reply(interaction, embed=e)


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

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

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected, delete channel / league row from DB"""

        await interaction.response.defer()
        return await self.view.remove_leagues(self.values)


class TickerConfig(BaseView):
    """Match Event Ticker View"""

    def __init__(self, interaction: Interaction, tc: TickerChannel):
        super().__init__(interaction)
        self.tc: TickerChannel = tc
        self.index: int = 0
        self.pages: list[Embed] = []

    async def remove_leagues(self, leagues: list[str]) -> Message:
        """Bulk remove leagues from a ticker channel"""
        # Ask user to confirm their choice.
        view = Confirmation(
            self.interaction,
            label_a="Remove",
            label_b="Cancel",
            style_a=ButtonStyle.red,
        )
        lg_text = "```yaml\n" + "\n".join(sorted(leagues)) + "```"

        ch = self.bot.get_channel(self.tc.channel)

        e = Embed(title="Transfer Ticker", colour=Colour.red())
        e.description = f"Remove these leagues from {ch.mention}?\n{lg_text}"
        await self.bot.reply(self.interaction, embed=e, view=view)
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
        if self.tc.channel in [i.channel.id for i in self.bot.score_channels]:
            err = "You cannot create a ticker in a livescores channel."
            await self.bot.error(self.interaction, err)
            return False

        c = self.bot.get_channel(self.tc.channel).mention

        view = Confirmation(
            self.interaction,
            style_a=ButtonStyle.green,
            label_a="Create ticker",
            label_b="Cancel",
        )
        notfound = (f"{c} does not have a ticker,"
                    " would you like to create one?")
        await self.bot.reply(self.interaction, notfound, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {c}"
            self.stop()
            view.clear_items()
            await self.bot.error(self.interaction, txt)
            return False

        try:
            try:
                await self.tc.create_ticker()
            # We have code to handle the ForeignKeyViolation within
            # create_ticker, so rerun it.
            except ForeignKeyViolationError:
                await self.tc.create_ticker()
        except IsLiveScoreError:
            err = "You cannot add tickers to a livescores channel."
            await self.bot.error(self.interaction, err)
            return False

        self.bot.ticker_channels.append(self.tc)
        await self.update(content=f"A ticker was created for {c}")
        return True

    async def update(self, content: str = None) -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        if not self.tc.settings:
            await self.tc.get_settings()

        c = Colour.dark_teal()
        embed = Embed(colour=c, title="Match Event Ticker config")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(
            text="Button Colour Key\n"
            "Red: Off, Green: On, Blue: Extended (Show all previous events)"
        )

        missing = []

        ch = self.bot.get_channel(self.tc.channel)
        perms = ch.permissions_for(ch.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = ("```yaml\nThis ticker channel will not work currently"
                 f"I am missing the following permissions.\n{missing}```")
            embed.add_field(name="Missing Permissions", value=v)

        if not self.tc.leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            embed.description = f"{ch.mention} has no tracked leagues."

        else:
            header = f"Tracked leagues for {ch.mention}```yaml\n"
            embeds = rows_to_embeds(
                embed, sorted(self.tc.leagues), header=header, footer="```"
            )
            self.pages = embeds

            add_page_buttons(self)

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
                if (k == "channel_id"):
                    continue
                row = 2 + count // 5
                self.add_item(ToggleButton(db_key=k, value=v, row=row))

                count += 1
        return await self.bot.reply(
            self.interaction, content=content, embed=embed, view=self
        )


class Ticker(Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        if TickerEvent.bot is None:
            TickerEvent.bot = bot
            TickerConfig.bot = bot
            TickerChannel.bot = bot

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        await self.update_cache()

    async def update_cache(self) -> None:
        """Store a list of all Ticker Channels into the bot"""
        sql = """SELECT DISTINCT channel_id FROM transfers_channels"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        for r in records:
            tc = TickerChannel(r["channel_id"])
            await tc.get_settings()
            self.bot.ticker_channels.append(tc)

    @Cog.listener()
    async def on_fixture_event(
        self, event_type: EventType, f: Fixture, home: bool = None
    ) -> Optional[TickerEvent]:
        """Event handler for when something occurs during a fixture."""
        # Update the competition's Table on certain events.

        flds = event_type.db_fields
        c: str = ", ".join(flds)
        not_nulls = " AND ".join([f"({x} IS NOT NULL)" for x in flds])
        sql = f"""SELECT {c}, ticker_settings.channel_id FROM ticker_settings
                  LEFT JOIN ticker_leagues ON ticker_settings.channel_id =
                  ticker_leagues.channel_id WHERE {not_nulls}
                  AND (league = $1::text)"""

        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, f.competition.title)

        if records:
            match event_type:
                case EventType.GOAL | EventType.FULL_TIME:
                    await f.competition.table()

        channels: list[TickerChannel] = []
        long: bool = False

        r: Record
        score_channels = [i.channel.id for i in self.bot.score_channels]
        tickers = self.bot.ticker_channels.copy()

        for r in records:
            # Validate this channel is suitable for message output.
            ch_id = r["channel_id"]
            if ch_id in score_channels:
                continue

            channel = self.bot.get_channel(ch_id)
            if channel is None or channel.is_news():
                continue

            perms = channel.permissions_for(channel.guild.me)
            if not perms.send_messages or not perms.embed_links:
                continue

            if all(x for x in r):
                long = True

            try:
                tc = next(i for i in tickers if i.channel == channel.id)
            except StopIteration:
                tc = TickerChannel(channel.id)
                self.bot.ticker_channels.append(tc)
            channels.append(tc)

        if channels:
            return TickerEvent(
                long=long,
                channels=channels,
                fixture=f,
                event_type=event_type,
                home=home,
            )

    ticker = Group(
        name="ticker",
        description="match event ticker",
        guild_only=True,
        default_permissions=Permissions(manage_channels=True),
    )

    @ticker.command()
    @describe(channel="Manage which channel?")
    async def manage_ticker(
        self, interaction: Interaction, channel: TextChannel = None
    ) -> Message:
        """View the config of this channel's Match Event Ticker"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        # Validate channel is a ticker channel.
        try:
            channel = next(
                i for i in self.bot.ticker_channels if i.channel == channel.id
            )
            return await channel.view(interaction).update()
        except StopIteration:
            channel = TickerChannel(channel.id)
            success = await channel.view(interaction).creation_dialogue()
            if success:
                self.bot.ticker_channels.append(channel)

    @ticker.command()
    @autocomplete(query=lg_ac)
    @describe(
        query="Search for a league by name", channel="Add to which channel?"
    )
    async def add_league(
        self, interaction: Interaction, query: str, channel: TextChannel = None
    ) -> Message:
        """Add a league to your Match Event Ticker"""

        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        try:
            t_chan = next(
                i for i in self.bot.ticker_channels if i.channel == channel.id
            )
        except StopIteration:
            t_chan = TickerChannel(channel.id)
            success = await t_chan.view(interaction).creation_dialogue()
            if not success:
                return

            self.bot.ticker_channels.append(t_chan)

        # Find the Competition Object.
        fsr = self.bot.get_competition(query)
        if fsr is None:
            if "http" not in query:
                fsr = await fs_search(interaction, query, mode="comp")

                if isinstance(fsr, Message):
                    return fsr

            else:
                if "flashscore" not in query:
                    return await self.bot.error(
                        interaction, f"Invalid link provided ({query})"
                    )

                fsr = await Competition.by_link(self.bot, query)

                if fsr is None:
                    err = f"Failed to get league data from <{query}>."
                    return await self.bot.error(interaction, err)

        await t_chan.add_leagues([fsr.title])
        txt = f"Added {fsr.title} to {channel.mention} tracked leagues"
        await t_chan.view(interaction).update(txt)

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with self.bot.database.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        for x in self.bot.ticker_channels.copy():
            if x.channel == channel.id:
                self.bot.ticker_channels.remove(x)


async def setup(bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(Ticker(bot))
