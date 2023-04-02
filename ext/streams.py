"""Allow guilds to add a list of their own streams to keep track of events."""
from __future__ import annotations

import typing

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from core import Bot


class Stream:
    """A generic dataclass representing a stream"""

    def __init__(
        self, name: str, link: str, added_by: discord.Member | discord.User
    ) -> None:
        self.name: str = name
        self.link: str = link
        self.added_by: discord.Member | discord.User = added_by

    def __str__(self):
        text = self.link if self.name is None else self.name
        return f"[{text}]({self.link}) added by {self.added_by.mention}"

    @property
    def ac_row(self) -> str:
        """casefold version of name and link for autocomplete purposes"""
        return f"{self.name} {self.link}".casefold()


async def st_ac(
    ctx: discord.Interaction[Bot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Return List of Guild Streams"""
    if ctx.guild is None:
        return []

    strms = ctx.client.streams[ctx.guild.id]
    cur = current.casefold()
    matches = [i.name[:100] for i in strms if cur in i.ac_row]

    options = []
    for item in matches:
        options.append(discord.app_commands.Choice(name=item, value=item))

        if len(options) == 25:
            break

    return options


class GuildStreams(commands.Cog):
    """Guild specific stream listings."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    streams = discord.app_commands.Group(
        name="streams",
        description="Stream list for your server",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )

    @streams.command()
    async def list(self, interaction: discord.Interaction[Bot]) -> None:
        """List all streams for the match added by users."""
        if interaction.guild is None:
            raise commands.NoPrivateMessage

        if not (strms := self.bot.streams[interaction.guild.id]):
            err = "Nobody has added any streams yet."
            return await self.bot.error(interaction, err)

        embed = discord.Embed(title="Streams")
        embed.description = "\n".join([str(i) for i in strms])
        return await interaction.response.send_message(embed=embed)

    @streams.command(name="add")
    @discord.app_commands.describe(name="Stream Name", link="Stream Link")
    async def add_stream(
        self, interaction: discord.Interaction[Bot], link: str, name: str
    ):
        """Add a stream to the stream list."""
        if interaction.guild is None:
            raise commands.NoPrivateMessage

        if not (guild_streams := self.bot.streams[interaction.guild.id]):
            self.bot.streams[interaction.guild.id] = []

        if link in [i.link for i in guild_streams]:
            return await self.bot.error(interaction, "Already in stream list.")

        stream = Stream(name=name, link=link, added_by=interaction.user)
        self.bot.streams[interaction.guild.id].append(stream)

        embed = discord.Embed(title="Streams")
        embed.description = "\n".join([str(i) for i in guild_streams])

        msg = f"Added <{stream.link}> to stream list."
        return await interaction.response.send_message(
            content=msg, embed=embed
        )

    @streams.command(name="clear")
    async def clear_streams(
        self, interaction: discord.Interaction[Bot]
    ) -> None:
        """Remove all streams from guild stream list"""
        if interaction.guild is None:
            raise commands.NoPrivateMessage

        self.bot.streams[interaction.guild.id] = []
        msg = f"{interaction.guild.name} stream list cleared."
        return await interaction.response.send_message(content=msg)

    @streams.command(name="delete")
    @discord.app_commands.autocomplete(stream=st_ac)
    async def delete_stream(
        self, interaction: discord.Interaction[Bot], stream: str
    ) -> discord.InteractionMessage:
        """Delete a stream from the stream list"""
        await interaction.response.defer(thinking=True)

        if interaction.guild is None or interaction.channel is None:
            raise commands.NoPrivateMessage

        strms = interaction.client.streams[interaction.guild.id]

        name = stream.casefold()

        matches = [i for i in strms if name in f"{i.name} {i.link}".casefold()]

        if not matches:
            err = f"{stream} not in {interaction.guild.name} stream list."
            return await self.bot.error(interaction, err)

        perms = interaction.channel.permissions_for(interaction.guild.me)
        if not perms.manage_messages:
            user = interaction.user
            if not (matches := [i for i in matches if i.added_by == user]):
                err = "You did not add that stream and you are not a mod."
                return await self.bot.error(interaction, err)

        g_streams = self.bot.streams.get(interaction.guild.id, {})

        new = [i for i in g_streams if i not in matches]
        self.bot.streams[interaction.guild.id] = new

        txt = "\n".join([f"<{i.link}>" for i in matches])
        msg = f"Removed {txt} from {interaction.guild.name} stream list"

        embed = discord.Embed(title=f"{interaction.guild.name} Streams")
        embed.description = "\n".join([str(i) for i in strms])
        return await interaction.edit_original_response(
            content=msg, embed=embed
        )


async def setup(bot: Bot) -> None:
    """Load the streams cog into the bot"""
    await bot.add_cog(GuildStreams(bot))
