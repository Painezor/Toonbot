"""Discord transformers for various API entities"""
import logging
import typing

import aiohttp
import discord

from .wg_id import WG_ID
from .clan import Clan
from .enums import Map, Region
from .gamemode import GameMode
from .player import Player, PlayerClanData
from .warships import Ship

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]


CLAN_SEARCH = "https://api.worldofwarships.%%/wows/clans/list/"
PLAYER_SEARCH = "https://api.worldofwarships.%%/wows/account/list/"
PLAYER_CLAN = "https://api.worldofwarships.%%/wows/clans/accountinfo/"
MAPS = "https://api.worldofwarships.eu/wows/encyclopedia/battlearenas/"

logger = logging.getLogger("api.transformers")


__all__ = [
    "clan_transform",
    "map_transform",
    "mode_transform",
    "player_transform",
    "ship_transform",
]


class ClanTransformer(discord.app_commands.Transformer):
    """Convert User Input to a Clan Object"""

    async def autocomplete(
        self, interaction: Interaction, value: str, /
    ) -> list[discord.app_commands.Choice[int]]:
        """Autocomplete for a list of clan names"""
        region = getattr(interaction.namespace, "region", None)
        rgn = next((i for i in Region if i.db_key == region), Region.EU)

        link = CLAN_SEARCH.replace("%%", rgn.domain)
        params = {
            "search": value,
            "limit": 25,
            "application_id": WG_ID,
        }

        async with interaction.client.session.get(link, params=params) as resp:
            if resp.status != 200:
                logger.error("%s on %s", resp.status, link)
                return []

            clans = await resp.json()

        choices = []
        interaction.extras["clans"] = []
        for i in clans.pop("data", []):
            clan = Clan(i)

            name = f"[{clan.tag}] {clan.name}"
            choice = discord.app_commands.Choice(name=name, value=clan.clan_id)
            choices.append(choice)
        return choices

    async def transform(self, interaction: Interaction, value: int, /) -> Clan:
        """Conversion"""
        clans: list[Clan] = interaction.extras["clans"]
        return next(i for i in clans if value == i.clan_id)


class MapTransformer(discord.app_commands.Transformer):
    """Convert User Input to a Map Object"""

    async def autocomplete(
        self, interaction: Interaction, value: str, /
    ) -> list[discord.app_commands.Choice[int]]:
        """Autocomplete for the list of maps in World of Warships"""
        cur = value.casefold()

        if not interaction.client.maps:
            params = {"application_id": WG_ID, "language": "en"}
            session = interaction.client.session
            async with session.get(MAPS, params=params) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, MAPS)
                    return []
                items = await resp.json()

            for k, val in items["data"].items():
                interaction.client.maps.update({k: Map(val)})

        choices = []
        for i in sorted(interaction.client.maps, key=lambda j: j.name):
            if cur not in i.ac_match:
                continue

            name = i.ac_row[:100]
            val = i.battle_arena_id
            choice = discord.app_commands.Choice(name=name, value=val)
            choices.append(choice)

            if len(choices) == 25:
                break

        return choices

    async def transform(self, interaction: Interaction, value: int, /) -> Map:
        """Convert"""
        maps = interaction.client.maps
        return next(i for i in maps if i.battle_arena_id == value)


class ModeTransformer(discord.app_commands.Transformer):
    """Convert user input to API Game Mode"""

    async def autocomplete(
        self,
        interaction: Interaction,
        current: str,
        /,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        modes = interaction.client.modes
        modes = sorted(modes, key=lambda x: x.name)

        curr = current.casefold()

        choices = []
        for i in modes:
            if curr not in i.name.casefold():
                continue

            choice = discord.app_commands.Choice(name=i.name, value=i.name)
            choices.append(choice)
        return choices

    async def transform(
        self, interaction: discord.Interaction[PBot], value: str, /
    ) -> typing.Optional[GameMode]:
        """Convert"""
        return next(i for i in interaction.client.modes if i.name == value)


class PlayerTransformer(discord.app_commands.Transformer):
    """Conver User Input to Player Object"""

    async def autocomplete(
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[int]]:
        """Fetch player's account ID by searching for their name."""
        if len(current) < 3:
            return []

        params = {"application_id": WG_ID, "search": current, "limit": 25}

        region = getattr(interaction.namespace, "region", None)
        region = next((i for i in Region if i.db_key == region), Region.EU)

        link = PLAYER_SEARCH.replace("%%", region.domain)
        async with interaction.client.session.get(link, params=params) as resp:
            if resp.status != 200:
                logger.error("%s on %s: %s", resp.status, link, resp.reason)
            clan_data = await resp.json()

        players = clan_data.pop("data", None)
        logger.info("remaining data %s", clan_data)

        link = PLAYER_CLAN.replace("%%", region.domain)
        parms = {
            "application_id": WG_ID,
            "account_id": ", ".join([i.account_id for i in players]),
            "extra": "clan",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(link, params=parms) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, link)
                clan_raw = await resp.json()
                clan_data = clan_raw.pop("data")

        cln = [PlayerClanData(i) for i in clan_data]

        choices = []
        for i in (players := [Player(i) for i in players][:25]):

            try:
                plr = next(j for j in cln if i.account_id == i.account_id)
                name = f"[{plr.clan.tag}] {plr.account_name}"
            except StopIteration:
                name = i.nickname

            value = i.account_id
            choices.append(discord.app_commands.Choice(name=name, value=value))

        interaction.extras["players"] = players
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[Player]:
        """Conversion"""
        players: list[Player] = interaction.extras["players"]
        return next(i for i in players if i.account_id == value)


class ShipTransformer(discord.app_commands.Transformer):
    """Convert User Input to a ship Object"""

    async def autocomplete(
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the list of maps in World of Warships"""

        current = current.casefold()
        choices = []
        for i in sorted(interaction.client.ships, key=lambda s: s.name):
            if not i.ship_id_str:
                continue
            if current not in i.ac_row:
                continue

            value = i.ship_id_str
            name = i.ac_row[:100]
            choices.append(discord.app_commands.Choice(name=name, value=value))

            if len(choices) == 25:
                break

        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[Ship]:
        """Convert"""
        return interaction.client.get_ship(value)


_ = discord.app_commands.Transform[Clan, ClanTransformer]
clan_transform: typing.TypeAlias = _

_ = discord.app_commands.Transform[Map, MapTransformer]
map_transform: typing.TypeAlias = _

_ = discord.app_commands.Transform[GameMode, ModeTransformer]
mode_transform: typing.TypeAlias = _

_ = discord.app_commands.Transform[Player, PlayerTransformer]
player_transform: typing.TypeAlias = _

_ = discord.app_commands.Transform[Ship, ShipTransformer]
ship_transform: typing.TypeAlias = _
