"""Data retrieved from the Modules endpoint"""
import dataclasses
import logging

import aiohttp

from .emojis import (
    ARTILLERY_EMOJI,
    DIVE_BOMBER_EMOJI,
    ENGINE_EMOJI,
    FIRE_CONTROL_EMOJI,
    HULL_EMOJI,
    ROCKET_PLANE_EMOJII,
    TORPEDO_PLANE_EMOJI,
    TORPEDOES_EMOJI,
)
from .shipparameters import BomberAccuracy
from .wg_id import WG_ID

from typing import Any


MODULES = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"

logger = logging.getLogger("ext.modules")


@dataclasses.dataclass(slots=True)
class ArtilleryProfile:
    """An 'Artillery' Module"""

    gun_rate: float
    max_damage_ap: int
    max_damage_he: int
    rotation_time: float
    emoji = ARTILLERY_EMOJI

    def __init__(self, data: dict[str, int | float]) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass(slots=True)
class DiveBomberProfile:
    """A 'Dive Bomber' Module"""

    accuracy: BomberAccuracy
    bomb_burn_probability: float
    cruise_speed: int
    max_damage: int
    max_health: int

    emoji = DIVE_BOMBER_EMOJI

    def __init__(self, data: dict[str, Any]) -> None:
        self.accuracy = BomberAccuracy(data.pop("accuracy"))
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass(slots=True)
class EngineProfile:
    """An 'Engine' Module"""

    max_speed: float

    emoji = ENGINE_EMOJI

    def __init__(self, data: dict[str, float]) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass(slots=True)
class FighterProfile:
    """A 'Fighter' Module"""

    avg_damage: int
    cruise_speed: int
    max_ammo: int
    max_health: int

    emoji = ROCKET_PLANE_EMOJII

    def __init__(self, data: dict[str, int]) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass(slots=True)
class FireControlProfile:
    """A 'Fire Control' Module"""

    distance: float
    distance_increase: int

    emoji = FIRE_CONTROL_EMOJI

    def __init__(self, data: dict[str, float | int]) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass(slots=True)
class FlightControlProfile:
    """Deprecated - CV FlightControl"""

    bomber_squadrons: int
    fighter_squadrons: int
    torpedo_squadrons: int

    emoji = ROCKET_PLANE_EMOJII

    def __init__(self, data: dict[str, int]) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass(slots=True)
class HullArmour:
    """The Thickness of the Ship's armour in mm"""

    min: int
    max: int

    def __init__(self, data: dict[str, int]) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class HullProfile:
    """A 'Hull' Module"""

    anti_aircraft_barrels: int
    artillery_barrels: int
    atba_barrels: int
    health: int
    planes_amount: int
    torpedoes_barrels: int
    range: HullArmour

    emoji = HULL_EMOJI

    def __init__(self, data: dict[str, Any]) -> None:
        self.range = HullArmour(data.pop("range"))
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class TorpedoBomberProfile:
    """A 'Torpedo Bomber' Module"""

    cruise_speed: int
    distance: float
    max_damage: int
    max_health: int
    torpedo_damage: int
    torpedo_max_speed: int
    torpedo_name: str

    emoji = TORPEDO_PLANE_EMOJI

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class TorpedoProfile:
    """A 'Torpedoes' Module"""

    distance: int
    max_damage: int
    shot_speed: int  # Reload Time
    torpedo_speed: int

    emoji = TORPEDOES_EMOJI

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ModuleProfile:
    """Data Not always present"""

    artillery: ArtilleryProfile
    dive_bomber: DiveBomberProfile
    engine: EngineProfile
    fighter: FighterProfile
    fire_control: FireControlProfile
    flight_control: FlightControlProfile
    hull: HullProfile
    torpedo_bomber: TorpedoBomberProfile
    torpedoes: TorpedoProfile

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            val = {
                "artillery": ArtilleryProfile,
                "dive_bomber": DiveBomberProfile,
                "engine": EngineProfile,
                "fighter": FighterProfile,
                "flght_control": FlightControlProfile,
                "hull": HullProfile,
                "torpedo_bomber": TorpedoBomberProfile,
                "torpedoes": TorpedoProfile,
            }[k](val)
            setattr(self, k, val)

    @property
    def emoji(self) -> str:
        """Return the Generic Auxiliary Armament Image"""
        return "<:auxiliary:991806987362902088>"


@dataclasses.dataclass(slots=True)
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

    def __init__(self, data: dict[str, Any]) -> None:
        for k, val in data.items():
            if k == "profile":
                val = ModuleProfile(val)
            setattr(self, k.lower(), val)

    @property
    def emoji(self) -> str:
        """Return an emoji representing the module"""
        return self.profile.emoji


async def get_modules(modules: list[int]) -> dict[int, Module]:
    """Fetch Module Objects from the world of warships API"""
    module_id = ", ".join(str(i) for i in modules)
    params = {"application_id": WG_ID, "module_id": module_id}
    session = aiohttp.ClientSession()
    async with session.get(MODULES, params=params) as resp:
        if resp.status != 200:
            text = await resp.text()
            logger.error("%s %s: %s", resp.status, text, resp.url)
        data = await resp.json()

    output = {id_: Module(data) for id_, data in data["data"].items()}

    return output
