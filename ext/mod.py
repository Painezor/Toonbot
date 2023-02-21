"""Moderation Commands"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from discord import Guild, Member, TextChannel, Interaction, Colour, Embed, HTTPException, Message, TextStyle
from discord.app_commands import command, describe, default_permissions, guild_only, Choice, autocomplete
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ui import Modal, TextInput

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class DiscordColours(Enum):
    """Valid Colours of discord.Colour"""
    Blue = "blue"
    Blurple = "blurple"
    Brand_Green = "brand_green"
    Brand_Red = 'brand_red'
    Dark_Blue = 'dark_blue'
    Dark_Embed = 'dark_embed'
    Dark_Gold = 'dark_gold'
    Dark_Gray = 'dark_gray'
    Dark_Green = 'dark_gray'
    Dark_Magenta = 'dark_magenta'
    Dark_Orange = 'dark_orange'
    Dark_Purple = 'dark_purple'
    Dark_Red = 'dark_red'
    Dark_Teal = 'dark_teal'
    Darker_Gray = 'darker_gray'
    Default = 'default'
    Fuchsia = 'fuchsia'
    Gold = 'gold'
    Green = 'green'
    Greyple = 'greyple'
    Light_Embed = 'light_embed'
    Light_Gray = 'light_gray'
    Lighter_Gray = 'lighter_gray'
    Magenta = 'magenta'
    OG_Blurplee = 'og_blurple'
    Orange = 'orange'
    Purple = 'purple'
    Random = 'random'
    Red = 'red'
    Teal = 'teal'
    Yellow = 'yellow'


async def colour_ac(_: Interaction, current: str) -> list[Choice]:
    """Return from list of colours"""
    return [Choice(name=i.value, value=i.value) for i in DiscordColours if current.lower() in i.value.lower()][:25]


class EmbedModal(Modal, title="Send an Embed"):
    """A Modal to allow the author to send an embedded message"""
    e_title = TextInput(label="Embed Title", placeholder="Announcement")
    text = TextInput(label="Embed Text", placeholder="Enter your text here", style=TextStyle.paragraph, max_length=4000)
    thumbnail = TextInput(label="Thumbnail", placeholder="Enter url for thumbnail image", required=False)
    image = TextInput(label="Image", placeholder="Enter url for large image", required=False)

    def __init__(self, bot: Bot | PBot, interaction: Interaction, destination: TextChannel, colour: Colour) -> None:
        super().__init__()
        self.bot: Bot | PBot = bot
        self.interaction: Interaction = interaction
        self.destination: TextChannel = destination
        self.colour: Colour = colour

    async def on_submit(self, interaction: Interaction) -> None:
        """Send the embed"""
        e = Embed(title=self.e_title, colour=self.colour)

        try:
            e.set_author(name=self.interaction.guild.name, icon_url=self.interaction.guild.icon.url)
        except AttributeError:
            e.set_author(name=self.interaction.guild.name)

        if self.image.value is not None and "http:" in self.image.value:
            e.set_image(url=self.image.value)
        if self.thumbnail.value is not None and "http:" in self.thumbnail.value:
            e.set_thumbnail(url=self.thumbnail.value)

        e.description = self.text.value

        try:
            await self.destination.send(embed=e)
            await self.bot.reply(interaction, "Message sent.", ephemeral=True)
        except HTTPException:
            await self.bot.error(interaction, "I can't send messages to that channel.")


class Mod(Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @command()
    @guild_only()
    @default_permissions(manage_messages=True)
    @autocomplete(colour=colour_ac)
    @describe(destination="Choose Target Channel", colour="Choose embed colour")
    async def embed(self, interaction: Interaction, destination: TextChannel = None, colour: str = 'random') \
            -> Message:
        """Send an embedded announcement as the bot in a specified channel"""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if destination is None:
            destination = interaction.channel

        # In theory this should get the class method from the Colour class and perform it.
        colour: Colour = getattr(Colour, next((i for i in DiscordColours if i.value == colour), "random"))()

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, "You cannot send messages to other servers.")

        perms = destination.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            err = f"Bot missing permission: {destination.mention} ❌ send_messages"
            return await self.bot.error(interaction, err)
        if not perms.embed_links:
            return await self.bot.error(interaction, f"Bot missing permission: {destination.mention} ❌ embed_links")

        modal = EmbedModal(self.bot, interaction, destination, colour)
        await interaction.response.send_modal(modal)

    @command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @describe(message="Enter a message to send as the bot", destination="Choose Target Channel")
    async def say(self, interaction: Interaction, message: str, destination: TextChannel = None) -> Message:
        """Say something as the bot in specified channel"""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if destination is None:
            destination = interaction.channel

        if len(message) > 2000:
            return await self.bot.error(interaction, "Message too long. Keep it under 2000.")

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, "You cannot send messages to other servers.")

        try:
            await destination.send(message)
            await interaction.edit_original_response(content="Message sent.")
        except HTTPException:
            return interaction.edit_original_response(content="I can't send messages to that channel.")

    @command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @describe(number="Enter the maximum number of messages to delete.")
    async def clean(self, interaction: Interaction, number: int = 10):
        """Deletes my messages from the last x messages in channel"""
        await interaction.response.defer(thinking=True)

        def is_me(m):
            """Return only messages sent by the bot."""
            return m.author.id == self.bot.user.id

        try:
            d = await interaction.channel.purge(limit=number, check=is_me, reason=f"/clean ran by {interaction.user}")
            await self.bot.reply(interaction, content=f'♻ Deleted {len(d)} bot message{"s" if len(d) > 1 else ""}')
        except HTTPException:
            pass

    @command()
    @default_permissions(moderate_members=True)
    @bot_has_permissions(moderate_members=True)
    @describe(member="Pick a user to untimeout", reason="Enter the reason for ending the timeout.")
    async def untimeout(self, interaction: Interaction, member: Member, reason: str = "Not provided"):
        """End the timeout for a user."""
        if not member.is_timed_out():
            return await self.bot.error(interaction, "That user is not timed out.")

        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}")
            e: Embed = Embed(title="User Un-Timed Out", color=Colour.dark_magenta())
            e.description = f"{member.mention} is no longer timed out."
            await self.bot.reply(interaction, embed=e)
        except HTTPException:
            await self.bot.error(interaction, "I can't un-timeout that user.")

    # Listeners
    @Cog.listener()
    async def on_guild_join(self, guild: Guild) -> None:
        """Create database entry for new guild"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(q, guild.id)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        """Delete guild's info upon leaving one."""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute("""DELETE FROM guild_settings WHERE guild_id = $1""", guild.id)


async def setup(bot: Bot | PBot):
    """Load the mod cog into the bot"""
    await bot.add_cog(Mod(bot))
