"""Moderation Commands"""
from __future__ import annotations

from typing import Literal, TYPE_CHECKING

from discord import Guild, Member, TextChannel, Interaction, Colour, Embed, HTTPException, Forbidden, Object, Message, \
    TextStyle, NotFound
from discord.app_commands import command, describe, default_permissions, guild_only
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ui import Modal, TextInput

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


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
            await self.bot.reply(interaction, content="Message sent.", ephemeral=True)
        except Forbidden:
            await self.bot.error(interaction, content="I can't send messages to that channel.")


class Mod(Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    # TODO: Slash attachments pass
    # TODO: Custom RGB Colour for embed command
    @command()
    @guild_only()
    @default_permissions(manage_messages=True)
    @describe(destination="target channel", colour="embed colour")
    async def embed(self, interaction: Interaction, destination: TextChannel = None,
                    colour: Literal['red', 'blue', 'green', 'yellow', 'white'] = None) -> Message:
        """Send an embedded announcement as the bot in a specified channel"""
        destination = interaction.channel if destination is None else destination

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, content="You cannot send messages to other servers.")

        perms = destination.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            return await self.bot.error(interaction, content="I need send_messages permissions in that channel.")
        if not perms.embed_links:
            return await self.bot.error(interaction, content="I need embed_links permissions in that channel.")

        match colour:
            case 'red':
                colour = Colour.red()
            case 'blue':
                colour = Colour.blue()
            case 'green':
                colour = Colour.green()
            case 'yellow':
                colour = Colour.yellow()
            case 'white':
                colour = Colour.light_gray()

        modal = EmbedModal(self.bot, interaction, destination, colour)
        await interaction.response.send_modal(modal)

    @command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @describe(message="text to send", destination="target channel")
    async def say(self, interaction: Interaction, message: str, destination: TextChannel = None) -> Message:
        """Say something as the bot in specified channel"""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if len(message) > 2000:
            return await self.bot.error(interaction, content="Message too long. Keep it under 2000.")

        destination = interaction.channel if destination is None else destination

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, content="You cannot send messages to other servers.")

        try:
            await destination.send(message)
            await interaction.edit_original_response(content="Message sent.")
        except Forbidden:
            return interaction.edit_original_response(content="I can't send messages to that channel.")

    @command()
    @default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    @describe(user_id="User ID# of the person to unban")
    async def unban(self, interaction: Interaction, user_id: str):
        """Unbans a user from the server"""
        try:
            await interaction.guild.unban(Object(int(user_id)))
        except ValueError:
            return await self.bot.error(interaction, content="Invalid user ID provided.")
        except HTTPException:
            await self.bot.error(interaction, content="I can't unban that user.")
        else:
            target = await self.bot.fetch_user(int(user_id))
            e = Embed(title=user_id, description=f"User ID: {user_id} ({target}) was unbanned", colour=Colour.green())
            await self.bot.reply(interaction, embed=e)

    @command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @describe(number="Number of messages to delete.")
    async def clean(self, interaction: Interaction, number: int = None):
        """Deletes my messages from the last x messages in channel"""
        await interaction.response.defer(thinking=True)

        def is_me(m):
            """Return only messages sent by the bot."""
            return m.author.id == self.bot.user.id

        number = 10 if number is None else number

        try:
            d = await interaction.channel.purge(limit=number, check=is_me, reason=f"/clean ran by {interaction.user}")
            c = f'♻ Deleted {len(d)} bot message{"s" if len(d) > 1 else ""}'
            await self.bot.reply(interaction, content=c)
        except NotFound:
            pass

    @command()
    @default_permissions(moderate_members=True)
    @bot_has_permissions(moderate_members=True)
    @describe(member="The user to untimeout", reason="reason for ending the timeout")
    async def untimeout(self, interaction: Interaction, member: Member, reason: str = "Not provided"):
        """End the timeout for a user."""
        if not member.is_timed_out():
            return await self.bot.error(interaction, content="That user is not timed out.")

        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}")
            e: Embed = Embed(title="User Un-Timed Out", color=Colour.dark_magenta())
            e.description = f"{member.mention} is no longer timed out."
            await self.bot.reply(interaction, embed=e)
        except HTTPException:
            await self.bot.error(interaction, content="I can't un-timeout that user.")

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
