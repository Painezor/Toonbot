"""Commands that pull information about various discord objects"""
from __future__ import annotations

import re
import typing
import importlib
import discord
from discord.ext import commands

from ext import logs
from ext.utils import view_utils, embed_utils, timed_events

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot | Bot]
    User: typing.TypeAlias = discord.User | discord.Member

# TODO: Donate Button Command.
# TODO: Subclass Embeds for Info (Too many branches linter warning)


class Info(commands.Cog):
    """Get information about users or servers."""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot
        importlib.reload(view_utils)

    @discord.app_commands.command()
    @discord.app_commands.describe(user="Select a user")
    async def avatar(
        self,
        interaction: Interaction,
        user: typing.Optional[User],
    ) -> None:
        """Shows a member's avatar"""
        embed = discord.Embed(timestamp=discord.utils.utcnow())

        if user is None:
            user = interaction.user

        embed.description = f"{user.mention}'s avatar"
        embed.colour = user.colour
        embed.set_footer(text=user.display_avatar.url)
        embed.set_image(url=user.display_avatar.url)
        return await interaction.response.send_message(embed=embed)

    info = discord.app_commands.Group(
        name="info", description="Get information about things on your server"
    )

    @info.command()
    @discord.app_commands.describe(channel="select a channel")
    async def channel(
        self, interaction: Interaction, channel: discord.abc.GuildChannel
    ) -> discord.InteractionMessage:
        """Get information about a channel"""
        created = channel.created_at
        base_embed = discord.Embed(timestamp=created)
        base_embed.set_author(name=f"{channel.name} ({channel.id})")

        embed = base_embed.copy()
        embed.description = f"{channel.mention}\n\n"

        if channel.category:
            if channel.permissions_synced:
                sync = " (Perms Synced)"
            else:
                sync = " (Perms not Synced)"

            embed.description += (
                f"**Category**: {channel.category.mention} {sync}\n"
            )
            embed.description += f"**Type**: {channel.type}\n"
            embed.description += f"**Position**: {channel.position}\n"

        embed.set_footer(text="Channel Created")

        if isinstance(channel, discord.TextChannel):
            embed.title = "Text Channel"

            if channel.topic:
                embed.add_field(name="Topic", value=channel.topic)

            if channel.slowmode_delay:
                ach = logs.stringify_seconds(channel.slowmode_delay)
                embed.description += f"**Slowmode**: {ach}\n"

            if channel.nsfw:
                embed.description += "**NSFW**: True\n"

            if channel.is_news():
                embed.description += "**News**: True\n"

            ach = logs.stringify_minutes(channel.default_auto_archive_duration)
            embed.description += f"**Thread Archive Time**: {ach}\n"

            embed.description += (
                f"**Visible To**: {len(channel.members)} Users\n"
            )

            if thrds := channel.threads:
                embed.description += f"**Current Threads**: {len(thrds)}\n"
        elif isinstance(channel, discord.VoiceChannel):
            embed.title = "Voice Channel"
            embed.description += f"**Bitrate**: {channel.bitrate / 1000}kbps\n"
            embed.description += f"**Max Users**: {channel.user_limit}\n"

            quality = channel.video_quality_mode
            embed.description += f"**Video Quality**: {quality}\n"
            if channel.rtc_region:
                embed.description += f"**Region**: {channel.rtc_region}\n"

            embed.description += (
                f"**Visible To**: {len(channel.members)} Users\n"
            )

            if channel.nsfw:
                embed.description += "**NSFW**: True\n"

            if channel.slowmode_delay:
                ach = logs.stringify_seconds(channel.slowmode_delay)
                embed.description += f"**Text Slowmode**: {ach}\n"

        elif isinstance(channel, discord.CategoryChannel):
            embed.title = "Category Channel"
            embed.description += (
                f"**Channels In Category**:"
                f"{len(channel.channels)} "
                f"({len(channel.text_channels)} Text, "
                f"{len(channel.voice_channels)} Voice, "
                f"{len(channel.stage_channels)} Stage)\n"
            )

        elif isinstance(channel, discord.StageChannel):
            embed.title = "Stage Channel"

            embed.description += f"**Bitrate**: {channel.bitrate / 1000}kbps\n"
            embed.description += f"**Max Users**: {channel.user_limit}\n"
            embed.description += (
                f"**Video Quality**: {channel.video_quality_mode}\n"
            )
            if channel.rtc_region:
                embed.description += f"**Region**: {channel.rtc_region}\n"

            if channel.slowmode_delay:
                ach = logs.stringify_seconds(channel.slowmode_delay)
                embed.description += f"**Text Slowmode**: {ach}\n"

            if channel.topic:
                embed.add_field(name="Topic", value=channel.topic)

            rts = channel.requesting_to_speak
            embed.description += f"**Requests to Speak**: {len(rts)}\n"
            embed.description += f"**Speakers**: {len(channel.speakers)}\n"
            embed.description += f"**Listeners**: {len(channel.listeners)}\n"
            embed.description += f"**Moderators**: {len(channel.moderators)}\n"

            # INSTANCE
            if ins := channel.instance:
                private = not ins.discoverable_disabled
                val = (
                    f"**Topic**: {ins.topic}\n\n"
                    f"**Privacy Level**: {ins.privacy_level}\n"
                    f"**Public Event?**: {private}\n"
                )

                if ins.scheduled_event is not None:
                    event: discord.ScheduledEvent = ins.scheduled_event

                    start = timed_events.Timestamp(event.start_time)
                    end = timed_events.Timestamp(event.end_time)

                    val += f"**Event**: {event.name} {start} - {end})"

                    if event.cover_image:
                        embed.set_image(url=event.cover_image.url)

                embed.add_field(
                    name="Stage in Progress", value=val, inline=False
                )

        elif isinstance(channel, discord.ForumChannel):
            embed.title = "Forum Channel"

            embed.description += f"**Total Threads**: {len(channel.threads)}\n"
            embed.description += f"**NSFW?**: {channel.is_nsfw()}\n"

            ach = logs.stringify_minutes(channel.default_auto_archive_duration)
            embed.description += f"**Thread Archive Time**: {ach}\n"

            s_m = logs.stringify_seconds(channel.default_thread_slowmode_delay)
            embed.description += f"**Default SlowMode**: {s_m}\n"

            emoji = channel.default_reaction_emoji
            embed.description += f"**Default Emoji**: {emoji}\n"
            embed.description += (
                f"**Default Layout**: {channel.default_layout}\n"
            )

            # flags
            if channel.flags.require_tag:
                embed.description += "**Force Tags?**: True\n"

            if channel.topic:
                embed.add_field(name="Topic", value=channel.topic)

            if tags := channel.available_tags:
                val = ", ".join(f"{i.emoji} {i.name}" for i in tags)
                embed.add_field(name="Available Tags", value=val)

        # List[Role | Member | Object]
        if not channel.overwrites:
            await interaction.response.send_message(embed=embed)
            return await interaction.original_response()

        target: discord.Role | discord.Member | discord.Object
        embeds: list[discord.Embed] = [embed]
        for target, ovw in channel.overwrites.items():
            emb = base_embed.copy()
            emb.title = "Permission Overwrites"

            if isinstance(target, discord.Role):
                emb.description = f"<@&{target.id}> ({target.id})"
            elif isinstance(target, discord.Member):
                emb.description = f"<@{target.id}> ({target.id})"
            else:
                emb.description = f"{target.id}"

            if allow := "\n".join(f"✅ {k}" for k, v in ovw if v):
                emb.add_field(name="Allowed", value=allow)

            if deny := "\n".join(f"❌ {k}" for k, v in ovw if v is False):
                emb.add_field(name="Denied", value=deny)
            embeds.append(emb)

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        return view.message

    @info.command()
    @discord.app_commands.describe(role="select a role")
    async def role(self, interaction: Interaction, role: discord.Role) -> None:
        """Get information about a channel"""

        embed = discord.Embed(description=f"{role.mention}\n\n")
        embed.colour = role.colour

        if isinstance(role.display_icon, str):
            ico = role.display_icon
        elif role.display_icon:
            ico = role.display_icon.url
        else:
            ico = None

        embed.description = f"<@&{role.id}>\n\n"
        embed.set_author(name=f"{role.name} ({role.id})", icon_url=ico)

        mems = len(role.members)
        if mems == 0:
            embed.description += "**This Role is Unused**\n"
        elif mems < 15:
            val = ", ".join(i.mention for i in role.members)
            embed.add_field(name="Users", value=val)
        else:
            embed.description = f"**Total Users**: {len(role.members)}\n"

        embed.description += f"**Show Separately?**: {role.hoist}\n"
        embed.description += f"**Position**: {role.position}\n"
        embed.description += f"**Icon**: {ico}\n"

        color = role.colour
        embed.description += f"**Colour**: {color.value} ({color.to_rgb()})\n"
        embed.description += f"**Mentionable**: {role.mentionable}\n"

        if role.managed:
            if role.tags:
                int_id = role.tags.integration_id
                if int_id:
                    embed.description += (
                        f"Role managed by interaction #{int_id}\n"
                    )

        if interaction.guild:
            if role.is_bot_managed() and role.tags:
                if role.tags.bot_id:
                    bot = interaction.guild.get_member(role.tags.bot_id)
                    if bot:
                        embed.description += f"Role for bot {bot.mention}\n"

            if role.is_default():
                guild = interaction.guild.name
                txt = f"```This is your default role for {guild}.```"
                embed.description += txt

            if role.is_premium_subscriber():
                embed.description += "```This Role is for server boosters```"

        if role.tags:
            if role.tags.is_guild_connection():
                txt = "```This Role is managed by an external connection```"
                embed.description += txt
            if role.tags.is_available_for_purchase():
                embed.description += "```This Role is purchasable.```"

        embed.set_footer(text="Role Created")
        embed.timestamp = role.created_at

        try:
            perm_embed = embed.copy()
            permissions: discord.Permissions = role.permissions
            val = ", ".join([k for k, v in permissions if v])
            perm_embed.add_field(name="✅ Allowed Perms", value=val)
        except AttributeError:
            perm_embed = None

        embeds = [i for i in [embed, perm_embed] if i]

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        return

    @info.command(name="emote")
    @discord.app_commands.describe(emote="enter an emote")
    async def info_emote(self, interaction: Interaction, emote: str) -> None:
        """View a bigger version of an Emoji"""
        embeds = []
        regex = r"<(?P<animated>a?):(?P<name>\w{2,32}):(?P<id>\d{18,22})>"

        for anim, name, e_id in re.findall(regex, emote):
            embed = discord.Embed(title=name)
            embed.description = ""

            if (emo := self.bot.get_emoji(e_id)) is None:
                emo = discord.PartialEmoji(
                    name=name, animated=bool(anim), id=e_id
                )

                if emo is not None:
                    embed.colour = await embed_utils.get_colour(emo.url)
                    if emo.animated:
                        embed.description = f"**Animated?**: {emo.animated}\n"
                    embed.set_image(url=emo.url)
                    embed.set_footer(text=emo.url)

            if isinstance(emo, discord.Emoji):  # Not a partial emoji
                if (gild := emo.guild) is not None:
                    embed.description += f"**Server**: {gild.name} ({gild.id})"
                embed.timestamp = emo.created_at

            embeds.append(embed)

        if not embeds:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 No emotes found in {emote}"
            _ = interaction.response.send_message
            await _(embed=embed, ephemeral=True)
            return

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        return

    @info.command()
    @discord.app_commands.guild_only()
    async def server(self, interaction: Interaction) -> None:
        """Shows information about the server"""
        guild = interaction.guild
        if guild is None:
            raise discord.app_commands.errors.NoPrivateMessage

        base_embed = discord.Embed(description="")
        if (ico := guild.icon) is not None:
            clr = await embed_utils.get_colour(ico.url)

            base_embed.colour = clr
            base_embed.set_thumbnail(url=ico.url)
            name = f"{guild.name} ({guild.id})"
            base_embed.set_author(name=name, icon_url=ico.url)
        else:
            base_embed.set_author(name=guild.name)

        cover = base_embed.copy()
        cover.description = ""
        cover.set_footer(text="Server Created")
        cover.timestamp = guild.created_at

        if guild.owner:
            cover.description += f"**Owner**: {guild.owner.mention}\n"

        cover.description += f"**Members**: {len(guild.members)}\n"

        notifs = logs.stringify_notification_level(guild.default_notifications)
        cover.description += f"**Notification Settings**: {notifs}\n"

        mfa_lvl = logs.stringify_mfa(guild.mfa_level)
        cover.description += f"**MFA-Level**: {mfa_lvl}\n"

        ct_filter = guild.explicit_content_filter
        cover.description += f"**Explicit Content Check**: {ct_filter}\n"
        cover.description += f"**Locale**: {guild.preferred_locale}\n"

        if desc := guild.description:
            cover.description += f"\n{desc}"

        if guild.banner is not None:
            cover.set_image(url=guild.banner.url)
        elif guild.discovery_splash is not None:
            cover.set_image(url=guild.discovery_splash.url)

        # Nitro Boosting
        if boosts := guild.premium_subscription_count:
            tier = guild.premium_tier
            cover.description += f"**Boosts**: {boosts} (Tier {tier})\n"

        try:
            if (vanity := await guild.vanity_invite()) is not None:
                cover.add_field(name="Server Vanity invite", value=vanity)
        except discord.Forbidden:
            pass

        chs = base_embed.copy()
        chs.title = "Channels"
        chs.description = f"**Text Channels**: {len(guild.text_channels)}\n"
        if voice := guild.voice_channels:
            chs.description += f"**Voice Channels**: {len(voice)}\n"
        if threads := guild.threads:
            chs.description += f"**Threads**: {len(threads)}\n"
        if stages := guild.stage_channels:
            chs.description += f"**Stages**: {len(stages)}\n"
        if forums := guild.forums:
            chs.description += f"**Forums**: {len(forums)}\n"

        chs.description += f"**Bitrate Limit**: {guild.bitrate_limit}\n"
        chs.description += (
            f"**FileSize Limit**: {guild.filesize_limit / 1000}kb\n"
        )

        if (rules := guild.rules_channel) is not None:
            chs.description += f"**Rules Channel**: {rules.mention}\n"

        if (updates := guild.public_updates_channel) is not None:
            chs.description += f"**Updates Channel**: {updates.mention}\n"

        flags = []
        if guild.system_channel:
            sys = guild.system_channel.mention
            chs.description += f"\n**System Channel**: {sys}\n"
            flag = guild.system_channel_flags

            toggle = "on" if flag.guild_reminder_notifications else "off"
            flags.append(f"**Setup Tips**: {toggle}")

            toggle = "on" if flag.join_notifications else "off"
            flags.append(f"**Join Notifications**: {toggle}")

            toggle = "on" if flag.join_notification_replies else "off"
            flags.append(f"**Join Stickers**: {toggle}")

            toggle = "on" if flag.premium_subscriptions else "off"
            flags.append(f"**Boost Notifications**: {toggle}")

            sub_notif = flag.role_subscription_purchase_notifications
            toggle = {"on" if sub_notif else "off"}
            flags.append(f"**Role Subscriptions**: {toggle}")

            if flag.role_subscription_purchase_notification_replies:
                toggle = "on"
            else:
                toggle = "off"

            flags.append(f"**Sub Stickers**: {toggle}")

            chs.add_field(name="System Channel Flags", value="\n".join(flags))

        if guild.afk_channel:
            chs.description += (
                f"\n**AFK Channel**: {guild.afk_channel.mention}\n"
            )

        stickers: discord.Embed = base_embed.copy()
        stickers.title = "Emotes and Stickers"

        elm = guild.sticker_limit
        count = len(guild.stickers)
        stickers.description = f"**Stickers Used**: {count} / {elm}\n"

        elm = guild.emoji_limit
        stickers.description += (
            f"**Emotes Used**: {len(guild.emojis)} / {elm}\n\n"
        )

        for emoji in guild.emojis:
            if len(stickers.description) + len(str(emoji)) < 4096:
                stickers.description += str(emoji)

        r_e = base_embed.copy()
        r_e.title = "Roles"
        r_e.description = f"**Number of Roles**: {len(guild.roles)}\n"
        r_e.description += f"**Default Role**: {guild.default_role.mention}\n"

        if guild.premium_subscriber_role:
            nitro = guild.premium_subscriber_role.mention
            r_e.description += f"**Booster Role**: {nitro}\n"

        empty = len([i for i in guild.roles if not i.members])
        r_e.description += f"**Unused Roles**: {empty}\n"
        if guild.self_role:
            r_e.description += f"**My Role**: {guild.self_role.mention}\n"

        embeds = [cover, chs, stickers, r_e]

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        return

    @info.command()
    async def user(
        self, interaction: Interaction, member: discord.Member
    ) -> None:
        """Show info about this member."""
        # Embed 1: Generic Info
        base_embed = discord.Embed(colour=member.accent_colour)
        base_embed.timestamp = discord.utils.utcnow()

        try:
            ico = member.display_avatar.url
        except AttributeError:
            ico = None

        base_embed.set_author(name=member, icon_url=ico)

        generic = base_embed.copy()
        mem = member
        desc = [f"{'🤖 ' if mem.bot else ''}{mem.mention}\nUser ID: {mem.id}"]

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
            time = timed_events.Timestamp(member.joined_at).countdown
            desc.append(f"**Joined Date**: {time}")
        except AttributeError:
            pass

        time = timed_events.Timestamp(member.created_at).countdown
        desc.append(f"**Account Created**: {time}")
        generic.description = "\n".join(desc)

        # User Flags
        flags = []
        pub_flags = member.public_flags
        if pub_flags.verified_bot:
            flags.append("🤖 Verified Bot")
        elif member.bot:
            flags.append("🤖 Bot")
        if member.flags.did_rejoin:
            flags.append("Rejoined Server")
        if member.flags.bypasses_verification:
            flags.append("Bypassed Verification")
        if pub_flags.active_developer:
            flags.append("Active Developer")
        if pub_flags.staff:
            flags.append("Discord Staff")
        if pub_flags.partner:
            flags.append("Discord Partner")
        if pub_flags.hypesquad_balance:
            flags.append("Hypesquad Balance")
        if pub_flags.hypesquad_bravery:
            flags.append("Hypesquad Bravery")
        if pub_flags.hypesquad_brilliance:
            flags.append("Hypesquad Brilliance")
        if pub_flags.bug_hunter_level_2:
            flags.append("Bug Hunter Level 2")
        elif pub_flags.bug_hunter:
            flags.append("Bug Hunter")
        if pub_flags.early_supporter:
            flags.append("Early Supporter")
        if pub_flags.system:
            flags.append("Official Discord Representative")
        if pub_flags.verified_bot_developer:
            flags.append("Verified Bot Developer")
        if pub_flags.discord_certified_moderator:
            flags.append("Discord Certified Moderator")
        if pub_flags.spammer:
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

            chan = interaction.channel
            perm_embed.description = f"Showing Permissions in <#{chan.id}>"
        else:
            perm_embed = None

        # Embed 3 - User Avatar
        avatar = base_embed.copy()
        avatar.description = f"{member.mention}'s avatar"
        avatar.set_image(url=member.display_avatar.url)

        # Shared Servers.
        matches = [f"`{i.id}:` **{i.name}**" for i in member.mutual_guilds]
        shared = discord.Embed(colour=discord.Colour.og_blurple())

        shared.description = f"User found on {len(matches)} servers."
        embeds = embed_utils.rows_to_embeds(shared, matches, 20)
        embeds += [i for i in [generic, perm_embed, avatar] if i is not None]

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        return


async def setup(bot: Bot | PBot) -> None:
    """Load the Info cog into the bot"""
    return await bot.add_cog(Info(bot))
