"""Various World of Warships related Enums"""
from __future__ import annotations

import enum

# TODO: Encyclopedia - Collections
# TODO: Pull Achievement Data to specifically get Jolly Rogers
#       and Hurricane Emblems for player stats.
# TODO: Player's Ranked Battle Season History


class League(enum.Enum):
    """Enum of Clan Battle Leagues"""

    def __new__(cls) -> League:
        value = len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(
        self, alias: str, emote: str, colour: int, image: str
    ) -> None:
        self.alias: str = alias
        self.emote: str = emote
        self.colour: int = colour
        self.image: str = image

    @property
    def thumbnail(self) -> str:
        """Return a link to the image version of the clan's league"""
        return (
            "https://glossary-wows-global.gcdn.co/"
            f"icons//clans/leagues/{self.image}"
        )

    # noinspection SpellCheckingInspection
    HURRICANE = (
        "Hurricane",
        "<:Hurricane:990599761574920332>",
        0xCDA4FF,
        (
            "cvc_league_0_small_1ffb7bdd0346e4a10eaa1"
            "befbd53584dead5cd5972212742d015fdacb34160a1.png"
        ),
    )
    TYPHOON = (
        "Typhoon",
        "<:Typhoon:990599751584067584>",
        0xBEE7BD,
        (
            "cvc_league_1_small_73d5594c7f6ae307721fe89a845b"
            "81196382c08940d9f32c9923f5f2b23e4437.png"
        ),
    )
    STORM = (
        "Storm",
        "<:Storm:990599740079104070>",
        0xE3D6A0,
        (
            "cvc_league_2_small_a2116019add2189c449af6497873"
            "ef87e85c2c3ada76120c27e7ec57d52de163.png"
        ),
    )

    GALE = (
        "Gale",
        "<:Gale:990599200905527329>",
        0xCCE4E4,
        (
            "cvc_league_3_small_d99914b661e711deaff0bdb614"
            "77d82a4d3d4b83b9750f5d1d4b887e6b1a6546.png"
        ),
    )
    SQUALL = (
        "Squall",
        "<:Squall:990597783817965568>",
        0xCC9966,
        (
            "cvc_league_4_small_154e2148d23ee9757568a144e06"
            "c0e8b904d921cc166407e469ce228a7924836.png"
        ),
    )


class Nation(enum.Enum):
    """An Enum representing different nations."""

    def __new__(cls) -> Nation:
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


class Region(enum.Enum):
    """A Generic object representing a region"""

    def __new__(cls) -> Region:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(
        self,
        db_key: str,
        url: str,
        emote: str,
        colour: int,
        code_prefix: str,
        realm: str,
    ) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: int = colour
        self.code_prefix: str = code_prefix
        self.realm: str = realm

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

    def __init__(self, data: dict) -> None:
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
