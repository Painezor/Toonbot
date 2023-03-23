"""Commands that pull information about various discord objects"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from importlib import reload
import discord
from discord.ext import commands
from discord import (
    Member,
    Embed,
    Colour,
    Forbidden,
    Message,
    User,
    Emoji,
    Permissions,
    Role,
)
from discord.abc import GuildChannel
from discord.app_commands import guild_only, Group
from discord.utils import utcnow

import ext.logs as logs
from ext.utils.embed_utils import get_colour, rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils import view_utils

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Info(commands.Cog):
    """Get information about users or servers."""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot
        reload(view_utils)

    @discord.app_commands.command()
    @discord.app_commands.describe(user="Select a user")
    async def avatar(
        self,
        interaction: discord.Interaction[Bot | PBot],
        user: Optional[User | Member],
    ) -> Message:
        """Shows a member's avatar"""

        await interaction.response.defer(thinking=True)

        e: Embed = Embed(timestamp=utcnow())

        if user is None:
            user = interaction.user
        else:
            auth = interaction.user
            e.set_author(
                name=f"{auth} ({auth.id})", icon_url=auth.display_avatar.url
            )

        e.description = f"{user.mention}'s avatar"
        e.colour = user.colour
        e.set_footer(text=user.display_avatar.url)
        e.set_image(url=user.display_avatar.url)
        return await interaction.edit_original_response(embed=e)

    info = Group(
        name="info", description="Get information about things on your server"
    )

    @info.command()
    @discord.app_commands.describe(c="select a channel")
    async def channel(
        self, interaction: discord.Interaction[Bot | PBot], c: GuildChannel
    ):
        """Get information about a channel"""

        await interaction.response.defer(thinking=True)

        ts = c.created_at
        base_embed = Embed(timestamp=ts)
        base_embed.set_author(name=f"{c.name} ({c.id})")

        e = base_embed.copy()
        e.description = f"{c.mention}\n\n"

        if c.category:
            if c.permissions_synced:
                sync = " (Perms Synced)"
            else:
                sync = " (Perms not Synced)"

            e.description += f"**Category**: {c.category.mention} {sync}\n"
            e.description += f"**Type**: {c.type}\n"
            e.description += f"**Position**: {c.position}\n"

        e.set_footer(text="Channel Created")

        if isinstance(c, discord.TextChannel):
            e.title = "Text Channel"

            if c.topic:
                e.add_field(name="Topic", value=c.topic)

            if c.slowmode_delay:
                s = logs.stringify_seconds(c.slowmode_delay)
                e.description += f"**Slowmode**: {s}\n"

            if c.nsfw:
                e.description += "**NSFW**: True\n"

            if c.is_news():
                e.description += "**News**: True\n"

            s = logs.stringify_minutes(c.default_auto_archive_duration)
            e.description += f"**Thread Archive Time**: {s}\n"

            e.description += f"**Visible To**: {len(c.members)} Users\n"

            if c.threads:
                e.description += f"**Current Threads**: {len(c.threads)}\n"
        elif isinstance(c, discord.VoiceChannel):
            e.title = "Voice Channel"
            e.description += f"**Bitrate**: {c.bitrate / 1000}kbps\n"
            e.description += f"**Max Users**: {c.user_limit}\n"

            e.description += f"**Video Quality**: {c.video_quality_mode}\n"
            if c.rtc_region:
                e.description += f"**Region**: {c.rtc_region}\n"

            e.description += f"**Visible To**: {len(c.members)} Users\n"

            if c.nsfw:
                e.description += "**NSFW**: True\n"

            if c.slowmode_delay:
                s = logs.stringify_seconds(c.slowmode_delay)
                e.description += f"**Text Slowmode**: {s}\n"

        elif isinstance(c, discord.CategoryChannel):
            e.title = "Category Channel"
            e.description += (
                f"**Channels In Category**:"
                f"{len(c.channels)} "
                f"({len(c.text_channels)} Text, "
                f"{len(c.voice_channels)} Voice, "
                f"{len(c.stage_channels)} Stage)\n"
            )

        elif isinstance(c, discord.StageChannel):
            e.title = "Stage Channel"

            e.description += f"**Bitrate**: {c.bitrate / 1000}kbps\n"
            e.description += f"**Max Users**: {c.user_limit}\n"
            e.description += f"**Video Quality**: {c.video_quality_mode}\n"
            if c.rtc_region:
                e.description += f"**Region**: {c.rtc_region}\n"

            if c.slowmode_delay:
                s = logs.stringify_seconds(c.slowmode_delay)
                e.description += f"**Text Slowmode**: {s}\n"

            if c.topic:
                e.add_field(name="Topic", value=c.topic)

            rts = c.requesting_to_speak
            e.description += f"**Requests to Speak**: {len(rts)}\n"
            e.description += f"**Speakers**: {len(c.speakers)}\n"
            e.description += f"**Listeners**: {len(c.listeners)}\n"
            e.description += f"**Moderators**: {len(c.moderators)}\n"

            # INSTANCE
            if ins := c.instance:
                private = not ins.discoverable_disabled
                val = (
                    f"**Topic**: {ins.topic}\n\n"
                    f"**Privacy Level**: {ins.privacy_level}\n"
                    f"**Public Event?**: {private}\n"
                )

                if ins.scheduled_event is not None:
                    ev: discord.ScheduledEvent = ins.scheduled_event

                    start = Timestamp(ev.start_time)
                    end = Timestamp(ev.end_time)

                    val += f"**Event**: {ev.name} {start} - {end})"

                    if ev.cover_image:
                        e.set_image(url=ev.cover_image.url)

                e.add_field(name="Stage in Progress", value=val, inline=False)

        elif isinstance(c, discord.ForumChannel):
            e.title = "Forum Channel"

            e.description += f"**Total Threads**: {len(c.threads)}\n"
            e.description += f"**NSFW?**: {c.is_nsfw()}\n"

            s = logs.stringify_minutes(c.default_auto_archive_duration)
            e.description += f"**Thread Archive Time**: {s}\n"

            s = logs.stringify_seconds(c.default_thread_slowmode_delay)
            e.description += f"**Default SlowMode**: {s}\n"

            em = c.default_reaction_emoji
            e.description += f"**Default Emoji**: {em}\n"
            e.description += f"**Default Layout**: {c.default_layout}\n"

            # flags
            if c.flags.require_tag:
                e.description += "**Force Tags?**: True\n"

            if c.topic:
                e.add_field(name="Topic", value=c.topic)

            if tags := c.available_tags:
                val = ", ".join(f"{i.emoji} {i.name}" for i in tags)
                e.add_field(name="Available Tags", value=val)

        # List[Role | Member | Object]
        if not c.overwrites:
            return await interaction.edit_original_response(embed=e)

        target: Role | Member | discord.Object
        embeds: list[Embed] = []
        for target, overwrite in c.overwrites.items():
            emb = base_embed.copy()
            emb.title = "Permission Overwrites"

            if isinstance(target, discord.Role):
                emb.description = f"<@&{target.id}> ({target.id})"
            elif isinstance(target, discord.Member):
                emb.description = f"<@{target.id}> ({target.id})"
            else:
                emb.description = f"{target.id}"

            if allow := "\n".join(f"✅ {k}" for k, v in overwrite if v):
                emb.add_field(name="Allowed", value=allow)

            if deny := "\n".join(f"❌ {k}" for k, v in overwrite if v is False):
                emb.add_field(name="Denied", value=deny)
            embeds.append(emb)

        return await view_utils.Paginator(interaction, [e] + embeds).update()

    @info.command()
    @discord.app_commands.describe(role="select a role")
    async def role(
        self, interaction: discord.Interaction[Bot | PBot], role: discord.Role
    ):
        """Get information about a channel"""

        await interaction.response.defer(thinking=True)

        e = Embed(description=f"{role.mention}\n\n", colour=role.colour)

        if isinstance(role.display_icon, str):
            ico = role.display_icon
        elif role.display_icon:
            ico = role.display_icon.url
        else:
            ico = None

        e.description = f"<@&{role.id}>\n\n"
        e.set_author(name=f"{role.name} ({role.id})", icon_url=ico)

        match len(role.members):
            case 0:
                e.description += "**This Role is Unused**\n"
            case role.members if len(role.members) < 15:
                val = ", ".join(i.mention for i in role.members)
                e.add_field(name="Users", value=val)
            case _:
                e.description = f"**Total Users**: {len(role.members)}\n"

        e.description += f"**Show Separately?**: {role.hoist}\n"
        e.description += f"**Position**: {role.position}\n"
        e.description += f"**Icon**: {ico}\n"

        c = role.colour
        e.description += f"**Colour**: {c.value} ({c.to_rgb()})\n"
        e.description += f"**Mentionable**: {role.mentionable}\n"

        if role.managed:
            if role.tags:
                int_id = role.tags.integration_id
                if int_id:
                    e.description += f"Role managed by interaction #{int_id}\n"

        if interaction.guild:
            if role.is_bot_managed() and role.tags:
                if role.tags.bot_id:
                    bot = interaction.guild.get_member(role.tags.bot_id)
                    if bot:
                        e.description += f"Role for bot {bot.mention}\n"

            if role.is_default():
                g = interaction.guild.name
                e.description += f"```This is your default role for {g}.```"

            if role.is_premium_subscriber():
                e.description += "```This Role is for server boosters```"

        if role.tags:
            if role.tags.is_guild_connection():
                txt = "```This Role is managed by an external connection```"
                e.description += txt
            if role.tags.is_available_for_purchase():
                e.description += "```This Role is purchasable.```"

        e.set_footer(text="Role Created")
        e.timestamp = role.created_at

        try:
            perm_embed = e.copy()
            permissions: Permissions = role.permissions
            val = ", ".join([k for k, v in permissions if v])
            perm_embed.add_field(name="✅ Allowed Perms", value=val)
        except AttributeError:
            perm_embed = None

        embeds = [i for i in [e, perm_embed] if i]
        return await view_utils.Paginator(interaction, embeds).update()

    @info.command(name="emote")
    @discord.app_commands.describe(emoji="enter a list of emotes")
    async def info_emote(
        self, interaction: discord.Interaction[Bot | PBot], emoji: str
    ) -> Message:
        """View a bigger version of an Emoji"""

        await interaction.response.defer(thinking=True)

        embeds = []

        regex = r"<(?P<animated>a?):(?P<name>\w{2,32}):(?P<id>\d{18,22})>"

        for anim, name, e_id in re.findall(regex, emoji):
            e = Embed(title=name)
            e.description = ""

            if (em := self.bot.get_emoji(e_id)) is None:
                em = discord.PartialEmoji(
                    name=name, animated=bool(anim), id=e_id
                )

            if em is not None:
                e.colour = await get_colour(em.url)
                if em.animated:
                    e.description = f"**Animated?**: {em.animated}\n"
                e.set_image(url=em.url)
                e.set_footer(text=em.url)

            if isinstance(em, Emoji):  # Not a partial emoji
                if (g := em.guild) is not None:
                    e.description += f"**Server**: {g.name} ({g.id})"
                e.timestamp = em.created_at

            embeds.append(e)

        if not embeds:
            err = (
                f"No emotes found in {emoji}\n\nPlease note this only works"
                " for custom server emotes, not default emotes."
            )
            return await self.bot.error(interaction, err)

        return await view_utils.Paginator(interaction, embeds).update()

    @info.command()
    @guild_only()
    async def server(
        self, interaction: discord.Interaction[PBot | Bot]
    ) -> discord.InteractionMessage:
        """Shows information about the server"""

        await interaction.response.defer(thinking=True)

        g = interaction.guild
        if g is None:
            raise

        base_embed: Embed = Embed(description="")
        if (ico := g.icon) is not None:
            clr = await get_colour(ico.url)

            base_embed.colour = clr
            base_embed.set_thumbnail(url=ico.url)
            base_embed.set_author(name=f"{g.name} ({g.id})", icon_url=ico.url)
        else:
            base_embed.set_author(name=g.name)

        cover = base_embed.copy()
        cover.description = ""
        cover.set_footer(text="Server Created")
        cover.timestamp = g.created_at

        if g.owner:
            cover.description += f"**Owner**: {g.owner.mention}\n"

        cover.description += f"**Members**: {len(g.members)}\n"

        n = logs.stringify_notification_level(g.default_notifications)
        cover.description += f"**Notification Settings**: {n}\n"

        s = logs.stringify_mfa(g.mfa_level)
        cover.description += f"**MFA-Level**: {s}\n"

        s = g.explicit_content_filter
        cover.description += f"**Explicit Content Check**: {s}\n"
        cover.description += f"**Locale**: {g.preferred_locale}\n"

        if desc := g.description:
            cover.description += f"\n{desc}"

        if g.banner is not None:
            cover.set_image(url=g.banner.url)
        elif g.discovery_splash is not None:
            cover.set_image(url=g.discovery_splash.url)

        # Nitro Boosting
        if boosts := g.premium_subscription_count:
            tier = g.premium_tier
            cover.description += f"**Boosts**: {boosts} (Tier {tier})\n"

        try:
            if (vanity := await g.vanity_invite()) is not None:
                cover.add_field(name="Server Vanity invite", value=vanity)
        except Forbidden:
            pass

        chs = base_embed.copy()
        chs.title = "Channels"
        chs.description = f"**Text Channels**: {len(g.text_channels)}\n"
        if vc := g.voice_channels:
            chs.description += f"**Voice Channels**: {len(vc)}\n"
        if threads := g.threads:
            chs.description += f"**Threads**: {len(threads)}\n"
        if stages := g.stage_channels:
            chs.description += f"**Stages**: {len(stages)}\n"
        if forums := g.forums:
            chs.description += f"**Forums**: {len(forums)}\n"

        chs.description += f"**Bitrate Limit**: {g.bitrate_limit}\n"
        chs.description += f"**FileSize Limit**: {g.filesize_limit / 1000}kb\n"

        if (rc := g.rules_channel) is not None:
            chs.description += f"**Rules Channel**: {rc.mention}\n"

        if (uc := g.public_updates_channel) is not None:
            chs.description += f"**Updates Channel**: {uc.mention}\n"

        fl = []
        if g.system_channel:
            sys = g.system_channel.mention
            chs.description += f"\n**System Channel**: {sys}\n"
            f = g.system_channel_flags

            o = "on" if f.guild_reminder_notifications else "off"
            fl.append(f"**Setup Tips**: {o}")

            o = "on" if f.join_notifications else "off"
            fl.append(f"**Join Notifications**: {o}")

            o = "on" if f.join_notification_replies else "off"
            fl.append(f"**Join Stickers**: {o}")

            o = "on" if f.premium_subscriptions else "off"
            fl.append(f"**Boost Notifications**: {o}")

            o = {"on" if f.role_subscription_purchase_notifications else "off"}
            fl.append(f"**Role Subscriptions**: {o}")

            if f.role_subscription_purchase_notification_replies:
                o = "on"
            else:
                o = "off"

            fl.append(f"**Sub Stickers**: {o}")

            chs.add_field(name="System Channel Flags", value="\n".join(fl))

        if g.afk_channel:
            chs.description += f"\n**AFK Channel**: {g.afk_channel.mention}\n"

        stickers: Embed = base_embed.copy()
        stickers.title = "Emotes and Stickers"

        lm = g.sticker_limit
        count = len(g.stickers)
        stickers.description = f"**Stickers Used**: {count} / {lm}\n"

        lm = g.emoji_limit
        stickers.description += f"**Emotes Used**: {len(g.emojis)} / {lm}\n\n"

        for emoji in g.emojis:
            if len(stickers.description) + len(str(emoji)) < 4096:
                stickers.description += str(emoji)

        r_e = base_embed.copy()
        r_e.title = "Roles"
        r_e.description = f"**Number of Roles**: {len(g.roles)}\n"
        r_e.description += f"**Default Role**: {g.default_role.mention}\n"

        if g.premium_subscriber_role:
            nitro = g.premium_subscriber_role.mention
            r_e.description += f"**Booster Role**: {nitro}\n"

        empty = len([i for i in g.roles if not i.members])
        r_e.description += f"**Unused Roles**: {empty}\n"
        if g.self_role:
            r_e.description += f"**My Role**: {g.self_role.mention}\n"

        embeds = [cover, chs, stickers, r_e]
        return await view_utils.Paginator(interaction, embeds).update()

    @info.command()
    async def user(
        self,
        interaction: discord.Interaction[Bot | PBot],
        member: discord.Member,
    ) -> discord.InteractionMessage:
        """Show info about this member."""
        # Embed 1: Generic Info

        await interaction.response.defer(thinking=True)

        base_embed = Embed(colour=member.accent_colour, timestamp=utcnow())

        try:
            ico = member.display_avatar.url
        except AttributeError:
            ico = None

        base_embed.set_author(name=member, icon_url=ico)

        generic = base_embed.copy()
        m = member
        desc = [f"{'🤖 ' if m.bot else ''}{m.mention}\nUser ID: {m.id}"]

        if member.raw_status:
            desc.append(f"**Status**: {member.raw_status}")

        if member.is_on_mobile():
            desc.append("📱 Using mobile app.")

        if member.voice:
            voice = member.voice.channel
            if voice:
                other = len(voice.members) - 1

                others = f"with {other} others" if other else "alone"
                voice = f"In voice channel {voice.mention} {others}"
                generic.add_field(name="Voice Status", value=voice)

        roles = [r.mention for r in reversed(member.roles) if r.position != 0]
        if roles:
            generic.add_field(name="Roles", value=" ".join(roles[:20]))

        if member.banner:
            generic.set_image(url=member.banner.url)

        try:
            ts = Timestamp(member.joined_at).countdown
            desc.append(f"**Joined Date**: {ts}")
        except AttributeError:
            pass

        ts = Timestamp(member.created_at).countdown
        desc.append(f"**Account Created**: {ts}")
        generic.description = "\n".join(desc)

        # User Flags
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
            generic.add_field(name="Flags", value=", ".join(flags))

        # Embed 2 - User Permissions
        if interaction.channel:
            perm_embed = base_embed.copy()
            permissions = interaction.channel.permissions_for(member)

            perm_embed.add_field(
                name="✅ Allowed Perms",
                value=", ".join([k for k, v in permissions if v]),
            )

            perm_embed.title = "Member Permissions"

            c = interaction.channel
            perm_embed.description = f"Showing Permissions in <#{c.id}>"
        else:
            perm_embed = None

        # Embed 3 - User Avatar
        av = base_embed.copy()
        av.description = f"{member.mention}'s avatar"
        av.set_image(url=member.display_avatar.url)

        # Shared Servers.
        matches = [f"`{i.id}:` **{i.name}**" for i in member.mutual_guilds]
        sh = Embed(colour=Colour.og_blurple())

        shared = f"User found on {len(matches)} servers."
        embeds = rows_to_embeds(sh, matches, 20, shared)
        embeds += [i for i in [generic, perm_embed, av] if i is not None]
        return await view_utils.Paginator(interaction, embeds).update()


async def setup(bot: Bot | PBot) -> None:
    """Load the Info cog into the bot"""
    return await bot.add_cog(Info(bot))
