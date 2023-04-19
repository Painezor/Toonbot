"""Ship Objects and associated classes"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp
from pydantic import (  # pylint: disable=no-name-in-module
    BaseModel,
    ValidationError,
)

from ext.wows_api.modules import Module

from .enums import Nation
from .shipparameters import ShipProfile
from .wg_id import WG_ID


logger = logging.getLogger("api.ship")


INFO = "https://api.worldofwarships.eu/wows/encyclopedia/info/"
SHIP_PROFILE = "https://api.worldofwarships.eu/wows/encyclopedia/shipprofile/"
SHIPS = "https://api.worldofwarships.eu/wows/encyclopedia/ships/"


async def get_ships() -> list[Ship]:
    """Cache the ships from the API."""
    _ = {"application_id": WG_ID, "language": "en"}
    params: dict[str, Any] = _

    async with aiohttp.ClientSession() as session:
        async with session.get(INFO, params=params) as resp:
            if resp.status != 200:
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, INFO)
            data = await resp.json()

        ship_types: list[ShipType] = []
        for i in data["data"]["ship_types"].values():
            images: dict[str, Any] = data["data"]["ship_type_images"][i]
            images.update({"name": i})
            ship_types.append(ShipType(**images))

        params.update({"page_no": 1})
        ships: list[Ship] = []

        async def get_page(count: int, session: aiohttp.ClientSession) -> int:
            params.update({"page_no": count})
            async with session.get(SHIPS, params=params) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
                items = await resp.json()

            meta: dict[str, int] = items.pop("meta")

            for data in items["data"].values():
                # Get from Resolved Ship Types.
                _type = data["type"]
                data["type"] = next(i for i in ship_types if i.name == _type)

                try:
                    ship = Ship(**data)
                except ValidationError as err:
                    logger.error(err)
                    continue

                ships.append(ship)
            return meta["page_total"]

        max_iter = await get_page(1, session)
        # Fetch all remaiing pages simultaneously
        await asyncio.gather(
            *[get_page(i, session) for i in range(2, max_iter + 1)]
        )

    for i in ships:
        for id_, cost in i.next_ships.items():
            try:
                nxt = next(k for k in ships if k.ship_id == id_)
            except StopIteration:
                continue
            i.next_ship_objects.append((nxt, cost))

        i.previous_ships = [j for j in ships if i.ship_id in j.next_ships]

    return ships


class ShipType(BaseModel):
    """
    name: Submarine, Destroyer, Cruiser, Battleship, Aircraft Carrier.
    image: Tech tree images
    image_elite: Tech Tree Fully Researched Images
    image_premium: Premium ship images.
    """

    name: str
    image: str
    image_elite: str
    image_premium: str


class ShipImages(BaseModel):
    """A List of images representing the ship
    contour: str  #  URL to 186 x 48 px outline image of ship
    large: str  #  URL to 870 x 512 px image of ship
    medium: str  # 	URL to 435 x 256 px image of ship
    small: str #  URL to 214 x 126 px image of ship
    """

    contour: str
    large: str
    medium: str
    small: str


class CompatibleModules(BaseModel):
    """Lists of modules of specific types available to a ship"""

    artillery: list[int]
    dive_bomber: list[int]
    engine: list[int]
    fighter: list[int]
    fire_control: list[int]
    flight_control: list[int]
    hull: list[int]
    torpedo_bomber: list[int]
    torpedoes: list[int]

    @property
    def all(self) -> list[int]:
        """Get all populated fields"""
        vals: list[list[int]] = list(self.dict().values())
        return [item for i in vals for item in i]


class TreeModule(BaseModel):
    """Meta information about the location of this module in the module tree"""

    is_default: bool
    module_id: int
    module_id_str: str
    name: str
    price_credit: int
    price_xp: int
    type: str

    next_modules: Optional[list[int]]
    next_ships: Optional[list[int]]


class Ship(BaseModel):
    """A World of Warships Ship."""

    description: str
    has_demo_profile: bool
    is_premium: bool
    is_special: bool
    mod_slots: int
    name: str
    nation: Nation
    next_ships: dict[int, int]  # Ship & XP Cost
    price_credit: int
    price_gold: int
    ship_id: int
    ship_id_str: str
    tier: int
    type: ShipType
    upgrades: list[int]

    default_profile: ShipProfile
    images: ShipImages
    modules: CompatibleModules
    modules_tree: dict[str, TreeModule]

    previous_ships: list[Ship] = []
    next_ship_objects: list[tuple[Ship, int]] = []

    @property
    def emoji(self) -> str:
        """Get an emoji based on the ship's class & premium state"""
        if self.is_premium:
            pass
        if self.is_special:
            pass
        logger.error("missing ship type for %s", self.type.name)
        return ""

    @property
    def ac_row(self) -> str:
        """Autocomplete text"""
        _ = self.type.name
        return f"{self.name} (Tier {self.tier} {self.nation.sane} {_})"


class ShipFit:
    """A Ship Fitting"""

    ship: Ship

    modules: dict[str, Module] = {}

    profile: ShipProfile

    def __init__(self, ship: Ship, initial_modules: list[Module]) -> None:
        self.ship = ship

        for i in initial_modules:
            self.set_module(i)

        self.profile = self.ship.default_profile

    def set_module(self, module: Module) -> None:
        """Set a module into the internal fitting"""
        self.modules[module.type] = module

    async def get_params(self, language: str = "en") -> ShipProfile:
        """Fetch the ship's parameters with the current fitting"""
        params = {"application_id": WG_ID, "language": language}

        convert = {
            "Artillery": "artillery_id",
            "Dive Bomber" "Hull": "dive_bomber_id",
            "Engine": "engine_id",
            "Fighter": "fighter_id",
            "Suo": "fire_control_id",
            "Hull": "hull_id",
            "Torpedo Bomber": "torpedo_bomber_id",
            "Torpedoes": "torpedoes_id",
        }
        for i in self.modules.values():
            try:
                params.update({convert[i.type]: str(i.module_id)})
            except KeyError:
                logger.error("Unable to convert %s to id field", i.type)

        async with aiohttp.ClientSession() as session:
            async with session.get(SHIP_PROFILE, params=params) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
                data = await resp.json()

        self.profile = ShipProfile(**data)
        return self.profile
