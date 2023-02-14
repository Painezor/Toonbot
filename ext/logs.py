"""Notify server moderators about specific events"""
# TODO: Split /logs command into subcommands with sub-views & Parent.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, ClassVar

import discord
from discord import Embed, Colour, AuditLogAction, File, Message, Emoji, Interaction, Member, User, Role
from discord.app_commands import command, default_permissions
from discord.ext.commands import Cog
from discord.ui import Button, View

from ext.utils import timed_events, view_utils
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

TWITCH_LOGO = "https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklogo.com.png"


class ToggleButton(Button):
    """A Button to toggle the notifications settings."""

    def __init__(self, bot: Bot | PBot, db_key: str, value: bool, row: int = 0) -> None:
        self.value: bool = value
        self.db_key: str = db_key
        self.bot: Bot | PBot = bot

        style = discord.ButtonStyle.green if value else discord.ButtonStyle.red
        emoji: str = '🟢' if value else '🔴'  # None (Off)
        title: str = db_key.replace('_', ' ').title()
        super().__init__(label=f"{title}", emoji=emoji, row=row, style=style)

    async def callback(self, interaction: Interaction) -> Message:
        """Set view value to button value"""
        await interaction.response.defer()

        async with self.bot.db.acquire(timeout=60) as connection:
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
    bot: ClassVar[Bot]

    def __init__(self, interaction: Interaction, channel: discord.TextChannel) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: discord.TextChannel = channel

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.interaction.delete_original_response()

    async def update(self, content: str = None) -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                if not (stg := await connection.fetchrow(q_stg, self.channel.id)):
                    await connection.execute(qq, self.interaction.guild.id, self.channel.id)
                    await connection.execute(qqq, self.channel.id)
                    return await self.update()

        e: Embed = Embed(color=0x7289DA, title="Notification Logs config")
        e.description = "Click the buttons below to turn on or off logging for events."

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
        LogsConfig.bot = bot

    async def cog_load(self) -> None:
        """When the cog loads"""
        await self.update_cache()

    # We don't need to db call every single time an event happens, just when config is updated
    # So we cache everything and store it in memory instead for performance and sanity reasons.
    async def update_cache(self) -> None:
        """Get the latest database information and load it into memory"""
        q = """SELECT * FROM notifications_channels LEFT OUTER JOIN notifications_settings
            ON notifications_channels.channel_id = notifications_settings.channel_id"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                self.bot.notifications_cache = await connection.fetch(q)

    # Master info command.
    @command()
    @default_permissions(view_audit_log=True)
    async def logs(self, interaction: Interaction, channel: discord.TextChannel = None) -> Message:
        """Create moderator logs in this channel."""
        if channel is None:
            channel = interaction.channel
        return await LogsConfig(interaction, channel).update()

    # Join messages
    @Cog.listener()
    async def on_member_join(self, member: Member) -> None:
        """Event handler to Dispatch new member information for servers that request it"""

        channels = filter(lambda i: i['guild_id'] == member.guild.id and i['joins'], self.bot.notifications_cache)
        channels = filter(None, [self.bot.get_channel(i['channel_id']) for i in channels])

        # Extended member join information.
        e: Embed = Embed(colour=0x7289DA)
        e.set_author(name=f"{member.name} joined {member.guild.name}", icon_url=member.display_avatar.url)

        def onboard() -> str:
            """Get the member's onboarding status"""
            if member.flags.completed_onboarding:
                return "Completed"
            elif member.flags.started_onboarding:
                return "Started"
            else:
                return "Not Started"

        e.description = f"{member.mention}\n" \
                        f"**User ID**: {member.id}\n" \
                        f"**Shared Servers**: {len(member.mutual_guilds)}\n" \
                        f"**Account Created**: {timed_events.Timestamp(member.created_at).date_relative}\n" \
                        f"**Onboarding Status**?: {onboard()}"

        flags = []
        pf = member.public_flags
        if pf.verified_bot:
            flags.append("🤖 Verified Bot")
        elif member.bot:
            flags.append("🤖 Bot")
        if member.flags.did_rejoin:
            flags.append("Rejoined Server")
        if member.flags.bypasses_verification:
            flags.append("Bypassed Verification")
        if pf.active_developer:
            flags.append("Active Developer")
        if pf.staff:
            flags.append("Discord Staff")
        if pf.partner:
            flags.append("Discord Partner")
        if pf.hypesquad_balance:
            flags.append("Hypesquad Balance")
        if pf.hypesquad_bravery:
            flags.append("Hypesquad Bravery")
        if pf.hypesquad_brilliance:
            flags.append("Hypesquad Brilliance")
        if pf.bug_hunter_level_2:
            flags.append("Bug Hunter Level 2")
        elif pf.bug_hunter:
            flags.append("Bug Hunter")
        if pf.early_supporter:
            flags.append("Early Supporter")
        if pf.system:
            flags.append("Official Discord Representative")
        if pf.verified_bot_developer:
            flags.append("Verified Bot Developer")
        if pf.discord_certified_moderator:
            flags.append("Discord Certified Moderator")
        if pf.spammer:
            flags.append("**Known Spammer**")

        if flags:
            e.add_field(name="Flags", value=', '.join(flags))

        for ch in channels:
            try:
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue

    @Cog.listener()
    async def on_user_update(self, bf: User, af: User):
        """Triggered when a user updates their profile"""
        guilds = [i.id for i in self.bot.guilds if i.get_member(af.id)]
        channels = filter(lambda i: i['guild_id'] in guilds and i['member_updates'], self.bot.notifications_cache)

        if not channels:
            return

        before: Embed = Embed(colour=Colour.dark_gray(), description="")
        after: Embed = Embed(colour=Colour.light_gray(), title="After", timestamp=discord.utils.utcnow(),
                             description="")

        if bf.name != af.name:
            before.description += f"**Name**: {bf.name}\n"
            after.description += f"**Name**: {af.name}\n"

        if bf.discriminator != af.discriminator:
            before.description += f"**Discriminator**: {bf.discriminator}\n"
            after.description += f"**Discriminator**: {af.discriminator}\n"

        if bf.display_avatar.url != af.display_avatar.url:
            before.description += f"**Discriminator**: {bf.display_avatar.url}\n"
            after.description += f"**Discriminator**: {af.display_avatar.url}\n"

    @Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """Generic Handler"""
        channels = filter(lambda i: i['guild_id'] == entry.guild.id, self.bot.notifications_cache)
        if not (channels := filter(lambda i: self.bot.get_channel(i['channel_id']), channels)):
            return

        before: Embed = Embed(colour=Colour.dark_gray(), description="")
        after: Embed = Embed(colour=Colour.light_gray(), title="After", timestamp=entry.created_at, description="")

        if isinstance((user := entry.user), discord.Object):
            user = entry.guild.get_member(entry.user)

        ftr = f"Action Performed by:\n{user}\n{user.id}\n"
        if entry.reason:
            ftr += f"\nReason: {entry.reason}"

        before.set_footer(text=ftr, icon_url=user.display_avatar.url)
        after.set_footer(text=ftr, icon_url=user.display_avatar.url)

        # AUTHOR is the TARGET of the event
        # TITLE is the TYPE of event
        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}

        for k, v in entry.changes.after:
            changes[k]["after"] = v

        match entry.action:
            case AuditLogAction.guild_update:
                if not (channels := filter(lambda i: i['server'], channels)):
                    return

                before.set_footer()  # Clear Footer Fields.

                # Author Icon
                if icon := changes.pop('icon', False):
                    bf_ico, af_ico = icon['before'].url, icon['after'].url
                    before.description += f"**Icon**: [link]({bf_ico})\n"
                    after.description += f"**Icon**: [link]({af_ico})\n"
                else:
                    bf_ico = af_ico = entry.guild.icon.url

                if key := changes.pop("name", False):
                    before.set_author(name=key['before'], icon_url=bf_ico)
                    after.set_author(name=key['after'], icon_url=af_ico)
                    before.description += f"**Name**: {key['before']}\n"
                    after.description += f"**Name**: {key['after']}\n"
                else:
                    before.set_author(name=f"{entry.guild.name} Updated", icon_url=bf_ico)

                if key := changes.pop("owner", False):
                    before.description += f"**Owner**: {key['before'].mention if key['before'] else None}\n"
                    after.description += f"**Owner**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop("public_updates_channel", False):
                    before.description += f"**Announcement Channel**: " \
                                          f"{key['before'].mention if key['before'] else None}\n"
                    after.description += f"**Announcement Channel**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop("afk_channel", False):
                    before.description += f"**AFK Channel**: {key['before'].mention if key['before'] else None}\n"
                    after.description += f"**AFK Channel**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop("rules_channel", False):
                    before.description += f"**Rules Channel**: {key['before'].mention if key['before'] else None}\n"
                    after.description += f"**Rules Channel**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop("system_channel", False):
                    before.description += f"**System Channel**: {key['before'].mention if key['before'] else None}\n"
                    after.description += f"**System Channel**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop("widget_channel", False):
                    before.description += f"**Widget Channel**: {key['before'].mention if key['before'] else None}\n"
                    after.description += f"**Widget Channel**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop("afk_timeout", False):
                    before.description += f"AFK Timeout: {key['before'] + ' seconds' if key['before'] else None}\n"
                    after.description += f"AFK Timeout: {key['after'] + ' seconds' if key['after'] else None}\n"

                if key := changes.pop("default_notifications", False):
                    def stringify(value: discord.NotificationLevel) -> str:
                        """Convert Enum to human string"""
                        match value:
                            case discord.NotificationLevel.all_messages:
                                return "All Messages"
                            case discord.NotificationLevel.only_mentions:
                                return "Mentions Only"
                            case _:
                                return value

                    before.description += f"Default Notifications: {stringify(key['before'])}\n"
                    after.description += f"Default Notifications: {stringify(key['after'])}\n"

                if key := changes.pop("explicit_content_filter", False):
                    def stringify(value: discord.ContentFilter) -> str:
                        """Convert Enum to human string"""
                        match value:
                            case discord.ContentFilter.all_members:
                                return "Check All Members"
                            case discord.ContentFilter.no_role:
                                return "Check Un-roled Members"
                            case discord.ContentFilter.disabled:
                                return None

                    before.description += f"**Explicit Content Filter**: {stringify(key['before'])}\n"
                    after.description += f"**Explicit Content Filter**: {stringify(key['after'])}\n"

                if key := changes.pop("mfa_level", False):
                    def stringify(value: discord.MFALevel) -> str:
                        """Convert Enum to human string"""
                        match value:
                            case discord.MFALevel.disabled:
                                return None
                            case discord.MFALevel.require_2fa:
                                return "2-Factor Authentication Required"
                            case _:
                                return value

                    before.description += f"**MFA Level**: {stringify(key['before'])}\n"
                    after.description += f"**MFA Level**: {stringify(key['after'])}\n"

                if key := changes.pop("verification_level", False):
                    def stringify(value: discord.VerificationLevel) -> str:
                        """Convert Enum to human string"""
                        match value:
                            case discord.VerificationLevel.none:
                                return "None"
                            case discord.VerificationLevel.low:
                                return "Verified Email"
                            case discord.VerificationLevel.medium:
                                return "Verified Email, Registered for 5 minutes"
                            case discord.VerificationLevel.high:
                                return "Verified Email, Registered for 5 minutes, Server Member 10 Minutes"
                            case discord.VerificationLevel.highest:
                                return "Verified Phone"

                    before.description += f"**Verification Level**: `{key['before'].name}` {stringify(key['before'])}\n"
                    after.description += f"**Verification Level**: `{key['after'].name}` {stringify(key['after'])}\n"

                if key := changes.pop("vanity_url_code", False):
                    before.description += f"**Invite URL**: [{key['before']}](https://discord.gg/{key['before']})"
                    after.description += f"**Invite URL**: [{key['after']}](https://discord.gg/{key['after']})"

                if key := changes.pop("description", False):
                    before.add_field(name="**Description**", value=key['before'])
                    after.add_field(name="**Description**", value=key['after'])

                if key := changes.pop("prune_delete_days", None):
                    before.description += f"**Kick Inactive**: " \
                                          f"{key['before'] + ' days' if key['before'] else 'Never'}\n"
                    after.description += f"**Kick Inactive**: {key['after'] + ' days' if key['after'] else 'Never'}\n"

                if key := changes.pop("widget_enabled", None):
                    before.description += f"**Widget Enabled**: {key['before']}\n"
                    after.description += f"**Widget Enabled**: {key['after']}\n"

                if key := changes.pop("preferred_locale", None):
                    before.description += f"**Language**: {key['before']}\n"
                    after.description += f"**Language**: {key['after']}\n"

                if key := changes.pop("splash", None):
                    before.description += f"**Invite Image**: [link]({key['before'].url})\n"
                    before.set_image(url=key['before'].url if key['before'].url else None)
                    after.description += f"**Invite Image**: [link]({key['after'].url})\n"
                    after.set_image(url=key['before'].url if key['after'].url else None)

                if key := changes.pop("discovery_splash", None):
                    before.description += f"**Discovery Image**: [link]({key['before'].url})\n"
                    before.set_image(url=key['before'].url if key['before'].url else None)
                    after.description += f"**Discovery Image**: [link]({key['after'].url})\n"
                    after.set_image(url=key['before'].url if key['after'].url else None)

                if key := changes.pop("banner", None):
                    before.description += f"**Banner**: [link]({key['before'].url})\n"
                    before.set_image(url=key['before'].url if key['before'].url else None)
                    after.description += f"**Banner**: [link]({key['after'].url})\n"
                    after.set_image(url=key['before'].url if key['after'].url else None)

                if key := changes.pop("system_channel_flags", None):
                    bf: discord.SystemChannelFlags = key['before']
                    af: discord.SystemChannelFlags = key['after']

                    if (b := bf.guild_reminder_notifications) != (a := af.guild_reminder_notifications):
                        before.description += f"**Setup Tips**: {'on' if b else 'off'}\n"
                        after.description += f"**Setup Tips**: {'on' if a else 'off'}\n"

                    if (b := bf.join_notifications) != (a := af.join_notifications):
                        before.description += f"**Join Notifications**: {'on' if b else 'off'}\n"
                        after.description += f"**Join Notifications**: {'on' if a else 'off'}\n"

                    if (b := bf.join_notification_replies) != (a := af.join_notification_replies):
                        before.description += f"**Join Stickers**: {'on' if b else 'off'}\n"
                        after.description += f"**Join Stickers**: {'on' if a else 'off'}\n"

                    if (b := bf.premium_subscriptions) != (a := af.premium_subscriptions):
                        before.description += f"**Boost Notifications**: {'on' if b else 'off'}\n"
                        after.description += f"**Boost Notifications**: {'on' if a else 'off'}\n"

                    if (b := bf.role_subscription_purchase_notifications) != \
                            (a := af.role_subscription_purchase_notifications):
                        before.description += f"**Role Subscriptions**: {'on' if b else 'off'}\n"
                        after.description += f"**Role Subscriptions**: {'on' if a else 'off'}\n"

                    if (b := bf.role_subscription_purchase_notification_replies) != \
                            (a := af.role_subscription_purchase_notification_replies):
                        before.description += f"**Role Sub Stickers**: {'on' if b else 'off'}\n"
                        after.description += f"**Role Sub Stickers**: {'on' if a else 'off'}\n"

            case AuditLogAction.channel_create | AuditLogAction.channel_update | AuditLogAction.channel_delete:
                if not (channels := filter(lambda i: i['channels'], channels)):
                    return

                if isinstance(entry.target, discord.Object):
                    channel = entry.guild.get_channel(entry.target.id)
                else:
                    channel = entry.target

                if channel is not None:
                    match entry.action:
                        case AuditLogAction.channel_create:
                            after.description = f"{channel.mention}\n\n"
                        case AuditLogAction.channel_update:
                            before.description = f"{channel.mention}\n\n"
                        case AuditLogAction.channel_delete:
                            before.description = f"{channel.mention}\n\n"

                if key := changes.pop("name", False):
                    before.description += f"**Name**: {key['before']}\n"
                    after.description += f"**Name**: {key['after']}\n"

                if key := changes.pop("bitrate", False):
                    bf = f"{key['before'] / 1000}kbps" if key['before'] else None
                    af = f"{key['after'] / 1000}kbps" if key['after'] else None
                    before.description += f"**Bitrate**: {bf}\n"
                    after.description += f"**Bitrate**: {af}\n"

                if key := changes.pop("user_limit", False):
                    before.description += f"**User Limit**: {key['before']}\n"
                    after.description += f"**User Limit**: {key['after']}\n"

                if key := changes.pop("default_auto_archive_duration", False):
                    bf_archive = str(key['before']) + 'mins' if key['before'] else None
                    af_archive = str(key['before']) + 'mins' if key['before'] else None

                    before.description += f"**Thread Archiving**: {bf_archive}\n"
                    after.description += f"**Thread Archiving**: {af_archive}\n"

                if key := changes.pop("position", False):
                    before.description += f"**Order**: {key['before']}\n"
                    after.description += f"**Order**: {key['after']}\n"

                if key := changes.pop("nsfw", False):
                    before.description += f"**NSFW**: {key['before']}\n"
                    after.description += f"**NSFW**: {key['after']}\n"

                if key := changes.pop("rtc_region", False):
                    before.description += f"**Region**: {key['before']}\n"
                    after.description += f"**Region**: {key['after']}\n"

                if key := changes.pop("topic", False):
                    before.add_field(name="Topic", value=key['before'], inline=False)
                    after.add_field(name="Topic", value=key['after'], inline=False)

                if key := changes.pop("slowmode_delay", False):
                    sm_bf = f"{key['before']} seconds" if key['before'] else 'None'
                    sm_af = f"{key['after']} seconds" if key['before'] else 'None'

                    before.description += f"**Slowmode**: {sm_bf}\n"
                    after.description += f"**Slowmode**: {sm_af}\n"

                # Enums
                if key := changes.pop('video_quality_mode', False):
                    before.description += f"**Video Quality**: {key['before'].name.title()}"
                    after.description += f"**Video Quality**: {key['after'].name.title()}\n"

                if key := changes.pop('type', False):
                    before.description += f"**Type**: {key['before'].name.title() if key['before'] is not None else ''}"
                    after.description += f"**Type**: {key['after'].name.title() if key['after'] is not None else ''}\n"

                if _ := changes.pop('available_tags', False):
                    pass  # Discard.

                # Permission Overwrites
                if key := changes.pop("overwrites", False):
                    bf: list[tuple[discord.Object, discord.PermissionOverwrite]] = key['before']
                    af: list[tuple[discord.Object, discord.PermissionOverwrite]] = key['after']

                    if None not in [bf, af]:
                        for bf_overwrites, af_overwrites in zip(bf, af):
                            user_or_role = bf_overwrites[0]

                            if isinstance(user_or_role, discord.Object):
                                if (user_or_role := self.bot.get_user(user_or_role.id)) is None:
                                    user_or_role = entry.guild.get_role(bf_overwrites[0])

                            if user_or_role:
                                before.description += f"{user_or_role.mention}: "
                                after.description += f"{user_or_role.mention}: "

                            bf_allow, bf_deny = bf_overwrites[1].pair()
                            af_allow, af_deny = af_overwrites[1].pair()

                            for item_bf, item_af in zip(iter(bf_allow), iter(af_allow)):
                                if item_bf[1] == item_af[1]:
                                    continue
                                before.description += f" ✅ {item_bf[0]}" if item_bf[1] else f" ❌ {item_bf[1]}\n"
                                after.description += f" ✅ {item_af[0]}" if item_af[1] else f" ❌ {item_bf[1]}\n"

                # Flags
                if key := changes.pop('flags', False):
                    bf: discord.ChannelFlags = key['before']
                    af: discord.ChannelFlags = key['after']

                    if isinstance(entry.target, discord.Thread):
                        if isinstance(entry.target.parent, discord.ForumChannel):
                            if bf is not None:
                                before.description += f"**Thread Pinned**: {bf.pinned}\n"
                                before.description += f"**Force Tags?**: {bf.require_tag}\n"
                            if af is not None:
                                after.description += f"**Thread Pinned**: {af.pinned}\n"
                                after.description += f"**Force Tags?**: {af.require_tag}\n"

                match entry.action:
                    case AuditLogAction.channel_create:
                        before = None
                        after.title = "Channel Created"
                    case AuditLogAction.channel_update:
                        before.title = "Channel Updated"
                    case AuditLogAction.channel_delete:
                        after = None
                        before.title = "Channel Deleted"

            case AuditLogAction.thread_create | AuditLogAction.thread_update | AuditLogAction.thread_delete:
                if not (channels := filter(lambda i: i['threads'], channels)):
                    return

                if isinstance(thread := entry.target, discord.Object):
                    thread: discord.Thread = entry.guild.get_thread(thread.id)

                if thread is None:
                    before.description = after.description = f"Thread ID# {entry.target.id}"
                else:
                    before.description = after.description = f"{thread.mention}\n\n"

                for k in ['name', 'invitable', 'locked', 'archived']:
                    if key := changes.pop(k, False):
                        before.description += f"**{k.title()}**: {key['before']}\n"
                        after.description += f"**{k.title()}**: {key['after']}\n"

                if key := changes.pop('auto_archive_duration', False):
                    before.description += f"**Inactivity Archive**: {key['before']} minutes\n"
                    after.description += f"**Inactivity Archive**: {key['after']} minutes\n"

                if key := changes.pop('applied_tags', False):
                    bf: list[discord.ForumTag] = [f"{i.emoji} {i.name}" for i in key['before']]
                    af: list[discord.ForumTag] = [f"{i.emoji} {i.name}" for i in key['after']]

                    match entry.action:
                        case AuditLogAction.thread_create:
                            before = None
                            after.add_field(name="Tags", value=', '.join(af))
                        case AuditLogAction.thread_delete:
                            after = None
                            before.add_field(name="Tags", value=', '.join(bf))
                        case AuditLogAction.thread_update:
                            if new := [i for i in af if i not in bf]:
                                after.add_field(name="Tags Removed", value=' ,'.join(new))
                            if gone := [i for i in bf if i not in af]:
                                after.add_field(name="Tags Added", value=' ,'.join(gone))

                if key := changes.pop('flags', False):
                    if thread is not None:
                        if isinstance(thread.parent, discord.ForumChannel):
                            bf: discord.ChannelFlags = key['before']
                            af: discord.ChannelFlags = key['after']
                            if bf is not None:
                                before.description += f"**Thread Pinned**: {bf.pinned}\n"
                                before.description += f"**Force Tags?**: {bf.require_tag}\n"
                            if af is not None:
                                after.description += f"**Thread Pinned**: {af.pinned}\n"
                                after.description += f"**Force Tags?**: {af.require_tag}\n"

                if key := changes.pop('slowmode_delay', False):
                    before.description += f"**Slow Mode**: {key['before'] + 'seconds' if key['before'] else None}\n"
                    after.description += f"**Slow Mode**: {key['after'] + 'seconds' if key['before'] else None}\n"

                if ct := changes.pop('type', False):
                    ct: dict[str, discord.ChannelType]
                    bf_type = str(ct['before'])
                    af_type = str(ct['after'])
                else:
                    bf_type = af_type = "Thread"

                match entry.action:
                    case AuditLogAction.thread_create:
                        before = None
                        after.title = f"{af_type} Created"
                    case AuditLogAction.thread_delete:
                        after = None
                        before.title = f"{bf_type} Deleted"
                    case AuditLogAction.thread_update:
                        before.title = f"{af_type} Thread Updated"

            case AuditLogAction.stage_instance_create | AuditLogAction.stage_instance_update | \
                 AuditLogAction.stage_instance_delete:

                if not (channels := filter(lambda i: i['channels'], channels)):
                    return

                # A Stage *INSTANCE* happens on a stage *CHANNEL*
                if isinstance(entry.target, discord.Object):
                    stg_channel: discord.StageChannel = entry.guild.get_channel(entry.target.id)
                else:
                    stage: discord.StageInstance = entry.target
                    stg_channel = stage.channel

                if stg_channel is not None:
                    before.description = after.description = f"{stg_channel.mention}\n\n"

                if key := changes.pop('topic', False):
                    before.add_field(name="Topic", value=key['before'])
                    after.add_field(name="Topic", value=key['after'])

                if key := changes.pop('privacy_level', False):
                    before.description += f"**Privacy**: {key['before']}\n"
                    after.description += f"**Privacy**: {key['after']}\n"

                match entry.action:
                    case AuditLogAction.stage_instance_create:
                        after.title = "Stage Instance Started"
                        before = None
                    case AuditLogAction.stage_instance_update:
                        before.title = "Stage Instance Updated"
                        before.set_footer()  # Clear Footer
                    case AuditLogAction.stage_instance_delete:
                        before.title = "Stage Instance Ended"
                        after = None

            case AuditLogAction.message_pin | AuditLogAction.message_unpin:
                if not (channels := filter(lambda i: i['channels'], channels)):
                    return

                msg = entry.extra.channel.get_partial_message(entry.extra.message_id)
                after.description = f"{entry.extra.channel.mention} {entry.target.mention}" \
                                    f"\n\n[Jump to Message]({msg.jump_url})"
                before = None
                match entry.action:
                    case AuditLogAction.message_pin:
                        after.title = "Message Pinned"
                        after.colour = Colour.light_gray()
                    case AuditLogAction.message_unpin:
                        after.title = "Message Unpinned"
                        after.colour = Colour.dark_gray()

            case AuditLogAction.overwrite_create | AuditLogAction.overwrite_update | AuditLogAction.overwrite_delete:
                if not (channels := filter(lambda i: i['channels'], channels)):
                    return

                channel: discord.TextChannel = entry.target
                if isinstance(entry.extra, Role | Member):
                    ow_target = entry.extra.mention
                else:
                    ow_target = f"{entry.extra.name} ({entry.extra.type}: {entry.extra.id})"

                # id & type of channel

                before.description = f"{channel.mention}: {ow_target}\n\n"
                after.description = f"{channel.mention}: {ow_target}\n\n"

                if _ids := changes.pop('id', False):
                    _types: dict[str, discord.ChannelType] = changes.pop('type')

                    if _types is not None:
                        before.set_author(name=f"{_types['before']}: {channel.name} ({channel.id})")
                        after.set_author(name=f"#{_types['after']}: {channel.name} ({channel.id})")
                    else:
                        before.set_author(name=f"{channel.name} ({channel.id})")
                        after.set_author(name=f"{channel.name} ({channel.id})")

                if key := changes.pop('deny', False):
                    bf: discord.Permissions = key['before']
                    af: discord.Permissions = key['after']

                    bf_list = []
                    af_list = []

                    if None not in [bf, af]:
                        for k, v in iter(bf):
                            if getattr(bf, k) == getattr(af, k):
                                continue

                            if v:
                                bf_list.append(f"❌ {k}")
                            else:
                                af_list.append(f"❌ {k}")
                    elif bf is None:
                        af_list = [f"❌ {k}" for k, v in iter(af) if v]
                    elif af is None:
                        bf_list = [f"❌ {k}" for k, v in iter(bf) if v]

                    if bf_list:
                        before.add_field(name='Denied Perms', value='\n'.join(bf_list))
                    if af_list:
                        after.add_field(name='Denied Perms', value='\n'.join(af_list))

                if key := changes.pop('allow', False):
                    bf: discord.Permissions = key['before']
                    af: discord.Permissions = key['after']
                    bf_list = []
                    af_list = []

                    if None not in [bf, af]:
                        for k, v in iter(bf):
                            if getattr(bf, k) == getattr(af, k):
                                continue

                            if v:
                                bf_list.append(f"✅ {k}")
                            else:
                                af_list.append(f"✅ {k}")
                    elif bf is None:
                        af_list = [f"✅ {k}" for k, v in iter(af) if v]
                    elif af is None:
                        bf_list = [f"✅ {k}" for k, v in iter(bf) if v]

                    if bf_list:
                        before.add_field(name='Allowed Perms', value="\n".join(bf_list))
                    if af_list:
                        after.add_field(name='Allowed Perms', value="\n".join(af_list))

                match entry.action:
                    case AuditLogAction.overwrite_create:
                        before = None
                        after.title = "Channel Permission Overwrites Created"
                    case AuditLogAction.overwrite_update:
                        before.title = "Channel Permission Overwrites Updated"
                        before.set_footer()  # Clear Footer
                        after.description = None
                    case AuditLogAction.overwrite_delete:
                        after = None
                        before.title = "Channel Permission Overwrites Removed"

            case AuditLogAction.scheduled_event_create | AuditLogAction.scheduled_event_update | \
                 AuditLogAction.scheduled_event_delete:
                if not (channels := filter(lambda i: i['events'], channels)):
                    return

                if image := changes.pop('cover_image', False):
                    image: dict[str, discord.Asset]
                    before.set_image(url=image['before'].url)
                    after.set_image(url=image['after'].url)

                if key := changes.pop('name', False):
                    before.description += f"**Name**: {key['before']}\n"
                    after.description += f"**Name**: {key['after']}\n"

                if key := changes.pop('description', False):
                    before.add_field(name="Event Description", value=key['before'])
                    after.add_field(name="Event Description", value=key['after'])

                if key := changes.pop('privacy_level', False):
                    before.description += f"**Privacy**: {key['before']}\n"
                    after.description += f"**Privacy**: {key['after']}\n"

                if key := changes.pop('status', False):
                    before.description += f"**Status**: {key['before']}\n"
                    after.description += f"**Status**: {key['after']}\n"

                location: dict[str, str] = changes.pop('location', {})
                channel: dict[str, discord.StageChannel | discord.VoiceChannel] = changes.pop('channel', {})

                if key := changes.pop('entity_type', False):
                    match key['before']:
                        case discord.EntityType.voice | discord.EntityType.stage_instance:
                            before.description += f"**Location**: {channel['before'].mention}"
                        case discord.EntityType.external:
                            before.description += f"**Location**: {location['before']}"

                    match key['after']:
                        case discord.EntityType.voice | discord.EntityType.stage_instance:
                            after.description += f"**Location**: {channel['after'].mention}"
                        case discord.EntityType.external:
                            after.description += f"**Location**: {location['after']}"

                match entry.action:
                    case AuditLogAction.scheduled_event_create:
                        after.title = "Scheduled Event Created"
                        before = None
                    case AuditLogAction.scheduled_event_update:
                        before.title = "Scheduled Event Updated"
                        before.set_footer()  # Clear Footer fields.
                    case AuditLogAction.scheduled_event_delete:
                        before.title = "Scheduled Event Deleted"
                        after = None

            case AuditLogAction.kick:
                if not (channels := filter(lambda i: i['kicks'], channels)):
                    return

                before = None

                after.title = "User Kicked"

                if isinstance(target := entry.target, discord.Object):
                    target: User = self.bot.get_user(target.id)

                if target is not None:
                    after.set_author(name=f"{target} ({entry.target.id})", icon_url=entry.target.display_avatar.url)
                    after.description = f"{target.mention} (ID: {target.id}) was kicked."
                else:
                    after.set_author(name=f"User #{entry.target.id}")
                    after.description = f"User with ID `{entry.target.id}` was kicked."

            case AuditLogAction.ban:
                if not (channels := filter(lambda i: i['bans'], channels)):
                    return

                before = None
                after.title = "User banned"

                if isinstance(target := entry.target, discord.Object):
                    target = self.bot.get_user(entry.target.id)

                if target is not None:
                    after.set_author(name=f"{target} ({entry.target.id})", icon_url=entry.target.display_avatar.url)
                    after.description = f"{entry.target.mention} was banned."
                else:
                    after.set_author(name=f"User #{entry.target.id}")
                    after.description = f"User with ID `{entry.target.id}` was banned."

            case AuditLogAction.unban:
                if not (channels := filter(lambda i: i['bans'], channels)):
                    return

                before = None
                after.title = "User unbanned"

                if isinstance(user := entry.target, discord.Object):
                    user = self.bot.get_user(entry.target.id)

                if user is not None:
                    after.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
                    after.description = f"{user.mention} was unbanned."
                else:
                    after.set_author(name=f"User #{entry.target.id}")
                    after.description = f"User with ID `{entry.target.id}` was unbanned."

            # User Edits
            case AuditLogAction.member_update:
                # Name Change, Muted, Deafened, Timed Out.
                if not (channels := filter(lambda i: i['moderation'], channels)):
                    return

                if isinstance(user := entry.target, discord.Object):
                    user = entry.guild.get_member(user.id)

                after.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
                after.description = f"{user.mention}\n\n"

                if key := changes.pop("nick", False):
                    after.title = "User Renamed"

                    bf = user.name if key['before'] is None else key['before']
                    af = user.name if key['after'] is None else key['after']

                    after.description += f"**Old**: {bf}\n**New**: {af}"

                if key := changes.pop("mute", False):
                    if key['before']:
                        after.title = "User Server Un-muted"
                    else:
                        after.title = "User Server Muted"

                if key := changes.pop("deaf", False):
                    if key['before']:
                        after.title = "User Server Un-deafened"
                    else:
                        after.title = "User Server Deafened"

                if key := changes.pop("timed_out_until", False):
                    if key['before'] is None:
                        after.title = "Timed Out"
                        after.description += f"**Timeout Expires*: {Timestamp(key['after']).relative}\n"
                    else:
                        after.title = "Timeout Ended"

                before = None

            case AuditLogAction.member_move:
                if not (channels := filter(lambda i: i['moderation'], channels)):
                    return

                before = None

                after.title = "Moved to Voice Channel"
                after.description = f"{entry.extra.count} users\n\nNew Channel: {entry.extra.channel.mention}"

            case AuditLogAction.member_disconnect:  # Kicked from voice
                if not (channels := filter(lambda i: i['moderation'], channels)):
                    return

                before = None
                after.title = "Kicked From Voice Channel"
                after.description = f"{entry.extra.count} users"

            # Roles
            case AuditLogAction.role_create | AuditLogAction.role_update | AuditLogAction.role_delete:
                if not (channels := filter(lambda i: i['role_edits'], channels)):
                    return

                before.description = after.description = f"<@&{entry.target.id}>\n\n"

                for k in ['name', 'mentionable']:
                    if key := changes.pop(k, False):
                        before.description += f"**{k.title()}**: {key['before']}\n"
                        after.description += f"**{k.title()}**: {key['after']}\n"

                if key := changes.pop("colour", False):
                    changes.pop("color")
                    before.description += f"**Colour**: {key['before']}\n"
                    after.description += f"**Colour**: {key['after']}\n"
                    before.colour = key['before']
                    after.colour = key['after']

                if key := changes.pop("hoist", False):
                    before.description += f"**Show Separately**: {key['before']}\n"
                    after.description += f"**Show Separately**: {key['after']}\n"

                if key := changes.pop("unicode_emoji", False):
                    before.description += f"**Emoji**: {key['before']}\n"
                    after.description += f"**Emoji**: {key['after']}\n"

                if key := changes.pop("icon", False):
                    bf_img = key['before'].url if key['before'] is not None else None
                    af_img = key['before'].url if key['after'] is not None else None

                    before.description += f"**Icon**: {f'[Link]({bf_img})' if bf_img else None}\n"
                    after.description += f"**Icon**: {f'[Link]({af_img})' if af_img else None}\n"
                    before.set_image(url=key['before'].url if bf_img is not None else None)
                    after.set_image(url=key['after'].url if af_img is not None else None)

                if key := changes.pop("permissions", False):
                    bf: discord.Permissions = key['before']
                    af: discord.Permissions = key['after']

                    bf_list = []
                    af_list = []

                    if None not in [bf, af]:
                        for k, v in iter(bf):
                            if getattr(bf, k) == getattr(af, k):
                                continue

                            if v:
                                bf_list.append(f"✅ {k}")
                                af_list.append(f"❌ {k}")
                            else:
                                bf_list.append(f"❌ {k}")
                                af_list.append(f"✅ {k}")
                    elif bf is None:
                        af_list = [f"✅ {k}" for k, v in iter(af) if v]
                    elif af is None:
                        bf_list = [f"✅ {k}" for (k, v) in iter(bf) if v]

                    if bf_list:
                        before.add_field(name='Permissions', value='\n'.join(bf_list))
                    if af_list:
                        after.add_field(name='Permissions', value='\n'.join(af_list))

                if isinstance(role := entry.target, discord.Object):
                    role = entry.guild.get_role(entry.target.id)

                if role is None:
                    role_icon = None
                else:
                    role_icon: str = role.display_icon.url if role.display_icon is not None else None

                match entry.action:
                    case AuditLogAction.role_create:

                        before.set_author(name=f"{role} ({entry.target.id})", icon_url=role_icon)
                        before.title = "Role Created"
                        after = None
                    case AuditLogAction.role_update:
                        before.set_author(name=f"{role} ({entry.target.id})", icon_url=role_icon)
                        before.title = "Role Updated"
                        before.set_footer()  # Clear Footer.
                    case AuditLogAction.role_delete:
                        before = None
                        after.title = "Role Deleted"
                        after.set_author(name=f"{role} ({entry.target.id})", icon_url=role_icon)

            case AuditLogAction.member_role_update:  # Role Grants
                if not (channels := filter(lambda i: i['user_roles'], channels)):
                    return

                before = None

                member = entry.target
                if isinstance(member, discord.Object):
                    member = entry.guild.get_member(member.id)

                if member is not None:
                    after.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
                else:
                    after.set_author(name=f"User with ID #{entry.target.id}")

                if key := changes.pop("roles", False):
                    if key['after']:
                        after.title = "Role Granted"
                        after.colour = Colour.green()
                        after.description = ', '.join([i.mention for i in key['after']])
                    else:
                        after.title = "Role Removed"
                        after.colour = Colour.red()
                        after.description = ', '.join([i.mention for i in key['before']])

            # Emojis / Emotes
            case AuditLogAction.emoji_create | AuditLogAction.emoji_update | AuditLogAction.emoji_delete:
                if not (channels := filter(lambda i: i['emote_and_sticker'], channels)):
                    return

                if isinstance(emoji := entry.target, discord.Object):
                    try:
                        emoji = next(i for i in entry.guild.emojis if i.id == emoji.id)
                    except StopIteration:
                        try:
                            emoji = await entry.guild.fetch_emoji(emoji.id)
                        except discord.NotFound:
                            emoji = None

                    if emoji is not None:
                        before.set_image(url=emoji.url)
                        after.set_image(url=emoji.url)

                for k in ['name']:
                    if key := changes.pop(k, False):
                        before.description += f"**{k.title()}((: {key['before']}\n"
                        after.description += f"**{k.title()}**: {key['after']}\n"

                match entry.action:
                    case AuditLogAction.emoji_create:
                        before.title = "Emoji Created"
                        after = None
                    case AuditLogAction.emoji_update:
                        before.title = "Emoji Updated"
                        after.set_image(url=None)
                    case AuditLogAction.emoji_delete:
                        before = None
                        after.title = "Emoji Deleted"

            # Stickers
            case AuditLogAction.sticker_create | AuditLogAction.sticker_update | AuditLogAction.sticker_delete:
                if not (channels := filter(lambda i: i['emote_and_sticker'], channels)):
                    return

                if isinstance(target := entry.target, discord.Object):
                    target: discord.GuildSticker = self.bot.get_sticker(target.id)

                if key := changes.pop('name', False):
                    before.description = f"name: {key['before']}\n"
                    after.description = f"name: {key['after']}\n"

                if key := changes.pop('description', False):
                    before.add_field(name="Description", value=f"{key['before']}")
                    after.add_field(name="Description", value=f"{key['after']}")

                match entry.action:
                    case AuditLogAction.sticker_create:
                        after.set_image(url=target.url)
                        after.title = "Sticker Created"
                        before = None
                    case AuditLogAction.sticker_update:
                        before.set_image(url=target.url)
                        before.title = "Sticker Updated"
                    case AuditLogAction.sticker_delete:
                        before.set_image(url=target.url)
                        before.title = "Sticker Deleted"
                        after = None
            # Invites
            case AuditLogAction.invite_create | AuditLogAction.invite_update | AuditLogAction.invite_delete:
                if not (channels := filter(lambda i: i['invites'], channels)):
                    return

                if key := changes.pop('code', False):
                    before.description += f"**Link**: http://www.discord.gg/{key['before']}\n\n"
                    after.description += f"**Link**: http://www.discord.gg/{key['after']}\n\n"

                if key := changes.pop('channel', False):
                    before.description += f"**Channel**: {key['before'].mention}\n" if key['before'] is not None else ''
                    after.description += f"**Channel**: {key['after'].mention}\n" if key['after'] is not None else ''

                if key := changes.pop('inviter', False):
                    user = key['before']
                    if user is not None:
                        before.set_author(name=f"{user.mention} ({user.id})", icon_url=user.display_avatar.url)
                    user = key['after']
                    if user is not None:
                        after.set_author(name=f"{user.mention} ({user.id})", icon_url=user.display_avatar.url)

                if key := changes.pop('uses', False):
                    before.description += f"**Uses**: {key['before']}\n"
                    after.description += f"**Uses**: {key['after']}\n"

                if key := changes.pop('max_uses', False):
                    before.description += f"**Max Uses**: {key['before']}\n"
                    after.description += f"**Max Uses**: {key['after']}\n"

                if key := changes.pop('max_age', False):
                    bf = f"{key['before']}" + ' seconds' if key['before'] else 'Permanent'
                    before.description += f"**Expiry**: {bf}\n"
                    af = f"{key['after']}" + ' seconds' if key['after'] else 'Permanent'
                    after.description += f"**Expiry**: {af}\n"

                temp = "Temporary" if changes.pop('temporary', False) else "Permanent"

                match entry.action:
                    case AuditLogAction.invite_create:
                        after.title = f"{temp} Invite Created"
                        before = None
                    case AuditLogAction.invite_update:
                        before.title = f"{temp} Invite Updated"
                    case AuditLogAction.invite_delete:
                        before.title = f"{temp} Invite Deleted"
                        after = None

            # Bots & Integrations
            case AuditLogAction.bot_add:
                if not (channels := filter(lambda i: i['bot_management'], channels)):
                    return

                after.title = "Bot Added"
                after.set_author(name=f"{entry.target} ({entry.target.id})", icon_url=entry.target.display_avatar.url)
                after.description = f"{entry.target.mention} (ID: {entry.target.id})"
                before = None

            case AuditLogAction.message_delete:
                if not (channels := filter(lambda i: i['deleted_messages'], channels)):
                    return

                if isinstance(target := entry.target, discord.Object):
                    try:
                        target = entry.guild.get_member(entry.target.id)
                    except AttributeError:
                        target = self.bot.get_user(entry.target.id)

                if target is not None:
                    after.set_author(name=f"{target} ({target.id})", icon_url=target.display_avatar.url)
                else:
                    after.set_author(name=f"User with ID# {entry.target.id}")

                after.description = f"{entry.extra.count} message(s) deleted in {entry.extra.channel.mention}"
                before = None
            case AuditLogAction.message_bulk_delete:
                if not (channels := filter(lambda i: i['deleted_messages'], channels)):
                    return

                after.title = "Messages Bulk Deleted"
                after.description = f"{entry.target.mention}: {entry.extra.count} messages deleted."
                before = None

            # Webhooks
            case AuditLogAction.webhook_create | AuditLogAction.webhook_update | AuditLogAction.webhook_delete:
                logging.info(f"{entry.action} |  {changes}")
                if not (channels := filter(lambda i: i['bot_management'], channels)):
                    return

                if key := changes.pop('name', False):
                    before.description += f"**Name**: {key['before']}\n"
                    after.description += f"**Name**: {key['after']}\n"

                if key := changes.pop('channel', False):
                    before.description += f"**Channel**: {key['before'].mention if key['before'] else None}\n"
                    after.description += f"**Channel**: {key['after'].mention if key['after'] else None}\n"

                if key := changes.pop('channel', False):
                    before.description += f"**Type**: {key['before'].name if key['before'] else None}\n"
                    after.description += f"**Type**: {key['after'].name if key['after'] else None}\n"

                if key := changes.pop('application_id', False):
                    before.description += f"**Application ID**: {key['before']}\n"
                    after.description += f"**Application ID**: {key['after']}\n"

                match entry.action:
                    case AuditLogAction.webhook_create:
                        before = None
                        after.title = "Webhook Created"
                    case AuditLogAction.webhook_update:
                        before.set_footer()  # Clear Footer
                        before.title = "Webhook Updated"
                    case AuditLogAction.webhook_delete:
                        before.title = "Webhook Deleted"
                        after = None

            # Integrations
            case AuditLogAction.integration_create | AuditLogAction.integration_update | \
                 AuditLogAction.integration_delete:

                if not (channels := filter(lambda i: i['bot_management'], channels)):
                    return

                # TODO: Parse
                # Changes Remain: {'name': {'before': None, 'after': 'Spam'},
                # 'trigger_type': {'before': None, 'after': <AutoModRuleTriggerType.spam: 3>},
                # 'event_type': {'before': None, 'after': <AutoModRuleEventType.message_send: 1>},
                # 'actions': {'before': None, 'after': [<AutoModRuleAction type=1 channel=None duration=None>]},
                # 'enabled': {'before': None, 'after': True},
                # 'exempt_roles': {'before': None, 'after': []},
                # 'exempt_channels': {'before': None, 'after': []}}

                if key := changes.pop("name", False):
                    before.description += f"**Name**: {key['before']}\n"
                    after.description += f"**Name**: {key['after']}\n"

                if key := changes.pop("type", False):
                    before.description += f"**Type**: {key['before']}\n"
                    after.description += f"**Type**: {key['after']}\n"

                if key := changes.pop("exempt_roles", False):
                    bf_roles: list[Role] = key['before']
                    af_roles: list[Role] = key['after']

                    new = [i for i in af_roles if i not in bf_roles]
                    removed = [i for i in bf_roles if i not in af_roles]

                    if bf_roles:
                        after.add_field(name="Role Exemptions Added", value=', '.join([i.mention for i in new]))
                    if af_roles:
                        after.add_field(name="Role Exemptions Removed", value=', '.join([i.mention for i in removed]))

                match entry.action:
                    case AuditLogAction.automod_rule_create:
                        before = None
                        after.title = "Integration Created"
                    case AuditLogAction.integration_update:
                        before.set_footer()  # Clear Footer
                        before.title = "Integration Updated"
                    case AuditLogAction.integration_delete:
                        before.title = "Integration Deleted"
                        after = None

            # Command Permissions
            case AuditLogAction.app_command_permission_update:

                if not (channels := filter(lambda i: i['bot_management'], channels)):
                    return

                integration: discord.PartialIntegration | discord.app_commands.AppCommand = entry.target

                # The Integration that this Command Belongs to.
                extra: discord.PartialIntegration | discord.Object = entry.extra

                before.set_footer()  # Clear Footer

                if isinstance(integration, discord.Object):

                    match integration.type:
                        case discord.PartialIntegration:

                            before.title = f"Application Permissions Updated"
                            before.set_author(name=str(integration))

                        case discord.app_commands.models.AppCommand:

                            before.title = "Command Permissions Updated"
                            before.set_author(name=f"{extra.name}: ({extra.id})")
                            before.description = f"{extra.name}: {integration.__dict__}"

                # If it is a partial Integration, this affects the Application server-wide.
                if isinstance(integration, discord.PartialIntegration):
                    before.title = f"Application Permissions Updated"
                    before.set_author(name=integration.name)
                    before.description = f"<{integration.name}:{integration.id}>"

                # If it is an app_command, this affects the specific command.
                elif isinstance(integration, discord.app_commands.models.AppCommand):
                    app_cmd: discord.app_commands.models.AppCommand = integration

                    before.set_author(name=f"Application ID: {app_cmd.application_id}")
                    before.description = f"{app_cmd.mention}\n\n"
                    before.title = f"App Command Permissions Updated"

                if key := changes.pop("app_command_permissions", False):

                    def do_perms(permissions: list[discord.app_commands.AppCommandPermissions], embed: Embed) -> None:
                        """Update the embed"""

                        if not permissions:
                            permissions = entry.target.default_member_permissions

                        for p in permissions:
                            match p.type:
                                case discord.AppCommandPermissionType.user:
                                    mention = f"<@{p.target.id}>"
                                case discord.AppCommandPermissionType.role:
                                    mention = f"<@&{p.target.id}>"
                                case discord.AppCommandPermissionType.channel:
                                    if isinstance(p.target, discord.app_commands.AllChannels):
                                        mention = f"All Channels: <id:browse>"
                                    else:
                                        mention = f"<#{p.target.id}>"
                                case _:
                                    mention = "?"
                            embed.description += f"{'✅' if p.permission else '❌'} {mention}\n"

                    do_perms(key['before'], before)
                    do_perms(key['after'], after)

            # Auto moderation
            case AuditLogAction.automod_rule_create | AuditLogAction.automod_rule_update | \
                 AuditLogAction.automod_rule_delete:

                if not (channels := filter(lambda i: i['bot_management'], channels)):
                    return

                if key := changes.pop('trigger', False):
                    bf: discord.AutoModTrigger = key['before'] if key['before'] else []
                    af: discord.AutoModTrigger = key['after'] if key['after'] else []

                    if None not in [bf, af]:
                        new_words = [i for i in bf if i not in af]
                        removed = [i for i in bf if i not in af]
                    elif bf is None:
                        new_words = af
                        removed = []
                    else:  # af is None
                        new_words = []
                        removed = bf

                    if new_words:
                        after.add_field(name="New Blocked Terms", value=', '.join(new_words), inline=False)
                    if removed:
                        before.add_field(name="Blocked Terms Removed", value=', '.join(removed), inline=False)

                match entry.action:
                    case AuditLogAction.automod_rule_create:
                        before = None
                        after.title = "Automod Rule Created"
                    case AuditLogAction.automod_rule_update:
                        before.set_footer()  # Clear Footer
                        before.title = "Automod Rule Updated"
                    case AuditLogAction.automod_rule_delete:
                        after.title = "Automod Rule Deleted"
                        before = None

            case AuditLogAction.automod_flag_message | AuditLogAction.automod_block_message:
                if not (channels := filter(lambda i: i['moderation'], channels)):
                    return

                match entry.action:
                    case AuditLogAction.automod_flag_message:
                        after.title = "Automod: Message Flagged"
                    case AuditLogAction.automod_block_message:
                        after.title = "Automod: Message Blocked"

                match entry.extra.automod_rule_trigger_type:
                    case discord.AutoModRuleTriggerType.keyword:
                        trigger = "Keyword Mentioned"
                    case discord.AutoModRuleTriggerType.keyword_preset:
                        trigger = "Keyword Preset Mentioned"
                    case discord.AutoModRuleTriggerType.harmful_link:
                        trigger = "Harmful Links"
                    case discord.AutoModRuleTriggerType.mention_spam:
                        trigger = "Mention Spam"
                    case discord.AutoModRuleTriggerType.spam:
                        trigger = "Spam"
                    case _:
                        trigger = "Unknown"

                after.description = f"{entry.target.mention}: {entry.extra.channel.mention}\n\n" \
                                    f"**Rule**: {entry.extra.automod_rule_name}\n" \
                                    f"**Trigger**: {trigger}"

            case AuditLogAction.automod_timeout_member:
                if not (channels := filter(lambda i: i['moderation'], channels)):
                    return

                member = entry.target

                match entry.extra.automod_rule_trigger_type:
                    case discord.AutoModRuleTriggerType.keyword:
                        trigger = "Keyword Mentioned"
                    case discord.AutoModRuleTriggerType.keyword_preset:
                        trigger = "Keyword Preset Mentioned"
                    case discord.AutoModRuleTriggerType.harmful_link:
                        trigger = "Harmful Links"
                    case discord.AutoModRuleTriggerType.mention_spam:
                        trigger = "Mention Spam"
                    case discord.AutoModRuleTriggerType.spam:
                        trigger = "Spam"
                    case _:
                        trigger = "Unknown"

                after.title = "Automod Timeout"
                after.description = f"{member.mention} in {entry.extra.channel.mention}" \
                                    f"**Rule**: {entry.extra.automod_rule_name}\n" \
                                    f"**Trigger**: {trigger}"
                before = None

        # Audit log entries received through the gateway are subject to data retrieval from cache rather than REST.
        # This means that some data might not be present when you expect it to be.
        # For example, the AuditLogEntry.target attribute will usually be a discord.Object and the AuditLogEntry.user
        # attribute will depend on user and member cache.
        #
        # To get the user ID of entry, AuditLogEntry.user_id can be used instead.
        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        for ch in channels:
            try:
                await self.bot.get_channel(ch['channel_id']).send(embeds=[i for i in [before, after] if i])
            except discord.HTTPException:
                continue

    # Deleted message notif
    @Cog.listener()
    async def on_message_delete(self, message: Message) -> None:
        """Event handler for reposting deleted messages from users"""
        if message.guild is None or message.author.bot:
            return  # Ignore DMs & Do not log message deletions from bots.

        ch = filter(lambda i: i['guild_id'] == message.guild.id and i['deleted_messages'], self.bot.notifications_cache)
        if not (ch := filter(None, [self.bot.get_channel(i['channel_id']) for i in ch])):
            return

        e: Embed = Embed(colour=Colour.dark_red(), title="Deleted Message", timestamp=discord.utils.utcnow())
        e.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
        t = timed_events.Timestamp(discord.utils.utcnow()).datetime
        e.description = f"{t} {message.channel.mention}\n\n{message.content}"
        attachments: list[File] = []

        for num, z in enumerate(message.attachments, 1):
            v = f"📎 *Attachment info*: [{z.filename}]({z.proxy_url}) ({z.content_type} - {z.size} bytes)" \
                f"\n*This is cached and will only be available for a limited time*"
            e.add_field(name=f"Attachment #{num}", value=v)
            try:
                attachments.append(await z.to_file(spoiler=True, use_cached=True))
            except discord.HTTPException:
                pass

        for channel in ch:
            try:
                await channel.send(embed=e, files=attachments)
            except discord.HTTPException:
                continue

    # Kick notif
    # Leave notif
    @Cog.listener()
    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent) -> None:
        """Event handler for outputting information about member kick, ban, or other departures"""
        # Check if in mod action log and override to specific channels.
        channels = filter(lambda i: i['guild_id'] == payload.guild_id and i['leaves'],
                          self.bot.notifications_cache)
        channels = filter(None, [self.bot.get_channel(i['channel_id']) for i in channels])

        if not channels:
            return

        ts = discord.utils.utcnow()
        timestamp = Timestamp(ts).time_relative

        member: User | Member = payload.user
        e: Embed = Embed(description=f"{timestamp} {member.mention}", colour=Colour.dark_red(), timestamp=ts)
        e.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
        e.title = "Member Left"

        for ch in channels:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                pass

    # emojis notif
    @Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[Emoji], after: list[Emoji]) -> None:
        """Event listener for outputting information about updated emojis on a server"""
        channels = filter(lambda i: i['guild_id'] == guild.id and i['emote_and_sticker'], self.bot.notifications_cache)

        if not (channels := filter(None, [self.bot.get_channel(i['channel_id']) for i in channels])):
            return

        e: Embed = Embed()
        # Find if it was addition or removal.
        added = [i for i in after if i not in before]
        removed = [i for i in before if i not in after]

        embeds: list[Embed] = []

        if added:
            for emoji in added:
                e.colour = Colour.dark_purple() if emoji.managed else Colour.green()
                if not emoji.managed:
                    continue

                e.set_author(name="Twitch Integration", icon_url=TWITCH_LOGO)
                if emoji.roles:
                    e.add_field(name='Available to roles', value=' '.join([i.mention for i in emoji.roles]))

                e.title = f"New {'animated ' if emoji.animated else ''}emote: {emoji.name}"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)
                embeds.append(e.copy())
                e.clear_fields()
        else:
            e.title = "Emote removed"
            e.colour = Colour.light_gray()
            for emoji in removed:
                if not emoji.managed:
                    continue

                e.title = f"{'Animated ' if emoji.animated else ''} Emoji Removed"
                e.description = f"The '{emoji}' emote was removed"
                e.set_image(url=emoji.url)
                e.set_footer(text=emoji.url)
                embeds.append(e.copy())
                e.clear_fields()

        for ch in channels:
            try:
                await ch.send(embeds=embeds)
            except discord.HTTPException:
                continue

    @Cog.listener()
    async def on_message_edit(self, before: Message, after: Message) -> None:
        """Edited message output."""
        if before.guild is None or before.content == after.content:
            return

        if before.author.bot:
            return

        ch = filter(lambda i: i['guild_id'] == before.guild.id and i['edited_messages'], self.bot.notifications_cache)
        if not (ch := filter(None, [self.bot.get_channel(i['channel_id']) for i in ch])):
            return

        ts = Timestamp(before.created_at).relative
        e: Embed = Embed(title="Message Edited", colour=Colour.brand_red(),
                         description=f"{ts} {before.channel.mention}\n\n{before.content}")
        e2: Embed = Embed(title="After", colour=Colour.brand_green(), timestamp=after.edited_at,
                          description=f"{after.content}")
        e.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)

        v = View()
        v.add_item(Button(label="Jump to message", url=before.jump_url, style=discord.ButtonStyle.url))

        for c in ch:
            try:
                await c.send(embeds=[e, e2], view=v)
            except discord.HTTPException:
                continue

    @Cog.listener()
    async def on_bulk_message_delete(self, messages: list[Message]):
        """Iter message_delete"""
        for x in messages:
            await self.on_message_delete(x)

    @Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionClearEvent):
        """Triggered when all reactions are removed from a message"""
        channels = filter(lambda i: i['guild_id'] == payload.guild_id, self.bot.notifications_cache)
        if not (channels := filter(lambda i: self.bot.get_channel(i['channel_id']), channels)):
            return

        if not (channels := filter(lambda i: i['moderation'], channels)):
            return

        channel = self.bot.get_channel(payload.channel_id)
        message = channel.get_partial_message(payload.message_id)

        e = Embed(title="All Reactions Cleared", colour=Colour.greyple())
        e.description = f"**Message**: [Link]({message.jump_url})\n"

        for ch in channels:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                continue

    @Cog.listener()
    async def on_raw_reaction_clear_emoji(self, payload: discord.RawReactionClearEmojiEvent):
        """Triggered when a single reaction is removed from a message"""
        channels = filter(lambda i: i['guild_id'] == payload.guild_id, self.bot.notifications_cache)
        if not (channels := filter(lambda i: self.bot.get_channel(i['channel_id']), channels)):
            return

        if not (channels := filter(lambda i: i['moderation'], channels)):
            return

        channel = self.bot.get_channel(payload.channel_id)
        message = channel.get_partial_message(payload.message_id)
        emoji = payload.emoji

        e = Embed(title="Reaction Cleared", colour=Colour.greyple())
        e.description = f"**Message**: [Link]({message.jump_url})\n**Emoji**: {emoji}"

        for ch in channels:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                continue

    @Cog.listener()
    async def on_bot_notification(self, notification: str) -> None:
        """Custom event dispatched by painezor, output to tracked guilds."""
        e: Embed = Embed(description=notification)

        for x in filter(lambda i: i['bot_notifications'], self.bot.notifications_cache):
            try:
                ch = self.bot.get_channel(x['channel_id'])
                e.colour = ch.guild.me.colour
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue


async def setup(bot: Bot | PBot) -> None:
    """Loads the notifications cog into the bot"""
    await bot.add_cog(Logs(bot))
