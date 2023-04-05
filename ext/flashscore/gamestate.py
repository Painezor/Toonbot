"""Flashscore GameState Objects and ticker dispatching"""
from __future__ import annotations

import enum
import logging
import typing

import discord

from .matchevents import EventType
from .fixture import Fixture


if typing.TYPE_CHECKING:
    from core import Bot


logger = logging.getLogger("flashscore.gamestate")


class GameState(enum.Enum):
    """An Enum representing the various possibilities of game state"""

    def __new__(cls, *args) -> GameState:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
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


def dispatch_events(bot: Bot, fix: Fixture, old: GameState) -> None:
    """Dispatch events to the ticker"""
    evt = "fixture_event"
    send_event = bot.dispatch

    new = fix.state

    if old == new or old is None:
        return

    if new == GameState.ABANDONED:
        return send_event(evt, EventType.ABANDONED, fix)
    elif new == GameState.AFTER_EXTRA_TIME:
        return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fix)
    elif new == GameState.AFTER_PENS:
        return send_event(evt, EventType.PENALTY_RESULTS, fix)
    elif new == GameState.CANCELLED:
        return send_event(evt, EventType.CANCELLED, fix)
    elif new == GameState.DELAYED:
        return send_event(evt, EventType.DELAYED, fix)
    elif new == GameState.INTERRUPTED:
        return send_event(evt, EventType.INTERRUPTED, fix)
    elif new == GameState.BREAK_TIME:
        if old == GameState.EXTRA_TIME:
            # Break Time = after regular time & before penalties
            return send_event(evt, EventType.EXTRA_TIME_END, fix)
        fix.breaks += 1
        if fix.periods is not None:
            return send_event(evt, EventType.PERIOD_END, fix)
        else:
            return send_event(evt, EventType.NORMAL_TIME_END, fix)
    elif new == GameState.EXTRA_TIME:
        if old == GameState.HALF_TIME:
            return send_event(evt, EventType.HALF_TIME_ET_END, fix)
        return send_event(evt, EventType.EXTRA_TIME_BEGIN, fix)
    elif new == GameState.FULL_TIME:
        if old == GameState.EXTRA_TIME:
            return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fix)
        elif old in [GameState.SCHEDULED, GameState.HALF_TIME]:
            return send_event(evt, EventType.FINAL_RESULT_ONLY, fix)
        return send_event(evt, EventType.FULL_TIME, fix)
    elif new == GameState.HALF_TIME:
        # Half Time is fired at regular Half time & ET Half time.
        if old == GameState.EXTRA_TIME:
            return send_event(evt, EventType.HALF_TIME_ET_BEGIN, fix)
        else:
            return send_event(evt, EventType.HALF_TIME, fix)
    elif new == GameState.LIVE:
        if old in [GameState.SCHEDULED, GameState.DELAYED]:
            return send_event(evt, EventType.KICK_OFF, fix)
        elif old == GameState.INTERRUPTED:
            return send_event(evt, EventType.RESUMED, fix)
        elif old == GameState.HALF_TIME:
            return send_event(evt, EventType.SECOND_HALF_BEGIN, fix)
        elif old == GameState.BREAK_TIME:
            return send_event(evt, EventType.PERIOD_BEGIN, fix)
    elif new == GameState.PENALTIES:
        return send_event(evt, EventType.PENALTIES_BEGIN, fix)
    elif new == GameState.POSTPONED:
        return send_event(evt, EventType.POSTPONED, fix)
    elif new == GameState.STOPPAGE_TIME:
        return

    logger.error("States: %s -> %s %s @ %s", old, new, fix.url, fix.time)
