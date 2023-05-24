"""Working with Webscraping the flashscore website"""
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
from .matchevents import MatchIncident
from .players import FSPlayer
from .squad import SquadMember
from .team import Team
from .topscorers import TopScorer
from .transfers import FSTransfer

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
    # match events
    "MatchIncident",
    # players
    "FSPlayer",
    "TopScorer",
    "FSTransfer",
    "SquadMember",
    # team
    "Team",
]
