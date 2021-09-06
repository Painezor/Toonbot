"""Testing Cog for new commands."""
import discord
from discord.ext import commands

from ext.utils import view_utils, embed_utils


class SettingsButton(discord.ui.Button):
    """A generic button for a config embed setting."""

    def __init__(self, label):
        super().__init__(label=label)
        self.emojis = ['🔴', '🟢', '🔵']  # red, green, blue
        self.settings = [None, False, True]

    def rotate(self):
        """Cycle through emoji & setting to get next in each"""
        self.emojis = self.emojis[-1:] + self.emojis[:-1]
        self.settings = self.settings[-1:] + self.settings[:-1]


class ConfigView(discord.ui.View):
    """Generic Config View"""

    def __init__(self, ctx, channel):
        super().__init__()
        self.page = 0
        self.ctx = ctx
        self.channel = channel
        self.message = None

    async def get_settings(self):
        """Fetch settings for a View's channel"""
        connection = self.ctx.bot.db.acquire()
        async with connection.transaction():
            settings = await connection.fetch("""SELECT * FROM ticker_settings WHERE channel_id = $1""",
                                              self.channel.id)
        await self.ctx.bot.db.release(connection)
        return settings

    async def get_leagues(self):
        """Fetch Leagues for View's Channel"""
        connection = self.ctx.bot.db.acquire()
        async with connection.transaction():
            leagues = await connection.fetch("""SELECT * FROM ticker_leagues WHERE channel_id = $1""", self.channel.id)
        await self.ctx.bot.db.release(connection)
        leagues = [r['league'] for r in leagues]
        return leagues

    async def update(self):
        """TODO ...."""
        pass

    async def generate_embeds(self):
        """Formatted Ticker Embed"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Toonbot Ticker config"
        e.set_thumbnail(url=self.channel.me.user.display_avatar.url)

        header = f'Tracked leagues for {self.channel.mention}'
        # Warn if they fuck up permissions.
        if not self.channel.permissions_for(self.ctx.me).send_messages:
            v = f"```css\n[WARNING]: I do not have send_messages permissions in {self.channel.mention}!"
            e.add_field(name="Cannot Send Messages", value=v)
        if not self.channel.permissions_for(self.ctx.me).embed_links:
            v = f"```css\n[WARNING]: I do not have embed_links permissions in {self.channel.mention}!"
            e.add_field(name="Cannot send Embeds", value=v)

        leagues = self.get_leagues()

        if not leagues:
            leagues = ["```css\n[WARNING]: Your tracked leagues is completely empty! Nothing is being output!```"]
        embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=header)
        return embeds


# TODO: Button to Toggle Substitutes in Extended Views


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🧪"

    def cog_check(self, ctx):
        """Assure all commands in this cog can only be ran on the r/NUFC discord"""
        if ctx.guild:
            return ctx.channel.id == 873620981497876590 or ctx.author.id == 210582977493598208

    # TODO: Delete channel from DB
    async def delete_ticker(self, channel_id):
        """Purge a channel from the database"""

    # TODO: Insert channel to DB
    async def create_ticker(self, channel):
        """Create a database entry for this channel."""

    async def get_guild_channels(self, ctx, channel):
        """Fetch all guild tickers"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            channels = await connection.fetch("""SELECT * FROM ticker_channels WHERE guild_id = $1""", ctx.guild.id)
        await self.bot.db.release(connection)

        validated = [channel]
        # Database cleanup -- If a channel is not found, delete it from the database.
        for _ in list(channels):  # Copy for popping.
            cid = _['channel_id']
            ch = self.bot.get_channel(cid)
            if ch is None:
                await self.delete_ticker(cid)
            else:
                if ch.id != channel.id:
                    validated.append(ch)

        if len(validated) == 1:
            return validated[0]

        view = view_utils.ChannelPicker(ctx.author, validated)
        view.message = await self.bot.reply(ctx, "Configure ticker for which channel?", view=view)
        await view.wait()
        return validated[int(view.value)]

    async def get_channel_settings(self, ctx, channel):
        """Get channel to be modified"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            settings = await connection.fetchrow("""SELECT * FROM ticker_settings WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)

        if not settings:
            # If the channel is not found in the DB, ask user if they would like to create a ticker.
            view = view_utils.Confirmation(ctx.author, f"Create Ticker for {channel.mention}?", "Cancel")
            view.message = await self.bot.reply(ctx, f"No ticker found in {channel.mention}", view=view)
            await view.wait()
            if view.value:
                await self.create_ticker(channel)
            return

        view = ConfigView(ctx, channel)
        view.message = await self.bot.reply(ctx, f"Fetching config for {channel.mention}...", view=view)
        await view.update()

    @commands.command()
    async def tkr(self, ctx, channel: discord.TextChannel = None):
        """Configure your Match Event Ticker"""
        channel = ctx.channel if channel is None else channel
        channel = await self.get_guild_channels(ctx, channel)
        await self.get_channel_settings(ctx, channel)


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))
