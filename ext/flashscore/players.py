"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations

import dataclasses
import typing

from ext.utils import flags

from .constants import GOAL_EMOJI

if typing.TYPE_CHECKING:
    from .abc import Team


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
        return f"{self.forename} {self.surname}"

    @property
    def markdown(self) -> str:
        """Return [name](url)"""
        if self.url is None:
            return self.name
        return f"[{self.name}]({self.url})"

    @property
    def flags(self) -> list[str]:
        """Get the flag using transfer_tools util"""
        return flags.get_flags(self.country)


@dataclasses.dataclass(slots=True)
class TopScorer:
    """A Top Scorer object fetched from a Flashscore Item"""

    player: Player
    team: Team

    goals: int
    rank: int
    assists: int

    def __init__(self, player: Player) -> None:
        self.player = player

    @property
    def output(self) -> str:
        """Return a formatted string output for this TopScorer"""
        text = f"`{str(self.rank).rjust(3)}.` {GOAL_EMOJI} {self.goals}"
        text += f" {self.player.flags} {self.player.markdown}"
        if self.assists:
            text += f" (+{self.assists})"
        if self.team:
            text += f" ({self.team.markdown})"
        return text
