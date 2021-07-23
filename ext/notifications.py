"""Notify server moderators about specific events"""
import asyncio
import datetime
import typing

import discord
from discord.ext import commands

from ext.utils import codeblocks

TWITCH_LOGO = "https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklogo.com.png"


class Notifications(commands.Cog):
    """Guild Moderation Commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.records = []
        self.bot.loop.create_task(self.update_cache())
    
    # TODO: Custom welcome message
    # TODO: Custom Reactions.

    # Db Create / Delete Listeners
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Reload the cog's database info after joining a new guild"""
        await asyncio.sleep(10)  # Time for other cogs to do their shit.
        await self.update_cache()

    async def update_cache(self):
        """Get the latest databse information and load it into memory"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            self.records = await connection.fetch("""SELECT * FROM guild_settings""")
        await self.bot.db.release(connection)
        
    # Master info command.
    @commands.has_permissions(manage_guild=True)
    @commands.command(invoke_without_command=True, usage="mod")
    async def mod(self, ctx):
        """Shows the status of various mod tools."""
        # Get settings.
        e = discord.Embed(color=0x7289DA)
        e.description = ""
        e.set_author(name=ctx.guild.name)
        e.title = f"Notification message settings"
        
        try:
            r = [r for r in self.records if r["guild_id"] == ctx.guild.id][0]
        except IndexError:
            e.description = "No configuration set."
        else:
            for key, value in dict(r).items():
                if key == "guild_id":
                    continue
                key = {"joins_channel_id": "Joins", "leaves_channel_id": "Leaves", "emojis_channel_id": "Emojis",
                       "mutes_channel_id": "Mutes", "deletes_channel_id": "Deleted Messages"}[key]
                    
                try:
                    value = self.bot.get_channel(value).mention if value is not None else "Not set"
                except AttributeError:
                    value = "Deleted channel."
    
                e.description += f"{key}: {value} \n"
        
        e.set_thumbnail(url=ctx.guild.icon_url)
        await ctx.bot.reply(ctx, embed=e)
    
    # Join messages
    @commands.Cog.listener()
    async def on_member_join(self, new_member):
        """Event handler to Dispatch new member information for servers that request it"""
        try:
            joins = [r['joins_channel_id'] for r in self.records if r["guild_id"] == new_member.guild.id][0]
            ch = self.bot.get_channel(joins)
            if ch is None:
                return
        except IndexError:
            return

        # Extended member join information.
        e = discord.Embed()
        e.colour = 0x7289DA
        s = sum(1 for m in self.bot.get_all_members() if m.id == new_member.id)
        e.title = str(new_member)
        e.add_field(name='User ID', value=new_member.id)
        e.add_field(name='Mutual Servers', value=f'{s} shared')
        if new_member.bot:
            e.description = '**This is a bot account**'

        coloured_time = codeblocks.time_to_colour(new_member.created_at)

        e.add_field(name="Account Created", value=coloured_time, inline=False)
        e.set_thumbnail(url=new_member.avatar_url)

        try:
            await ch.send(embed=e)
        except discord.Forbidden:  # If you wanna fuck up your settings it's not my fault.
            pass
    
    @commands.has_permissions(manage_channels=True)
    @commands.group(usage="joins <#channel> to set a new channel, or leave blank to show current information.")
    async def joins(self, ctx, channel: typing.Optional[discord.TextChannel]):
        """Send member information to a channel on join."""
        if channel is None:  # Give current info
            joins = [r['joins_channel_id'] for r in self.records if r["guild_id"] == ctx.guild.id][0]
            ch = self.bot.get_channel(joins)
            rep = " not currently being output" if ch is None else f" currently being output to {ch.mention}"
            return await self.bot.reply(ctx, text=f'Member information is ' + rep)

        if not ctx.me.permissions_in(channel).send_messages:
            return await self.bot.reply(ctx, text=f'🚫 I cannot send messages to {channel.mention}.',
                                        mention_author=True)

        assert channel.guild.id == ctx.guild.id, "You cannot edit the settings of a channel on another server."

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET joins_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()

        await self.bot.reply(ctx, text=f'Information about new users will be sent to {channel.mention} when they join.')

    @commands.has_permissions(manage_channels=True)
    @joins.command(name="off", alaises=["none", "disable"], usages="joins off")
    async def joins_off(self, ctx):
        """Disable information output for new members joining the server"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET joins_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text='Information about new users will no longer be output.')

    # Deleted messages
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Event handler for reposting deleted messages from users/"""
        # Ignore DMs & messages from bots
        if message.guild is None or message.author.bot:
            return

        # ignore commands.
        for i in self.bot.prefix_cache[message.guild.id]:
            if message.content.startswith(i):
                return

        # Filter out deleted numbers - Toonbot.
        # Todo: Code "If message was not deleted by bot or user return "
        try:
            int(message.content)
        except ValueError:
            pass
        else:
            return

        try:
            deletes = [r['deletes_channel_id'] for r in self.records if r["guild_id"] == message.guild.id][0]
            ch = self.bot.get_channel(deletes)
            if ch is None:
                return
        except IndexError:
            return
        
        a = message.author
        
        e = discord.Embed()
        e.set_author(name=f"{a} (ID: {a.id})", icon_url=a.avatar_url)
        e.timestamp = datetime.datetime.now()
        e.set_footer(text=f"🗑️ Deleted message from {message.channel.name}")
        e.description = message.clean_content

        if message.attachments:
            att = message.attachments[0]
            if hasattr(att, "height"):
                v = f"📎 *Attachment info*: {att.filename} ({att.size} bytes, {att.height}x{att.width})," \
                    f"attachment url: {att.proxy_url}"
                e.add_field(name="Attachment info", value=v)

        try:
            await ch.send(embed=e)
        except discord.HTTPException:
            return
        
    @commands.has_permissions(manage_channels=True)
    @commands.group(usage="deletes <#channel> to set a new channel, or leave blank to show current information.")
    async def deletes(self, ctx, channel: typing.Optional[discord.TextChannel]):
        """Copies deleted messages to another channel."""
        if channel is None:  # Give current info
            deletes = [r['deletes_channel_id'] for r in self.records if r["guild_id"] == ctx.guild.id][0]
            ch = self.bot.get_channel(deletes)
            rep = "not currently being output" if ch is None else f"currently being output to {ch.mention}"
            return await self.bot.reply(ctx, text=f'Deleted messages are ' + rep)

        if not ctx.me.permissions_in(channel).send_messages:
            return await self.bot.reply(ctx, text=f"🚫 I can't send messages to {channel.mention}", mention_author=True)

        assert channel.guild.id == ctx.guild.id, "You cannot edit the settings of a channel on another server."

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET deletes_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text=f'Deleted messages will be sent to {channel.mention}.')

    @commands.has_permissions(manage_channels=True)
    @deletes.command(name="off", alaises=["none", "disable"], usages="deletes off")
    async def deletes_off(self, ctx):
        """Disable the reposting of deleted messages by the bot"""
        connection = await self.bot.db.acquire()
        await connection.execute("""UPDATE guild_settings SET deletes_channel_id = $2 WHERE guild_id = $1""",
                                 ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text='Deleted messages will no longer be output.')
    
    # Leave / ban / kick notifications
    @commands.has_permissions(manage_guild=True)
    @commands.group(usage="leaves <#channel> to set a new channel, or leave blank to show current setting")
    async def leaves(self, ctx, channel: typing.Optional[discord.TextChannel] = None):
        """Set a channel to show information about new member joins"""
        if channel is None:  # Show current info
            leaves = [r['leaves_channel_id'] for r in self.records if r["guild_id"] == ctx.guild.id][0]
            ch = self.bot.get_channel(leaves)
            rep = "not currently being output" if ch is None else f"currently being output to {ch.mention}"
            return await self.bot.reply(ctx, text=f'Member leave information is ' + rep)

        if not ctx.me.permissions_in(channel).send_messages:
            return await self.bot.reply(ctx, f'🚫 I cannot send messages to {channel.mention}.', mention_author=True)

        assert channel.guild.id == ctx.guild.id, "You cannot edit the settings of a channel on another server."

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""
                UPDATE guild_settings SET leaves_channel_id = $2 WHERE guild_id = $1
               """, ctx.guild.id, channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()

        await self.bot.reply(ctx, text=f'Notifications will be sent to {channel.mention} when users leave.')

    @commands.has_permissions(manage_channels=True)
    @leaves.command(name="off", alaises=["none", "disable"], usage="leaves off")
    async def leaves_off(self, ctx):
        """Disables the outputting of information about members leaving the server"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET joins_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text='Leave notifications will no longer be output.')

    # Unban notifier.
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """Event handler for outputting information about unbanned users."""
        try:
            unbans = [r['leaves_channel_id'] for r in self.records if r["guild_id"] == guild.id][0]
            ch = self.bot.get_channel(unbans)
        except (IndexError, AttributeError):
            return
    
        if ch is None:
            return
        
        try:
            await ch.send(f"🆗 {user} (ID: {user.id}) was unbanned.")
        except discord.HTTPException:
            pass  # Fuck you.
    
    # Muting and blocking.
    @commands.has_permissions(manage_channels=True)
    @commands.group(usage="mutes <#channel> to set a new channel or leave blank to show current setting>")
    async def mutes(self, ctx, channel: typing.Optional[discord.TextChannel] = None):
        """Set a channel to show messages about user mutings"""
        if channel is None:  # Show current info
            mutes = [r['mutes_channel_id'] for r in self.records if r["guild_id"] == ctx.guild.id][0]
            ch = self.bot.get_channel(mutes)
            rep = " not currently being output" if ch is None else f" currently being output to {ch.mention}"
            return await self.bot.reply(ctx, text=f'Mute notifications are' + rep)

        if not ctx.me.permissions_in(channel).send_messages:
            return await self.bot.reply(ctx, text=f'🚫 I cannot send messages to {channel.mention}.',
                                        mention_author=True)

        assert channel.guild.id == ctx.guild.id, "You cannot edit the settings of a channel on another server."

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET mutes_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text=f"Notifications will be output to {channel.mention} when a member is muted.")

    @commands.has_permissions(manage_channels=True)
    @mutes.command(name="off", alaises=["none", "disable"], usage="leaves off")
    async def mutes_off(self, ctx):
        """Disable outputting information about members being unmuted"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET mutes_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text='Mute and block notifications will no longer be output.')
    
    # Emoji update notifications
    @commands.has_permissions(manage_channels=True)
    @commands.group(usage="emojis <#channe> to set a new channel or leave blank to show current setting>")
    async def emojis(self, ctx, channel: typing.Optional[discord.TextChannel] = None):
        """Set a channel to show when emojis are changed."""
        if channel is None:
            emojis = [r['emojis_channel_id'] for r in self.records if r["guild_id"] == ctx.guild.id][0]
            ch = self.bot.get_channel(emojis)
            rep = "not currently being output." if ch is None else f' currently being output to {ch.mention}'
            return await self.bot.reply(ctx, text="Emoji change notifications are " + rep)

        if not ctx.me.permissions_in(channel).send_messages:
            return await self.bot.reply(ctx, text=f'🚫 I cannot send messages to {channel.mention}.',
                                        mention_author=True)

        assert channel.guild.id == ctx.guild.id, "You cannot edit the settings of a channel on another server."

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""
                UPDATE guild_settings SET emojis_channel_id = $2 WHERE guild_id = $1
               """, ctx.guild.id, channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text=f"Notifications will be sent to {channel.mention} if emojis are changed.")

    @emojis.command(name="off")
    @commands.has_permissions(manage_channels=True)
    async def emojis_off(self, ctx):
        """Disable the outputting of information about emoji additions and removals."""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""UPDATE guild_settings SET emojis_channel_id = $2 WHERE guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text='Emoji update notifications will no longer be output.')

    # # TODO: Blocked
    # @commands.Cog.listener()
    # async def on_guild_channel_update(self, before, after):
    #     pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Event handler for outputting information about mutings and unmutings"""
        try:
            mutes = [r['mutes_channel_id'] for r in self.records if r["guild_id"] == before.guild.id][0]
            ch = self.bot.get_channel(mutes)
        except IndexError:
            return  # Notification channel note set.
        
        if ch is None:
            return
        
        # Notify about member mute/un-mute.
        muted_role = discord.utils.find(lambda r: r.name.lower() == 'muted', before.guild.roles)
        if muted_role in before.roles and muted_role not in after.roles:
            content = f"🙊 {before.mention} was unmuted"
        elif muted_role not in before.roles and muted_role in after.roles:
            content = f"🙊 {before.mention} was muted"
        else:
            return
        
        try:
            async for entry in before.guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=1):
                content += f" by {entry.user} for {entry.reason}"
        except discord.Forbidden:
            pass  # Missing permissions to get reason.
        await ch.send(content)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Event handler for outputting information about member kick, ban, or other departures"""
        # Default outputs
        try:
            ch = [r['leaves_channel_id'] for r in self.records if r["guild_id"] == member.guild.id][0]
            ch = self.bot.get_channel(ch)
        except (AttributeError, TypeError, IndexError):
            return
        
        if ch is None:
            return
        
        output = f"⬅ {member.mention} left the server."
        
        # Check if in mod action log and override to specific channels.
        try:
            async for x in member.guild.audit_logs(limit=5):
                if x.target == member:
                    if x.action == discord.AuditLogAction.kick:
                        output = f"👢 {member.mention} was kicked by {x.user} for {x.reason}."
                    elif x.action == discord.AuditLogAction.ban:
                        output = f"☠ {member.mention} was banned by {x.user} for {x.reason}."
                    break
        except discord.Forbidden:
            pass  # We cannot see audit logs.

        try:
            await ch.send(output)
        except discord.HTTPException:
            return
        
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        """Event listener for outputting information about updated emojis on a server"""
        try:
            ch = guild.get_channel([r['emojis_channel_id'] for r in self.records if r["guild_id"] == guild.id][0])
        except IndexError:
            return
        
        if ch is None:
            return
        
        # Find if it was addition or removal.
        new_emoji = [i for i in after if i not in before]
        if not new_emoji:
            try:
                removed_emoji = [i for i in before if i.id not in [i.id for i in after]][0]
                await ch.send(f"The '{removed_emoji}' emoji was removed")
            except IndexError:
                pass  # :shrug:
        else:
            for emoji in new_emoji:

                e = discord.Embed()
                
                if emoji.user is not None:
                    e.add_field(name="Uploaded by", value=emoji.user.mention)
                
                e.colour = discord.Colour.dark_purple() if emoji.managed else discord.Colour.green()
                if emoji.managed:
                    e.set_author(name="Twitch Integration", icon_url=TWITCH_LOGO)
                    if emoji.roles:
                        e.add_field(name='Required role', value="".join([i.mention for i in emoji.roles]))
                
                e.title = f"New {'animated ' if emoji.animated else ''}emoji: {emoji.name}"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)
                await ch.send(embed=e)
        
        
def setup(bot):
    """Loads the notifications cog into the bot"""
    bot.add_cog(Notifications(bot))
