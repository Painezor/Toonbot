"""Data retrieved from the Modules endpoint"""
import dataclasses
import logging

import aiohttp

from .shipparameters import BomberAccuracy
from .wg_id import WG_ID


MODULES = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"

logger = logging.getLogger("ext.modules")


@dataclasses.dataclass
class ArtilleryProfile:
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
class DiveBomberProfile:
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
class EngineProfile:
    """An 'Engine' Module"""

    max_speed: float
    emoji = "<:Engine:991025095772373032>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class FighterProfile:
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
class FireControlProfile:
    """A 'Fire Control' Module"""

    distance: float
    distance_increase: int

    emoji = "<:FireControl:991026256722161714>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k.lower(), val)


@dataclasses.dataclass
class FlightControlProfile:
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
class HullProfile:
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
class TorpedoBomberProfile:
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
class TorpedoProfile:
    """A 'Torpedoes' Module"""

    distance: int
    max_damage: int
    shot_speed: int  # Reload Time
    torpedo_speed: int

    emoji = "<:Torpedoes:990731144565764107>"

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
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

    def __init__(self, data: dict) -> None:
        for k, val in data:
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


async def get_modules(modules: list[int]) -> dict[int, Module]:
    """Fetch Module Objects from the world of warships API"""
    module_id = ", ".join(str(i) for i in modules)
    params = {"application_id": WG_ID, "module_id": module_id}
    session = aiohttp.ClientSession()
    async with session.get(MODULES, params=params) as resp:
        if resp.status != 200:
            logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
        data = await resp.json()

    output = dict()
    for id_, data in data["data"].items():
        output.update({id_: Module(data)})
    return output
