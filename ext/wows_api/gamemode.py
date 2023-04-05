"""World of Warships Game Modes"""
from __future__ import annotations

import dataclasses
import logging
import typing

import aiohttp

from .wg_id import WG_ID

logger = logging.getLogger("api.gamemodes")

MODES = "https://api.worldofwarships.eu/wows/encyclopedia/battletypes/"


async def get_game_modes() -> set[GameMode]:
    """Get a list of Game Modes from the API"""
    params = {"application_id": WG_ID, "language": "en"}

    async with aiohttp.ClientSession() as session:
        async with session.get(MODES, params=params) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, MODES)
            data = await resp.json()

    logger.info(data)
    modes: set[GameMode] = set()
    for i in data["data"].values():

        modes.add(GameMode(i))

    return modes


@dataclasses.dataclass
class GameMode:
    """ "An Object representing different Game Modes"""

    description: str
    image: str
    name: str
    tag: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)

    @property
    def emoji(self) -> typing.Optional[str]:
        """Get the Emoji Representation of the game mode."""
        return {
            "BRAWL": "<:Brawl:989921560901058590>",
            "CLAN": "<:Clan:989921285918294027>",
            "COOPERATIVE": "<:Coop:989844738800746516>",
            "EVENT": "<:Event:989921682007420938>",
            "PVE": "<:Scenario:989921800920109077>",
            "PVE_PREMADE": "<:Scenario_Hard:989922089303687230>",
            "PVP": "<:Randoms:988865875824222338>",
            "RANKED": "<:Ranked:989845163989950475>",
        }.get(self.tag, None)