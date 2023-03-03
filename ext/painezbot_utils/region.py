from __future__ import annotations

import enum
import discord


class Region(enum.Enum):
    """A Generic object representing a region"""

    def __new__(cls, *args, **kwargs) -> Region:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(
        self,
        db_key: str,
        url: str,
        emote: str,
        colour: discord.Colour,
        code_prefix: str,
        realm: str,
    ) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: discord.Colour = colour
        self.code_prefix: str = code_prefix
        self.realm: str = realm

    @property
    def inventory(self) -> str:
        """Returns a link to the 'Inventory Management' webpage"""
        return f"https://warehouse.worldofwarships.{self.domain}"

    @property
    def armory(self) -> str:
        """Returns a link to the 'Armory' webpage"""
        return f"https://armory.worldofwarships.{self.domain}/en/"

    @property
    def clans(self) -> str:
        """Returns a link to the 'Clans' webpage"""
        return (
            f"https://clans.worldofwarships.{self.domain}"
            "/clans/gateway/wows/profile"
        )

    @property
    def logbook(self) -> str:
        """Returns a link to the 'Captains Logbook' page"""
        return f"https://logbook.worldofwarships.{self.domain}/"

    @property
    def dockyard(self) -> str:
        """Return a link to the 'Dockyard' page"""
        return f"http://dockyard.worldofwarships.{self.domain}/en/"

    @property
    def news(self) -> str:
        """Return a link to the in-game version of the portal news"""
        return f"https://worldofwarships.{self.domain}/news_ingame"

    @property
    def recruiting(self) -> str:
        """Return a link to the 'Recruiting Station' page"""
        return f"https://friends.worldofwarships.{self.domain}/en/players/"

    # database key, domain, emote, colour, code prefix, realm
    EU = ("eu", "eu", "<:EU:993495456988545124>", 0x0000FF, "eu", "eu")
    NA = ("na", "com", "<:NA:993495467788869663>", 0x00FF00, "na", "us")
    SEA = ("sea", "asia", "<:ASIA:993495476978589786>", 0x00FFFF, "asia", "sg")
    CIS = ("cis", "ru", "<:CIS:993495488248680488>", 0xFF0000, "ru", "ru")
