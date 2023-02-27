"""Notify server moderators about specific events"""
# TODO: Fallback parser using regular events -- Check if bot has
# view_audit_log perms
# TODO: Split /logs command into subcommands with sub-views & Parent.
from __future__ import annotations

import datetime
import typing
import discord
from discord.ext import commands
import logging

from typing import Optional, TYPE_CHECKING

from ext.utils import view_utils, timed_events

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

logger = logging.getLogger("AuditLogs")

action = discord.AuditLogAction


TWTCH = (
    "https://seeklogo.com/images/T/"
    "twitch-tv-logo-51C922E0F0-seeklogo.com.png"
)


# We don't need to db call every single time an event happens, just when
# config is updated So we cache everything and store it in memory
# instead for performance and sanity reasons.
async def update_cache(bot: Bot | PBot) -> None:
    """Get the latest database information and load it into memory"""
    q = """SELECT * FROM notifications_channels LEFT OUTER JOIN
        notifications_settings ON notifications_channels.channel_id
        = notifications_settings.channel_id"""
    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            bot.notifications_cache = await connection.fetch(q)


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
            logging.info("Unhandled archive duration %s", value)
            return str(value)


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
            logger.info(f"Stringify - Unhandled Seconds: {value}")
            return f"{value} Seconds"


def stringify_content_filter(value: discord.ContentFilter) -> str:
    """Convert Enum to human string"""
    match value:
        case discord.ContentFilter.all_members:
            return "Check All Members"
        case discord.ContentFilter.no_role:
            return "Check Un-roled Members"
        case discord.ContentFilter.disabled:
            return "Disabled"


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


def iter_embed(
    entry: discord.AuditLogEntry,
    diff: discord.AuditLogDiff,
    main: bool = False,
    last: bool = False,
) -> discord.Embed:

    # Diff is either entry.changes.before or entry.changes.after

    embed = discord.Embed()
    embed.description = ""

    # Start by getting info about our Target.
    target = entry.target
    extra = entry.extra

    # Shorten
    action = discord.AuditLogAction

    # Build our Header Embed
    if main:
        embed.title = entry.action.name.replace('_', ' ').title()

        # TODO: Overrides Go Here.
        if isinstance(target, discord.Object):
            embed.description = f"{target.type} {target.id}"
            logger.info(f"Object with {target.type} / {target.id} not handled")
            # TODO: Overrides Come out here.

        elif isinstance(target, discord.Guild):
            ico = entry.guild.icon.url if entry.guild.icon else None
            embed.set_author(name=entry.guild.name, icon_url=ico)

        elif isinstance(target, discord.Member | discord.User):
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

        elif isinstance(target, discord.Emoji):
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
                embed.set_author(name=f"{ctr} ({ctr.id})", icon_url=ico)
            embed.description = f"{target.name} ({target.id})\n\n"

        elif target:
            logger.info(f"Target {target} not handled.")

        if entry.action == action.member_prune:
            # Extra is a proxy with two attributes
            # Fuck you we'll do it the really fucking ugly way
            days: int = getattr(extra, "delete_member_days")
            removed: int = getattr(extra, "members_removed")
            text = f"{removed} Members kicked for {days} Day Inactivity\n\n"
            embed.description += text

        elif entry.action == action.member_move:
            # This might also be an object, but we only want the ID
            ch: discord.TextChannel = getattr(extra, "channel")
            count: int = getattr(extra, "count")
            embed.description += f"{count} users moved to <#{ch.id}>\n"

        elif entry.action == action.member_disconnect:
            count: int = getattr(extra, "count")
            embed.description += f"{count} users disconnected\n"

        elif entry.action == action.message_delete:
            ch: discord.TextChannel = getattr(extra, "channel")
            count: int = getattr(extra, "count")
            embed.description += f"{count} messages deleted in <#{ch.id}>\n"

        elif entry.action == action.message_bulk_delete:
            count: int = getattr(extra, "count")
            embed.description += f"{count} messages deleted\n"

        elif entry.action in (
            action.message_pin,
            action.message_unpin,
        ):
            ch: discord.TextChannel = getattr(extra, "channel")
            _id: int = getattr(extra, "message_id")
            g: int = entry.guild.id

            # Build your own Jump URL.
            lnk = f"https://discord.com/{g}/{ch.id}/{_id}"
            embed.description += f"<#{ch.id}> [Message Pinned]({lnk})\n"

        elif entry.action == action.app_command_permission_update:
            # Yike. Fuck. Shit
            if isinstance(extra, discord.Object):
                app_extra = typing.cast(discord.Object, entry.extra)
                embed.description += f"Application ID #{app_extra.id}"
            elif isinstance(extra, discord.PartialIntegration):
                ex = typing.cast(discord.PartialIntegration, extra)
                txt = f"{ex.name} ({ex.type} / {ex.id}) {ex.account.name}\n"
                embed.description += txt

        elif entry.action in [
            action.automod_block_message,
            action.automod_flag_message,
            action.automod_timeout_member,
        ]:
            name = getattr(entry, "automod_rule_name")
            trigger = getattr(entry, "automod_rule_trigger")
            trigger = typing.cast(discord.AutoModRuleTriggerType, trigger)
            channel = getattr(entry, "channel")
            channel = typing.cast(discord.TextChannel, channel)

            text = f"{name} ({trigger.name}) in <#{channel.id}>\n"
            embed.description += text

        else:
            # Extra Handling.
            role_override = False
            user_override = False
            if isinstance(extra, discord.Object):
                x: discord.Object = extra
                role_override = x.type == "role"
                user_override = x.type == "user"

            if isinstance(extra, discord.Role) or role_override:
                role = typing.cast(discord.Role, extra)
                embed.description += f"<@&{role.id}>\n"

            if (
                isinstance(extra, discord.Member | discord.User)
                or user_override
            ):
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
                        text += f" in <#{i.channel_id}"
                    text += "\n"
                embed.add_field(name=key, value=text)

        elif key == "afk_channel":
            afk_chan: discord.VoiceChannel | None = value
            ch_id = afk_chan.id if afk_chan else None
            embed.description += f"**AFK Channel**: <#{ch_id}>"

        elif key == "afk_timeout":
            timeout: int = value
            to = stringify_seconds(timeout)
            embed.description += f"**AFK Timeout**: {to}"

        elif key == "allow":
            allow: discord.Permissions = value
            allowed = [f"✅ {k}" for k, v in iter(allow) if v]
            if allowed:
                embed.add_field(name="Allowed Perms", value=", ".join(allowed))
            else:
                embed.add_field(name="Allowed Perms", value="None")

        elif key == "app_command_permissions":
            perms: list[discord.app_commands.AppCommandPermissions] = value
            ac = discord.app_commands.AllChannels

            output = ""
            for p in perms:
                if isinstance(p.target, discord.Object):
                    ment = f"{p.target.id} ({p.target.type})"
                else:
                    ment = {
                        ac: "All Channels: <id:browse>",
                        discord.abc.GuildChannel: f"<#{p.target.id}>",
                        discord.User: f"<@{p.target.id}>",
                        discord.Member: f"<@{p.target.id}>",
                        discord.Role: f"<@&{p.target.id}>",
                    }[type(p.target)]

                emoji = "✅" if p.permission else "❌"
                output += f"{emoji} {ment}\n"
            if output:
                embed.add_field(name="Permissions", value=output)

        elif key == "archived":
            archived: bool = value
            embed.description += f"**Archived**: {archived}\n"

        elif key == "auto_archive_duration":
            archive_time: int = value
            s = stringify_minutes(archive_time)
            embed.description += f"**Archive Time**: {s}\n"

        elif key == "auto_archive_duration":
            # Thread Archiving
            available: bool = value
            embed.description += f"**Available**: `{available}`\n"

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
            br = str(bitrate / 1000) + "kbps"
            embed.description += f"**Bitrate**: {br}\n"

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
            s = stringify_minutes(archive_time)
            embed.description += f"**Default Archive Time**: {s}\n"

        elif key == "default_notifications":
            # Guild Notification Level
            notif: discord.NotificationLevel = value
            s = stringify_notification_level(notif)
            embed.description += f"**Notification Level**: {s}\n"

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
            s = "Enabled" if em_enable else "Disabled"
            embed.description += f"**Emote Syncing**: `{s}`\n"

        elif key == "enabled":
            # Automod Rule Enabled
            em_enable: bool = value
            s = "Enabled" if em_enable else "Disabled"
            embed.description += f"**Enabled**: `{s}`\n"

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
            e_chans: list = value
            ment = ", ".join([f"<#{i.id}>" for i in e_chans])
            embed.add_field(name="Exempt Channels", value=ment)

        elif key == "exempt_roles":
            # The list of channels or threads that are
            # exempt from the automod rule.
            e_roles: list[discord.Role | discord.Object] = value
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
            s = stringify_content_filter(filt)
            embed.description += f"**Explcit Content Filter**: {s}\n"

        elif key == "flags":
            if isinstance(value, discord.ChannelFlags):
                flags: discord.ChannelFlags = value
                embed.description += f"**Thread Pinned**: `{flags.pinned}`\n"

                rt = flags.require_tag
                embed.description += f"**Tag Required**: `{rt}`\n"

            else:
                logger.info("Action %s", entry.action)
                logger.info("Unhandled Flag Type", type(entry.target))
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
            inviter: Optional[discord.Member] = value
            if inviter:
                embed.description += f"**inviter**: `{inviter.mention}`\n"

        elif key == "locked":
            # Is thread locked
            locked: bool = value
            embed.description += f"**Locked**: `{locked}`\n"

        elif key == "max_age":
            # Max age of an invite, seconds.
            max_age: int = value
            s = stringify_seconds(max_age)
            embed.description += f"**Max Age**: {s}\n"

        elif key == "max_uses":
            # Maximum number of invite uses
            max_uses: int = value
            embed.description += f"**Max Uses**: {max_uses}\n"

        elif key == "mentionable":
            mentionable: bool = value
            embed.description += f"**Pingable**: `{mentionable}`\n"

        elif key == "mfa_level":
            mfa_level: discord.MFALevel = value
            s = stringify_mfa(mfa_level)
            embed.description += f"**2FA Requirement**: {s}\n"

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
            ow: discord.PermissionOverwrite

            output = ""
            for user_or_role, ow in overwrites:
                if user_or_role is not None:
                    if isinstance(user_or_role, discord.Object):
                        if user_or_role.type == "role":
                            output += f"<@&{user_or_role.id}>"
                        else:
                            output += f"<@{user_or_role.id}>"
                    elif isinstance(user_or_role, discord.Role):
                        output += f"<@&{user_or_role.id}>"
                    else:
                        output += f"<@{user_or_role.id}>"
                else:
                    output += "????????????"

                rows = []
                for k, v in ow:
                    if v is True:
                        rows.append(f"✅ {k}")
                    elif v is False:
                        rows.append(f"❌ {k}")
                    else:
                        pass  # Neutral / Unset.

                output += ", ".join(rows) + "\n\n"
            if output:
                embed.add_field(name="Permission Overwrites", value=output)

        elif key == "owner":
            owner: discord.Member | discord.User = value
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

        elif key == "prune_delete_days":
            # Inactive users are kicked after...
            prune: int = value
            text = f"{prune} Days" if prune else "`Never`"
            embed.description = f"**Inactivity Kick**: {text}\n"

        elif key == "roles":
            # List of roles being added or removed.
            roles: list[discord.Role | discord.Object] = value
            text = ", ".join(f"<@&{i.id}>" for i in roles)
            embed.description += f"{text}\n\n"

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
            s = stringify_seconds(slowmode)
            embed.description += f"**Slowmode**: {s}\n"

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
            to_end: Optional[datetime.datetime] = value

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
                rules = []
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
            elif trg_t == amt.mention_spam:
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
            # Role Icon
            limit: int = value
            embed.description += f"**User Limit**: {limit}\n"

        elif key == "unicode_emoji":
            # Role Icon
            emoji: str = value
            embed.description += f"**Emoji**: {emoji}\n"

        elif key == "uses":
            # Invite Uses
            uses: int = value
            embed.description += f"**Uses**: {uses}\n"

        elif key == "vanity_code_url":
            # Server Custom invite
            vanity: str = value
            embed.description += f"**Vanity URL**: {vanity}\n"

        elif key == "verification_level":
            # Server Vericaition Level
            verify: discord.VerificationLevel = value
            s = stringify_verification(verify)
            embed.description += f"**Verification Level**: {s}\n"

        elif key == "video_quality_mode":
            # VC Video Quality
            vq: discord.VideoQualityMode = value
            embed.description += f"**Videeo Quality**: {vq.name.title()}\n"

        elif key == "widget_channel":
            widge: discord.TextChannel | discord.Object = value
            embed.description += f"**Widget Channel**: <#{widge.id}>\n"

        elif key == "widget_enabled":
            widget: bool = value
            embed.description += f"**Widget Enabled**: `{widget}`\n"

        else:
            logger.info("Unhandled key in changes %s (%s)", key, value)

    # Build our Footer
    if last:
        embed.timestamp = entry.created_at
        if u := entry.user:
            ico = u.display_avatar.url if u.display_avatar else None
            reason = "\n" + entry.reason if entry.reason else ""
            embed.set_footer(text=f"{u.name}\n{u.id}{reason}", icon_url=ico)

    return embed


class ToggleButton(discord.ui.Button):
    """A Button to toggle the notifications settings."""

    view: LogsConfig

    def __init__(self, db_key: str, value: bool, row: int = 0) -> None:
        self.value: bool = value
        self.db_key: str = db_key  # The Database Key this button correlates to

        style = discord.ButtonStyle.green if value else discord.ButtonStyle.red
        emoji: str = "🟢" if value else "🔴"  # None (Off)
        title: str = db_key.replace("_", " ").title()
        super().__init__(label=f"{title}", emoji=emoji, row=row, style=style)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.Message:
        """Set view value to button value"""

        await interaction.response.defer()
        bot = interaction.client
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = f"""UPDATE notifications_settings SET {self.db_key} =
                    $1 WHERE channel_id = $2"""
                c = self.view.channel.id
                await connection.execute(q, not self.value, c)

        await update_cache(interaction.client)
        return await self.view.update()


class LogsConfig(view_utils.BaseView):
    """Generic Config View"""

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        channel: discord.TextChannel,
    ) -> None:

        super().__init__(interaction)

        self.channel: discord.TextChannel = channel

    async def on_timeout(self) -> None:
        """Hide menu on timeout."""
        return await self.interaction.delete_original_response()

    async def update(self, content: Optional[str] = None) -> discord.Message:
        """Regenerate view and push to message"""
        self.clear_items()

        if self.interaction.guild is None:
            raise

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
                    return await self.update(content="Generating...")

        embed = discord.Embed(color=0x7289DA, title="Notification Logs config")
        embed.description = "Click buttons below to toggle logging events."

        row = 0
        for num, (k, v) in enumerate(sorted(stg.items())):
            if k == "channel_id":
                continue

            if num % 5 == 0:
                row += 1

            self.add_item(ToggleButton(db_key=k, value=v, row=row))
        self.add_item(view_utils.Stop(row=4))

        i = self.interaction
        return await self.bot.reply(i, content, embed=embed, view=self)


class AuditLogs(commands.Cog):
    """Set up Server Logs"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """When the cog loads"""
        await update_cache(self.bot)

    async def get_channels(
        self, entry: discord.AuditLogEntry
    ) -> list[discord.TextChannel]:

        c = self.bot.notifications_cache

        channels = [i for i in c if i["guild_id"] == entry.guild.id]
        if not channels:
            return []

        match entry.action:
            # Kicks, Bans, Moderation
            case action.ban | action.unban:
                field = ["bans"]
            case action.kick:
                field = ["kicks"]
            case (
                action.member_disconnect
                | action.member_move
                | action.member_update
                | action.automod_flag_message
                | action.automod_block_message
                | action.automod_timeout_member
            ):
                field = ["moderation"]
            case action.message_bulk_delete | action.message_delete:
                field = ["deleted_messages"]

            # Bots, Integrations, and Webhooks
            case (
                action.app_command_permission_update
                | action.bot_add
                | action.integration_create
                | action.integration_update
                | action.integration_delete
                | action.webhook_create
                | action.webhook_update
                | action.webhook_delete
                | action.automod_rule_create
                | action.automod_rule_update
                | action.automod_rule_delete
            ):
                field = ["bot_management"]

            # Emotes and stickers
            case (
                action.emoji_create
                | action.emoji_update
                | action.emoji_delete
                | action.sticker_create
                | action.sticker_update
                | action.sticker_delete
            ):
                field = ["emote_and_sticker"]

            # Server, Channels and Threads
            case action.guild_update:
                field = ["server"]
            case (
                action.channel_create
                | action.channel_update
                | action.channel_delete
                | action.message_pin
                | action.message_unpin
                | action.overwrite_create
                | action.overwrite_update
                | action.overwrite_delete
                | action.stage_instance_create
                | action.stage_instance_update
                | action.stage_instance_delete
            ):
                field = ["channels"]

            # Threads
            case (
                action.thread_create
                | action.thread_update
                | action.thread_delete
            ):
                field = ["threads"]
            # Events
            case (
                action.scheduled_event_create
                | action.scheduled_event_update
                | action.scheduled_event_delete
            ):
                field = ["events"]

            # Invites
            case (
                action.invite_create
                | action.invite_update
                | action.invite_delete
            ):
                field = ["invites"]

            # Roles
            case (
                action.role_create | action.role_update | action.role_delete
            ):
                field = ["role_edits"]

            case action.member_role_update:
                field = ["user_roles"]
            case _:
                logger.info(f"Unhandled Audit Log Action Type {entry.action}")
                field = []

        for setting in field:
            channels = [i for i in channels if i[setting]]

        channels = [self.bot.get_channel(i["channel_id"]) for i in channels]
        channels = [i for i in channels if isinstance(i, discord.TextChannel)]
        return channels

    @commands.Cog.listener()
    async def on_audit_log_entry_create(
        self, entry: discord.AuditLogEntry
    ) -> None:

        channels = await self.get_channels(entry)

        match entry.category:
            case discord.AuditLogActionCategory.create:
                before = None
                after = discord.Embed()
                after.timestamp = entry.created_at

                after = iter_embed(entry, entry.changes.after, main=True)
            case discord.AuditLogActionCategory.delete:
                before = discord.Embed()
                before.timestamp = entry.created_at

                before = iter_embed(entry, entry.changes.before)
                after = None
            case discord.AuditLogActionCategory.update:
                after = iter_embed(entry, entry.changes.after)
                before = iter_embed(entry, entry.changes.before)
            case None:
                before = after = None

        # Handle View Creation
        view = None

        embeds = [i for i in [before, after] if i]
        for ch in channels:
            try:
                if view:
                    await ch.send(embeds=embeds, view=view)
                else:
                    await ch.send(embeds=embeds)
            except discord.HTTPException:
                continue

    # Join messages
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Event handler to Dispatch new member information
        for servers that request it"""

        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["joins"] and i["guild_id"] == member.guild.id:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        # Extended member join information.
        e = discord.Embed(colour=0x7289DA, title="Member Joined")
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

        for channel in channels:
            try:
                await channel.send(embed=e)
            except discord.Forbidden:
                continue
            except discord.HTTPException as err:
                logging.error(err)

    # Leave notif
    @commands.Cog.listener()
    async def on_raw_member_remove(
        self, payload: discord.RawMemberRemoveEvent
    ) -> None:
        """Event handler for outputting information about member kick, ban
        or other departures"""
        # Check if in mod action log and override to specific channels.
        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["joins"] and i["guild_id"] == payload.guild_id:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        u: discord.User | discord.Member = payload.user
        e = discord.Embed(title="Member Left", description=u.mention)
        e.colour = discord.Colour.dark_red()
        e.timestamp = discord.utils.utcnow()

        e.set_author(name=f"{u} ({u.id})", icon_url=u.display_avatar.url)
        for ch in channels:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                pass

    # emojis notif
    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        """Event listener for outputting information about updated emojis"""
        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["emote_and_sticker"] and i["guild_id"] == guild.id:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        embed = discord.Embed(color=discord.Colour.dark_purple())
        embed.set_author(name="Twitch Integration", icon_url=TWTCH)
        # Find if it was addition or removal.

        def parse_emoji(emoji, added: bool = False) -> discord.Embed:
            e = embed.copy()
            if emoji.roles:
                roles = ", ".join([i.mention for i in emoji.roles])
                e.add_field(name="Available to roles", value=roles)

            anim = "animated " if emoji.animated else ""
            if added:
                e.title = f"New {anim}emote: {emoji.name}"
            else:
                e.title = f"{anim}Emoji Removed"

            e.description = f"{emoji}"
            e.set_image(url=emoji.url)
            e.set_footer(text=emoji.url)
            return e

        new = [i for i in after if i not in before]
        removed = [i for i in before if i not in after]

        embeds: list[discord.Embed] = []

        embeds += [parse_emoji(emoji, True) for emoji in new if emoji.managed]
        embeds += [parse_emoji(emoji) for emoji in removed if emoji.managed]

        for ch in channels:
            try:
                await ch.send(embeds=embeds)
            except discord.HTTPException:
                continue

    # Deleted message notif
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Event handler for reposting deleted messages from users"""
        if message.guild is None:
            return  # Ignore DMs

        if message.author.bot:
            return  # Ignore bots to avoid chain reaction

        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["deleted_messages"] and i["guild_id"] == message.guild.id:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        e = discord.Embed(colour=discord.Colour.yellow())
        e.title = "Deleted Message"
        e.timestamp = message.created_at

        au = message.author
        e.set_author(name=f"{au} ({au.id})", icon_url=au.display_avatar.url)

        e.description = f"<#{message.channel.id}>\n\n{message.content}"
        attachments: list[discord.File] = []

        files = []
        dels = discord.Embed(title="Attachments")
        dels.description = ""
        for num, i in enumerate(message.attachments):
            type_ = i.content_type
            url = i.proxy_url
            val = f"{num}. {i.filename} ({type_})[{url}] ({i.size})\n"
            dels.description += val
            files.append(await i.to_file(spoiler=True, use_cached=True))
        else:
            dels = None

        embeds = [i for i in [e, dels] if i]
        for ch in channels:
            try:
                await ch.send(embeds=embeds, files=attachments)
            except discord.HTTPException:
                continue

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        """Iter message_delete"""
        guild = messages[0].guild
        if guild is None:
            return

        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["deleted_messages"] and i["guild_id"] == guild.id:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        for x in messages:
            await self.on_message_delete(x)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """Edited message output."""
        if before.guild is None:
            return

        if before.attachments == after.attachments:
            if before.content == after.content:
                return

        if before.author.bot:
            return

        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["edited_messages"] and i["guild_id"] == before.guild.id:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        delta = after.created_at - before.created_at

        u = before.author

        if before.reference:
            reply = discord.Embed()
            if before.reference:
                if before.reference.cached_message:
                    cache = before.reference.cached_message
                    au = cache.author
                    ico = au.display_avatar.url
                    if au:
                        txt = f"Replying to {au}"
                        reply.set_author(name=txt, icon_url=ico)
                        reply.timestamp = cache.created_at
                    reply.set_footer(text=cache.content)
        else:
            reply = None

        if before.content != after.content:
            e = discord.Embed(title="Message Edited")
            e.set_author(name=f"{u} ({u.id})", icon_url=u.display_avatar.url)
            e.colour = discord.Colour.brand_red()
            e.description = f"<#{before.channel.id}>\n> {before.content}"
            e.timestamp = before.created_at

            e2 = discord.Embed(colour=discord.Colour.brand_green())
            e2.timestamp = after.edited_at
            e2.description = f"> {after.content}"
            e2.set_footer(text=f"Message edited after Delay: {delta}")
        else:
            e = e2 = None

        files = []
        if before.attachments != after.attachments:
            att = [i for i in before.attachments if i not in after.attachments]
            gone = discord.Embed(title="Removed Attachemnts")
            gone.description = ""
            for num, i in enumerate(att):
                type_ = i.content_type
                url = i.proxy_url
                val = f"{num}. {i.filename} ({type_})[{url}] ({i.size})\n"
                gone.description += val
                files.append(await i.to_file(spoiler=True, use_cached=True))
        else:
            gone = None

        v = discord.ui.View()
        uri = before.jump_url
        btn = discord.ui.Button(style=discord.ButtonStyle.url, url=uri)
        btn.label = "Jump to message"
        v.add_item(btn)

        embeds = [i for i in [reply, e, e2, gone] if i]
        for ch in channels:
            try:
                await ch.send(embeds=embeds, view=v, files=files)
            except (discord.Forbidden, discord.NotFound):
                continue

    @commands.Cog.listener()
    async def on_user_update(self, bf: discord.User, af: discord.User):
        """Triggered when a user updates their profile"""
        guilds = [i.id for i in self.bot.guilds if i.get_member(af.id)]

        cache = self.bot.notifications_cache
        channels = []
        for i in cache:
            if i["users"] and i["guild_id"] in guilds:
                ch = self.bot.get_channel(i["channel_id"])
                if ch is not None:
                    channels.append(ch)

        if not channels:
            return

        before = discord.Embed(colour=discord.Colour.dark_gray())
        ico = bf.display_avatar.url
        before.set_author(name=f"{bf.name} ({bf.id})", icon_url=ico)
        after = discord.Embed(colour=discord.Colour.light_gray())

        before.description = ""
        after.description = ""

        after.timestamp = discord.utils.utcnow()

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

        for ch in channels:
            try:
                await ch.send(embeds=[before, after])
            except (discord.Forbidden, discord.NotFound):
                continue

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(view_audit_log=True)
    async def logs(
        self,
        interaction: discord.Interaction[Bot],
        channel: Optional[discord.TextChannel] = None,
    ) -> discord.Message:
        """Create moderator logs in this channel."""

        await interaction.response.defer()
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        return await LogsConfig(interaction, channel).update()


async def setup(bot: Bot | PBot) -> None:
    """Loads the notifications cog into the bot"""
    await bot.add_cog(AuditLogs(bot))


# Old Code

# async def handle_channel_update(entry: discord.AuditLogEntry):
#     """Handler for when a channel is updated"""

#     if key := changes.pop("default_reaction_emoji", False):
#         b = key["before"]
#         a = key["after"]
#         before.description += f"**Default Reaction Emoji**: {b}\n"
#         after.description += f"**Default Reaction Emoji**: {a}\n"

#     if key := changes.pop("default_thread_slowmode_delay", False):
#         sm_bf = stringify_seconds(key["before"])
#         sm_af = stringify_seconds(key["after"])
#         before.description += f"**Thread Reply Slowmode**: {sm_bf}\n"
#         after.description += f"**Thread Reply Slowmode**: {sm_af}\n"

#     if key := changes.pop("available_tags", False):
#         if new := [i for i in key["after"] if i not in key["before"]]:
#             txt = ""
#             for i in new:
#                 txt += f"{i.emoji} {i.name}"
#                 if i.moderated:
#                     txt += " (Mod Only)"
#             after.add_field(name="Tags Added", value=txt)

#         if removed := [i for i in key["before"] if i not in key["after"]]:
#             txt = ""
#             for i in removed:
#                 txt += f"{i.emoji} {i.name}"
#                 if i.moderated:
#                     txt += " (Mod Only)"
#             before.add_field(name="Tags Removed", value=txt)


# async def handle_guild_update(self, entry: discord.AuditLogEntry):
#     """Handler for When a guild is updated."""

#     if key := changes.pop("system_channel_flags", None):
#         bf: discord.SystemChannelFlags = key["before"]
#         af: discord.SystemChannelFlags = key["after"]

#         b = bf.guild_reminder_notifications
#         a = af.guild_reminder_notifications
#         if a != b:
#             o = "on" if b else "off"
#             before.description += f"**Setup Tips**: {o}\n"
#             o = "on" if a else "off"
#             after.description += f"**Setup Tips**: {o}\n"

#         if (b := bf.join_notifications) != (a := af.join_notifications):
#             o = "on" if b else "off"
#             before.description += f"**Join Notifications**: {o}\n"
#             o = "on" if a else "off"
#             after.description += f"**Join Notifications**: {o}\n"

#         b = bf.join_notification_replies
#         a = af.join_notification_replies
#         if a != b:
#             o = "on" if b else "off"
#             before.description += f"**Join Stickers**: {o}\n"
#             o = "on" if a else "off"
#             after.description += f"**Join Stickers**: {o}\n"

#         b = bf.premium_subscription
#         a = af.premium_subscriptions
#         if a != b:
#             o = "on" if b else "off"
#             before.description += f"**Boost Notifications**: {o}\n"
#             o = "on" if a else "off"
#             after.description += f"**Boost Notifications**: {o}\n"

#         b = bf.role_subscription_purchase_notifications
#         a = af.role_subscription_purchase_notifications
#         if a != b:
#             o = "on" if b else "off"
#             before.description += f"**Role Subscriptions**: {o}\n"
#             o = "on" if a else "off"
#             after.description += f"**Role Subscriptions**: {o}\n"

#         b = bf.role_subscription_purchase_notification_replies
#         a = af.role_subscription_purchase_notification_replies
#         if a != b:
#             o = "on" if b else "off"
#             before.description += f"**Role Sub Stickers**: {o}\n"
#             o = "on" if a else "off"
#             after.description += f"**Role Sub Stickers**: {o}\n"
