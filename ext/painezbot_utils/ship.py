"""Ship Objects and associated classes"""
from __future__ import annotations

import dataclasses
import enum
import typing
import unidecode

import discord

from ext.painezbot_utils.module import Module


class Nation(enum.Enum):
    """An Enum representing different nations."""

    def __new__(cls, *args, **kwargs) -> Nation:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, alias: str, match: str, flag: str) -> None:
        self.alias: str = alias
        self.match: str = match
        self.flag: str = flag

    COMMONWEALTH = ("Commonwealth", "commonwealth", "")
    EUROPE = ("Pan-European", "europe", "🇪🇺")
    FRANCE = ("French", "france", "🇫🇷")
    GERMANY = ("German", "germany", "🇩🇪")
    ITALY = ("Italian", "italy", "🇮🇹")
    JAPAN = ("Japanese", "japan", "🇯🇵")
    NETHERLANDS = ("Dutch", "netherlands", "🇳🇱")
    PAN_ASIA = ("Pan-Asian", "pan_asia", "")
    PAN_AMERICA = ("Pan-American", "pan_america", "")
    SPAIN = ("Spanish", "spain", "🇪🇸")
    UK = ("British", "uk", "🇬🇧")
    USSR = ("Soviet", "ussr", "")
    USA = ("American", "usa", "🇺🇸")


@dataclasses.dataclass
class ShipType:
    """Submarine, Cruiser, etc."""

    def __init__(self, match: str, alias: str, images: dict):
        self.match: str = match
        self.alias: str = alias

        self.image = images["image"]
        self.image_elite = images["image_elite"]
        self.image_premium = images["image_premium"]


class Ship:
    """A World of Warships Ship."""

    # Class attr.

    def __init__(self) -> None:
        self.name: str = "Unknown Ship"
        self.ship_id: typing.Optional[int] = None
        self.ship_id_str: typing.Optional[str] = None

        # Initial Data
        self.description: typing.Optional[str] = None  # Ship description
        # Indicates that ship iS WIP
        self.has_demo_profile: bool = False
        self.is_premium: bool = False  # Indicates if the ship is Premium ship
        self.is_special: bool = False  # ship is on a special offer
        self.images: dict = {}  # A list of images
        self.mod_slots: int = 0  # Number of slots for upgrades
        self._modules: dict = {}  # Dict of Lists of available modules.
        self.modules_tree: dict = {}  #
        self.nation: typing.Optional[Nation] = None  # Ship Nation
        self.next_ships: dict = {}  # {k: ship_id as str, v: xp as int }
        self.price_credit: int = 0  # Cost in credits
        self.price_gold: int = 0  # Cost in doubloons
        self.tier: int = 0  # Tier of the ship (1 - 11 for super)
        self.type: ShipType  # Type of ship
        self.upgrades: list[int] = []  # List of compatible Modifications IDs

        # Fetched Modules
        self.available_modules: dict[int, Module]
        # Params Data
        self.default_profile: dict = {}

    def base_embed(self) -> discord.Embed:
        """Get a generic embed for the ship"""
        prem = any([self.is_premium, self.is_special])

        embed = discord.Embed()
        if _class := self.type:
            icon_url = _class.image_premium if prem else _class.image
            _class = _class.alias
        else:
            icon_url = None

        nation = self.nation.alias if self.nation else ""
        tier = f"Tier {self.tier}" if self.tier else ""

        name = [i for i in [tier, nation, _class, self.name] if i]
        embed.set_author(name=" ".join(name), icon_url=icon_url)

        if self.images:
            embed.set_thumbnail(url=self.images["contour"])
        return embed

    @property
    def ac_row(self) -> str:
        """Autocomplete text"""
        nation = "Unknown nation" if self.nation is None else self.nation.alias
        type_ = "Unknown class" if self.type is None else self.type.alias

        # Remove Accents.
        decoded = unidecode.unidecode(self.name)
        return f"{self.tier}: {decoded} {nation} {type_}".casefold()
