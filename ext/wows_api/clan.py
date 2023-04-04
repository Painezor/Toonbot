"""Data realted to the fetching of World of Warships Clans from the API"""
from __future__ import annotations

import dataclasses
import datetime
import logging

import aiohttp
from .enums import League, Region
from .wg_id import WG_ID


# TODO: Clan Battle Season objects for Images for Leaderboard.


logger = logging.getLogger("api.clan")


CB_STATS = "https://clans.worldofwarships.%%/api/members/CLAN_ID/"
VORTEX_INFO = "https://clans.worldofwarships.%%/api/clanbase/CLAN_ID/claninfo/"
WINNERS = "https://clans.worldofwarships.eu/api/ladder/winners/"


__all__ = []


async def get_cb_winners() -> dict[int, ClanLeaderboardStats]:
    """Get Winners for all Clan Battle Seasons"""
    async with aiohttp.ClientSession() as session:
        async with session.get(WINNERS) as resp:
            if resp.status != 200:
                logger.error("%s %s %s", resp.status, resp.reason, resp.url)
        data = await resp.json()

    winners = data.pop("winners")
    logger.info("remaining data %s", data)

    # k is season - int
    # val is dict
    for k, val in winners.copy().items():
        winners[k] = ClanLeaderboardStats(val)
    return winners


class ClanBuilding:
    """A World of Warships Clan Building"""


@dataclasses.dataclass
class ClanSeasonStats:
    """A Single Clan's statistics for a Clan Battles season"""

    clan: Clan

    season_number: int

    battles_count: int
    wins_count: int

    public_rating: int
    league: League
    division: int

    max_division: int
    max_rating: int
    max_league: League
    longest_winning_streak: int

    last_win_at: datetime.datetime

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k in ["max_league", "final_league"]:
                val = next(i for i in League if i.value == val)
            setattr(self, k, val)


@dataclasses.dataclass
class ClanLeaderboardStats:
    """Stats from the Clan Leaderboard Endpoint"""

    id: int  # pylint: disable=C0103
    tag: str
    name: str
    battles_count: int
    is_clan_disbanded: bool
    last_battle_at: datetime.datetime
    leading_team_number: int
    league: League
    public_rating: int
    rank: int
    season_number: int

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "league":
                val = next(i for i in League if i.value == val)
            elif k in ["last_battle_at"]:
                val = datetime.datetime.strptime(val, "%Y-%m-%d %H:%M:%S%z")
            setattr(self, k, val)


@dataclasses.dataclass
class PlayerCBStats:
    """A Player's Clan Battle Stats for a season"""

    win_rate: float
    battles_count: int
    damage_per_battle: float
    frags_per_battle: float

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)


@dataclasses.dataclass
class ClanMemberVortexData:
    """A member's data, from Vortex API"""

    average_damage: int
    average_kills: float
    average_xp: int
    battles: int
    battles_per_day: int
    is_banned: bool
    is_online: bool
    joined_clan_at: datetime.datetime
    nickname: str
    win_rate: float

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "joined_clan_at":
                val = datetime.datetime.strptime(val, "%Y-%m-%dT%H:%M:%S%z")
            setattr(self, k, val)


@dataclasses.dataclass
class ClanMember:
    """A Clan Member From the clans API"""

    account_id: int
    account_name: int
    joined_at: datetime.datetime
    role: str

    def __init__(self, data: dict) -> None:
        for k, value in data.items():
            setattr(self, k, value)


@dataclasses.dataclass
class ClanDetails:
    """Fetched from Clan Details EndPoint"""

    clan_id: int
    created_at: datetime.datetime
    creator_id: int
    creator_name: str
    description: str
    is_clan_disbanded: bool
    leader_id: int
    leader_name: str
    members_count: int
    members_ids: list[int]
    name: str
    old_name: str
    old_tag: str
    renamed_at: datetime.datetime
    tag: str
    updated_at: datetime.datetime

    members: list[ClanMember] = []

    def __init__(self, data: dict) -> None:
        for k, values in data.items():

            if k == "members":
                self.members = [ClanMember(i) for i in values.values()]

            else:
                setattr(self, k, values)


@dataclasses.dataclass
class ClanVortexData:
    """Data about a clan from the Vortex Endpoint"""

    # Clan Buildings.
    academy: list
    coal_yard: list
    design_department: list
    dry_dock: list
    headquarters: list
    paragon_yard: list
    shipbuilding_factory: list
    steel_yard: list
    treasury: list
    university: list

    # Clan Battles Data
    battles_count: int
    colour: int
    current_winning_streak: int
    division: int
    last_battle_at: datetime.datetime
    leading_team_number: int
    league: League
    max_division: int
    max_league: League
    max_position: int
    max_public_rating: int
    max_winning_streak: int
    public_rating: int
    season_number: int
    total_battles_played: int
    wins_count: int

    # Misc
    is_banned: bool

    def __init__(self, data: dict) -> None:
        ladder = data.pop("wows_ladder")  # This info we care about.

        for k, val in ladder:
            if k in ["last_battle_at", "last_win_at"]:
                val = datetime.datetime.strptime(val, "%Y-%m-%dT%H:%M:%S%z")
            elif k in ["league", "max_league"]:
                val = next(i for i in League if val == i)
            elif k == "ratings":
                _v = []
                for i in val:
                    _v.append(ClanSeasonStats(i))
                val = _v
            elif k == "buildings":
                for _k, _v in val.items():
                    setattr(self, _k, _v["modifiers"])
            setattr(self, k, val)

    @property
    def coal_bonus(self) -> str:
        """Clan Base's bonus Coal"""
        return {1: "No Bonus", 2: "+5% Coal", 3: "+7% Coal", 4: "+10% Coal"}[
            len(self.coal_yard)
        ]

    @property
    def max_members(self) -> int:
        """Get maximum number of clan members"""
        num = len(self.headquarters)
        return {1: 30, 2: 35, 3: 40, 4: 45, 5: 50}[num]

    @property
    def purchase_cost_discount(self) -> str:
        """Clan's Ship Purchase Cost Discount"""
        return {
            1: "No Bonus",
            2: "-10% Cost of ships up to Tier IV",
            3: "-10% Cost of ships up to Tier VIII",
            4: "-10% Cost of ships up to Tier X",
            5: "-12% Cost of ships up to Tier X",
            6: "-14% Cost of ships up to Tier X",
            7: "-15% Cost of ships up to Tier X",
        }[len(self.shipbuilding_factory)]

    @property
    def steel_bonus(self) -> str:
        """Clan Base's bonus Steel"""
        return {
            1: "No Bonus",
            2: "+5% Steel",
            3: "+7% Steel",
            4: "+10% Steel",
        }[len(self.steel_yard)]

    @property
    def service_cost_bonus(self) -> str:
        """Clan Base's bonus Service Cost Reduction"""
        return {
            1: "No Bonus",
            2: "-5% Service Cost (up to Tier IV)",
            3: "-5% Service Cost (up to Tier VIII)",
            4: "-5% Service Cost (up to Tier IX)",
            5: "-5% Service Cost (up to Tier X)",
            6: "-7% Service Cost (up to Tier X)",
            7: "-10% Service Cost (up to Tier X)",
        }[len(self.dry_dock)]

    @property
    def commander_xp_bonus(self) -> str:
        """Clan's Bonus to XP Earned"""
        return {
            1: "No Bonus",
            2: "+2% Commander XP",
            3: "+4% Commander XP",
            4: "+6% Commander XP",
            5: "+8% Commander XP",
            6: "+10% Commander XP",
        }[len(self.academy)]

    @property
    def free_xp_bonus(self) -> str:
        """Clan's Bonus to Free XP Earned"""
        return {
            1: "No Bonus",
            2: "+10% Free XP up to Tier VI",
            3: "+10% Free XP up to Tier VIII",
            4: "+10% Free XP up to Tier X",
            5: "+15% Free XP up to Tier X",
            6: "+20% Free XP up to Tier X",
            7: "+25% Free XP up to Tier X",
        }[len(self.design_department)]

    @property
    def research_points_bonus(self) -> str:
        """Get the Clan's Bonus to Research Points earned"""
        return {
            1: "No Bonus",
            2: "+1% Research Points",
            3: "+3% Research Points",
            4: "+5% Research Points",
        }[len(self.paragon_yard)]

    @property
    def xp_bonus(self) -> str:
        """Get the Clan's Bonus to XP earned"""
        return {
            1: "No Bonus",
            2: "+2% XP up to Tier VI",
            3: "+2% Up to Tier VIII",
            4: "+2% Up to Tier X",
            5: "+3% Up to Tier X",
            6: "+4% Up to Tier X",
            7: "+5% Up to Tier X",
        }[len(self.university)]

    @property
    def max_rating_name(self) -> str:
        """Is Alpha or Bravo their best rating?"""
        return {1: "Alpha", 2: "Bravo"}[self.leading_team_number]

    @property
    def cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        if self.public_rating:
            return "Rating Not Found"

        if self.league == League.HURRICANE:
            return f"Hurricane ({self.public_rating - 2200} points)"
        else:
            league = self.league.alias
            div = self.division * "I" if self.division else ""
            return f"{league} {div} ({self.public_rating // 100} points)"

    @property
    def max_cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        if self.max_league == League.HURRICANE:
            return f"Hurricane ({self.max_public_rating - 2200} points)"
        league = self.max_league.alias
        div = self.max_division * "I"
        return f"{league} {div} ({self.max_public_rating // 100} points)"

    @property
    def treasury_rewards(self) -> str:
        """Get a list of available treasury operations for the clan"""
        rewards = [
            "Allocation of resources",
            "More Resources Bundles",
            "Try Your Luck Bundles",
            "Supercontainer Bundles",
            "'additional' bundles",
        ]
        return ", ".join(rewards[: len(self.treasury)])


@dataclasses.dataclass
class Clan:
    """A World of Warships clan."""

    clan_id: int
    created_at: datetime.datetime
    members_count: int
    name: str
    tag: str

    def __init__(self, data: dict):

        for k, val in data.items():
            setattr(self, k, val)

    async def fetch_details(self) -> ClanDetails:
        """Fetch clan information."""
        cid = self.clan_id
        params = {"application_id": WG_ID, "clan_id": cid, "extra": "members"}
        domain = self.region.domain
        url = f"https://api.worldofwarships.{domain}/wows/clans/info/"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise ConnectionError(f"{resp.status} {await resp.text()}")
                return ClanDetails(await resp.json())

    async def fetch_vortex_data(self) -> ClanVortexData:
        """Get clan data from the vortex api"""
        url = VORTEX_INFO.replace("%%", self.region.domain)
        url = url.replace("CLAN_ID", str(self.clan_id))

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("[%s] %s: %s", resp.status, resp.reason, url)
            data = await resp.json()

        return ClanVortexData(data.pop("clanview"))

    @property
    def title(self) -> str:
        """[Tag] and Name of clan"""
        return f"[{self.tag}] {self.name}"

    @property
    def region(self) -> Region:
        """Get a Region object based on the clan's ID number."""
        if 0 < self.clan_id < 500000000:
            raise ValueError("CIS is no longer supported")
        elif 500000000 < self.clan_id < 999999999:
            return Region.EU
        elif 1000000000 < self.clan_id < 1999999999:
            return Region.NA
        else:
            return Region.SEA

    async def player_cb_stats(self, season: int) -> list[PlayerCBStats]:
        """Attempt to fetch clan battle stats for members"""
        url = CB_STATS.replace("%%", self.region.domain)
        url = url.replace("CLAN_ID", str(self.clan_id))
        url += "?battle_type=cvc"
        params = {"battle_type": "cvc", "season": season}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    err = f"{resp.status} {await resp.text()} on {url}"
                    raise ConnectionError(err)
                season_stats = await resp.json()

        logging.info("DEBUG: Season Stats\n%s", season_stats)
        return [PlayerCBStats(i) for i in season_stats["items"]]

    async def get_members_vortex(self) -> list[ClanMemberVortexData]:
        """Attempt to fetch clan battle stats for members"""
        dom = self.region.domain
        cid = self.clan_id
        url = f"https://clans.worldofwarships.{dom}/api/members/{cid}/"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    err = "Error %s fetching %s (%s)"
                    txt = await resp.text()
                    raise ConnectionError(err, resp.status, url, txt)
                data = await resp.json()

        return [ClanMemberVortexData(i) for i in data.pop("items")]
