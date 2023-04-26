"""Parameters about a ship in a specifiic fitting state"""
import logging

from pydantic import BaseModel

logger = logging.getLogger("api.shipparams")


class AAGun(BaseModel):
    """Details about a ship's AA gun"""

    avg_damage: int | None
    caliber: int
    distance: float
    guns: int
    name: str


class ShipAAProfile(BaseModel):
    """Information about a ship profile's Anti Aircraft"""

    defense: int
    slots: dict[str, AAGun] | None


class Range(BaseModel):
    """
    Armour for a specific section of a ship

    """

    max: int | None
    min: int | None


class ShipArmourProfile(BaseModel):
    """Information about a ship profile's Armour"""

    flood_damage: int  # Belt Torpedo Reduction in %
    # flood_prob: int  # Belt Flood Chance Reduction in %
    health: int
    total: float  # Damage Reduction %  -- This is dead.

    casemate: Range
    citadel: Range
    deck: Range
    extremities: Range
    range: Range


class MainGun(BaseModel):
    """Details about a ship's main gun"""

    barrels: int
    guns: int  # Turret count
    name: str


class Shell(BaseModel):
    """Information about a Shell"""

    bullet_mass: int
    bullet_speed: int
    damage: int
    name: str
    type: str

    burn_probability: float | None


class ShipArtilleryProfile(BaseModel):
    """Information about a ship profile's Main Battery"""

    artillery_id: int
    artillery_id_str: str
    distance: float  # Firing Range
    gun_rate: float  # Rounds per minute
    max_dispersion: int  # meters
    rotation_time: float  # 180 turn time in seconds
    shot_delay: float  # reload time

    shells: dict[str, Shell]
    slots: dict[str, MainGun] | None

    @property
    def module_id(self) -> int:
        """Retrieve the module's id int"""
        return self.artillery_id

    @property
    def module_id_str(self) -> str:
        """Retrieve the module's id str"""
        return self.artillery_id_str


class SecondaryGun(BaseModel):
    """A Secondary Gun Module"""

    bullet_mass: int
    bullet_speed: int
    burn_probability: float | None
    damage: int
    gun_rate: float
    name: str
    shot_delay: float
    type: str


class ShipSecondaryProfile(BaseModel):
    """Information about a ship profile's Secondary Armaments"""

    distance: float  # range
    slots: dict[str, SecondaryGun] | None


class ShipConcealmentProfile(BaseModel):
    """Information about a ship profile's Concealment"""

    detect_distance_by_plane: float
    detect_distance_by_ship: float
    total: float  # This is a percentage...? Possibly rating.


class BomberAccuracy(BaseModel):
    """THe accuracy of a divebomber"""

    min: float | None
    max: float | None


class ShipDiveBomberProfile(BaseModel):
    """Information about a ship profile's Dive Bombers"""

    bomb_bullet_mass: int
    bomb_burn_probability: float | None
    bomb_damage: int | None
    bomb_name: str | None
    cruise_speed: int
    dive_bomber_id: int
    dive_bomber_id_str: str
    gunner_damage: int | None
    max_damage: int | None
    max_health: int
    name: str
    plane_level: int
    prepare_time: int | None
    squadrons: int | None

    accuracy: BomberAccuracy
    count_in_squadron: Range

    @property
    def module_id(self) -> int:
        """Retrieve the module's id int"""
        return self.dive_bomber_id

    @property
    def module_id_str(self) -> str:
        """Retrieve the module's id str"""
        return self.dive_bomber_id_str


class ShipEngineProfile(BaseModel):
    """Information about a ship profile's Engine"""

    engine_id: int
    engine_id_str: str
    max_speed: float  # knots

    @property
    def module_id(self) -> int:
        """Retrieve the module's id int"""
        return self.engine_id

    @property
    def module_id_str(self) -> str:
        """Retrieve the module's id str"""
        return self.engine_id_str


class ShipFighterProfile(BaseModel):
    """Information about a ship profile's Fighters"""

    avg_damage: int | None
    cruise_speed: int | None
    fighters_id: int
    fighters_id_str: str
    gunner_damage: int | None
    max_ammo: int | None
    max_health: int | None
    name: str | None
    plane_level: int | None
    prepare_time: int | None
    squadrons: int | None

    count_in_squadron: Range

    @property
    def module_id(self) -> int:
        """Retrieve the module's id int"""
        return self.fighters_id

    @property
    def module_id_str(self) -> str:
        """Retrieve the module's id str"""
        return self.fighters_id_str


class ShipFireControlProfile(BaseModel):
    """Information about a ship profile's Fire Control System"""

    distance: float  # firing range
    distance_increase: int | None  # range %
    fire_control_id: int
    fire_control_id_str: str

    @property
    def module_id(self) -> int:
        return self.fire_control_id

    @property
    def module_id_str(self) -> str:
        return self.fire_control_id_str


class ShipFlightControlProfile(BaseModel):
    """Information about a ship profile's Flight Control System"""

    bomber_squadrons: int
    fighter_squadrons: int
    flight_control_id: int
    flight_control_id_str: str
    torpedo_squadrons: int

    @property
    def module_id(self) -> int:
        return self.flight_control_id

    @property
    def module_id_str(self) -> str:
        return self.flight_control_id_str


class ShipHullProfile(BaseModel):
    """Information about a ship profile's Hull"""

    anti_aircraft_barrels: int
    artillery_barrels: int
    atba_barrels: int
    health: int
    hull_id: int
    hull_id_str: str
    planes_amount: int | None
    torpedoes_barrels: int

    range: Range  # Ship Armour

    @property
    def module_id(self) -> int:
        return self.hull_id

    @property
    def module_id_str(self) -> str:
        return self.hull_id_str


class ShipMobilityProfile(BaseModel):
    """Information about a ship profile's Mobility"""

    max_speed: float
    rudder_time: float
    total: int  # Manouverability Rating
    turning_radius: int  # meters


class ShipTorpedoBomberProfile(BaseModel):
    """Information about a ship profile's Torpedo Bombers"""

    cruise_speed: int | None
    gunner_damage: int | None
    max_damage: int | None
    max_health: int | None
    name: str | None
    plane_level: int | None
    prepare_time: int | None
    squadrons: int | None
    torpedo_bomber_id: int
    torpedo_bomber_id_str: str
    torpedo_damage: int | None
    torpedo_distance: float | None
    torpedo_max_speed: int | None
    torpedo_name: str | None

    count_in_squadron: Range

    @property
    def module_id(self) -> int:
        return self.torpedo_bomber_id

    @property
    def module_id_str(self) -> str:
        return self.torpedo_bomber_id_str


class Torpedo(BaseModel):
    """A Torpedo Module"""

    barrels: int
    caliber: int
    guns: int
    name: str


class ShipTorpedoProfile(BaseModel):
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

    slots: dict[str, Torpedo] | None

    @property
    def module_id(self) -> int:
        return self.torpedoes_id

    @property
    def module_id_str(self) -> str:
        return self.torpedoes_id_str


class ShipWeaponryProfile(BaseModel):
    """Ratings for the ship's weaponry"""

    aircraft: float
    anti_aircraft: float
    artillery: float
    torpedoes: float


class ShipProfile(BaseModel):
    """Information about a ship in a specific configuration (A "Profile")"""

    battle_level_range_max: int | None
    battle_level_range_min: int | None

    anti_aircraft: ShipAAProfile | None
    armour: ShipArmourProfile | None
    artillery: ShipArtilleryProfile | None
    atbas: ShipSecondaryProfile | None
    concealment: ShipConcealmentProfile | None
    dive_bomber: ShipDiveBomberProfile | None
    engine: ShipEngineProfile | None
    fighters: ShipFighterProfile | None
    fire_control: ShipFireControlProfile | None
    flight_control: ShipFlightControlProfile | None
    hull: ShipHullProfile | None
    mobility: ShipMobilityProfile | None
    torpedo_bomber: ShipTorpedoBomberProfile | None
    torpedoes: ShipTorpedoProfile | None
    weaponry: ShipWeaponryProfile | None
