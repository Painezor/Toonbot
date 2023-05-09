"""Notify server moderators about specific events"""
from __future__ import annotations

import datetime
import logging
import typing
from typing import TYPE_CHECKING, TypeAlias

import discord
from discord import Emoji, Message, Embed, AuditLogEntry
from discord.abc import Messageable
from discord.ext import commands

from ext.utils import view_utils, timed_events, embed_utils


if TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[Bot | PBot]
    User: TypeAlias = discord.User | discord.Member

# TODO: Split /logs command into subcommands with sub-views & Parent.
# TODO: Fallback parser using regular events -- Check if bot has
# view_audit_log perms

logger = logging.getLogger("AuditLogs")

Action = discord.AuditLogAction


TWTCH = (
    "https://seeklogo.com/images/T/"
    "twitch-tv-logo-51C922E0F0-seeklogo.com.png"
)


# TODO: Create LogChannel Object to subsume notifications_cache
class LogChannel:
    """A Channel that tracks changes on a discord server."""

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel = channel


# We don't need to db call every single time an event happens, just when
# config is updated So we cache everything and store it in memory
# instead for performance and sanity reasons.


def stringify_minutes(value: int) -> str:
    """Convert Minutes to less painful to read value"""
    try:
        return {60: "1 Hour", 1440: "1 Day", 4320: "3 Days", 10080: "7 Days"}[
            value
        ]
    except KeyError:
        logging.error("Unhandled archive duration %s", value)
        return str(value)


def stringify_seconds(value: int) -> str:
    """Convert seconds to less painful to read value"""

    try:
        return {
            0: "`None`",
            60: "1 minute",
            120: "2 minutes",
            300: "5 minutes",
            600: "10 minutes",
            1800: "30 minutes",
            3600: "1 hour",
            7200: "2 hours",
            21600: "6 hours",
            86400: "1 day",
            604800: "7 days",
        }[value]
    except KeyError:
        if value > 60:
            logger.error("Stringify - Unhandled Seconds: %s", value)
        return f"{value} seconds"


def stringify_content_filter(value: discord.ContentFilter) -> str:
    """Convert Enum to human string"""

    try:
        return {
            discord.ContentFilter.all_members: "Check All Members",
            discord.ContentFilter.no_role: "Check Un-roled Members",
            discord.ContentFilter.disabled: "Disabled",
        }[value]
    except KeyError:
        logger.info("Unhandled content filter %s", value.name)
        return value.name


def stringify_mfa(value: discord.MFALevel) -> str:
    """Convert discord.MFALevel to human-readable string"""
    try:
        return {
            discord.MFALevel.disabled: "Disabled",
            discord.MFALevel.require_2fa: "2-Factor Authentication Required",
        }[value]
    except KeyError:
        logger.info("Unhandled mfa level %s", value)
        return value.name


def stringify_notification_level(val: discord.NotificationLevel) -> str:
    """Convert Enum to human string"""
    try:
        return {
            discord.NotificationLevel.all_messages: "All Messages",
            discord.NotificationLevel.only_mentions: "Mentions Only",
        }[val]
    except KeyError:
        logger.error("No string found for %s", val)
        return val.name


def stringify_trigger_type(value: discord.AutoModRuleTriggerType) -> str:
    """Convert discord.AutModRuleTriggerType to human-readable string"""
    trigger = discord.AutoModRuleTriggerType
    try:
        return {
            trigger.keyword: "Keyword Mentioned",
            trigger.keyword_preset: "Keyword Preset Mentioned",
            trigger.harmful_link: "Harmful Links",
            trigger.mention_spam: "Mention Spam",
            trigger.spam: "Spam",
        }[value]
    except KeyError:
        logging.info("Failed to parse AutoModRuleTriggerType %s", value)
        return "Unknown"


def stringify_verification(value: discord.VerificationLevel) -> str:
    """Convert discord.VerificationLevel to human-readable string"""

    veri = discord.VerificationLevel
    verhigh = veri.high
    try:
        return {
            veri.none: "None",
            veri.low: "Verified Email",
            veri.medium: "Verified Email, Registered 5 minutes",
            verhigh: "Verified Email, Registered 5 minutes, Member 10 Minutes",
            veri.highest: "Verified Phone",
        }[value]
    except KeyError:
        logger.error("Failed to parse Verification Level %s", value)
        return value.name


def app_command_permission_update(entry: AuditLogEntry) -> str:
    app_extra = typing.cast(discord.Object, entry.extra)
    desc = f"Application ID #{app_extra.id}"
    if isinstance(entry.extra, discord.PartialIntegration):
        ex = entry.extra
        txt = f"{ex.name} ({ex.type} / {ex.id}) {ex.account.name}\n"
        desc += txt
    return desc


def automod_action(entry: AuditLogEntry) -> str:
    name = getattr(entry.extra, "automod_rule_name")

    trigger = getattr(entry.extra, "automod_rule_trigger_type")
    trigger = typing.cast(discord.AutoModRuleTriggerType, trigger)
    channel = getattr(entry.extra, "channel")
    channel = typing.cast(discord.TextChannel, channel)
    text = f"{name} ({trigger.name}) in <#{channel.id}>\n"
    return text


def member_disconnect(entry: AuditLogEntry) -> str:
    return f"{getattr(entry.extra, 'count')} users disconnected\n"


def member_move(entry: AuditLogEntry) -> str:
    chan: discord.TextChannel = getattr(entry.extra, "channel")
    return f"{getattr(entry.extra, 'count')} users moved to <#{chan.id}>\n"


def member_prune(entry: AuditLogEntry) -> str:
    # Extra is a proxy with two attributes
    # Fuck you we'll do it the really fucking ugly way
    days: int = getattr(entry.extra, "delete_member_days")
    removed: int = getattr(entry.extra, "members_removed")
    text = f"{removed} Members kicked for {days} Day Inactivity\n\n"
    return text


def message_delete(entry: AuditLogEntry) -> str:
    chn: discord.TextChannel = getattr(entry.extra, "channel")
    return f"{getattr(entry.extra, 'count')} messages deleted in <#{chn.id}>\n"


def message_bulk_delete(entry: AuditLogEntry) -> str:
    return f"{getattr(entry.extra, 'count')} messages deleted\n"


def message_pin(entry: AuditLogEntry) -> str:
    chan: discord.TextChannel = getattr(entry.extra, "channel")
    _id: int = getattr(entry.extra, "message_id")
    g_id: int = entry.guild.id

    # Build your own Jump URL.
    lnk = f"https://discord.com/{g_id}/{chan.id}/{_id}"
    return f"<#{chan.id}> [Message Pinned]({lnk})\n"


action = discord.AuditLogAction
action_desc = {
    action.app_command_permission_update: app_command_permission_update,
    action.member_disconnect: member_disconnect,
    action.member_move: member_move,
    action.member_prune: member_prune,
    action.message_delete: message_delete,
    action.message_bulk_delete: message_bulk_delete,
    action.message_pin: message_pin,
    action.message_unpin: message_pin,
    action.automod_block_message: automod_action,
    action.automod_flag_message: automod_action,
    action.automod_timeout_member: automod_action,
}


def iter_embed(
    entry: discord.AuditLogEntry,
    diff: discord.AuditLogDiff,
    main: bool = False,
    last: bool = False,
) -> Embed:
    # Diff is either entry.changes.before or entry.changes.after

    embed = Embed()
    embed.description = ""

    # Start by getting info about our Target.
    target = entry.target
    extra = entry.extra

    # Shorten

    # Build our Header Embed
    if main:
        embed.title = entry.action.name.replace("_", " ").title()

        if isinstance(target, discord.Object):
            embed.description = f"{target.type.__name__} {target.id}\n\n"

        elif isinstance(target, discord.Guild):
            ico = entry.guild.icon.url if entry.guild.icon else None
            embed.set_author(name=entry.guild.name, icon_url=ico)

        elif isinstance(target, discord.User | discord.Member):
            ico = target.display_avatar.url if target.display_avatar else None
            embed.set_author(name=f"{target} ({target.id})", icon_url=ico)
            embed.description = f"<@{target.id}>\n\n"

        elif isinstance(target, discord.abc.GuildChannel | discord.Thread):
            embed.set_author(name=f"{target.name} ({target.id})")

            parent: discord.TextChannel | discord.ForumChannel | None
            if parent := getattr(target, "parent", None):
                if parent:
                    embed.description += f"<#{parent.id}> -> "

            embed.description += f"<#{target.id}> ({target.type.name})\n\n"

        elif isinstance(target, discord.Role):
            embed.set_author(name=f"{target.name} ({target.id})")
            mems = len(target.members)
            embed.description = f"<@&{target.id}> ({mems} users)\n\n"

        elif isinstance(target, Emoji):
            embed.set_author(name=f"{target.name} ({target.id})")
            embed.set_thumbnail(url=target.url)
            embed.description = f"{str(target)} [Link]({target.url})\n\n"

        elif isinstance(target, discord.StageInstance):
            # There really isn't much info availabel here.
            if target.channel_id:
                embed.description = f"<#{target.channel_id}>"

        elif isinstance(target, discord.GuildSticker):
            embed.set_author(name=f"{target.name} ({target.id})")
            embed.set_thumbnail(url=target.url)

        elif isinstance(target, discord.Invite):
            ivt = target.inviter
            if ivt:
                ico = ivt.avatar.url if ivt.avatar else None
                embed.set_author(name=f"{ivt.name} ({ivt.id})", icon_url=ico)
            embed.description = f"{target.url}\n\n"

        elif isinstance(entry.target, discord.app_commands.AppCommand):
            cmd = typing.cast(discord.app_commands.AppCommand, entry.target)
            embed.set_author(name=f"{cmd.name} ({cmd.id})")
            embed.description += f"{cmd.mention}\n"

        elif isinstance(target, discord.PartialIntegration):
            # 😬 Fuck this shit.
            embed.set_author(name=f"{target.name} ({target.id})")

            aid = target.application_id
            if target.application_id:
                embed.description = f"<@{aid}>\n**App ID**: {aid}\n\n"

        elif isinstance(target, discord.AutoModRule):
            if target.creator:
                ctr = target.creator
                ico = ctr.display_avatar.url if ctr.display_avatar else None
                embed_utils.user_to_footer(embed, target.creator)
            embed.description = f"{target.name} ({target.id})\n\n"

        try:
            embed.description += action_desc[entry.action](entry)
        except KeyError:
            pass

        # Extra Handling.
        role_override = False
        user_override = False
        if extra is not None and hasattr(extra, "type"):
            role_override = isinstance(extra, discord.Role)
            user_override = isinstance(extra, discord.User)

        if role_override:
            role = typing.cast(discord.Role, extra)
            embed.description += f"<@&{role.id}>\n"

        if user_override:
            usr = typing.cast(discord.Member, extra)
            embed.description += f"<@{usr.id}>\n"

    for key, value in diff:
        if key == "actions":
            actions: list[discord.AutoModRuleAction] = value
            if actions:
                text = ""
                for i in actions:
                    text += f"{i.type.name}"

                    # For Timeouts
                    if i.duration:
                        text += f" for {i.duration}"

                    # For Warnings
                    if i.channel_id:
                        text += f" in <#{i.channel_id}>"
                    text += "\n"
                embed.add_field(name="Actions", value=text)

        elif key == "afk_channel":
            afk_chan: discord.VoiceChannel | None = value
            ch_id = afk_chan.id if afk_chan else None
            embed.description += f"**AFK Channel**: <#{ch_id}>"

        elif key == "afk_timeout":
            timeout: int = value
            to_txt = stringify_seconds(timeout)
            embed.description += f"**AFK Timeout**: {to_txt}"

        elif key == "allow":
            allow: discord.Permissions = value
            allowed = [f"✅ {k}" for k, v in iter(allow) if v]
            if allowed:
                embed.add_field(name="Allowed Perms", value=", ".join(allowed))
            else:
                embed.add_field(name="Allowed Perms", value="`None`")

        elif key == "app_command_permissions":
            perms: list[discord.app_commands.AppCommandPermissions] = value
            ac = discord.app_commands.AllChannels

            output = ""
            for i in perms:
                if isinstance(i.target, discord.Object):
                    ment = f"{i.target.id} ({i.target.type})"
                else:
                    ment = {
                        ac: "All Channels: <id:browse>",
                        discord.abc.GuildChannel: f"<#{i.target.id}>",
                        discord.TextChannel: f"<#{i.target.id}>",
                        discord.User: f"<@{i.target.id}>",
                        discord.Member: f"<@{i.target.id}>",
                        discord.Role: f"<@&{i.target.id}>",
                    }[type(i.target)]

                emoji = "✅" if i.permission else "❌"
                output += f"{emoji} {ment}\n"
            if output:
                embed.add_field(name="Permissions", value=output)

        elif key == "archived":
            archived: bool = value
            embed.description += f"**Archived**: {archived}\n"

        elif key == "auto_archive_duration":
            archive_time: int = value
            txt = stringify_minutes(archive_time)
            embed.description += f"**Archive Time**: {txt}\n"

        elif key == "available":
            # Sticker Availability
            available: bool = value
            embed.description += f"**Available**: `{available}`\n"

        elif key == "available_tags":
            a_tags: list[discord.ForumTag] = value
            txt = ""
            for i in a_tags:
                txt += f"{i.emoji} {i.name}"
                if i.moderated:
                    txt += " (Mod Only)"
            embed.add_field(name="Tags Changed", value=txt)

        elif key == "applied_tags":
            a_tags: list[discord.ForumTag] = value
            try:
                txt = [f"{i.emoji} {i.name}" for i in a_tags]
            except TypeError:
                txt = [i.name for i in a_tags]
            embed.add_field(name="Tags Changed", value=txt)

        elif key == "avatar":
            # User / Member Avatar
            avatar: discord.Asset | None = value

            if avatar:
                embed.set_thumbnail(url=avatar.url)
                embed.description += f"**Avatar**: [Link]({avatar})\n"
            else:
                embed.description += "**Avatar**: `None`\n"

        elif key == "banner":
            # Guild Banner
            banner: discord.Asset | None = value
            if banner:
                embed.set_image(url=banner.url)
                embed.description += f"**Banner**: [Link]({banner})\n"
            else:
                embed.description += "**Banner**: `None`\n"

        elif key == "bitrate":
            # Voice Channel Bitrate
            bitrate: int = value
            rate = str(bitrate / 1000) + "kbps"
            embed.description += f"**Bitrate**: {rate}\n"

        elif key == "channel":
            # Voice Channel Bitrate
            channel: discord.abc.GuildChannel = value
            ch_md = f"<#{channel.id}>" if channel else "`None`"
            embed.description += f"**Channel**: {ch_md}\n"

        elif key == "code":
            code: str = value
            embed.description += f"**Code**: {code}\n"

        elif key == "color":
            pass  # This is an alias to colour
        elif key == "colour":
            colour: discord.Colour = value
            embed.description += f"**Colour**: RGB{colour.to_rgb()}"

        elif key == "cover_image":
            # Scheduled Event Cover Image
            image: discord.Asset = value
            if image:
                embed.description += f"**Cover Image**: [Link]({image})\n"
                embed.set_image(url=image.url)
            else:
                embed.description += "**Cover Image**: `None`\n"

        elif key == "deaf":
            deaf: bool = value
            embed.description += f"**Server Deafened**: {deaf}\n"

        elif key == "default_auto_archive_duration":
            archive_time: int = value
            txt = stringify_minutes(archive_time)
            embed.description += f"**Default Archive Time**: {txt}\n"

        elif key == "default_notifications":
            # Guild Notification Level
            notif: discord.NotificationLevel = value
            txt = stringify_notification_level(notif)
            embed.description += f"**Notification Level**: {txt}\n"

        elif key == "deny":
            deny: discord.Permissions = value
            dny = [f"❌ {k}" for k, v in iter(deny) if v is False]
            if dny:
                embed.add_field(name="Denied Perms", value="None")
            else:
                embed.add_field(name="Denied Perms", value=", ".join(dny))

        elif key == "description":
            # Guild, Sticker, or Scheduled Event
            desc: str = value
            embed.description += f"**Description**: {desc}"

        elif key == "discovery_splash":
            image: discord.Asset = value
            short = "**Discover Image8*"
            if image:
                embed.description += f"{short}: [Link]({image})\n"
                embed.set_image(url=image.url)
            else:
                embed.description += "**Discovery Image**: `None`\n"

        elif key == "emoji":
            # The Emote of a guild sticker
            emoji: str = value
            embed.description += f"**Emote**: {emoji}\n"

        elif key == "enable_emoticons":
            # Emote Syncing for an integration
            em_enable: bool = value
            txt = "Enabled" if em_enable else "Disabled"
            embed.description += f"**Emote Syncing**: `{txt}`\n"

        elif key == "enabled":
            # Automod Rule Enabled
            em_enable: bool = value
            txt = "Enabled" if em_enable else "Disabled"
            embed.description += f"**Enabled**: `{txt}`\n"

        elif key == "entity_type":
            # Scheduled Event entity_type changed
            en_type: discord.EntityType = value
            embed.description += f"**Location Type**: {en_type}\n"

        elif key == "event_type":
            # The event type for triggering the automod rule.
            ev_type: discord.AutoModRuleEventType = value
            embed.description += f"**Event**: {ev_type.name}\n"

        elif key == "exempt_channels":
            # The list of channels or threads that are
            # exempt from the automod rule.
            e_chans: list[discord.TextChannel] = value
            ment = ", ".join([f"<#{i.id}>" for i in e_chans])
            embed.add_field(name="Exempt Channels", value=ment)

        elif key == "exempt_roles":
            # The list of channels or threads that are
            # exempt from the automod rule.
            e_roles: list[discord.Role | discord.Object] = value
            if e_roles:
                ment = ", ".join([f"<&{i.id}>" for i in e_roles])
                embed.add_field(name="Exempt Roles", value=ment)

        elif key == "expire_behavior":
            pass  # Alias
        elif key == "expire_behaviour":
            # The behaviour of expiring subscribers changed.
            # Twitch Subscriptions, e.g.
            behav: discord.ExpireBehavior = value
            if value == behav.kick:
                text = "Server Kick"
            elif value == behav.remove_role:
                text = "Role Removed"
            else:
                logger.error("Unhandled ExpireBehavior %s", value)
                text = "Unknown"
            embed.description += f"**Subscription Expiry**: {text}\n"

        elif key == "expire_grace_period":
            # Twitch Subscriptions, e.g.
            days: int = value
            embed.description += f"**Grace Period**: {days} Days\n"

        elif key == "explicit_content_filter":
            filt: discord.ContentFilter = value
            txt = stringify_content_filter(filt)
            embed.description += f"**Explcit Content Filter**: {txt}\n"

        elif key == "flags":
            if isinstance(value, discord.ChannelFlags):
                flags: discord.ChannelFlags = value
                embed.description += f"**Thread Pinned**: `{flags.pinned}`\n"

                req_tag = flags.require_tag
                embed.description += f"**Tag Required**: `{req_tag}`\n"

            elif value:
                logger.info("Action %s", entry.action)
                logger.info("Unhandled Target Type %s", type(entry.target))
                logger.info("Flags %s (Type %s)", value, type(value))

        elif key == "format_type":
            # Guild Sticker Format
            fmt: discord.StickerFormatType = value
            embed.description += f"**Format**: {fmt.name}\n"

        elif key == "hoist":
            # Guild Sticker Format
            hoist: bool = value
            embed.description += f"**Show Seperately**: `{hoist}`\n"

        elif key == "icon":
            # Guild or Role Icon
            image: discord.Asset = value
            if image:
                embed.description += f"**Icon**: [Link]({image})\n"
                embed.set_thumbnail(url=image.url)
            else:
                embed.description += "**Icon**: `None`\n"

        elif key == "id":
            # Literally anything
            _id: int = value
            embed.description += f"**ID**: {_id}\n"

        elif key == "invitable":
            # Can non-mods invite other users to a thread
            invitable: bool = value
            embed.description += f"**Invitable**: `{invitable}`\n"

        elif key == "inviter":
            # User who created the invite
            inviter: discord.Member | None = value
            if inviter:
                embed.description += f"**inviter**: `{inviter.mention}`\n"

        elif key == "location":
            if isinstance(value, str):
                embed.description += f"**Location**: {value}\n"
            else:
                logger.info("Location %s found of type %s", value, type(value))

        elif key == "locked":
            # Is thread locked
            locked: bool = value
            embed.description += f"**Locked**: `{locked}`\n"

        elif key == "max_age":
            # Max age of an invite, seconds.
            max_age: int = value
            txt = stringify_seconds(max_age)
            embed.description += f"**Max Age**: {txt}\n"

        elif key == "max_uses":
            # Maximum number of invite uses
            max_uses: int = value
            embed.description += f"**Max Uses**: {max_uses}\n"

        elif key == "mentionable":
            mentionable: bool = value
            embed.description += f"**Pingable**: `{mentionable}`\n"

        elif key == "mfa_level":
            mfa_level: discord.MFALevel = value
            txt = stringify_mfa(mfa_level)
            embed.description += f"**2FA Requirement**: {txt}\n"

        elif key == "mute":
            muted: bool = value
            embed.description += f"**Muted**: `{muted}`\n"

        elif key == "name":
            name: str = value
            embed.description += f"**Name**: {name}\n"

        elif key == "nick":
            nick: str = value
            embed.description += f"**Nickname**: {nick}\n"

        elif key == "nsfw":
            nsfw: bool = value
            embed.description += f"**NSFW**: `{nsfw}`\n"

        elif key == "overwrites":
            # A list of [target, permoverwrites] tuples for a channel
            # EXPLIT TRUE / None / EXPLICIT FALSE
            overwrites = value

            user_or_role: (
                discord.Member | discord.User | discord.Role | discord.Object
            )
            dow: discord.PermissionOverwrite

            output = ""
            for user_or_role, dow in overwrites:
                if user_or_role:
                    if isinstance(user_or_role, discord.Object):
                        if isinstance(user_or_role.type, discord.Role):
                            output += f"<@&{user_or_role.id}>"
                        else:
                            output += f"<@{user_or_role.id}>"
                    elif isinstance(user_or_role, discord.Role):
                        output += f"<@&{user_or_role.id}>"
                    else:
                        output += f"<@{user_or_role.id}>"
                else:
                    output += "????????????"

                rows: list[str] = []
                for k, val in dow:
                    if val is True:
                        rows.append(f"✅ {k}")
                    elif val is False:
                        rows.append(f"❌ {k}")
                    else:
                        pass  # Neutral / Unset.

                output += ", ".join(rows) + "\n\n"
            if output:
                embed.add_field(name="Permission Overwrites", value=output)

        elif key == "owner":
            owner: discord.User | discord.Member = value
            onr = owner.mention if owner else "None"
            embed.description += f"**Owner**: {onr}\n"

        elif key == "permissions":
            # List of permissions for a role
            permissions: discord.Permissions = value
            allowed = [f"✅ {k}" for k, v in iter(permissions) if v]

            lst = ", ".join(allowed) if allowed else "None"
            embed.add_field(name="Allowed Perms", value=lst)

        elif key == "position":
            # Role or Channel Position #
            pos: int = value
            embed.description += f"**Order**: {pos}\n"

        elif key == "preferred_locale":
            locale: discord.Locale = value
            text = locale.name if locale else "`None`"
            embed.description += f"**Preferred Locale**: {text}\n"

        elif key == "privacy_level":
            # Events & Stage Instances
            priv_lvl: discord.PrivacyLevel = value
            text = priv_lvl.name if priv_lvl else "`None`"
            embed.description += f"**Privacy Level**: {text}\n"

        elif key == "public_updates_channel":
            r_channel: discord.TextChannel | discord.Object = value
            text = f"<#{r_channel.id}>" if r_channel else "`None`"
            embed.description += f"**Rules Channel**: {text}\n"

        elif key == "prune_delete_days":
            # Inactive users are kicked after...
            prune: int = value
            text = f"{prune} Days" if prune else "`Never`"
            embed.description = f"**Inactivity Kick**: {text}\n"

        elif key == "roles":
            # List of roles being added or removed.
            roles: list[discord.Role | discord.Object] = value
            rls = ", ".join(f"<@&{i.id}>" for i in roles)
            if roles:
                if main:
                    embed.description += f"Roles Removed: {rls}"
                else:
                    embed.description += f"Roles Added: {rls}"

        elif key == "rtc_region":
            # Voice Chat Region
            region: str | None = value
            region = region if region else "`Automatic`"
            embed.description += f"**Region**: {region}\n"

        elif key == "rules_channel":
            r_channel: discord.TextChannel | discord.Object = value
            text = f"<#{r_channel.id}>" if r_channel else "`None`"
            embed.description += f"**Rules Channel**: {text}\n"

        elif key == "slowmode_delay":
            slowmode: int = value
            txt = stringify_seconds(slowmode)
            embed.description += f"**Slowmode**: {txt}\n"

        elif key == "splash":
            # Guild invite Splash
            image: discord.Asset = value
            if image:
                embed.description += f"**Splash Image**: {image.url}\n"
                embed.set_image(url=image.url)
            else:
                embed.description += "**Splash Image**: `None`\n"

        elif key == "status":
            # Guild invite Splash
            status: discord.EventStatus = value
            embed.description += f"**Status**: {status.name}\n"

        elif key == "system_channel":
            s_channel: discord.TextChannel | discord.Object = value
            text = f"<#{s_channel.id}>" if s_channel else "`None`"
            embed.description += f"**System Channel**: {text}\n"

        elif key == "temporary":
            temporary: bool = value
            embed.description += f"**Temporary**: `{temporary}`\n"

        elif key == "timed_out_until":
            # Member Timeout
            to_end: datetime.datetime | None = value

            if to_end:
                text = f"{timed_events.Timestamp(to_end).relative}"
            else:
                text = "`Not Timed Out`"
            embed.description += f"**Timeout Ends**: {text}\n"

        elif key == "topic":
            # StageChannel / TextChannel Topic
            topic: str = value
            embed.add_field(name="Topic", value=topic)

        elif key == "trigger":
            # Trigger for an automod rule
            trg: discord.AutoModTrigger = value

            if trg.allow_list:
                text = ", ".join(trg.allow_list)
                embed.add_field(name="Allowed Terms", value=text)

            if trg.keyword_filter:
                text = ", ".join(trg.keyword_filter)
                embed.add_field(name="Banned Terms", value=text)

            if trg.regex_patterns:
                rules: list[str] = []
                for i in trg.regex_patterns:
                    rules.append(f"`{discord.utils.escape_markdown(i)}`")
                text = ", ".join(rules)
                embed.add_field(name="Regex Patterns", value=text)

            if trg.presets:
                text = ", ".join([f"`{k}`" for k, v in trg.presets if v])
                embed.description += f"**Enabled Presets**: {text}\n"

            if trg.mention_limit:
                embed.description += f"**Mention Limit** {trg.mention_limit}\n"

        elif key == "trigger_type":
            # Trigger Type for an automod rule
            trg_t: discord.AutoModRuleTriggerType = value
            amt = discord.AutoModRuleTriggerType
            if trg_t == amt.harmful_link:
                embed.description += "**Trigger**: `Harmful Links`\n"
            elif trg_t == amt.keyword:
                embed.description += "**Trigger**: `Keywords`\n"
            elif trg_t == amt.keyword_preset:
                embed.description += "**Trigger**: `Keywords Presets`\n"
            elif trg_t == amt.mention_spam:
                embed.description += "**Trigger**: `Mention Spam`\n"
            elif trg_t == amt.spam:
                embed.description += "**Trigger**: `Spam`\n"

        elif key == "type":
            # Type of Channel / Sticker / Webhook / Integration
            _type: (
                discord.ChannelType
                | discord.StickerType
                | discord.WebhookType
                | str
            )
            _type = value
            if isinstance(_type, str):
                text = _type
            else:
                text = _type.name.replace("_", " ").title()
            embed.description += f"**Type**: {text}\n"

        elif key == "user_limit":
            embed.description += f"**User Limit**: {value}\n"  # int

        elif key == "unicode_emoji":
            embed.description += f"**Emoji**: {value}\n"  # Role Icon (str)

        elif key == "uses":
            embed.description += f"**Uses**: {value}\n"  # (int)

        elif key == "vanity_url_code":
            embed.description += f"**Vanity URL**: {value}\n"  # str

        elif key == "verification_level":
            txt = stringify_verification(value)  # discord.VerificationLevel
            embed.description += f"**Verification Level**: {txt}\n"

        elif key == "video_quality_mode":
            if value:
                text = value.name.title()  # discord.VideoQualityMode
                embed.description += f"**Video Quality**: {text}\n"

        elif key == "widget_channel":
            widge: discord.TextChannel | discord.Object = value
            embed.description += f"**Widget Channel**: <#{widge.id}>\n"

        elif key == "widget_enabled":
            widget: bool = value
            embed.description += f"**Widget Enabled**: `{widget}`\n"

        else:
            evt = entry.action
            logger.info("Unhandled key in changes %s %s (%s)", evt, key, value)

    # Build our Footer
    if last:
        embed.timestamp = entry.created_at
        if entry.user:
            reason = entry.reason
            embed_utils.user_to_footer(embed, entry.user, reason=reason)
    return embed


# TODO: Dropdown instead of Button
class ToggleButton(discord.ui.Button["LogsConfig"]):
    """A Button to toggle the notifications settings."""

    def __init__(self, db_key: str, value: bool, row: int = 0) -> None:
        self.value: bool = value
        self.db_key: str = db_key  # The Database Key this button correlates to

        style = discord.ButtonStyle.green if value else discord.ButtonStyle.red
        emoji: str = "🟢" if value else "🔴"  # None (Off)
        title: str = db_key.replace("_", " ").title()
        super().__init__(label=f"{title}", emoji=emoji, row=row, style=style)

    async def callback(self, interaction: Interaction) -> None:  # type: ignore
        """Set view value to button value"""
        assert self.view is not None
        await interaction.response.defer()
        bot = interaction.client
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = f"""UPDATE notifications_settings SET {self.db_key} =
                    $1 WHERE channel_id = $2"""
                chan_id = self.view.channel.id
                await connection.execute(sql, not self.value, chan_id)

        cog = interaction.client.get_cog(AuditLogs.__cog_name__)
        assert isinstance(cog, AuditLogs)
        await cog.update_cache()
        return await self.view.update(interaction)


class LogsConfig(view_utils.BaseView):
    """Generic Config View"""

    def __init__(self, invoker: User, channel: discord.TextChannel) -> None:
        super().__init__(invoker)

        self.channel: discord.TextChannel = channel

    async def update(
        self, interaction: Interaction, content: str | None = None
    ) -> None:
        """Regenerate view and push to message"""
        self.clear_items()

        if interaction.guild is None:
            raise commands.NoPrivateMessage

        sql = (
            """SELECT * FROM notifications_settings WHERE (channel_id) = $1"""
        )
        sq2 = """INSERT INTO notifications_channels (guild_id, channel_id)
                VALUES ($1, $2)"""
        sq3 = """INSERT INTO notifications_settings (channel_id) VALUES ($1)"""

        ch_id = self.channel.id
        g_id = self.channel.guild.id
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                if not (stg := await connection.fetchrow(sql, ch_id)):
                    await connection.execute(sq2, g_id, ch_id)
                    await connection.execute(sq3, ch_id)
                    return await self.update(interaction, content="Generating")

        embed = Embed(color=0x7289DA, title="Notification Logs config")
        embed.description = "Click buttons below to toggle logging events."

        row = 0
        for num, (k, value) in enumerate(sorted(stg.items())):
            if k == "channel_id":
                continue

            if num % 5 == 0:
                row += 1

            self.add_item(ToggleButton(db_key=k, value=value, row=row))
        edit = interaction.response.edit_message
        return await edit(content=content, embed=embed, view=self)


class AuditLogs(commands.Cog):
    """Set up Server Logs"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot = bot

    async def update_cache(self) -> None:
        """Get the latest database information and load it into memory"""
        sql = """SELECT * FROM notifications_channels LEFT OUTER JOIN
            notifications_settings ON notifications_channels.channel_id
            = notifications_settings.channel_id"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                self.notifications_cache = await connection.fetch(sql)

    async def cog_load(self) -> None:
        """When the cog loads"""
        await self.update_cache()

    async def get_channels(
        self, entry: discord.AuditLogEntry
    ) -> list[discord.TextChannel]:
        """Get a list of TextChannels that require a notification for this"""

        cache = self.notifications_cache

        channels = [i for i in cache if i["guild_id"] == entry.guild.id]
        if not channels:
            return []

        if entry.action == discord.AuditLogAction.message_delete:
            if isinstance(entry.target, (discord.User, discord.Member)):
                if entry.target.bot:
                    return []

        for setting in {
            Action.ban: ["bans"],
            Action.unban: ["bans"],
            Action.kick: ["kicks"],
            Action.member_disconnect: ["moderation"],
            Action.member_move: ["moderation"],
            Action.member_update: ["moderation"],
            Action.automod_flag_message: ["moderation"],
            Action.automod_block_message: ["moderation"],
            Action.automod_timeout_member: ["moderation"],
            Action.message_bulk_delete: ["deleted_messages"],
            Action.message_delete: ["deleted_messages"],
            Action.app_command_permission_update: ["bot_management"],
            Action.bot_add: ["bot_management"],
            Action.integration_create: ["bot_management"],
            Action.integration_update: ["bot_management"],
            Action.integration_delete: ["bot_management"],
            Action.webhook_create: ["bot_management"],
            Action.webhook_update: ["bot_management"],
            Action.webhook_delete: ["bot_management"],
            Action.automod_rule_create: ["bot_management"],
            Action.automod_rule_update: ["bot_management"],
            Action.automod_rule_delete: ["bot_management"],
            Action.emoji_create: ["emote_and_sticker"],
            Action.emoji_update: ["emote_and_sticker"],
            Action.emoji_delete: ["emote_and_sticker"],
            Action.sticker_create: ["emote_and_sticker"],
            Action.sticker_update: ["emote_and_sticker"],
            Action.sticker_delete: ["emote_and_sticker"],
            Action.guild_update: ["server"],
            Action.channel_create: ["channels"],
            Action.channel_update: ["channels"],
            Action.channel_delete: ["channels"],
            Action.message_pin: ["channels"],
            Action.message_unpin: ["channels"],
            Action.overwrite_create: ["channels"],
            Action.overwrite_update: ["channels"],
            Action.overwrite_delete: ["channels"],
            Action.stage_instance_create: ["channels"],
            Action.stage_instance_update: ["channels"],
            Action.stage_instance_delete: ["channels"],
            Action.thread_create: ["threads"],
            Action.thread_update: ["threads"],
            Action.thread_delete: ["threads"],
            Action.scheduled_event_create: ["events"],
            Action.scheduled_event_update: ["events"],
            Action.scheduled_event_delete: ["events"],
            Action.invite_create: ["invites"],
            Action.invite_update: ["invites"],
            Action.invite_delete: ["invites"],
            Action.role_create: ["role_edits"],
            Action.role_update: ["role_edits"],
            Action.role_delete: ["role_edits"],
            Action.member_role_update: ["user_roles"],
        }[entry.action]:
            channels = [i for i in channels if i[setting]]

        channels = [self.bot.get_channel(i["channel_id"]) for i in channels]
        channels = [i for i in channels if isinstance(i, discord.TextChannel)]
        return channels

    @commands.Cog.listener()
    async def on_audit_log_entry_create(
        self, entry: discord.AuditLogEntry
    ) -> None:
        channels = await self.get_channels(entry)

        if entry.category is discord.AuditLogActionCategory.create:
            before = None
            after = Embed()
            after.timestamp = entry.created_at

            after = iter_embed(
                entry, entry.changes.after, main=True, last=True
            )
        elif entry.category is discord.AuditLogActionCategory.delete:
            before = Embed()
            before.timestamp = entry.created_at

            before = iter_embed(
                entry, entry.changes.before, main=True, last=True
            )
            after = None
        else:
            after = iter_embed(entry, entry.changes.after, last=True)
            before = iter_embed(entry, entry.changes.before, main=True)

        embeds = [i for i in [before, after] if i]
        for i in channels:
            try:
                await i.send(embeds=embeds)
            except discord.HTTPException:
                continue

    # Join messages
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Event handler to Dispatch new member information
        for servers that request it"""

        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["joins"] and i["guild_id"] == member.guild.id:
                channel = self.bot.get_channel(i["channel_id"])
                if isinstance(channel, Messageable):
                    channels.append(channel)

        if not channels:
            return

        # Extended member join information.
        embed = Embed(colour=0x7289DA, title="Member Joined")
        embed_utils.user_to_author(embed, member)

        time = timed_events.Timestamp(member.created_at).date_relative
        embed.description = (
            f"{member.mention}\n"
            f"**Shared Servers**: {len(member.mutual_guilds)}\n"
            f"**Account Created**: {time}\n"
        )

        if flags := [k for k, val in member.flags if val]:
            embed.add_field(name="Flags", value=", ".join(flags))

        if flags := [k for k, val in member.public_flags if val]:
            embed.add_field(name="Public Flags", value=", ".join(flags))

        for channel in channels:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                continue
            except discord.HTTPException as err:
                logger.error(err)

    # Leave notif
    @commands.Cog.listener()
    async def on_raw_member_remove(
        self, payload: discord.RawMemberRemoveEvent
    ) -> None:
        """Event handler for outputting information about member kick, ban
        or other departures"""
        # Check if in mod action log and override to specific channels.
        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["joins"] and i["guild_id"] == payload.guild_id:
                channel = self.bot.get_channel(i["channel_id"])
                if isinstance(channel, Messageable):
                    channels.append(channel)

        if not channels:
            return

        user: User = payload.user
        embed = Embed(title="Member Left", description=user.mention)
        embed.colour = discord.Colour.dark_red()
        embed.timestamp = discord.utils.utcnow()
        embed_utils.user_to_author(embed, user)

        for channel in channels:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    # emojis notif
    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[Emoji],
        after: list[Emoji],
    ) -> None:
        """Event listener for outputting information about updated emojis"""
        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["emote_and_sticker"] and i["guild_id"] == guild.id:
                i = self.bot.get_channel(i["channel_id"])

                if isinstance(i, Messageable):
                    channels.append(i)

        if not channels:
            return

        embed = Embed(color=discord.Colour.dark_purple())

        # Find if it was addition or removal.

        def parse_emoji(emoji: Emoji, added: bool | None = None) -> Embed:
            new_embed = embed.copy()
            if emoji.roles:
                role = min(emoji.roles, key=lambda i: i.position).mention
            else:
                role = ""

            anim = "animated " if emoji.animated else ""
            if added:
                tit = f"New {anim}emote: {emoji.name}"
            else:
                tit = f"{anim}Emoji Removed"
            embed.set_author(name=f"Integration: {tit}", icon_url=TWTCH)

            if emoji.user is not None:
                new_embed.set_footer(text=emoji.user)

            new_embed.description = f"{emoji} {role}"
            new_embed.set_thumbnail(url=emoji.url)
            new_embed.set_footer(text=emoji.url)
            return new_embed

        new = [i for i in after if i not in before]
        removed = [i for i in before if i not in after]

        embeds: list[Embed] = []

        embeds += [parse_emoji(emoji, True) for emoji in new if emoji.managed]
        embeds += [parse_emoji(emoji) for emoji in removed if emoji.managed]

        for i in channels:
            try:
                await i.send(embeds=embeds)
            except discord.HTTPException:
                continue

    # Deleted message notif
    @commands.Cog.listener()
    async def on_message_delete(self, message: Message) -> None:
        """Event handler for reposting deleted messages from users"""
        if message.guild is None:
            return  # Ignore DMs

        if message.author.bot:
            return  # Ignore bots to avoid chain reaction

        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["deleted_messages"] and i["guild_id"] == message.guild.id:
                channel = message.guild.get_channel(i["channel_id"])
                if isinstance(channel, Messageable):
                    channels.append(channel)

        if not channels:
            return

        embed = Embed(colour=discord.Colour.yellow())
        embed.title = "Deleted Message"
        embed.timestamp = message.created_at
        embed_utils.user_to_footer(embed, message.author)

        embed.description = f"<#{message.channel.id}>\n\n{message.content}"

        atts: list[discord.File] = []
        dels = Embed(title="Attachments")
        dels.description = ""
        for num, i in enumerate(message.attachments):
            type_ = i.content_type
            url = i.proxy_url
            val = f"{num}. {i.filename} [{type_}]({url}) ({i.size})\n"
            dels.description += val
            try:
                atts.append(await i.to_file(spoiler=True, use_cached=True))
            except discord.HTTPException:
                pass

        if not atts:
            dels = None

        embeds = [i for i in [embed, dels] if i]
        for channel in channels:
            try:
                await channel.send(embeds=embeds, files=atts)
            except discord.HTTPException:
                continue

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[Message]):
        """Iter message_delete"""
        guild = messages[0].guild
        if guild is None:
            return

        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["deleted_messages"] and i["guild_id"] == guild.id:
                channel = self.bot.get_channel(i["channel_id"])
                if isinstance(channel, Messageable):
                    channels.append(channel)

        if not channels:
            return

        for i in messages:
            await self.on_message_delete(i)

    @commands.Cog.listener()
    async def on_message_edit(self, before: Message, after: Message) -> None:
        """Edited message output."""
        if before.guild is None:
            return

        if before.attachments == after.attachments:
            if before.content == after.content:
                return

        if before.author.bot:
            return

        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["edited_messages"] and i["guild_id"] == before.guild.id:
                i = self.bot.get_channel(i["channel_id"])
                if isinstance(i, Messageable):
                    channels.append(i)

        if not channels:
            return

        if before.reference:
            reply = Embed()
            if before.reference:
                if before.reference.cached_message:
                    cache = before.reference.cached_message
                    auth = cache.author
                    ico = auth.display_avatar.url
                    if auth:
                        txt = f"Replying to {auth}"
                        reply.set_author(name=txt, icon_url=ico)
                        reply.timestamp = cache.created_at
                    reply.set_footer(text=cache.content)
        else:
            reply = None

        if before.content != after.content:
            embed = Embed(title="Message Edited")
            embed_utils.user_to_footer(embed, before.author)
            embed.colour = discord.Colour.brand_red()
            embed.description = f"<#{before.channel.id}>\n> {before.content}"
            embed.timestamp = before.created_at

            embe2 = Embed(colour=discord.Colour.brand_green())
            embe2.timestamp = after.edited_at
            embe2.description = f"> {after.content}"

            if after.edited_at is not None:
                delta = after.edited_at - before.created_at
                embe2.set_footer(text=f"Message edited after Delay: {delta}")
        else:
            embed = embe2 = None

        atts: list[discord.File] = []
        if before.attachments != after.attachments:
            att = [i for i in before.attachments if i not in after.attachments]
            gone = Embed(title="Removed Attachments")
            gone.description = ""
            for num, i in enumerate(att, 1):
                type_ = i.content_type
                url = i.proxy_url

                size = i.size / 1000
                val = f"{num}. {i.filename} [{type_}({url}) ({size}kb)\n"
                gone.description += val
                try:
                    atts.append(await i.to_file(spoiler=True, use_cached=True))
                except discord.HTTPException:
                    pass
        else:
            gone = None

        view = discord.ui.View()
        uri = before.jump_url
        btn: discord.ui.Button[discord.ui.View] = discord.ui.Button(url=uri)
        btn.label = "Jump to message"
        view.add_item(btn)

        embeds = [i for i in [reply, embed, embe2, gone] if i]
        for i in channels:
            try:
                await i.send(embeds=embeds, view=view, files=atts)
            except (discord.Forbidden, discord.NotFound):
                continue

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        """Triggered when a user updates their profile"""
        guilds = [i.id for i in self.bot.guilds if i.get_member(after.id)]

        cache = self.notifications_cache
        channels: list[Messageable] = []
        for i in cache:
            if i["users"] and i["guild_id"] in guilds:
                channel = self.bot.get_channel(i["channel_id"])
                if isinstance(channel, Messageable):
                    channels.append(channel)

        if not channels:
            return

        # Key, Before, After
        embed = Embed(colour=discord.Colour.dark_gray())
        embed_utils.user_to_footer(embed, before)
        embed.description = ""
        embed.timestamp = discord.utils.utcnow()

        if before.name != after.name:
            embed.description += f"**Name**: {before.name} -> {after.name}\n"

        if before.discriminator != after.discriminator:
            bf_d = before.discriminator
            af_d = after.discriminator
            embed.description += f"**Discriminator**: {bf_d} -> {af_d}\n"

        if before.display_avatar != after.display_avatar:
            bfi = before.display_avatar
            afi = after.display_avatar
            embed.description += f"**Avatar**: [Old]({bfi}) -> [New]({afi})\n"
            if bfi:
                embed.set_thumbnail(url=bfi)
            if afi:
                embed.set_thumbnail(url=afi)

        for channel in channels:
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.NotFound):
                continue

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(view_audit_log=True)
    async def logs(
        self,
        interaction: Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Create moderator logs in this channel."""

        await interaction.response.defer()
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        return await LogsConfig(interaction.user, channel).update(interaction)


async def setup(bot: Bot | PBot) -> None:
    """Loads the notifications cog into the bot"""
    await bot.add_cog(AuditLogs(bot))
