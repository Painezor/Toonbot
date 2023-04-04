"""Ship Objects and associated classes"""
from __future__ import annotations

import dataclasses
import logging
import typing

import aiohttp
import unidecode

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
    params: dict[str, typing.Any] = _

    session = aiohttp.ClientSession()

    async with session.get(INFO, params=params) as resp:
        if resp.status != 200:
            logger.error("%s %s: %s", resp.status, resp.reason, INFO)
        data = await resp.json()

    ship_types: list[ShipType] = []
    for k, values in data["data"]["ship_types"].items():
        images = data["data"]["ship_type_images"][k]
        ship_types.append(ShipType(k, values, images))

    params.update({"page_no": 1})
    max_iter = 1
    ships: list[Ship] = []
    while (count := 1) <= max_iter:
        # Initial Pull.
        params.update({"page_no": count})
        async with session.get(SHIPS, params=params) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, SHIPS)
            items = await resp.json()
            count += 1

        max_iter = items["meta"]["page_total"]

        for data in items["data"].values():
            nation = data.pop("nation")
            _ = data.pop("type")
            _type = next(i for i in ship_types if i.alias == _)
            ship = Ship(data)

            ship.nation = Nation[nation]
            ship.type = _type

            ships.append(ship)
    logger.info("%s ships fetched", len(ships))
    return ships


@dataclasses.dataclass
class ShipTypeImages:
    """Images representing the different types of ship in the game"""

    image: str
    image_elite: str
    image_premium: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class ShipType:
    """Submarine, Destroyer, Cruiser, Battleship, Aircraft Carrier."""

    match: str
    alias: str
    images: ShipTypeImages

    def __init__(self, match: str, alias: str, images: dict) -> None:

        self.match = match
        self.alias = alias

        self.images = ShipTypeImages(images)


@dataclasses.dataclass
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

    def __init__(self, data: dict) -> None:
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

    def __init__(self, data: dict) -> None:
        self.all_modules = []
        for k, val in data.items():
            self.all_modules += val
            setattr(self, k, val)


class TreeModule:
    """Meta information about the location of this module in the module tree"""

    is_default: bool
    module_id: int
    module_id_str: str
    name: str
    next_modules: typing.Optional[list[int]]
    next_ships: typing.Optional[list[int]]
    price_credit: int
    price_xp: int
    type: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class Ship:
    """A World of Warships Ship."""

    description: str
    has_demo_profile: bool
    is_premium: bool
    is_special: bool
    mod_slots: int
    name: str
    nation: Nation
    next_ships: list
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
    module_tree: list[TreeModule]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "module_tree":
                self.module_tree = [TreeModule(i) for i in val.values()]
            elif k == "nation":
                val = next(i for i in Nation if i.alias == val)
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
        nation = "Unknown nation" if self.nation is None else self.nation.alias
        # Remove Accents.
        decoded = unidecode.unidecode(self.name)
        return f"{self.tier}: {decoded} {nation} {self.type.alias}".casefold()


class ShipFit:
    """A Ship Fitting"""

    ship_id: int
    artillery_id: int
    dive_bomber_id: int
    engine_id: int
    fighter_id: int
    fire_control_id: int
    flight_control_id: int
    hull_id: int
    torpedo_bombers_id: int
    torpedoes_id: int

    def __init__(self, initial_modules: list[TreeModule]) -> None:
        for i in initial_modules:
            self.set_module(i)

    def set_module(self, module: TreeModule) -> None:
        """Set a module into the internal fitting"""
        attr = {"": ""}[module.type]
        setattr(self, attr, module.module_id)

    @property
    def all_modules(self) -> list[int]:
        """Get a list of all stored values"""
        output = []
        for i in dir(self):
            if i.startswith("__"):
                continue

            if callable(getattr(self, i)):
                continue

            output.append(getattr(self, i))
        return output

    async def get_params(self, language: str) -> ShipProfile:
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
                logger.error("[%s] %s %s", resp.status, resp.url, resp.reason)
            data = await resp.json()

        return ShipProfile(data)
