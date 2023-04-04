"""Ship Objects and associated classes"""
from __future__ import annotations

import dataclasses
import logging
import typing

import aiohttp
import unidecode

from .enums import Nation
from .wg_id import WG_ID


logger = logging.getLogger("api.ship")


INFO = "https://api.worldofwarships.eu/wows/encyclopedia/info/"
SHIP_PROFILE = "https://api.worldofwarships.eu/wows/encyclopedia/shipprofile/"
SHIPS = "https://api.worldofwarships.eu/wows/encyclopedia/ships/"


async def cache_ships() -> list[Ship]:
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
class ShipProfile:
    """Information about a ship in a specific configuration (A "Profile")"""

    battle_level_range_max: int
    battle_level_range_min: int

    anti_air: AAProfile
    armour: ArmourProfile
    artillery: ArtilleryProfile
    atbas: SecondaryProfile
    concealment: ConcealmentProfile
    dive_bomber: typing.Optional[DiveBomberProfile]
    engine: EngineProfile
    fighters: typing.Optional[ShipFighterProfile]
    fire_control: FireControlProfile
    flight_control: typing.Optional[ShipFlightControlProfile]
    hull: HullProfile
    mobility: MobilityProfile
    torpedo_bomber: typing.Optional[TorpedoBomberProfile]
    torpedoes: TorpedoProfile
    weaponry: WeaponryProfile

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            try:
                val = {
                    "anti_air": AAProfile,
                    "armour": ArmourProfile,
                    "artillery": ArtilleryProfile,
                    "atbas": SecondaryProfile,
                    "concealment": ConcealmentProfile,
                    "dive_bomber": DiveBomberProfile,
                    "engine": EngineProfile,
                    "fire_control": FireControlProfile,
                    "flight_control": ShipFlightControlProfile,
                    "hull": HullProfile,
                    "mobility": MobilityProfile,
                    "torpedo_bomber": TorpedoBomberProfile,
                    "torpedoes": TorpedoProfile,
                    "weaponry": WeaponryProfile,
                }[k](val)
            except KeyError:
                pass
            setattr(self, k, val)


@dataclasses.dataclass
class AAProfile:
    """Information about a ship profile's Anti Aircraft"""

    defense: int
    slots: list[AAGun]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "slots":
                val = [AAGun(i) for i in val]
            setattr(self, k, val)


@dataclasses.dataclass
class ArmourProfile:
    """Information about a ship profile's Armour"""

    flood_damage: int  # Belt Torpedo Reduction in %
    flood_prob: int  # Belt Flood Chance Reduction in %
    health: int
    total: float  # Damage Reduction %  -- This is dead.

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k in ["casemate", "citadel", "deck", "extremities", "range"]:
                val = ArmourSegment(k, val)
            setattr(self, k, val)


@dataclasses.dataclass
class ArtilleryProfile:
    """Information about a ship profile's Main Battery"""

    artillery_id: int
    artillery_id_str: str
    distance: float  # Firing Range
    gun_rate: float  # Rounds per minute
    max_dispersion: int  # meters
    rotation_time: float  # 180 turn time in seconds
    shot_delay: float  # reload time

    shells: list[Shell]
    slots: list[MainGun]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if val == "shells":
                val = [Shell(i) for i in val]
            elif val == "slots":
                val = [MainGun(i) for i in val]
            setattr(self, k, val)


@dataclasses.dataclass
class SecondaryProfile:
    """Information about a ship profile's Secondary Armaments"""

    distance: float  # range
    slots: list[SecondaryGun]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "slots":
                val = [SecondaryGun(i) for i in val]
            setattr(self, k, val)


@dataclasses.dataclass
class ConcealmentProfile:
    """Information about a ship profile's Concealment"""

    detect_distance_by_plane: float
    detect_distance_by_ship: float
    total: float  # This is a percentage...? Possibly rating.

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class DiveBomberProfile:
    """Information about a ship profile's Dive Bombers"""

    bomb_bullet_mass: int
    bomb_burn_probability: float
    bomb_damage: int
    bomb_name: str
    cruise_speed: int
    dive_bomber_id: int
    dive_bomber_id_str: str
    gunner_damage: int
    max_damage: int
    max_health: int
    name: str
    plane_level: int
    prepare_time: int
    squadrons: int

    accuracy: BomberAccuracy
    count_in_squadron: SquadronSize

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "accuracy":
                val = BomberAccuracy(val)
            elif k == "count_in_squadron":
                val = SquadronSize(val)
            setattr(self, k, val)


@dataclasses.dataclass
class EngineProfile:
    """Information about a ship profile's Engine"""

    engine_id: int
    engine_id_str: str
    max_speed: float  # knots

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class ShipFighterProfile:
    """Information about a ship profile's Fighters"""

    avg_damage: int
    cruise_speed: int
    fighters_id: int
    fighters_id_str: str
    gunner_damage: int
    max_ammo: int
    max_health: int
    name: int
    plane_level: int
    prepare_time: int
    squadrons: int

    count_in_squadron: SquadronSize

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "count_in_squadron":
                val = SquadronSize(val)
            setattr(self, k, val)


@dataclasses.dataclass
class FireControlProfile:
    """Information about a ship profile's Fire Control System"""

    distance: float  # firing range
    distance_increase: int  # range %
    fire_control_id: int
    fire_control_id_str: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class ShipFlightControlProfile:
    """Information about a ship profile's Flight Control System"""

    bomber_squadrons: int
    fighter_squadrons: int
    flight_control_id: int
    flight_control_id_str: str
    torpedo_squadrons: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class HullProfile:
    """Information about a ship profile's Hull"""

    anti_aircraft_barrels: int
    artillery_barrels: int
    atba_barrels: int
    health: int
    hull_id: int
    hull_id_str: str
    planes_amount: int
    torpedoes_barrels: int

    range: HullArmourRange  # Ship Armour

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "range":
                val = HullArmourRange(val)
            setattr(self, k, val)


@dataclasses.dataclass
class MobilityProfile:
    """Information about a ship profile's Mobility"""

    max_speed: float
    rudder_time: float
    total: int  # Manouverability Rating
    turning_radius: int  # meters

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class TorpedoBomberProfile:
    """Information about a ship profile's Torpedo Bombers"""

    cruise_speed: int
    gunner_damage: int
    max_damage: int
    max_health: int
    name: str
    plane_level: int
    prepare_time: int
    squadrons: int
    torpedo_bomber_id: int
    torpedo_bomber_id_str: str
    torpedo_damage: int
    torpedo_distance: float
    torpedo_max_speed: int
    torpedo_name: str

    count_in_squadron: SquadronSize

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "count_in_squadron":
                val = SquadronSize(val)
            setattr(self, k, val)


@dataclasses.dataclass
class TorpedoProfile:
    """Information about a ship profile's Torpedoes"""

    distance: float
    max_damage: int
    reload_time: int
    rotation_time: float
    torpedo_name: str
    torpedo_speed: int
    torpedoes_id: int
    torpedoes_id_str: str
    visibility_dist: float

    slots: list[Torpedo]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "slots":
                val = [Torpedo(i) for i in val]
            setattr(self, k, val)


@dataclasses.dataclass
class WeaponryProfile:
    """Ratings for the ship's weaponry"""

    aircraft: float
    anti_aircraft: float
    artillery: float
    torpedoes: float

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class SquadronSize:
    """The amount of planes in a Squadron"""

    max: int
    min: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class HullArmourRange:
    """Min and Max Values of a ship's hull's Armour"""

    max: int
    min: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class Shell:
    """Information about a Shell"""

    bullet_mass: int
    bullet_speed: int
    burn_probability: float
    damage: int
    name: str
    type: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class ArmourSegment:
    """Armour for a specific section of a ship"""

    name: str
    max: int
    min: int

    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class AAGun:
    """Details about a ship's AA gun"""

    avg_damage: int
    calibre: int
    distance: float
    guns: int
    name: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class MainGun:
    """Details about a ship's main gun"""

    barrels: int
    guns: int  # Turret count
    name: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class Torpedo:
    """A Torpedo Module"""

    barrels: int
    caliber: int
    guns: int
    name: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class SecondaryGun:
    """A Secondary Gun Module"""

    bullet_mass: int
    bullet_speed: int
    burn_probability: float
    damage: int
    gun_rate: float
    name: str
    shot_delay: float
    type: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


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


@dataclasses.dataclass
class Module:
    """A Module that can be mounted in a ship fitting"""

    image: str
    module_id: int
    module_id_str: str
    price_credit: int
    name: str
    tag: str
    type: str

    profile: ModuleProfile

    def __init__(self, data: dict) -> None:

        for k, val in data.items():
            if k == "profile":
                val = ModuleProfile(val)
            setattr(self, k.lower(), val)

    @property
    def emoji(self) -> str:
        """Return an emoji representing the module"""
        return self.profile.emoji


@dataclasses.dataclass
class ModuleParams:
    """Generic"""

    emoji = "<:auxiliary:991806987362902088>"


@dataclasses.dataclass
class ModuleProfile:
    """Data Not alwawys present"""

    params: ModuleParams = ModuleParams()

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            self.params = {
                "artillery": Artillery,
                "dive_bomber": DiveBomber,
                "engine": Engine,
                "fighter": Fighter,
                "fire_control": FireControl,
                "flight_control": FlightControl,
                "hull": Hull,
                "torpedo_bomber": TorpedoBomberParams,
                "torepdoes": TorpedoParams,
            }[k](val)

    @property
    def emoji(self) -> str:
        """Get an emote representing the module"""
        return self.params.emoji


@dataclasses.dataclass
class Artillery(ModuleParams):
    """An 'Artillery' Module"""

    gun_rate: float
    max_damage_ap: int
    max_damage_he: int
    rotation_time: float
    emoji = "<:Artillery:991026648935718952>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class BomberAccuracy:
    """THe accuracy of a divebomber"""

    min: float
    max: float

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class DiveBomber(ModuleParams):
    """A 'Dive Bomber' Module"""

    accuracy: BomberAccuracy
    bomb_burn_probability: float
    cruise_speed: int
    max_damage: int
    max_health: int

    emoji = "<:DiveBomber:991027856496791682>"

    def __init__(self, data: dict) -> None:
        self.accuracy = BomberAccuracy(data.pop("accuracy"))
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class Engine(ModuleParams):
    """An 'Engine' Module"""

    max_speed: float
    emoji = "<:Engine:991025095772373032>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class Fighter(ModuleParams):
    """A 'Fighter' Module"""

    avg_damage: int
    cruise_speed: int
    max_ammo: int
    max_health: int

    emoji = "<:RocketPlane:991027006554656898>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class FireControl(ModuleParams):
    """A 'Fire Control' Module"""

    distance: float
    distance_increase: int

    emoji = "<:FireControl:991026256722161714>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class FlightControl(ModuleParams):
    """Deprecated - CV FlightControl"""

    bomber_squadrons: int
    fighter_squadrons: int
    torpedo_squadrons: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class HullArmour:
    """The Thickness of the Ship's armour in mm"""

    min: int
    max: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class Hull(ModuleParams):
    """A 'Hull' Module"""

    anti_aircraft_barrels: int
    artillery_barrels: int
    atba_barrels: int
    health: int
    planes_amount: int
    torpedoes_barrels: int
    range: HullArmour

    emoji = "<:Hull:991022247546347581>"

    def __init__(self, data: dict) -> None:
        self.range = HullArmour(data.pop("range"))
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class TorpedoBomberParams(ModuleParams):
    """A 'Torpedo Bomber' Module"""

    cruise_speed: int
    distance: float
    max_damage: int
    max_health: int
    torpedo_damage: int
    torpedo_max_speed: int
    torpedo_name: str

    emoji = "<:TorpedoBomber:991028330251829338>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class TorpedoParams(ModuleParams):
    """A 'Torpedoes' Module"""

    distance: int
    max_damage: int
    shot_speed: int  # Reload Time
    torpedo_speed: int

    emoji = "<:Torpedoes:990731144565764107>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


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
