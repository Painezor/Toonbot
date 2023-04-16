"""Various World of Warships related Enums"""
from __future__ import annotations


import enum
import logging
from typing import Union


logger = logging.getLogger("wows.enums")
# TODO: Encyclopedia - Collections
# TODO: Pull Achievement Data to specifically get Jolly Rogers
#       and Hurricane Emblems for player stats.
# TODO: Player's Ranked Battle Season History


class Nation(enum.Enum):
    """An Enum representing different nations."""

    def __new__(cls, *args: str) -> Nation:
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, _, match: str, flag: str) -> None:
        self.match: str = match
        self.flag: str = flag
        super().__init__()

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


class Region(enum.Enum):
    """A Generic object representing a region"""

    def __new__(cls, *args: str) -> Region:
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(
        self,
        _,  # ignore, already handled by init
        url: str,
        emote: str,
        colour: int,
        code_prefix: str,
        realm: str,
    ) -> None:
        super().__init__()
        self.domain: str = url
        self.emote: str = emote
        self.colour = colour
        self.code_prefix = code_prefix
        self.realm = realm

    # database key, domain, emote, colour, code prefix, realm
    EU = ("eu", "eu", "<:EU:993495456988545124>", 0x0000FF, "eu", "eu")
    NA = ("na", "com", "<:NA:993495467788869663>", 0x00FF00, "na", "us")
    SEA = ("sea", "asia", "<:ASIA:993495476978589786>", 0x00FFFF, "asia", "sg")


class Map:
    """A Generic container class representing a map"""

    battle_arena_id: int
    description: str
    icon: str
    name: str

    def __init__(self, data: dict[str, Union[int, str]]) -> None:
        for k, val in data.items():
            setattr(self, k, val)

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    @property
    def ac_row(self) -> str:
        """Autocomplete row for this map"""
        return f"{self.name}: {self.description}"

    @property
    def ac_match(self) -> str:
        """Autocomplete match for this map"""
        return f"{self.name}: {self.description} {self.icon}".casefold()
