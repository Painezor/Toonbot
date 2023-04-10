"""Working with Webscraping the flashscore website"""
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
from .competitions import Competition
from .fixture import Fixture
from .gamestate import GameState, dispatch_events
from .matchevents import MatchEvent, EventType, Penalty, Substitution
from .players import Player
from .team import FSTransfer, Team, SquadMember
from .search import search, save_comp, save_team
from .transformers import comp_trnsf, fix_trnsf, team_trnsf

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
    "dispatch_events",
    # match events
    "EventType",
    "MatchEvent",
    "Penalty",
    "Substitution",
    # players
    "Player",
    # team
    "Team",
    "FSTransfer",
    "SquadMember",
    # search
    "search",
    "save_comp",
    "save_team",
    # transformers
    "comp_trnsf",
    "fix_trnsf",
    "team_trnsf",
]
