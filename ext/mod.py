"""Moderation Commands"""
import datetime
import typing

import discord
from discord import Option
from discord.ext import commands

from ext.utils import embed_utils, view_utils, timed_events

MEMBER = Option(discord.Member, "Select a user to ban", required=False)
USER_ID = Option(int, "Ban a user by their ID number", required=False)
DEL_DAYS = Option(int, "Number of days worth of messages to delete", required=False, default=0)


def minutes_autocomplete(ctx):
    """Return number of minutes"""
    autos = range(0, 59)
    return [i for i in autos if ctx.value in str(i)]


def hours_autocomplete(ctx):
    """Return number of hours"""
    autos = range(0, 23)
    return [i for i in autos if ctx.value in str(i)]


def days_autocomplete(ctx):
    """Return number of hours"""
    autos = range(0, 367)
    return [i for i in autos if ctx.value in str(i)]


minutes = Option(int, "Number of minutes", name="minutes", autocomplete=minutes_autocomplete, required=False, default=0)
hours = Option(int, "Number of hours", name="hours", autocomplete=hours_autocomplete, required=False, default=0)
days = Option(int, "Number of days", name="days", autocomplete=days_autocomplete, required=False, default=0)


class Mod(commands.Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot):
        self.bot = bot

    # Listeners
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Create database entry for new guild"""
        await self.create_guild(guild.id)

    # @commands.Cog.listener()
    # async def on_guild_remove(self, guild):
    #     """Delete guild's info upon leaving one."""
    #     await self.delete_guild(guild.id)

    async def create_guild(self, guild_id):
        """Insert the database entry for a new guild"""
        q = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, guild_id)
        finally:
            await self.bot.db.release(connection)
            
    async def delete_guild(self, guild_id):
        """Remove a guild's settings from the database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM guild_settings WHERE guild_id = $1""", guild_id)
        finally:
            await self.bot.db.release(connection)

    @commands.slash_command()
    async def leave(self, ctx):
        """Un-invite the bot from your server"""
        if not ctx.channel.permissions_for(ctx.author).kick_members:
            return await self.bot.reply(ctx, content="You need kick_members permissions to kick me.")

        red = discord.ButtonStyle.red

        view = view_utils.Confirmation(ctx, label_a="Leave", colour_a=red, label_b="Stay")
        await self.bot.reply(ctx, content='Should I leave the server? All of your settings will be wiped.', view=view)

        if view.value:
            await self.bot.reply(ctx, content='Farewell!')
            await ctx.guild.leave()
        else:
            await self.bot.reply(ctx, content="Okay, I'll stick around a bit longer then.")

    @commands.slash_command()
    async def name(self, ctx, *, new_name: str):
        """Rename the bot for your server."""
        if not ctx.channel.permissions_for(ctx.author).manage_nicknames:
            return await self.bot.error(ctx, "You need manage_nicknames permissions to do that.")

        await ctx.me.edit(nick=new_name)
        await self.bot.reply(ctx, content=f"Name changed to {new_name}.")

    @commands.slash_command()
    async def say(self, ctx, destination: typing.Optional[discord.TextChannel] = None, *, message=None):
        """Say something as the bot in specified channel"""
        if not ctx.guild:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if message is None:
            return await self.bot.error(ctx, "You need to specify a message to say.")

        if destination is None:
            destination = ctx

        if destination.guild.id != ctx.guild.id:
            return await self.bot.error(ctx, "You cannot send messages to other servers.")

        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            if not ctx.author.id == self.bot.owner.id:
                return await self.bot.error(ctx, "You need manage_messages permissions to do that")

        if len(message) > 2000:
            return await self.bot.error(ctx, "Message too long. Keep it under 2000.")

        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        await destination.send(message)

    @commands.slash_command()
    async def topic(self, ctx, *, new_topic):
        """Set the topic for the current channel"""
        if not ctx.guild:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if not ctx.channel.permissions_for(ctx.channel).manage_channels:
            return await self.bot.error(ctx, "You need manage_channels permissions to edit the channel topic.")

        await ctx.channel.edit(topic=new_topic)
        await self.bot.reply(ctx, content=f"{ctx.channel.mention} Topic updated")

    @commands.slash_command()
    async def pin(self, ctx, *, message):
        """Pin a message to the current channel"""
        if not ctx.channel.permissions_for(ctx.channel).manage_channels:
            return await self.bot.error(ctx, "You need manage_channels permissions to pin a message.")

        message = await self.bot.reply(ctx, content=message)
        await message.pin()

    @commands.slash_command()
    async def rename(self, ctx, member: discord.Member, new_nickname):
        """Rename a member"""
        if not ctx.guild:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_nicknames:
            return await self.bot.error(ctx, "You need manage_nicknames permissions to rename a user")

        try:
            await member.edit(nick=new_nickname)
        except discord.Forbidden:
            await self.bot.error(ctx, "I can't change that member's nickname.")
        except discord.HTTPException:
            await self.bot.error(ctx, "❔ Member edit failed.")
        else:
            await self.bot.reply(ctx, content=f"{member.mention} has been renamed.")

    @commands.slash_command()
    async def kick(self, ctx, member: discord.Member, reason="unspecified reason."):
        """Kicks the user from the server"""
        if not ctx.guild:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if not ctx.channel.permissions_for(ctx.author).kick_members:
            return await self.bot.error(ctx, "You need kick_members permissions to rename a user")

        try:
            await member.kick(reason=f"{ctx.author.name}: {reason}")
        except discord.Forbidden:
            await self.bot.error(ctx, f"I can't kick {ctx.author.mention}")
        else:
            await self.bot.reply(ctx, content=f"{ctx.author.mention} was kicked.")

    @commands.slash_command()
    async def ban(self, ctx, member: MEMBER, user_id: USER_ID, delete_days: DEL_DAYS, reason="Not specified"):
        """Bans a list of members (or User IDs) from the server, deletes all messages for the last x days"""
        if not ctx.guild:
            return await self.bot.error(ctx, "This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).ban_members:
            return await self.bot.error(ctx, "You need ban_members permissions to ban someone.")

        delete_days = 7 if delete_days > 7 else delete_days

        if member is not None:
            message = f"{member.mention} was banned by {ctx.author} for: \"{reason}\""
            if delete_days:
                message += f", messages from last {delete_days} day(s) were deleted."
            try:
                await member.ban(reason=f"{ctx.author.name}: {reason}", delete_message_days=delete_days)
                await self.bot.reply(ctx, content=message)
            except discord.Forbidden:
                await self.bot.error(ctx, content=f"I can't ban {member.mention}.")

        if user_id is not None:
            target = await self.bot.fetch_user(user_id)
            message = f"☠ UserID {user_id} {target} was banned for reason: \"{reason}\""
            if delete_days:
                message += f", messages from last {delete_days} day(s) were deleted."
            try:
                await self.bot.http.ban(user_id, ctx.message.guild.id)
                await self.bot.reply(ctx, content=message)
            except discord.HTTPException:
                await self.bot.reply(ctx, content=f"⚠ Banning failed for UserID# {user_id}.")

    @commands.slash_command()
    async def unban(self, ctx, user_id: int):
        """Unbans a user from the server"""
        if not ctx.guild:
            return await self.bot.error(ctx, "This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).ban_members:
            return await self.bot.error(ctx, "You need ban_members permissions to unban someone.")

        user = discord.Object(user_id)

        try:
            await ctx.guild.unban(user)
        except discord.HTTPException:
            await self.bot.error(ctx, "I can't unban that user.")
        else:
            target = await self.bot.fetch_user(user_id)
            await self.bot.reply(ctx, content=f"{target} was unbanned")

    @commands.slash_command()
    async def banlist(self, ctx):
        """Show the ban list for the server"""
        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be used in DMs.")

        if not ctx.channel.permissions_for(ctx.author).view_audit_log:
            return await self.bot.error(ctx, "You need view_audit_log permissions to view the ban list.")

        ban_lines = [f"\💀 {x.user.name}#{x.user.discriminator}: {x.reason}" for x in await ctx.guild.bans()]
        if not ban_lines:
            ban_lines = ["☠ No bans found!"]

        e = discord.Embed(color=0x111)
        n = f"≡ {ctx.guild.name} discord ban list"
        _ = ctx.guild.icon.url if ctx.guild.icon is not None else None
        e.set_author(name=n, icon_url=_)
        e.set_thumbnail(url="https://i.ytimg.com/vi/eoTDquDWrRI/hqdefault.jpg")
        e.title = "User (Reason)"

        embeds = embed_utils.rows_to_embeds(e, ban_lines, rows_per=25)
        view = view_utils.Paginator(ctx, embeds)
        view.message = await self.bot.reply(ctx, content="Fetching banlist...", view=view)
        await view.update()

    @commands.slash_command()
    async def clean(self, ctx, number: Option(int, description="Number of messages to delete", default=10)):
        """Deletes my messages from the last x messages in channel"""
        if not ctx.author.permissions_for(ctx.channel).manage_messages:
            return await self.bot.error(ctx, 'You need manage_messages permissions to clear my messages.')

        def is_me(m):
            """Return only messages sent by the bot."""
            return m.author.id == ctx.me.id

        deleted = await ctx.channel.purge(limit=number, check=is_me)
        await self.bot.reply(ctx, content=f'♻ Deleted {len(deleted)} bot message{"s" if len(deleted) > 1 else ""}',
                             delete_after=5)

    @commands.slash_command()
    async def timeout(self, ctx, member: discord.Member, m: minutes, h: hours, d: days, reason="Not specified"):
        """Timeout a user for the specified amount of time."""
        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if not ctx.channel.permissions_for(ctx.author).moderate_members:
            return await self.bot.error(ctx, "You need moderate_members permissions to time someone out.")

        delta = datetime.timedelta(minutes=m, hours=h, days=d)

        target_time = datetime.datetime.now(datetime.timezone.utc) + delta

        t = timed_events.Timestamp(target_time).time_relative

        try:
            await member.timeout(until=target_time, reason=reason)
        except discord.HTTPException:
            await self.bot.error(ctx, "I can't time out that user.")
        else:
            await self.bot.reply(ctx, content=f"{member.mention} was timed out.\nTimeout ends: {t}")

    @commands.slash_command()
    async def untimeout(self, ctx, member: discord.Member):
        """End the timeout for a user."""
        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if not ctx.channel.permissions_for(ctx.author).moderate_members:
            return await self.bot.error(ctx, "You need moderate_members permissions to cancel a timeout.")

        try:
            await member.untimeout()
        except discord.HTTPException:
            await self.bot.error(ctx, "I can't un-timeout that user.")
        else:
            await self.bot.reply(ctx, content=f"{member.mention} is no longer timed out.")

    # @commands.command(usage="<command name to enable>")
    # async def enable(self, ctx, command: str):
    #     """Re-enables a disabled command for this server"""
    #     disable = self.bot.get_command('disable')
    #     await ctx.invoke(disable, command)
    #
    # @commands.command(usage="<command name to disable>")
    # @commands.has_permissions(manage_guild=True)
    # async def disable(self, ctx, command: str):
    #     """Disables a command for this server."""
    #     command = command.lower()
    #
    #     if ctx.invoked_with == "enable":
    #         if command not in self.bot.disabled_cache[ctx.guild.id]:
    #             return await self.bot.reply(ctx, content=f"The {command} command is not disabled on this server.")
    #         else:
    #             connection = await self.bot.db.acquire()
    #             async with connection.transaction():
    #                 await connection.execute("""
    #                     DELETE FROM disabled_commands WHERE (guild_id,command) = ($1,$2)
    #                    """, ctx.guild.id, command)
    #             await self.bot.db.release(connection)
    #             await self.update_cache()
    #             return await self.bot.reply(ctx, content=f"The {command} command was enabled for {ctx.guild.name}")
    #     elif ctx.invoked_with == "disable":
    #         if command in self.bot.disabled_cache[ctx.guild.id]:
    #             return await self.bot.reply(ctx, content=f"The {command} command is already disabled on this server.")
    #
    #
    #     if command in ('disable', 'enable'):
    #         return await self.bot.reply(ctx, content='You cannot disable the disable command.')
    #     elif command not in [i.name for i in list(self.bot.commands)]:
    #         return await self.bot.reply(ctx, content='Unrecognised command name.')
    #
    #     connection = await self.bot.db.acquire()
    #     await connection.execute("""INSERT INTO disabled_commands (guild_id,command) VALUES ($1,$2)""",
    #                              ctx.guild.id, command)
    #     await self.bot.db.release(connection)
    #     await self.update_cache()
    #     return await self.bot.reply(ctx, content=f"The {command} command was disabled for {ctx.guild.name}")
    #
    # @commands.command(usage="disabled")
    # @commands.has_permissions(manage_guild=True)
    # async def disabled(self, ctx):
    #     """Check which commands are disabled on this server"""
    #     try:
    #         disabled = self.bot.disabled_cache[ctx.guild.id]
    #     except KeyError:
    #         disabled = ["None"]
    #
    #     header = f"The following commands are disabled on this server:"
    #     embeds = embed_utils.rows_to_embeds(discord.Embed(), disabled, header=header)
    #
    #     view = view_utils.Paginator(ctx, embeds)
    #     view.message = await self.bot.reply(ctx, content="Fetching disabled commands...", view=view)
    #     await view.update()

def setup(bot):
    """Load the mod cog into the bot"""
    bot.add_cog(Mod(bot))
