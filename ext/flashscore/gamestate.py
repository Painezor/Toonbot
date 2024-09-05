"""Flashscore GameState Objects and ticker dispatching"""
from __future__ import annotations

import enum
import logging

from typing import Any

logger = logging.getLogger("flashscore.gamestate")


class GameState(enum.Enum):
    """An Enum representing the various possibilities of game state"""

    def __new__(cls, *args: str) -> GameState:
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, shorthand: str, emote: str, colour: int) -> None:
        self.shorthand: str = shorthand
        self.emote: str = emote
        self.colour: int = colour

    def __eq__(self, other: Any) -> bool:
        if type(self).__qualname__ != type(other).__qualname__:
            return NotImplemented
        return self.name == other.name and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

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
    DELAYED = ("Del", "🟠", 0xFF6700)
    INTERRUPTED = ("Int", "🟠", 0xFF6700)

    # Green
    LIVE = ("Live", "🟢", 0x00FF00)

    # Yellow
    HALF_TIME = ("HT", "🟡", 0xFFFF00)

    # Purple
    EXTRA_TIME = ("ET", "🟣", 0x9932CC)
    STOPPAGE_TIME = ("+", "🟣", 0x9932CC)

    # Brown
    BREAK_TIME = ("Break", "🟤", 0xA52A2A)

    # Blue
    PENALTIES = ("PSO", "🔵", 0x4285F4)

    # White
    FULL_TIME = ("FT", "⚪", 0xFFFFFF)
    AFTER_PENS = ("Pen", "⚪", 0xFFFFFF)
    AFTER_EXTRA_TIME = ("AET", "⚪", 0xFFFFFF)
    AWARDED = ("Awrd", "⚪", 0xFFFFFF)
