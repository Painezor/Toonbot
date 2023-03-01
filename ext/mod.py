"""Moderation Commands"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional
import typing

from discord import (
    Guild,
    Member,
    TextChannel,
    Interaction,
    Colour,
    Embed,
    TextStyle,
)
import discord
from discord.app_commands import (
    default_permissions,
    guild_only,
    Choice,
)
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ui import Modal, TextInput

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class DiscordColours(Enum):
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


async def colour_ac(_: Interaction[Bot], current: str) -> list[Choice]:
    """Return from list of colours"""
    return [
        Choice(name=i.value, value=i.value)
        for i in DiscordColours
        if current.casefold() in i.value.casefold()
    ][:25]


class EmbedModal(Modal, title="Send an Embed"):
    """A Modal to allow the author to send an embedded message"""

    e_title = TextInput(label="Embed Title", placeholder="Announcement")

    text = TextInput(
        label="Embed Text",
        placeholder="Enter your text here",
        style=TextStyle.paragraph,
        max_length=4000,
    )

    thumbnail = TextInput(
        label="Thumbnail",
        required=False,
        placeholder="Enter url for thumbnail image",
    )

    image = TextInput(
        label="Image", placeholder="Enter url for large image", required=False
    )

    def __init__(
        self,
        bot: Bot | PBot,
        interaction: Interaction[Bot | PBot],
        destination: TextChannel,
        colour: Colour,
    ) -> None:

        super().__init__()

        self.bot: Bot | PBot = bot
        self.interaction: Interaction[Bot | PBot] = interaction
        self.destination: TextChannel = destination
        self.colour: Colour = colour

    async def on_submit(self) -> None:
        """Send the embed"""
        e = Embed(title=self.e_title, colour=self.colour)

        g = typing.cast(Guild, self.interaction.guild)

        if g is None:
            raise

        icon_url = g.icon.url if g.icon else None
        e.set_author(name=g.name, icon_url=icon_url)

        if self.image.value is not None:
            if "http:" in self.image.value:
                e.set_image(url=self.image.value)

        if self.thumbnail.value is not None:
            if "http:" in self.thumbnail.value:
                e.set_thumbnail(url=self.thumbnail.value)

        e.description = self.text.value

        try:
            await self.destination.send(embed=e)
            await self.bot.reply(
                self.interaction, "Message sent.", ephemeral=True
            )
        except discord.HTTPException:
            err = "I can't send messages to that channel."
            await self.bot.error(self.interaction, err)


class Mod(Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: PBot | Bot = bot

    @discord.app_commands.command()
    @guild_only()
    @default_permissions(manage_messages=True)
    @discord.app_commands.autocomplete(colour=colour_ac)
    @discord.app_commands.describe(
        destination="Choose Target Channel", colour="Choose embed colour"
    )
    async def embed(
        self,
        interaction: Interaction[Bot],
        destination: Optional[TextChannel],
        colour: str = "random",
    ) -> None:
        """Send an embedded announcement as the bot in a specified channel"""

        await interaction.response.defer(thinking=True, ephemeral=True)

        if destination is None:
            destination = typing.cast(TextChannel, interaction.channel)

        if interaction.guild is None:
            return await self.bot.error(interaction, "Can't be used in DMs")

        # TODO: Fuck this, go add all of the actual dcolos to the damn Enum.
        clr = next(
            (i.name for i in DiscordColours if i.value == colour), "random"
        )
        cl: Colour = getattr(Colour, clr)()

        if destination.guild.id != interaction.guild.id:
            err = "You cannot send messages to other servers."
            return await self.bot.error(interaction, err)

        perms = destination.permissions_for(interaction.guild.me)
        loc = destination.mention

        if not perms.send_messages:
            err = f"Bot missing permission: {loc} ❌ send_messages"
            return await self.bot.error(interaction, err)
        if not perms.embed_links:
            err = f"Bot missing permission: {loc} ❌ embed_links"
            return await self.bot.error(interaction, err)

        modal = EmbedModal(self.bot, interaction, destination, cl)

        await interaction.response.send_modal(modal)

    @discord.app_commands.command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @discord.app_commands.describe(
        message="Enter a message to send as the bot",
        destination="Choose Target Channel",
    )
    async def say(
        self,
        interaction: Interaction[Bot],
        message: str,
        destination: Optional[TextChannel] = None,
    ) -> discord.Message:
        """Say something as the bot in specified channel"""

        await interaction.response.defer(thinking=True, ephemeral=True)

        if destination is None:
            destination = typing.cast(TextChannel, interaction.channel)

        if interaction.guild is None:
            return await self.bot.error(interaction, "Can't be used in DMs")

        if len(message) > 2000:
            err = "Message too long. Keep it under 2000."
            return await self.bot.error(interaction, err)

        if destination.guild.id != interaction.guild.id:
            err = "You cannot send messages to other servers."
            return await self.bot.error(interaction, err)

        try:
            await destination.send(message)
            msg = "Message sent."
            return await interaction.edit_original_response(content=msg)
        except discord.HTTPException:
            err = "I can't send messages to that channel."
            return await interaction.edit_original_response(content=err)

    @discord.app_commands.command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @discord.app_commands.describe(
        number="Enter the maximum number of messages to delete."
    )
    async def clean(self, interaction: Interaction[Bot], number: int = 10):
        """Deletes my messages from the last x messages in channel"""

        await interaction.response.defer(thinking=True)

        def is_me(m):
            """Return only messages sent by the bot."""
            return m.author.id == self.bot.application_id

        channel = typing.cast(TextChannel, interaction.channel)
        reason = f"/clean ran by {interaction.user}"
        try:
            d = await channel.purge(limit=number, check=is_me, reason=reason)

            msg = f'♻ Deleted {len(d)} bot message{"s" if len(d) > 1 else ""}'
            await self.bot.reply(interaction, msg)
        except discord.HTTPException:
            pass

    @discord.app_commands.command()
    @default_permissions(moderate_members=True)
    @bot_has_permissions(moderate_members=True)
    @discord.app_commands.describe(
        member="Pick a user to untimeout",
        reason="Enter the reason for ending the timeout.",
    )
    async def untimeout(
        self,
        interaction: Interaction[Bot],
        member: Member,
        reason: str = "Not provided",
    ):
        """End the timeout for a user."""
        if not member.is_timed_out():
            err = "That user is not timed out."
            return await self.bot.error(interaction, err)

        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}")
            e = Embed(title="User Un-Timed Out", color=Colour.dark_magenta())
            e.description = f"{member.mention} is no longer timed out."
            await self.bot.reply(interaction, embed=e)
        except discord.HTTPException:
            await self.bot.error(interaction, "I can't un-timeout that user.")

    # Listeners
    @Cog.listener()
    async def on_guild_join(self, guild: Guild) -> None:
        """Create database entry for new guild"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                       ON CONFLICT DO NOTHING"""
                await connection.execute(q, guild.id)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        """Delete guild's info upon leaving one."""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """DELETE FROM guild_settings WHERE guild_id = $1"""
                await connection.execute(q, guild.id)


async def setup(bot: Bot | PBot):
    """Load the mod cog into the bot"""
    await bot.add_cog(Mod(bot))
