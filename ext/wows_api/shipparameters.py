"""Parameters about a ship in a specifiic fitting state"""
import dataclasses
import logging
import typing

logger = logging.getLogger("api.shipparams")


@dataclasses.dataclass(slots=True)
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


@dataclasses.dataclass(slots=True)
class ShipAAProfile:
    """Information about a ship profile's Anti Aircraft"""

    defense: int
    slots: list[AAGun]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "slots":
                val = [AAGun(i) for i in val]
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ArmourSegment:
    """Armour for a specific section of a ship"""

    name: str
    max: int
    min: int

    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipArmourProfile:
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


@dataclasses.dataclass(slots=True)
class MainGun:
    """Details about a ship's main gun"""

    barrels: int
    guns: int  # Turret count
    name: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
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


@dataclasses.dataclass(slots=True)
class ShipArtilleryProfile:
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

    @property
    def module_id(self) -> int:
        return self.artillery_id

    @property
    def module_id_str(self) -> str:
        return self.artillery_id_str


@dataclasses.dataclass(slots=True)
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


@dataclasses.dataclass(slots=True)
class ShipSecondaryProfile:
    """Information about a ship profile's Secondary Armaments"""

    distance: float  # range
    slots: list[SecondaryGun]

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "slots":
                val = [SecondaryGun(i) for i in val.values()]
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipConcealmentProfile:
    """Information about a ship profile's Concealment"""

    detect_distance_by_plane: float
    detect_distance_by_ship: float
    total: float  # This is a percentage...? Possibly rating.

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class BomberAccuracy:
    """THe accuracy of a divebomber"""

    min: float
    max: float

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class SquadronSize:
    """The amount of planes in a Squadron"""

    max: int
    min: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipDiveBomberProfile:
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

    @property
    def module_id(self) -> int:
        return self.dive_bomber_id

    @property
    def module_id_str(self) -> str:
        return self.dive_bomber_id_str


@dataclasses.dataclass(slots=True)
class ShipEngineProfile:
    """Information about a ship profile's Engine"""

    engine_id: int
    engine_id_str: str
    max_speed: float  # knots

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)

    @property
    def module_id(self) -> int:
        return self.engine_id

    @property
    def module_id_str(self) -> str:
        return self.engine_id_str


@dataclasses.dataclass(slots=True)
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

    @property
    def module_id(self) -> int:
        return self.fighters_id

    @property
    def module_id_str(self) -> str:
        return self.fighters_id_str


@dataclasses.dataclass(slots=True)
class ShipFireControlProfile:
    """Information about a ship profile's Fire Control System"""

    distance: float  # firing range
    distance_increase: int  # range %
    fire_control_id: int
    fire_control_id_str: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)

    @property
    def module_id(self) -> int:
        return self.fire_control_id

    @property
    def module_id_str(self) -> str:
        return self.fire_control_id_str


@dataclasses.dataclass(slots=True)
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

    @property
    def module_id(self) -> int:
        return self.flight_control_id

    @property
    def module_id_str(self) -> str:
        return self.flight_control_id_str


@dataclasses.dataclass(slots=True)
class HullArmourRange:
    """Min and Max Values of a ship's hull's Armour"""

    max: int
    min: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipHullProfile:
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

    @property
    def module_id(self) -> int:
        return self.hull_id

    @property
    def module_id_str(self) -> str:
        return self.hull_id_str


@dataclasses.dataclass(slots=True)
class ShipMobilityProfile:
    """Information about a ship profile's Mobility"""

    max_speed: float
    rudder_time: float
    total: int  # Manouverability Rating
    turning_radius: int  # meters

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipTorpedoBomberProfile:
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

    @property
    def module_id(self) -> int:
        return self.torpedo_bomber_id

    @property
    def module_id_str(self) -> str:
        return self.torpedo_bomber_id_str


@dataclasses.dataclass(slots=True)
class Torpedo:
    """A Torpedo Module"""

    barrels: int
    caliber: int
    guns: int
    name: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipTorpedoProfile:
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
                val = [Torpedo(i) for i in val.values()]
            setattr(self, k, val)

    @property
    def module_id(self) -> int:
        return self.torpedoes_id

    @property
    def module_id_str(self) -> str:
        return self.torpedoes_id_str


@dataclasses.dataclass(slots=True)
class ShipWeaponryProfile:
    """Ratings for the ship's weaponry"""

    aircraft: float
    anti_aircraft: float
    artillery: float
    torpedoes: float

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class ShipProfile:
    """Information about a ship in a specific configuration (A "Profile")"""

    battle_level_range_max: int
    battle_level_range_min: int

    anti_air: ShipAAProfile
    armour: ShipArmourProfile
    artillery: ShipArtilleryProfile
    atbas: ShipSecondaryProfile
    concealment: ShipConcealmentProfile
    dive_bomber: typing.Optional[ShipDiveBomberProfile]
    engine: ShipEngineProfile
    fighters: typing.Optional[ShipFighterProfile]
    fire_control: ShipFireControlProfile
    flight_control: typing.Optional[ShipFlightControlProfile]
    hull: ShipHullProfile
    mobility: ShipMobilityProfile
    torpedo_bomber: typing.Optional[ShipTorpedoBomberProfile]
    torpedoes: ShipTorpedoProfile
    weaponry: ShipWeaponryProfile

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if val is not None:
                try:
                    val = {
                        "anti_air": ShipAAProfile,
                        "armour": ShipArmourProfile,
                        "artillery": ShipArtilleryProfile,
                        "atbas": ShipSecondaryProfile,
                        "concealment": ShipConcealmentProfile,
                        "dive_bomber": ShipDiveBomberProfile,
                        "engine": ShipEngineProfile,
                        "fire_control": ShipFireControlProfile,
                        "flight_control": ShipFlightControlProfile,
                        "hull": ShipHullProfile,
                        "mobility": ShipMobilityProfile,
                        "torpedo_bomber": ShipTorpedoBomberProfile,
                        "torpedoes": ShipTorpedoProfile,
                        "weaponry": ShipWeaponryProfile,
                    }[k](val)
                except KeyError:
                    pass
            setattr(self, k, val)
