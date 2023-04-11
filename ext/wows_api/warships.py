"""Ship Objects and associated classes"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any

import aiohttp
import unidecode

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
        for i in data["data"]["ship_types"].keys():
            images = data["data"]["ship_type_images"][i]
            ship_types.append(ShipType(i, images))

        params.update({"page_no": 1})
        ships: list[Ship] = []

        async def get_page(count: int, session: aiohttp.ClientSession) -> int:
            params.update({"page_no": count})
            async with session.get(SHIPS, params=params) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
                items = await resp.json()

            logger.info("Scanning page %s", count)
            meta = items.pop("meta")

            for data in items["data"].values():
                _type = data.pop("type")
                ship = Ship(data)

                ship.type = next(i for i in ship_types if i.name == _type)

                ships.append(ship)
            return meta["page_total"]

        max_iter = await get_page(1, session)
        logger.info("pagetotal = %s", max_iter)
        # Fetch all remaiing pages simultaneously
        await asyncio.gather(
            *[get_page(i, session) for i in range(2, max_iter + 1)]
        )

    for i in ships:
        i.next_ship_objects = {}
        for k, val in i.next_ships.items():
            try:
                ship = next(i for i in ships if str(i.ship_id) == k)
            except StopIteration:
                logger.error("failed to find ship_id %s", k)
                continue
            i.next_ship_objects.update({ship: val})

        prevs = [j for j in ships if str(i.ship_id) in i.next_ships.keys()]
        i.previous_ship_objects = prevs

    logger.info("%s ships fetched", len(ships))
    return ships


@dataclasses.dataclass(slots=True)
class ShipTypeImages:
    """Images representing the different types of ship in the game"""

    image: str
    image_elite: str
    image_premium: str

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipType:
    """Submarine, Destroyer, Cruiser, Battleship, Aircraft Carrier."""

    name: str
    images: ShipTypeImages

    def __init__(self, name: str, images: dict[str, Any]) -> None:
        self.name = name
        self.images = ShipTypeImages(images)


@dataclasses.dataclass(slots=True)
class ShipImages:
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

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            setattr(self, k, val)


class CompatibleModules:
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

    all_modules: list[int]

    def __init__(self, data: dict[str, Any]) -> None:
        self.all_modules = []
        for k, val in data.items():
            self.all_modules += val
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class TreeModule:
    """Meta information about the location of this module in the module tree"""

    is_default: bool
    module_id: int
    module_id_str: str
    name: str
    price_credit: int
    price_xp: int
    type: str

    next_modules: list[int] = dataclasses.field(default_factory=list)
    next_ships: list[int] = dataclasses.field(default_factory=list)

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class Ship:
    """A World of Warships Ship."""

    description: str
    has_demo_profile: bool
    is_premium: bool
    is_special: bool
    mod_slots: int
    name: str
    nation: Nation
    next_ships: dict[str, int]
    next_ship_objects: dict[Ship, int]
    previous_ship_objects: list[Ship]
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
    modules_tree: list[TreeModule]

    def __hash__(self) -> int:
        return hash(self.ship_id)

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            if k == "modules_tree":
                val = [TreeModule(i) for i in val.values()]
            elif k == "nation":
                val = next(i for i in Nation if i.match == val)
            else:
                try:
                    val = {
                        "default_profile": ShipProfile,
                        "images": ShipImages,
                        "modules": CompatibleModules,
                    }[k](val)
                except KeyError:
                    pass
            setattr(self, k, val)

    @property
    def ac_row(self) -> str:
        """Autocomplete text"""
        # Remove Accents.
        decoded = unidecode.unidecode(self.name)
        return f"{decoded} ({self.tier} {self.nation.alias} {self.type.name})"


class ShipFit:
    """A Ship Fitting"""

    ship: Ship

    artillery: Module
    dive_bomber: Module
    engine: Module
    fighter: Module
    fire_control: Module
    flight_control: Module
    hull: Module
    torpedo_bomber: Module
    torpedoes: Module

    profile: ShipProfile

    def __init__(self, ship: Ship, initial_modules: list[Module]) -> None:
        self.ship = ship

        for i in initial_modules:
            self.set_module(i)

        self.profile = self.ship.default_profile

    def set_module(self, module: Module) -> None:
        """Set a module into the internal fitting"""
        logger.info('Recieved module type "%s" in set_module', module.type)
        return
        attr = {"": ""}[module.type]
        setattr(self, attr, module.module_id)

    @property
    def all_modules(self) -> list[int]:
        """Get a list of all stored values"""
        output: list[int] = []
        for i in dir(self):
            if i.startswith("__"):
                continue

            if callable(getattr(self, i)):
                continue

            output.append(getattr(self, i))
        return output

    async def get_params(self, language: str = "en") -> ShipProfile:
        """Fetch the ship's parameters with the current fitting"""
        params = {"application_id": WG_ID, "language": language}

        for i in dir(self):
            if i.startswith("__"):
                continue

            if callable(getattr(self, i)):
                continue

            params.update({i: getattr(self, i)})

        session = aiohttp.ClientSession()
        async with session.get(SHIP_PROFILE, params=params) as resp:
            if resp.status != 200:
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, resp.url)
            data = await resp.json()

        self.profile = ShipProfile(data)
        return self.profile
