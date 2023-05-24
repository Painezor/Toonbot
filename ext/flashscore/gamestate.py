"""Flashscore GameState Objects and ticker dispatching"""
from __future__ import annotations

import enum
import logging

from typing import Any

logger = logging.getLogger("flashscore.gamestate")


class EventType(enum.Enum):
    """An Enum representing an EventType for ticker events"""

    def __init__(self, value: str):
        self._value_ = value

    # Goals
    GOAL = "Goal"
    VAR_GOAL = "VAR Goal"

    # Cards
    RED_CARD = "Red Card"
    VAR_RED_CARD = "VAR Red Card"

    # State Changes
    DELAYED = "Match Delayed"
    INTERRUPTED = "Match Interrupted"
    CANCELLED = "Match Cancelled"
    POSTPONED = "Match Postponed"
    ABANDONED = "Match Abandoned"
    RESUMED = "Match Resumed"

    # Period Changes
    KICK_OFF = "Kick Off"
    HALF_TIME = "Half Time"
    SECOND_HALF_BEGIN = "Second Half"
    PERIOD_BEGIN = "Period #PERIOD#"
    PERIOD_END = "Period #PERIOD# Ends"
    FULL_TIME = "Full Time"

    FINAL_RESULT_ONLY = "Final Result"
    SCORE_AFTER_EXTRA_TIME = "Score After Extra Time"

    NORMAL_TIME_END = "End of normal time"
    EXTRA_TIME_BEGIN = "ET: First Half"
    ET_HT_BEGIN = "ET: Half Time"
    ET_HT_END = "ET: Second Half"
    EXTRA_TIME_END = "ET: End of Extra Time"
    PENALTIES_BEGIN = "Penalties Begin"
    PENALTY_RESULTS = "Penalty Results"


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
    STOPPAGE_TIME = ("Stoppage Time", "🟣", 0x9932CC)

    # Brown
    BREAK_TIME = ("Break", "🟤", 0xA52A2A)

    # Blue
    PENALTIES = ("PSO", "🔵", 0x4285F4)

    # White
    FULL_TIME = ("FT", "⚪", 0xFFFFFF)
    AFTER_PENS = ("Pen", "⚪", 0xFFFFFF)
    AFTER_EXTRA_TIME = ("AET", "⚪", 0xFFFFFF)
    AWARDED = ("Awrd", "⚪", 0xFFFFFF)
