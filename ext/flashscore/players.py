"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations

import typing

from ext.utils import flags

from .competitions import Competition
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

        # Attrs
        self.squad_number: typing.Optional[int] = None
        self.position: typing.Optional[str] = None
        self.country: list[str] = []
        self.age: typing.Optional[int] = None

        # Misc Objects.
        self.team: typing.Optional[Team] = None
        self.competition: typing.Optional[Competition] = None

        # Dynamic Attrs
        self.appearances: typing.Optional[int] = None
        self.goals: typing.Optional[int] = None
        self.assists: typing.Optional[int] = None
        self.yellows: typing.Optional[int] = None
        self.reds: typing.Optional[int] = None
        self.injury: typing.Optional[str] = None

        # From top scorers pages.
        self.rank: typing.Optional[int] = None

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
