"""Working with Webscraping the flashscore website"""
# pyright: reportImportCycles=false
from .abc import FSObject
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
    YELLOW_CARD_EMOJI,
)
from .fixture import Fixture
from .gamestate import GameState, get_event_type
from .matchevents import EventType, MatchEvent, Penalty, Substitution
from .players import FSPlayer, TopScorer
from .team import Team, FSTransfer, SquadMember
from .transformers import (
    cmp_tran,
    fx_tran,
    tm_tran,
    live_comp_transf,
    universal,
)

__all__ = [
    "FSObject",
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
    "YELLOW_CARD_EMOJI",
    # competition
    "Competition",
    # fixture
    "Fixture",
    # gamestate,
    "GameState",
    "get_event_type",
    # match events
    "EventType",
    "MatchEvent",
    "Penalty",
    "Substitution",
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
