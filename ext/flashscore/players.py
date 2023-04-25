"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations

from pydantic import BaseModel
from typing import TYPE_CHECKING, Optional

from ext.utils import flags

from .constants import GOAL_EMOJI

if TYPE_CHECKING:
    from .team import Team


class FSPlayer(BaseModel):
    """An object representing a player from flashscore."""

    forename: Optional[str]
    surname: str
    url: Optional[str]

    country: list[str] = []
    age: Optional[int] = None
    team: Optional[Team] = None

    def __init__(
        self,
        forename: Optional[str],
        surname: str,
        url: Optional[str],
    ) -> None:
        # Main. Forename will not always be present.
        self.forename: Optional[str] = forename
        self.surname: str = surname
        self.url: Optional[str] = url

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


class TopScorer(BaseModel):
    """A Top Scorer object fetched from a Flashscore Item"""

    player: FSPlayer
    team: Optional[Team] = None
    goals: int = 0
    rank: int = 0
    assists: int = 0

    def __init__(self, player: FSPlayer) -> None:
        self.player = player

    @property
    def output(self) -> str:
        """Return a formatted string output for this TopScorer"""
        text = f"`{str(self.rank).rjust(3)}.` {GOAL_EMOJI} {self.goals}"
        if self.assists:
            text += f" (+{self.assists})"
        text += f" {self.player.flags[0]} {self.player.markdown}"
        if self.team:
            text += f" ({self.team.markdown})"
        return text
