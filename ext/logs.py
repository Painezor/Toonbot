"""Notify server moderators about specific events"""
# TODO: Fallback parser using regular events -- Check if bot has
# view_audit_log perms
# TODO: Validate all auditlog actions on test server.
# TODO: Fix Timestamping for all auditlog actions

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import discord
from discord import (
    AuditLogAction,
    Colour,
    Embed,
    Emoji,
    File,
    Interaction,
    Member,
    Message,
    Role,
    TextChannel,
    User,
)
from discord.app_commands import command, default_permissions
from discord.ext.commands import Cog
from discord.ui import Button

from ext.utils import timed_events, view_utils
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

TWTCH = (
    "https://seeklogo.com/images/T/"
    "twitch-tv-logo-51C922E0F0-seeklogo.com.png"
)


class ToggleButton(Button):
    """A Button to toggle the notifications settings."""

    def __init__(
        self, bot: Bot | PBot, db_key: str, value: bool, row: int = 0
    ) -> None:
        self.value: bool = value
        self.db_key: str = db_key  # The Database Key this button correlates to
        self.bot: Bot | PBot = bot

        style = discord.ButtonStyle.green if value else discord.ButtonStyle.red
        emoji: str = "🟢" if value else "🔴"  # None (Off)
        title: str = db_key.replace("_", " ").title()
        super().__init__(label=f"{title}", emoji=emoji, row=row, style=style)

    async def callback(self, interaction: Interaction) -> Message:
        """Set view value to button value"""

        await interaction.response.defer()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = f"""UPDATE notifications_settings SET {self.db_key} =
                    $1 WHERE channel_id = $2"""
                c = self.view.channel.id
                await connection.execute(q, not self.value, c)

        await self.bot.get_cog("Logs").update_cache()
        return await self.view.update()


class LogsConfig(BaseView):
    """Generic Config View"""

    def __init__(
        self, interaction: Interaction, channel: discord.TextChannel
    ) -> None:

        super().__init__(interaction)

        self.channel: discord.TextChannel = channel

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.interaction.delete_original_response()

    async def update(self, content: str = None) -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        q = """SELECT * FROM notifications_settings WHERE (channel_id) = $1"""
        qq = """INSERT INTO notifications_channels (guild_id, channel_id)
                VALUES ($1, $2)"""
        qqq = """INSERT INTO notifications_settings (channel_id) VALUES ($1)"""

        c = self.channel.id
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                if not (stg := await connection.fetchrow(q, c)):
                    await connection.execute(qq, self.interaction.guild.id, c)
                    await connection.execute(qqq, c)
                    return await self.update()

        e: Embed = Embed(color=0x7289DA, title="Notification Logs config")
        e.description = "Click the buttons below to toggle logging for events."

        row = 0
        for num, (k, v) in enumerate(sorted(stg.items())):
            if k == "channel_id":
                continue

            if num % 5 == 0:
                row += 1

            self.add_item(ToggleButton(self.bot, db_key=k, value=v, row=row))
        self.add_item(view_utils.Stop(row=4))
        await self.bot.reply(self.interaction, content, embed=e, view=self)


def do_footer(entry, embed):
    """Unified Footers."""
    if isinstance(user := entry.user, discord.Object):
        if (_ := entry.guild.get_member(entry.user)) is not None:
            user = _

    if user is None:
        return

    text = f"{user}\nID: {user.id}"
    if entry.reason:
        text += f"\nReason: {entry.reason}"
    embed.set_footer(text=text, icon_url=user.display_avatar.url)


def stringify_minutes(value: int) -> str:
    """Convert Minutes to less painful to read value"""
    match value:
        case 60:
            return "1 Hour"
        case 1440:
            return "1 Day"
        case 4320:
            return "3 Days"
        case 10080:
            return "7 Days"
        case _:
            logging.info(f"Unhandled archive duration, {value}")
            return value


def stringify_seconds(value: int) -> str:
    """Convert seconds to less painful to read value"""
    match value:
        case value if value < 60:
            return f"{value} Seconds"
        case 60:
            return "1 Minute"
        case 86400:
            return "1 Day"
        case 604800:
            return "7 Days"
        case _:
            logging.info(f"Unhandled Seconds: {value}")
            return f"{value} Seconds"


def stringify_mfa(value: discord.MFALevel) -> str:
    """Convert discord.MFALevel to human-readable string"""
    match value:
        case discord.MFALevel.disabled:
            return "Disabled"
        case discord.MFALevel.require_2fa:
            return "2-Factor Authentication Required"
        case _:
            logging.info(f"Could not parse value for MFALevel {value}")
            return value


def stringify_content_filter(value: discord.ContentFilter) -> str:
    """Convert Enum to human string"""
    match value:
        case discord.ContentFilter.all_members:
            return "Check All Members"
        case discord.ContentFilter.no_role:
            return "Check Un-roled Members"
        case discord.ContentFilter.disabled:
            return None


def stringify_notification_level(value: discord.NotificationLevel) -> str:
    """Convert Enum to human string"""
    match value:
        case discord.NotificationLevel.all_messages:
            return "All Messages"
        case discord.NotificationLevel.only_mentions:
            return "Mentions Only"
        case _:
            return value


def stringify_trigger_type(value: discord.AutoModRuleTriggerType) -> str:
    """Convert discord.AutModRuleTriggerType to human-readable string"""
    match value:
        case discord.AutoModRuleTriggerType.keyword:
            return "Keyword Mentioned"
        case discord.AutoModRuleTriggerType.keyword_preset:
            return "Keyword Preset Mentioned"
        case discord.AutoModRuleTriggerType.harmful_link:
            return "Harmful Links"
        case discord.AutoModRuleTriggerType.mention_spam:
            return "Mention Spam"
        case discord.AutoModRuleTriggerType.spam:
            return "Spam"
        case _:
            logging.info(f"Failed to parse AutoModRuleTriggerType {value}")
            return "Unknown"


def stringify_verification(value: discord.VerificationLevel) -> str:
    """Convert discord.VerificationLevel to human-readable string"""
    match value:
        case discord.VerificationLevel.none:
            return "None"
        case discord.VerificationLevel.low:
            return "Verified Email"
        case discord.VerificationLevel.medium:
            return "Verified Email, Registered 5 minutes"
        case discord.VerificationLevel.high:
            return "Verified Email, Registered 5 minutes, Member 10 Minutes"
        case discord.VerificationLevel.highest:
            return "Verified Phone"
        case _:
            logging.info(f"Failed to parse Verification Level {value}")
            return value


def do_perms(
    entry: discord.AuditLogEntry,
    permissions: list[discord.app_commands.AppCommandPermissions],
    embed: Embed,
) -> Embed:
    """Add a human-readable list of parsed permissions to an embed"""

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
                    mention = "All Channels: <id:browse>"
                else:
                    mention = f"<#{p.target.id}>"
            case _:
                mention = "?"
        embed.description += f"{'✅' if p.permission else '❌'} {mention}\n"
    return embed


class Logs(Cog):
    """Set up Server Logs"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        LogsConfig.bot = bot

    async def cog_load(self) -> None:
        """When the cog loads"""
        await self.update_cache()

    # We don't need to db call every single time an event happens, just when
    # config is updated So we cache everything and store it in memory
    # instead for performance and sanity reasons.
    async def update_cache(self) -> None:
        """Get the latest database information and load it into memory"""
        q = """SELECT * FROM notifications_channels LEFT OUTER JOIN
            notifications_settings ON notifications_channels.channel_id
            = notifications_settings.channel_id"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                self.bot.notifications_cache = await connection.fetch(q)

    async def dispatch(
        self,
        channels: list[TextChannel],
        e: list[Embed],
        view: discord.ui.View = None,
    ):
        """Bulk dispatch messages to their destinations"""

        for ch in channels:
            try:
                await ch.send(embeds=e, view=view)
            except discord.HTTPException:
                continue

    def get_channels(self, guild, filters: list[str]):
        """Filter down to the required channels"""
        c = self.bot.notifications_cache
        channels = [i for i in c if i["guild_id"] == guild.id]
        for setting in filters:
            channels = [i for i in channels if i[setting]]

        channels = [self.bot.get_channel(i["channel_id"]) for i in channels]
        channels = [i for i in channels if i is not None]
        return channels

    # Join messages
    @Cog.listener()
    async def on_member_join(self, member: Member) -> None:
        """Event handler to Dispatch new member information
        for servers that request it"""
        if not (channels := self.get_channels(member.guild, ["joins"])):
            return

        # Extended member join information.
        e: Embed = Embed(colour=0x7289DA, title="Member Joined")
        e.set_author(
            name=f"{member.name} {member.id}",
            icon_url=member.display_avatar.url,
        )

        def onboard() -> str:
            """Get the member's onboarding status"""
            if member.flags.completed_onboarding:
                return "Completed"
            elif member.flags.started_onboarding:
                return "Started"
            else:
                return "Not Started"

        ts = timed_events.Timestamp(member.created_at).date_relative
        e.description = (
            f"{member.mention}\n"
            f"**Shared Servers**: {len(member.mutual_guilds)}\n"
            f"**Account Created**: {ts}\n"
            f"**Onboarding Status**?: {onboard()}"
        )

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
            e.add_field(name="Flags", value=", ".join(flags))
        await self.dispatch(channels, [e])

    @Cog.listener()
    async def on_user_update(self, bf: User, af: User):
        """Triggered when a user updates their profile"""
        guilds = [i.id for i in self.bot.guilds if i.get_member(af.id)]

        n = self.bot.notifications_cache
        channels = [i for i in n if i["guild_id"] in guilds and i["users"]]
        channels = [self.bot.get_channel(i) for i in channels]
        channels = [i for i in channels if i is not None]
        if channels:
            return

        before: Embed = Embed(colour=Colour.dark_gray(), description="")
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=discord.utils.utcnow(),
            description="",
        )

        if bf.name != af.name:
            before.description += f"**Name**: {bf.name}\n"
            after.description += f"**Name**: {af.name}\n"

        if bf.discriminator != af.discriminator:
            before.description += f"**Discriminator**: {bf.discriminator}\n"
            after.description += f"**Discriminator**: {af.discriminator}\n"

        if bf.display_avatar.url != af.display_avatar.url:
            b = bf.display_avatar.url
            before.description += f"**Avatar**: [Link]({b})\n"
            if b:
                before.set_thumbnail(url=b)
            a = af.display_avatar.url
            if a:
                after.set_thumbnail(url=a)
            after.description += f"**Avatar**: [Link]({a})\n"

        return await self.dispatch(channels, [before, after])

    def parse_channel_overwrites(self, entry, ow_pairs, e: Embed):
        """Parse a list of Channel Overwrites & append data to embed"""
        ow_pairs: list[tuple[discord.Object, discord.PermissionOverwrite]]

        output = ""
        for user_or_role, perms in ow_pairs:
            if isinstance(user_or_role, discord.Object):
                if (target := self.bot.get_user(user_or_role.id)) is None:
                    target = entry.guild.get_role(user_or_role.id)
            else:
                target = user_or_role

            if target is not None:
                output += f"{target.mention}: "
            else:
                output += f"ID# {user_or_role.id}: "

            output += ", ".join(f"✅ {k}" for (k, v) in perms if v)
            # False but not None.
            output += ", ".join(f"❌ {k}" for (k, v) in perms if v is False)
            output += "\n\n"
        e.add_field(name="Permission Overwrites", value=output)

    async def handle_channel_create(self, entry: discord.AuditLogEntry):
        """Handler for when a channel is created"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {k: v for k, v in entry.changes.after if k != "type"}
        c_type = str(entry.target.type).replace("_", " ").title()
        e = Embed(
            colour=Colour.orange(),
            title=f"{c_type} Channel Created",
            timestamp=entry.created_at,
        )

        do_footer(entry, e)
        t = entry.target
        e.description = f"<#{t.id}> {t.name} ({t.id})\n\n"

        if _ := changes.pop("name", False):
            pass  # Name is found in entry.target anyway.

        if bitrate := changes.pop("bitrate", False):
            e.description += f"**Bitrate**: {math.floor(bitrate/ 1000)}kbps"

        if max_users := changes.pop("user_limit", False):
            e.description += f"**User Limit**: {max_users}\n"

        if archive := changes.pop("default_auto_archive_duration", False):
            s = stringify_minutes(archive)
            e.description += f"**Thread Archiving**: {s}\n"

        if order := changes.pop("position", False):
            e.description += f"**Position**: {order}\n"

        if _ := changes.pop("nsfw", False):
            e.description += "**NSFW**: `True`\n"

        if region := changes.pop("rtc_region", False):
            e.description += f"**Region**: {region}\n"

        if topic := changes.pop("topic", False):
            e.add_field(name="Topic", value=topic, inline=False)

        if slowmode := changes.pop("slowmode_delay", False):
            e.description += f"**Slowmode**: {stringify_seconds(slowmode)}\n"

        # Enums
        if vq := changes.pop("video_quality_mode", False):
            e.description += f"**Video Quality**: {vq.name.title()}\n"

        # Flags
        if flags := changes.pop("flags", False):
            if flags.pinned:
                e.description += "**Thread Pinned**: `True`\n"
            if flags.require_tag:
                e.description += "**Force Tags?**: `True`\n"

        # Permission Overwrites
        if overwrites := changes.pop("overwrites", False):
            self.parse_channel_overwrites(entry, overwrites, e)

        if changes:
            logging.info(f"Channel Create Changes Remain: {changes}")
        return await self.dispatch(channels, [e])

    # TODO: Move up
    async def handle_channel_update(self, entry: discord.AuditLogEntry):
        """Handler for when a channel is updated"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        if _ := changes.pop("type", False):
            pass  # Get from target object.

        c_type = str(entry.target.type).replace("_", " ").title()
        before = Embed(
            colour=Colour.dark_gray(),
            title=f"{c_type} Channel Updated",
            description="",
        )

        t = entry.target
        before.description = f"<#{t.id}> {t.name} ({t.id})\n\n"

        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if key := changes.pop("name", False):
            before.description += f"**Name**: {key['before']}\n"
            after.description += f"**Name**: {key['after']}\n"

        if key := changes.pop("type", False):
            if (b := key["before"]) is not None:
                before.description += f"**Type**: {b.name.title()}\n"
            if (a := key["after"]) is not None:
                after.description += f"**Type**: {a.name.title()}\n"

        if key := changes.pop("bitrate", False):
            b = key["before"]
            a = key["after"]
            bf = f"{math.floor(b / 1000)}kbps" if b else None
            af = f"{math.floor(a / 1000)}kbps" if a else None
            before.description += f"**Bitrate**: {bf}\n"
            after.description += f"**Bitrate**: {af}\n"

        if key := changes.pop("user_limit", False):
            if key["before"]:
                before.description += f"**User Limit**: {key['before']}\n"
            if key["after"]:
                after.description += f"**User Limit**: {key['after']}\n"

        if key := changes.pop("default_auto_archive_duration", False):
            s = stringify_minutes(key["before"])
            before.description += f"**Thread Archiving**: {s}\n"
            s = stringify_minutes(key["after"])
            after.description += f"**Thread Archiving**: {s}\n"

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
            before.add_field(name="Topic", value=key["before"], inline=False)
            after.add_field(name="Topic", value=key["after"], inline=False)

        if key := changes.pop("slowmode_delay", False):
            sm_bf = stringify_seconds(key["before"])
            sm_af = stringify_seconds(key["after"])
            before.description += f"**Create New Threads Slowmode**: {sm_bf}\n"
            after.description += f"**Create New Threads Slowmode**: {sm_af}\n"

        if key := changes.pop("default_reaction_emoji", False):
            b = key["before"]
            a = key["after"]
            before.description += f"**Default Reaction Emoji**: {b}\n"
            after.description += f"**Default Reaction Emoji**: {a}\n"

        if key := changes.pop("default_thread_slowmode_delay", False):
            sm_bf = stringify_seconds(key["before"])
            sm_af = stringify_seconds(key["after"])
            before.description += f"**Thread Reply Slowmode**: {sm_bf}\n"
            after.description += f"**Thread Reply Slowmode**: {sm_af}\n"

        # Enums
        if key := changes.pop("video_quality_mode", False):
            o = key["before"].name.title() if key["before"] else "Auto"
            before.description += f"**Video Quality**: {o}\n"
            o = key["after"].name.title() if key["before"] else "Auto"
            after.description += f"**Video Quality**: {o}\n"

        # Flags
        if key := changes.pop("flags", False):
            bf_flags: discord.ChannelFlags = key["before"]
            af_flags: discord.ChannelFlags = key["after"]

            if isinstance(entry.target, discord.Thread):
                if isinstance(entry.target.parent, discord.ForumChannel):
                    if bf_flags is not None:
                        b = bf_flags.pinned
                        before.description += f"**Thread Pinned**: `{b}`\n"
                        b = bf_flags.require_tag
                        before.description += f"**Force Tags?**: `{b}`\n"
                    if af_flags is not None:
                        a = af_flags.pinned
                        after.description += f"**Thread Pinned**: `{a}`\n"
                        a = af_flags.require_tag
                        after.description += f"**Force Tags?**: `{a}`\n"

        if key := changes.pop("available_tags", False):
            if new := [i for i in key["after"] if i not in key["before"]]:
                txt = ""
                for i in new:
                    txt += f"{i.emoji} {i.name}"
                    if i.moderated:
                        txt += " (Mod Only)"
                after.add_field(name="Tags Added", value=txt)

            if removed := [i for i in key["before"] if i not in key["after"]]:
                txt = ""
                for i in removed:
                    txt += f"{i.emoji} {i.name}"
                    if i.moderated:
                        txt += " (Mod Only)"
                before.add_field(name="Tags Removed", value=txt)

        # Permission Overwrites
        if key := changes.pop("overwrites", False):
            self.parse_channel_overwrites(entry, key["before"], before)
            self.parse_channel_overwrites(entry, key["after"], after)

        if changes:
            logging.info(f"Channel Update Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_channel_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a channel is deleted"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {k: v for k, v in entry.changes.before}

        if not (c_type := changes.pop("type", False)):
            c_type = str(entry.target.type).replace("_", " ").title()

        e = Embed(
            colour=Colour.dark_orange(),
            title=f"{c_type}Channel Deleted",
            timestamp=entry.created_at,
        )

        do_footer(entry, e)

        t = entry.target
        if name := changes.pop("name", False):
            e.description = f"<#{t.id}> {name} ({t.id})\n\n"
        else:
            e.description = f"<#{t.id}> ({t.id})\n\n"

        if bitrate := changes.pop("bitrate", False):
            e.description += f"**Bitrate**: {math.floor(bitrate / 1000)}kbps\n"

        if max_users := changes.pop("user_limit", False):
            e.description += f"**User Limit**: {max_users}"

        if archive := changes.pop("default_auto_archive_duration", False):
            s = stringify_minutes(archive)
            e.description += f"**Thread Archiving**: {s}\n"

        if position := changes.pop("position", False):
            e.description += f"**Position**: {position}\n"

        if _ := changes.pop("nsfw", False):
            e.description += "**NSFW**: `True`\n"

        if region := changes.pop("rtc_region", False):
            e.description += f"**Region**: {region}\n"

        if topic := changes.pop("topic", False):
            e.add_field(name="Topic", value=topic, inline=False)

        if slowmode := changes.pop("slowmode_delay", False):
            e.description += f"**Slowmode**: {stringify_seconds(slowmode)}\n"

        # Enums
        if vq := changes.pop("video_quality_mode", False):
            e.description += f"**Video Quality**: {vq.name.title()}"

        if tags := changes.pop("available_tags", False):
            logging.info(f"Add tags: {tags} for deleted forum channel.")

        # Flags
        if flags := changes.pop("flags", False):
            if flags.pinned:
                e.description += "**Thread Pinned**: `True`\n"
            if flags.require_tag:
                e.description += "**Force Tags?**: `True`\n"

        # Permission Overwrites
        if overwrites := changes.pop("overwrites", False):
            self.parse_channel_overwrites(entry, overwrites, e)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_guild_update(self, entry: discord.AuditLogEntry):
        """Handler for When a guild is updated."""
        if not (channels := self.get_channels(entry.guild, ["server"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(colour=Colour.dark_gray(), description="")
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        # Author Icon
        if icon := changes.pop("icon", False):
            if icon["before"] is None:
                bf_ico = entry.guild.icon.url
                before.description += "**Icon**: None\n"
            else:
                bf_ico = icon["before"].url
                before.description += f"**Icon**: [link]({bf_ico})\n"

            if icon["after"] is None:
                af_ico = entry.guild.icon.url
                after.description += "**Icon**: None\n"
            else:
                af_ico = icon["after"].url
                after.description += f"**Icon**: [link]({af_ico})\n"
        else:
            bf_ico = af_ico = entry.guild.icon.url

        if key := changes.pop("name", False):
            before.set_author(name=key["before"], icon_url=bf_ico)
            after.set_author(name=key["after"], icon_url=af_ico)
            before.description += f"**Name**: {key['before']}\n"
            after.description += f"**Name**: {key['after']}\n"
        else:
            before.set_author(
                name=f"{entry.guild.name} Updated", icon_url=bf_ico
            )

        if key := changes.pop("owner", False):
            old_owner = key["before"].mention if key["before"] else None
            before.description += f"**Owner**: {old_owner}\n"
            new_owner = key["after"].mention if key["after"] else None
            after.description += f"**Owner**: {new_owner}\n"

        if key := changes.pop("public_updates_channel", False):
            bf = key["before"].mention if key["before"] else None
            before.description += f"**Announcement Channel**: {bf}\n"
            af = key["after"].mention if key["after"] else None
            after.description += f"**Announcement Channel**: {af}\n"

        if key := changes.pop("afk_channel", False):
            bf = key["before"].mention if key["before"] else None
            before.description += f"**AFK Channel**: {bf}\n"
            af = key["after"].mention if key["after"] else None
            after.description += f"**AFK Channel**: {af}\n"

        if key := changes.pop("rules_channel", False):
            bf = key["before"].mention if key["before"] else None
            before.description += f"**Rules Channel**: {bf}\n"
            af = key["after"].mention if key["after"] else None
            after.description += f"**Rules Channel**: {af}\n"

        if key := changes.pop("system_channel", False):
            bf_ch = key["before"].mention if key["before"] else None
            before.description += f"**System Channel**: {bf_ch}\n"
            af_ch = key["after"].mention if key["after"] else None
            after.description += f"**System Channel**: {af_ch}\n"

        if key := changes.pop("widget_channel", False):
            bf_ch = key["before"].mention if key["before"] else None
            before.description += f"**Widget Channel**: {bf_ch}\n"
            af_ch = key["after"].mention if key["after"] else None
            after.description += f"**Widget Channel**: {af_ch}\n"

        if key := changes.pop("afk_timeout", False):
            s = stringify_seconds(key["before"])
            before.description += f"AFK Timeout: {s}\n"
            s = stringify_seconds(key["after"])
            after.description += f"AFK Timeout: {s}\n"

        if key := changes.pop("default_notifications", False):
            s = stringify_notification_level(key["before"])
            before.description += f"Default Notifications: {s}\n"
            s = stringify_notification_level(key["after"])
            after.description += f"Default Notifications: {s}\n"

        if key := changes.pop("explicit_content_filter", False):
            s = stringify_content_filter(key["before"])
            before.description += f"**Explicit Content Filter**: {s}\n"
            s = stringify_content_filter(key["after"])
            after.description += f"**Explicit Content Filter**: {s}\n"

        if key := changes.pop("mfa_level", False):
            s = stringify_mfa(key["before"])
            before.description += f"**MFA Level**: {s}\n"
            s = stringify_mfa(key["after"])
            after.description += f"**MFA Level**: {s}\n"

        if key := changes.pop("verification_level", False):
            s = stringify_verification(key["before"])
            before.description += f"**Verification Level**: {s}\n"
            s = stringify_verification(key["after"])
            after.description += f"**Verification Level**: {s}\n"

        if key := changes.pop("vanity_url_code", False):
            before.description += (
                f"**Invite URL**: [{key['before']}]"
                f"(https://discord.gg/{key['before']})"
            )
            after.description += (
                f"**Invite URL**: [{key['after']}]"
                f"(https://discord.gg/{key['after']})"
            )

        if key := changes.pop("description", False):
            before.add_field(name="**Description**", value=key["before"])
            after.add_field(name="**Description**", value=key["after"])

        if key := changes.pop("prune_delete_days", None):

            bf = key["before"] + " days" if key["before"] else "Never"
            af = key["after"] + " days" if key["after"] else "Never"

            before.description += f"**Kick Inactive**: {bf}\n"
            after.description += f"**Kick Inactive**: {af}\n"

        if key := changes.pop("widget_enabled", None):
            before.description += f"**Widget Enabled**: {key['before']}\n"
            after.description += f"**Widget Enabled**: {key['after']}\n"

        if key := changes.pop("preferred_locale", None):
            before.description += f"**Language**: {key['before']}\n"
            after.description += f"**Language**: {key['after']}\n"

        if key := changes.pop("splash", None):
            if key["before"]:
                u = key["before"].url
                before.description += f"**Invite Image**: [link]({u})\n"
                if u:
                    before.set_image(url=u)
            if key["after"]:
                u = key["after"].url
                after.description += f"**Invite Image**: [link]({u})\n"
                if u:
                    after.set_image(url=u)

        if key := changes.pop("discovery_splash", None):
            if key["before"]:
                b = key["before"].url
                before.description += f"**Discovery Image**: [link]({b})\n"
                before.set_image(url=b)
            else:
                before.description += "**Discovery Image**: None"

            if key["after"]:
                a = key["after"].url
                after.description += f"**Discovery Image**: [link]({a})\n"
                after.set_image(url=a)
            else:
                after.description += "**Discovery Image**: None"

        if key := changes.pop("banner", None):
            if key["before"]:
                b = key["before"].url
                before.description += f"**Banner**: [link]({b})\n"
                before.set_image(url=b)
            else:
                before.description += "**Banner**: None\n"

            if key["after"]:
                a = key["after"].url
                after.description += f"**Banner**: [link]({a})\n"
                after.set_image(url=a)
            else:
                after.description += "**Banner**: None\n"

        if key := changes.pop("system_channel_flags", None):
            bf: discord.SystemChannelFlags = key["before"]
            af: discord.SystemChannelFlags = key["after"]

            b = bf.guild_reminder_notifications
            a = af.guild_reminder_notifications
            if a != b:
                o = "on" if b else "off"
                before.description += f"**Setup Tips**: {o}\n"
                o = "on" if a else "off"
                after.description += f"**Setup Tips**: {o}\n"

            if (b := bf.join_notifications) != (a := af.join_notifications):
                o = "on" if b else "off"
                before.description += f"**Join Notifications**: {o}\n"
                o = "on" if a else "off"
                after.description += f"**Join Notifications**: {o}\n"

            b = bf.join_notification_replies
            a = af.join_notification_replies
            if a != b:
                o = "on" if b else "off"
                before.description += f"**Join Stickers**: {o}\n"
                o = "on" if a else "off"
                after.description += f"**Join Stickers**: {o}\n"

            b = bf.premium_subscription
            a = af.premium_subscriptions
            if a != b:
                o = "on" if b else "off"
                before.description += f"**Boost Notifications**: {o}\n"
                o = "on" if a else "off"
                after.description += f"**Boost Notifications**: {o}\n"

            b = bf.role_subscription_purchase_notifications
            a = af.role_subscription_purchase_notifications
            if a != b:
                o = "on" if b else "off"
                before.description += f"**Role Subscriptions**: {o}\n"
                o = "on" if a else "off"
                after.description += f"**Role Subscriptions**: {o}\n"

            b = bf.role_subscription_purchase_notification_replies
            a = af.role_subscription_purchase_notification_replies
            if a != b:
                o = "on" if b else "off"
                before.description += f"**Role Sub Stickers**: {o}\n"
                o = "on" if a else "off"
                after.description += f"**Role Sub Stickers**: {o}\n"

        if changes:
            logging.info(f"Guild Update Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_thread_create(self, entry: discord.AuditLogEntry):
        """Handler for when a thread is created"""
        if not (channels := self.get_channels(entry.guild, ["threads"])):
            return

        changes = {}
        for k, v in entry.changes.after:
            changes[k] = {"after": v}

        for _ in ["name", "type"]:
            if changes.pop(_, None):
                pass  # Get from target object.

        c_type = str(entry.target.type).replace("_", " ").title()
        e: Embed = Embed(
            colour=Colour.light_gray(),
            title=f"{c_type} Created",
            timestamp=entry.created_at,
        )
        e.description = f"<#{entry.target.id}> ({entry.target.id})\n\n"
        do_footer(entry, e)

        for k in ["invitable", "locked", "archived"]:
            if key := changes.pop(k, False):
                if key["after"]:
                    e.description += f"**{k.title()}**: `True`\n"

        if key := changes.pop("auto_archive_duration", False):
            s = stringify_minutes(key["after"])
            e.description += f"**Inactivity Archive**: {s}\n"

        if key := changes.pop("applied_tags", False):
            txt = ", ".join([f"{i.emoji} {i.name}" for i in key["after"]])
            e.add_field(name="Tags", value=txt)

        if key := changes.pop("flags", False):
            af: discord.ChannelFlags = key["after"]
            if af.pinned:
                e.description += "**Thread Pinned**: `True`\n"
            if af.require_tag:
                e.description += "**Force Tags?**: `True`\n"

        if key := changes.pop("slowmode_delay", False):
            if key["after"]:
                s = stringify_seconds(key["after"])
                e.description += f"**Slow Mode**: {s}"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_thread_update(self, entry: discord.AuditLogEntry):
        """Handler for when threads are updated"""
        if not (channels := self.get_channels(entry.guild, ["threads"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        if _ := changes.pop("type", False):
            pass  # Get from target object.

        c_type = str(entry.target.type).replace("_", " ").title()
        before: Embed = Embed(
            colour=Colour.dark_gray(),
            title=f"{c_type} Updated",
            description="",
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if isinstance(thread := entry.target, discord.Object):
            thread: discord.Thread = entry.guild.get_thread(thread.id)

        if thread is None:
            before.description = f"Thread ID# {entry.target.id}\n\n"
        else:
            before.description = f"{thread.mention}\n\n"

        for k in ["name", "invitable", "locked", "archived"]:
            if key := changes.pop(k, False):
                before.description += f"**{k.title()}**: {key['before']}\n"
                after.description += f"**{k.title()}**: {key['after']}\n"

        if key := changes.pop("auto_archive_duration", False):
            s = stringify_minutes(key["before"])
            before.description += f"**Inactivity Archive**: {s}\n"
            s = stringify_minutes(key["after"])
            after.description += f"**Inactivity Archive**: {s}\n"

        if key := changes.pop("applied_tags", False):
            b = key["before"]
            a = key["after"]
            bf: list[discord.ForumTag] = [f"{i.emoji} {i.name}" for i in b]
            af: list[discord.ForumTag] = [f"{i.emoji} {i.name}" for i in a]

            if new := [i for i in af if i not in bf]:
                after.add_field(name="Tags Removed", value=", ".join(new))
            if gone := [i for i in bf if i not in af]:
                after.add_field(name="Tags Added", value=", ".join(gone))

        if key := changes.pop("flags", False):
            bf: discord.ChannelFlags = key["before"]
            af: discord.ChannelFlags = key["after"]

            if bf is not None:
                before.description += f"**Thread Pinned**: {bf.pinned}\n"
                before.description += f"**Force Tags?**: {bf.require_tag}\n"
            if af is not None:
                after.description += f"**Thread Pinned**: {af.pinned}\n"
                after.description += f"**Force Tags?**: {af.require_tag}\n"

        if key := changes.pop("slowmode_delay", False):
            s = stringify_seconds(key["before"])
            before.description += f"**Slow Mode**: {s}\n"
            stringify_seconds(key["after"])
            after.description += f"**Slow Mode**: {s}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")
        return await self.dispatch(channels, [before, after])

    async def handle_thread_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a thread is deleted"""
        if not (channels := self.get_channels(entry.guild, ["threads"])):
            return

        changes = {k: v for k, v in entry.changes.before}
        if _ := changes.pop("type", False):
            pass  # Get from target object.

        c_type = str(entry.target.type).replace("_", " ").title()
        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title=f"{c_type} Deleted",
            description="",
        )
        e.description = f"<#{entry.target.id}> ({entry.target.id})"
        do_footer(entry, e)

        for k in ["name", "invitable", "locked", "archived"]:
            if key := changes.pop(k, False):
                e.description += f"**{k.title()}**: {key}\n"

        if archive := changes.pop("auto_archive_duration", False):
            s = stringify_minutes(archive)
            e.description += f"**Inactivity Archive**: {s}\n"

        if tags := changes.pop("applied_tags", False):
            e.add_field(
                name="Tags",
                value=", ".join([f"{i.emoji} {i.name}" for i in tags]),
            )

        if flags := changes.pop("flags", False):
            if flags.pinned:
                e.description += "**Thread Pinned**: `True`\n"
            if flags.require_tag:
                e.description += "**Force Tags?**: `True`\n"

        if slowmode := changes.pop("slowmode_delay", False):
            e.description += f"**Slow Mode**: {stringify_seconds(slowmode)}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_stage_create(self, entry: discord.AuditLogEntry):
        """Handler for when a stage instance is created"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {k: v for k, v in entry.changes.after}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Stage Instance Started",
            timestamp=entry.created_at,
        )
        do_footer(entry, e)

        t = entry.target
        # A Stage *INSTANCE* happens on a stage *CHANNEL*
        if isinstance(entry.target, discord.Object):
            stage: discord.StageChannel = entry.guild.get_channel(t.id)
        else:
            instance: discord.StageInstance = entry.target
            stage = instance.channel

        if stage is None:
            e.description = f"Channel #{entry.target.id}\n\n"
        else:
            e.description = f"{stage.mention}\n\n"

        if topic := changes.pop("topic", False):
            e.add_field(name="Topic", value=topic, inline=False)

        if privacy_level := changes.pop("privacy_level", False):
            e.description += f"**Privacy**: {privacy_level}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_stage_update(self, entry: discord.AuditLogEntry):
        """Handler for when a stage instance is updated"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Stage Instance Updated",
            description="",
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )

        do_footer(entry, after)

        t = entry.target
        # A Stage *INSTANCE* happens on a stage *CHANNEL*
        if isinstance(entry.target, discord.Object):
            stage: discord.StageChannel = entry.guild.get_channel(t.id)
        else:
            instance: discord.StageInstance = entry.target
            stage = instance.channel

        if stage is not None:
            before.desription = f"Channel #{entry.target.id}\n\n"
        else:
            before.description = f"{stage.mention}\n\n"

        if key := changes.pop("topic", False):
            before.add_field(name="Topic", value=key["before"], inline=False)
            after.add_field(name="Topic", value=key["after"], inline=False)

        if key := changes.pop("privacy_level", False):
            before.description += f"**Privacy**: {key['before']}\n"
            after.description += f"**Privacy**: {key['after']}\n"
        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")
        return await self.dispatch(channels, [before, after])

    async def handle_stage_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a stage instance is deleted"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {k: v for k, v in entry.changes.before}
        e: Embed = Embed(
            colour=Colour.dark_gray(), title="Stage Instance Ended"
        )
        do_footer(entry, e)

        # A Stage *INSTANCE* happens on a stage *CHANNEL*
        t = entry.target
        if isinstance(entry.target, discord.Object):
            stage: discord.StageChannel = entry.guild.get_channel(t.id)
        else:
            instance: discord.StageInstance = entry.target
            stage = instance.channel

        if stage is None:
            e.description = f"Channel #{entry.target.id}\n\n"
        else:
            e.description = f"{stage.mention}\n\n"

        if topic := changes.pop("topic", False):
            e.add_field(name="Topic", value=topic, inline=False)

        if privacy := changes.pop("privacy_level", False):
            e.description += f"**Privacy**: {privacy}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_message_pin(self, entry: discord.AuditLogEntry):
        """Handler for when messages are pinned"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Message Pinned",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        x = entry.extra
        t = entry.target
        msg = x.channel.get_partial_message(x.message_id)
        e.description = (
            f"{x.channel.mention} {t.mention}\n\n"
            f"[Jump to Message]({msg.jump_url})"
        )

        return await self.dispatch(channels, [e])

    async def handle_message_unpin(self, entry: discord.AuditLogEntry):
        """Handler for when messages are unpinned"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Message Unpinned",
            timestamp=entry.created_at,
        )
        do_footer(entry, e)

        x = entry.extra
        t = entry.target
        msg = entry.extra.channel.get_partial_message(x.message_id)
        e.description = (
            f"{x.channel.mention} {t.mention}"
            f"\n\n[Jump to Message]({msg.jump_url})"
        )

        return await self.dispatch(channels, [e])

    async def handle_overwrite_create(self, entry: discord.AuditLogEntry):
        """Handler for when a channel has new permission overwrites created"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        af = entry.changes.after
        changes = {k: v for k, v in af if k not in ["id", "type"]}
        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Channel Permissions Created",
            timestamp=entry.created_at,
        )
        do_footer(entry, e)

        t = entry.target
        e.description = f"<#{t.id}> {t.name} ({t.id})\n\n"
        x = entry.extra
        if isinstance(entry.extra, discord.Role):
            e.description += f"<@&{x.id}> {x.name} (Role #{x.id})"
        elif isinstance(entry.extra, discord.User | discord.Member):
            e.description += f"<@{x.id}> {x.name} (User #{x.extra.id})"
        else:
            logging.info(f"extra for overwrite_create is {x} ({type(x)})")

        if deny := changes.pop("deny", False):
            if fmt := [f"❌ {k}" for k, v in iter(deny) if v]:
                e.add_field(name="Denied Perms", value=", ".join(fmt))

        if allow := changes.pop("allow", False):
            if fmt := [f"✅ {k}" for k, v in iter(allow) if v]:
                e.add_field(name="Allowed Perms", value=", ".join(fmt))

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_overwrite_update(self, entry: discord.AuditLogEntry):
        """Handler for when a channels' permission overwrites are updated"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        c_type = str(entry.target.type).title()
        before: Embed = Embed(
            colour=Colour.dark_gray(),
            title=f"{c_type} Channel Permissions Updated",
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        t = entry.target
        x = entry.extra
        before.description = f"<#{t.id}> {t.name} ({t.id})"
        match type(entry.extra):
            case discord.Role:
                before.description += f"<@&{x.id}> {x.name} (Role #{x.id})"
            case discord.Member:
                before.description += f"<@{x.id}> {x.name} (User #{x.id})"
            case _:
                logging.info(f"extra for overwrite_update is {x} ({type(x)})")

        if key := changes.pop("deny", False):
            a = key["after"]
            b = key["before"]

            if new_deny := [f"❌ {i[0]}" for i in a if i not in b and i[1]]:

                after.add_field(
                    name="Denied Permissions Added", value=", ".join(new_deny)
                )

            if reset_deny := [f"🔄 {i[0]}" for i in b if i not in a and i[1]]:
                before.add_field(
                    name="Denied Permissions Reset",
                    value="\n".join(reset_deny),
                )

        if key := changes.pop("allow", False):
            a = key["after"]
            b = key["before"]

            if new_allow := [f"✅ {i[0]}" for i in a if i not in b and i[1]]:
                after.add_field(
                    name="Allowed Permissions Added",
                    value=", ".join(new_allow),
                )

            if reset_allow := [f"🔄 {i[0]}" for i in b if i not in a and i[1]]:
                before.add_field(
                    name="Allowed Permissions Reset",
                    value="\n".join(reset_allow),
                )

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_overwrite_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a permission overwrite for a channel is deleted"""
        if not (channels := self.get_channels(entry.guild, ["channels"])):
            return

        bf = entry.changes.before
        changes = {k: v for k, v in bf if k not in ["id", "type"]}
        c_type = str(entry.target.type).title()
        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title=f"{c_type} Channel Permissions Removed",
            timestamp=discord.utils.utcnow(),
        )
        do_footer(entry, e)

        t = entry.target
        x = entry.extra
        e.description = f"<#{t.id}> {t.name} ({t.id})\n\n"
        match type(entry.extra):
            case discord.Role:
                e.description += f"<@&{x.id}> {x.name} (Role #{x.id})"
            case discord.Member:
                e.description += f"<@{x.id}> {x.name} (User #{x.id})"
            case _:
                logging.info(f"extra for overwrite_delete is {x} ({type(x)})")

        if deny := changes.pop("deny", False):
            if fmt := [f"🔄 {k}" for k, v in iter(deny) if v]:
                e.add_field(
                    name="Denied Permissions Reset", value="\n".join(fmt)
                )

        if allow := changes.pop("allow", False):
            if fmt := [f"🔄 {k}" for k, v in iter(allow) if v]:
                e.add_field(
                    name="Allowed Permissions Reset", value="\n".join(fmt)
                )

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_event_create(self, entry: discord.AuditLogEntry):
        """Handler for when a scheduled event is created"""
        if not (channels := self.get_channels(entry.guild, ["events"])):
            return

        changes = {k: v for k, v in entry.changes.after}
        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Scheduled Event Created",
            timestamp=entry.created_at,
        )
        e.description = ""
        do_footer(entry, e)

        for attr in ["name", "status"]:
            if key := changes.pop(attr, False):
                e.description += f"**{attr.title()}**: {key}\n"

        if image := changes.pop("cover_image", False):
            e.set_image(url=image.url)

        if description := changes.pop("description", False):
            e.add_field(
                name="Event Description", value=description, inline=False
            )

        if privacy := changes.pop("privacy_level", False):
            e.description += f"**Privacy**: {privacy}\n"

        location: str = changes.pop("location", {})
        channel: discord.channel.VocalGuildChannel = changes.pop("channel", {})

        if entity := changes.pop("entity_type", False):
            match entity:
                case (
                    discord.EntityType.voice
                    | discord.EntityType.stage_instance
                ):
                    e.description += f"**Location**: {channel.mention}"
                case discord.EntityType.external:
                    try:
                        e.description += f"**Location**: {location}"
                    except AttributeError:
                        e.description += "**Location**: Unknown"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_event_update(self, entry: discord.AuditLogEntry):
        """Handler for when a scheduled event is updated"""
        if not (channels := self.get_channels(entry.guild, ["events"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Scheduled Event Updated",
            description="",
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        for attr in ["name", "status"]:
            if key := changes.pop(attr, False):
                before.description += f"**{attr.title()}**: {key['before']}\n"
                after.description += f"**{attr.title()}**: {key['after']}\n"

        if image := changes.pop("cover_image", False):
            if image["before"] is not None:
                before.set_image(url=image["before"].url)
            if image["after"] is not None:
                after.set_image(url=image["after"].url)

        if key := changes.pop("description", False):
            before.add_field(name="Event Description", value=key["before"])
            after.add_field(name="Event Description", value=key["after"])

        if key := changes.pop("privacy_level", False):
            before.description += f"**Privacy**: {key['before']}\n"
            after.description += f"**Privacy**: {key['after']}\n"

        location: dict[str, str] = changes.pop("location", {})
        channel: changes.pop("channel", None)

        if key := changes.pop("entity_type", False):
            match key["before"]:
                case (
                    discord.EntityType.voice
                    | discord.EntityType.stage_instance
                ):
                    c_bf = channel["before"].mention
                    before.description += f"**Location**: {c_bf}"
                case discord.EntityType.external:
                    before.description += f"**Location**: {location['before']}"

            match key["after"]:
                case (
                    discord.EntityType.voice
                    | discord.EntityType.stage_instance
                ):
                    c_af = channel["after"].mention
                    after.description += f"**Location**: {c_af}"
                case discord.EntityType.external:
                    after.description += f"**Location**: {location['after']}"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_event_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a scheduled event is deleted"""
        if not (channels := self.get_channels(entry.guild, ["events"])):
            return

        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Scheduled Event Deleted",
            description="",
        )
        do_footer(entry, e)
        e.description = ""

        for attr in ["name", "status"]:
            if key := changes.pop(attr, False):
                e.description += f"**{attr.title()}**: {key}\n"

        if image := changes.pop("cover_image", False):
            e.set_image(url=image.url)

        if description := changes.pop("description", False):
            e.add_field(name="Event Description", value=description)

        if privacy := changes.pop("privacy_level", False):
            e.description += f"**Privacy**: {privacy}\n"

        location: str = changes.pop("location", {})
        channel: discord.channel.VocalGuildChannel = changes.pop("channel", {})

        if entity := changes.pop("entity_type", False):
            match entity:
                case (
                    discord.EntityType.voice
                    | discord.EntityType.stage_instance
                ):
                    e.description += f"**Location**: {channel.mention}"
                case discord.EntityType.external:
                    e.description += f"**Location**: {location}"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_kick(self, entry: discord.AuditLogEntry):
        """Handler for when a member is kicked"""
        if not (channels := self.get_channels(entry.guild, ["kicks"])):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="User Kicked",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if isinstance(target := entry.target, discord.Object):
            target: User = self.bot.get_user(target.id)

        if target is not None:
            e.set_author(
                name=f"{target} ({entry.target.id})",
                icon_url=entry.target.display_avatar.url,
            )
            e.description = f"{target.mention} (ID: {target.id}) was kicked."
        else:
            e.set_author(name=f"User #{entry.target.id}")
            e.description = f"User with ID `{entry.target.id}` was kicked."

        return await self.dispatch(channels, [e])

    async def handle_ban(self, entry: discord.AuditLogEntry):
        """Handler for when a user is banned"""
        if not (channels := self.get_channels(entry.guild, ["bans"])):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="User Banned",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if isinstance(target := entry.target, discord.Object):
            target = self.bot.get_user(entry.target.id)

        if target is not None:
            e.set_author(
                name=f"{target} ({entry.target.id})",
                icon_url=entry.target.display_avatar.url,
            )
            e.description = f"{entry.target.mention} was banned."
        else:
            e.set_author(name=f"User #{entry.target.id}")
            e.description = f"User with ID `{entry.target.id}` was banned."

        return await self.dispatch(channels, [e])

    async def handle_unban(self, entry: discord.AuditLogEntry):
        """Handler for when a user is unbanned"""
        if not (channels := self.get_channels(entry.guild, ["bans"])):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="User Unbanned",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if isinstance(user := entry.target, discord.Object):
            user = self.bot.get_user(entry.target.id)

        if user is not None:
            e.set_author(
                name=f"{user} ({user.id})", icon_url=user.display_avatar.url
            )
            e.description = f"{user.mention} was unbanned."
        else:
            e.set_author(name=f"User #{entry.target.id}")
            e.description = f"User with ID `{entry.target.id}` was unbanned."

        return await self.dispatch(channels, [e])

    async def handle_member_update(self, entry: discord.AuditLogEntry):
        """Handler for when various things when a member is updated
        e.g. Name Change, Muted, Deafened, Timed Out."""
        if not (channels := self.get_channels(entry.guild, ["moderation"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        e: Embed = Embed(colour=Colour.og_blurple(), description="")
        do_footer(entry, e)

        if isinstance(user := entry.target, discord.Object):
            user = entry.guild.get_member(user.id)

        e.set_author(
            name=f"{user} ({user.id})", icon_url=user.display_avatar.url
        )
        e.description = f"{user.mention}\n\n"

        if key := changes.pop("nick", False):
            e.title = "User Renamed"
            bf = user.name if key["before"] is None else key["before"]
            af = user.name if key["after"] is None else key["after"]
            e.description += f"**Old**: {bf}\n**New**: {af}"

        if key := changes.pop("mute", False):
            if key["before"]:
                e.title = "User Server Un-muted"
            else:
                e.title = "User Server Muted"

        if key := changes.pop("deaf", False):
            if key["before"]:
                e.title = "User Server Un-deafened"
            else:
                e.title = "User Server Deafened"

        if key := changes.pop("timed_out_until", False):
            if key["before"] is None:
                e.title = "Timed Out"
                s = Timestamp(key["after"]).relative
                e.description += f"**Timeout Expires**: {s}\n"
            else:
                e.title = "Timeout Ended"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_member_move(self, entry: discord.AuditLogEntry):
        """Handler for when a member's voice channel is moved"""
        if not (channels := self.get_channels(entry.guild, ["moderation"])):
            return

        e: Embed = Embed(
            colour=Colour.brand_red(),
            title="Moved to Voice Channel",
            description="",
        )
        do_footer(entry, e)

        x = entry.extra
        e.description = f"{x.count} users\n\nNew Channel: <#{x.channel.id}>"

        return await self.dispatch(channels, [e])

    async def handle_member_disconnect(self, entry: discord.AuditLogEntry):
        """Handler for when user(s) are kicked from a voice channel"""
        if not (channels := self.get_channels(entry.guild, ["moderation"])):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Kicked From Voice Channel",
            timestamp=entry.created_at,
        )
        do_footer(entry, e)
        e.description = f"{entry.extra.count} members"

        return await self.dispatch(channels, [e])

    async def handle_role_create(self, entry: discord.AuditLogEntry):
        """Handler for when a role is created"""
        if not (channels := self.get_channels(entry.guild, ["role_edits"])):
            return

        changes = {k: v for k, v in entry.changes.after}
        e: Embed = Embed(
            colour=Colour.light_gray(), title="Role Created", description=""
        )
        do_footer(entry, e)

        if isinstance(role := entry.target, discord.Object):
            role = entry.guild.get_role(entry.target.id)

        if role is None:
            role_icon = None
        else:
            role_icon: str = (
                role.display_icon.url
                if role.display_icon is not None
                else None
            )

        e.set_author(name=f"{role} ({entry.target.id})", icon_url=role_icon)
        e.description = f"<@&{entry.target.id}>\n\n"

        for key in ["name", "mentionable"]:
            if value := changes.pop(key, False):
                e.description += f"**{key.title()}**: {value}\n"

        if colour := changes.pop("colour", False):
            changes.pop("color")
            e.description += f"**Colour**: {colour}\n"
            e.colour = colour

        if (hoist := changes.pop("hoist", None)) is not None:
            e.description += f"**Show Separately**: `{hoist}`\n"

        if emoji := changes.pop("unicode_emoji", False):
            e.description += f"**Emoji**: {emoji}\n"

        if icon := changes.pop("icon", False):
            e.description += f"**Icon**: f'[Link]({icon.url})\n"
            e.set_image(url=icon.url)

        if permissions := changes.pop("permissions", False):
            if perms := [f"✅ {k}" for (k, v) in iter(permissions) if v]:
                e.add_field(name="Permissions", value=", ".join(perms))

        return await self.dispatch(channels, [e])

    async def handle_role_update(self, entry: discord.AuditLogEntry):
        """Handler for when a role is updated"""
        if not (channels := self.get_channels(entry.guild, ["role_edits"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(colour=Colour.dark_gray(), title="Role Updated")
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if isinstance(role := entry.target, discord.Object):
            role = entry.guild.get_role(entry.target.id)

        if role is None:
            role_icon = None
            before.set_author(
                name=f"{entry.target.name} ({entry.target.id})",
                icon_url=role_icon,
            )
        else:
            role_icon: str = (
                role.display_icon.url
                if role.display_icon is not None
                else None
            )
            before.set_author(
                name=f"{role.name} ({entry.target.id})", icon_url=role_icon
            )
        before.description = f"<@&{entry.target.id}>\n\n"

        for k in ["name", "mentionable"]:
            if key := changes.pop(k, False):
                before.description += f"**{k.title()}**: {key['before']}\n"
                after.description += f"**{k.title()}**: {key['after']}\n"

        if key := changes.pop("colour", False):
            changes.pop("color", None)
            before.description += f"**Colour**: {key['before']}\n"
            after.description += f"**Colour**: {key['after']}\n"
            before.colour = key["before"]
            after.colour = key["after"]

        if key := changes.pop("hoist", False):
            before.description += f"**Show Separately**: {key['before']}\n"
            after.description += f"**Show Separately**: {key['after']}\n"

        if key := changes.pop("unicode_emoji", False):
            before.description += f"**Emoji**: {key['before']}\n"
            after.description += f"**Emoji**: {key['after']}\n"

        if key := changes.pop("icon", False):
            bf_img = key["before"].url if key["before"] is not None else None
            af_img = key["after"].url if key["after"] is not None else None

            bf = f"[Link]({bf_img})" if bf_img else None
            af = f"[Link]({af_img})" if af_img else None
            before.description += f"**Icon**: {bf}\n"
            after.description += f"**Icon**: {af}\n"
            before.set_image(url=bf_img)
            after.set_image(url=af_img)

        if key := changes.pop("permissions", False):
            bf: discord.Permissions = key["before"]
            af: discord.Permissions = key["after"]

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
                before.add_field(name="Permissions", value="\n".join(bf_list))
            if af_list:
                after.add_field(name="Permissions", value="\n".join(af_list))

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_role_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a role is deleted"""
        if not (channels := self.get_channels(entry.guild, ["role_edits"])):
            return

        changes = {k: v for k, v in entry.changes.before}
        e: Embed = Embed(
            colour=Colour.dark_gray(), title="Role Deleted", description=""
        )
        do_footer(entry, e)

        if icon := changes.pop("icon", None):
            e.description += f"**Icon**: [Link]({icon.url})\n"

        if name := changes.pop("name", "Deleted Role"):
            e.description += f"**Name**: {name}\n"

        e.set_author(name=f"{name} ({entry.target.id})", icon_url=icon)
        e.description = f"<@&{entry.target.id}>\n\n"

        if mentionable := changes.pop("mentionable", False):
            e.description += f"**Mentionable**: {mentionable}\n"

        if colour := changes.pop("colour", False):
            changes.pop("color")
            e.description += f"**Colour**: {colour}\n"
            e.colour = colour

        if hoist := changes.pop("hoist", False):
            e.description += f"**Show Separately**: {hoist}\n"

        if emote := changes.pop("unicode_emoji", False):
            e.description += f"**Emoji**: {emote}\n"

        if permissions := changes.pop("permissions", False):
            if perms := [f"✅ {k}" for (k, v) in iter(permissions) if v]:
                e.add_field(name="Permissions", value=", ".join(perms))

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_member_role_update(self, entry: discord.AuditLogEntry):
        """Handler for when a member gains or loses roles"""
        if not (channels := self.get_channels(entry.guild, ["user_roles"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        e: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        member = entry.target
        if isinstance(member, discord.Object):
            member = entry.guild.get_member(member.id)

        if member is not None:
            e.set_author(
                name=f"{member} ({member.id})",
                icon_url=member.display_avatar.url,
            )
        else:
            e.set_author(name=f"User with ID <@{entry.target.id}>")

        if key := changes.pop("roles", False):
            if key["after"]:
                e.title = "Role Granted"
                e.colour = Colour.green()
                e.description = ", ".join([i.mention for i in key["after"]])
            else:
                e.title = "Role Removed"
                e.colour = Colour.red()
                e.description = ", ".join([i.mention for i in key["before"]])

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_emoji_create(self, entry: discord.AuditLogEntry):
        """Handler for when an emoji is created"""
        if not (
            channels := self.get_channels(entry.guild, ["emote_and_sticker"])
        ):
            return

        changes = {k: v for k, v in entry.changes.after}
        e: Embed = Embed(
            colour=Colour.dark_gray(), title="Emoji Created", description=""
        )
        do_footer(entry, e)

        if isinstance(emoji := entry.target, discord.Object):
            try:
                emoji = next(i for i in entry.guild.emojis if i.id == emoji.id)
            except StopIteration:
                try:
                    emoji = await entry.guild.fetch_emoji(emoji.id)
                except discord.NotFound:
                    emoji = None

            if emoji is not None:
                e.set_image(url=emoji.url)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_emoji_update(self, entry: discord.AuditLogEntry):
        """Handler for when an emoji is updated"""
        if not (
            channels := self.get_channels(entry.guild, ["emote_and_sticker"])
        ):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(), title="Emoji Updated", description=""
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

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

        for k in ["name"]:
            if key := changes.pop(k, False):
                before.description += f"**{k.title()}((: {key['before']}\n"
                after.description += f"**{k.title()}**: {key['after']}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_emoji_delete(self, entry: discord.AuditLogEntry):
        """Handler for when an emoji is deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["emote_and_sticker"])
        ):
            return

        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Emoji Deleted",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if isinstance(emoji := entry.target, discord.Object):
            try:
                emoji = next(i for i in entry.guild.emojis if i.id == emoji.id)
            except StopIteration:
                try:
                    emoji = await entry.guild.fetch_emoji(emoji.id)
                except discord.NotFound:
                    emoji = None

            if emoji is not None:
                e.set_image(url=emoji.url)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_sticker_create(self, entry: discord.AuditLogEntry):
        """Handler for when a sticker is created"""
        if not (
            channels := self.get_channels(entry.guild, ["emote_and_sticker"])
        ):
            return

        changes = {
            k: v
            for k, v in entry.changes.after
            if k not in ["name", "description"]
        }

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Sticker Uploaded",
            timestamp=entry.created_at,
        )
        do_footer(entry, e)

        if isinstance(sticker := entry.target, discord.Object):
            sticker: discord.GuildSticker = self.bot.get_sticker(sticker.id)

        e.description = (
            f":{sticker.emoji}: **{sticker.name}**\n{sticker.url}"
            f"\n\n{sticker.description}"
        )
        e.set_image(url=sticker.url)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_sticker_update(self, entry: discord.AuditLogEntry):
        """Handler for when a sticker is updated"""
        if not (
            channels := self.get_channels(entry.guild, ["emote_and_sticker"])
        ):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(), title="Sticker Updated", description=""
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if isinstance(target := entry.target, discord.Object):
            target: discord.GuildSticker = self.bot.get_sticker(target.id)
        before.set_thumbnail(url=target.url)

        for attr in ["name", "emoji", "description"]:
            if key := changes.pop(attr, False):
                before.description += f"**{attr.title()}**: {key['before']}"
                after.description += f"**{attr.title()}**: {key['after']}"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_sticker_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a sticker is deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["emote_and_sticker"])
        ):
            return

        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Sticker Deleted",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description = f"**Name**: {name}\n"

        if description := changes.pop("description", False):
            e.description += f"**Description**: {description}"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_invite_create(self, entry: discord.AuditLogEntry):
        """Handler for when an invitation is created"""
        if not (channels := self.get_channels(entry.guild, ["invites"])):
            return

        changes = {k: v for k, v in entry.changes.after}

        if (temp := changes.pop("temporary", False)) and temp:
            temp = "Temporary "
        else:
            temp = ""

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title=f"{temp}Invite Created",
            timestamp=entry.created_at,
        )
        do_footer(entry, e)
        e.description = f"<@{entry.user.id}>"

        if channel := changes.pop("channel", False):
            e.description += f"{channel.mention} "

        if code := changes.pop("code", False):
            e.description += f"[{code}](http://www.discord.gg/{code})\n\n"

        if _ := changes.pop("inviter", False):
            pass  # We just use the user field.

        if _ := changes.pop("uses", False):
            pass  # This should not have been used at creation point.

        if max_use := changes.pop("max_uses", False):
            e.description += f"**Max Uses**: {max_use}\n"

        if max_age := changes.pop("max_age", False):
            e.description += f"**Expiry**: {stringify_seconds(max_age)}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_invite_update(self, entry: discord.AuditLogEntry):
        """Handler for when an invitation is updated"""
        if not (channels := self.get_channels(entry.guild, ["invites"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(), title="Invite Updated", description=""
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if key := changes.pop("code", False):
            before.description += (
                f"**Link**: http://www.discord.gg/{key['before']}\n\n"
            )
            after.description += (
                f"**Link**: http://www.discord.gg/{key['after']}\n\n"
            )

        if key := changes.pop("channel", False):
            before.description += (
                f"**Channel**: {key['before'].mention}\n"
                if key["before"] is not None
                else ""
            )
            after.description += (
                f"**Channel**: {key['after'].mention}\n"
                if key["after"] is not None
                else ""
            )

        if key := changes.pop("inviter", False):
            user = key["before"]
            if user is not None:
                before.set_author(
                    name=f"{user.mention} ({user.id})",
                    icon_url=user.display_avatar.url,
                )
            user = key["after"]
            if user is not None:
                after.set_author(
                    name=f"{user.mention} ({user.id})",
                    icon_url=user.display_avatar.url,
                )

        if key := changes.pop("uses", False):
            before.description += f"**Uses**: {key['before']}\n"
            after.description += f"**Uses**: {key['after']}\n"

        if key := changes.pop("max_uses", False):
            before.description += f"**Max Uses**: {key['before']}\n"
            after.description += f"**Max Uses**: {key['after']}\n"

        if key := changes.pop("max_age", False):
            bf = (
                f"{key['before']}" + " seconds"
                if key["before"]
                else "Permanent"
            )
            before.description += f"**Expiry**: {bf}\n"
            af = (
                f"{key['after']}" + " seconds" if key["after"] else "Permanent"
            )
            after.description += f"**Expiry**: {af}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_invite_delete(self, entry: discord.AuditLogEntry):
        """Handler for when an invitation is deleted"""
        if not (channels := self.get_channels(entry.guild, ["invites"])):
            return

        changes = {k: v for k, v in entry.changes.before}

        try:
            temp = "Temporary " if changes.pop("temporary")["before"] else ""
        except AttributeError:
            temp = ""

        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title=f"{temp}Invite Deleted",
            description="",
        )
        do_footer(entry, e)

        if inviter := changes.pop("inviter", False):
            e.set_author(
                name=f"{inviter} ({inviter.id})",
                icon_url=inviter.display_avatar.url,
            )
            e.description = f"{inviter.mention}\n"

        if code := changes.pop("code", False):
            e.description += (
                f"**Code**: [{code}](http://www.discord.gg/{code})\n"
            )

        if channel := changes.pop("channel", False):
            e.description += f"**Channel**: {channel.mention}\n"

        if uses := changes.pop("uses", False):
            e.description += f"**Uses**: {uses}\n"

        if max_uses := changes.pop("max_uses", False):
            e.description += f"**Max Uses**: {max_uses}\n"

        if max_age := changes.pop("max_age", False):
            e.description += f"**Expiry**: {stringify_seconds(max_age)}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_bot_add(self, entry: discord.AuditLogEntry):
        """Handler for when a bot is added"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Bot Added",
            timestamp=entry.created_at,
        )
        e.set_author(
            name=f"{entry.target} ({entry.target.id})",
            icon_url=entry.target.display_avatar.url,
        )
        e.description = f"{entry.target.mention} (ID: {entry.target.id})"
        do_footer(entry, e)

        changes = {k: v for k, v in entry.changes.after}

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_message_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a message is deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["deleted_messages"])
        ):
            return

        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Message(s) Deleted",
            timestamp=entry.created_at,
        )
        x = entry.extra
        e.description = f"{x.count} message(s) deleted in <#{x.channel.id}>"
        do_footer(entry, e)

        if isinstance(target := entry.target, discord.Object):
            try:
                target = entry.guild.get_member(entry.target.id)
            except AttributeError:
                target = self.bot.get_user(entry.target.id)

        if target is not None:
            e.set_author(
                name=f"{target} ({target.id})",
                icon_url=target.display_avatar.url,
            )
        else:
            e.set_author(name=f"User with ID# {entry.target.id}")

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_message_bulk_delete(self, entry: discord.AuditLogEntry):
        """Handler for when messages are bulk deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["deleted_messages"])
        ):
            return

        changes = {k: v for k, v in entry.changes.before}
        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Messages Bulk Deleted",
            timestamp=entry.created_at,
        )
        e.description = (
            f"{entry.target.mention}: {entry.extra.count} messages deleted."
        )
        do_footer(entry, e)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_webhook_create(self, entry: discord.AuditLogEntry):
        """Handler for when a webhook is created"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {k: v for k, v in entry.changes.after}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Webhook Created",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if channel := changes.pop("channel", False):
            e.description += f"**Channel**: {channel.mention}\n"

        if c_type := changes.pop("type", False):  # Channel Type.
            e.description += f"**Type**: {c_type.name}\n"

        if application_id := changes.pop("application_id", False):
            e.description += f"**Application ID**: {application_id}\n"

        if avatar := changes.pop("avatar", False):
            e.set_image(url=avatar.url)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_webhook_update(self, entry: discord.AuditLogEntry):
        """Handler for when a webhook is updated"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(), title="Webhook Updated", description=""
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if key := changes.pop("name", False):
            before.description += f"**Name**: {key['before']}\n"
            after.description += f"**Name**: {key['after']}\n"

        if key := changes.pop("channel", False):
            b = key["before"].mention if key["before"] else None
            a = key["after"].mention if key["after"] else None
            before.description += f"**Channel**: {b}\n"
            after.description += f"**Channel**: {a}\n"

        if key := changes.pop("type", False):  # Channel Type.
            b = key["before"].name if key["before"] else None
            a = key["after"].name if key["after"] else None
            if a != b:
                if b:
                    before.description += f"**Type**: {b}\n"
                if a:
                    after.description += f"**Type**: {a}\n"

        if key := changes.pop("application_id", False):
            before.description += f"**Application ID**: {key['before']}\n"
            after.description += f"**Application ID**: {key['after']}\n"

        if key := changes.pop("avatar", False):
            if (ico := key["before"]) is not None:
                before.set_image(url=ico.url)
            if (ico := key["after"]) is not None:
                after.set_image(url=ico.url)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_webhook_delete(self, entry: discord.AuditLogEntry):
        """Handler for when a webhook is deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.dark_gray(), title="Webhook Deleted", description=""
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if channel := changes.pop("channel", False):
            e.description += f"**Channel**: {channel.mention}\n"

        if c_type := changes.pop("type", False):  # Channel Type.
            e.description += f"**Type**: {c_type.name}\n"

        if application_id := changes.pop("application_id", False):
            e.description += f"**Application ID**: {application_id}\n"

        if avatar := changes.pop("avatar", False):
            e.set_image(url=avatar.url)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_integration_create(self, entry: discord.AuditLogEntry):
        """Handler for when an integration is created"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {k: v for k, v in entry.changes.after}
        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Integration Created",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if c_type := changes.pop("type", False):
            e.description += f"**Type**: {c_type}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_integration_update(self, entry: discord.AuditLogEntry):
        """Handler for when an integration is updated"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Integration Updated",
            description="",
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if key := changes.pop("name", False):
            before.description += f"**Name**: {key['before']}\n"
            after.description += f"**Name**: {key['after']}\n"

        if key := changes.pop("type", False):
            before.description += f"**Type**: {key['before']}\n"
            after.description += f"**Type**: {key['after']}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_integration_delete(self, entry: discord.AuditLogEntry):
        """Handler for when an integration is deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return
        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Integration Deleted",
            description="",
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if c_type := changes.pop("type", False):
            e.description += f"**Type**: {c_type}\n"

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_app_command_perms_update(
        self, entry: discord.AuditLogEntry
    ):
        """Handler for when an application's permissions are updated"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(colour=Colour.dark_gray(), description="")
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        # When this is the action, the type of target is a PartialIntegration
        # for an integrations general permissions.
        # OR AppCommand for a specific commands permissions,
        # or Object with the ID of the command or integration
        # which was updated.
        target = entry.target
        if isinstance(target, discord.PartialIntegration):
            target: discord.Integration = next(
                i
                for i in await entry.guild.integrations()
                if i.id == target.id
            )

            if target.account is not None:
                before.set_author(
                    name=f"{target.account.name} ({target.account.id})"
                )
            else:
                before.set_author(name=f"{target.name} ({target.id})")
            before.description = (
                f"{target.type} Integration Permissions Updated."
            )
            before.title = f"{target.type} Integration Permissions Updated"

        elif isinstance(target, discord.app_commands.AppCommand):
            before.title = "Command Permissions Updated"
            before.description = target.mention

        else:
            before.title = "Integration Updated"
            before.description = f"Integration ID #{target.id}"

        # When this is the action, the type of extra is set
        # to a PartialIntegration or Object with the ID of application
        # that command or integration belongs to.
        x = entry.extra
        if isinstance(x, discord.Object):
            before.description = f"\nApplication ID: {x.id}"
        else:  # PartialIntegration
            a = x.account
            before.description += f"\nIntegration: {x.name} {a.name} ({a.id})"

        if key := changes.pop("app_command_permissions", False):
            do_perms(entry, key["before"], before)
            do_perms(entry, key["after"], after)

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")
        return await self.dispatch(channels, [before, after])

    async def handle_automod_rule_create(self, entry: discord.AuditLogEntry):
        """Handler for when an automod rule is created"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {k: v for k, v in entry.changes.after}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Automod Rule Created",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if enabled := changes.pop("enabled", None) is not None:
            e.description += f"**Enabled**: `{enabled}`\n"

        if trigger := changes.pop("trigger", False):
            e.add_field(
                name="New Blocked Terms",
                value=", ".join(trigger),
                inline=False,
            )

        if exempt_roles := changes.pop("exempt_roles", False):
            e.add_field(
                name="Exempt Roles",
                value=", ".join([i.mention for i in exempt_roles]),
            )

        if exempt_channels := changes.pop("exempt_channels", False):
            e.add_field(
                name="Exempt Channels",
                value=", ".join([i.mention for i in exempt_channels]),
            )

        acts = []
        for i in changes.pop("actions", []):
            match i.type:
                case discord.AutoModRuleActionType.timeout:
                    acts.append(f"Timeout for {i.duration}")
                case discord.AutoModRuleActionType.block_message:
                    acts.append("Block Message")
                case discord.AutoModRuleActionType.send_alert_message:
                    channel = self.bot.get_channel(i.channel_id)
                    acts.append(f"Send Alert Message to {channel.mention}")
                case _:
                    logging.info(f"Unhandled AutoModRuleActionType, {i}")
        if acts:
            e.add_field(name="Actions", value="\n".join(acts))

        if trigger_type := changes.pop("trigger_type", False):
            e.description += (
                f"**Trigger Type**: {stringify_trigger_type(trigger_type)}\n"
            )

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")
        return await self.dispatch(channels, [e])

    async def handle_automod_rule_update(self, entry: discord.AuditLogEntry):
        """Handler for when an automod rule is updated"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        before: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Automod Rule Updated",
            description="",
        )
        after: Embed = Embed(
            colour=Colour.light_gray(),
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, after)

        if key := changes.pop("name", False):
            before.description += f"**Rule name**: {key['before']}\n"
            after.description += f"**Rule name**: {key['after']}\n"

        if key := changes.pop("enabled", False):
            before.description += f"**Rule enabled**: `{key['before']}`\n"
            after.description += f"**Rule enabled**: `{key['after']}`\n"

        if key := changes.pop("trigger", False):
            bf: discord.AutoModTrigger = key["before"] if key["before"] else []
            af: discord.AutoModTrigger = key["after"] if key["after"] else []

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
                after.add_field(
                    name="New Blocked Terms",
                    value=", ".join(new_words),
                    inline=False,
                )
                before.add_field(
                    name="New Blocked Terms",
                    value=", ".join(new_words),
                    inline=False,
                )
            if removed:
                after.add_field(
                    name="Blocked Terms Removed",
                    value=", ".join(removed),
                    inline=False,
                )
                before.add_field(
                    name="Blocked Terms Removed",
                    value=", ".join(removed),
                    inline=False,
                )

        if key := changes.pop("exempt_roles", False):
            bf_roles: list[Role] = key["before"]
            af_roles: list[Role] = key["after"]

            if new := [i for i in af_roles if i not in bf_roles]:
                after.add_field(
                    name="Exempt Roles Added",
                    value=", ".join([i.mention for i in new]),
                )
            if removed := [i for i in bf_roles if i not in af_roles]:
                after.add_field(
                    name="Exempt Roles Removed",
                    value=", ".join([i.mention for i in removed]),
                )

        if key := changes.pop("exempt_channels", False):
            bf_channels: list[TextChannel] = key["before"]
            af_channels: list[TextChannel] = key["after"]

            if new := [i for i in af_channels if i not in bf_channels]:
                after.add_field(
                    name="Exempt Channels Added",
                    value=", ".join([i.mention for i in new]),
                )
            if removed := [i for i in bf_channels if i not in af_channels]:
                after.add_field(
                    name="Exempt Channels Removed",
                    value=", ".join([i.mention for i in removed]),
                )

        if key := changes.pop("actions", False):
            acts = []
            for i in key["before"]:
                match i.type:
                    case discord.AutoModRuleActionType.timeout:
                        acts.append(f"Timeout for {i.duration}")
                    case discord.AutoModRuleActionType.block_message:
                        acts.append("Block Message")
                    case discord.AutoModRuleActionType.send_alert_message:
                        channel = self.bot.get_channel(i.channel_id)
                        acts.append(f"Send Alert Message to {channel.mention}")
            if acts:
                before.add_field(name="Actions", value="\n".join(acts))

            acts.clear()
            for i in key["after"]:
                match i.type:
                    case discord.AutoModRuleActionType.timeout:
                        acts.append(f"Timeout for {i.duration}")
                    case discord.AutoModRuleActionType.block_message:
                        acts.append("Block Message")
                    case discord.AutoModRuleActionType.send_alert_message:
                        channel = self.bot.get_channel(i.channel_id)
                        acts.append(f"Send Alert Message to {channel.mention}")
                    case _:
                        logging.info(f"Unhandled AutoModRuleActionType, {i}")
            if acts:
                after.add_field(name="Actions", value="\n".join(acts))

        if key := changes.pop("trigger_type", False):
            before.description += (
                f"**Trigger Type**: {stringify_trigger_type(key['before'])}\n"
            )
            after.description += (
                f"**Trigger Type**: {stringify_trigger_type(key['after'])}\n"
            )

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [before, after])

    async def handle_automod_rule_delete(self, entry: discord.AuditLogEntry):
        """Handler for when an automod rule is deleted"""
        if not (
            channels := self.get_channels(entry.guild, ["bot_management"])
        ):
            return

        changes = {k: v for k, v in entry.changes.before}

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Automod Rule Deleted",
            timestamp=entry.created_at,
            description="",
        )
        do_footer(entry, e)

        if name := changes.pop("name", False):
            e.description += f"**Name**: {name}\n"

        if enabled := changes.pop("enabled", False):
            e.description += f"**Enabled**: `{enabled}`\n"

        if trigger := changes.pop("trigger", False):
            e.add_field(
                name="Blocked Terms Removed",
                value=", ".join(trigger),
                inline=False,
            )

        if exempt_roles := changes.pop("exempt_roles", False):
            e.add_field(
                name="Exempt Roles",
                value=", ".join([i.mention for i in exempt_roles]),
            )

        if exempt_channels := changes.pop("exempt_channels", False):
            e.add_field(
                name="Exempt Channels",
                value=", ".join([i.mention for i in exempt_channels]),
            )

        acts = []
        for i in changes.pop("actions", False):
            match i.type:
                case discord.AutoModRuleActionType.timeout:
                    acts.append(f"Timeout for {i.duration}")
                case discord.AutoModRuleActionType.block_message:
                    acts.append("Block Message")
                case discord.AutoModRuleActionType.send_alert_message:
                    channel = self.bot.get_channel(i.channel_id)
                    acts.append(f"Send Alert Message to {channel.mention}")
        if acts:
            e.add_field(name="Actions", value="\n".join(acts))

        if trigger_type := changes.pop("trigger_type", False):
            e.description += (
                f"**Trigger Type**: {stringify_trigger_type(trigger_type)}\n"
            )

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")

        return await self.dispatch(channels, [e])

    async def handle_automod_flag_message(self, entry: discord.AuditLogEntry):
        """Handler for when a message is flagged by auto moderator"""
        if not (channels := self.get_channels(entry.guild, ["moderation"])):
            return

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Automod: Message Flagged",
            timestamp=entry.created_at,
        )
        s = stringify_trigger_type(entry.extra.automod_rule_trigger_type)
        e.description = (
            f"{entry.target.mention}: {entry.extra.channel.mention}\n\n"
            f"**Rule**: {entry.extra.automod_rule_name}\n"
            f"**Trigger**: {s}"
        )

        return await self.dispatch(channels, [e])

    async def handle_automod_block_message(self, entry: discord.AuditLogEntry):
        """Handler for when a message is blocked by auto moderator"""
        if not (channels := self.get_channels(entry.guild, ["moderation"])):
            return

        e: Embed = Embed(
            colour=Colour.dark_gray(),
            title="Automod: Message Blocked",
            timestamp=entry.created_at,
        )
        s = stringify_trigger_type(entry.extra.automod_rule_trigger_type)
        e.description = (
            f"{entry.target.mention}: {entry.extra.channel.mention}\n\n"
            f"**Rule**: {entry.extra.automod_rule_name}\n"
            f"**Trigger**: {s}"
        )
        return await self.dispatch(channels, [e])

    async def handle_automod_timeout_member(
        self, entry: discord.AuditLogEntry
    ):
        """Handler for when a member is timed out by auto moderator"""
        if not (channels := self.get_channels(entry.guild, ["moderation"])):
            return

        changes = {}
        for k, v in entry.changes.before:
            changes[k] = {"before": v}
        for k, v in entry.changes.after:
            changes[k]["after"] = v

        e: Embed = Embed(
            colour=Colour.light_gray(),
            title="Automod Timeout",
            timestamp=entry.created_at,
            description="",
        )

        member = entry.target
        s = stringify_trigger_type(entry.extra.automod_rule_trigger_type)
        e.description = (
            f"{member.mention} in {entry.extra.channel.mention}\n"
            f"**Rule**: {entry.extra.automod_rule_name}\n"
            f"**Trigger**: {s}"
        )

        if changes:
            logging.info(f"{entry.action} | Changes Remain: {changes}")
        else:
            logging.info(f"{entry.action} has no changes.")

        return await self.dispatch(channels, [e])

    @Cog.listener()
    async def on_audit_log_entry_create(
        self, entry: discord.AuditLogEntry
    ) -> None:
        """Send to own handlers"""
        match entry.action:
            case AuditLogAction.app_command_permission_update:
                return await self.handle_app_command_perms_update(entry)
            case AuditLogAction.ban:
                return await self.handle_ban(entry)
            case AuditLogAction.bot_add:
                return await self.handle_bot_add(entry)
            case AuditLogAction.channel_create:
                return await self.handle_channel_create(entry)
            case AuditLogAction.channel_delete:
                return await self.handle_channel_delete(entry)
            case AuditLogAction.channel_update:
                return await self.handle_channel_update(entry)
            case AuditLogAction.emoji_create:
                return await self.handle_emoji_create(entry)
            case AuditLogAction.emoji_delete:
                return await self.handle_emoji_delete(entry)
            case AuditLogAction.emoji_update:
                return await self.handle_emoji_update(entry)
            case AuditLogAction.guild_update:
                return await self.handle_guild_update(entry)
            case AuditLogAction.integration_create:
                return await self.handle_integration_create(entry)
            case AuditLogAction.integration_update:
                return await self.handle_integration_update(entry)
            case AuditLogAction.integration_delete:
                return await self.handle_integration_delete(entry)
            case AuditLogAction.invite_create:
                return await self.handle_invite_create(entry)
            case AuditLogAction.invite_update:
                return await self.handle_invite_update(entry)
            case AuditLogAction.invite_delete:
                return await self.handle_invite_delete(entry)
            case AuditLogAction.kick:
                return await self.handle_kick(entry)
            case AuditLogAction.member_disconnect:
                return await self.handle_member_disconnect(entry)
            case AuditLogAction.member_move:
                return await self.handle_member_move(entry)
            case AuditLogAction.member_role_update:
                return await self.handle_member_role_update(entry)
            case AuditLogAction.member_update:
                return await self.handle_member_update(entry)
            case AuditLogAction.message_bulk_delete:
                return await self.handle_message_bulk_delete(entry)
            case AuditLogAction.message_delete:
                return await self.handle_message_delete(entry)
            case AuditLogAction.message_pin:
                return await self.handle_message_pin(entry)
            case AuditLogAction.message_unpin:
                return await self.handle_message_unpin(entry)
            case AuditLogAction.overwrite_create:
                return await self.handle_overwrite_create(entry)
            case AuditLogAction.overwrite_update:
                return await self.handle_overwrite_update(entry)
            case AuditLogAction.overwrite_delete:
                return await self.handle_overwrite_delete(entry)
            case AuditLogAction.role_create:
                return await self.handle_role_create(entry)
            case AuditLogAction.role_delete:
                return await self.handle_role_delete(entry)
            case AuditLogAction.role_update:
                return await self.handle_role_update(entry)
            case AuditLogAction.scheduled_event_create:
                return await self.handle_event_create(entry)
            case AuditLogAction.scheduled_event_update:
                return await self.handle_event_update(entry)
            case AuditLogAction.scheduled_event_delete:
                return await self.handle_event_delete(entry)
            case AuditLogAction.stage_instance_create:
                return await self.handle_stage_create(entry)
            case AuditLogAction.stage_instance_update:
                return await self.handle_stage_update(entry)
            case AuditLogAction.stage_instance_delete:
                return await self.handle_stage_delete(entry)
            case AuditLogAction.sticker_create:
                return await self.handle_sticker_create(entry)
            case AuditLogAction.sticker_update:
                return await self.handle_sticker_update(entry)
            case AuditLogAction.sticker_delete:
                return await self.handle_sticker_delete(entry)
            case AuditLogAction.thread_create:
                return await self.handle_thread_create(entry)
            case AuditLogAction.thread_delete:
                return await self.handle_thread_delete(entry)
            case AuditLogAction.thread_update:
                return await self.handle_thread_update(entry)
            case AuditLogAction.unban:
                return await self.handle_unban(entry)
            case AuditLogAction.webhook_create:
                return await self.handle_webhook_create(entry)
            case AuditLogAction.webhook_update:
                return await self.handle_webhook_update(entry)
            case AuditLogAction.webhook_delete:
                return await self.handle_webhook_delete(entry)
            case AuditLogAction.automod_rule_create:
                return await self.handle_automod_rule_create(entry)
            case AuditLogAction.automod_rule_update:
                return await self.handle_automod_rule_update(entry)
            case AuditLogAction.automod_rule_delete:
                return await self.handle_automod_rule_delete(entry)
            case AuditLogAction.automod_flag_message:
                return await self.handle_automod_flag_message(entry)
            case AuditLogAction.automod_block_message:
                return await self.handle_automod_block_message(entry)
            case AuditLogAction.automod_timeout_member:
                return await self.handle_automod_timeout_member(entry)
            case _:
                logging.info(f"Unhandled Audit Log Action Type {entry.action}")

    # Deleted message notif
    @Cog.listener()
    async def on_message_delete(self, message: Message) -> None:
        """Event handler for reposting deleted messages from users"""
        if message.guild is None or message.author.bot:
            return  # Ignore DMs & Do not log message deletions from bots.

        ch = filter(
            lambda i: i["guild_id"] == message.guild.id
            and i["deleted_messages"],
            self.bot.notifications_cache,
        )
        if not (
            ch := filter(
                None, [self.bot.get_channel(i["channel_id"]) for i in ch]
            )
        ):
            return

        e: Embed = Embed(
            colour=Colour.dark_red(),
            title="Deleted Message",
            timestamp=discord.utils.utcnow(),
        )
        e.set_author(
            name=f"{message.author} ({message.author.id})",
            icon_url=message.author.display_avatar.url,
        )
        t = timed_events.Timestamp(discord.utils.utcnow()).datetime
        e.description = f"{t} {message.channel.mention}\n\n{message.content}"
        attachments: list[File] = []

        for num, z in enumerate(message.attachments, 1):
            v = (
                f"📎 *Attachment info*: [{z.filename}]({z.proxy_url})"
                f"({z.content_type} - {z.size} bytes)\n"
                f"*This is cached and only be available for a limited time*"
            )
            e.add_field(name=f"Attachment #{num}", value=v)
            try:
                attachments.append(
                    await z.to_file(spoiler=True, use_cached=True)
                )
            except discord.HTTPException:
                pass

        for channel in ch:
            try:
                await channel.send(embed=e, files=attachments)
            except discord.HTTPException:
                continue

    # Leave notif
    @Cog.listener()
    async def on_raw_member_remove(
        self, payload: discord.RawMemberRemoveEvent
    ) -> None:
        """Event handler for outputting information about member kick, ban
        or other departures"""
        # Check if in mod action log and override to specific channels.
        guild = self.bot.get_guild(payload.guild_id)
        if not (channels := self.get_channels(guild, ["leaves"])):
            return

        ts = discord.utils.utcnow()
        timestamp = Timestamp(ts).time_relative

        member: User | Member = payload.user
        e: Embed = Embed(
            description=f"{timestamp} {member.mention}",
            colour=Colour.dark_red(),
            timestamp=ts,
        )
        e.set_author(
            name=f"{member} ({member.id})", icon_url=member.display_avatar.url
        )
        e.title = "Member Left"
        for ch in channels:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                pass

    # emojis notif
    @Cog.listener()
    async def on_guild_emojis_update(
        self, guild: discord.Guild, before: list[Emoji], after: list[Emoji]
    ) -> None:
        """Event listener for outputting information about updated emojis"""
        if not (channels := self.get_channels(guild, ["emote_and_sticker"])):
            return

        e: Embed = Embed()
        # Find if it was addition or removal.
        added = [i for i in after if i not in before]
        removed = [i for i in before if i not in after]

        embeds: list[Embed] = []

        if added:
            for emoji in added:
                e.colour = (
                    Colour.dark_purple() if emoji.managed else Colour.green()
                )
                if not emoji.managed:
                    continue

                e.set_author(name="Twitch Integration", icon_url=TWTCH)
                if emoji.roles:
                    e.add_field(
                        name="Available to roles",
                        value=" ".join([i.mention for i in emoji.roles]),
                    )

                anim = "animated " if emoji.animated else ""
                e.title = f"New {anim}emote: {emoji.name}"
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

                e.title = (
                    f"{'Animated ' if emoji.animated else ''} Emoji Removed"
                )
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

        ch = filter(
            lambda i: i["guild_id"] == before.guild.id
            and i["edited_messages"],
            self.bot.notifications_cache,
        )
        if not (
            ch := filter(
                None, [self.bot.get_channel(i["channel_id"]) for i in ch]
            )
        ):
            return

        ts = Timestamp(before.created_at).relative
        e: Embed = Embed(
            title="Message Edited",
            colour=Colour.brand_red(),
            description=f"{before.channel.mention} {ts}\n> {before.content}",
        )
        e2: Embed = Embed(
            colour=Colour.brand_green(),
            timestamp=after.edited_at,
            description=f"> {after.content}",
        )
        e2.set_footer(
            text=f"{before.author} {before.author.id}",
            icon_url=before.author.display_avatar.url,
        )

        v = discord.ui.View()
        v.add_item(
            Button(
                label="Jump to message",
                url=before.jump_url,
                style=discord.ButtonStyle.url,
            )
        )
        return await self.dispatch(ch, [e, e2], view=v)

    @Cog.listener()
    async def on_bulk_message_delete(self, messages: list[Message]):
        """Iter message_delete"""
        for x in messages:
            await self.on_message_delete(x)

    @Cog.listener()
    async def on_raw_reaction_clear(
        self, payload: discord.RawReactionClearEvent
    ):
        """Triggered when all reactions are removed from a message"""
        guild = self.bot.get_guild(payload.guild_id)
        if not (channels := self.get_channels(guild, ["bot_management"])):
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
    async def on_raw_reaction_clear_emoji(
        self, payload: discord.RawReactionClearEmojiEvent
    ):
        """Triggered when a single reaction is removed from a message"""
        channels = filter(
            lambda i: i["guild_id"] == payload.guild_id,
            self.bot.notifications_cache,
        )
        if not (
            channels := filter(
                lambda i: self.bot.get_channel(i["channel_id"]), channels
            )
        ):
            return

        if not (channels := filter(lambda i: i["moderation"], channels)):
            return

        channel = self.bot.get_channel(payload.channel_id)
        message = channel.get_partial_message(payload.message_id)
        emoji = payload.emoji

        e = Embed(title="Reaction Cleared", colour=Colour.greyple())
        e.description = (
            f"**Message**: [Link]({message.jump_url})\n**Emoji**: {emoji}"
        )

        for ch in channels:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                continue

    @Cog.listener()
    async def on_bot_notification(self, notification: str) -> None:
        """Custom event dispatched by painezor, output to tracked guilds."""
        e: Embed = Embed(description=notification)

        for x in filter(
            lambda i: i["bot_notifications"], self.bot.notifications_cache
        ):
            try:
                ch = self.bot.get_channel(x["channel_id"])
                e.colour = ch.guild.me.colour
                await ch.send(embed=e)
            except (AttributeError, discord.HTTPException):
                continue

    @command()
    @default_permissions(view_audit_log=True)
    async def logs(
        self, interaction: Interaction, channel: discord.TextChannel = None
    ) -> Message:
        """Create moderator logs in this channel."""
        # TODO: Split /logs command into subcommands with sub-views & Parent.

        await interaction.response.defer()
        if channel is None:
            channel = interaction.channel
        return await LogsConfig(interaction, channel).update()


async def setup(bot: Bot | PBot) -> None:
    """Loads the notifications cog into the bot"""
    await bot.add_cog(Logs(bot))
