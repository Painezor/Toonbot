"""Allow guilds to add a list of their own streams to keep track of events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from discord import Embed, Permissions, Member, Interaction, Message
from discord.app_commands import autocomplete, Choice, Group, describe
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from core import Bot


@dataclass
class Stream:
    """A generic dataclass representing a stream"""
    link: str
    added_by: Member
    name: str = None

    def __str__(self):
        return f"[{self.link if self.name is None else self.name}]({self.link}) added by {self.added_by.mention}"


async def st_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Return List of Guild Streams"""
    guild_streams = interaction.client.streams.get(interaction.guild.id, {})
    m = [i.name[:100] for i in guild_streams if current.lower() in i.name.lower() + i.link.lower()]
    return [Choice(name=item, value=item) for item in m if current.lower() in item.lower()][:25]


class GuildStreams(Cog):
    """Guild specific stream listings."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    prm = Permissions(manage_messages=True)
    streams = Group(name="streams", description="Stream list for your server", guild_only=True, default_permissions=prm)

    @streams.command()
    async def list(self, interaction: Interaction) -> Message:
        """List all streams for the match added by users."""
        if not (guild_streams := self.bot.streams.get(interaction.guild.id, {})):
            return await self.bot.reply(interaction, content="Nobody has added any streams yet.")

        e = Embed(title="Streams", description="\n".join([str(i) for i in guild_streams]))
        return await self.bot.reply(interaction, embed=e)

    @streams.command(name="add")
    @describe(name="Enter a name for the stream", link="Enter the link oF the stream")
    async def add_stream(self, interaction: Interaction, link: str, name: str):
        """Add a stream to the stream list."""
        if not (guild_streams := self.bot.streams.get(interaction.guild.id, {})):
            self.bot.streams[interaction.guild.id] = []

        if link in [i.link for i in guild_streams]:
            return await self.bot.error(interaction, "Already in stream list.")

        stream = Stream(name=name, link=link, added_by=interaction.user)
        self.bot.streams[interaction.guild.id].append(stream)

        e: Embed = Embed(title="Streams", description="\n".join([str(i) for i in guild_streams]))
        await self.bot.reply(interaction, content=f"Added <{stream.link}> to stream list.", embed=e)

    @streams.command(name="clear")
    async def clear_streams(self, interaction: Interaction):
        """Remove all streams from guild stream list"""
        self.bot.streams[interaction.guild.id] = []
        await self.bot.reply(interaction, content=f"{interaction.guild.name} stream list cleared.")

    @streams.command(name="delete")
    @autocomplete(stream=st_ac)
    async def delete_stream(self, interaction: Interaction, stream: str):
        """Delete a stream from the stream list"""
        guild_streams = self.bot.streams.get(interaction.guild.id, {})

        if not (matches := [i for i in guild_streams if stream.lower() in f"{i.name.lower()} {i.link.lower()}"]):
            err = f"Couldn't find that stream in {interaction.guild.name} stream list."
            return await self.bot.error(interaction, err)

        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            if not (matches := [i for i in matches if i.added_by == interaction.user]):
                err = "You cannot remove a stream you did not add unless you have manage_messages permissions"
                return await self.bot.error(interaction, err)

        s = self.bot.streams.get(interaction.guild.id, {})
        self.bot.streams[interaction.guild.id] = [i for i in s if i not in matches]

        msg = "Removed " + "\n".join([f"<{i.link}>" for i in matches]) + f" from {interaction.guild.name} stream list"
        e = Embed(title=f"{interaction.guild.name} Streams", description="\n".join([str(i) for i in guild_streams]))
        await self.bot.reply(interaction, content=msg, embed=e)


async def setup(bot: Bot) -> None:
    """Load the streams cog into the bot"""
    await bot.add_cog(GuildStreams(bot))
