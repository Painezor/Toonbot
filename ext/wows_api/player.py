"""Information related to Players from the Wows API"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import typing

import aiohttp
import discord
from .wg_id import WG_ID
from .enums import Region
from .clan import Clan
from .warships import Ship

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]

logger = logging.getLogger("api.player")

PLAYER_STATS = "https://api.worldofwarships.%%/wows/account/info/"
PLAYER_STATS_SHIP = "https://api.worldofwarships.%%/wows/ships/stats/"

# For Generation of Embeds? Why is this here ...
ARMAMENT_TYPES = [
    "aircraft",
    "main_battery",
    "ramming",
    "second_battery",
    "torpedoes",
]

# For fetching player mode stats
MODE_STRINGS = [
    "oper_div",
    "oper_div_hard",
    "oper_solo",
    "pve",
    "pve_div2",
    "pve_div3",
    "pve_solo",
    "pvp",
    "pvp_div2",
    "pvp_div3",
    "pvp_solo",
    "rank_div2",
    "rank_div3",
    "rank_solo",
]

#
#         Player Personal Data Endpoint.
#         self.created_at: datetime.datetime  # Player Account creation
#         self.hidden_profile: bool  # Player Stats are hidden?
#         self.karma: int  # Player Karma
#         self.last_battle_time: datetime.datetime
#         self.levelling_points: int  # Player level - Garbage
#         self.levelling_tier: int  # Same.
#         self.logout_at: datetime.datetime
#         self.stats_updated_at: datetime.datetime

#         # CB Season Stats
#         self.clan: typing.Optional[clan.Clan] = None

#         # Keyed By Season ID.
#         self.clan_battle_stats: dict[int, PlayerCBStats] = {}


@dataclasses.dataclass
class Player:
    """A World of Warships player."""

    account_id: int
    nickname: str

    clan_data: typing.Optional[PlayerClanData] = None

    def __init__(self, data: dict) -> None:
        # Player Search Endpoint
        for k, val in data.items():
            setattr(self, k, val)

    async def fetch_stats(self) -> PlayerStats:
        """Fetch Player Stats from API"""
        parmas = {"application_id": WG_ID, "account_id": self.account_id}

        url = PLAYER_STATS.replace("%%", self.region.domain)

        extra = ", ".join(f"statistics.{i}" for i in MODE_STRINGS)
        parmas.update({"extra": extra})

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=parmas) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logger.error("%s on %s -> %s", resp.status, url, err)
                    raise ConnectionError()
            data = await resp.json()

        statistics = PlayerStats(data.pop("statistics"))
        for k, value in data:
            if k == "private":
                continue
            else:
                setattr(self, k, value)
        return statistics

    async def fetch_ship_stats(self, ship: Ship) -> PlayerStats:
        """Get stats for a player in a specific ship"""
        url = PLAYER_STATS_SHIP.replace("%%", self.region.domain)
        params = {
            "application_id": WG_ID,
            "account_id": self.account_id,
            "ship_id": ship.ship_id,
            "extra": ", ".join(MODE_STRINGS),
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise ConnectionError(resp.status)
                data = await resp.json()

        statistics = PlayerStats(data.pop("statistics"))
        return statistics

    @property
    def region(self) -> Region:
        """Get a Region object based on the player's ID number."""
        if 0 < self.account_id < 500000000:
            raise ValueError("CIS Is no longer supported.")
        elif 500000000 < self.account_id < 999999999:
            return Region.EU
        elif 1000000000 < self.account_id < 1999999999:
            return Region.NA
        else:
            return Region.SEA

    @property
    def community_link(self) -> str:
        """Get a link to this player's community page."""
        dom = self.region.domain
        uid = self.account_id
        nom = self.nickname
        return f"https://worldofwarships.{dom}/community/accounts/{uid}-{nom}/"

    @property
    def wows_numbers(self) -> str:
        """Get a link to this player's wows_numbers page."""
        dom = {Region.NA: "na", Region.SEA: "asia", Region.EU: ""}[self.region]
        name = self.nickname
        acc_id = self.account_id
        return f"https://{dom}.wows-numbers.com/player/{acc_id},{name}/"


@dataclasses.dataclass
class PlayerClanData:
    """Information about the player's current clan"""

    account_id: int
    account_name: int
    clan_id: int
    joined_at: datetime.datetime
    role: str

    clan: Clan

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "clan":
                val = Clan(val)
            setattr(self, k, val)


@dataclasses.dataclass
class PlayerStats:
    """Generics for a Player"""

    oper_div: PlayerStatsMode
    oper_div_hard: PlayerStatsMode
    oper_solo: PlayerStatsMode
    pve: PlayerStatsMode
    pve_div2: PlayerStatsMode
    pve_div3: PlayerStatsMode
    pve_solo: PlayerStatsMode
    pvp: PlayerStatsMode
    pvp_div2: PlayerStatsMode
    pvp_div3: PlayerStatsMode
    pvp_solo: PlayerStatsMode

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "club":
                continue  # Dead data.

            if k in MODE_STRINGS:
                setattr(self, k, PlayerStatsMode(val))
            else:
                setattr(self, k, val)


@dataclasses.dataclass
class PlayerStatsMode:
    """Generic Container for all API Data"""

    art_agro: int  # Potential Damage
    battles: int  # Total Number of Battles
    capture_points: int  # Sum of Below x2
    control_capture_points: int  # Same
    control_dropped_points: int  # Defended
    damage_dealt: int
    damage_scouting: int  # Spotting Damage
    damage_to_buildings: int  # Dead
    draws: int  # Draws
    dropped_capture_points: int  # ????
    frags: int  # Kills
    losses: int  # Losses
    max_damage_dealt: int
    max_damage_dealt_ship_id: int
    max_damage_dealt_to_buildings: int
    max_damage_scouting: int
    max_frags_battle: int
    max_frags_ship_id: int
    max_planes_killed: int
    max_planes_killed_ship_id: int
    max_scouting_damage_ship_id: int
    max_ships_spotted: int
    max_ships_spotted_ship_id: int
    max_suppressions: int
    max_suppressions_ship_id: int
    max_total_agro: int  # Potential Damage
    max_total_agro_ship_id: int
    max_xp: int
    max_xp_ship_id: int
    planes_killed: int
    ships_spotted: int
    suppressions_count: int
    survived_battles: int
    survived_wins: int
    team_capture_points: int  # Team Total Cap Points earned
    team_dropped_capture_points: int  # Team Total Defence Points Earned
    torpedo_agro: int
    wins: int
    xp: int  # pylint: disable=C0103

    # Subdicts
    aircraft: PlayerModeArmamentStats
    main_battery: PlayerModeArmamentStats
    ramming: PlayerModeArmamentStats
    second_battery: PlayerModeArmamentStats
    torpedoes: PlayerModeArmamentStats

    # Operations fucky.
    wins_by_tasks: typing.Optional[dict] = None

    def __init__(self, data: dict) -> None:
        for k, value in data.items():
            if k in ARMAMENT_TYPES:
                setattr(self, k, PlayerModeArmamentStats(value))
            else:
                setattr(self, k, value)

    @property
    def potential_damage(self) -> int:
        """Combined sum of art_agro and torpedo_agro"""
        return self.art_agro + self.torpedo_agro


@dataclasses.dataclass
class PlayerModeArmamentStats:
    """A player's stats for a specific armament within a gamemode"""

    hits: int
    frags: int
    max_frags_battle: int
    max_frags_ship_id: int
    shots: int

    def __init__(self, data: dict) -> None:
        for k, value in data.items():
            setattr(self, k, value)
