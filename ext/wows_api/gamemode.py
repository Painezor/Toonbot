"""World of Warships Game Modes"""
from __future__ import annotations

import logging

import aiohttp
from pydantic import BaseModel

from .wg_id import WG_ID

logger = logging.getLogger("api.gamemodes")

MODES = "https://api.worldofwarships.eu/wows/encyclopedia/battletypes/"


async def get_game_modes() -> list[GameMode]:
    """Get a list of Game Modes from the API"""
    params = {"application_id": WG_ID, "language": "en"}

    async with aiohttp.ClientSession() as session:
        async with session.get(MODES, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

    return [GameMode.parse_obj(i) for i in data.pop("data").values()]


class GameMode(BaseModel):
    """ "An Object representing different Game Modes"""

    description: str
    image: str
    name: str
    tag: str

    @property
    def emoji(self) -> str:
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
        }[self.tag]
