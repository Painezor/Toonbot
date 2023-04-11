"""Discord transformers for various API entities"""
from __future__ import annotations

import logging
import typing

import aiohttp
import discord

from .wg_id import WG_ID
from .clan import PartialClan
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


def get_locale(interaction: Interaction) -> str:
    """Convert an interaction's locale into API language field"""
    try:
        language = {
            discord.Locale.czech: "cs",
            discord.Locale.german: "de",
            discord.Locale.spain_spanish: "es",
            discord.Locale.french: "fr",
            discord.Locale.japanese: "ja",
            discord.Locale.polish: "pl",
            discord.Locale.russian: "ru",
            discord.Locale.thai: "th",
            discord.Locale.taiwan_chinese: "zh-tw",
            discord.Locale.turkish: "tr",
            discord.Locale.chinese: "zh-cn",
            discord.Locale.brazil_portuguese: "pt-br",
        }[interaction.locale]
    except KeyError:
        language = "en"
    return language


class ClanTransformer(discord.app_commands.Transformer):
    """Convert User Input to a Clan Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for a list of clan names"""
        if len(value) < 2:
            txt = "🚫 Search too short"
            return [discord.app_commands.Choice(name=txt, value="0")]

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

        choices: list[discord.app_commands.Choice[str]] = []
        clans = [PartialClan(i) for i in clans.pop("data", [])]
        interaction.extras["clans"] = clans
        for i in clans:
            name = f"[{i.tag}] {i.name}"
            val = str(i.clan_id)
            choice = discord.app_commands.Choice(name=name, value=val)
            choices.append(choice)
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> PartialClan:
        """Conversion"""
        clans: list[PartialClan] = interaction.extras["clans"]
        return next(i for i in clans if int(value) == i.clan_id)


class MapTransformer(discord.app_commands.Transformer):
    """Convert User Input to a Map Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[discord.app_commands.Choice[str]]:
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

        choices: list[discord.app_commands.Choice[str]] = []
        for i in sorted(interaction.client.maps, key=lambda j: j.name):
            if cur not in i.ac_match:
                continue

            name = i.ac_row[:100]
            val = str(i.battle_arena_id)
            choice = discord.app_commands.Choice(name=name, value=val)
            choices.append(choice)

            if len(choices) == 25:
                break

        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Map:
        """Convert"""
        maps = interaction.client.maps
        return next(i for i in maps if i.battle_arena_id == int(value))


class ModeTransformer(discord.app_commands.Transformer):
    """Convert user input to API Game Mode"""

    async def autocomplete(  # type: ignore
        self,
        interaction: Interaction,
        current: str,
        /,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        curr = current.casefold()
        choices: list[discord.app_commands.Choice[str]] = []
        for i in sorted(interaction.client.modes, key=lambda x: x.name):
            if curr not in i.name.casefold():
                continue

            choice = discord.app_commands.Choice(name=i.name, value=i.name)
            choices.append(choice)
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[GameMode]:
        """Convert"""
        return next(i for i in interaction.client.modes if i.name == value)


class PlayerTransformer(discord.app_commands.Transformer):
    """Convert User Input to Player Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Fetch player's account ID by searching for their name."""
        if len(value) < 2:
            txt = "🚫 Search too short"
            return [discord.app_commands.Choice(name=txt, value="0")]

        params = {"application_id": WG_ID, "search": value, "limit": 25}
        region = getattr(interaction.namespace, "region", None)
        region = next((i for i in Region if i.db_key == region), Region.EU)

        logger.info("Fetching players")
        link = PLAYER_SEARCH.replace("%%", region.domain)
        async with interaction.client.session.get(link, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

        players = [Player(i) for i in data.pop("data", [])]
        logger.info("Generated %s players", len(players))

        link = PLAYER_CLAN.replace("%%", region.domain)
        parms = {
            "application_id": WG_ID,
            "account_id": ", ".join([str(i.account_id) for i in players]),
            "extra": "clan",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(link, params=parms) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, link)
                clan_raw = await resp.json()
                clan_data = clan_raw.pop("data")

        logger.info("Clan data results %s", clan_data)

        for k, val in clan_data.items():
            # k is the player's id
            player = next(i for i in players if i.account_id == int(k))
            player.clan = PlayerClanData(val)

        choices: list[discord.app_commands.Choice[str]] = []
        for i in players[:25]:
            if i.clan is not None:
                name = f"[{i.clan.tag}] {i.nickname}"
            else:
                name = i.nickname

            value = str(i.account_id)
            choices.append(discord.app_commands.Choice(name=name, value=value))

        interaction.extras["players"] = players
        logger.info("Made %s choices", len(choices))
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Player:
        """Conversion"""
        players: list[Player] = interaction.extras["players"]
        return next(i for i in players if i.account_id == int(value))


class ShipTransformer(discord.app_commands.Transformer):
    """Convert User Input to a ship Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete for the list of maps in World of Warships"""

        current = current.casefold()
        choices: list[discord.app_commands.Choice[str]] = []
        for i in sorted(interaction.client.ships, key=lambda i: i.name):
            if not i.ship_id_str:
                continue

            if current not in i.name.casefold():
                continue

            value = i.ship_id_str
            name = i.ac_row[:100]
            choices.append(discord.app_commands.Choice(name=name, value=value))

            if len(choices) == 25:
                break

        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Ship:
        """Retrieve the ship object for the selected autocomplete"""
        ships = interaction.client.ships
        return next(i for i in ships if i.ship_id_str == value)


clan_transform: typing.TypeAlias = discord.app_commands.Transform[
    PartialClan, ClanTransformer
]
map_transform: typing.TypeAlias = discord.app_commands.Transform[
    Map, MapTransformer
]
mode_transform: typing.TypeAlias = discord.app_commands.Transform[
    GameMode, ModeTransformer
]
player_transform: typing.TypeAlias = discord.app_commands.Transform[
    Player, PlayerTransformer
]
ship_transform: typing.TypeAlias = discord.app_commands.Transform[
    Ship, ShipTransformer
]
