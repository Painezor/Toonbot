"""Commands to set up Automatic Moderation to handle misbehaving users"""
import typing
from collections import defaultdict

import discord
from discord.ext import commands


class AutoMod(commands.Cog):
    """Set up automated moderation tools"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🛡️"
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

    @commands.has_permissions(manage_guild=True)
    @commands.command(usage="mentionspam <number of pings> <'kick', or 'ban'>", aliases=["pingspam"])
    async def mentionspam(self, ctx, threshold: typing.Optional[int] = None, action=None):
        """Automatically kick or ban a member for pinging more than x users in a message.
        Use '0' for threshold to turn the feature off."""
        e = self.base_embed
        e.title = "Ping Spamming"
        error = ""

        if threshold is None:  # Get current settings.
            try:
                c = self.cache[ctx.guild.id]
                action = c['mention_action']
                threshold = c['mention_threshold']
                e.description = f"I will {action} members who ping {threshold} or more other users in a message."
            except KeyError:
                e.description = f"No action is currently being taken against users who spam mentions."
            return await self.bot.reply(ctx, embed=e)

        if threshold < 4:
            error += "Please set a limit higher than 3.\n"

        action = action.lower() if action is not None else action
        if action is None or action not in ['kick', 'ban']:
            error += "🚫 Invalid action specified, valid modes are: `kick`, `ban`.",
        elif action == "kick":
            if not ctx.channel.permissions_for(ctx.me).kick_members:
                error += "🚫 I need the 'kick_members' permission to do that.\n"
            if not ctx.channel.permissions_for(ctx.author).kick_members:
                error += "🚫 You need the 'kick_members' permission to do that.\n"
        elif action == "ban":
            if not ctx.channel.permissions_for(ctx.me).ban_members:
                error += "🚫 I need the 'ban_members' permission to do that.\n"
            if not ctx.channel.permissions_for(ctx.author).ban_members:
                error += "🚫 You need the 'ban_members' permission to do that.\n"

        if error:
            e.description = error
            e.colour = discord.Colour.red()
            return await self.bot.reply(ctx, embed=e)

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(
                """INSERT INTO mention_spam (guild_id,mention_threshold, mention_action) VALUES ($1, $2, $3) ON CONFLICT 
                (guild_id) DO UPDATE SET (mention_threshold, mention_action) = ($2,$3) WHERE EXCLUDED.guild_id = $1""",
                ctx.guild.id, threshold, action)
        await self.bot.db.release(connection)
        await self.update_cache()

        action = "banned" if action == "ban" else "kicked"
        e.description = f"Users will be {action} if they ping {threshold} users in a message."
        return await self.bot.reply(ctx, embed=e)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Check every single message to see if they trigger any auto-moderation rules"""
        try:
            guild_cache = self.cache[message.guild.id]
            if guild_cache["mention_threshold"] > len(message.mentions):
                return
        except (KeyError, AttributeError):
            return

        try:
            assert guild_cache["mention_action"] in ['kick', 'ban']
        except AssertionError:
            return

        if guild_cache["mention_action"] == "kick":
            try:
                await message.author.kick(reason=f"Mentioning {guild_cache['mention_threshold']} members in a message.")
            except discord.Forbidden:
                return
            else:
                reply = f"{message.author.mention} was kicked for mention spamming."

        else:
            try:
                await message.author.ban(reason=f"Mentioning {guild_cache['mention_threshold']} members in a message.")
            except discord.HTTPException:
                return
            else:
                reply = f"☠️{message.author.mention} was banned for mention spamming."

        try:
            return await message.reply(reply)
        except discord.HTTPException:
            return


def setup(bot):
    """Load the Automatic Moderation Cog"""
    bot.add_cog(AutoMod(bot))

# TODO: Bad words filters
