"""Working with Webscraping the flashscore website"""
from .constants import (
    ADS,
    COMPETITION_EMOJI,
    DEFAULT_LEAGUES,
    FLASHSCORE,
    INBOUND_EMOJI,
    INJURY_EMOJI,
    TEAM_EMOJI,
    OUTBOUND_EMOJI,
)
from .competitions import Competition
from .fixture import Fixture, parse_games
from .gamestate import GameState, dispatch_events
from .matchevents import MatchEvent, EventType, Penalty, Substitution
from .players import Player
from .team import Team
from .search import search, save_comp, save_team
from .transformers import comp_trnsf, fix_trnsf, team_trnsf

__all__ = [
    # constants
    "ADS",
    "DEFAULT_LEAGUES",
    "FLASHSCORE",
    "INBOUND_EMOJI",
    "INJURY_EMOJI",
    "OUTBOUND_EMOJI",
    # competition
    "Competition",
    # emojis
    "COMPETITION_EMOJI",
    "TEAM_EMOJI",
    # fixture
    "Fixture",
    "parse_games",
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
    # search
    "search",
    "save_comp",
    "save_team",
    # transformers
    "comp_trnsf",
    "fix_trnsf",
    "team_trnsf",
]
