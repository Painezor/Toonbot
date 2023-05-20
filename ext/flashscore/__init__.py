"""Working with Webscraping the flashscore website"""
# pyright: reportImportCycles=false
from .abc import BaseTeam
from .cache import FlashscoreCache
from .competitions import Competition
from .constants import (
    ADS,
    COMPETITION_EMOJI,
    DEFAULT_LEAGUES,
    FLASHSCORE,
    GOAL_EMOJI,
    INBOUND_EMOJI,
    INJURY_EMOJI,
    OUTBOUND_EMOJI,
    PLAYER_EMOJI,
    RED_CARD_EMOJI,
    TEAM_EMOJI,
    VAR_EMOJI,
    WARNING_EMOJI,
    YELLOW_CARD_EMOJI,
)
from .fixture import Fixture
from .gamestate import GameState, get_event_type, EventType
from .matchevents import MatchIncident
from .players import FSPlayer
from .topscorers import TopScorer
from .team import Team
from .transfers import FSTransfer
from .squad import SquadMember
from .transformers import (
    cmp_tran,
    fx_tran,
    tm_tran,
    live_comp_transf,
    universal,
)

__all__ = [
    # abc
    "BaseTeam",
    # constants
    "ADS",
    "COMPETITION_EMOJI",
    "DEFAULT_LEAGUES",
    "FLASHSCORE",
    "GOAL_EMOJI",
    "INBOUND_EMOJI",
    "INJURY_EMOJI",
    "OUTBOUND_EMOJI",
    "PLAYER_EMOJI",
    "RED_CARD_EMOJI",
    "TEAM_EMOJI",
    "WARNING_EMOJI",
    "VAR_EMOJI",
    "YELLOW_CARD_EMOJI",
    # cache
    "FlashscoreCache",
    # competition
    "Competition",
    # fixture
    "Fixture",
    # gamestate,
    "GameState",
    "get_event_type",
    # match events
    "EventType",
    "MatchIncident",
    # players
    "FSPlayer",
    "TopScorer",
    "FSTransfer",
    "SquadMember",
    # team
    "Team",
    # transformers
    "cmp_tran",
    "fx_tran",
    "live_comp_transf",
    "tm_tran",
    "universal",
]
