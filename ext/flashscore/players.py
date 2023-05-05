"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ext.utils import flags

if TYPE_CHECKING:
    from .team import Team


class FSPlayer(BaseModel):
    """An object representing a player from flashscore."""

    forename: str | None
    surname: str
    url: str | None

    country: list[str] = []
    age: int | None = None
    team: Team | None = None

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
