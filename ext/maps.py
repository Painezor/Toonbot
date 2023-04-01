from __future__ import annotations

import typing
import logging

import discord
from discord.ext import commands

import ext.utils.wows_api as api

if typing.TYPE_CHECKING:
    from painezBot import PBot


MAPS = "https://api.worldofwarships.eu/wows/encyclopedia/battlearenas/"

logger = logging.getLogger("maps")


class MapTransformer(discord.app_commands.Transformer):
    async def autocomplete(
        self, interaction: discord.Interaction[PBot], current: str
    ) -> list[discord.app_commands.Choice[int]]:
        """Autocomplete for the list of maps in World of Warships"""
        cur = current.casefold()

        if not interaction.client.maps:
            p = {"application_id": api.WG_ID, "language": "en"}
            async with interaction.client.session.get(MAPS, params=p) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, MAPS)
                    return []
                items = await resp.json()

            maps = []

            for k, v in items["data"].items():
                maps.append(api.Map(v["name"], v["description"], k, v["icon"]))
            interaction.client.maps = maps

        choices = []
        for i in sorted(interaction.client.maps, key=lambda map_: map_.name):
            if cur not in i.ac_match:
                continue

            value = i.battle_arena_id
            choice = discord.app_commands.Choice(
                name=i.ac_row[:100], value=value
            )
            choices.append(choice)

            if len(choices) == 25:
                break

        return choices

    async def transform(
        self, interaction: discord.Interaction[PBot], value: int
    ) -> api.Map:
        maps = interaction.client.maps
        return next(i for i in maps if i.battle_arena_id == value)


class Maps(commands.Cog):
    def __init__(self, bot: PBot) -> None:
        self.bot = bot

    @discord.app_commands.command()
    @discord.app_commands.describe(map="Search for a map by name")
    async def map(
        self,
        interaction: discord.Interaction[PBot],
        map: discord.app_commands.Transform[api.Map, MapTransformer],
    ) -> discord.InteractionMessage:
        """Fetch a map from the world of warships API"""
        await interaction.response.defer(thinking=True)
        return await interaction.edit_original_response(embed=map.embed)


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Maps(bot))
