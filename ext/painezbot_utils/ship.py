"""Ship Objects and associated classes"""
from __future__ import annotations

from types import DynamicClassAttribute
import typing
import enum

import unidecode as unidecode
import discord

from ext.painezbot_utils.modules import Module


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

        e = discord.Embed()
        if _class := self.type:
            icon_url = _class.image_premium if prem else _class.image
            _class = _class.alias
        else:
            icon_url = None

        nation = self.nation.alias if self.nation else ""
        tier = f"Tier {self.tier}" if self.tier else ""

        name = [i for i in [tier, nation, _class, self.name] if i]
        e.set_author(name=" ".join(name), icon_url=icon_url)

        if self.images:
            e.set_thumbnail(url=self.images["contour"])
        return e

    @property
    def ac_row(self) -> str:
        """Autocomplete text"""
        nation = "Unknown nation" if self.nation is None else self.nation.alias
        type_ = "Unknown class" if self.type is None else self.type.alias

        # Remove Accents.
        decoded = unidecode.unidecode(self.name)
        return f"{self.tier}: {decoded} {nation} {type_}".casefold()


class ShipSentinel(enum.Enum):
    """A special Sentinel Ship object if we cannot find the original ship"""

    def __new__(cls, *args, **kwargs) -> ShipSentinel:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, ship_id: str, name: str, tier: int) -> None:
        self.id: str = ship_id
        self._name: str = name
        self.tier: int = tier

    @DynamicClassAttribute
    def name(self) -> str:
        """Override 'name' attribute."""
        return self._name

    # IJN DD Split
    FUBUKI_OLD = (4287510224, "Fubuki (pre 01-12-2016)", 8)
    HATSUHARU_OLD = (4288558800, "Hatsuharu (pre 01-12-2016)", 7)
    KAGERO_OLD = (4284364496, "Kagero (pre 01-12-2016)", 9)
    MUTSUKI_OLD = (4289607376, "Mutsuki (pre 01-12-2016)", 6)

    # Soviet DD Split
    GNEVNY_OLD = (4184749520, "Gnevny (pre 06-03-2017)", 5)
    OGNEVOI_OLD = (4183700944, "Ognevoi (pre 06-03-2017)", 6)
    KIEV_OLD = (4180555216, "Kiev (pre 06-03-2017)", 7)
    TASHKENT_OLD = (4181603792, "Tashkent (pre 06-03-2017)", 8)

    # US Cruiser Split
    CLEVELAND_OLD = (4287543280, "Cleveland (pre 31-05-2018)", 6)
    PENSACOLA_OLD = (4282300400, "Pensacola (pre 31-05-2018)", 7)
    NEW_ORLEANS_OLD = (4280203248, "New Orleans (pre 31-05-2018)", 8)
    BALTIMORE_OLD = (4277057520, "Baltimore (pre 31-05-2018)", 9)

    # CV Rework
    HOSHO_OLD = (4292851408, "Hosho (pre 30-01-2019)", 4)
    ZUIHO_OLD = (4288657104, "Zuiho (pre 30-01-2019)", 5)
    RYUJO_OLD = (4285511376, "Ryujo (pre 30-01-2019)", 6)
    HIRYU_OLD = (4283414224, "Hiryu (pre 30-01-2019)", 7)
    SHOKAKU_OLD = (4282365648, "Shokaku (pre 30-01-2019)", 8)
    TAIHO_OLD = (4279219920, "Taiho (pre 30-01-2019)", 9)
    HAKURYU_OLD = (4277122768, "Hakuryu (pre 30-01-2019)", 10)

    LANGLEY_OLD = (4290754544, "Langley (pre 30-01-2019)", 4)
    BOGUE_OLD = (4292851696, "Bogue (pre 30-01-2019)", 5)
    INDEPENDENCE_OLD = (4288657392, "Independence (pre 30-01-2019)", 6)
    RANGER_OLD = (4284463088, "Ranger (pre 30-01-2019)", 7)
    LEXINGTON_OLD = (4282365936, "Lexington (pre 30-01-2019)", 8)
    ESSEX_OLD = (4281317360, "Essex (pre 30-01-2019)", 9)
    MIDWAY_OLD = (4279220208, "Midway (pre 30-01-2019)", 10)

    KAGA_OLD = (3763320528, "Kaga (pre 30-01-2019)", 7)
    SAIPAN_OLD = (3763320816, "Saipan (pre 30-01-2019)", 7)
    ENTERPRISE_OLD = (3762272240, "Enterprise (pre 30-01-2019)", 8)
    GRAF_ZEPPELIN_OLD = (3762272048, "Graf Zeppelin (pre 30-01-2019)", 8)

    # Submarines ...
    U_2501 = (4179015472, "U-2501", 10)
    CACHALOT = (4078352368, "Cachalot", 6)
