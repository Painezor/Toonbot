"""Commands about the meta-state of the bot and information about users and servers"""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from discord import Member, Embed, Colour, TextChannel, Forbidden, Interaction, Message
from discord.app_commands import CommandAlreadyRegistered, context_menu, command, guild_only
from discord.ext.commands import Cog
from discord.utils import utcnow

from ext.utils.embed_utils import get_colour, rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


@context_menu(name="Get User Info")
async def u_info(interaction: Interaction, member: Member) -> Message:
    """Show info about this member."""
    # Embed 1: Generic Info
    bot: Bot = interaction.client
    await interaction.response.defer(thinking=True)

    e: Embed = Embed(colour=member.colour)

    try:
        ico = member.display_icon.url
    except AttributeError:
        ico = None

    e.set_author(name=member, icon_url=ico)
    if member.display_avatar:
        e.set_thumbnail(url=member.display_avatar.url)
    desc = [f"{'🤖 ' if member.bot else ''}{member.mention}\nUser ID: {member.id}"]

    if hasattr(member, 'is_on_mobile') and member.is_on_mobile():
        desc.append("📱 Using mobile app.")

    if hasattr(member, 'voice') and member.voice:
        voice = member.voice.channel
        voice_other = len(voice.members) - 1

        voice = f'In voice channel {voice.mention} {f"with {voice_other} others" if voice_other else "alone"}'
        e.add_field(name="Connected to voice chat", value=voice)

    try:
        roles = [role.mention for role in reversed(member.roles) if not role.position == 0]
        if roles:
            e.add_field(name='Roles', value=' '.join(roles))
    except AttributeError:
        pass

    if hasattr(member, "banner") and member.banner:
        e.set_image(url=member.banner.url)

    try:
        desc.append(f'Joined Server: {Timestamp(member.joined_at).countdown}')
    except AttributeError:
        pass
    desc.append(f'Created Account: {Timestamp(member.created_at).countdown}')
    e.description = "\n".join(desc)

    # Embed 2 - User Permissions
    try:
        permissions = interaction.channel.permissions_for(member)
        permissions = "\n".join([f"{i[0]} : {i[1]}" for i in permissions])
        perm_embed = deepcopy(e)
        perm_embed.description = permissions
        perm_embed.title = "Member Permissions"
    except AttributeError:
        perm_embed = None

    # Embed 3 - User Avatar
    av = Embed(colour=member.color, description=f"{member.mention}'s avatar")
    av.set_footer(text=member.display_avatar.url)
    av.set_image(url=member.display_avatar.url)
    av.timestamp = utcnow()

    # Shared Servers.
    matches = [f"`{i.id}:` **{i.name}**" for i in bot.guilds if i.get_member(member.id) is not None]

    sh = Embed(colour=Colour.og_blurple())
    sh.set_footer(text=f"{member} (ID: {member})", icon_url=member.display_avatar.url)
    embeds = rows_to_embeds(sh, matches, 20, header=f"User found on {len(matches)} servers.")
    return await Paginator(interaction, [i for i in [e, perm_embed, av] if i is not None] + embeds).update()


class Info(Cog):
    """Get information about users or servers."""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot
        try:
            self.bot.tree.add_command(u_info)
        except CommandAlreadyRegistered:
            pass

    @command()
    @guild_only()
    async def server_info(self, interaction: Interaction) -> Message:
        """Shows information about the server"""
        await interaction.response.defer(thinking=True)

        e: Embed = Embed(title=interaction.guild.name)

        desc = []
        if interaction.guild.description:
            desc.append(interaction.guild.description)
        desc.append(f"Guild ID: {interaction.guild.id}")
        try:
            desc.append(f"Owner: {interaction.guild.owner.mention}")
        except AttributeError:
            pass
        desc.append(f'\n{len(interaction.guild.members)} Members')

        # figure out what channels are 'secret'
        text_channels = 0
        for channel in interaction.guild.channels:
            text_channels += isinstance(channel, TextChannel)
        regular_channels = len(interaction.guild.channels)
        voice_channels = regular_channels - text_channels

        desc.append(f"{regular_channels} text channels ")
        if voice_channels:
            desc.append(f"{voice_channels} Voice channels")

        if interaction.guild.premium_subscription_count:
            desc.append(f"{interaction.guild.premium_subscription_count} "
                        f"Boosts (Tier {interaction.guild.premium_tier})")

        if interaction.guild.banner is not None:
            e.set_image(url=interaction.guild.banner.url)
        elif interaction.guild.discovery_splash is not None:
            e.set_image(url=interaction.guild.discovery_splash.url)

        if interaction.guild.icon:
            e.set_thumbnail(url=interaction.guild.icon.url)
            e.colour = await get_colour(str(interaction.guild.icon.url))

        emojis = ""
        for emoji in interaction.guild.emojis:
            if len(emojis) + len(str(emoji)) < 1024:
                emojis += str(emoji)

        if emojis:
            e.add_field(name="Emotes", value=emojis, inline=False)

        desc.append(f"**Emotes**: {len(interaction.guild.emojis)} / {interaction.guild.emoji_limit}  slots used.")
        desc.append(f"**Stickers**: {len(interaction.guild.stickers)} / {interaction.guild.sticker_limit} slots used.")

        try:
            vanity = await interaction.guild.vanity_invite()
            if vanity is not None:
                e.add_field(name="Server Vanity invite", value=vanity)
        except Forbidden:
            pass

        roles = [role.mention for role in interaction.guild.roles]
        e.add_field(name='Roles', value=', '.join(roles) if len(roles) < 15 else f'{len(roles)} roles', inline=False)
        e.add_field(name="Creation Date", value=Timestamp(interaction.guild.created_at).date_relative)
        e.description = "\n".join(desc)
        return await self.bot.reply(interaction, embed=e)


async def setup(bot: Bot | PBot) -> None:
    """Load the Info cog into the bot"""
    return await bot.add_cog(Info(bot))
