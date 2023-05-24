"""Information related to Players from the Wows API"""
from __future__ import annotations

import datetime
import logging

import aiohttp
from pydantic import BaseModel
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
    #   "pvp",  PVP is included by default.
    "pvp_div2",
    "pvp_div3",
    "pvp_solo",
    "rank_div2",
    "rank_div3",
    "rank_solo",
]


async def fetch_player_stats(
    players: list[PartialPlayer],
) -> list[PlayerStats]:
    """Fetch Player Stats from API"""
    ids = ", ".join([str(i.account_id) for i in players][:100])
    parmas = {"application_id": WG_ID, "account_id": ids}

    url = PLAYER_STATS.replace("%%", players[0].region.domain)

    modes = MODE_STRINGS.copy()
    extra = ", ".join(f"statistics.{i}" for i in modes)
    parmas.update({"extra": extra})

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=parmas) as resp:
            if resp.status != 200:
                err = await resp.text()
                logger.error("%s on %s -> %s", resp.status, url, err)
                raise ConnectionError()
            data = await resp.json()

    return [PlayerStats.parse_obj(i) for i in data.pop("data").values()]


async def fetch_player_ship_stats(
    player: PartialPlayer, ship: Ship | None = None
) -> dict[str, PlayerShipStats]:
    """Get stats for a player in a specific ship"""
    url = PLAYER_STATS_SHIP.replace("%%", player.region.domain)

    params = {
        "application_id": WG_ID,
        "account_id": player.account_id,
        "extra": ", ".join(MODE_STRINGS),
    }
    if ship is not None:
        params.update({"ship_id": ship.ship_id})

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                logger.error(resp.status, await resp.text())
            data = await resp.json()

    data = data["data"][str(player.account_id)]

    statistics: dict[str, PlayerShipStats] = {}
    for i in data:
        statistics.update({i["ship_id"]: PlayerShipStats(**i)})
    return statistics


class PartialPlayer(BaseModel):
    """A World of Warships player."""

    account_id: int
    nickname: str

    clan: PlayerClanData | None = None

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


class ModeArmamentStats(BaseModel):
    """A player's stats for a specific armament within a gamemode"""

    frags: int
    hits: int | None
    max_frags_battle: int | None
    max_frags_ship_id: int | None
    shots: int | None


class ModeBattleStats(BaseModel):
    """Generic Container for all API Data"""

    battles: int  # Total Number of Battles
    survived_battles: int
    survived_wins: int
    wins: int
    xp: int  # pylint: disable=C0103

    art_agro: int | None  # Potential Damage
    capture_points: int | None  # Sum of Below x2
    control_captured_points: int | None  # Same
    control_dropped_points: int | None  # Defended
    damage_dealt: int | None
    damage_scouting: int | None  # Spotting Damage
    damage_to_buildings: int | None  # Dead
    draws: int | None  # Draws
    dropped_capture_points: int | None  # ????
    frags: int | None  # Kills
    losses: int  # Losses
    max_damage_dealt: int | None
    max_damage_dealt_ship_id: int | None
    max_damage_dealt_to_buildings: int | None
    max_damage_dealt_to_buildings_ship_id: int | None
    max_damage_scouting: int | None
    max_frags_battle: int | None
    max_frags_ship_id: int | None
    max_planes_killed: int | None
    max_planes_killed_ship_id: int | None
    max_scouting_damage_ship_id: int | None
    max_ships_spotted: int | None
    max_ships_spotted_ship_id: int | None
    max_suppressions_count: int | None
    max_suppressions_ship_id: int | None
    max_total_agro: int | None  # Potential Damage
    max_total_agro_ship_id: int | None
    max_xp: int | None
    max_xp_ship_id: int | None
    planes_killed: int | None
    ships_spotted: int | None
    suppressions_count: int | None
    team_capture_points: int | None  # Team Total Cap Points earned
    team_dropped_capture_points: int | None  # Team Defence Points Earned
    torpedo_agro: int | None

    # Garbage
    battles_since_510: int | None
    battles_since_512: int | None

    # Subdicts
    aircraft: ModeArmamentStats | None
    main_battery: ModeArmamentStats | None
    ramming: ModeArmamentStats | None
    second_battery: ModeArmamentStats | None
    torpedoes: ModeArmamentStats | None
    wins_by_tasks: dict[int, int] | None

    @property
    def potential_damage(self) -> int:
        return (self.art_agro or 0) + (self.torpedo_agro or 0)


class PlayerShipStats(BaseModel):
    """Statistics for a player on a specific ship"""

    account_id: int
    battles: int
    distance: int
    last_battle_time: int
    ship_id: int
    updated_at: int

    # Player's private stats.
    private: None

    # Various mode stats
    club: ModeBattleStats | None
    oper_div: ModeBattleStats | None
    oper_div_hard: ModeBattleStats | None
    oper_solo: ModeBattleStats | None
    pve: ModeBattleStats | None
    pve_div2: ModeBattleStats | None
    pve_div3: ModeBattleStats | None
    pve_solo: ModeBattleStats | None
    pvp: ModeBattleStats
    pvp_div2: ModeBattleStats | None
    pvp_div3: ModeBattleStats | None
    pvp_solo: ModeBattleStats | None
    rank_solo: ModeBattleStats | None
    rank_div2: ModeBattleStats | None
    rank_div3: ModeBattleStats | None


class PlayerBattleStatistics(BaseModel):
    """Stats retrieved from the Player Statistics Endpoint"""

    distance: int
    battles: int

    oper_div: ModeBattleStats
    oper_div_hard: ModeBattleStats
    oper_solo: ModeBattleStats
    pve: ModeBattleStats
    pve_div2: ModeBattleStats
    pve_div3: ModeBattleStats
    pve_solo: ModeBattleStats
    pvp: ModeBattleStats
    pvp_div2: ModeBattleStats
    pvp_div3: ModeBattleStats
    pvp_solo: ModeBattleStats
    rank_div2: ModeBattleStats
    rank_div3: ModeBattleStats
    rank_solo: ModeBattleStats


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
