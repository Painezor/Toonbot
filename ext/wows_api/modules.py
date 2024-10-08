"""Data retrieved from the Modules endpoint"""
import logging

import aiohttp
from pydantic import BaseModel, ValidationError

from .emojis import (
    ARTILLERY_EMOJI,
    AUXILIARY_EMOJI,
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


MODULES = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"

logger = logging.getLogger("api.modules")


class ArtilleryModuleProfile(BaseModel):
    """An 'Artillery' Module"""

    gun_rate: float
    max_damage_AP: int
    max_damage_HE: int
    rotation_time: float
    emoji = ARTILLERY_EMOJI


class DiveBomberModuleProfile(BaseModel):
    """A 'Dive Bomber' Module"""

    accuracy: BomberAccuracy
    bomb_burn_probability: float
    cruise_speed: int
    max_damage: int | None
    max_health: int

    emoji = DIVE_BOMBER_EMOJI


class EngineModuleProfile(BaseModel):
    """An 'Engine' Module"""

    max_speed: float

    emoji = ENGINE_EMOJI


class FighterModuleProfile(BaseModel):
    """A 'Fighter' Module"""

    avg_damage: int | None
    cruise_speed: int
    max_ammo: int | None
    max_health: int

    emoji = ROCKET_PLANE_EMOJII


class FireControlModuleProfile(BaseModel):
    """A 'Fire Control' Module"""

    distance: float
    distance_increase: int | None

    emoji = FIRE_CONTROL_EMOJI


class FlightControlModuleProfile(BaseModel):
    """Deprecated - CV FlightControl"""

    bomber_squadrons: int
    fighter_squadrons: int
    torpedo_squadrons: int

    emoji = ROCKET_PLANE_EMOJII


class HullArmour(BaseModel):
    """The Thickness of the Ship's armour in mm"""

    min: int
    max: int


class HullModuleProfile(BaseModel):
    """A 'Hull' Module"""

    anti_aircraft_barrels: int
    artillery_barrels: int
    atba_barrels: int
    health: int
    planes_amount: int | None
    torpedoes_barrels: int
    range: HullArmour

    emoji = HULL_EMOJI


class TorpedoBomberModuleProfile(BaseModel):
    """A 'Torpedo Bomber' Module"""

    cruise_speed: int
    distance: float | None
    max_damage: int
    max_health: int
    torpedo_damage: int
    torpedo_max_speed: int
    torpedo_name: str

    emoji = TORPEDO_PLANE_EMOJI


class TorpedoModuleProfile(BaseModel):
    """A 'Torpedoes' Module"""

    distance: int
    max_damage: int
    shot_speed: int  # Reload Time
    torpedo_speed: int

    emoji = TORPEDOES_EMOJI


class ModuleProfile(BaseModel):  # Generic
    """Data Not always present"""

    artillery: ArtilleryModuleProfile | None
    dive_bomber: DiveBomberModuleProfile | None
    engine: EngineModuleProfile | None
    fighter: FighterModuleProfile | None
    fire_control: FireControlModuleProfile | None
    flight_control: FlightControlModuleProfile | None
    hull: HullModuleProfile | None
    torpedo_bomber: TorpedoBomberModuleProfile | None
    torpedoes: TorpedoModuleProfile | None

    @property
    def emoji(self) -> str:
        """Retrieve the emoji from the profiel, else Generic Emoji"""
        for i in self.dict(exclude_none=True).values():
            if i:
                return i["emoji"]
        return AUXILIARY_EMOJI


class Module(BaseModel):
    """A Module that can be mounted in a ship fitting"""

    image: str
    module_id: int
    module_id_str: str
    price_credit: int
    name: str
    tag: str
    type: str

    profile: ModuleProfile


async def fetch_modules(modules: list[int]) -> dict[str, Module]:
    """Fetch Module Objects from the world of warships API"""
    module_id = ", ".join(str(i) for i in modules)
    params = {"application_id": WG_ID, "module_id": module_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(MODULES, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

    output: dict[str, Module] = {}
    for id_, data in data["data"].items():
        try:
            output.update({id_: Module.parse_obj(data)})
        except ValidationError as err:
            logger.error("Validation failed on %s", id_)
            logger.error(err)
            continue

    return output
