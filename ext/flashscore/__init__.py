"""Working with Webscraping the flashscore website"""
from .constants import (
    ADS,
    DEFAULT_LEAGUES,
    FLASHSCORE,
    INBOUND_EMOJI,
    INJURY_EMOJI,
    OUTBOUND_EMOJI,
)
from .competitions import Competition
from .fixture import Fixture, parse_games
from .matchevents import MatchEvent, EventType, Penalty, Substitution
from .players import Player
from .team import Team
from .search import search, save_comp, save_team

__all__ = [
    # constants
    "ADS",
    "DEFAULT_LEAGUES",
    "FLASHSCORE",
    "INBOUND_EMOJI",
    "INJURY_EMOJI".
    "OUTBOUND_EMOJI",
    # competition
    "Competition",
    # fixture
    "Fixture",
    "parse_games",
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

]
