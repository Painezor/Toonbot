"""Working with teams retrieved from flashscore"""
from __future__ import annotations

import dataclasses
import datetime
import typing

from ext.utils import timed_events


from .constants import (
    GOAL_EMOJI,
    INBOUND_EMOJI,
    INJURY_EMOJI,
    OUTBOUND_EMOJI,
    RED_CARD_EMOJI,
    TEAM_EMOJI,
    YELLOW_CARD_EMOJI,
)

if typing.TYPE_CHECKING:
    from .abc import Team
    from .players import Player


TFOpts = typing.Literal["All", "Arrivals", "Departures"]


@dataclasses.dataclass(slots=True)
class SquadMember:
    """A Player that is a member of a team"""

    player: Player
    position: str

    squad_number: int
    position: str
    appearances: int
    goals: int
    assists: int
    yellows: int
    reds: int
    injury: str

    @property
    def output(self) -> str:
        """Return a row representing the Squad Member"""
        plr = self.player
        pos = self.position
        text = f"`#{self.squad_number}` {plr.flags} {plr.markdown} ({pos}): "

        if self.goals:
            text += f" {GOAL_EMOJI} {self.goals}"
        if self.appearances:
            text += f" {TEAM_EMOJI} {self.appearances}"
        if self.reds:
            text += f" {RED_CARD_EMOJI} {self.reds}"
        if self.yellows:
            text += f" {YELLOW_CARD_EMOJI} {self.yellows}"
        if self.injury:
            text += f" {INJURY_EMOJI} {self.injury}"
        return text

    def __init__(self, **kwargs: typing.Any) -> None:
        for k, val in kwargs.items():
            setattr(self, k, val)


@dataclasses.dataclass(slots=True)
class FSTransfer:
    """A Transfer Retrieved from Flashscore"""

    date: datetime.datetime
    direction: str
    player: Player
    type: str

    team: typing.Optional[Team] = None  #

    def __init__(self) -> None:
        pass

    @property
    def emoji(self) -> str:
        """Return emoji depending on whether transfer is inbound or outbound"""
        return INBOUND_EMOJI if self.direction == "in" else OUTBOUND_EMOJI

    @property
    def output(self) -> str:
        """Player Markdown, Emoji, Team Markdown, Date, Type of transfer"""
        pmd = self.player.markdown
        tmd = self.team.markdown if self.team else "Free Agent"
        date = timed_events.Timestamp(self.date).date
        return f"{pmd} {self.emoji} {tmd}\n{date} {self.type}\n"
