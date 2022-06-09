"""Utilities for World of Warships related commands."""
from enum import Enum

from discord import Colour


class Region(Enum):
    """A Generic object representing a region"""

    def __new__(cls, *args, **kwargs):
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, db_key: str, url: str, emote: str, colour: Colour, code_prefix: str) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: Colour = colour
        self.code_prefix: str = code_prefix

    #     db_key  | domain                       | emote                             | colour   | code prefix
    EU = ('eu', 'https://worldofwarships.eu/', "<:painezBot:928654001279471697>", 0x0000ff, 'eu')
    NA = ('na', 'https://worldofwarships.com/', "<:Bonk:746376831296471060>", 0x00ff00, 'na')
    SEA = ('sea', 'https://worldofwarships.asia/', "<:painezRaid:928653997680754739>", 0x00ffff, 'asia')
    CIS = ('cis', 'https://worldofwarships.ru/', "<:Button:826154019654991882>", 0xff0000, 'ru')
