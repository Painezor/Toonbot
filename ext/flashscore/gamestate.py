"""Flashscore GameState Objects and ticker dispatching"""
from __future__ import annotations

import enum
import logging

from .matchevents import EventType

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


def get_half_time_change(old: GameState) -> EventType:
    if old == GameState.EXTRA_TIME:
        return EventType.ET_HT_BEGIN
    return EventType.HALF_TIME


def get_break_time_change(old: GameState) -> EventType:
    if old == GameState.EXTRA_TIME:
        return EventType.EXTRA_TIME_END
    return EventType.NORMAL_TIME_END


def get_extra_time_change(old: GameState) -> EventType:
    if old == GameState.HALF_TIME:
        return EventType.ET_HT_END
    return EventType.EXTRA_TIME_BEGIN


def get_live_change(old: GameState) -> EventType:
    return {
        GameState.SCHEDULED: EventType.KICK_OFF,
        GameState.DELAYED: EventType.KICK_OFF,
        GameState.INTERRUPTED: EventType.RESUMED,
        GameState.STOPPAGE_TIME: EventType.SECOND_HALF_BEGIN,
        GameState.HALF_TIME: EventType.SECOND_HALF_BEGIN,
        GameState.BREAK_TIME: EventType.PERIOD_BEGIN,
    }[old]


def get_full_time_change(old: GameState) -> EventType:
    try:
        return {
            GameState.EXTRA_TIME: EventType.SCORE_AFTER_EXTRA_TIME,
            GameState.SCHEDULED: EventType.FINAL_RESULT_ONLY,
            GameState.HALF_TIME: EventType.FINAL_RESULT_ONLY,
        }[old]
    except KeyError:
        return EventType.FULL_TIME


def get_event_type(
    new: GameState | None, old: GameState | None
) -> EventType | None:
    """Conver a new / old difference to an EventType"""
    if old == new or old is None or new is None:
        return

    # I'm pretty sure this is a fucking warcrime.
    try:
        return {
            GameState.ABANDONED: EventType.ABANDONED,
            GameState.AFTER_EXTRA_TIME: EventType.SCORE_AFTER_EXTRA_TIME,
            GameState.AFTER_PENS: EventType.PENALTY_RESULTS,
            GameState.BREAK_TIME: get_break_time_change(old),
            GameState.AWARDED: EventType.CANCELLED,
            GameState.CANCELLED: EventType.CANCELLED,
            GameState.WALKOVER: EventType.CANCELLED,
            GameState.DELAYED: EventType.DELAYED,
            GameState.EXTRA_TIME: get_extra_time_change(old),
            GameState.FULL_TIME: get_full_time_change(old),
            GameState.HALF_TIME: get_half_time_change(old),
            GameState.INTERRUPTED: EventType.INTERRUPTED,
            GameState.PENALTIES: EventType.PENALTIES_BEGIN,
            GameState.POSTPONED: EventType.POSTPONED,
            GameState.STOPPAGE_TIME: None,
            GameState.LIVE: get_live_change(old),
        }[new]
    except KeyError:
        logger.error("State Change Not Handled: %s -> %s", old, new)
