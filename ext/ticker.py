"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
from __future__ import annotations  # Cyclic Type hinting

from asyncio import sleep, Semaphore
from typing import List, Optional, TYPE_CHECKING, Type, Dict

from asyncpg import ForeignKeyViolationError, Record
from discord import Colour, ButtonStyle, Embed, HTTPException, Permissions, Interaction, TextChannel, Guild, Message
from discord.app_commands import Group, describe, autocomplete
from discord.ext.commands import Cog
from discord.ui import Select, View, Button

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.flashscore import Substitution, Penalty, Fixture, Competition, MatchEvent, search, EventType, Team, \
    DEFAULT_LEAGUES, WORLD_CUP_LEAGUES, lg_ac
from ext.utils.view_utils import add_page_buttons, Confirmation

if TYPE_CHECKING:
    from core import Bot


class IsLiveScoreError(Exception):
    """Raise this when someone tries to create a ticker in a livescore channel."""


semaphore = Semaphore(value=5)


# TODO: Migrate Event embed generation to the individual Events
class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""
    bot: Bot

    def __init__(self, bot: 'Bot', fixture: Fixture, event_type: EventType, channels: List[TickerChannel], long: bool,
                 home: bool = False) -> None:

        self.bot: Bot = bot
        self.fixture: Fixture = fixture
        self.event_type: EventType = event_type
        self.channels: List[TickerChannel] = channels
        self.long: bool = long
        self.home: bool = home

        # Cache for shorter retrieval
        self.embed: Optional[Embed] = None
        self.full_embed: Optional[Embed] = None

        # For exact event.
        self.event: Optional[MatchEvent] = None

        # Begin loop on init
        self.bot.loop.create_task(self.event_loop())

    @property
    async def _embed(self) -> Embed:
        """The embed for the fixture event."""
        e = await self.fixture.base_embed
        e.title = None
        e.remove_author()

        match self.event_type:
            case EventType.GOAL | EventType.VAR_GOAL | EventType.RED_CARD | EventType.VAR_RED_CARD:
                h, a = ('**', '') if self.home else ('', '**')  # Bold Home or Away Team Name.
                home = f"{h}{self.fixture.home.name}{h}"
                away = f"{a}{self.fixture.away.name}{a}"
                score = f"{self.fixture.score_home} - {self.fixture.score_away}"
                e.description = f"**{self.event_type.value}** | {home} [{score}]({self.fixture.url}) {away}\n"
            case EventType.PENALTY_RESULTS:
                try:
                    h, a = ("**", "") if self.fixture.penalties_home > self.fixture.penalties_away else ("", "**")
                    home = f"{h}{self.fixture.home.name}{h}"
                    away = f"{a}{self.fixture.away.name}{a}"
                    score = f"{self.fixture.penalties_home} - {self.fixture.penalties_away}"
                    e.description = f"**Penalty Results** | {home} [{score}]({self.fixture.url}) {away}\n"
                except (TypeError, AttributeError):  # If penalties_home / penalties_away are NoneType or not found.
                    e.description = f"**Penalty Results** | {self.fixture.bold_markdown}\n"

                shootout = [i for i in getattr(self.fixture, 'events', []) if getattr(i, "shootout", False)]
                # iterate through everything after penalty header
                for _ in [self.fixture.home, self.fixture.away]:
                    value = "\n".join([str(i) for i in shootout if i.team == _])
                    if value:
                        e.add_field(name=_, value=value)
            case EventType.PERIOD_BEGIN:
                m = self.event_type.value.replace('#PERIOD#', self.fixture.breaks + 1)
                e.description = f"**{m}** | {self.fixture.bold_markdown}\n"
                e.colour = self.event_type.colour
            case _:
                m = self.event_type.value
                e.description = f"**{m}** | {self.fixture.bold_markdown}\n"
                e.colour = self.event_type.colour

        # Append our event
        if self.event is not None:
            e.description += str(self.event)
            try:
                e.description += f"\n\n{self.event.description}"
            except AttributeError:
                pass

        # Append extra info
        if hasattr(self.fixture, 'infobox'):
            e.description += f"```yaml\n{self.fixture.infobox}```"

        e.set_footer(text=self.fixture.time.state.shorthand)
        self.embed = e
        return e

    @property
    async def _full_embed(self) -> Embed:
        """Extended Embed with all events for Extended output event_type"""
        e = await self._embed
        for i in getattr(self.fixture, 'events', []):
            if isinstance(i, Substitution):
                continue  # skip subs, they're just spam.

            # Penalty Shootouts are handled in self.embed, we don't need to duplicate.
            if hasattr(self.fixture, 'penalties_away'):
                if isinstance(i, Penalty) and i.shootout:
                    continue

            if str(i) not in e.description:  # Dupes bug.
                e.description += f"{i}\n"

        self.full_embed = e
        return e

    async def event_loop(self) -> List[Message]:
        """The Fixture event's internal loop"""
        # Handle Match Events with no game events.
        if self.long:
            await self._full_embed
        else:
            await self._embed

        if self.event_type == EventType.KICK_OFF:
            for x in self.channels:
                await x.dispatch(self)
            return []  # Done.

        retry: int = 0
        index: Optional[int] = None
        while retry < 5:
            await sleep(retry * 120)
            retry += 1

            async with semaphore:
                await self.fixture.refresh()

            # Figure out which event we're supposed to be using (Either newest event, or Stored if refresh)
            if index is not None:
                try:
                    self.event = self.fixture.events[index]
                except IndexError:
                    self.event = None
                    break
            else:
                team: Team = self.fixture.home if self.home else self.fixture.away

                events = getattr(self.fixture, 'events', [])
                if team is not None:
                    events: List = [i for i in events if i.team.name == team.name]

                valid: Type[MatchEvent] = self.event_type.valid_events
                if valid is not None and events:
                    try:
                        self.event = [i for i in events if isinstance(i, valid)][-1]
                        index = self.fixture.events.index(self.event)
                    except IndexError:
                        pass

            if self.long and index is not None:
                if all([hasattr(i, 'player') for i in self.fixture.events[:index + 1]]):
                    break
            elif not self.event:
                break
            else:
                if hasattr(self.event, 'player'):
                    break

            if self.long:
                await self._full_embed
            else:
                await self._embed

            for ch in self.channels:
                await ch.dispatch(self)


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    def __init__(self, bot: 'Bot', channel: TextChannel) -> None:
        self.bot: Bot = bot
        self.channel: TextChannel = channel
        self.leagues: List[str] = []
        self.settings: Dict = {}
        self.dispatched: Dict[TickerEvent, Message] = {}

    # Send messages
    async def dispatch(self, event: TickerEvent) -> Optional[Message]:
        """Send the appropriate embed to this channel"""
        # Check if we need short or long embed.
        # For each stored db_field value, we check against our own settings field.
        for x in event.event_type.db_fields:
            if not self.settings[x]:
                e = event.embed
                break
        else:
            e = event.full_embed

        try:
            if event in self.dispatched:
                message = self.dispatched[event]
                if message.embeds[0].description != e.description:
                    # Save on ratelimiting by checking.
                    message = await message.edit(embed=e)
            else:
                message = await self.channel.send(embed=e)
        except HTTPException:
            return None

        self.dispatched[event] = message
        return message

    # Database management.
    async def get_settings(self) -> Dict:
        """Retrieve the settings of the TickerChannel from the database"""
        connection = await self.bot.db.acquire()

        try:
            async with connection.transaction():
                sql = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
                stg = await connection.fetchrow(sql, self.channel.id)

                sql = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
                leagues = await connection.fetch(sql, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        if stg is not None:
            for k, v in stg.items():
                if k == 'channel_id':
                    continue
                self.settings[k] = v

        self.leagues = [r['league'] for r in leagues]
        return self.settings

    async def create_ticker(self) -> TickerChannel:
        """Create a ticker for the target channel"""
        connection = await self.bot.db.acquire()
        try:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                invalidate = await connection.fetchrow(q, self.channel.id)
                if invalidate:
                    raise IsLiveScoreError

            async with connection.transaction():
                q = """INSERT INTO ticker_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.channel.guild.id, self.channel.id)

            async with connection.transaction():
                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(qq, self.channel.id)

            async with connection.transaction():
                qqq = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.executemany(qqq, [(self.channel.id, x) for x in DEFAULT_LEAGUES])

        except ForeignKeyViolationError:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)"""
                await connection.execute(sql, self.channel.guild.id)
        finally:
            await self.bot.db.release(connection)
        return self

    async def delete_ticker(self) -> None:
        """Delete the ticker for this channel from the database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM ticker_channels WHERE channel_id = $1""", self.channel.id)
        finally:
            await self.bot.db.release(connection)
        self.bot.ticker_channels.remove(self)

    async def add_leagues(self, leagues: List[str]) -> List[str]:
        """Add a league to the TickerChannel's Tracked Leagues"""
        sql = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, x) for x in leagues])
        finally:
            await self.bot.db.release(connection)

        self.leagues += leagues
        return self.leagues

    async def remove_leagues(self, leagues: List[str]) -> List[str]:
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from ticker_leagues WHERE (channel_id, league) = ($1, $2)"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, x) for x in leagues])
        finally:
            await self.bot.db.release(connection)

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def reset_leagues(self) -> List[str]:
        """Reset the Ticker Channel to the list of default leagues."""
        sql = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, x) for x in DEFAULT_LEAGUES])
        finally:
            await self.bot.db.release(connection)

        self.leagues = DEFAULT_LEAGUES
        return self.leagues

    async def toggle_setting(self, db_key: str, new_value: Optional[bool]) -> dict:
        """Toggle a database setting"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE ticker_settings SET {db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        self.settings[db_key] = new_value
        return self.settings

    # View representing the channel
    def view(self, interaction: Interaction) -> TickerConfig:
        """Get a view representing this TickerChannel"""
        return TickerConfig(self.bot, interaction, self)


class ToggleButton(Button):
    """A Button to toggle the ticker settings."""
    view: TickerConfig

    def __init__(self, db_key: str, value: Optional[bool], row: int = 0):
        self.value: Optional[bool] = value
        self.db_key: str = db_key

        if value is None:
            emoji = '🔴'  # None (Off)
            label = "Off"
        else:
            emoji = '🔵' if value else '🟢'  # Extended (True), Normal (False)
            label = "Extended" if value else "On"

        title = db_key.replace('_', ' ').title()

        match title:
            case "Goal":
                title = 'Goals'
            case "Delayed":
                title = "Delayed Games"
            case "Red Card":
                title = "Red Cards"
            case "Var":
                title = "VAR Reviews"
            case "Penalties":
                title = "Penalty Shootouts"

        super().__init__(label=f"{title} ({label})", emoji=emoji, row=row)

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
    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.tc.reset_leagues()
        return await self.view.update(content=f"Tracked leagues for {self.view.tc.channel.mention} reset")


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""
    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button delete ticker"""
        await interaction.response.defer()
        await self.view.tc.delete_ticker()
        return await self.view.update(content=f"The Ticker for {self.view.tc.channel.mention} was deleted.")


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, leagues: List[str], row: int = 2) -> None:
        super().__init__(placeholder="Remove tracked league(s)", row=row, max_values=len(leagues))
        # No idea how we're getting duplicates here but fuck it I don't care.
        for lg in sorted(set(leagues)):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected, delete channel / league row from DB"""
        await interaction.response.defer()
        return await self.view.remove_leagues(self.values)


class TickerConfig(View):
    """Match Event Ticker View"""

    def __init__(self, bot: 'Bot', interaction: Interaction, tc: TickerChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.tc: TickerChannel = tc
        self.index: int = 0
        self.pages: List[Embed] = []
        self.bot: Bot = bot

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def remove_leagues(self, leagues: List[str]) -> Message:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        txt = f"Remove these leagues from {self.tc.channel.mention}? {lg_text}"
        await self.bot.reply(self.interaction, content=txt, embed=None, view=view)
        await view.wait()

        if not view.value:
            return await self.update(content="No leagues were removed")

        await self.tc.remove_leagues(leagues)
        return await self.update(content=f"Removed {self.tc.channel.mention} tracked leagues: {lg_text}")

    async def creation_dialogue(self) -> Message:
        """Send a dialogue to check if the user wishes to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        if self.tc.channel.id in [i.channel.id for i in self.bot.score_channels]:
            return await self.bot.error(self.interaction, content='You cannot create a ticker in a livescores channel.')

        view = Confirmation(self.interaction, colour_a=ButtonStyle.green, label_a=f"Create ticker", label_b="Cancel")
        notfound = f"{self.tc.channel.mention} does not have a ticker, would you like to create one?"
        await self.bot.reply(self.interaction, content=notfound, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {self.tc.channel.mention}"
            self.stop()
            return await self.bot.error(self.interaction, txt)

        try:
            try:
                await self.tc.create_ticker()
            # We have code to handle the ForeignKeyViolation within create_ticker, so rerun it.
            except ForeignKeyViolationError:
                await self.tc.create_ticker()
        except IsLiveScoreError:
            return await self.bot.error(self.interaction, content='You cannot add a ticker to a livescores channel.')

        self.bot.ticker_channels.append(self.tc)
        return await self.update(content=f"A ticker was created for {self.tc.channel.mention}")

    async def update(self, content: str = "") -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        if not self.tc.settings:
            await self.tc.get_settings()

        e = Embed(colour=Colour.dark_teal(), title="Toonbot Match Event Ticker config")
        e.set_thumbnail(url=self.bot.user.display_avatar.url)

        missing = []
        perms = self.tc.channel.permissions_for(self.tc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = "```yaml\nThis ticker channel will not work currently, I am missing the following permissions.\n"
            e.add_field(name='Missing Permissions', value=f"{v} {missing}```")

        if not self.tc.leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            e.description = f"{self.tc.channel.mention} has no tracked leagues."

        else:
            header = f'Tracked leagues for {self.tc.channel.mention}```yaml\n'
            embeds = rows_to_embeds(e, sorted(self.tc.leagues), header=header, footer="```", max_rows=25)
            self.pages = embeds

            add_page_buttons(self)

            e = self.pages[self.index]

            if len(self.tc.leagues) > 25:
                # Get everything after index * 25 (page len), then up to 25 items from that page.
                remove_list = self.tc.leagues[self.index * 25:][:25]
            else:
                remove_list = self.tc.leagues

            self.add_item(RemoveLeague(remove_list, row=1))

            count = 0
            row = 2
            for k, v in sorted(self.tc.settings.items()):
                if k == "channel_id":  # We don't need a button for channel_id, it's just the database key.
                    continue

                count += 1
                if count % 5 == 0:
                    row += 1

                self.add_item(ToggleButton(db_key=k, value=v, row=row))
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class TickerCog(Cog, name="Ticker"):
    """Get updates whenever match events occur"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    async def on_load(self) -> None:
        """Reset the cache on load."""
        self.bot.ticker_channels = []
        await self.update_cache()

    async def update_cache(self) -> None:
        """Store a list of all Ticker Channels into the bot"""
        sql = f"""SELECT * FROM transfers_channels"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch(sql)
        finally:
            await self.bot.db.release(connection)

        # Purge dead
        cached = set([r['channel_id'] for r in records])
        for tc in self.bot.ticker_channels.copy():
            if tc.channel.id not in cached:
                self.bot.ticker_channels.remove(tc)

        # Bring in new
        for cid in cached:
            tc = next((i for i in self.bot.ticker_channels if i.channel.id == cid), None)
            if tc is None:
                channel = self.bot.get_channel(cid)
                if channel is None:
                    continue

                tc = TickerChannel(self.bot, channel)
                await tc.get_settings()
                self.bot.ticker_channels.append(tc)

    @Cog.listener()
    async def on_fixture_event(self, event_type: EventType, f: Fixture, home: bool = True) -> Optional[TickerEvent]:
        """Event handler for when something occurs during a fixture."""
        if not self.bot.ticker_channels:
            await self.update_cache()

        # Update the competition's Table on certain events.
        match event_type:
            case EventType.GOAL | EventType.FULL_TIME:
                await f.competition.table()

        c: str = ", ".join(event_type.db_fields)
        not_nulls = " AND ".join([f'({x} IS NOT NULL)' for x in event_type.db_fields])
        sql = f"""SELECT {c}, ticker_settings.channel_id FROM ticker_settings LEFT JOIN ticker_leagues 
                ON ticker_settings.channel_id = ticker_leagues.channel_id WHERE {not_nulls} AND (league = $1::text)"""

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch(sql, f.competition.title)
        finally:
            await self.bot.db.release(connection)

        channels: List[TickerChannel] = []
        long: bool = False

        r: Record
        score_channels = [i.channel.id for i in self.bot.score_channels]
        tickers = self.bot.ticker_channels.copy()
        for r in records:
            try:
                # Validate this channel is suitable for message output.
                channel = self.bot.get_channel(r['channel_id'])
                assert channel is not None
                assert channel.permissions_for(channel.guild.me).send_messages
                assert channel.permissions_for(channel.guild.me).embed_links
                assert channel.id not in score_channels
                assert not channel.is_news()
                if all(x for x in r):
                    long = True

                tc = next((i for i in tickers if i.channel.id == channel.id), None)
                if tc is None:
                    continue
            except AssertionError:
                continue

        return TickerEvent(self.bot, long=long, channels=channels, fixture=f, event_type=event_type, home=home)

    # Ticker command is available to those who have manage messages permissions.
    tkr_perms = Permissions(manage_channels=True)
    ticker = Group(name="ticker", description="match event ticker", guild_only=True, default_permissions=tkr_perms)

    @ticker.command()
    async def manage(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """View the config of this channel's Match Event Ticker"""
        if channel is None:
            channel = interaction.channel

        tc = next((i for i in self.bot.ticker_channels if i.channel.id == channel.id), None)
        # Validate channel is a ticker channel.
        if tc is None:
            return await TickerChannel(self.bot, channel).view(interaction).creation_dialogue()

        return await TickerConfig(self.bot, interaction, tc).update()

    @ticker.command()
    @autocomplete(query=lg_ac)
    @describe(query="Search for a league by name")
    async def add(self, interaction: Interaction, query: str, channel: TextChannel = None) -> Message:
        """Add a league to your Match Event Ticker"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        tc = next((i for i in self.bot.ticker_channels if i.channel.id == channel.id), None)

        # Validate channel is a ticker channel.
        if tc is None:
            return await TickerChannel(self.bot, channel).view(interaction).creation_dialogue()

        # Find the Competition Object.
        # TODO: EXTEND BOT.GET_COMPETITION TO FETCH FROM FLASHSCORE?
        fsr = self.bot.get_competition(query)
        if fsr is None:
            if "http" not in query:
                fsr = await search(self.bot, interaction, query, competitions=True)

                if isinstance(fsr, Message):
                    return fsr

            else:
                if "flashscore" not in query:
                    return await self.bot.error(interaction, content='🚫 Invalid link provided')

                fsr = await Competition.by_link(self.bot, query)

                if fsr is None:
                    return await self.bot.error(interaction, f"🚫 Failed to get league data from <{query}>.")

        await tc.add_leagues([fsr.title])
        await tc.view(interaction).update(f"Added {fsr.title} to {channel.mention} tracked leagues")

    @ticker.command()
    async def add_world_cup(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """Add the qualifying tournaments for the World Cup to a channel's ticker"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        tc = next((i for i in self.bot.ticker_channels if i.channel.id == channel.id), None)
        # Validate channel is a ticker channel.
        if tc is None:
            return await TickerChannel(self.bot, channel).view(interaction).creation_dialogue()

        await tc.add_leagues(WORLD_CUP_LEAGUES)
        leagues = "\n".join(WORLD_CUP_LEAGUES)
        msg = f"Added tracked leagues to {channel.mention}```yaml\n{leagues}```"
        return await tc.view(interaction).update(msg)

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Handle deletion of channel data from database upon channel deletion."""
        sql = f"""DELETE FROM ticker_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(sql, channel.id)
        finally:
            await self.bot.db.release(connection)

        for x in self.bot.ticker_channels.copy():
            if x.channel.id == channel.id:
                self.bot.ticker_channels.remove(x)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        """Delete all data related to a guild from the database upon guild leave."""
        for x in self.bot.ticker_channels.copy():
            if x.channel.guild.id == guild.id:
                self.bot.ticker_channels.remove(x)


async def setup(bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(TickerCog(bot))
