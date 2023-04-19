"""Information related to Players from the Wows API"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

import aiohttp
from pydantic import BaseModel  # pylint: disable = no-name-in-module
from .wg_id import WG_ID
from .enums import Region
from .clan import Clan, PartialClan
from .warships import Ship

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


async def fetch_stats(players: list[PartialPlayer]) -> list[PlayerStats]:
    """Fetch Player Stats from API"""
    ids = ", ".join([str(i.account_id) for i in players][:100])
    parmas = {"application_id": WG_ID, "account_id": ids}

    url = PLAYER_STATS.replace("%%", players[0].region.domain)

    modes = MODE_STRINGS.copy()
    modes.remove("pvp")
    extra = ", ".join(f"statistics.{i}" for i in modes)
    parmas.update({"extra": extra})

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=parmas) as resp:
            if resp.status != 200:
                err = await resp.text()
                logger.error("%s on %s -> %s", resp.status, url, err)
                raise ConnectionError()
            data = await resp.json()

    return [PlayerStats(**i) for i in data.pop("data").values()]


class PartialPlayer(BaseModel):
    """A World of Warships player."""

    account_id: int
    nickname: str

    clan: Optional[PlayerClanData] = None

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

        statistics = PlayerStats(**data.pop("statistics"))
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
        dom = {Region.NA: "na.", Region.SEA: "asia.", Region.EU: ""}[
            self.region
        ]
        name = self.nickname
        acc_id = self.account_id
        return f"https://{dom}wows-numbers.com/player/{acc_id},{name}/"


class PlayerClanData(BaseModel):
    """Information about the player's current clan"""

    account_id: int
    account_name: str
    clan_id: int
    joined_at: datetime.datetime
    role: str

    clan: PartialClan

    @property
    def tag(self) -> str:
        """Fetch tag from parent"""
        return self.clan.tag

    async def fetch_details(self) -> Clan:
        """Fetch clan details from the parent"""
        return await self.clan.fetch_details()


class PlayerModeArmamentStats(BaseModel):
    """A player's stats for a specific armament within a gamemode"""

    frags: int
    hits: Optional[int]
    max_frags_battle: Optional[int]
    max_frags_ship_id: Optional[int]
    shots: Optional[int]


class ModeStats(BaseModel):
    """Generic Container for all API Data"""

    battles: int  # Total Number of Battles
    survived_battles: int
    survived_wins: int
    wins: int
    xp: int  # pylint: disable=C0103

    art_agro: Optional[int]  # Potential Damage
    capture_points: Optional[int]  # Sum of Below x2
    control_captured_points: Optional[int]  # Same
    control_dropped_points: Optional[int]  # Defended
    damage_dealt: Optional[int]
    damage_scouting: Optional[int]  # Spotting Damage
    damage_to_buildings: Optional[int]  # Dead
    draws: Optional[int]  # Draws
    dropped_capture_points: Optional[int]  # ????
    frags: Optional[int]  # Kills
    losses: int  # Losses
    max_damage_dealt: Optional[int]
    max_damage_dealt_ship_id: Optional[int]
    max_damage_dealt_to_buildings: Optional[int]
    max_damage_dealt_to_buildings_ship_id: Optional[int]
    max_damage_scouting: Optional[int]
    max_frags_battle: Optional[int]
    max_frags_ship_id: Optional[int]
    max_planes_killed: Optional[int]
    max_planes_killed_ship_id: Optional[int]
    max_scouting_damage_ship_id: Optional[int]
    max_ships_spotted: Optional[int]
    max_ships_spotted_ship_id: Optional[int]
    max_suppressions_count: Optional[int]
    max_suppressions_ship_id: Optional[int]
    max_total_agro: Optional[int]  # Potential Damage
    max_total_agro_ship_id: Optional[int]
    max_xp: Optional[int]
    max_xp_ship_id: Optional[int]
    planes_killed: Optional[int]
    ships_spotted: Optional[int]
    suppressions_count: Optional[int]
    team_capture_points: Optional[int]  # Team Total Cap Points earned
    team_dropped_capture_points: Optional[
        int
    ]  # Team Total Defence Points Earned
    torpedo_agro: Optional[int]

    # Garbage
    battles_since_510: Optional[int]
    battles_since_512: Optional[int]

    # Subdicts
    aircraft: Optional[PlayerModeArmamentStats]
    main_battery: Optional[PlayerModeArmamentStats]
    ramming: Optional[PlayerModeArmamentStats]
    second_battery: Optional[PlayerModeArmamentStats]
    torpedoes: Optional[PlayerModeArmamentStats]
    wins_by_tasks: Optional[dict[int, int]]

    @property
    def potential_damage(self) -> int:
        return (self.art_agro or 0) + (self.torpedo_agro or 0)


class PlayerBattleStatistics(BaseModel):
    """Stats retrieved from the Player Statistics Endpoint"""

    distance: int
    battles: int

    oper_div: ModeStats
    oper_div_hard: ModeStats
    oper_solo: ModeStats
    pve: ModeStats
    pve_div2: ModeStats
    pve_div3: ModeStats
    pve_solo: ModeStats
    pvp: ModeStats
    pvp_div2: ModeStats
    pvp_div3: ModeStats
    pvp_solo: ModeStats
    rank_div2: ModeStats
    rank_div3: ModeStats
    rank_solo: ModeStats


class PlayerStats(BaseModel):
    """Generics for a Player"""

    account_id: int
    created_at: int
    hidden_profile: bool
    last_battle_time: int
    leveling_tier: int  # e.g. 17
    leveling_points: int  # 28887
    logout_at: int
    nickname: str
    karma: None  # requires Oauth
    private: None  # requires Oauth
    statistics: PlayerBattleStatistics
    updated_at: int
