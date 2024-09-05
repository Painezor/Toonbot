"""Fetching Maps from the WoWs API"""
import aiohttp
import logging

from pydantic import BaseModel

from .wg_id import WG_ID


logger = logging.getLogger("wows_api.maps")

MAPS = "https://api.worldofwarships.eu/wows/encyclopedia/battlearenas/"


class Map(BaseModel):
    """A Generic container class representing a map"""

    battle_arena_id: int
    description: str
    icon: str
    name: str

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


async def get_maps() -> list[Map]:
    params = {"application_id": WG_ID, "language": "en"}
    async with aiohttp.ClientSession().get(MAPS, params=params) as resp:
        if resp.status != 200:
            logger.error("%s on %s", resp.status, MAPS)
            return []
        items = await resp.json()

    out: list[Map] = []
    for val in items["data"].values():
        out.append(Map(**val))
    return out
