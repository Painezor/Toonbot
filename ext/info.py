"""Commands about the meta-state of the bot and information about users and servers"""
import datetime
from copy import deepcopy
from typing import TYPE_CHECKING, Union

from discord import Member, Embed, Colour, TextChannel, Forbidden, Interaction, Message
from discord.app_commands import CommandAlreadyRegistered, context_menu, command, guild_only
from discord.ext.commands import Cog

from ext.utils import timed_events
from ext.utils.embed_utils import get_colour, rows_to_embeds
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


@context_menu(name="Get User Info")
async def u_info(interaction: Interaction, member: Member) -> Message:
    """Show info about this member."""
    # Embed 1: Generic Info
    await interaction.response.defer(thinking=True)

    e: Embed = Embed(colour=member.colour)

    try:
        ico = member.display_icon.url
    except AttributeError:
        ico = None

    e.set_author(name=member, icon_url=ico)
    if member.display_avatar:
        e.set_thumbnail(url=member.display_avatar.url)
    e.description = f"{'🤖 ' if member.bot else ''}{member.mention}\nUser ID: {member.id}"

    if hasattr(member, 'is_on_mobile') and member.is_on_mobile():
        e.description += "\n📱 Using mobile app."

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
        e.description += f'\nJoined Server: {timed_events.Timestamp(member.joined_at).countdown}'
    except AttributeError:
        pass
    e.description += f'\nCreated Account: {timed_events.Timestamp(member.created_at).countdown}'

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
    av.timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Shared Servers.
    matches = [f"`{i.id}:` **{i.name}**" for i in interaction.client.guilds if i.get_member(member.id) is not None]

    sh = Embed(colour=Colour.og_blurple())
    sh.set_footer(text=f"{member} (ID: {member})", icon_url=member.display_avatar.url)
    embeds = rows_to_embeds(sh, matches, 20, header=f"User found on {len(matches)} servers.")

    v = Paginator(interaction.client, interaction, [i for i in [e, perm_embed, av] if i is not None] + embeds)
    return await v.update()


class Info(Cog):
    """Get information about users or servers."""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot
        try:
            self.bot.tree.add_command(u_info)
        except CommandAlreadyRegistered:
            pass

    @command()
    @guild_only()
    async def server_info(self, interaction: Interaction) -> Message:
        """Shows information about the server"""
        e: Embed = Embed(title=interaction.guild.name)
        e.description = interaction.guild.description if interaction.guild.description is not None else ""
        e.description += f"Guild ID: {interaction.guild.id}"
        try:
            e.description += f"\nOwner: {interaction.guild.owner.mention}"
        except AttributeError:
            pass
        e.description += f'\n\n{len(interaction.guild.members)} Members'

        # figure out what channels are 'secret'
        text_channels = 0
        for channel in interaction.guild.channels:
            text_channels += isinstance(channel, TextChannel)
        regular_channels = len(interaction.guild.channels)
        voice_channels = regular_channels - text_channels

        e.description += f"\n{regular_channels} text channels "
        if voice_channels:
            e.description += f"\n{voice_channels} Voice channels"

        if interaction.guild.premium_subscription_count:
            e.description += f"\n\n{interaction.guild.premium_subscription_count} " \
                             f"Nitro Boosts (Tier {interaction.guild.premium_tier})"

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

        e.description += f"\n**Emotes**: {len(interaction.guild.emojis)} / {interaction.guild.emoji_limit}  slots used."
        e.description += f"\n**Stickers**: {len(interaction.guild.stickers)} " \
                         f"/ {interaction.guild.sticker_limit} slots used."

        try:
            vanity = await interaction.guild.vanity_invite()
            if vanity is not None:
                e.add_field(name="Server Vanity invite", value=vanity)
        except Forbidden:
            pass

        roles = [role.mention for role in interaction.guild.roles]
        e.add_field(name='Roles', value=', '.join(roles) if len(roles) < 20 else f'{len(roles)} roles', inline=False)
        e.add_field(name="Creation Date", value=timed_events.Timestamp(interaction.guild.created_at).date_relative)
        return await self.bot.reply(interaction, embed=e)


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Load the Info cog into the bot"""
    return await bot.add_cog(Info(bot))
