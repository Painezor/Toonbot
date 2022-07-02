"""Notify server moderators about specific events"""
import datetime
from copy import deepcopy
from typing import List, Sequence, TYPE_CHECKING, Union, Callable

from discord import Embed, Colour, HTTPException, AuditLogAction, Interaction, Member, User, Message
from discord import Guild, Emoji, GuildSticker, TextChannel
from discord.app_commands import command, default_permissions
from discord.ext.commands import Cog
from discord.ui import Button, View

from ext.utils import timed_events, view_utils

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

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


class ToggleButton(Button):
    """A Button to toggle the notifications settings."""

    def __init__(self, bot: Union['Bot', 'PBot'], db_key: str, value: bool, row: int = 0) -> None:
        self.value: bool = value
        self.db_key: str = db_key
        self.bot: Bot | PBot = bot

        emoji: str = '🟢' if value else '🔴'  # None (Off)
        label: str = "On" if value else "Off"
        title: str = db_key.replace('_', ' ').title()
        super().__init__(label=f"{title} ({label})", emoji=emoji, row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Set view value to button value"""
        await interaction.response.defer()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE notifications_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, not self.value, self.view.channel.id)
        finally:
            await self.bot.db.release(connection)
        cog: Cog = self.bot.get_cog("Logs")
        upd: Callable = getattr(cog, "update_cache")
        await upd()
        return await self.view.update()


# Config View SQL Queries
q_stg = """SELECT * FROM notifications_settings WHERE (channel_id) = $1"""
qq = """INSERT INTO notifications_channels (guild_id, channel_id) VALUES ($1, $2)"""
qqq = """INSERT INTO notifications_settings (channel_id) VALUES ($1)"""


class LogsConfig(View):
    """Generic Config View"""

    def __init__(self, bot: 'Bot', interaction: Interaction, channel: TextChannel) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel
        self.bot: Bot = bot

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = "") -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                stg = await connection.fetchrow(q_stg, self.channel.id)
            if not stg:
                await connection.execute(qq, self.interaction.guild.id, self.channel.id)
                await connection.execute(qqq, self.channel.id)
                return await self.update()
        finally:
            await self.bot.db.release(connection)

        e: Embed = Embed(color=0x7289DA, title="Notification Logs config")
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

            self.add_item(ToggleButton(self.bot, db_key=k, value=v, row=row))
        self.add_item(view_utils.Stop(row=4))
        await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class Logs(Cog):
    """Set up Server Logs"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    async def cog_load(self) -> None:
        """When the cog loads"""
        await self.update_cache()

    @command()
    @default_permissions(manage_messages=True)
    async def logs(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """Create moderator logs in this channel."""
        if channel is None:
            channel = interaction.channel

        return await LogsConfig(self.bot, interaction, channel).update()

    # We don't need to db call every single time an event happens, just when config is updated
    # So we cache everything and store it in memory instead for performance and sanity reasons.
    async def update_cache(self) -> None:
        """Get the latest database information and load it into memory"""
        q = """SELECT * FROM notifications_channels LEFT OUTER JOIN notifications_settings
            ON notifications_channels.channel_id = notifications_settings.channel_id"""

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            self.bot.notifications_cache = await connection.fetch(q)
        await self.bot.db.release(connection)

    # Master info command.

    # Join messages
    @Cog.listener()
    async def on_member_join(self, member: Member) -> List[Message]:
        """Event handler to Dispatch new member information for servers that request it"""
        # Extended member join information.
        e: Embed = Embed(colour=0x7289DA)
        e.description = f"➡ {member.mention} joined {member.guild.name}\n**User ID**: {member.id}"

        other_servers: int = sum(1 for m in self.bot.get_all_members() if m.id == member.id) - 1
        if other_servers:
            e.add_field(name='Shared Servers', value=f'Seen on {other_servers} other servers')
        if member.bot:
            e.description += '\n\n🤖 **This is a bot account**'

        e.add_field(name="Account Created", value=timed_events.Timestamp(member.created_at).date_relative)
        try:
            e.set_thumbnail(url=member.display_avatar.url)
        except AttributeError:
            pass

        messages: List[Message] = []
        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == member.guild.id and i['member_joins']]:
            try:
                ch: TextChannel = self.bot.get_channel(x['channel_id'])
                messages.append(await ch.send(embed=e))
            except (AttributeError, HTTPException):
                continue
        return messages

    # Unban notifier.
    @Cog.listener()
    async def on_member_unban(self, guild, user: User) -> None:
        """Event handler for outputting information about unbanned users."""
        e: Embed = Embed(title="User Unbanned", colour=Colour.dark_blue())
        e.description = f"{user} (ID: {user.id}) was unbanned."

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['user_unbans']]:
            try:
                ch: TextChannel = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    @Cog.listener()
    async def on_member_ban(self, guild: Guild, user: User | Member) -> List[Message]:
        """Event handler for outputting information about unbanned users."""
        channels = [self.bot.get_channel(i['channel_id']) for i in self.bot.notifications_cache
                    if i['guild_id'] == guild.id and i['user_unbans']]
        channels = [i for i in channels if i is not None]

        if not channels:
            return []

        e: Embed = Embed(title="User Banned", colour=Colour.dark_red())

        try:
            e.description = f"{user.mention} (ID: {user.id}) was banned."
        except AttributeError:  # Users do not have .mention
            e.description = f"{user} (ID: {user.id}) was banned."

        try:
            async for x in guild.audit_logs(limit=5):
                if x.target.id == user.id:
                    e.add_field(name="Reason", value=f"{x.user.mention}: {x.reason}")
                    break
        except HTTPException:
            pass  # We cannot see audit logs.

        messages: List[Message] = []
        for ch in channels:
            try:
                messages.append(await ch.send(embed=e))
            except (AttributeError, HTTPException):
                continue
        return messages

    @Cog.listener()
    async def on_bulk_message_delete(self, messages: List[Message]) -> List[Message]:
        """Yeet every single deleted message into the deletion log. Awful idea I know."""
        for message in messages:
            await self.on_message_delete(message)
        return messages

    # Deleted message notif
    @Cog.listener()
    async def on_message_delete(self, message: Message) -> List[Message]:
        """Event handler for reposting deleted messages from users/"""
        if message.guild is None or message.author.bot:
            return []  # Ignore DMs & Do not log message deletions from bots.

        e: Embed = Embed(colour=Colour.dark_red())
        t = timed_events.Timestamp(datetime.datetime.now(datetime.timezone.utc)).datetime
        e.description = f"{t}\n{message.channel.mention} {message.author.mention}\n> {message.content}"
        e.set_footer(text=f"Deleted Message from UserID: {message.author.id}")

        for z in message.attachments:
            if hasattr(z, "height"):
                v = f"📎 *Attachment info*: {z.filename} ({z.size} bytes, {z.height}x{z.width})," \
                    f"attachment url: {z.proxy_url}"
                e.add_field(name="Attachment info", value=v)

        for x in [i for i in self.bot.notifications_cache
                  if i['guild_id'] == message.guild.id and i['message_deletes']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # Kick notif
    # Leave notif
    @Cog.listener()
    async def on_member_remove(self, member: Member) -> None:
        """Event handler for outputting information about member kick, ban, or other departures"""
        # Check if in mod action log and override to specific channels.
        e: Embed = Embed(title="Member Left", description=f"{member.mention} | {member} (ID: {member.id})")
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        db_field: str = "member_leaves"
        try:
            async for x in member.guild.audit_logs(limit=5):
                if x.target == member:
                    if x.action == AuditLogAction.kick:
                        e.title = "Member Kicked"
                        e.colour = Colour.dark_red()
                        e.description = f"{member.mention} kicked by {x.user} for {x.reason}."
                        db_field = "member_kicks"
                        break
        except HTTPException:
            pass  # We cannot see audit logs.

        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == member.guild.id and i[db_field]]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # Timeout notif
    # Timeout end notif
    @Cog.listener()
    async def on_member_update(self, before: Member, after: Member) -> None:
        """Track Timeouts"""
        if after.is_timed_out() == before.is_timed_out():
            return []

        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == after.guild.id and i['member_timeouts']]

        if not channels:
            return []

        if not before.is_timed_out():
            e: Embed = Embed(title="User Timed Out")
            end_time = after.timed_out_until
            diff = end_time - datetime.datetime.now(datetime.timezone.utc)
            target_time = timed_events.Timestamp(end_time).day_time
            e.description = f"{after.mention} was timed out for {diff}\nTimeout ends: {target_time}"
        else:
            e: Embed = Embed(title="Timeout ended", description=f"{after.mention} is no longer timed out.")

        for x in channels:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue

    # emojis notif
    @Cog.listener()
    async def on_guild_emojis_update(self, guild: Guild, before: Sequence[Emoji], after: Sequence[Emoji]) -> None:
        """Event listener for outputting information about updated emojis on a server"""
        e: Embed = Embed()
        # Find if it was addition or removal.
        new_emoji = [i for i in after if i not in before]

        embeds: List[Embed] = []

        if new_emoji:
            for emoji in new_emoji:
                if emoji.user is not None:
                    e.add_field(name="Uploaded by", value=emoji.user.mention)
                e.colour = Colour.dark_purple() if emoji.managed else Colour.green()
                if emoji.managed:
                    e.set_author(name="Twitch Integration", icon_url=TWITCH_LOGO)
                    if emoji.roles:
                        e.add_field(name='Available to roles', value=' '.join([i.mention for i in emoji.roles]))

                e.title = f"New {'animated ' if emoji.animated else ''}emote: {emoji.name}"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)
                embeds.append(deepcopy(e))
                e.clear_fields()
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
                await ch.send(embeds=embeds)
            except (AttributeError, HTTPException):
                continue

    # stickers notif
    @Cog.listener()
    async def on_guild_stickers_update(self, guild: Guild, old: Sequence[GuildSticker], new: Sequence[GuildSticker]):
        """Event listener for outputting information about updated stickers on a server"""
        e: Embed = Embed()
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

    @Cog.listener()
    async def on_bot_notification(self, notification):
        """Custom event dispatched by painezor, output to tracked guilds."""
        e: Embed = Embed(description=notification)

        for x in [i for i in self.bot.notifications_cache if i['bot_notifications']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                e.colour = ch.guild.me.colour
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue


async def setup(bot: Union['Bot', 'PBot']):
    """Loads the notifications cog into the bot"""
    await bot.add_cog(Logs(bot))
