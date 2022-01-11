"""Notify server moderators about specific events"""
import datetime

import discord
from discord.ext import commands

from ext.utils import timed_events, view_utils

TWITCH_LOGO = "https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklogo.com.png"


# Unhandled Events
# on_bulk_message_delete
# on_message_edit
# on_reaction_clear
# on_guild_channel_create
# on_guild_channel_delete
# on_guild_channel_update
# on_user_update
# on_guild_update
# on_guild_role_create
# on_guild_role_delete
# on_guild_stickers_update
# on_invite_create
# on_invite_delete
# on_scheduled_event_create
# on_scheduled_event_update
# on_scheduled_event_delete

# Create bot notification event so I can message server owners.


class ToggleButton(discord.ui.Button):
    """A Button to toggle the notifications settings."""

    def __init__(self, db_key, value, row=0):
        self.value = value
        self.db_key = db_key

        emoji = '🟢' if value else '🔴'  # None (Off)
        label = "On" if value else "Off"

        title = db_key.replace('_', ' ').title()
        super().__init__(label=f"{title} ({label})", emoji=emoji, row=row)

    async def callback(self, interaction: discord.Interaction):
        """Set view value to button value"""
        await interaction.response.defer()
        new_value = False if self.value else True

        connection = await self.view.ctx.bot.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE notifications_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.view.ctx.channel.id)
        finally:
            await self.view.ctx.bot.db.release(connection)
        await self.view.update()


class ConfigView(discord.ui.View):
    """Generic Config View"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.message = None

    async def on_timeout(self):
        """Hide menu on timeout."""
        self.clear_items()
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
        e.title = "Mod Logs config"
        return e

    async def update(self, text=""):
        """Regenerate view and push to message"""
        self.clear_items()

        q = """SELECT * FROM notifications_settings WHERE channel_id = $1"""
        qq = """INSERT INTO notifications_settings (channel_id) VALUES $1"""
        connection = await self.ctx.bot.db.acquire()
        try:
            async with connection.transaction():
                stg = await connection.fetchrow(q, self.ctx.channel.id)
            if not stg:
                print("Settings not found! Creating...")
                await connection.execute(qq, self.ctx.channel.id)
                return await self.update()
        finally:
            await self.ctx.bot.db.release(connection)

        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Notification Logs config"

        count = 0
        row = 2
        for k, v in sorted(stg.items()):

            print("Iterating through settings...", k, v)

            if k == "channel_id":
                continue

            count += 1
            if count % 5 == 0:
                row += 1

            self.add_item(ToggleButton(db_key=k, value=v, row=row))

        self.add_item(view_utils.StopButton())

        try:
            await self.message.edit(content=text, embed=e, view=self)
        except discord.NotFound:
            self.stop()
            return


class Logs(commands.Cog):
    """Set up Server Logs"""

    def __init__(self, bot):
        self.bot = bot
        self.records = []
        self.bot.loop.create_task(self.update_cache())

    # We don't need to db call every single time an event happens, just when config is updated
    # So we cache everything and store it in memory instead for performance and sanity reasons.
    async def update_cache(self):
        """Get the latest database information and load it into memory"""
        q = """SELECT * FROM notifications_channels LEFT OUTER JOIN notifications_settings
            ON notifications_channels.channel_id = notifications_settings.channel_id"""

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            self.records = await connection.fetch(q)
        await self.bot.db.release(connection)

    # Master info command.
    @commands.slash_command()
    async def logs(self, ctx):
        """Create moderator logs in this channel."""
        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            err = "You need manage_messages permissions to view and set mod logs"
            return await self.bot.error(ctx, err)

        # Get settings.
        e = discord.Embed(color=0x7289DA)
        e.description = ""
        e.set_author(name=ctx.guild.name)
        e.title = f"Notification message settings"
        e.set_thumbnail(url=ctx.guild.icon.url)
        view = ConfigView(ctx)
        view.message = await ctx.bot.reply(ctx, embed=e, view=view)

    # Join messages
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Event handler to Dispatch new member information for servers that request it"""
        # Extended member join information.
        e = discord.Embed()
        e.colour = 0x7289DA
        e.description = f"➡ {member.mention} joined {member.guild.name}\n**User ID**: {member.id}"

        other_servers = sum(1 for m in self.bot.get_all_members() if m.id == member.id) - 1
        if other_servers:
            e.add_field(name='Shared Servers', value=f'Seen on {other_servers} other servers')
        if member.bot:
            e.description += '\n\n🤖 **This is a bot account**'

        e.add_field(name="Account Created", value=timed_events.Timestamp(member.created_at).date_relative)
        try:
            e.set_thumbnail(url=member.display_avatar.url)
        except AttributeError:
            pass

        for x in [i for i in self.records if i['guild_id'] == member.guild.id and i['member_joins']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue

    # Unban notifier.
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """Event handler for outputting information about unbanned users."""
        e = discord.Embed(title="User Unbanned")
        e.colour = discord.Colour.dark_blue()
        e.description = f"{user} (ID: {user.id}) was unbanned."

        for x in [i for i in self.records if i['guild_id'] == guild.id and i['user_unbans']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue

    # Deleted message notif
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Event handler for reposting deleted messages from users/"""
        if message.guild is None or message.author.bot:
            return  # Ignore DMs & Do not log message deletions from bots.

        e = discord.Embed()
        t = timed_events.Timestamp(datetime.datetime.now()).datetime
        e.title = "Deleted Message"
        e.colour = discord.Colour.dark_red()
        e.description = f"{message.author.mention} in {message.channel.mention}: \n\n{t}\n> {message.content}"
        e.set_footer(text=f"UserID: {message.author.id}")

        for z in message.attachments:
            if hasattr(z, "height"):
                v = f"📎 *Attachment info*: {z.filename} ({z.size} bytes, {z.height}x{z.width})," \
                    f"attachment url: {z.proxy_url}"
                e.add_field(name="Attachment info", value=v)
            else:
                print("Deletion log - unspecified attachment info [No HEIGHT found]")
                print(z.__dict__)

        for x in [i for i in self.records if i['guild_id'] == message.guild.id and i['message_deletes']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue

    # Kick notif
    # Leave notif
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Event handler for outputting information about member kick, ban, or other departures"""
        # Check if in mod action log and override to specific channels.
        e = discord.Embed(title="Member Left")
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        e.description = f"{member.mention} | {member} (ID: {member.id})"
        db_field = "member_leaves"
        try:
            async for x in member.guild.audit_logs(limit=5):
                if x.target == member:
                    if x.action == discord.AuditLogAction.kick:
                        e.title = "Member Kicked"
                        e.colour = discord.Colour.dark_red()
                        e.description = f"{member.mention} kicked by {x.user} for {x.reason}."
                        db_field = "member_kicks"
                        break
        except discord.Forbidden:
            pass  # We cannot see audit logs.

        for x in [i for i in self.records if i['guild_id'] == member.guild.id and i[db_field]]:
            try:
                ch = [x['channel_id']]
                ch = self.bot.get_channel(ch)
                assert ch is not None
                assert ch.permissions_for(member.guild.me).send_messages
                assert ch.permissions_for(member.guild.me).embed_links
                await ch.send(embed=e)
            except (AttributeError, TypeError, IndexError, AssertionError, discord.HTTPException):
                continue

    # Timeout notif
    # Timeout end notif
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Track Timeouts"""
        if after.timed_out == before.timed_out:
            return

        channels = [i for i in self.records if i['guild_id'] == after.guild.id and i['member_timeouts']]

        if not channels:
            return

        e = discord.Embed()
        if not before.timed_out:
            e.title = "User Timed Out"
            end_time = after.communication_disabled_until
            diff = end_time - datetime.datetime.now(datetime.timezone.utc)
            target_time = timed_events.Timestamp(end_time).day_time
            e.description = f"{after.mention} was timed out for {diff}\nTimeout ends: {target_time}"
        else:
            e.title = "Timeout ended"
            e.description = f"{after.mention} is no longer timed out."

        for x in channels:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue

    # emojis notif
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        """Event listener for outputting information about updated emojis on a server"""
        e = discord.Embed()
        # Find if it was addition or removal.
        new_emoji = [i for i in after if i not in before]
        if new_emoji:
            for emoji in new_emoji:
                if emoji.user is not None:
                    e.add_field(name="Uploaded by", value=emoji.user.mention)
                e.colour = discord.Colour.dark_purple() if emoji.managed else discord.Colour.green()
                if emoji.managed:
                    e.set_author(name="Twitch Integration", icon_url=TWITCH_LOGO)
                    if emoji.roles:
                        e.add_field(name='Available to roles', value="".join([i.mention for i in emoji.roles]))

                e.title = f"New {'animated ' if emoji.animated else ''}emote: {emoji.name}"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)
        else:
            try:
                removed_emoji = [i for i in before if i.id not in [i.id for i in after]][0]
            except IndexError:
                return  # Shrug?
            e.title = "Emote removed"
            e.colour = discord.Colour.light_gray()
            e.description = f"The '{removed_emoji}' emote was removed"

        for x in [i for i in self.records if i['guild_id'] == guild.id and i['emoji_updates']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue


def setup(bot):
    """Loads the notifications cog into the bot"""
    bot.add_cog(Logs(bot))
