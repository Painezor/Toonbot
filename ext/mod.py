"""Moderation Commands"""
from __future__ import annotations

import enum
import typing
import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]


class DiscordColours(enum.Enum):
    """Valid Colours of discord.Colour"""

    BLUE = "blue"
    BLURPLE = "blurple"
    BRAND_GREEN = "brand_green"
    BRAND_RED = "brand_red"
    DARK_BLUE = "dark_blue"
    DARK_EMBED = "dark_embed"
    DARK_GOLD = "dark_gold"
    DARK_GRAY = "dark_gray"
    DARK_GREEN = "dark_gray"
    DARK_MAGENTA = "dark_magenta"
    DARK_ORANGE = "dark_orange"
    DARK_PURPLE = "dark_purple"
    DARK_RED = "dark_red"
    DARK_TEAL = "dark_teal"
    DARKER_GRAY = "darker_gray"
    DEFAULT = "default"
    FUCHSIA = "fuchsia"
    GOLD = "gold"
    GREEN = "green"
    GREYPLE = "greyple"
    LIGHT_EMBED = "light_embed"
    LIGHT_GRAY = "light_gray"
    LIGHTER_GRAY = "lighter_gray"
    MAGENTA = "magenta"
    OG_BLURPLE = "og_blurple"
    ORANGE = "orange"
    PURPLE = "purple"
    RANDOM = "random"
    RED = "red"
    TEAL = "teal"
    YELLOW = "yellow"


async def colour_ac(
    _: discord.Interaction[Bot], current: str
) -> list[discord.app_commands.Choice]:
    """Return from list of colours"""
    return [
        discord.app_commands.Choice(name=i.value, value=i.value)
        for i in DiscordColours
        if current.casefold() in i.value.casefold()
    ][:25]


class EmbedModal(discord.ui.Modal, title="Send an Embed"):
    """A Modal to allow the author to send an embedded message"""

    ttl = discord.ui.TextInput(label="Embed Title", placeholder="Announcement")

    text = discord.ui.TextInput(label="Embed Text", max_length=4000)
    text.style = discord.TextStyle.paragraph

    thumbnail = discord.ui.TextInput(label="Thumbnail", required=False)
    thumbnail.placeholder = "Enter url for thumbnail image"

    image = discord.ui.TextInput(label="Image", required=False)
    image.placeholder = "Enter url for large image"

    def __init__(
        self,
        destination: discord.TextChannel,
        colour: discord.Colour,
    ) -> None:

        super().__init__()
        self.destination: discord.TextChannel = destination
        self.colour: discord.Colour = colour

    async def on_submit(self, interaction: Interaction, /) -> None:
        """Send the embed"""
        await interaction.response.send_message("Sent!", ephemeral=True)
        embed = discord.Embed(title=self.ttl, colour=self.colour)

        guild = typing.cast(discord.Guild, interaction.guild)

        if guild is None:
            raise commands.NoPrivateMessage

        icon_url = guild.icon.url if guild.icon else None
        embed.set_author(name=guild.name, icon_url=icon_url)

        if self.image.value is not None:
            if "http:" in self.image.value:
                embed.set_image(url=self.image.value)

        if self.thumbnail.value is not None:
            if "http:" in self.thumbnail.value:
                embed.set_thumbnail(url=self.thumbnail.value)

        embed.description = self.text.value

        try:
            await self.destination.send(embed=embed)
        except discord.HTTPException:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 I can't send messages to that channel."
            await interaction.edit_original_response(embed=embed, content=None)


class Mod(commands.Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: PBot | Bot = bot

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(manage_messages=True)
    @discord.app_commands.autocomplete(colour=colour_ac)
    @discord.app_commands.describe(
        destination="Choose Target Channel", colour="Choose embed colour"
    )
    async def embed(
        self,
        interaction: Interaction,
        destination: typing.Optional[discord.TextChannel],
        colour: str = "random",
    ) -> None:
        """Send an embedded announcement as the bot in a specified channel"""
        if destination is None:
            destination = typing.cast(discord.TextChannel, interaction.channel)

        # TODO: Make this into a transformer
        clr = next(
            (i.value for i in DiscordColours if i.value == colour), "random"
        )
        colo: discord.Colour = getattr(discord.Colour, clr)()

        modal = EmbedModal(destination, colo)

        await interaction.response.send_modal(modal)

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(manage_messages=True)
    @discord.app_commands.checks.bot_has_permissions(manage_messages=True)
    @discord.app_commands.describe(
        message="Enter a message to send as the bot",
        destination="Choose Target Channel",
    )
    async def say(
        self,
        interaction: Interaction,
        message: str,
        destination: typing.Optional[discord.TextChannel] = None,
    ) -> discord.Message:
        """Say something as the bot in specified channel"""
        if destination is None:
            destination = typing.cast(discord.TextChannel, interaction.channel)

        if interaction.guild is None:
            raise discord.app_commands.NoPrivateMessage

        if len(message) > 2000:
            embed = discord.Embed()
            embed.description = "🚫 Message too long (2000 char max)."
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        if destination.guild.id != interaction.guild.id:
            err = "You cannot send messages to other servers."
            embed = discord.Embed()
            embed.description = "🚫 " + err
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        try:
            await destination.send(message)
            msg = "Message sent."
            return await interaction.edit_original_response(content=msg)
        except discord.HTTPException:
            err = "I can't send messages to that channel."
            return await interaction.edit_original_response(content=err)

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(manage_messages=True)
    @discord.app_commands.checks.bot_has_permissions(manage_messages=True)
    @discord.app_commands.describe(number="Number of messages to delete")
    async def clean(
        self, interaction: Interaction, number: int = 10
    ) -> discord.InteractionMessage:
        """Deletes my messages from the last x messages in channel"""
        await interaction.response.defer(thinking=True)

        def is_me(message):
            """Return only messages sent by the bot."""
            return message.author.id == self.bot.application_id

        channel = typing.cast(discord.TextChannel, interaction.channel)
        reason = f"/clean ran by {interaction.user}"

        dlt = await channel.purge(limit=number, check=is_me, reason=reason)

        msg = f'♻ Deleted {len(dlt)} bot message{"s" if len(dlt) > 1 else ""}'
        return await interaction.edit_original_response(content=msg)

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(moderate_members=True)
    @discord.app_commands.checks.bot_has_permissions(moderate_members=True)
    @discord.app_commands.describe(
        member="Pick a user to untimeout",
        reason="Enter the reason for ending the timeout.",
    )
    async def untimeout(
        self,
        interaction: Interaction,
        member: discord.Member,
        reason: str = "Not provided",
    ) -> None:
        """End the timeout for a user."""
        embed = discord.Embed(colour=discord.Colour.red())
        if not member.is_timed_out():
            embed.description = "That user is not timed out."
            return await interaction.response.send_message(embed=embed)

        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}")
            embed.title = "User Un-Timed Out"
            embed.color = discord.Colour.dark_magenta()
            embed.description = f"{member.mention} is no longer timed out."
        except discord.HTTPException:
            embed.description = "I can't un-timeout that user."
        return await interaction.response.send_message(embed=embed)

    # Listeners
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Create database entry for new guild"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                       ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Delete guild's info upon leaving one."""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM guild_settings WHERE guild_id = $1"""
                await connection.execute(sql, guild.id)


async def setup(bot: Bot | PBot):
    """Load the mod cog into the bot"""
    await bot.add_cog(Mod(bot))
