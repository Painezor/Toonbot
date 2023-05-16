"""Allow guilds to add a list of their own streams to keep track of events."""
from __future__ import annotations

import collections
from typing import TYPE_CHECKING, TypeAlias, cast

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member


class Stream:
    """A generic dataclass representing a stream"""

    def __init__(self, name: str, link: str, added_by: User) -> None:
        self.name: str = name
        self.link: str = link
        self.added_by: User = added_by

    def __str__(self):
        return f"[{self.name}]({self.link}) added by {self.added_by.mention}"


async def st_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Return List of Guild Streams"""
    if interaction.guild is None:
        return []

    bot = interaction.client

    cog = cast(GuildStreams, bot.get_cog(GuildStreams.__cog_name__))
    cur = current.casefold()
    options: list[discord.app_commands.Choice[str]] = []

    for i in cog.streams[interaction.guild.id]:
        if cur not in f"{i.name} {i.link}".casefold():
            continue

        val = i.name[:100]
        options.append(discord.app_commands.Choice(name=val, value=val))

        if len(options) == 25:
            break

    return options


class GuildStreams(commands.Cog):
    """Guild specific stream listings."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.streams: dict[int, list[Stream]] = collections.defaultdict(list)

    strmcmd = discord.app_commands.Group(
        name="streams",
        description="Stream list for your server",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )

    @strmcmd.command()
    async def list(self, interaction: Interaction) -> None:
        """List all streams for the match added by users."""
        if interaction.guild is None:
            raise commands.NoPrivateMessage

        if not (strms := self.streams[interaction.guild.id]):
            err = "Nobody has added any streams yet."
            embed = discord.Embed()
            embed.description = "🚫 " + err
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        embed = discord.Embed(title="Streams")
        embed.description = "\n".join([str(i) for i in strms])
        return await interaction.response.send_message(embed=embed)

    @strmcmd.command(name="add")
    @discord.app_commands.describe(name="Stream Name", link="Stream Link")
    async def add_stream(self, interaction: Interaction, link: str, name: str):
        """Add a stream to the stream list."""
        if interaction.guild is None:
            raise commands.NoPrivateMessage

        if not (guild_streams := self.streams[interaction.guild.id]):
            self.streams[interaction.guild.id] = []

        if link in [i.link for i in guild_streams]:
            embed = discord.Embed()
            embed.description = "🚫 Already in stream list"
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        stream = Stream(name=name, link=link, added_by=interaction.user)
        self.streams[interaction.guild.id].append(stream)

        embed = discord.Embed(title="Streams")
        embed.description = "\n".join([str(i) for i in guild_streams])

        msg = f"Added <{stream.link}> to stream list."
        return await interaction.response.send_message(
            content=msg, embed=embed
        )

    @strmcmd.command(name="clear")
    async def clear_streams(self, interaction: Interaction) -> None:
        """Remove all streams from guild stream list"""
        if interaction.guild is None:
            raise commands.NoPrivateMessage

        self.streams[interaction.guild.id] = []
        msg = f"{interaction.guild.name} stream list cleared."
        return await interaction.response.send_message(content=msg)

    @strmcmd.command(name="delete")
    @discord.app_commands.autocomplete(stream=st_ac)
    async def delete_stream(
        self, interaction: Interaction, stream: str
    ) -> None:
        """Delete a stream from the stream list"""
        if interaction.guild is None or interaction.channel is None:
            raise commands.NoPrivateMessage

        strms = self.streams[interaction.guild.id]

        name = stream.casefold()

        matches = [i for i in strms if name in f"{i.name} {i.link}".casefold()]

        if not matches:
            err = f"🚫 {stream} not in {interaction.guild.name} stream list."
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = err
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        perms = interaction.channel.permissions_for(interaction.guild.me)
        if not perms.manage_messages:
            user = interaction.user
            if not (matches := [i for i in matches if i.added_by == user]):
                err = "🚫 You did not add that stream and you are not a mod."
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = err
                reply = interaction.response.send_message
                return await reply(embed=embed, ephemeral=True)

        g_streams = self.streams.get(interaction.guild.id, {})

        new = [i for i in g_streams if i not in matches]
        self.streams[interaction.guild.id] = new

        txt = "\n".join([f"<{i.link}>" for i in matches])
        msg = f"Removed {txt} from {interaction.guild.name} stream list"

        embed = discord.Embed(title=f"{interaction.guild.name} Streams")
        embed.description = "\n".join([str(i) for i in strms])
        return await interaction.response.send_message(
            content=msg, embed=embed
        )


async def setup(bot: Bot) -> None:
    """Load the streams cog into the bot"""
    await bot.add_cog(GuildStreams(bot))
