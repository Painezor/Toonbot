"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
import asyncio
import typing
from importlib import reload

import discord
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


class ToggleButton(discord.ui.Button):
    """A Button to toggle the ticker settings."""

    def __init__(self, label, emoji):
        super().__init__(label=label, emoji=emoji)

    async def callback(self, interaction: discord.Interaction):
        """Set view value to button value"""
        await interaction.response.defer()
        self.view.value = self.label
        self.view.stop()


class ChangeSetting(discord.ui.View):
    """Toggle a setting"""

    def __init__(self, owner):
        super().__init__()
        self.add_item(ToggleButton(label='Off', emoji='🔴'))
        self.add_item(ToggleButton(label='On', emoji='🟢'))
        self.add_item(ToggleButton(label='Extended', emoji='🔵'))
        self.owner = owner
        self.value = None
        self.message = None

    async def on_timeout(self) -> None:
        """Cleanup"""
        try:
            await self.message.delete()
        except discord.HTTPException:
            pass
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction):
        """Assure owner is the one clicking buttons."""
        return self.owner.id == interaction.user.id


class SettingsSelect(discord.ui.Select):
    """The Dropdown that lists all configurable settings for a ticker"""

    def __init__(self, settings):
        self.settings = settings
        super().__init__(placeholder="Turn events on or off", row=3)

        for k, v in sorted(self.settings.items()):
            if k == "channel_id":
                continue
            title = k.replace('_', ' ').title()

            if v is None:
                emoji = '🔴'
            else:
                emoji = '🔵' if v else '🟢'

            if v is not None:
                extended = "Extended notifications are being sent" if v else "Notifications are being sent"
            else:
                extended = "Nothing is being sent"

            if title == "Goal":
                description = f"{extended} when goals are scored."
                title = 'Scored Goals'

            elif title == "Delayed":
                title = "Delayed Games"
                description = f"{extended} when games are delayed."

            elif title in ['Half Time', 'Full Time', 'Extra Time']:
                description = f"{extended} at {title}"
            elif title == "Kick Off":
                description = f"{extended} when a match kicks off."

            elif title == "Final Result Only":
                title = "Full Time for Final Result Only games  "
                description = f"{extended} when the final result of a game is detected."

            elif title == "Second Half Begin":
                title = "Start of Second Half"
                description = f"{extended} at the start of the second half of a game."

            elif title == "Red Card":
                title = "Red Cards"
                description = f"{extended} for Red Cards"

            elif title == "Var":
                title = "VAR Reviews"
                description = f"{extended} when goals or cards are overturned."

            elif title == "Penalties":
                title = "Penalty Shootouts"
                description = f"{extended} for penalty shootouts."
            else:
                description = v

            if v is not None:
                v = "Extended" if v else "On"
            else:
                v = "Off"

            title = f"{title} ({v})"
            self.add_option(label=title, emoji=emoji, description=description, value=k)

    async def callback(self, interaction: discord.Interaction):
        """When an option is selected."""
        await interaction.response.defer()
        await self.view.change_setting(self.values[0])


class ResetLeagues(discord.ui.Button):
    """Button to reset a ticker back to it's default leagues"""

    def __init__(self):
        super().__init__(label="Reset to default leagues", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.reset_leagues()


class DeleteTicker(discord.ui.Button):
    """Button to delete a ticker entirely"""

    def __init__(self):
        super().__init__(label="Delete ticker", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.delete_ticker()


class RemoveLeague(discord.ui.Select):
    """Button to bring up the settings dropdown."""

    def __init__(self, leagues):
        super().__init__(placeholder="Remove tracked league(s)", row=4)
        self.max_values = len(leagues)

        for league in sorted(leagues):
            self.add_option(label=league)

    async def callback(self, interaction: discord.Interaction):
        """When a league is selected"""
        await interaction.response.defer()
        await self.view.remove_leagues(self.values)


class ConfigView(discord.ui.View):
    """Generic Config View"""

    def __init__(self, ctx, channel):
        super().__init__()
        self.index = 0
        self.ctx = ctx
        self.channel = channel
        self.message = None
        self.pages = None
        self.settings = None

    async def on_timeout(self):
        """Hide menu on timeout."""
        try:
            await self.message.delete()
        except discord.HTTPException:
            pass
        self.stop()

    @property
    def base_embed(self):
        """Generic Embed for Config Views"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Toonbot Ticker config"
        e.set_thumbnail(url=self.ctx.bot.user.display_avatar.url)
        return e

    async def change_setting(self, db_field):
        """Edit a setting in the database for a channel."""
        view = ChangeSetting(self.ctx.author)

        if db_field == "goal":
            description = f"when goals are scored."

        elif db_field == "delayed":
            description = f"delayed games."

        elif db_field in ['half_time', 'full_time', 'extra_time']:
            description = f"{db_field.replace('_', ' ').title()} events."

        elif db_field == "kick_off":
            description = f"when a match kicks off."

        elif db_field == "final_result_only":
            description = f"when the final result of a game is detected."

        elif db_field == "second_half_begin":
            description = f"the start of the second half of a game."

        elif db_field == "red_Card":
            description = f"Red Cards"

        elif db_field == "var":
            description = f"overturned goals & red cards."

        elif db_field == "penalties":
            description = f"penalty shootouts."
        else:
            description = db_field

        view.message = await self.ctx.bot.reply(self.ctx, f"Toggle notifications for {description}", view=view)
        await view.wait()

        if view.value:
            _ = {"On": False, "Off": None, "Extended": True}
            toggle = _[view.value]
            connection = await self.ctx.bot.db.acquire()
            async with connection.transaction():
                q = f"""UPDATE ticker_settings SET {db_field} = $1 WHERE channel_id = $2"""
                await connection.execute(q, toggle, self.channel.id)
            await self.ctx.bot.db.release(connection)

            answer = "on extended" if view.value == "Extended" else view.value.lower()
            if _ is None:
                emoji = '🔴'
            else:
                emoji = '🟢' if _ else '🔵'

            await self.ctx.bot.reply(self.ctx, f"{emoji} Turned {answer} notifications for {description}")
            await view.message.delete()
            await self.update()
        else:
            self.stop()
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass

    async def get_settings(self):
        """Fetch settings for a View's channel"""
        connection = await self.ctx.bot.db.acquire()
        async with connection.transaction():
            stg = await connection.fetchrow("""SELECT * FROM ticker_settings WHERE channel_id = $1""", self.channel.id)
        await self.ctx.bot.db.release(connection)

        if not stg:
            stg = await self.creation_dialogue()

        self.settings = stg

    async def get_leagues(self):
        """Fetch Leagues for View's Channel"""
        connection = await self.ctx.bot.db.acquire()
        async with connection.transaction():
            leagues = await connection.fetch("""SELECT * FROM ticker_leagues WHERE channel_id = $1""", self.channel.id)
        await self.ctx.bot.db.release(connection)

        leagues = [r['league'] for r in leagues]
        return leagues

    async def creation_dialogue(self):
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()
        view = view_utils.Confirmation(owner=self.ctx.author, colour_a=discord.ButtonStyle.green,
                                       label_a=f"Create a ticker for #{self.channel.name}", label_b="Cancel")
        _ = f"{self.channel.mention} does not have a ticker, would you like to create one?"
        view.message = await self.ctx.bot.reply(self.ctx, _, view=view)
        await view.wait()
        try:
            await view.message.delete()
        except discord.HTTPException:
            pass

        if view.value:
            connection = await self.ctx.bot.db.acquire()
            async with connection.transaction():
                q = """INSERT INTO ticker_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)"""
                qqq = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
                await connection.execute(q, self.channel.guild.id, self.channel.id)
                self.settings = await connection.fetchrow(qq, self.channel.id)
                for x in DEFAULT_LEAGUES:
                    await connection.execute(qqq, self.channel.id, x)
            await self.ctx.bot.db.release(connection)
        else:
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass
            self.stop()
            return

        try:
            await self.message.delete()
        except discord.HTTPException:
            pass

        self.message = await self.ctx.bot.reply(self.ctx, ".", view=self)
        await self.update()

    async def update(self):
        """Push newest version of view to message"""
        self.clear_items()
        await self.get_settings()
        if self.settings is None:
            return

        leagues = await self.get_leagues()

        if leagues:
            await self.generate_embeds(leagues)

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

            embed = self.pages[self.index]

            self.add_item(SettingsSelect(self.settings))

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues))
            cont = ""
        else:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            embed = None
            cont = f"You have no tracked leagues for {self.channel.mention}, would you like to reset or delete it?"

        am = discord.AllowedMentions.none()
        try:
            await self.message.edit(content=cont, embed=embed, view=self, allowed_mentions=am)
        except discord.NotFound:
            self.stop()
            return

    async def generate_embeds(self, leagues):
        """Formatted Ticker Embed"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Toonbot Ticker config"
        e.set_thumbnail(url=self.channel.guild.me.display_avatar.url)

        header = f'Tracked leagues for {self.channel.mention}```yaml\n'
        # Warn if they fuck up permissions.
        if not self.channel.permissions_for(self.ctx.me).send_messages:
            v = f"```css\n[WARNING]: I do not have send_messages permissions in {self.channel.mention}!"
            e.add_field(name="Cannot Send Messages", value=v)
        if not self.channel.permissions_for(self.ctx.me).embed_links:
            v = f"```css\n[WARNING]: I do not have embed_links permissions in {self.channel.mention}!"
            e.add_field(name="Cannot send Embeds", value=v)

        if not leagues:
            leagues = ["```css\n[WARNING]: Your tracked leagues is completely empty! Nothing is being output!```"]
        embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=header, footer="```", rows_per=25)
        self.pages = embeds

    async def remove_leagues(self, leagues):
        """Bulk remove leagues from a ticker."""
        red = discord.ButtonStyle.red
        view = view_utils.Confirmation(owner=self.ctx.author, label_a="Remove", label_b="Cancel", colour_a=red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        _ = f"Remove these leagues from {self.channel.mention}? {lg_text}"
        view.message = await self.ctx.bot.reply(self.ctx, _, view=view)
        await view.wait()

        if view.value:
            connection = await self.ctx.bot.db.acquire()
            async with connection.transaction():
                for x in leagues:
                    await connection.execute("""DELETE from ticker_leagues WHERE (channel_id, league) = ($1, $2)""",
                                             self.channel.id, x)
            await self.ctx.bot.db.release(connection)
            await self.ctx.bot.reply(self.ctx, f"Removed from {self.channel.mention} tracked leagues: {lg_text} ")

            await self.message.delete()
            self.message = await self.ctx.bot.reply(self.ctx, ".", view=self)

        await self.update()

    async def reset_leagues(self):
        """Reset a channel to default leagues."""
        connection = await self.ctx.bot.db.acquire()
        async with connection.transaction():
            for x in DEFAULT_LEAGUES:
                q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2)"""
                await connection.execute(q, self.channel.id, x)
        await self.ctx.bot.db.release(connection)
        await self.ctx.bot.reply(self.ctx, f"Reset the tracked leagues for {self.channel.mention}")
        await self.message.delete()
        self.message = await self.ctx.bot.reply(self.ctx, ".", view=self)
        await self.update()

    async def delete_ticker(self):
        """Deleete the ticker from a channel"""
        connection = await self.ctx.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM ticker_channels WHERE channel_id = $1""", self.channel.id)
        await self.ctx.bot.db.release(connection)
        await self.message.delete()
        await self.ctx.bot.reply(self.ctx, f"The ticker for {self.channel.mention} was deleted.")
        self.stop()


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
            e.description = f"**Kick Off** | [{self.fixture.bold_score}]({self.fixture.url})"
            e.colour = discord.Colour.lighter_gray()

        elif "ht_et" in self.mode:
            temp_mode = "Half Time" if self.mode == "ht_et_begin" else "Second Half Begins"
            e.description = f"Extra Time: {temp_mode} | [{self.fixture.bold_score}]({self.fixture.url})"

        elif self.mode in ["goal", "var_goal", "red_card", "var_red_card"]:
            h, a = ('**', '') if self.home else ('', '**')  # Bold Home or Away Team Name.
            h, a = ('**', '**') if self.home is None else (h, a)
            home = f"{h}{self.fixture.home} {self.fixture.score_home}{h}"
            away = f"{a}{self.fixture.score_away} {self.fixture.away}{a}"
            e.description = f"**{m}** | [{home} - {away}]({self.fixture.url})\n"

        elif self.mode == "penalties_begin":
            e.description = f"**Penalties Begin** | {self.fixture.bold_score}"

        elif self.mode == "penalty_results":
            try:
                h, a = ("**", "") if self.fixture.penalties_home > self.fixture.penalties_away else ("", "**")
                home = f"{h}{self.fixture.home} {self.fixture.penalties_home}{h}"
                away = f"{a}{self.fixture.penalties_away} {self.fixture.away}{a}"

                e.description = f"**Penalty Shootout Results** | [{home} - {away}]({self.fixture.url})"
            except TypeError:  # If penalties_home / penalties_away are NoneType
                e.description = f"**Penalty Shootout Results** | [{self.fixture.bold_score}]({self.fixture.url})\n"

            events = [i for i in self.fixture.events if isinstance(i, football.Penalty) and i.shootout is True]

            # iterate through everything after penalty header
            home = [str(i) for i in events if i.team == self.fixture.home]
            away = [str(i) for i in events if i.team == self.fixture.away]

            if home:
                e.add_field(name=self.fixture.home, value="\n".join(home))
            if away:
                e.add_field(name=self.fixture.away, value="\n".join(away))

        else:
            e.description = f"**{m}** | [{self.fixture.bold_score}]({self.fixture.url})\n"

        # Fetch Embed Colour
        if "end_of_period" in self.mode:
            e.colour = discord.Colour.greyple()
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
                if isinstance(i, (football.Substitution, football.Booking)):
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
            print(f'[WARNING] {self.fixture} Ticker: Attempted to retract event for missing mode: {self.mode}')

    async def send_messages(self):
        """Dispatch latest event embed to all applicable channels"""
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

    async def get_channel_settings(self, ctx, channel):
        """Get channel to be modified"""
        view = ConfigView(ctx, channel)
        view.message = await self.bot.reply(ctx, f"Fetching config for {channel.mention}...", view=view)
        await view.update()

    @commands.group(invoke_without_command=True, usage="<channel to modify>", aliases=['ticker'])
    @commands.has_permissions(manage_channels=True)
    async def tkr(self, ctx, channel: discord.TextChannel = None):
        """Configure your Match Event Ticker"""
        channel = ctx.channel if channel is None else channel
        await self.get_channel_settings(ctx, channel)

    @tkr.command(usage="<name of league to search for>")
    async def add(self, ctx, query: commands.clean_content = None):
        """Add a league to your Match Event Ticker"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            row = await connection.fetchrow("""SELECT * FROM ticker_channels WHERE channel_id = $1""", ctx.channel.id)
        await self.bot.db.release(connection)

        if not row:
            return await self.get_channel_settings(ctx, ctx.channel)

        if query is None:
            err = '🚫 You need to specify a search query or a flashscore league link'
            return await self.bot.reply(ctx, text=err, ping=True)

        if "http" not in query:
            res = await football.fs_search(ctx, query)
            if res is None:
                return await self.bot.reply(ctx, f"No matching competitions found for {query}")
        else:
            if "flashscore" not in query:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', ping=True)

            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition.by_link(query, page)
            except IndexError:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', ping=True)
            finally:
                await page.close()

            if res is None:
                return await self.bot.reply(ctx, text=f"🚫 Failed to get league data from <{query}>.", ping=True)

        res = res.title

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            await connection.execute(q, ctx.channel.id, res)
        await self.bot.db.release(connection)

        await self.bot.reply(ctx, text=f"Added to tracked leagues for {ctx.channel.mention}```yaml\n{res}```")
        await self.get_channel_settings(ctx, ctx.channel)

    @tkr.command(usage="<channel to modify>")
    @commands.has_permissions(manage_channels=True)
    async def addwc(self, ctx, channel: discord.TextChannel = None):
        """ Temporary command: Add the qualifying tournaments for the World Cup to a channel's ticker"""
        channel = ctx.channel if channel is None else channel

        # Validate.
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            row = await connection.fetchrow("""SELECT * FROM ticker_channels WHERE channel_id = $1""", ctx.channel.id)
        await self.bot.db.release(connection)

        if not row:
            return await self.get_channel_settings(ctx, ctx.channel)

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            for res in WORLD_CUP_LEAGUES:
                await connection.execute(q, channel.id, res)
        await self.bot.db.release(connection)

        leagues = "\n".join(WORLD_CUP_LEAGUES)
        await self.bot.reply(ctx, text=f"Added to tracked leagues for {channel.mention}```yaml\n{leagues}```")

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Handle deletion of channel data from database upon channel deletion."""
        q = f"""DELETE FROM ticker_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(q, channel.id)
        await self.bot.db.release(connection)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete all data related to a guild from the database upon guild leave."""
        q = f"""DELETE FROM ticker_channels WHERE guild_id = $1"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(q, guild.id)
        await self.bot.db.release(connection)


def setup(bot):
    """Load the goal tracker cog into the bot."""
    bot.add_cog(Ticker(bot))
