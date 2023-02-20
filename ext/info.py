"""Commands about the meta-state of the bot and information about users and servers"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord import Member, Embed, Colour, Forbidden, Interaction, Message, PartialEmoji, User, Emoji, Permissions, Role
from discord.abc import GuildChannel
from discord.app_commands import command, guild_only, describe, Group
from discord.ext.commands import Cog
from discord.utils import utcnow

from ext.utils.embed_utils import get_colour, rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Info(Cog):
    """Get information about users or servers."""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @command()
    @describe(user="Select a user")
    async def avatar(self, interaction: Interaction, user: User | Member = None) -> Message:
        """Shows a member's avatar"""
        await interaction.response.defer(thinking=True)

        if user is None:
            user = interaction.user

        e: Embed = Embed(description=f"{user.mention}'s avatar", colour=user.colour, timestamp=utcnow())
        e.set_author(name=f"{user} ({user.id})", icon_url=interaction.user.display_avatar.url)
        e.set_footer(text=user.display_avatar.url)
        e.set_image(url=user.display_avatar.url)
        return await self.bot.reply(interaction, embed=e)

    info = Group(name="info", description="Get information about things on your server")

    @info.command()
    @describe(channel="select a channel")
    async def channel(self, interaction: Interaction, channel: GuildChannel):
        """Get information about a channel"""
        await interaction.response.defer(thinking=True)

        base_embed = Embed(description=f"{channel.mention}\n\n", timestamp=channel.created_at)
        base_embed.set_author(name=f"{channel.name} ({channel.id})")

        e = base_embed.copy()

        if channel.category:
            sync = " (Perms Synced)" if channel.permissions_synced else " (Perms not Synced)"
            e.description += f"**Category**: {channel.category.mention} {sync}\n"
            e.description += f"**Type**: {channel.type}\n"
            e.description += f"**Position**: {channel.position}\n"

        e.set_footer(text="Channel Created")

        match type(channel):
            case discord.TextChannel:
                e.title = "Text Channel"
                channel: discord.TextChannel
                if channel.topic:
                    e.add_field(name="Topic", value=channel.topic)

                if channel.slowmode_delay:
                    e.description += f"**Slowmode**: {channel.slowmode_delay} seconds\n"

                if channel.nsfw:
                    e.description += f"**NSFW**: True\n"
                if channel.is_news():
                    e.description += f"**News**: True\n"

                e.description += f"**Thread Archive Time**: {channel.default_auto_archive_duration}mins\n"
                e.description += f"**Visible To**: {len(channel.members)} Users\n"
                if channel.threads:
                    e.description += f"**Current Threads**: {len(channel.threads)}\n"

            case discord.VoiceChannel:
                channel: discord.VoiceChannel
                e.title = "Voice Channel"
                e.description += f"**Bitrate**: {channel.bitrate / 1000}kbps\n"
                e.description += f"**Max Users**: {channel.user_limit}\n"
                e.description += f"**Video Quality**: {channel.video_quality_mode}\n"
                if channel.rtc_region:
                    e.description += f"**Region**: {channel.rtc_region}\n"

                e.description += f"**Visible To**: {len(channel.members)} Users\n"

                if channel.nsfw:
                    e.description += f"**NSFW**: True\n"
                if channel.slowmode_delay:
                    e.description += f"**Text Slowmode**: {channel.slowmode_delay} seconds\n"

            case discord.CategoryChannel:
                e.title = "Category Channel"
                channel: discord.CategoryChannel
                e.description += f"**Channels In Category**: {len(channel.channels)} " \
                                 f"({len(channel.text_channels)} Text, {len(channel.voice_channels)} Voice" \
                                 f"{len(channel.stage_channels)} Stage)\n"
            case discord.StageChannel:
                e.title = "Stage Channel"

                channel: discord.StageChannel
                e.description += f"**Bitrate**: {channel.bitrate / 1000}kbps\n"
                e.description += f"**Max Users**: {channel.user_limit}\n"
                e.description += f"**Video Quality**: {channel.video_quality_mode}\n"
                if channel.rtc_region:
                    e.description += f"**Region**: {channel.rtc_region}\n"

                if channel.slowmode_delay:
                    e.description += f"**Text Slowmode**: {channel.slowmode_delay} seconds\n"

                if channel.topic:
                    e.add_field(name="Topic", value=channel.topic)

                e.description += f"**Requests to Speak**: {len(channel.requesting_to_speak)}\n"
                e.description += f"**Speakers**: {len(channel.speakers)}\n"
                e.description += f"**Listeners**: {len(channel.listeners)}\n"
                e.description += f"**Moderators**: {len(channel.moderators)}\n"

                # INSTANCE
                if ins := channel.instance:
                    ins: discord.StageInstance
                    val = f"**Topic**: {ins.topic}\n\n" \
                          f"**Privacy Level**: {ins.privacy_level}\n" \
                          f"**Public Event?**: {not ins.discoverable_disabled}\n"

                    if ins.scheduled_event:
                        event: discord.ScheduledEvent = ins.scheduled_event

                        val += f"**Event**: {event.name} {Timestamp(event.start_time)} - {Timestamp(event.end_time)})"
                        if event.cover_image:
                            e.set_image(url=event.cover_image.url)

                    e.add_field(name="Stage in Progress", value=val, inline=False)

            case discord.ForumChannel:
                channel: discord.ForumChannel
                e.title = "Forum Channel"

                e.description += f"**Total Threads**: {len(channel.threads)}\n"
                e.description += f"**NSFW?**: {channel.is_nsfw()}\n"
                e.description += f"**Thread Archive Time**: {channel.default_auto_archive_duration}mins\n"
                e.description += f"**Default SlowMode**: {channel.default_thread_slowmode_delay} seconds\n"
                e.description += f"**Default Emoji**: {channel.default_reaction_emoji}\n"
                e.description += f"**Default Layout**: {channel.default_layout}\n"

                # flags
                if channel.flags.require_tag:
                    e.description += f"**Force Tags?**: True\n"

                if channel.topic:
                    e.add_field(name="Topic", value=channel.topic)

                if tags := channel.available_tags:
                    e.add_field(name="Available Tags", value=', '.join(f"{i.emoji} {i.name}" for i in tags))

        # List[Role | Member | Object]

        if not channel.overwrites:
            return await self.bot.reply(interaction, embed=e)

        target: Role | Member | discord.Object
        embeds: list[Embed] = []
        for target, overwrite in channel.overwrites.items():
            emb = base_embed.copy()
            emb.title = "Permission Overwrites"
            emb.description = f"{target.mention} ({target.id})"

            if allow := '\n'.join(f'✅ {k}' for k, v in overwrite if v):
                emb.add_field(name="Allowed", value=allow)

            if deny := '\n'.join(f'❌ {k}' for k, v in overwrite if v is False):
                emb.add_field(name="Denied", value=deny)
            embeds.append(emb)

        return await Paginator(interaction, [e] + embeds).update()

    @info.command()
    @describe(role="select a role")
    async def role(self, interaction: Interaction, role: Role):
        """Get information about a channel"""
        await interaction.response.defer(thinking=True)

        e = Embed(description=f"{role.mention}\n\n", colour=role.colour)
        ico = role.display_icon.url if role.display_icon is not None else None
        e.set_author(name=f"{role.name} ({role.id})", icon_url=ico)

        match len(role.members):
            case role.members if role.members:
                e.description += "**This Role is Unused**\n"
            case role.members if len(role.members) < 15:
                e.add_field(name="Users", value=', '.join(i.mention for i in role.members))
            case _:
                e.description = f"**Total Users**: {len(role.members)}\n"

        e.description += f"**Show Separately?**: {role.hoist}\n"
        e.description += f"**Position**: {role.position}\n"
        try:
            e.description += f"**Icon**: [Link]({role.display_icon.url})\n"
        except AttributeError:
            pass
        e.description += f"**Colour**: {role.colour.value} ({role.colour.to_rgb()})\n"
        e.description += f"**Mentionable**: {role.mentionable}\n"

        if role.managed:
            e.description += f"Role managed by interaction with ID {role.tags.integration_id}\n"
        if role.is_bot_managed():
            e.description += f"Role for bot {interaction.guild.get_member(role.tags.bot_id).mention}\n"
        if role.is_default():
            e.description += f"```\nThis Role is the default role for {interaction.guild.name}.```"
        if role.is_default():
            e.description += f"```\nThis Role is for server boosters```"
        if role.tags.is_guild_connection():
            e.description += f"```\nThis Role is managed by an external connection```"
        if role.tags.is_available_for_purchase():
            e.description += f"```\nThis Role is purchasable.```"

        e.set_footer(text="Role Created")
        e.timestamp = role.created_at

        try:
            perm_embed = e.copy()
            permissions: Permissions = role.permissions
            perm_embed.add_field(name="✅ Allowed Perms", value=', '.join([i for i in permissions if i[1]]))
            perm_embed.title = "Role Permissions"
        except AttributeError:
            perm_embed = None

        return await Paginator(interaction, [i for i in [e, perm_embed] if i]).update()

    @info.command(name="emote")
    @describe(emoji="enter a list of emotes")
    async def info_emote(self, interaction: Interaction, emoji: str) -> Message:
        """View a bigger version of an Emoji"""
        await interaction.response.defer(thinking=True)

        embeds = []
        for anim, name, e_id in re.findall(r'<(?P<animated>a?):(?P<name>\w{2,32}):(?P<id>\d{18,22})>', emoji):
            e: Embed = Embed(title=name)
            if (emoji := self.bot.get_emoji(e_id)) is None:
                emoji = PartialEmoji(name=name, animated=bool(anim), id=e_id)

            e.colour = await get_colour(emoji.url)
            if emoji.animated:
                e.description = f"**Animated?**: {emoji.animated}\n"
            e.set_image(url=emoji.url)
            e.set_footer(text=emoji.url)

            if isinstance(emoji, Emoji):  # Not a partial emoji
                e.description += f"**Server**: {emoji.guild.name} ({emoji.guild.id})"
                e.timestamp = emoji.created_at

            embeds.append(e)

        if not embeds:
            return await self.bot.error(interaction, f"No emotes found in {emoji}\n\nPlease note this only works for"
                                                     f"custom server emotes, not default emotes.")

        return await Paginator(interaction, embeds).update()

    @info.command()
    @guild_only()
    async def server(self, interaction: Interaction) -> Message:
        """Shows information about the server"""
        await interaction.response.defer(thinking=True)

        g = interaction.guild

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

        try:
            cover.description += f"**Owner**: {g.owner.mention}\n"
        except AttributeError:
            pass

        cover.description += f"**Members**: {len(g.members)}\n"
        cover.description += f"**Notification Settings**: {g.default_notifications.name.replace('_', ' ').title()}\n"
        cover.description += f"**MFA-Level**: {g.mfa_level.name.replace('_', ' ').title()}\n"
        cover.description += f"**Explicit Content Check**: {g.explicit_content_filter.name.replace('_', ' ').title()}\n"
        cover.description += f"**Locale**: {g.preferred_locale}\n"

        if desc := g.description:
            cover.description += f"\n{desc}"

        if g.banner is not None:
            cover.set_image(url=g.banner.url)
        elif g.discovery_splash is not None:
            cover.set_image(url=g.discovery_splash.url)

        # Nitro Boosting
        if boosts := g.premium_subscription_count:
            cover.description += f"**Boosts**: {boosts} (Tier {g.premium_tier})\n"

        try:
            if (vanity := await g.vanity_invite()) is not None:
                cover.add_field(name="Server Vanity invite", value=vanity)
        except Forbidden:
            pass

        channels = base_embed.copy()
        channels.title = "Channels"
        channels.description = f"**Text Channels**: {len(g.text_channels)}\n"
        if vc := g.voice_channels:
            channels.description += f"**Voice Channels**: {len(vc)}\n"
        if threads := g.threads:
            channels.description += f"**Threads**: {len(threads)}\n"
        if stages := g.stage_channels:
            channels.description += f"**Stages**: {len(stages)}\n"
        if forums := g.forums:
            channels.description += f"**Forums**: {len(forums)}\n"

        channels.description += f"**Bitrate Limit**: {g.bitrate_limit}\n"
        channels.description += f"**FileSize Limit**: {g.filesize_limit / 1000}kb\n"

        try:
            channels.description += f"\n**Rules Channel**: {g.rules_channel.mention}\n"
        except AttributeError:
            pass

        try:
            channels.description += f"\n**Updates Channel**: {g.public_updates_channel.mention}\n"
        except AttributeError:
            pass

        fl = []
        try:
            channels.description += f"\n**System Channel**: {g.system_channel.mention}\n"
            flags = g.system_channel_flags
            fl.append(f"**Setup Tips**: {'on' if flags.guild_reminder_notifications else 'off'}")
            fl.append(f"**Join Notifications**: {'on' if flags.join_notifications else 'off'}")
            fl.append(f"**Join Stickers**: {'on' if flags.join_notification_replies else 'off'}")
            fl.append(f"**Boost Notifications**: {'on' if flags.premium_subscriptions else 'off'}")
            fl.append(f"**Role Subscriptions**: {'on' if flags.role_subscription_purchase_notifications else 'off'}")
            fl.append(f"**Sub Stickers**: {'on' if flags.role_subscription_purchase_notification_replies else 'off'}")
            channels.add_field(name="System Channel Flags", value='\n'.join(fl))
        except AttributeError:
            pass

        try:
            channels.description += f"\n**AFK Channel**: {g.afk_channel.mention}\n"
        except AttributeError:
            pass

        stickers: Embed = base_embed.copy()
        stickers.title = "Emotes and Stickers"

        emojis = ""
        for emoji in g.emojis:
            if len(emojis) + len(str(emoji)) < 1024:
                emojis += str(emoji)

        if emojis:
            stickers.add_field(name="Emotes", value=emojis, inline=False)

        stickers.description = f"**Emotes Used**: {len(g.emojis)} / {g.emoji_limit}\n"
        stickers.description += f"**Stickers Used**: {len(g.stickers)} / {g.sticker_limit}\n"

        r_e = base_embed.copy()
        r_e.title = "Roles"
        r_e.description = f"**Number of Roles**: {len(g.roles)}\n"
        r_e.description += f"**Default Role**: {g.default_role.mention}\n"
        try:
            r_e.description += f"**Booster Role**: {g.premium_subscriber_role.mention}\n"
        except AttributeError:
            pass
        r_e.description += f"**Unused Roles**: {len([i for i in g.roles if not i.members])}\n"
        if g.self_role:
            r_e.description += f"**My Role**: {g.self_role.mention}\n"

        return await Paginator(interaction, [cover, channels, stickers, r_e]).update()

    @info.command()
    async def user(self, interaction: Interaction, member: Member) -> Message:
        """Show info about this member."""
        # Embed 1: Generic Info
        await interaction.response.defer(thinking=True)

        base_embed: Embed = Embed(colour=member.accent_colour, timestamp=utcnow())

        try:
            ico = member.display_avatar.url
        except AttributeError:
            ico = None

        base_embed.set_author(name=member, icon_url=ico)

        generic = base_embed.copy()
        desc = [f"{'🤖 ' if member.bot else ''}{member.mention}\nUser ID: {member.id}"]

        if member.raw_status:
            desc.append(f"**Status**: {member.raw_status}")

        if member.is_on_mobile():
            desc.append("📱 Using mobile app.")

        if member.voice:
            voice = member.voice.channel
            voice_other = len(voice.members) - 1

            voice = f'In voice channel {voice.mention} {f"with {voice_other} others" if voice_other else "alone"}'
            generic.add_field(name="Voice Status", value=voice)

        if roles := [r.mention for r in reversed(member.roles) if r.position != 0]:
            generic.add_field(name='Roles', value=' '.join(roles))

        if member.banner:
            generic.set_image(url=member.banner.url)

        try:
            desc.append(f'**Joined Date**: {Timestamp(member.joined_at).countdown}')
        except AttributeError:
            pass
        desc.append(f'**Account Created**: {Timestamp(member.created_at).countdown}')
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
            generic.add_field(name="Flags", value=', '.join(flags))

        # Embed 2 - User Permissions
        try:
            perm_embed = base_embed.copy()
            permissions: Permissions = interaction.channel.permissions_for(member)
            perm_embed.add_field(name="✅ Allowed Perms", value=', '.join([i for i in permissions if i[1]]))
            perm_embed.title = "Member Permissions"
            perm_embed.description = f"Showing Permissions in {interaction.channel.mention}"
        except AttributeError:
            perm_embed = None

        # Embed 3 - User Avatar
        av = base_embed.copy()
        av.description = f"{member.mention}'s avatar"
        av.set_image(url=member.display_avatar.url)

        # Shared Servers.
        matches = [f"`{i.id}:` **{i.name}**" for i in member.mutual_guilds]
        sh = Embed(colour=Colour.og_blurple())
        embeds = rows_to_embeds(sh, matches, 20, header=f"User found on {len(matches)} servers.")
        return await Paginator(interaction, [i for i in [generic, perm_embed, av] if i is not None] + embeds).update()


async def setup(bot: Bot | PBot) -> None:
    """Load the Info cog into the bot"""
    return await bot.add_cog(Info(bot))
