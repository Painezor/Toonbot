"""Moderation Commands"""
from __future__ import annotations
import asyncio

import typing
from discord import Colour
from discord.app_commands import Choice
import discord

from discord.ui import TextInput
from discord.ext import commands

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]

exclude = ("r", "g", "b", "hsv", "grey", "grey", "from_", "__")
colours = [i for i in dir(Colour) if not i.startswith(exclude)]


async def colour_ac(_: Interaction, current: str) -> list[Choice[str]]:
    """Return from list of colours"""
    cur = current.casefold()
    return [Choice(name=i, value=i) for i in colours if cur in i][:25]


class EmbedModal(discord.ui.Modal, title="Send an Embed"):
    """A Modal to allow the author to send an embedded message"""

    ttl: TextInput[EmbedModal]
    ttl = TextInput(label="Embed Title", placeholder="Announcement")

    text: TextInput[EmbedModal]
    text = TextInput(label="Embed Text", max_length=4000)
    text.style = discord.TextStyle.paragraph

    thumbnail: TextInput[EmbedModal]
    thumbnail = TextInput(label="Thumbnail", required=False)
    thumbnail.placeholder = "Enter url for thumbnail image"

    image: TextInput[EmbedModal] = TextInput(label="Image", required=False)
    image.placeholder = "Enter url for large image"

    def __init__(
        self,
        destination: discord.TextChannel,
        colour: Colour,
    ) -> None:
        super().__init__()
        self.destination: discord.TextChannel = destination
        self.colour: Colour = colour

    async def on_submit(self, interaction: discord.Interaction, /) -> None:
        """Send the embed"""

        embed = discord.Embed(title=self.ttl, colour=self.colour)
        guild = typing.cast(discord.Guild, interaction.guild)

        icon_url = guild.icon.url if guild.icon else None
        embed.set_author(name=guild.name, icon_url=icon_url)

        if "http:" in self.image.value:
            embed.set_image(url=self.image.value)

        if "http:" in self.thumbnail.value:
            embed.set_thumbnail(url=self.thumbnail.value)

        embed.description = self.text.value

        try:
            await self.destination.send(embed=embed)
            await interaction.response.send_message("Sent!", ephemeral=True)
            return
        except discord.HTTPException:
            pass
        embed = discord.Embed(colour=Colour.red())
        embed.description = "🚫 I can't send messages to that channel."
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
        destination: discord.TextChannel | None,
        colour: str = "random",
    ) -> None:
        """Send an embedded announcement as the bot in a specified channel"""
        if destination is None:
            destination = typing.cast(discord.TextChannel, interaction.channel)

        colo: Colour = getattr(Colour, colour)()
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
        destination: discord.TextChannel | None = None,
    ) -> None:
        """Say something as the bot in specified channel"""
        if destination is None:
            destination = typing.cast(discord.TextChannel, interaction.channel)

        if interaction.guild is None:
            raise discord.app_commands.NoPrivateMessage

        say_reply = interaction.response.send_message
        if len(message) > 2000:
            embed = discord.Embed()
            embed.description = "🚫 Message too long (2000 char max)."
            return await say_reply(embed=embed, ephemeral=True)

        if destination.guild.id != interaction.guild.id:
            err = "You cannot send messages to other servers."
            embed = discord.Embed()
            embed.description = "🚫 " + err
            return await say_reply(embed=embed, ephemeral=True)

        try:
            await destination.send(message)
            return await say_reply(content="Sent!", ephemeral=True)
        except discord.HTTPException:
            embed = discord.Embed(colour=Colour.red())
            embed.description = "🚫 I can't send messages to that channel."
            return await say_reply(embed=embed, ephemeral=True)

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(manage_messages=True)
    @discord.app_commands.checks.bot_has_permissions(manage_messages=True)
    @discord.app_commands.describe(number="Number of messages to delete")
    async def clean(self, interaction: Interaction, number: int = 10) -> None:
        """Deletes my messages from the last x messages in channel"""
        await interaction.response.defer()

        def is_me(message: discord.Message):
            """Return only messages sent by the bot."""
            return message.author.id == self.bot.application_id

        channel = typing.cast(discord.TextChannel, interaction.channel)
        reason = f"/clean ran by {interaction.user}"

        dlt = await channel.purge(limit=number, check=is_me, reason=reason)

        msg = f'♻ Deleted {len(dlt)} bot message{"s" if len(dlt) > 1 else ""}'
        msg = await interaction.followup.send(content=msg)
        await asyncio.sleep(5)

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
        embed = discord.Embed(colour=Colour.red())
        if not member.is_timed_out():
            embed.description = "That user is not timed out."
            return await interaction.response.send_message(embed=embed)

        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}")
            embed.title = "User Un-Timed Out"
            embed.color = Colour.dark_magenta()
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
