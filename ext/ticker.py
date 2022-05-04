"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
from asyncio import sleep
from typing import List, Optional, TYPE_CHECKING, Type

from discord import Colour, ButtonStyle, Interaction, Embed, TextChannel, Guild, Message, HTTPException, Permissions
from discord.app_commands import Choice, Group, describe, autocomplete
from discord.app_commands.checks import has_permissions
from discord.ext.commands import Cog
from discord.ui import Select, View, Button

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.football import Substitution, Penalty, Fixture, Competition, MatchEvent, \
    fs_search, EventType, Team
from ext.utils.view_utils import add_page_buttons, Confirmation

if TYPE_CHECKING:
    from core import Bot

DEFAULT_LEAGUES = [
    "WORLD: Friendly international",
    "EUROPE: Champions League",
    "EUROPE: Euro",
    "EUROPE: Europa League",
    "EUROPE: UEFA Nations League",
    "ENGLAND: Premier League",
    "ENGLAND: Championship",
    "ENGLAND: League One",
    "ENGLAND: FA Cup",
    "ENGLAND: EFL Cup",
    "FRANCE: Ligue 1",
    "FRANCE: Coupe de France",
    "GERMANY: Bundesliga",
    "ITALY: Serie A",
    "NETHERLANDS: Eredivisie",
    "SCOTLAND: Premiership",
    "SPAIN: Copa del Rey",
    "SPAIN: LaLiga",
    "USA: MLS"
]
WORLD_CUP_LEAGUES = [
    "EUROPE: World Cup",
    "ASIA: World Cup",
    "AFRICA: World Cup",
    "NORTH & CENTRAL AMERICA: World Cup",
    "SOUTH AMERICA: World Cup"
]


class ToggleButton(Button):
    """A Button to toggle the ticker settings."""

    def __init__(self, bot: 'Bot', db_key: str, value: Optional[bool], row: int = 0):
        self.value: Optional[bool] = value
        self.db_key: str = db_key
        self.bot: Bot = bot

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

    async def callback(self, interaction: Interaction):
        """Set view value to button value"""
        match self.value:
            case True:
                new_value = None
            case False:
                new_value = True
            case _:
                new_value = False

        await interaction.response.defer()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE ticker_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.view.channel.id)
        finally:
            await self.bot.db.release(connection)
        await self.view.update()


class ResetLeagues(Button):
    """Button to reset a ticker back to its default leagues"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
            for x in DEFAULT_LEAGUES:
                await connection.execute(q, self.view.channel.id, x)
        await self.bot.db.release(connection)
        await self.view.update(content=f"The tracked leagues for {self.view.channel.mention} were reset")


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """DELETE FROM ticker_channels WHERE channel_id = $1"""
            await connection.execute(q, self.view.channel.id)
        await self.bot.db.release(connection)
        txt = f"The match events ticker for {self.view.channel.mention} was deleted."
        await self.view.update(content=txt)


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, bot: 'Bot', leagues: List[str], row: int = 2):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.bot: Bot = bot
        self.max_values = len(leagues)

        for lg in sorted(leagues):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction):
        """When button is pushed, delete channel / league row from DB"""
        await interaction.response.defer()

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """DELETE from ticker_leagues WHERE (channel_id, league) = ($1, $2)"""
            for x in self.values:
                await connection.execute(q, self.view.channel.id, x)
        await self.bot.db.release(connection)
        await self.view.update()


class TickerConfig(View):
    """Match Event Ticker View"""

    def __init__(self, bot: 'Bot', interaction: Interaction, channel: TextChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel
        self.index = 0
        self.pages: List[Embed] = []
        self.settings = None
        self.value = None

        self.bot = bot

    async def on_timeout(self) -> None:
        """Hide menu on timeout."""
        self.clear_items()
        await self.bot.reply(self.interaction, view=self, followup=False)
        self.stop()

    @property
    def base_embed(self) -> Embed:
        """Generic Embed for Config Views"""
        return Embed(colour=Colour.dark_teal(), title="Match Event Ticker config")

    async def creation_dialogue(self) -> Message:
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()

        # Ticker Verify -- NOT A SCORES CHANNEL
        if self.channel.id in self.bot.scores_cache:
            return await self.bot.error(self.interaction, 'You cannot create a ticker in a livescores channel.')

        view = Confirmation(self.interaction, colour_a=ButtonStyle.green, label_b="Cancel",
                            label_a=f"Create a ticker for #{self.channel.name}")
        _ = f"{self.channel.mention} does not have a ticker, would you like to create one?"
        await self.bot.reply(self.interaction, content=_, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {self.channel.mention}"
            self.stop()
            return await self.bot.error(self.interaction, txt)

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                invalidate = await connection.fetchrow(q, self.channel.id)
                if invalidate:
                    return await self.bot.error(self.interaction, 'You cannot add a ticker to a livescores channel.')

            async with connection.transaction():
                q = """INSERT INTO ticker_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.interaction.guild.id, self.channel.id)

            async with connection.transaction():
                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)"""
                self.settings = await connection.fetchrow(qq, self.channel.id)

            async with connection.transaction():
                qqq = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
                for x in DEFAULT_LEAGUES:
                    await connection.execute(qqq, self.channel.id, x)
            return await self.update(content=f"A ticker was created for {self.channel.mention}")
        except Exception as err:
            _ = f"An error occurred while creating a ticker for {self.channel.mention}"
            self.stop()
            await self.bot.error(self.interaction, _)
            raise err
        finally:
            await self.bot.db.release(connection)

    async def update(self, content: str = "") -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.channel.id)
                qq = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
                stg = await connection.fetchrow(qq, self.channel.id)
                qqq = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
                leagues = await connection.fetch(qqq, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        if channel is None:
            return await self.creation_dialogue()

        leagues = [r['league'] for r in leagues]

        if not leagues:
            self.add_item(ResetLeagues(self.bot))
            self.add_item(DeleteTicker(self.bot))
            e = self.base_embed
            e.description = f"{self.channel.mention} has no tracked leagues."
        else:
            e: Embed = Embed(colour=Colour.dark_teal(), title="Toonbot Match Event Ticker config")
            e.set_thumbnail(url=self.interaction.guild.me.display_avatar.url)
            header = f'Tracked leagues for {self.channel.mention}```yaml\n'
            embeds = rows_to_embeds(e, sorted(leagues), header=header, footer="```", rows_per=25)
            self.pages = embeds

            add_page_buttons(self)

            e = self.pages[self.index]

            if len(leagues) > 25:
                # Get everything after index * 25 (page len), then up to 25 items from that page.
                leagues = leagues[self.index * 25:][:25]

            self.add_item(RemoveLeague(self.bot, leagues, row=1))

            count = 0
            row = 2
            for k, v in sorted(stg.items()):
                if k == "channel_id":
                    continue

                count += 1
                if count % 5 == 0:
                    row += 1

                self.add_item(ToggleButton(self.bot, db_key=k, value=v, row=row))

        await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(self, bot: 'Bot', fixture: Fixture, event_type: EventType, channels_short: List[TextChannel],
                 channels_long: List[TextChannel], home: bool = False) -> None:

        self.bot: Bot = bot
        self.fixture: Fixture = fixture
        self.event_type: EventType = event_type
        self.channels_short: List[TextChannel] = channels_short
        self.channels_long: List[TextChannel] = channels_long
        self.home: bool = home

        # For exact event.
        self.event: Optional[MatchEvent] = None

        # Begin loop on init
        self.bot.loop.create_task(self.event_loop())

    @property
    async def embed(self) -> Embed:
        """The embed for the fixture event."""
        e = await self.fixture.base_embed()
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

                shootout = [i for i in self.fixture.events if hasattr(i, "shootout") and i.shootout]
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
            if self.event.description:
                e.description += f"\n\n{self.event.description}"

        # Append extra info
        if self.fixture.infobox is not None:
            e.description += f"```yaml\n{self.fixture.infobox}```"

        e.set_footer(text=self.fixture.time.state)
        return e

    @property
    async def full_embed(self) -> Embed:
        """Extended Embed with all events for Extended output event_type"""
        e = await self.embed
        if self.fixture.events:
            for i in self.fixture.events:
                if isinstance(i, Substitution):
                    continue  # skip subs, they're just spam.

                # Penalty Shootouts are handled in self.embed, we don't need to duplicate.
                if self.fixture.penalties_away:
                    if isinstance(i, Penalty) and i.shootout:
                        continue

                if str(i) in e.description:  # Dupes bug.
                    continue
                e.description += f"{str(i)}\n"
        return e

    async def send_messages(self) -> List[Message]:
        """Dispatch the latest event embed to all applicable channels"""

        async def dispatch(embed: Embed, channels: List[TextChannel]) -> List[Message]:
            """Send target embed to target channels"""
            these_messages = []
            for channel in channels:
                try:
                    these_messages.append(await channel.send(embed=embed))
                except HTTPException:
                    continue
            return these_messages

        messages: List[Message] = []
        messages += await dispatch(await self.embed, self.channels_short)
        messages += await dispatch(await self.full_embed, self.channels_long)
        return messages

    async def bulk_edit(self, messages: List[Message], new_event_type: EventType = None) -> List[Message]:
        """Edit existing messages"""
        if new_event_type is not None:
            self.event_type = new_event_type

        short_embed = await self.embed
        long_embed = await self.full_embed

        for message in messages.copy():
            messages.remove(message)

            e = short_embed if message.channel in self.channels_short else long_embed

            if message.embeds[0].description != e.description:
                # Transpose the data from the new embed onto the old one. (Do not overwrite footer with timestamp)
                old_embed = message.embeds[0]
                old_embed.description = e.description
                try:
                    message = await message.edit(embed=e)
                except HTTPException:  # If we can't find a message, we don't try again to update it.
                    continue

            messages.append(message)
        return messages

    async def event_loop(self) -> List[Message]:
        """The Fixture event's internal loop"""
        # Handle Match Events with no game events.
        if self.event_type == EventType.KICK_OFF:
            return await self.send_messages()

        retry: int = 0
        index: Optional[int] = None
        messages: List[Message] = []
        while retry < 5:
            await sleep(retry * 120)
            retry += 1
            await self.fixture.refresh()

            # Figure out which event we're supposed to be using (Either newest event, or Stored if refresh)
            if index is not None:
                self.event = self.fixture.events[index]
            else:
                team: Team = self.fixture.home if self.home else self.fixture.away
                if team is not None:
                    events: List = [i for i in self.fixture.events if i.team.name == team.name]
                else:
                    events = self.fixture.events

                valid: Type[MatchEvent] = self.event_type.valid_events
                if valid is not None and events:
                    try:
                        self.event = [i for i in events if isinstance(i, valid)][-1]
                        index = self.fixture.events.index(self.event)
                    except IndexError:
                        pass

            if self.channels_long and index is not None:
                if all([i.player for i in self.fixture.events[:index + 1]]):
                    break
            elif self.event is False:
                break
            elif self.event:
                if self.event.player:
                    break

            if not messages:
                messages = await self.send_messages()
            else:
                messages = await self.bulk_edit(messages)
        if not messages:
            return await self.send_messages()
        return await self.bulk_edit(messages)


class TickerCog(Cog, name="Ticker"):
    """Get updates whenever match events occur"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    # Autocomplete
    async def lg_ac(self, _: Interaction, current: str) -> List[Choice[str]]:
        """Autocomplete from list of stored leagues"""
        lgs = self.bot.competitions.values()
        return [Choice(name=i.title[:100], value=i.id) for i in lgs if current.lower() in i.title.lower()][:25]

    @Cog.listener()
    async def on_fixture_event(self, event_type: EventType, f: Fixture, home: bool = True):
        """Event handler for when something occurs during a fixture."""
        connection = await self.bot.db.acquire()

        c: str = ", ".join(event_type.db_fields)
        not_nulls = " AND ".join([f'({x} IS NOT NULL)' for x in event_type.db_fields])
        sql = f"""SELECT {c}, ticker_settings.channel_id FROM ticker_settings LEFT JOIN ticker_leagues 
                ON ticker_settings.channel_id = ticker_leagues.channel_id WHERE {not_nulls} AND (league = $1::text)"""

        try:
            async with connection.transaction():
                records = await connection.fetch(sql, str(f.competition))
        except Exception as e:
            print(sql)
            raise e
        finally:
            await self.bot.db.release(connection)

        short: List[TextChannel] = []
        long: List[TextChannel] = []

        for r in list(records):
            try:
                channel = self.bot.get_channel(r['channel_id'])
                assert channel is not None
                assert channel.permissions_for(channel.guild.me).send_messages
                assert channel.permissions_for(channel.guild.me).embed_links
                assert channel.id not in self.bot.scores_cache
                assert not channel.is_news()

                long.append(channel) if all(x for x in r) else short.append(channel)
            except AssertionError:
                pass

        if not short and not long:  # skip fetch if unwanted.
            return

        # Settings for those IDs
        TickerEvent(self.bot, channels_short=short, channels_long=long, fixture=f, event_type=event_type, home=home)

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Handle deletion of channel data from database upon channel deletion."""
        q = f"""DELETE FROM ticker_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id)
        finally:
            await self.bot.db.release(connection)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        """Delete all data related to a guild from the database upon guild leave."""
        q = f"""DELETE FROM ticker_channels WHERE guild_id = $1"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(q, guild.id)
        await self.bot.db.release(connection)

    # Ticker command is available to those who have manage messages permissions.
    tkr_perms = Permissions(manage_channels=True)
    ticker = Group(name="ticker", description="match event ticker", guild_only=True, default_permissions=tkr_perms)

    @ticker.command()
    async def manage(self, interaction: Interaction, channel: Optional[TextChannel]):
        """View the config of this channel's Match Event Ticker"""
        if not interaction.permissions.manage_messages:
            return await self.bot.error(interaction, "You need manage messages permissions to edit a ticker")

        channel = interaction.channel if channel is None else channel

        await TickerConfig(self.bot, interaction, channel).update(content=f"Fetching config for {channel.mention}...")

    @ticker.command()
    @describe(query="League to search for")
    @autocomplete(query=lg_ac)
    @has_permissions(manage_channels=True)
    async def add(self, interaction: Interaction, query: str, channel: TextChannel = None):
        """Add a league to your Match Event Ticker"""
        if channel is None:
            channel = interaction.channel

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
            row = await connection.fetchrow(q, channel.id)
        await self.bot.db.release(connection)

        if not row:
            # If we cannot add, send to creation dialogue.
            return await TickerConfig(self.bot, interaction, channel).update(f"Fetching config for {channel.mention}")

        if query in self.bot.competitions:
            res = self.bot.competitions[query]
        elif "http" not in query:
            res = await fs_search(self.bot, interaction, query, competitions=True)
            if isinstance(res, Message):
                return
        else:
            if "flashscore" not in query:
                return await self.bot.error(interaction, '🚫 Invalid link provided')

            res = await Competition.by_link(self.bot, query)

            if res is None:
                return await self.bot.error(interaction, f"🚫 Failed to get league data from <{query}>.")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, channel.id, str(res))
        finally:
            await self.bot.db.release(connection)

        await TickerConfig(self.bot, interaction, channel).update(f"Added {res} tracked leagues for {channel.mention}")

    @ticker.command()
    async def add_world_cup(self, interaction: Interaction, channel: TextChannel = None):
        """Add the qualifying tournaments for the World Cup to a channel's ticker"""
        if channel is None:
            channel = interaction.channel

        # Validate.
        c = await self.bot.db.acquire()
        try:
            async with c.transaction():
                q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
                row = await c.fetchrow(q, channel.id)
        finally:
            await self.bot.db.release(c)

        if not row:
            return await TickerConfig(self.bot, interaction, channel).update(f"Fetching config for {channel.mention}")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                for res in WORLD_CUP_LEAGUES:
                    await connection.execute(q, channel.id, res)
        finally:
            await self.bot.db.release(connection)

        leagues = "\n".join(WORLD_CUP_LEAGUES)
        msg = f"Added tracked leagues to {channel.mention}```yaml\n{leagues}```"
        await self.bot.reply(interaction, content=msg)


async def setup(bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(TickerCog(bot))
