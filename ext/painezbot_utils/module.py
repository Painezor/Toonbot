"""Ship Modules for fittings"""
import typing


# TODO: Convert to Dataclasses & Dump in wows_api


class Module:
    """A Module that can be mounted on a ship"""

    emoji = "<:auxiliary:991806987362902088>"

    def __init__(
        self,
        name: str,
        image: str,
        tag: str,
        module_id: int,
        module_id_str: str,
        price_credit: int,
    ) -> None:
        self.image: str = image
        self.name: str = name
        self.module_id: int = module_id
        self.module_id_str: str = module_id_str
        self.price_credit: int = price_credit
        self.tag: str = tag

        # Extra
        self.is_default: bool = False
        self.price_xp: int = 0


class Artillery(Module):
    """An 'Artillery' Module"""

    emoji = "<:Artillery:991026648935718952>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        # Fire Rate (Rounds / Minute)
        self.gun_rate: float = kwargs.pop("gun_rate", 0)

        # Maximum Armour Piercing Damage
        # Maximum High Explosive Damage
        self.max_damage_AP: int = kwargs.pop("max_damage_AP", 0)
        self.max_damage_HE: int = kwargs.pop("max_damage_HE", 0)

        # Turret Traverse Time in seconds
        self.rotation_time: float = kwargs.pop("rotation_time", 0)


class DiveBomber(Module):
    """A 'Dive Bomber' Module"""

    emoji = "<:DiveBomber:991027856496791682>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        self.bomb_burn_probability: float = kwargs.pop(
            "bomb_burn_probability", 0.0
        )  # FIre Chance, e.g. 52.0
        self.accuracy: dict[str, float] = kwargs.pop(
            "accuracy", {"min": 0.0, "max": 0.0}
        )  # Accuracy, float.
        self.max_damage: int = kwargs.pop("max_damage", 0)  # Max Bomb Damage
        self.max_health: int = kwargs.pop("max_health", 0)  # Max Plane HP
        self.cruise_speed: int = kwargs.pop(
            "cruise_speed", 0
        )  # Max Plane Speed in knots


class Engine(Module):
    """An 'Engine' Module"""

    emoji = "<:Engine:991025095772373032>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        self.max_speed: float = kwargs.pop(
            "max_speed", 0
        )  # Maximum Speed in kts


class RocketPlane(Module):
    """A 'Fighter' Module"""

    emoji = "<:RocketPlane:991027006554656898>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        self.cruise_speed: int = kwargs.pop("cruise_speed", 0)  # Speed in kts
        self.max_health: int = kwargs.pop("max_health", 0)  # HP e.g. 1440

        # Garbage
        self.avg_damage: int = kwargs.pop("avg_damage", 0)
        self.max_ammo: int = kwargs.pop("max_ammo", 0)


class FireControl(Module):
    """A 'Fire Control' Module"""

    emoji = "<:FireControl:991026256722161714>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        self.distance: int = kwargs.pop("distance", 0)
        self.distance_increase: int = kwargs.pop("distance_increase", 0)


class Hull(Module):
    """A 'Hull' Module"""

    emoji = "<:Hull:991022247546347581>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        self.health: int = kwargs.pop("health", 0)
        self.anti_aircraft_barrels: int = kwargs.pop(
            "anti_aircraft_barrels", 0
        )
        self.range: dict[str, int] = kwargs.pop(
            "range"
        )  # This info is complete Garbage. Min - Max Armour.

        self.artillery_barrels: int = kwargs.pop(
            "artillery_barrels", 0
        )  # Number of Main Battery Slots
        self.atba_barrels: int = kwargs.pop(
            "atba_barrels", 0
        )  # Number of secondary battery mounts.
        self.torpedoes_barrels: int = kwargs.pop(
            "torpedoes_barrels", 0
        )  # Number of torpedo launchers.
        self.hangar_size: int = kwargs.pop(
            "planes_amount", 0
        )  # Not returned by API.


class Torpedoes(Module):
    """A 'Torpedoes' Module"""

    emoji = "<:Torpedoes:990731144565764107>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        # Maximum Range of torpedo
        self.distance: typing.Optional[int] = kwargs.pop("distance", 0)
        self.max_damage: typing.Optional[int] = kwargs.pop(
            "max_damage", 0
        )  # Maximum damage of a torpedo
        self.shot_speed: typing.Optional[float] = kwargs.pop(
            "shot_speed", 0
        )  # Reload Speed of the torpedo
        self.torpedo_speed: typing.Optional[int] = kwargs.pop(
            "torpedo_speed", 0
        )  # Maximum speed of the torpedo (knots)


class TorpedoBomber(Module):
    """A 'Torpedo Bomber' Module"""

    emoji = "<:TorpedoBomber:991028330251829338>"

    def __init__(
        self,
        name,
        image,
        tag,
        module_id,
        module_id_str,
        price_credit,
        **kwargs,
    ) -> None:
        super().__init__(
            name, image, tag, module_id, module_id_str, price_credit
        )

        # Cruise Speed in knots, e.g. 120
        self.cruise_speed: int = kwargs.pop("cruise_speed", 0)
        # Max Damage, e.g.  6466
        self.torpedo_damage: int = kwargs.pop("torpedo_damage", 0)
        self.max_damage: int = kwargs.pop("max_damage", 0)

        # Plane HP, e.g. 1800
        self.max_health: int = kwargs.pop("max_health", 0)

        # Torpedo Speed in knots, e.g. 35
        self.torpedo_max_speed: int = kwargs.pop("torpedo_max_speed", 0)

        # Garbage
        self.distance: float = kwargs.pop("distance", 0.0)  # "Firing Range" ?

        # """IDS_PAPT108_LEXINGTON_STOCK"""
        self.torpedo_name: str = kwargs.pop("torpedo_name", None)
