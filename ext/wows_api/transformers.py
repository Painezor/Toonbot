"""Discord transformers for various API entities"""
from __future__ import annotations

import logging
from typing import TypeAlias, TYPE_CHECKING

import aiohttp
from discord import Locale, Interaction as Itr
from discord.app_commands import Choice, Transform, Transformer
from pydantic import ValidationError

from .wg_id import WG_ID
from .clan import PartialClan
from .enums import Map, Region
from .gamemode import GameMode
from .player import PartialPlayer, PlayerClanData
from .warships import Ship, ShipType

if TYPE_CHECKING:
    from painezbot import PBot

    Interaction: TypeAlias = Itr[PBot]


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
            Locale.czech: "cs",
            Locale.german: "de",
            Locale.spain_spanish: "es",
            Locale.french: "fr",
            Locale.japanese: "ja",
            Locale.polish: "pl",
            Locale.russian: "ru",
            Locale.thai: "th",
            Locale.taiwan_chinese: "zh-tw",
            Locale.turkish: "tr",
            Locale.chinese: "zh-cn",
            Locale.brazil_portuguese: "pt-br",
        }[interaction.locale]
    except KeyError:
        language = "en"
    return language


class ClanTransformer(Transformer):
    """Convert User Input to a Clan Object"""

    clans: list[PartialClan] = []

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[Choice[str]]:
        """Autocomplete for a list of clan names"""
        if len(value) < 2:
            txt = "🚫 Search too short"
            return [Choice(name=txt, value="0")]

        rgn = interaction.namespace.region
        region = next((i for i in Region if i.domain == rgn), Region.EU)
        link = CLAN_SEARCH.replace("%%", region.domain)
        params = {
            "search": value,
            "limit": 25,
            "application_id": WG_ID,
        }

        async with interaction.client.session.get(link, params=params) as resp:
            if resp.status != 200:
                logger.error("%s on %s", resp.status, link)
            data = await resp.json()

        choices: list[Choice[str]] = []

        self.clans = [PartialClan(**i) for i in data.pop("data", [])]

        for i in self.clans:
            logger.info("%s: %s", i.name, i)
            name = f"[{i.tag}] {i.name}"[:100]
            choices.append(Choice(name=name, value=str(i.clan_id)))
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> PartialClan:
        """Conversion"""
        return next(i for i in self.clans if int(value) == i.clan_id)


class ClassTransformer(Transformer):
    """Convert User input to API ShipType"""

    async def autocomplete(  # type: ignore
        self,
        interaction: Interaction,
        current: str,
        /,
    ) -> list[Choice[str]]:
        """Autocomplete from list of classes of current ships"""
        ships = interaction.client.ships
        types = set(i.type.name.lower() for i in ships)
        cur = current.lower()
        return [Choice(name=i, value=i) for i in types if cur in i]

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str
    ) -> ShipType | None:
        """Get a shiptype"""
        for i in interaction.client.ships:
            if i.type.name == value:
                return i.type


class MapTransformer(Transformer):
    """Convert User Input to a Map Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[Choice[str]]:
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

        choices: list[Choice[str]] = []
        for i in sorted(interaction.client.maps, key=lambda j: j.name):
            if cur not in i.ac_match:
                continue

            name = i.ac_row[:100]
            choices.append(Choice(name=name, value=str(i.battle_arena_id)))

            if len(choices) == 25:
                break

        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Map:
        """Convert"""
        maps = interaction.client.maps
        return next(i for i in maps if i.battle_arena_id == int(value))


class ModeTransformer(Transformer):
    """Convert user input to API Game Mode"""

    async def autocomplete(  # type: ignore
        self,
        interaction: Interaction,
        current: str,
        /,
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored modes"""
        curr = current.casefold()
        choices: list[Choice[str]] = []
        for i in sorted(interaction.client.modes, key=lambda x: x.name):
            if curr not in i.name.casefold():
                continue

            choice = Choice(name=i.name, value=i.name)
            choices.append(choice)
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> GameMode | None:
        """Convert"""
        return next(i for i in interaction.client.modes if i.name == value)


class PlayerTransformer(Transformer):
    """Convert User Input to Player Object"""

    players: list[PartialPlayer] = []

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[Choice[str]]:
        """Fetch player's account ID by searching for their name."""
        if len(value) < 2:
            txt = "🚫 Search too short"
            return [Choice(name=txt, value="0")]

        params = {"application_id": WG_ID, "search": value, "limit": 25}
        _ = interaction.namespace.region
        region = next((i for i in Region if i.value == _), Region.EU)

        link = PLAYER_SEARCH.replace("%%", region.domain)
        async with interaction.client.session.get(link, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

        try:
            self.players = [PartialPlayer(**i) for i in data.pop("data", [])]
        except ValidationError as err:
            print(err)

        logger.info("Generated %s players", len(self.players))

        link = PLAYER_CLAN.replace("%%", region.domain)
        parms = {
            "application_id": WG_ID,
            "account_id": ", ".join([str(i.account_id) for i in self.players]),
            "extra": "clan",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(link, params=parms) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, link)
                clan_raw = await resp.json()
                clan_data = clan_raw.pop("data")

        logger.info("got %s clan_data items", len(clan_data))
        choices: list[Choice[str]] = []
        for k, val in clan_data.items():
            # k is the player's id
            try:
                plr = next(i for i in self.players if i.account_id == int(k))
            except StopIteration:
                plrs = ", ".join([str(p.account_id) for p in self.players])
                logger.info("Failed to map %s to %s", k, plrs)
                continue

            if val:
                plr.clan = PlayerClanData(**val)
                name = f"[{plr.clan.tag}] {plr.nickname}"
            else:
                plr.clan = None
                name = plr.nickname
            choices.append(Choice(name=name, value=str(plr.account_id)))
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> PartialPlayer:
        """Conversion"""
        return next(i for i in self.players if str(i.account_id) == value)


class ShipTransformer(Transformer):
    """Convert User Input to a ship Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete for the list of maps in World of Warships"""

        current = current.casefold()
        choices: list[Choice[str]] = []
        for i in sorted(interaction.client.ships, key=lambda i: i.name):
            if not i.ship_id_str:
                continue

            if current not in i.name.casefold():
                continue

            value = i.ship_id_str
            name = i.ac_row[:100]
            choices.append(Choice(name=name, value=value))

            if len(choices) == 25:
                break

        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Ship:
        """Retrieve the ship object for the selected autocomplete"""
        ships = interaction.client.ships
        return next(i for i in ships if i.ship_id_str == value)


class RegionTransformer(Transformer):
    """Convert User Input to Region Object"""

    async def autocomplete(  # type: ignore
        self, _: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Return api.Region stuff"""
        opts = [Choice(name=i.name, value=i.domain) for i in Region]
        return [i for i in opts if current.casefold() in i.name.casefold()]

    async def transform(  # type: ignore
        self, _: Interaction, value: str, /
    ) -> Region:
        """Retrieve the ship object for the selected autocomplete"""
        return next(i for i in Region if i.domain == value)


clan_transform: TypeAlias = Transform[PartialClan, ClanTransformer]
class_transform: TypeAlias = Transform[ShipType, ClassTransformer]
map_transform: TypeAlias = Transform[Map, MapTransformer]
mode_transform: TypeAlias = Transform[GameMode, ModeTransformer]
player_transform: TypeAlias = Transform[PartialPlayer, PlayerTransformer]
region_transform: TypeAlias = Transform[Region, RegionTransformer]
ship_transform: TypeAlias = Transform[Ship, ShipTransformer]
