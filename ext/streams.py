"""Allow guilds to add a list of their own streams to keep track of events."""
from collections import defaultdict
from dataclasses import dataclass
from typing import List

from discord import Embed, Member, app_commands, Interaction
from discord.ext import commands


@dataclass
class Stream:
    """A generic dataclass representing a stream"""
    link: str
    added_by: Member
    name: str = None

    def __str__(self):
        return f"[{self.link if self.name is None else self.name}]({self.link}) added by {self.added_by.mention}"


async def streams(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Return list of live leagues"""
    guild_streams = interaction.client.streams[interaction.guild.id]
    matches = [i.name for i in guild_streams if current.lower() in i.name.lower() + i.link.lower()]
    return [app_commands.Choice(name=item, value=item) for item in matches if current.lower() in item.lower()]


class Streams(app_commands.Group):
    """Stream list for your server"""

    @app_commands.command()
    async def list(self, interaction):
        """List all streams for the match added by users."""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be used in DMs")

        guild_streams = interaction.client.streams[interaction.guild.id]

        if not guild_streams:
            return await interaction.client.reply(interaction, content="Nobody has added any streams yet.")

        e = Embed(title="Streams", description="\n".join([str(i) for i in guild_streams]))
        await interaction.client.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.describe(name="Enter a name for the stream", link="Enter the link oF the stream")
    async def add(self, interaction: Interaction, link: str, name: str):
        """Add a stream to the stream list."""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be used in DMs")

        guild_streams = interaction.client.streams[interaction.guild.id]

        if link in [i.link for i in guild_streams]:
            return await interaction.client.error(interaction, "Already in stream list.")

        stream = Stream(name=name, link=link, added_by=interaction.user)
        interaction.client.streams[interaction.guild.id].append(stream)

        e = Embed(title="Streams", description="\n".join([str(i) for i in guild_streams]))
        await interaction.client.reply(interaction, content=f"Added <{stream.link}> to stream list.", embed=e)

    @app_commands.command()
    async def clear(self, interaction: Interaction):
        """Remove all streams from guild stream list"""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be used in DMs")

        if not interaction.permissions.manage_messages:
            err = "You cannot clear streams unless you have manage_messages permissions"
            return await interaction.client.error(interaction, err)

        interaction.client.streams[interaction.guild.id] = []
        await interaction.client.reply(interaction, content=f"{interaction.guild.name} stream list cleared.")

    @app_commands.command()
    @app_commands.auto_complete(stream=streams)
    async def delete(self, interaction: Interaction, stream: str):
        """Delete a stream from the stream list"""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be used in DMs")

        guild_streams = interaction.client.streams[interaction.guild.id]
        matches = [i for i in guild_streams if stream.lower() in i.name.lower() + i.link.lower()]
        if not matches:
            err = f"Couldn't find that stream in {interaction.guild.name} stream list."
            return await interaction.client.error(interaction, err)

        if not interaction.permissions.manage_messages:
            matches = [i for i in matches if i.added_by == interaction.user]
            if not matches:
                err = "You cannot remove a stream you did not add unless you have manage_messages permissions"
                return await interaction.client.error(interaction, err)

        s = interaction.client.streams[interaction.guild.id]
        interaction.client.streams[interaction.guild.id] = [i for i in s if i not in matches]

        msg = "Removed " + "\n".join([f"<{i.link}>" for i in matches]) + f" from {interaction.guild.name} stream list"
        e = Embed(title=f"{interaction.guild.name} Streams", description="\n".join([str(i) for i in guild_streams]))
        await interaction.client.reply(interaction, content=msg, embed=e)


class GuildStreams(commands.Cog):
    """Guild specific stream listings."""

    def __init__(self, bot):
        self.bot = bot
        if not hasattr(self.bot, "streams"):
            self.bot.streams = defaultdict(list)
        self.bot.tree.add_command(Streams)


def setup(bot):
    """Load the streams cog into the bot"""
    bot.add_cog(GuildStreams(bot))
