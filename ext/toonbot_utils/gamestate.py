"""Flashscore GameState & GameTime Objects"""
from __future__ import annotations

from enum import Enum

from discord import Colour


class GameState(Enum):
    """An Enum representing the various possibilities of game state"""

    def __new__(cls, *args, **kwargs) -> GameState:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, shorthand: str, emote: str, colour: Colour) -> None:
        self.shorthand: str = shorthand
        self.emote: str = emote
        self.colour: Colour = colour

    # Black
    SCHEDULED = ("sched", "⚫", 0x010101)
    AWAITING = ("soon", "⚫", 0x010101)
    FINAL_RESULT_ONLY = ("FRO", "⚫", 0x010101)

    # Red
    POSTPONED = ("PP", "🔴", 0xFF0000)
    ABANDONED = ("Abn", "🔴", 0xFF0000)
    CANCELLED = ("Canc", "🔴", 0xFF0000)
    WALKOVER = ("WO", "🔴", 0xFF0000)

    # Orange
    DELAYED = ("Del", "🟠", 0xff6700)
    INTERRUPTED = ("Int", "🟠", 0xff6700)

    # Green
    LIVE = ("Live", "🟢", 0x00FF00)

    # Yellow
    HALF_TIME = ("HT", "🟡", 0xFFFF00)

    # Purple
    EXTRA_TIME = ("ET", "🟣", 0x9932CC)
    STOPPAGE_TIME = ("Stoppage Time", "🟣", 0x9932CC)

    # Brown
    BREAK_TIME = ("Break", "🟤", 0xA52A2A)

    # Blue
    PENALTIES = ("PSO", "🔵", 0x4285F4)

    # White
    FULL_TIME = ("FT", '⚪', 0xffffff)
    AFTER_PENS = ("Pen", '⚪', 0xffffff)
    AFTER_EXTRA_TIME = ("AET", '⚪', 0xffffff)
    AWARDED = ("Awrd", '⚪', 0xffffff)
