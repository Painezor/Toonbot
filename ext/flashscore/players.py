"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations

import dataclasses
import datetime
import typing

from ext.utils import flags, timed_events

from .constants import (
    GOAL_EMOJI,
    INBOUND_EMOJI,
    INJURY_EMOJI,
    OUTBOUND_EMOJI,
    RED_CARD_EMOJI,
    TEAM_EMOJI,
    YELLOW_CARD_EMOJI,
)
from .team import Team


class Player:
    """An object representing a player from flashscore."""

    def __init__(
        self,
        forename: typing.Optional[str],
        surname: str,
        url: typing.Optional[str],
    ) -> None:
        # Main. Forename will not always be present.
        self.forename: typing.Optional[str] = forename
        self.surname: str = surname
        self.url: typing.Optional[str] = url

        self.country: list[str] = []
        self.age: typing.Optional[int] = None
        self.team: typing.Optional[Team] = None

    @property
    def name(self) -> str:
        """FirstName Surname or just Surname if no Forename is found"""
        if self.forename is None:
            return self.surname
        else:
            return f"{self.forename} {self.surname}"

    @property
    def markdown(self) -> str:
        """Return [name](url)"""
        if self.url is None:
            return self.name
        else:
            return f"[{self.name}]({self.url})"

    @property
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        return flags.get_flag(self.country) or ""


@dataclasses.dataclass(slots=True)
class TopScorer:
    """A Top Scorer object fetched from a Flashscore Item"""

    player: Player
    team: Team

    goals: int
    rank: int
    assists: int

    def __init__(self, **kwargs) -> None:
        for k, val in kwargs.items():
            setattr(self, k, val)

    def output(self) -> str:
        """Return a formatted string output for this TopScorer"""
        text = f"`{str(self.rank).rjust(3)}.` {GOAL_EMOJI} {self.goals}"
        text += f" {self.player.flag} {self.player.markdown}"
        if self.assists:
            text += f" (+{self.assists})"
        if self.team:
            text += f" ({self.team.markdown})"
        return text


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

    def output(self) -> str:
        """Return a row representing the Squad Member"""
        plr = self.player
        pos = self.position
        text = f"`#{self.squad_number}` {plr.flag} {plr.markdown} ({pos}): "

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

    def __init__(self, **kwargs) -> None:
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
