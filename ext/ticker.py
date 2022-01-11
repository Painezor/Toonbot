"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
import asyncio
import typing
from importlib import reload

import discord
from discord.commands import Option
from discord.ext import commands

from ext.utils import football, embed_utils, view_utils

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
    "goal": discord.Colour.dark_green(),
    "red_card": discord.Colour.red(),
    "var_goal": discord.Colour.og_blurple(),
    "var_red_card": discord.Colour.og_blurple(),
    "goal_overturned": discord.Colour.og_blurple(),
    "red_card_overturned": discord.Colour.og_blurple(),

    "kick_off": discord.Colour.green(),

    "delayed": discord.Colour.orange(),
    "interrupted": discord.Colour.dark_orange(),

    "cancelled": discord.Colour.red(),
    "postponed": discord.Colour.red(),
    "abandoned": discord.Colour.red(),

    "resumed": discord.Colour.light_gray(),
    "second_half_begin": discord.Color.light_gray(),

    "half_time": 0x00ffff,

    "end_of_normal_time": discord.Colour.greyple(),
    "extra_time_begins": discord.Colour.lighter_grey(),
    "ht_et_begin": discord.Colour.light_grey(),
    "ht_et_end": discord.Colour.dark_grey(),
    "end_of_extra_time": discord.Colour.darker_gray(),
    "penalties_begin": discord.Colour.dark_gold(),

    "full_time": discord.Colour.teal(),
    "final_result_only": discord.Colour.teal(),
    "score_after_extra_time": discord.Colour.teal(),
    "penalty_results": discord.Colour.teal()
}

# Refresh a maximum of x fixtures at a time
max_pages = asyncio.Semaphore(5)


# Autocomplete
async def live_leagues(ctx):
    """Return list of live leagues"""
    leagues = set([i.league for i in ctx.bot.games if ctx.value.lower() in i.league.lower()])
    return sorted(list(leagues))


LEAGUES = Option(str, "Search for a league to add", autocomplete=live_leagues)


class ToggleButton(discord.ui.Button):
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

        if title == "Goal":
            title = 'Goals'

        elif title == "Delayed":
            title = "Delayed Games"

        elif title == "Red Card":
            title = "Red Cards"

        elif title == "Var":
            title = "VAR Reviews"

        elif title == "Penalties":
            title = "Penalty Shootouts"

        super().__init__(label=f"{title} ({label})", emoji=emoji, row=row)

    async def callback(self, interaction: discord.Interaction):
        """Set view value to button value"""
        if self.value is True:
            new_value = None
        elif self.value is False:
            new_value = True
        else:
            new_value = False

        await interaction.response.defer()

        connection = await self.view.ctx.bot.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE ticker_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.view.ctx.channel.id)
        finally:
            await self.view.ctx.bot.db.release(connection)
        await self.view.update()


class ResetLeagues(discord.ui.Button):
    """Button to reset a ticker back to its default leagues"""

    def __init__(self):
        super().__init__(label="Reset to default leagues", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.ctx.bot.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
            for x in DEFAULT_LEAGUES:
                await connection.execute(q, self.view.ctx.channel.id, x)
        await self.view.ctx.bot.db.release(connection)
        await self.view.update(text=f"The tracked leagues for {self.view.channel.mention} were reset")


class DeleteTicker(discord.ui.Button):
    """Button to delete a ticker entirely"""

    def __init__(self):
        super().__init__(label="Delete ticker", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.ctx.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM ticker_channels WHERE channel_id = $1""", self.view.ctx.channel.id)
        await self.view.ctx.bot.db.release(connection)
        await self.view.update(text=f"The match events ticker for {self.view.ctx.channel.mention} was deleted.")


class RemoveLeague(discord.ui.Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, leagues, row=2):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.max_values = len(leagues)

        for league in sorted(leagues):
            self.add_option(label=league)

    async def callback(self, interaction: discord.Interaction):
        """When a league is selected"""
        await interaction.response.defer()

        connection = await self.view.ctx.bot.db.acquire()
        async with connection.transaction():
            q = """DELETE from ticker_leagues WHERE (channel_id, league) = ($1, $2)"""
            for x in self.values:
                await connection.execute(q, self.view.ctx.channel.id, x)
        await self.view.ctx.bot.db.release(connection)
        await self.view.update()


class ConfigView(discord.ui.View):
    """Generic Config View"""

    def __init__(self, ctx):
        super().__init__()
        self.index = 0
        self.ctx = ctx
        self.message = None
        self.pages = None
        self.settings = None
        self.value = None

    async def on_timeout(self):
        """Hide menu on timeout."""
        self.clear_items()
        try:
            await self.message.edit(view=self, content="")
        except discord.HTTPException:
            pass
        self.stop()

    @property
    def base_embed(self):
        """Generic Embed for Config Views"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Match Event Ticker config"
        return e

    async def creation_dialogue(self):
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()
        view = view_utils.Confirmation(self.ctx, colour_a=discord.ButtonStyle.green,
                                       label_a=f"Create a ticker for #{self.ctx.channel.name}", label_b="Cancel")
        _ = f"{self.ctx.channel.mention} does not have a ticker, would you like to create one?"
        await self.message.edit(content=_, view=view)
        await view.wait()

        if view.value:
            connection = await self.ctx.bot.db.acquire()
            try:
                async with connection.transaction():
                    q = """INSERT INTO ticker_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                    await connection.execute(q, self.ctx.channel.guild.id, self.ctx.channel.id)

                async with connection.transaction():
                    qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)"""
                    self.settings = await connection.fetchrow(qq, self.ctx.channel.id)

                async with connection.transaction():
                    qqq = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
                    for x in DEFAULT_LEAGUES:
                        await connection.execute(qqq, self.ctx.channel.id, x)
                await self.update(text=f"A ticker was created for {self.ctx.channel.mention}")
            except Exception as err:
                _ = f"An error occurred while trying to create a ticker for {self.ctx.channel.mention}"
                e = discord.Embed(description=_)
                e.colour = discord.Colour.red()
                await self.message.edit(embed=e, view=None)
                self.stop()
                raise err
            finally:
                await self.ctx.bot.db.release(connection)
            await self.update()
        else:
            _ = f"Cancelled ticker creation for {self.ctx.channel.mention}"
            e = discord.Embed(description=_)
            e.colour = discord.Colour.red()
            await self.message.edit(embed=e, view=None)
            self.stop()

    async def update(self, text=""):
        """Regenerate view and push to message"""
        self.clear_items()

        connection = await self.ctx.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM ticker_channels WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.ctx.channel.id)
                qq = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
                stg = await connection.fetchrow(qq, self.ctx.channel.id)
                qqq = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
                leagues = await connection.fetch(qqq, self.ctx.channel.id)
        finally:
            await self.ctx.bot.db.release(connection)

        if channel is None:
            await self.creation_dialogue()
            return

        leagues = [r['league'] for r in leagues]

        if not leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            e = self.base_embed
            e.description = f"{self.ctx.channel.mention} has no tracked leagues."
        else:
            e = discord.Embed()
            e.colour = discord.Colour.dark_teal()
            e.title = "Toonbot Match Event Ticker config"
            e.set_thumbnail(url=self.ctx.me.display_avatar.url)
            header = f'Tracked leagues for {self.ctx.channel.mention}```yaml\n'
            embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=header, footer="```", rows_per=25)
            self.pages = embeds

            _ = view_utils.PreviousButton()
            _.disabled = True if self.index == 0 else False
            self.add_item(_)

            _ = view_utils.PageButton()
            _.label = f"Page {self.index + 1} of {len(self.pages)}"
            _.disabled = True if len(self.pages) == 1 else False
            self.add_item(_)

            _ = view_utils.NextButton()
            _.disabled = True if self.index == len(self.pages) - 1 else False
            self.add_item(_)
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

        try:
            await self.message.edit(content=text, embed=e, view=self)
        except discord.NotFound:
            self.stop()
            return


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(self, bot, fixture, mode, channels: typing.List[typing.Tuple[int, bool]], home=False):
        self.bot = bot
        self.fixture = fixture
        self.mode = mode
        self.channels = channels
        self.home = home

        # dynamic properties
        self.retry = 0
        self.messages = []
        self.needs_refresh = True
        self.needs_extended = True if any([i[1] for i in channels]) else False

        # For exact event.
        self.event = None
        self.event_index = None

        # Begin loop on init
        bot.loop.create_task(self.event_loop())

    @property
    async def embed(self):
        """The embed for the fixture event."""
        e = await self.fixture.base_embed
        e.title = None
        e.remove_author()

        m = self.mode.title().replace('_', ' ')
        if self.mode == "Kick off":
            e = await self.embed
            e.description = f"**Kick Off** | [{self.fixture.bold_score}]({self.fixture.url})\n"
            e.colour = discord.Colour.lighter_gray()

        elif "ht_et" in self.mode:
            temp_mode = "Half Time" if self.mode == "ht_et_begin" else "Second Half Begins"
            e.description = f"Extra Time: {temp_mode} | [{self.fixture.bold_score}]({self.fixture.url})\n"

        elif self.mode in ["goal", "var_goal", "red_card", "var_red_card"]:
            h, a = ('**', '') if self.home else ('', '**')  # Bold Home or Away Team Name.
            h, a = ('**', '**') if self.home is None else (h, a)
            home = f"{h}{self.fixture.home} {self.fixture.score_home}{h}"
            away = f"{a}{self.fixture.score_away} {self.fixture.away}{a}"
            e.description = f"**{m}** | [{home} - {away}]({self.fixture.url})\n"

        if self.mode == "penalties_begin":
            e.description = f"**Penalties Begin** | [{self.fixture.bold_score}]({self.fixture.url})\n"

        elif self.mode == "penalty_results":
            try:
                h, a = ("**", "") if self.fixture.penalties_home > self.fixture.penalties_away else ("", "**")
                home = f"{h}{self.fixture.home} {self.fixture.penalties_home}{h}"
                away = f"{a}{self.fixture.penalties_away} {self.fixture.away}{a}"
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
            e.colour = discord.Colour.greyple()
        elif "start_of_period" in self.mode:
            e.colour = discord.Colour.blurple()
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
    async def full_embed(self):
        """Extended Embed with all events for Extended output mode"""
        e = await self.embed
        if self.fixture.events:
            for i in self.fixture.events:
                if isinstance(i, football.Substitution):
                    continue  # skip subs, they're just spam.

                # Penalties are handled later on.
                if self.fixture.penalties_away:
                    if isinstance(i, football.Penalty) and i.shootout:
                        continue

                if str(i) in e.description:  # Dupes bug.
                    continue
                e.description += f"{str(i)}\n"
        return e

    @property
    def valid_events(self):
        """Valid events for ticker mode"""
        if self.mode == "goal":
            return tuple([football.Goal, football.VAR])
        elif self.mode == "red_card":
            return football.RedCard
        elif self.mode in ("var_goal", "var_red_card"):
            return football.VAR
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
            except discord.NotFound:
                continue
            except discord.HTTPException as err:
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
                await message.edit(embed=embed)
            except discord.HTTPException:
                continue

    async def event_loop(self):
        """The Fixture event's internal loop"""
        # Handle full time only events.
        if self.mode == "kick_off":
            await self.send_messages()
            return

        while self.needs_refresh:
            # Fallback, Wait 2 minutes extra pre refresh
            _ = 120 * self.retry if self.retry in range(5) else False
            if _ is False:
                await self.bulk_edit()
                return
            else:
                await asyncio.sleep(_)

            page = await self.bot.browser.newPage()
            async with max_pages:
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
                    await self.bulk_edit()
                    return
            else:
                await self.send_messages()


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "⚽"
        [reload(_) for _ in [football, view_utils]]

    @commands.Cog.listener()
    async def on_fixture_event(self, mode, f: football.Fixture, home=True):
        """Event handler for when something occurs during a fixture."""
        if mode == "ht_et_begin":  # Special Check - Must pass both
            _ = ["half_time", "extra_time"]
        elif mode == "ht_et_end":  # Special Check - Must pass both
            _ = ["second_half_begin", "extra_time"]
        elif mode == "resumed":
            _ = ["kick_off"]
        elif mode in ["var_red_card", "var_goal", "red_card_overturned", "goal_overturned"]:
            _ = ["var"]
        elif mode in ["interrupted", "postponed", "cancelled"]:
            _ = ["delayed"]
        elif mode in ["extra_time_begins", "end_of_normal_time", "end_of_extra_time"]:
            _ = ["extra_time"]
        elif mode in ["score_after_extra_time", "abandoned", "full_time"]:
            _ = ["full_time"]
        elif mode in ["penalties_begin", "penalty_results"]:
            _ = ["penalties"]
        elif "start_of_period" in mode:
            _ = ["second_half_begin"]
        elif "end_of_period" in mode:
            _ = ["half_time"]
        else:
            _ = [mode]

        connection = await self.bot.db.acquire()

        columns = ", ".join(_)
        not_nulls = " AND ".join([f'({x} IS NOT NULL)' for x in _])
        sql = f"""SELECT {columns}, ticker_settings.channel_id FROM ticker_settings LEFT JOIN ticker_leagues 
                ON ticker_settings.channel_id = ticker_leagues.channel_id WHERE {not_nulls} AND (league = $1::text)"""

        try:
            async with connection.transaction():
                records = await connection.fetch(sql, f.full_league)
        except Exception as e:
            print(sql)
            raise e
        finally:
            await self.bot.db.release(connection)

        for _ in list(records):
            try:
                channel = self.bot.get_channel(_['channel_id'])
                assert channel is not None
                assert channel.permissions_for(channel.guild.me).send_messages
                assert channel.permissions_for(channel.guild.me).embed_links
            except AssertionError:
                records.remove(_)

        channels = [(int(r.pop(-1)), all(r)) for r in [list(x) for x in records]]

        if not channels:  # skip fetch if unwanted.
            return

        # Settings for those IDs
        TickerEvent(self.bot, channels=channels, fixture=f, mode=mode, home=home)

    @commands.slash_command()
    async def ticker(self, ctx):
        """View the config of this channel's Match Event Ticker"""
        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            return await self.bot.error(ctx, "You need manage messages permissions to edit a ticker")

        view = ConfigView(ctx)
        view.message = await self.bot.reply(ctx, content=f"Fetching config for {ctx.channel.mention}...", view=view)
        await view.update()

    @commands.slash_command()
    async def ticker_add(self, ctx, query: LEAGUES):
        """Add a league to your Match Event Ticker"""
        e = discord.Embed()
        e.colour = discord.Colour.red()

        if ctx.guild is None:
            e.description = "This command cannot be ran in DMs"
            await self.bot.reply(ctx, embed=e, ephemeral=True)
            return
        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            e.description = "You need manage messages permissions to edit a ticker"
            await self.bot.reply(ctx, embed=e, ephemeral=True)
            return

        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            row = await connection.fetchrow("""SELECT * FROM ticker_channels WHERE channel_id = $1""", ctx.channel.id)
        await self.bot.db.release(connection)

        if not row:
            # If we cannot add, send to creation dialogue.
            view = ConfigView(ctx)
            view.message = await self.bot.reply(ctx, content=f"Fetching config for {ctx.channel.mention}...", view=view)
            await view.update()
            return

        if "http" not in query:
            res = await football.fs_search(ctx, message, query)
            if res is None:
                e.description = f"No matching competitions found for {query}"
                await self.bot.reply(ctx, embed=e)
                return
        else:
            if "flashscore" not in query:
                e.description = '🚫 Invalid link provided'
                await self.bot.reply(ctx, embed=e)
                return

            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition.by_link(query, page)
            except IndexError:
                e.description = '🚫 Invalid link provided'
                await self.bot.reply(ctx, embed=e)
                return
            finally:
                await page.close()

            if res is None:
                e.description = f"🚫 Failed to get league data from <{query}>."
                await self.bot.reply(ctx, embed=e)
                return

        res = res.title

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            await connection.execute(q, ctx.channel.id, res)
        await self.bot.db.release(connection)

        view = ConfigView(ctx)
        view.message = message
        await view.update(text=f"Added {res} tracked leagues for {ctx.channel.mention}")

    @commands.slash_command()
    async def ticker_add_world_cup(self, ctx):
        """Add the qualifying tournaments for the World Cup to a channel's ticker"""
        e = discord.Embed()
        e.colour = discord.Colour.red()
        if ctx.guild is None:
            e.description = "This command cannot be ran in DMs"
            await self.bot.reply(ctx, embed=e, ephemeral=True)
            return
        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            e.description = "You need manage messages permissions to edit a ticker"
            await self.bot.reply(ctx, embed=e, ephemeral=True)
            return

        channel = ctx.channel

        # Validate.
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            row = await connection.fetchrow("""SELECT * FROM ticker_channels WHERE channel_id = $1""", ctx.channel.id)
        await self.bot.db.release(connection)

        if not row:
            view = ConfigView(ctx)
            view.message = await self.bot.reply(ctx, content=f"Fetching config for {channel.mention}...", view=view)
            await view.update()
            return

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            for res in WORLD_CUP_LEAGUES:
                await connection.execute(q, channel.id, res)
        await self.bot.db.release(connection)

        leagues = "\n".join(WORLD_CUP_LEAGUES)
        await self.bot.reply(ctx, content=f"Added to tracked leagues for {channel.mention}```yaml\n{leagues}```")

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Handle deletion of channel data from database upon channel deletion."""
        q = f"""DELETE FROM ticker_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(q, channel.id)
        await self.bot.db.release(connection)

    # @commands.Cog.listener()
    # async def on_guild_remove(self, guild):
    #     """Delete all data related to a guild from the database upon guild leave."""
    #     q = f"""DELETE FROM ticker_channels WHERE guild_id = $1"""
    #     connection = await self.bot.db.acquire()
    #     async with connection.transaction():
    #         await connection.execute(q, guild.id)
    #     await self.bot.db.release(connection)


def setup(bot):
    """Load the goal tracker cog into the bot."""
    bot.add_cog(Ticker(bot))
