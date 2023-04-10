"""Handling of Players Retrieved from flashscore"""
from __future__ import annotations

import typing

from ext.utils import flags

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
