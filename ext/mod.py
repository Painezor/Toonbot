"""Moderation Commands"""
from typing import Optional, Literal, TYPE_CHECKING, Union

from discord import Guild, Member, TextChannel, Interaction, Colour, Embed, HTTPException, Forbidden, Object, Message, \
    TextStyle, NotFound
from discord.app_commands import command, describe, default_permissions
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ui import Modal, TextInput

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class BanModal(Modal, title="Bulk ban user IDs"):
    """Modal for user to enter multi line bans on."""
    ban_list = TextInput(
        label="Enter User IDs to ban, one per line",
        style=TextStyle.paragraph,
        placeholder="12345678901234\n12345678901235\n12345678901236\n..."
    )
    reason = TextInput(label="Enter a reason", placeholder="<Insert your reason here>", default="No reason provided")

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        super().__init__()
        self.bot: Bot | PBot = bot

    async def on_submit(self, interaction: Interaction) -> None:
        """Ban users on submit."""
        e: Embed = Embed(title="Users Banned", description="")
        e.add_field(name="reason", value=self.reason.value)

        targets = [int(i.strip()) for i in self.ban_list.value.split('\n')]

        for i in targets:
            try:
                target = await self.bot.fetch_user(int(i))
            except NotFound:
                e.description += f"Could not find user with ID# {i}"
                continue

            try:
                await self.bot.http.ban(i, interaction.guild.id)
            except HTTPException:
                e.description += f"⚠ Banning failed for {i} {target}."
            else:
                e.description += f'☠ Banned UserID {i} {target}'
        await self.bot.reply(interaction, embed=e)


class EmbedModal(Modal, title="Send an Embed"):
    """A Modal to allow the author to send an embedded message"""
    e_title = TextInput(label="Embed Title", placeholder="Announcement")
    text = TextInput(label="Embed Text", placeholder="Enter your text here", style=TextStyle.paragraph, max_length=4000)
    thumbnail = TextInput(label="Thumbnail", placeholder="Enter url for thumbnail image", required=False)
    image = TextInput(label="Image", placeholder="Enter url for large image", required=False)

    def __init__(self, bot: 'Bot', interaction: Interaction, destination: TextChannel, colour: Colour) -> None:
        super().__init__()
        self.bot: Bot = bot
        self.interaction: Interaction = interaction
        self.destination: TextChannel = destination
        self.colour: Colour = colour

    async def on_submit(self, interaction: Interaction) -> None:
        """Send the embed"""
        e = Embed(title=self.e_title, colour=self.colour)
        e.set_author(name=self.interaction.guild.name, icon_url=self.interaction.guild.icon.url)

        if self.image.value is not None and "http:" in self.image.value:
            e.set_image(url=self.image.value)
        if self.thumbnail.value is not None and "http:" in self.thumbnail.value:
            e.set_thumbnail(url=self.thumbnail.value)
        try:
            await self.destination.send(embed=e)
            await self.bot.reply(interaction, content="Message sent.", ephemeral=True)
        except Forbidden:
            await self.bot.error(interaction, "I can't send messages to that channel.")


class Mod(Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    # TODO: Slash attachments pass
    @command()
    @default_permissions(manage_messages=True)
    @bot_has_permissions(manage_messages=True)
    @describe(destination="target channel", colour="embed colour")
    async def embed(self, interaction: Interaction, destination: TextChannel = None,
                    colour: Literal['red', 'blue', 'green', 'yellow', 'white'] = None) -> Message:
        """Send an embedded announcement as the bot in a specified channel"""
        destination = interaction.channel if destination is None else destination

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, "You cannot send messages to other servers.")

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
    async def say(self, interaction: Interaction, message: str, destination: Optional[TextChannel] = None) -> Message:
        """Say something as the bot in specified channel"""
        if len(message) > 2000:
            return await self.bot.error(interaction, "Message too long. Keep it under 2000.")

        destination = interaction.channel if destination is None else destination

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, "You cannot send messages to other servers.")

        try:
            await destination.send(message)
            await self.bot.reply(interaction, content="Message sent.", ephemeral=True)
        except Forbidden:
            return await self.bot.error(interaction, "I can't send messages to that channel.")

    @command()
    @default_permissions(manage_channels=True)
    @bot_has_permissions(manage_channels=True)
    @describe(new_topic="Type the new topic for this channel..")
    async def topic(self, interaction: Interaction, new_topic: str):
        """Set the topic for the current channel"""
        await interaction.channel.edit(topic=new_topic)
        await self.bot.reply(interaction, content=f"{interaction.channel.mention} Topic updated")

    @command()
    @default_permissions(manage_channels=True)
    @bot_has_permissions(manage_channels=True)
    @describe(message="Type a message to be pinned in this channel.")
    async def pin(self, interaction: Interaction, message: str):
        """Pin a message to the current channel"""
        message = await self.bot.reply(interaction, content=message)
        await message.pin()

    @command()
    @default_permissions(manage_nicknames=True)
    @bot_has_permissions(manage_nicknames=True)
    @describe(member="Pick a user to rename", new_nickname="Choose a new nickname for the member")
    async def rename(self, interaction: Interaction, member: Member, new_nickname: str):
        """Rename a member"""
        try:
            await member.edit(nick=new_nickname)
        except Forbidden:
            await self.bot.error(interaction, "I can't change that member's nickname.")
        except HTTPException:
            await self.bot.error(interaction, "❔ Member edit failed.")
        else:
            e = Embed(colour=Colour.og_blurple(), description=f"{member.mention} has been renamed.")
            await self.bot.reply(interaction, embed=e, ephemeral=True)

    @command()
    @default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def ban(self, interaction: Interaction):
        """Bans a list of user IDs"""
        await interaction.response.send_modal(BanModal(self.bot))

    @command()
    @default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    @describe(user_id="User ID# of the person to unban")
    async def unban(self, interaction: Interaction, user_id: str):
        """Unbans a user from the server"""
        try:
            await interaction.guild.unban(Object(int(user_id)))
        except ValueError:
            return await self.bot.error(interaction, "Invalid user ID provided.")
        except HTTPException:
            await self.bot.error(interaction, "I can't unban that user.")
        else:
            target = await self.bot.fetch_user(int(user_id))
            e = Embed(title=user_id, description=f"User ID: {user_id} ({target}) was unbanned", colour=Colour.green())
            await self.bot.reply(interaction, embed=e)

    # TODO: Banlist as View
    # TODO: Dropdown to unban users.
    @command()
    @default_permissions(view_audit_log=True)
    @bot_has_permissions(view_audit_log=True)
    async def banlist(self, interaction: Interaction) -> Message:
        """Show the ban list for the server"""
        bans = []
        async for x in interaction.guild.bans():
            bans.append(f"{x.user.id} | {x.user.name}#{x.user.discriminator}" f"```yaml\n{x.reason}```")

        if not bans:
            bans = ["No bans found"]

        e: Embed = Embed(color=0x111)
        n = f"{interaction.guild.name} ban list"
        _ = interaction.guild.icon.url if interaction.guild.icon is not None else None
        e.set_author(name=n, icon_url=_)

        embeds = rows_to_embeds(e, bans)
        view = Paginator(self.bot, interaction, embeds)
        return await view.update()

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
    async def on_guild_join(self, guild) -> None:
        """Create database entry for new guild"""
        q = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, guild.id)
        finally:
            await self.bot.db.release(connection)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        """Delete guild's info upon leaving one."""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM guild_settings WHERE guild_id = $1""", guild.id)
        finally:
            await self.bot.db.release(connection)


async def setup(bot: Union['Bot', 'PBot']):
    """Load the mod cog into the bot"""
    await bot.add_cog(Mod(bot))
