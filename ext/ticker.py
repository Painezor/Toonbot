"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
import asyncio
from importlib import reload
from typing import List, Tuple, Optional

from discord import Colour, ButtonStyle, Interaction, Embed, NotFound, \
    HTTPException, app_commands, Forbidden, TextChannel, Guild, Message
from discord.ext import commands
from discord.ui import Select, View, Button

from ext.utils import embed_utils, view_utils, football
from ext.utils.football import Substitution, Penalty, Goal, VAR, RedCard, Fixture, Competition

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
edict = {
    "goal": Colour.dark_green(),
    "red_card": Colour.red(),
    "var_goal": Colour.og_blurple(),
    "var_red_card": Colour.og_blurple(),
    "goal_overturned": Colour.og_blurple(),
    "red_card_overturned": Colour.og_blurple(),

    "kick_off": Colour.green(),

    "delayed": Colour.orange(),
    "interrupted": Colour.dark_orange(),

    "cancelled": Colour.red(),
    "postponed": Colour.red(),
    "abandoned": Colour.red(),

    "resumed": Colour.light_gray(),
    "second_half_begin": Colour.light_gray(),

    "half_time": 0x00ffff,

    "end_of_normal_time": Colour.greyple(),
    "extra_time_begins": Colour.lighter_grey(),
    "ht_et_begin": Colour.light_grey(),
    "ht_et_end": Colour.dark_grey(),
    "end_of_extra_time": Colour.darker_gray(),
    "penalties_begin": Colour.dark_gold(),

    "full_time": Colour.teal(),
    "final_result_only": Colour.teal(),
    "score_after_extra_time": Colour.teal(),
    "penalty_results": Colour.teal()
}
# Refresh a maximum of x fixtures at a time

# TODO: Permissions Pass.
# TODO: Figure out how to monitor page for changes rather than repeated scraping. Then Update iteration style.
# TODO: Change search to use FS Search Box.


class ToggleButton(Button):
    """A Button to toggle the ticker settings."""

    def __init__(self, db_key, value, row=0):
        self.value = value
        self.db_key = db_key

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

        connection = await self.view.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE ticker_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.view.channel.id)
        finally:
            await self.view.interaction.client.db.release(connection)
        await self.view.update()


class ResetLeagues(Button):
    """Button to reset a ticker back to its default leagues"""

    def __init__(self) -> None:
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.interaction.client.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
            for x in DEFAULT_LEAGUES:
                await connection.execute(q, self.view.channel.id, x)
        await self.view.interaction.client.db.release(connection)
        await self.view.update(content=f"The tracked leagues for {self.view.channel.mention} were reset")


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.interaction.client.db.acquire()
        async with connection.transaction():
            q = """DELETE FROM ticker_channels WHERE channel_id = $1"""
            await connection.execute(q, self.view.channel.id)
        await self.view.interaction.client.db.release(connection)
        txt = f"The match events ticker for {self.view.channel.mention} was deleted."
        await self.view.update(content=txt)


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, leagues, row=2):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.max_values = len(leagues)

        for lg in sorted(leagues):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction):
        """When a league is selected"""
        await interaction.response.defer()

        connection = await self.view.interaction.client.db.acquire()
        async with connection.transaction():
            q = """DELETE from ticker_leagues WHERE (channel_id, league) = ($1, $2)"""
            for x in self.values:
                await connection.execute(q, self.view.channel.id, x)
        await self.view.interaction.client.db.release(connection)
        await self.view.update()


class TickerConfig(View):
    """Match Event Ticker View"""

    def __init__(self, interaction: Interaction, channel: TextChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel
        self.index = 0
        self.pages = None
        self.settings = None
        self.value = None

    async def on_timeout(self) -> None:
        """Hide menu on timeout."""
        self.clear_items()
        await self.interaction.client.reply(self.interaction, view=self, followup=False)
        self.stop()

    @property
    def base_embed(self) -> Embed:
        """Generic Embed for Config Views"""
        return Embed(colour=Colour.dark_teal(), title="Match Event Ticker config")

    async def creation_dialogue(self) -> Message:
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()
        view = view_utils.Confirmation(self.interaction, colour_a=ButtonStyle.green, label_b="Cancel",
                                       label_a=f"Create a ticker for #{self.channel.name}")
        _ = f"{self.channel.mention} does not have a ticker, would you like to create one?"
        await self.interaction.client.reply(self.interaction, content=_, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {self.channel.mention}"
            self.stop()
            return await self.interaction.client.error(self.interaction, txt)

        connection = await self.interaction.client.db.acquire()
        try:
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
            await self.interaction.client.error(self.interaction, _)
            raise err
        finally:
            await self.interaction.client.db.release(connection)

    async def update(self, content: str = "") -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        connection = await self.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.channel.id)
                qq = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
                stg = await connection.fetchrow(qq, self.channel.id)
                qqq = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
                leagues = await connection.fetch(qqq, self.channel.id)
        finally:
            await self.interaction.client.db.release(connection)

        if channel is None:
            return await self.creation_dialogue()

        leagues = [r['league'] for r in leagues]

        if not leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            e = self.base_embed
            e.description = f"{self.channel.mention} has no tracked leagues."
        else:
            e = Embed(colour=Colour.dark_teal(), title="Toonbot Match Event Ticker config")
            e.set_thumbnail(url=self.interaction.guild.me.display_avatar.url)
            header = f'Tracked leagues for {self.channel.mention}```yaml\n'
            embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=header, footer="```", rows_per=25)
            self.pages = embeds

            self.add_item(view_utils.PreviousButton(disabled=True if self.index == 0 else False))
            self.add_item(view_utils.PageButton(label=f"Page {self.index + 1} of {len(self.pages)}",
                                                disabled=True if len(self.pages) == 1 else False))
            self.add_item(view_utils.NextButton(disabled=True if self.index == len(self.pages) - 1 else False))
            self.add_item(view_utils.StopButton(row=0))

            e = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues, row=1))

            count = 0
            row = 2
            for k, v in sorted(stg.items()):
                if k == "channel_id":
                    continue

                count += 1
                if count % 5 == 0:
                    row += 1

                self.add_item(ToggleButton(db_key=k, value=v, row=row))

        await self.interaction.client.reply(self.interaction, content=content, embed=e, view=self)


# TODO: Typehint
class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(self, bot, fixture, mode, channels: List[Tuple[int, bool]], home=False):
        self.bot = bot
        self.fixture = fixture
        self.mode = mode
        self.channels = channels
        self.home = home

        # dynamic properties
        self.retry: int = 0
        self.messages: List[Message] = []
        self.needs_refresh: bool = True
        self.needs_extended: bool = True if any([i[1] for i in channels]) else False

        # For exact event.
        self.event = None
        self.event_index = None

        # Begin loop on init
        bot.loop.create_task(self.event_loop())

    @property
    async def embed(self):
        """The embed for the fixture event."""
        e = await self.fixture.base_embed()
        e.title = None
        e.remove_author()

        m = self.mode.title().replace('_', ' ')
        if self.mode == "Kick off":
            e = await self.embed
            e.description = f"**Kick Off** | [{self.fixture.bold_score}]({self.fixture.url})\n"
            e.colour = Colour.lighter_gray()

        elif "ht_et" in self.mode:
            temp_mode = "Half Time" if self.mode == "ht_et_begin" else "Second Half Begins"
            e.description = f"Extra Time: {temp_mode} | [{self.fixture.bold_score}]({self.fixture.url})\n"

        elif self.mode in ["goal", "var_goal", "red_card", "var_red_card"]:
            h, a = ('**', '') if self.home else ('', '**')  # Bold Home or Away Team Name.
            h, a = ('**', '**') if self.home is None else (h, a)
            home = f"{h}{self.fixture.home.name} {self.fixture.score_home}{h}"
            away = f"{a}{self.fixture.score_away} {self.fixture.away.name}{a}"
            e.description = f"**{m}** | [{home} - {away}]({self.fixture.url})\n"

        if self.mode == "penalties_begin":
            e.description = f"**Penalties Begin** | [{self.fixture.bold_score}]({self.fixture.url})\n"

        elif self.mode == "penalty_results":
            try:
                h, a = ("**", "") if self.fixture.penalties_home > self.fixture.penalties_away else ("", "**")
                home = f"{h}{self.fixture.home.name} {self.fixture.penalties_home}{h}"
                away = f"{a}{self.fixture.penalties_away} {self.fixture.away.name}{a}"
                e.description = f"**Penalty Shootout Results** | [{home} - {away}]({self.fixture.url})\n"
            except (TypeError, AttributeError):  # If penalties_home / penalties_away are NoneType or not found.
                e.description = f"**Penalty Shootout Results** | [{self.fixture.bold_score}]({self.fixture.url})\n"

            shootout = [i for i in self.fixture.events if hasattr(i, "shootout") and i.shootout]
            # iterate through everything after penalty header
            for _ in [self.fixture.home, self.fixture.away]:
                value = "\n".join([str(i) for i in shootout if i.team == _])
                if value:
                    e.add_field(name=_, value=value)

        else:
            e.description = f"**{m}** | [{self.fixture.bold_score}]({self.fixture.url})\n"

        # Fetch Embed Colour
        if "end_of_period" in self.mode:
            e.colour = Colour.greyple()
        elif "start_of_period" in self.mode:
            e.colour = Colour.blurple()
        else:
            try:
                e.colour = edict[self.mode]
            except Exception as err:
                print(f"Ticker Embed Colour: edict error for mode {self.mode}", err)

        # Append our event
        if self.event is not None:
            e.description += str(self.event)
            if hasattr(self.event, "full_description"):
                e.description += f"\n\n{self.event.full_description}"

        # Append extra info
        if self.fixture.infobox is not None:
            e.description += f"```yaml\n{self.fixture.infobox}```"

        e.set_footer(text=self.fixture.event_footer)
        return e

    @property
    async def full_embed(self) -> Embed:
        """Extended Embed with all events for Extended output mode"""
        e = await self.embed
        if self.fixture.events:
            for i in self.fixture.events:
                if isinstance(i, Substitution):
                    continue  # skip subs, they're just spam.

                # Penalties are handled later on.
                if self.fixture.penalties_away:
                    if isinstance(i, Penalty) and i.shootout:
                        continue

                if str(i) in e.description:  # Dupes bug.
                    continue
                e.description += f"{str(i)}\n"
        return e

    # TODO: Enum
    @property
    def valid_events(self):
        """Valid events for ticker mode"""
        if self.mode == "goal":
            return tuple([Goal, VAR])
        elif self.mode == "red_card":
            return RedCard
        elif self.mode in ("var_goal", "var_red_card"):
            return VAR
        return None

    async def retract_event(self):
        """Handle corrections for erroneous events"""
        if self.mode == "goal":
            self.mode = "goal_overturned"
            await self.bulk_edit()
        elif self.mode == "red_card":
            self.mode = "red_card_overturned"
            await self.bulk_edit()
        else:
            print(f"Event Warning: {self.event}")
            print(f'[WARNING] {self.fixture} Ticker: Attempted to retract event for missing mode: {self.mode}')

    async def send_messages(self):
        """Dispatch the latest event embed to all applicable channels"""
        for channel_id, extended in self.channels:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue

            # True means Use Extended, False means use normal.
            try:
                _ = await self.full_embed if extended else await self.embed
            except KeyError as e:
                print('ticker - send_messages: Key Error', extended, self.mode, e)
                continue

            try:
                self.messages.append(await channel.send(embed=_))
            except (NotFound, Forbidden):
                continue
            except HTTPException as err:
                print("Ticker.py send:", channel.id, err)
                continue

    async def bulk_edit(self):
        """Edit existing messages"""
        for message in self.messages:
            r = next((i for i in self.channels if i[0] == message.channel.id), None)
            if r is None:
                continue

            # False means short embed, True means Extended Embed
            try:
                embed = await self.full_embed if r[1] else await self.embed
            except KeyError as e:
                print("Ticker, bulk edit, key error", e, self.mode, r)
                continue

            try:
                if message.embed.description != embed.description:
                    await message.edit(embed=embed)
            except HTTPException:
                continue

    async def event_loop(self):
        """The Fixture event's internal loop"""
        # Handle full time only events.
        if self.mode == "kick_off":
            await self.send_messages()
            return

        while self.needs_refresh:
            # Fallback, Wait 2 minutes extra pre refresh
            _ = 120 * self.retry if self.retry < 5 else False
            if _:
                await asyncio.sleep(_)
            else:
                return await self.bulk_edit()

            page = await self.bot.browser.newPage()
            try:
                await self.fixture.refresh(page)
            finally:  # ALWAYS close the browser after refreshing to avoid Memory leak
                await page.close()

            self.retry += 1

            # Figure out which event we're supposed to be using (Either newest event, or Stored if refresh)
            if self.event_index is not None:
                try:
                    self.event = self.fixture.events[self.event_index]
                    assert isinstance(self.event, self.valid_events)
                    # Event deleted or replaced.
                except (IndexError, AssertionError):
                    return await self.retract_event()

                if self.needs_extended:
                    if all([i.player for i in self.fixture.events[:self.event_index + 1]]):
                        self.needs_refresh = False
                else:
                    if self.event.player:
                        self.needs_refresh = False

            else:
                if self.fixture.events:
                    if self.valid_events is not None:
                        try:
                            events = [i for i in self.fixture.events if isinstance(i, self.valid_events)]
                            _ = self.fixture.home if self.home else self.fixture.away
                            event = [i for i in events if i.team == _].pop()
                            self.event_index = self.fixture.events.index(event)
                            self.event = event

                            if self.needs_extended:
                                if all([i.player for i in self.fixture.events[:self.event_index + 1]]):
                                    self.needs_refresh = False
                            else:
                                if event.player:
                                    self.needs_refresh = False
                        except IndexError:
                            self.event = None
                            self.event_index = None

            if self.messages:
                if not self.needs_refresh:
                    return await self.bulk_edit()
            else:
                await self.send_messages()


class TickerCog(commands.Cog, name="Ticker"):
    """Get updates whenever match events occur"""

    def __init__(self, bot) -> None:
        self.bot = bot
        [reload(_) for _ in [football, view_utils]]

    # Autocomplete
    async def lg_ac(self, _: Interaction, current: str, __) -> List[app_commands.Choice[str]]:
        """Autocomplete from list of stored leagues"""
        lgs = self.bot.competitions.values()
        return [app_commands.Choice(name=i.title, value=i.url) for i in lgs if current.lower() in i.title.lower()][:25]

    @commands.Cog.listener()  # TODO: Make Mode an Enum
    async def on_fixture_event(self, mode: str, f: Fixture, home: bool = True):
        """Event handler for when something occurs during a fixture."""
        match mode:
            case "ht_et_begin":  # Special Check - Must pass both
                columns = ["half_time", "extra_time"]
            case "ht_et_end":  # Special Check - Must pass both
                columns = ["second_half_begin", "extra_time"]
            case "resumed":
                columns = ["kick_off"]
            case "var_red_card" | "var_goal" | "red_card_overturned" | "goal_overturned":
                columns = ["var"]
            case "interrupted" | "postponed" | "cancelled":
                columns = ["delayed"]
            case "extra_time_begins" | "end_of_normal_time" | "end_of_extra_time":
                columns = ["extra_time"]
            case "score_after_extra_time" | "abandoned" | "full_time":
                columns = ["full_time"]
            case "penalties_begin" | "penalty_results":
                columns = ["penalties"]
            case "scheduled":
                print("How the fuck did you get a scheduled state?")
                return
            case mode if "start_of_period" in mode:
                columns = ["second_half_begin"]
            case mode if "end_of_period" in mode:
                columns = ["half_time"]
            case _:
                columns = [mode]

        connection = await self.bot.db.acquire()

        columns: list

        c: str = ", ".join(columns)
        not_nulls = " AND ".join([f'({x} IS NOT NULL)' for x in columns])
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

        for r in list(records):
            try:
                channel = self.bot.get_channel(r['channel_id'])
                assert channel is not None
                assert channel.permissions_for(channel.guild.me).send_messages
                assert channel.permissions_for(channel.guild.me).embed_links
                assert not channel.is_news()
            except AssertionError:
                records.remove(r)

        channels = [(int(r.pop(-1)), all(r)) for r in [list(x) for x in records]]

        if not channels:  # skip fetch if unwanted.
            return

        # Settings for those IDs
        TickerEvent(self.bot, channels=channels, fixture=f, mode=mode, home=home)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel):
        """Handle deletion of channel data from database upon channel deletion."""
        q = f"""DELETE FROM ticker_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id)
        finally:
            await self.bot.db.release(connection)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: Guild):
        """Delete all data related to a guild from the database upon guild leave."""
        q = f"""DELETE FROM ticker_channels WHERE guild_id = $1"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(q, guild.id)
        await self.bot.db.release(connection)

    ticker = app_commands.Group(name="ticker", description="match event ticker")

    @ticker.command()
    async def manage(self, interaction: Interaction, channel: Optional[TextChannel]):
        """View the config of this channel's Match Event Ticker"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions:
            return await self.bot.error(interaction, "You need manage messages permissions to edit a ticker")

        channel = interaction.channel if channel is None else channel

        await TickerConfig(interaction, channel).update(content=f"Fetching config for {channel.mention}...")

    @ticker.command()
    @app_commands.describe(query="League to search for")
    @app_commands.autocomplete(query=lg_ac)
    async def add(self, interaction: Interaction, query: str, channel: Optional[TextChannel]):
        """Add a league to your Match Event Ticker"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        elif not interaction.permissions.manage_messages:
            return await self.bot.error(interaction, "You need manage messages permissions to edit a ticker")

        channel = interaction.channel if channel is None else channel

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
            row = await connection.fetchrow(q, channel.id)
        await self.bot.db.release(connection)

        if not row:
            # If we cannot add, send to creation dialogue.
            return await TickerConfig(interaction, channel).update(content=f"Fetching config for {channel.mention}...")

        if "http" not in query:
            res = await football.fs_search(interaction, query)
            if res is None:
                return await self.bot.error(interaction, f"No matching competitions found for {query}")
        else:
            if "flashscore" not in query:
                return await self.bot.error(interaction, '🚫 Invalid link provided')

            page = await self.bot.browser.newPage()
            try:
                res = await Competition.by_link(query, page)
            except IndexError:
                return await self.bot.error(interaction, '🚫 Could not find competition data on that page')
            finally:
                await page.close()

            if res is None:
                return await self.bot.error(interaction, f"🚫 Failed to get league data from <{query}>.")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, channel.id, str(res))
        finally:
            await self.bot.db.release(connection)

        await TickerConfig(interaction, channel).update(content=f"Added {res} tracked leagues for {channel.mention}")

    @ticker.command()
    async def add_world_cup(self, interaction: Interaction, channel: Optional[TextChannel]):
        """Add the qualifying tournaments for the World Cup to a channel's ticker"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_messages:
            return await self.bot.error(interaction, "You need manage messages permissions to edit a ticker")

        channel = interaction.channel if channel is None else channel

        # Validate.
        c = await self.bot.db.acquire()
        try:
            async with c.transaction():
                q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
                row = await c.fetchrow(q, channel.id)
        finally:
            await self.bot.db.release(c)

        if not row:
            return await TickerConfig(interaction, channel).update(content=f"Fetching config for {channel.mention}...")

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


def setup(bot):
    """Load the goal tracker cog into the bot."""
    bot.add_cog(TickerCog(bot))
