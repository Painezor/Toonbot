"""Commands to set up Automatic Moderation to handle misbehaving users"""
import datetime
from collections import defaultdict

import discord
from discord import Option
from discord.ext import commands

PINGS = Option(int, description="Number of pings to trigger timeout (set to 0 to disable)")


class AutoMod(commands.Cog):
    """Set up automated moderation tools"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.update_cache())
        self.cache = defaultdict()

    @property
    def base_embed(self):
        """Base Embed for commands in this cog."""
        e = discord.Embed()
        e.set_author(name=f"{self.emoji} {self.qualified_name}")
        e.colour = discord.Colour.og_blurple()
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        return e

    async def update_cache(self):
        """Reload the latest version of the database into memory"""
        self.cache.clear()
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""SELECT * FROM mention_spam""")
        await self.bot.db.release(connection)

        for r in records:
            r = {r['guild_id']:
                     {"mention_threshold": r["mention_threshold"],
                      "mention_action": r['mention_action']}}
            self.cache.update(r)

    @commands.slash_command()
    async def mentionspam(self, ctx, threshold: PINGS = None):
        """Time out members for pinging more than x users in a message. Set to 0 to disable."""
        if not ctx.channel.permissions_for(ctx.author).moderate_members:
            return await self.bot.error(ctx, "You need the moderate_members permission to run this command.")

        e = self.base_embed
        e.title = "Ping Spamming"

        if threshold is None:  # Get current settings.
            try:
                c = self.cache[ctx.guild.id]
                action = c['mention_action']
                threshold = c['mention_threshold']
                e.description = f"Current action: {action.title()}\nFor pinging {threshold} or more users in a message."
            except KeyError:
                e.description = f"No action is currently being taken against users who spam pings."
            return await self.bot.reply(ctx, embed=e)

        if threshold < 4:
            return await self.bot.error(ctx, "Please set a limit higher than 3.")

        if not ctx.channel.permissions_for(ctx.author).moderate_members:
            return await self.bot.error(ctx, "You need moderate_members permissions to do that.")
        e.description = f"Users will be timed out for 1 hour if they ping {threshold} users in a message."

        if threshold == 0:
            connection = await self.bot.db.acquire()
            async with connection.transaction():
                await connection.execute("""DELETE FROM mention_spam WHERE (guild_id) = ($1)""", ctx.guild.id)
            await self.bot.db.release(connection)
            await self.update_cache()
            return await self.bot.reply(ctx, "Users will no longer be timed out for spam pinging.")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""
                    INSERT INTO mention_spam (guild_id,mention_threshold) VALUES ($1, $2) 
                    ON CONFLICT (guild_id) DO UPDATE 
                    SET (mention_threshold) = ($2,$3) WHERE EXCLUDED.guild_id = $1""", ctx.guild.id, threshold)
        finally:
            await self.bot.db.release(connection)
        await self.update_cache()
        return await self.bot.reply(ctx, embed=e)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Check every single message to see if they trigger any auto-moderation rules"""
        pings = len(set(message.mentions))

        try:
            guild_cache = self.cache[message.guild.id]
            if guild_cache["mention_threshold"] > pings:
                return
            await message.author.timeout_for(datetime.timedelta(hours=1), reason="Ping spamming: {}")
            e = discord.Embed(title="Timed Out")
            e.description = f"You were timed out for pinging {pings} users in a message."
            e.colour = discord.Colour.red()
            await self.bot.reply(message, embed=e)
        except (KeyError, AttributeError, discord.Forbidden, discord.HTTPException):
            return


def setup(bot):
    """Load the Automatic Moderation Cog"""
    bot.add_cog(AutoMod(bot))
