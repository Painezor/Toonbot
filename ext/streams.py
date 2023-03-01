"""Allow guilds to add a list of their own streams to keep track of events."""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import Embed, Permissions, Member, Interaction, Message, User
from discord.app_commands import Choice, Group
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from core import Bot


class Stream:
    """A generic dataclass representing a stream"""

    def __init__(self, name: str, link: str, added_by: Member | User) -> None:
        self.name: str = name
        self.link: str = link
        self.added_by: Member | User = added_by

    def __str__(self):
        text = self.link if self.name is None else self.name
        return f"[{text}]({self.link}) added by {self.added_by.mention}"

    @property
    def ac_row(self) -> str:
        return f"{self.name} {self.link}".casefold()


async def st_ac(ctx: Interaction[Bot], current: str) -> list[Choice[str]]:
    """Return List of Guild Streams"""
    if ctx.guild is None:
        return []

    strms = ctx.client.streams[ctx.guild.id]
    cur = current.casefold()
    m = [i.name[:100] for i in strms if cur in i.ac_row]
    return [Choice(name=item, value=item) for item in m][:25]


class GuildStreams(Cog):
    """Guild specific stream listings."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    prm = Permissions(manage_messages=True)
    streams = Group(
        name="streams",
        description="Stream list for your server",
        guild_only=True,
        default_permissions=prm,
    )

    @streams.command()
    async def list(self, interaction: Interaction) -> Message:
        """List all streams for the match added by users."""
        if interaction.guild is None:
            raise

        if not (strms := self.bot.streams[interaction.guild.id]):
            err = "Nobody has added any streams yet."
            return await self.bot.error(interaction, err)

        e = Embed(title="Streams")
        e.description = "\n".join([str(i) for i in strms])
        return await self.bot.reply(interaction, embed=e)

    @streams.command(name="add")
    @discord.app_commands.describe(name="Stream Name", link="Stream Link")
    async def add_stream(self, ctx: Interaction[Bot], link: str, name: str):
        """Add a stream to the stream list."""
        if ctx.guild is None:
            raise

        if not (guild_streams := self.bot.streams[ctx.guild.id]):
            self.bot.streams[ctx.guild.id] = []

        if link in [i.link for i in guild_streams]:
            return await self.bot.error(ctx, "Already in stream list.")

        stream = Stream(name=name, link=link, added_by=ctx.user)
        self.bot.streams[ctx.guild.id].append(stream)

        e: Embed = Embed(title="Streams")
        e.description = "\n".join([str(i) for i in guild_streams])

        msg = f"Added <{stream.link}> to stream list."
        await self.bot.reply(ctx, msg, embed=e)

    @streams.command(name="clear")
    async def clear_streams(self, interaction: Interaction):
        """Remove all streams from guild stream list"""
        if interaction.guild is None:
            raise

        self.bot.streams[interaction.guild.id] = []
        msg = f"{interaction.guild.name} stream list cleared."
        await self.bot.reply(interaction, msg)

    @streams.command(name="delete")
    @discord.app_commands.autocomplete(stream=st_ac)
    async def delete_stream(self, interaction: Interaction[Bot], stream: str):
        """Delete a stream from the stream list"""
        await interaction.response.defer(thinking=True)

        if interaction.guild is None:
            raise

        gs = interaction.client.streams[interaction.guild.id]

        lk = stream.casefold()

        matches = [i for i in gs if lk in f"{i.name} {i.link}".casefold()]

        if not matches:
            err = f"{stream} not in {interaction.guild.name} stream list."
            return await self.bot.error(interaction, err)

        if interaction.channel is None:
            raise

        p = interaction.channel.permissions_for(interaction.guild.me)
        if not p.manage_messages:
            u = interaction.user
            if not (matches := [i for i in matches if i.added_by == u]):
                err = "You did not add that stream and you are not a mod."
                return await self.bot.error(interaction, err)

        s = self.bot.streams.get(interaction.guild.id, {})

        new = [i for i in s if i not in matches]
        self.bot.streams[interaction.guild.id] = new

        txt = "\n".join([f"<{i.link}>" for i in matches])
        msg = f"Removed {txt} from {interaction.guild.name} stream list"

        e = Embed(title=f"{interaction.guild.name} Streams")
        e.description = "\n".join([str(i) for i in gs])
        await self.bot.reply(interaction, msg, embed=e)


async def setup(bot: Bot) -> None:
    """Load the streams cog into the bot"""
    await bot.add_cog(GuildStreams(bot))
