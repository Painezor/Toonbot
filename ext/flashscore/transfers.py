from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel

from .abc import BaseTeam
from .players import FSPlayer


class FSTransfer(BaseModel):
    """A Transfer Retrieved from Flashscore"""

    date: datetime.datetime
    direction: Literal["in", "out"]
    player: FSPlayer
    type: str

    team: BaseTeam | None = None
