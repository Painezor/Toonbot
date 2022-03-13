"""Commands about the meta-state of the bot and information about users and servers"""
import datetime
from copy import deepcopy
from typing import Optional

from discord import Member, Embed, Colour, TextChannel, ButtonStyle, Forbidden, User, app_commands, Interaction
from discord.ext import commands
from discord.ui import View, Button

from ext.utils import timed_events, embed_utils, view_utils

INV = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
      "&scope=bot%20applications.commands"


@app_commands.context_menu(name="Get User Info")
async def u_info(interaction: Interaction, member: Member):
    """Show info about this member."""
    # Embed 1: Generic Info
    await interaction.response.defer(thinking=True)

    e = Embed(colour=member.colour)
    e.set_author(name=member)
    if member.avatar:
        e.set_thumbnail(url=member.display_avatar.url)
    e.description = f"{'🤖 ' if member.bot else ''}{member.mention}\nUser ID: {member.id}"
    try:
        e.description += "\n📱 Using mobile app." if member.is_on_mobile() else ""
        voice = member.voice
        if voice is not None:
            voice = voice.channel
            voice_other = len(voice.members) - 1
            voice = f'In voice channel {voice.mention} {f"with {voice_other} others" if voice_other else "alone"}'
            e.description += f'\n\n{voice}'
    except AttributeError:  # User.
        pass

    try:
        roles = [role.mention for role in reversed(member.roles) if not role.position == 0]
    except AttributeError:
        roles = []

    if roles:
        e.add_field(name='Roles', value=' '.join(roles))

    if member.banner is not None:
        e.set_image(url=member.banner.url)

    shared = sum(1 for m in interaction.client.get_all_members() if m.id == member.id) - 1
    if shared:
        e.set_footer(text=f"User shares {shared} discords with Toonbot")

    try:
        e.description += f'\nJoined Server: {timed_events.Timestamp(member.joined_at).countdown}'
    except AttributeError:
        pass
    e.description += f'\nCreated Account: {timed_events.Timestamp(member.created_at).countdown}'

    # Embed 2 - User Permissions
    permissions = interaction.channel.permissions_for(member)
    permissions = "\n".join([f"{i[0]} : {i[1]}" for i in permissions])
    perm_embed = deepcopy(e)
    perm_embed.description = permissions
    perm_embed.title = "Member Permissions"

    # Embed 3 - User Avatar
    av = Embed(colour=member.color, description=f"{member.mention}'s avatar")
    av.set_footer(text=member.display_avatar.url)
    av.set_image(url=member.display_avatar.url)
    av.timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Rest of embeds:
    matches = [f"`{i.id}:` **{i.name}**" for i in interaction.client.guilds if i.get_member(member.id) is not None]

    sh = Embed(colour=Colour.og_blurple())
    sh.set_footer(text=f"{member} (ID: {member})", icon_url=member.display_avatar.url)

    embeds = embed_utils.rows_to_embeds(sh, matches, 20, header=f"User found on {len(matches)} servers.")

    view = view_utils.Paginator(interaction, [e, perm_embed, av] + embeds)
    await view.update()


class Info(commands.Cog):
    """Get information about users or servers."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(u_info)

    @app_commands.command()
    async def server_info(self, interaction: Interaction):
        """Shows information about the server"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs.")

        e = Embed(title=interaction.guild.name)
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
            e.colour = await embed_utils.get_colour(str(interaction.guild.icon.url))

        emojis = ""
        for emoji in interaction.guild.emojis:
            if len(emojis) + len(str(emoji)) < 1024:
                emojis += str(emoji)

        if emojis:
            e.add_field(name="Emotes", value=emojis, inline=False)

        e.description += f"\n**Emotes**: {len(emojis)} / {interaction.guild.emoji_limit} slots used."
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
        await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    async def avatar(self, interaction: Interaction, user: Optional[User | Member]):
        """Shows a member's avatar"""
        user = interaction.user if user is None else user

        try:
            e = Embed(colour=user.color, description=f"{user.mention}'s avatar")
        except AttributeError:
            e = Embed(description=f"{user}'s avatar")

        e.set_footer(text=user.display_avatar.url)
        e.set_image(url=user.display_avatar.url)
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    async def invite(self, interaction: Interaction):
        """Get the bots invite link"""
        view = View()
        view.add_item(Button(style=ButtonStyle.url, url=INV, label="Invite me to your server"))
        e = Embed(description="Use the button below to invite me to your server.")
        await self.bot.reply(interaction, embed=e, view=view, ephemeral=True)

    @app_commands.command()
    async def about(self, interaction: Interaction):
        """Tells you information about the bot itself."""
        e = Embed(colour=0x2ecc71, timestamp=interaction.client.user.created_at)
        e.set_footer(text=f"Toonbot is coded by Painezor and was created on ")

        me = self.bot.user
        e.set_thumbnail(url=me.display_avatar.url)
        e.title = "About Toonbot"

        # statistics
        total_members = sum(len(s.members) for s in self.bot.guilds)
        members = f"{total_members} Members across {len(self.bot.guilds)} servers."

        e.description = f"I do football lookup related things.\n I have {members}"

        view = View()
        s = ("Join my Support Server", "http://www.discord.gg/a5NHvPx")
        i = ("Invite me to your server", INV)
        d = ("Donate", "https://paypal.me/Toonbot")
        for label, link in [s, i, d]:
            view.add_item(Button(style=ButtonStyle.url, url=link, label=label))
        await self.bot.reply(interaction, embed=e, view=view)


def setup(bot):
    """Load the Info cog into the bot"""
    bot.add_cog(Info(bot))
