"""Flashscore GameState Objects and ticker dispatching"""
from __future__ import annotations
from dataclasses import MISSING

import enum
import logging
from typing import Optional

import discord

from .matchevents import EventType

logger = logging.getLogger("flashscore.gamestate")


class GameState(enum.Enum):
    """An Enum representing the various possibilities of game state"""

    def __new__(cls, *args: str) -> GameState:
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(
        self, shorthand: str, emote: str, colour: discord.Colour
    ) -> None:
        self.shorthand: str = shorthand
        self.emote: str = emote
        self.colour: discord.Colour = colour

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


def get_event_type(
    new: Optional[GameState], old: Optional[GameState]
) -> Optional[EventType]:
    """Dispatch events to the ticker"""

    if old == new or old is None:
        return

    evt = MISSING

    if new == GameState.ABANDONED:
        evt = EventType.ABANDONED
    elif new == GameState.AFTER_EXTRA_TIME:
        evt = EventType.SCORE_AFTER_EXTRA_TIME
    elif new == GameState.AFTER_PENS:
        evt = EventType.PENALTY_RESULTS
    elif new == GameState.CANCELLED:
        evt = EventType.CANCELLED
    elif new == GameState.DELAYED:
        evt = EventType.DELAYED
    elif new == GameState.INTERRUPTED:
        evt = EventType.INTERRUPTED
    elif new == GameState.BREAK_TIME:
        if old == GameState.EXTRA_TIME:
            # Break Time = after regular time & before penalties
            evt = EventType.EXTRA_TIME_END
        else:
            evt = EventType.NORMAL_TIME_END
    elif new == GameState.EXTRA_TIME:
        if old == GameState.HALF_TIME:
            evt = EventType.HALF_TIME_ET_END
        else:
            evt = EventType.EXTRA_TIME_BEGIN
    elif new == GameState.FULL_TIME:
        if old == GameState.EXTRA_TIME:
            evt = EventType.SCORE_AFTER_EXTRA_TIME
        elif old in [GameState.SCHEDULED, GameState.HALF_TIME]:
            evt = EventType.FINAL_RESULT_ONLY
        else:
            evt = EventType.FULL_TIME
    elif new == GameState.HALF_TIME:
        # Half Time is fired at regular Half time & ET Half time.
        if old == GameState.EXTRA_TIME:
            evt = EventType.HALF_TIME_ET_BEGIN
        else:
            evt = EventType.HALF_TIME
    elif new == GameState.LIVE:
        if old in [GameState.SCHEDULED, GameState.DELAYED]:
            evt = EventType.KICK_OFF
        elif old == GameState.INTERRUPTED:
            evt = EventType.RESUMED
        elif old == GameState.HALF_TIME:
            evt = EventType.SECOND_HALF_BEGIN
        elif old == GameState.BREAK_TIME:
            evt = EventType.PERIOD_BEGIN
    elif new == GameState.PENALTIES:
        evt = EventType.PENALTIES_BEGIN
    elif new == GameState.POSTPONED:
        evt = EventType.POSTPONED
    elif new == GameState.STOPPAGE_TIME:
        return None

    if evt is MISSING:
        logger.error("State Change Not Handled: %s -> %s", old, new)
        evt = None

    return evt
