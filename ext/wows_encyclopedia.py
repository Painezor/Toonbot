"""Module for working with the encyclopedia endpoint of the wows API"""
from __future__ import annotations

import logging
import typing

import discord
from discord.ext import commands

import ext.wows_api as api

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]

# TODO: CommanderXP Command (Show Total Commander XP per Rank)


logger = logging.getLogger("wows_encyclopedia")


class Encyclopedia(commands.Cog):
    """World of Warships API Fetching"""

    def __init__(self, bot: PBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.modes = await api.get_game_modes()

    @discord.app_commands.command(name="map")
    @discord.app_commands.describe(obj="Search for a map by name")
    @discord.app_commands.rename(obj="name")
    async def map_info(
        self,
        interaction: Interaction,
        obj: api.transformers.map_transform,
    ) -> discord.InteractionMessage:
        """Fetch a map from the world of warships API"""
        await interaction.response.defer(thinking=True)

        embed = discord.Embed(title=obj.name, colour=discord.Colour.greyple())
        embed.set_image(url=obj.icon)
        embed.set_footer(text=obj.description)
        return await interaction.edit_original_response(embed=embed)


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Encyclopedia(bot))
