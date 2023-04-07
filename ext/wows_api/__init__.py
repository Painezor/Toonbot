"""Utilities to work with the world of warhips API"""
from .clan import (
    get_cb_winners,
    get_cb_seasons,
    get_clan_details,
    get_clan_vortex_data,
    get_member_vortex,
    PartialClan,
    ClanBattleSeason,
    ClanBattleWinner,
    ClanBuilding,
    ClanSeasonStats,
    ClanLeaderboardStats,
    PlayerCBStats,
    Clan,
    ClanVortexData,
    ClanMember,
    ClanMemberVortexData,
)
from .enums import Map, Nation, Region
from .gamemode import GameMode, get_game_modes
from .modules import Module, get_modules
from .player import Player, PlayerStats, PlayerStatsMode
from .warships import Ship, ShipProfile, get_ships, ShipFit
from .transformers import (
    clan_transform,
    mode_transform,
    player_transform,
    ship_transform,
)

__all__ = [
    # clan
    "get_cb_seasons",
    "get_cb_winners",
    "get_clan_details",
    "get_member_vortex",
    "get_clan_vortex_data",
    "PartialClan",
    "ClanBattleSeason",
    "ClanBattleWinner",
    "ClanBuilding",
    "ClanSeasonStats",
    "ClanLeaderboardStats",
    "PlayerCBStats",
    "Clan",
    "ClanVortexData",
    "ClanMember",
    "ClanMemberVortexData",
    # enums
    "Map",
    "Nation",
    "Region",
    # gamemode,
    "get_game_modes",
    "GameMode",
    # modules,
    "Module",
    "get_modules",
    # player,
    "Player",
    "PlayerStatsMode",
    "PlayerStats",
    # ship
    "get_ships",
    "Ship",
    "ShipProfile",
    "ShipFit",
    # transformers
    "clan_transform",
    "mode_transform",
    "player_transform",
    "ship_transform",
]
