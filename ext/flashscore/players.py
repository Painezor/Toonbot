"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations
from typing import TYPE_CHECKING

from pydantic import BaseModel


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
