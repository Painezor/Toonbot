"""Testing Cog for new commands."""
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import view_utils, embed_utils, football

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
        self.row = 0
        super().__init__(placeholder="Turn events on or off")

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
        super().__init__(placeholder="Remove tracked league(s)")
        self.row = 2
        if len(leagues) > 25:
            leagues = leagues[self.view.index * 25:]
            if len(leagues) > 25:
                leagues = leagues[:25]
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
            await self.message.delete()
            self.stop()

        await self.message.delete()
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
            self.add_item(RemoveLeague(leagues))
            cont = ""
        else:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            embed = None
            cont = f"You have no tracked leagues for {self.channel.mention}, would you like to reset or delete it?"

        await self.message.edit(content=cont, embed=embed, view=self, allowed_mentions=discord.AllowedMentions.none())

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


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🧪"
        reload(view_utils)

    def cog_check(self, ctx):
        """Assure all commands in this cog can only be ran on the r/NUFC discord"""
        if ctx.guild:
            return ctx.channel.id == 873620981497876590 or ctx.author.id == 210582977493598208

    # TODO: Delete channel from DB
    async def delete_ticker(self, channel_id):
        """Purge a channel from the database"""

    async def get_channel_settings(self, ctx, channel):
        """Get channel to be modified"""
        view = ConfigView(ctx, channel)
        view.message = await self.bot.reply(ctx, f"Fetching config for {channel.mention}...", view=view)
        await view.update()

    @commands.group(invoke_without_command=True)
    @commands.is_owner()
    async def tkr(self, ctx, channel: discord.TextChannel = None):
        """Configure your Match Event Ticker"""
        if channel is None:
            return await self.bot.reply(ctx, "You need to specify the channel you wish to check or modify.", ping=True)
        await self.get_channel_settings(ctx, channel)

    @tkr.command()
    @commands.is_owner()
    async def add(self, ctx, channel: discord.TextChannel = None, query: commands.clean_content = None):
        """Add a league to your Match Event Ticker"""
        if channel is None:
            return await self.bot.reply(ctx, "You need to specify the channel you wish to check or modify.", ping=True)

        if query is None:
            err = '🚫 You need to specify a search query or a flashscore league link'
            return await self.bot.reply(ctx, text=err, ping=True)

        if "http" not in query:
            await self.bot.reply(ctx, text=f"Searching for {query}...", delete_after=5)
            res = await football.fs_search(ctx, query)
            if res is None:
                return
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

            res = f"{res.title}"

            connection = await self.bot.db.acquire()
            async with connection.transaction():
                q = """INSERT INTO ticker_leagues VALUES $1 WHERE channel_id = $2"""
                await connection.execute(q, res, channel.id)

            await self.bot.reply(ctx, text=f"✅ **{res}** added to the tracked leagues for {channel.mention}")
            await self.get_channel_settings(ctx, channel)


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))

# Maybe TO DO: Button to Toggle Substitutes in Extended Views
