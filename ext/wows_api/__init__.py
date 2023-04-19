"""Utilities to work with the world of warhips API"""
from .clan import (
    Clan,
    ClanBattleSeason,
    ClanBattleWinner,
    ClanLeaderboardStats,
    ClanMember,
    ClanMemberVortexData,
    ClanSeasonStats,
    ClanVortexData,
    PartialClan,
    PlayerCBStats,
    get_cb_leaderboard,
    get_cb_seasons,
    get_cb_winners,
    get_clan_details,
    get_clan_vortex_data,
    get_member_vortex,
)
from .emojis import (
    ARTILLERY_EMOJI,
    AUXILIARY_EMOJI,
    DIVE_BOMBER_EMOJI,
    ENGINE_EMOJI,
    HULL_EMOJI,
    FIRE_CONTROL_EMOJI,
    ROCKET_PLANE_EMOJII,
    TORPEDO_PLANE_EMOJI,
    TORPEDOES_EMOJI,
)
from .enums import Map, Nation, Region
from .gamemode import GameMode, get_game_modes
from .modules import Module, fetch_modules
from .player import PartialPlayer, PlayerStats, ModeStats, fetch_stats
from .transformers import (
    clan_transform,
    class_transform,
    mode_transform,
    player_transform,
    region_transform,
    ship_transform,
)
from .warships import Ship, ShipFit, ShipProfile, get_ships

__all__ = [
    # clan
    "get_cb_seasons",
    "get_cb_leaderboard",
    "get_cb_winners",
    "get_clan_details",
    "get_clan_vortex_data",
    "get_member_vortex",
    "PartialClan",
    "ClanBattleSeason",
    "ClanBattleWinner",
    "ClanSeasonStats",
    "ClanLeaderboardStats",
    "PlayerCBStats",
    "Clan",
    "ClanVortexData",
    "ClanMember",
    "ClanMemberVortexData",
    # emojis
    "ARTILLERY_EMOJI",
    "AUXILIARY_EMOJI",
    "DIVE_BOMBER_EMOJI",
    "ENGINE_EMOJI",
    "HULL_EMOJI",
    "FIRE_CONTROL_EMOJI",
    "ROCKET_PLANE_EMOJII",
    "TORPEDO_PLANE_EMOJI",
    "TORPEDOES_EMOJI",
    # enums
    "Map",
    "Nation",
    "Region",
    # gamemode,
    "get_game_modes",
    "GameMode",
    # modules,
    "Module",
    "fetch_modules",
    # player,
    "PartialPlayer",
    "ModeStats",
    "PlayerStats",
    "fetch_stats",
    # ship
    "get_ships",
    "Ship",
    "ShipProfile",
    "ShipFit",
    # transformers
    "clan_transform",
    "class_transform",
    "mode_transform",
    "player_transform",
    "region_transform",
    "ship_transform",
]
