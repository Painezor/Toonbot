"""Working with Webscraping the flashscore website"""
# pyright: reportImportCycles=false
from .abc import Competition, Fixture, Team
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
from .gamestate import GameState, get_event_type
from .matchevents import EventType, MatchEvent, Penalty, Substitution
from .players import PartialPlayer, TopScorer
from .team import FSTransfer, SquadMember
from .transformers import comp_trnsf, fix_trnsf, team_trnsf, live_comp_transf

__all__ = [
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
    "PartialPlayer",
    "TopScorer",
    "FSTransfer",
    "SquadMember",
    # team
    "Team",
    # transformers
    "comp_trnsf",
    "fix_trnsf",
    "live_comp_transf",
    "team_trnsf",
]
