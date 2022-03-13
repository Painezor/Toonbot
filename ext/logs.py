"""Notify server moderators about specific events"""
import datetime
from typing import List, Sequence, Optional

from discord import Embed, Colour, HTTPException, AuditLogAction, Interaction, Forbidden, app_commands, Member, User, \
    Message, Guild, Emoji, GuildSticker, TextChannel
from discord.ext import commands
from discord.ui import Button, View

from ext.utils import timed_events, view_utils

TWITCH_LOGO = "https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklogo.com.png"


# TODO: Handle events.
# Unhandled Events
# on_message_edit
# TODO: Message edited
# on_reaction_clear
# on_guild_channel_create
# on_guild_channel_delete
# on_guild_channel_update
# on_user_update
# TODO: Username changed.
# TODO: Nickname changed.
# TODO: Avatar changed.
# on_guild_update
# on_guild_role_create
# on_guild_role_delete
# on_invite_create
# on_invite_delete
# on_scheduled_event_create
# on_scheduled_event_update
# on_scheduled_event_delete

# TODO: Permissions Pass.


class ToggleButton(Button):
    """A Button to toggle the notifications settings."""

    def __init__(self, db_key, value, row=0):
        self.value = value
        self.db_key = db_key

        emoji = '🟢' if value else '🔴'  # None (Off)
        label = "On" if value else "Off"

        title = db_key.replace('_', ' ').title()
        super().__init__(label=f"{title} ({label})", emoji=emoji, row=row)

    async def callback(self, interaction: Interaction):
        """Set view value to button value"""
        await interaction.response.defer()
        new_value = False if self.value else True

        connection = await self.view.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE notifications_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.view.channel.id)
        finally:
            await self.view.interaction.client.db.release(connection)
        await self.view.interaction.client.get_cog("Logs").update_cache()
        await self.view.update()


# Config View SQL Queries
q_stg = """SELECT * FROM notifications_settings WHERE (channel_id) = $1"""
qq = """INSERT INTO notifications_channels (guild_id, channel_id) VALUES ($1, $2)"""
qqq = """INSERT INTO notifications_settings (channel_id) VALUES ($1)"""


class LogsConfig(View):
    """Generic Config View"""

    def __init__(self, interaction: Interaction, channel: TextChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel = channel

    async def on_timeout(self):
        """Hide menu on timeout."""
        self.clear_items()
        self.interaction.client.reply(self.interaction, view=self, followup=False)
        self.stop()

    async def update(self, content=""):
        """Regenerate view and push to message"""
        self.clear_items()

        connection = await self.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                stg = await connection.fetchrow(q_stg, self.channel.id)
            if not stg:
                await connection.execute(qq, self.interaction.guild.id, self.channel.id)
                await connection.execute(qqq, self.channel.id)
                return await self.update()
        finally:
            await self.interaction.client.db.release(connection)

        e = Embed(color=0x7289DA, title="Notification Logs config")
        e.description = "Click the buttons below to turn on or off logging for events."
        e.set_author(name=self.interaction.guild.name, icon_url=self.interaction.guild.icon.url)

        count = 0
        row = 0
        for k, v in sorted(stg.items()):
            if k == "channel_id":
                continue

            count += 1
            if count % 5 == 0:
                row += 1

            self.add_item(ToggleButton(db_key=k, value=v, row=row))
        self.add_item(view_utils.StopButton(row=4))
        await self.interaction.client.reply(self.interaction, content=content, embed=e, view=self)


class Logs(commands.Cog):
    """Set up Server Logs"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.update_cache())

    @app_commands.command()
    async def logs(self, interaction: Interaction, channel: Optional[TextChannel]):
        """Create moderator logs in this channel."""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        elif not interaction.permissions.manage_messages:
            err = "You need manage_messages permissions to view and set mod logs"
            return await self.bot.error(interaction, err)

        channel = interaction.channel if channel is None else channel

        await LogsConfig(interaction, channel).update()

    # We don't need to db call every single time an event happens, just when config is updated
    # So we cache everything and store it in memory instead for performance and sanity reasons.
    async def update_cache(self):
        """Get the latest database information and load it into memory"""
        q = """SELECT * FROM notifications_channels LEFT OUTER JOIN notifications_settings
            ON notifications_channels.channel_id = notifications_settings.channel_id"""

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            self.bot.notifications_cache = await connection.fetch(q)
        await self.bot.db.release(connection)

    # Master info command.

    # Join messages
    @commands.Cog.listener()
    async def on_member_join(self, member: Member):
        """Event handler to Dispatch new member information for servers that request it"""
        # Extended member join information.
        e = Embed(colour=0x7289DA)
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

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == member.guild.id and i['member_joins']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # Unban notifier.
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user: User):
        """Event handler for outputting information about unbanned users."""
        e = Embed(title="User Unbanned", colour=Colour.dark_blue(), description=f"{user} (ID: {user.id}) was unbanned.")

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['user_unbans']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[Message]):
        """Yeet every single deleted message into the deletion log. Awful idea I know."""
        for message in messages:
            await self.on_message_delete(message)

    # Deleted message notif
    @commands.Cog.listener()
    async def on_message_delete(self, message: Message):
        """Event handler for reposting deleted messages from users/"""
        if message.guild is None or message.author.bot:
            return  # Ignore DMs & Do not log message deletions from bots.

        e = Embed(colour=Colour.dark_red())
        t = timed_events.Timestamp(datetime.datetime.now()).datetime
        e.description = f"{t}\n{message.channel.mention} {message.author.mention}\n> {message.content}"
        e.set_footer(text=f"Deleted Message from UserID: {message.author.id}")

        for z in message.attachments:
            if hasattr(z, "height"):
                v = f"📎 *Attachment info*: {z.filename} ({z.size} bytes, {z.height}x{z.width})," \
                    f"attachment url: {z.proxy_url}"
                e.add_field(name="Attachment info", value=v)
            else:
                print("Deletion log - unspecified attachment info [No HEIGHT found]")
                print(z.__dict__)

        for x in [i for i in self.bot.notifications_cache
                  if i['guild_id'] == message.guild.id and i['message_deletes']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # Kick notif
    # Leave notif
    @commands.Cog.listener()
    async def on_member_remove(self, member: Member):
        """Event handler for outputting information about member kick, ban, or other departures"""
        # Check if in mod action log and override to specific channels.
        e = Embed(title="Member Left", description=f"{member.mention} | {member} (ID: {member.id})")
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        db_field = "member_leaves"
        try:
            async for x in member.guild.audit_logs(limit=5):
                if x.target == member:
                    if x.action == AuditLogAction.kick:
                        e.title = "Member Kicked"
                        e.colour = Colour.dark_red()
                        e.description = f"{member.mention} kicked by {x.user} for {x.reason}."
                        db_field = "member_kicks"
                        break
        except Forbidden:
            pass  # We cannot see audit logs.

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == member.guild.id and i[db_field]]:
            try:
                ch = [x['channel_id']]
                ch = self.bot.get_channel(ch)
                assert ch is not None
                assert ch.permissions_for(member.guild.me).send_messages
                assert ch.permissions_for(member.guild.me).embed_links
                await ch.send(embed=e)
            except (AttributeError, TypeError, IndexError, AssertionError, HTTPException):
                continue

    # Timeout notif
    # Timeout end notif
    @commands.Cog.listener()
    async def on_member_update(self, before: Member, after: Member):
        """Track Timeouts"""
        if after.is_timed_out() == before.is_timed_out():
            return

        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == after.guild.id and i['member_timeouts']]

        if not channels:
            return

        if not before.is_timed_out():
            e = Embed(title="User Timed Out")
            end_time = after.timed_out_until
            diff = end_time - datetime.datetime.now(datetime.timezone.utc)
            target_time = timed_events.Timestamp(end_time).day_time
            e.description = f"{after.mention} was timed out for {diff}\nTimeout ends: {target_time}"
        else:
            e = Embed(title="Timeout ended", description=f"{after.mention} is no longer timed out.")

        for x in channels:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # emojis notif
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: Guild, before: Sequence[Emoji], after: Sequence[Emoji]):
        """Event listener for outputting information about updated emojis on a server"""
        e = Embed()
        # Find if it was addition or removal.
        new_emoji = [i for i in after if i not in before]
        if new_emoji:
            for emoji in new_emoji:
                if emoji.user is not None:
                    e.add_field(name="Uploaded by", value=emoji.user.mention)
                e.colour = Colour.dark_purple() if emoji.managed else Colour.green()
                if emoji.managed:
                    e.set_author(name="Twitch Integration", icon_url=TWITCH_LOGO)
                    if emoji.roles:
                        e.add_field(name='Available to roles', value=''.join([i.mention for i in emoji.roles]))

                e.title = f"New {'animated ' if emoji.animated else ''}emote: {emoji.name}"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)
        else:
            try:
                removed_emoji = [i for i in before if i.id not in [i.id for i in after]][0]
            except IndexError:
                return  # Shrug?
            e.title = "Emote removed"
            e.colour = Colour.light_gray()
            e.description = f"The '{removed_emoji}' emote was removed"

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['emote_changes']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # stickers notif
    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: Guild, old: Sequence[GuildSticker], new: Sequence[GuildSticker]):
        """Event listener for outputting information about updated stickers on a server"""
        e = Embed()
        # Find if it was addition or removal.
        new_stickers = [i for i in new if i not in old]
        if new_stickers:
            for sticker in new_stickers:
                if sticker.user is not None:
                    e.add_field(name="Uploaded by", value=sticker.user.mention)

                e.title = f"New sticker: {sticker.name}"
                e.set_image(url=sticker.url)
                e.set_footer(text=sticker.url)
                e.description = sticker.description

        else:
            try:
                removed_sticker = [i for i in old if i.id not in [i.id for i in new]][0]
            except IndexError:
                return  # Shrug?
            e.title = "Emote removed"
            e.colour = Colour.light_gray()
            e.description = f"The '{removed_sticker}' emote was removed"

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['sticker_changes']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    @commands.Cog.listener()
    async def on_bot_notification(self, notification):
        """Custom event dispatched by painezor, output to tracked guilds."""
        e = Embed(description=notification)

        for x in [i for i in self.bot.notifications_cache if i['bot_notifications']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                e.colour = ch.guild.me.colour()
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue


def setup(bot):
    """Loads the notifications cog into the bot"""
    bot.add_cog(Logs(bot))
