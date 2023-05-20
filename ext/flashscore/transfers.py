from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from .players import FSPlayer

if TYPE_CHECKING:
    from .team import Team


class FSTransfer(BaseModel):
    """A Transfer Retrieved from Flashscore"""

    date: datetime.datetime
    direction: Literal["in", "out"]
    player: FSPlayer
    type: str

    team: Team | None = None
