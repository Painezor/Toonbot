from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from ext.utils import timed_events

from .constants import INBOUND_EMOJI, OUTBOUND_EMOJI
from .players import FSPlayer

if TYPE_CHECKING:
    from .team import Team


class FSTransfer(BaseModel):
    """A Transfer Retrieved from Flashscore"""

    date: datetime.datetime
    direction: str
    player: FSPlayer
    type: str

    team: Team | None = None

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
