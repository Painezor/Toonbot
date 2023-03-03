from __future__ import annotations

import typing

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from painezBot import PBot


API_PATH = "https://api.worldofwarships.eu/wows/"
MAPS = API_PATH + "encyclopedia/battlearenas/"


class Map:
    """A Generic container class representing a map"""

    def __init__(self, name: str, desc: str, map_id: int, icon: str) -> None:
        self.name: str = name
        self.description: str = desc
        self.battle_arena_id = map_id
        self.icon: str = icon

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    @property
    def ac_row(self) -> str:
        """Autocomplete row for this map"""
        return f"{self.name}: {self.description}"

    @property
    def ac_match(self) -> str:
        """Autocomplete match for this map"""
        return f"{self.name}: {self.description} {self.icon}".casefold()

    @property
    def embed(self) -> discord.Embed:
        """Return an embed representing this map"""
        e = discord.Embed(title=self.name, colour=discord.Colour.greyple())
        e.set_image(url=self.icon)
        e.set_footer(text=self.description)
        return e


async def fetch_maps(bot: PBot) -> list[Map]:
    p = {"application_id": bot.wg_id, "language": "en"}
    async with bot.session.get(MAPS, params=p) as resp:
        if resp.status != 200:
            raise ConnectionError(f"{resp.status} Error accessing {MAPS}")
        items = await resp.json()

    maps = []

    for k, v in items["data"].items():
        maps.append(Map(v["name"], v["description"], k, v["icon"]))

    return maps


async def map_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[int]]:
    """Autocomplete for the list of maps in World of Warships"""
    cur = current.casefold()

    choices = []
    for i in sorted(interaction.client.maps, key=lambda map_: map_.name):
        if cur not in i.ac_match:
            continue

        value = i.battle_arena_id
        choice = discord.app_commands.Choice(name=i.ac_row[:100], value=value)
        choices.append(choice)

        if len(choices) == 25:
            break

    return choices


class Maps(commands.Cog):
    def __init__(self, bot: PBot) -> None:
        self.bot = bot

    async def cog_load(self) -> list[Map]:
        self.bot.maps = await fetch_maps(self.bot)
        return self.bot.maps

    @discord.app_commands.command()
    @discord.app_commands.autocomplete(name=map_ac)
    @discord.app_commands.describe(name="Search for a map by name")
    async def map(
        self, interaction: discord.Interaction[PBot], name: str
    ) -> discord.InteractionMessage:
        """Fetch a map from the world of warships API"""

        await interaction.response.defer(thinking=True)

        if not self.bot.maps:
            raise ConnectionError("Unable to fetch maps from API")

        try:
            map_ = next(i for i in self.bot.maps if i.battle_arena_id == name)
        except StopIteration:
            err = f"Did not find map matching {name}, sorry."
            return await self.bot.error(interaction, err)

        return await interaction.edit_original_response(embed=map_.embed)


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Maps(bot))
