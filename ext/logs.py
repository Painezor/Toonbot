"""Notify server moderators about specific events"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING, Callable, ClassVar

import discord
from discord import Embed, Colour, HTTPException, AuditLogAction, ButtonStyle, RawMemberRemoveEvent, TextChannel
from discord.app_commands import command, default_permissions
from discord.ext.commands import Cog
from discord.ui import Button, View

from ext.utils import timed_events, view_utils
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot
    from discord import File, Guild, Message, Emoji, GuildSticker, Interaction, Member, User

TWITCH_LOGO = "https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklogo.com.png"


# TODO: Handle events.
# Unhandled Events
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
# on_automod_action,
# on_automod_rule_create,
# on_automod_rule_update,
# on_automod_rule_delete
# AutoModAction, AutoModRule, AutoModRuleAction, AutoModTrigger

class ToggleButton(Button):
    """A Button to toggle the notifications settings."""

    def __init__(self, bot: Bot | PBot, db_key: str, value: bool, row: int = 0) -> None:
        self.value: bool = value
        self.db_key: str = db_key
        self.bot: Bot | PBot = bot

        style = ButtonStyle.green if value else ButtonStyle.red
        emoji: str = '🟢' if value else '🔴'  # None (Off)
        title: str = db_key.replace('_', ' ').title()
        super().__init__(label=f"{title}", emoji=emoji, row=row, style=style)

    async def callback(self, interaction: Interaction) -> Message:
        """Set view value to button value"""
        await interaction.response.defer()

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                q = f"""UPDATE notifications_settings SET {self.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, not self.value, self.view.channel.id)

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
    bot: ClassVar[Bot] = None

    def __init__(self, bot: Bot, interaction: Interaction, channel: TextChannel) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel

        if self.__class__.bot is None:
            self.__class__.bot = bot

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = None) -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                stg = await connection.fetchrow(q_stg, self.channel.id)
            if not stg:
                await connection.execute(qq, self.interaction.guild.id, self.channel.id)
                await connection.execute(qqq, self.channel.id)
                return await self.update()

        e: Embed = Embed(color=0x7289DA, title="Notification Logs config")
        e.description = "Click the buttons below to turn on or off logging for events."
        e.set_author(name=self.interaction.guild.name, icon_url=self.interaction.guild.icon.url)

        row = 0
        for num, (k, v) in enumerate(sorted(stg.items())):
            if k == "channel_id":
                continue

            if num % 5 == 0:
                row += 1

            self.add_item(ToggleButton(self.bot, db_key=k, value=v, row=row))
        self.add_item(view_utils.Stop(row=4))
        await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class Logs(Cog):
    """Set up Server Logs"""

    def __init__(self, bot: Bot) -> None:
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

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                self.bot.notifications_cache = await connection.fetch(q)

    # Master info command.

    # Join messages
    @Cog.listener()
    async def on_member_join(self, member: Member) -> list[Message]:
        """Event handler to Dispatch new member information for servers that request it"""
        # Extended member join information.
        e: Embed = Embed(colour=0x7289DA)
        desc = [f"➡ {member.mention} joined {member.guild.name}\n**User ID**: {member.id}"]

        other_servers: int = sum(1 for m in self.bot.get_all_members() if m.id == member.id) - 1
        if other_servers:
            e.add_field(name='Shared Servers', value=f'Seen on {other_servers} other servers')
        if member.bot:
            desc.append('🤖 **This is a bot account**')

        e.description = "\n\n".join(desc)

        e.add_field(name="Account Created", value=timed_events.Timestamp(member.created_at).date_relative)
        try:
            e.set_thumbnail(url=member.display_avatar.url)
        except AttributeError:
            pass

        messages: list[Message] = []
        for x in [i for i in self.bot.notifications_cache if i['guild_id'] == member.guild.id and i['user_joins']]:
            try:
                ch: TextChannel = self.bot.get_channel(x['channel_id'])
                messages.append(await ch.send(embed=e))
            except (AttributeError, HTTPException):
                continue
        return messages

    # Unban notifier.
    @Cog.listener()
    async def on_member_unban(self, guild: Guild, user: User) -> None:
        """Event handler for outputting information about unbanned users."""
        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['user_unbans']]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]

        if not channels:
            return

        e: Embed = Embed(title="User Unbanned",
                         colour=Colour.dark_blue(),
                         description=f"{user.mention} (ID: {user.id}) was unbanned.",
                         timestamp=discord.utils.utcnow())

        if guild.me.guild_permissions.view_audit_log:
            try:
                ts = discord.utils.utcnow() - timedelta(seconds=30)
                action = next(i async for i in guild.audit_logs(action=AuditLogAction.unban, after=ts)
                              if i.target.id == user.id)
                e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                e.add_field(name="Reason", value=action.reason)
            except StopIteration:
                pass

        for ch in channels:
            try:
                await ch.send(embed=e)
            except HTTPException:
                continue

    @Cog.listener()
    async def on_member_ban(self, guild: Guild, user: User | Member) -> None:
        """Event handler for outputting information about unbanned users."""
        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['user_unbans']]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]

        if not channels:
            return

        e: Embed = Embed(title="User Banned",
                         colour=Colour.dark_red(),
                         description=f"{user.mention} (ID: {user.id}) was banned.",
                         timestamp=discord.utils.utcnow())

        if guild.me.guild_permissions.view_audit_log:
            try:
                action = next(i async for i in guild.audit_logs(action=AuditLogAction.ban) if i.target.id == user.id)
                e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                e.add_field(name="Reason", value=action.reason)
            except StopIteration:
                pass

        for ch in channels:
            try:
                await ch.send(embed=e)
            except HTTPException:
                continue

    @Cog.listener()
    async def on_bulk_message_delete(self, messages: list[Message]) -> list[Message]:
        """Yeet every single deleted message into the deletion log. Awful idea I know."""
        guild = messages[0].guild
        if guild is None:
            return  # Ignore DMs & Do not log message deletions from bots.

        ch = [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['message_deletes']]
        ch = [self.bot.get_channel(i) for i in ch]
        ch = [i for i in ch if i is not None]
        if not ch:
            return

        e: Embed = Embed(colour=Colour.dark_red(),
                         title="Message Bulk Delete")

        if guild.me.guild_permissions.view_audit_log:
            try:
                ts = discord.utils.utcnow() - timedelta(seconds=30)
                action = next(i async for i in guild.audit_logs(action=AuditLogAction.message_bulk_delete, after=ts)
                              if i.target.id == messages[0].channel.id)
                e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                e.add_field(name="Reason", value=action.reason)
            except StopIteration:
                pass

        e.description = f"**{len(messages)}** messages were deleted from {messages[0].channel.name}"
        return messages

    # Deleted message notif
    @Cog.listener()
    async def on_message_delete(self, message: Message) -> list[Message]:
        """Event handler for reposting deleted messages from users/"""
        if message.guild is None or message.author.bot:
            return []  # Ignore DMs & Do not log message deletions from bots.

        ch = [i for i in self.bot.notifications_cache if i['guild_id'] == message.guild.id and i['message_deletes']]
        ch = [self.bot.get_channel(i) for i in ch]
        ch = [i for i in ch if i is not None]
        if not ch:
            return

        e: Embed = Embed(colour=Colour.dark_red())
        t = timed_events.Timestamp(discord.utils.utcnow()).datetime
        e.description = f"{t}\n{message.channel.mention} {message.author.mention}\n> {message.content}"
        e.set_footer(text=f"UserID: {message.author.id}")

        attachments: list[File] = []

        for num, z in enumerate(message.attachments, 1):
            v = f"📎 *Attachment info*: [{z.filename}]({z.proxy_url}) ({z.content_type} - {z.size} bytes)" \
                f"\n*This is cached and will only be available for a limited time*"

            e.add_field(name=f"Attachment #{num}", value=v)
            attachments.append(await z.to_file(spoiler=True, use_cached=True))

        if message.guild.me.guild_permissions.view_audit_log:
            try:
                ts = discord.utils.utcnow() - timedelta(seconds=30)
                action = next(i async for i in message.guild.audit_logs(action=AuditLogAction.message_delete, after=ts)
                              if i.target.id == message.author.id)
                e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                e.add_field(name="Reason", value=action.reason)
            except StopIteration:
                pass

        for channel in ch:
            try:
                await channel.send(embed=e, files=attachments)
            except (AttributeError, HTTPException):
                continue

    # Kick notif
    # Leave notif
    @Cog.listener()
    async def on_raw_member_remove(self, payload: RawMemberRemoveEvent) -> None:
        """Event handler for outputting information about member kick, ban, or other departures"""
        # Check if in mod action log and override to specific channels.
        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == payload.guild_id]

        # First, we check if the user was kicked.
        kicks = [i for i in channels if i['user_kicks']]
        kicks = [self.bot.get_channel(i) for i in kicks if self.bot.get_channel(i) is not None]

        guild_id = payload.guild_id
        member: User | Member = payload.user

        leaves = [i for i in channels if i['user_leaves'] or i['user_kicks']]
        leaves = [self.bot.get_channel(i) for i in leaves if self.bot.get_channel(i) is not None]

        ts = discord.utils.utcnow()
        timestamp = Timestamp(ts).relative

        e: Embed = Embed(title="Member Left",
                         description=f"{member.mention}\n{timestamp}",
                         colour=Colour.dark_red(),
                         timestamp=ts)
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"User ID: {member.id}")

        for channel in leaves:
            try:
                await channel.send(embed=e)
            except HTTPException:
                pass

        if not kicks:
            return

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            guild = await self.bot.fetch_guild(guild_id)

        if guild.me.guild_permissions.view_audit_log:
            ts = discord.utils.utcnow() - timedelta(seconds=30)
            try:
                action = next(i async for i in guild.audit_logs(action=AuditLogAction.kick, after=ts)
                              if i.target.id == member.id)
            except StopIteration:
                return

            e.title = "Member Kicked"
            e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
            e.add_field(name="Reason", value=action.reason)

            for ch in kicks:
                try:
                    await ch.send(embed=e)
                except HTTPException:
                    continue

    # Timeout notif
    # Timeout end notif
    @Cog.listener()
    async def on_member_update(self, before: Member, after: Member) -> None:
        """Track Timeouts"""
        if after.is_timed_out() == before.is_timed_out():
            return []

        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == after.guild.id and i['user_timeouts']]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]

        if not channels:
            return []

        if not before.is_timed_out():
            e: Embed = Embed(title="User Timed Out", timestamp=discord.utils.utcnow())

            end_time = after.timed_out_until
            diff = end_time - discord.utils.utcnow()
            target_time = timed_events.Timestamp(end_time).day_time
            e.description = f"{after.mention} was timed out for {diff}\nTimeout ends: {target_time}"

            if before.guild.me.guild_permissions.view_audit_log:
                try:
                    action = next(i async for i in before.guild.audit_logs(action=AuditLogAction.member_update)
                                  if i.target.id == before.id)

                    if action.after.timed_out_until:
                        e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                        e.add_field(name="Reason", value=action.reason)
                except StopIteration:
                    pass
        else:
            e: Embed = Embed(title="Timeout ended", description=f"{after.mention} is no longer timed out.")

        for x in channels:
            try:
                await x.send(embed=e)
            except HTTPException:
                continue

    # emojis notif
    @Cog.listener()
    async def on_guild_emojis_update(self, guild: Guild, before: list[Emoji], after: list[Emoji]) -> None:
        """Event listener for outputting information about updated emojis on a server"""
        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['emote_changes']]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]

        if not channels:
            return

        e: Embed = Embed()
        # Find if it was addition or removal.
        added = [i for i in after if i not in before]
        removed = [i for i in before if i not in after]

        embeds: list[Embed] = []

        if added:
            for emoji in added:
                e.colour = Colour.dark_purple() if emoji.managed else Colour.green()
                if emoji.managed:
                    e.set_author(name="Twitch Integration", icon_url=TWITCH_LOGO)
                    if emoji.roles:
                        e.add_field(name='Available to roles', value=' '.join([i.mention for i in emoji.roles]))
                else:
                    if emoji.user is not None:
                        e.set_author(name=emoji.user, icon_url=emoji.user.display_avatar.url)

                e.title = f"New {'animated ' if emoji.animated else ''}emote: {emoji.name}"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)

                embeds.append(deepcopy(e))
                e.clear_fields()
        else:
            if guild.me.guild_permissions.view_audit_log:
                try:
                    action = next(i async for i in guild.audit_logs(action=AuditLogAction.emoji_delete))
                    e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                except StopIteration:
                    pass

            e.title = "Emote removed"
            e.colour = Colour.light_gray()
            for emoji in removed:
                e.description = f"The '{emoji}' emote was removed"
                embeds.append(deepcopy(e))

        for ch in channels:
            try:
                await ch.send(embeds=embeds)
            except HTTPException:
                continue

    # stickers notif
    @Cog.listener()
    async def on_guild_stickers_update(self, guild: Guild, old: list[GuildSticker], new: list[GuildSticker]) -> None:
        """Event listener for outputting information about updated stickers on a server"""
        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == guild.id and i['sticker_changes']]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]

        if not channels:
            return

        e: Embed = Embed()
        # Find if it was addition or removal.
        added = [i for i in new if i not in old]
        removed = [i for i in old if i not in new]

        embeds: list[Embed] = []

        if added:
            for sticker in added:
                if sticker.user is not None:
                    e.add_field(name="Uploaded by", value=sticker.user.mention)

                e.title = f"New sticker: {sticker.name}"
                e.set_image(url=sticker.url)
                e.set_footer(text=sticker.url)
                e.description = sticker.description

        else:
            if guild.me.guild_permissions.view_audit_log:
                try:
                    ts = discord.utils.utcnow() - timedelta(seconds=30)
                    action = next(i async for i in guild.audit_logs(action=AuditLogAction.emoji_delete, after=ts))
                    e.set_author(name=f"{action.user} ({action.user.id})", icon_url=action.user.display_avatar.url)
                except StopIteration:
                    pass

            e.title = "Sticker removed"
            e.colour = Colour.light_gray()
            for sticker in removed:
                e.description = f"The '{sticker}' sticker was removed"
                embeds.append(deepcopy(e))

        for ch in channels:
            try:
                await ch.send(embeds=embeds)
            except HTTPException:
                continue

    @Cog.listener()
    async def on_message_edit(self, before: Message, after: Message) -> None:
        """Edited message output."""
        if before.guild is None:
            return

        channels = [i for i in self.bot.notifications_cache if i['guild_id'] == before.guild.id and i['message_edits']]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]

        if not channels:
            return

        if before.content == after.content:
            return

        e: Embed = Embed(title="Message Edited", colour=Colour.brand_red(), timestamp=before.created_at,
                         description=f"{before.channel.mention} {before.mention} {before.content}")
        e2: Embed = Embed(title="New Content", colour=Colour.brand_green(), timestamp=after.edited_at,
                          description=f"{after.channel.mention} {after.mention} {after.content}")
        e.set_author(name=str(before.author), icon_url=before.author.display_icon.url)
        e2.set_author(name=str(after.author), icon_url=after.author.display_icon.url)

        v = View()
        v.add_item(Button(label="Jump to message", url=before.jump_url, style=ButtonStyle.url))

        for ch in channels:
            try:
                await ch.send(embeds=[e, e2], view=v)
            except HTTPException:
                continue

    @Cog.listener()
    async def on_bot_notification(self, notification: str) -> None:
        """Custom event dispatched by painezor, output to tracked guilds."""
        e: Embed = Embed(description=notification)

        for x in [i for i in self.bot.notifications_cache if i['bot_notifications']]:
            try:
                ch = self.bot.get_channel(x['channel_id'])
                e.colour = ch.guild.me.colour
                await ch.send(embed=e)
            except (AttributeError, HTTPException):
                continue


async def setup(bot: Bot | PBot) -> None:
    """Loads the notifications cog into the bot"""
    await bot.add_cog(Logs(bot))
