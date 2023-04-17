"""Data realted to the fetching of World of Warships Clans from the API"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Optional

import aiohttp
from pydantic import BaseModel  # pylint: disable=no-name-in-module
from .enums import Region
from .wg_id import WG_ID


logger = logging.getLogger("api.clan")


CLAN_DETAILS = "https://api.worldofwarships.%%/wows/clans/info/"
CB_STATS = "https://clans.worldofwarships.%%/api/members/CLAN_ID/"
CB_SEASON_INFO = "https://api.worldofwarships.eu/wows/clans/season/"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
LEADERBOARD = "https://clans.worldofwarships.eu/api/ladder/structure/"
VORTEX_INFO = "https://clans.worldofwarships.%%/api/clanbase/CLAN_ID/claninfo/"
WINNERS = "https://clans.worldofwarships.eu/api/ladder/winners/"


__all__ = []


async def get_clan_details(clan_id: int, region: Region) -> Clan:
    """Feetch a Clan's Details"""
    params = {"application_id": WG_ID, "clan_id": clan_id, "extra": "members"}

    url = CLAN_DETAILS.replace("%%", region.domain)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
    return Clan(**data.pop("data")[str(clan_id)])


async def get_clan_vortex_data(clan_id: int, region: Region) -> ClanVortexData:
    """Get clan data from the vortex api"""
    url = VORTEX_INFO.replace("%%", region.domain)
    url = url.replace("CLAN_ID", str(clan_id))

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

    return ClanVortexData(**data.pop("clanview"))


async def get_member_vortex(
    clan: int, region: Region
) -> list[ClanMemberVortexData]:
    """Attempt to fetch clan battle stats for members"""
    url = f"https://clans.worldofwarships.{region.domain}/api/members/{clan}/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

    return [ClanMemberVortexData(**i) for i in data.pop("items")]


async def get_cb_leaderboard(
    season: Optional[int] = None, region: Optional[Region] = None
) -> list[ClanLeaderboardStats]:
    """Get the leaderboard for a clan battle season"""
    params: dict[str, Any] = dict()

    # league: int, 0 = Hurricane.
    # division: int, 1-3

    if season is not None:
        params.update({"season": str(season)})

    params.update({"realm": region.realm if region is not None else "global"})
    async with aiohttp.ClientSession() as session:
        async with session.get(LEADERBOARD, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            return [ClanLeaderboardStats(**i) for i in await resp.json()]


async def get_cb_seasons(language: str = "en") -> list[ClanBattleSeason]:
    """Retrieve a list of ClanBattleSeason objects from the API"""
    params = {"application_id": WG_ID, language: language}

    async with aiohttp.ClientSession() as session:
        async with session.get(CB_SEASON_INFO, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)

            data = await resp.json()
            count = data.pop("meta")["count"]
            logger.info("Fetched %s Clan Battle Seasons", count)
            data = data.pop("data")

    output: list[ClanBattleSeason] = []
    for k, val in data.items():  # Key is useless
        if len(str(k)) == 3:
            continue  # Discard Fucked shit.
        output.append(ClanBattleSeason(**val))
    return output


async def get_cb_winners() -> dict[int, list[ClanBattleWinner]]:
    """Get Winners for all Clan Battle Seasons"""
    async with aiohttp.ClientSession() as session:
        async with session.get(WINNERS) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            data = await resp.json()

    winners = data.pop("winners")

    # k is season - int
    # val is dict
    for k, val in winners.items():
        winners[k] = [ClanBattleWinner(**i) for i in val]
    return winners


class ClanBattleLeague(BaseModel):
    """A League in a Clan Battle Season"""

    color: str
    icon: str
    name: str

    @property
    def emote(self) -> str:
        """Match a discord emote to the league's name"""
        return {
            "Hurricane League": "<:Hurricane:990599761574920332>",
            "Typhoon League": "<:Typhoon:990599751584067584>",
            "Storm League": "<:Storm:990599740079104070>",
            "Gale League": "<:Gale:990599200905527329>",
            "Squall League": "<:Squall:990597783817965568>",
        }[self.name]

    @property
    def value(self) -> int:
        """Convert League name to value"""
        return {
            "Hurricane League": 0,
            "Typhoon League": 1,
            "Storm League": 2,
            "Gale League": 3,
            "Squall League": 4,
        }[self.name]


class ClanBattleSeason(BaseModel):
    """Clan Battle Leagues"""

    division_points: int
    finish_time: datetime.datetime
    name: str
    season_id: int
    ship_tier_max: int
    ship_tier_min: int
    start_time: datetime.datetime

    leagues: list[ClanBattleLeague]

    @property
    def top_league(self) -> ClanBattleLeague:
        """Hackjob to get the top league of a season"""
        for j in [
            "Hurricane League",
            "Typhoon Leauge",
            "Storm League",
            "Gale League",
            "Squall League",
        ]:
            for i in self.leagues:
                if i.name == j:
                    return i

        vals = [i.name for i in self.leagues]
        logger.error("No acceptable League found in %s", vals)
        raise AttributeError


class ClanSeasonStats(BaseModel):
    """A Single Clan's statistics for a Clan Battles season"""

    clan: PartialClan

    season_number: int

    battles_count: int
    wins_count: int

    public_rating: int
    league: str
    division: int

    max_division: int
    max_rating: int
    max_league: str
    longest_winning_streak: int

    last_win_at: datetime.datetime


class ClanBattleWinner(BaseModel):
    """Winner of a Clan Battle Season"""

    clan_id: int
    division_rating: int
    name: str
    league: int
    public_rating: int
    realm: str
    season_id: int
    tag: str


class ClanLeaderboardStats(BaseModel):
    """Stats from the Clan Leaderboard Endpoint"""

    battles_count: int
    color: str
    disbanded: bool
    division: int
    division_rating: int
    hex_color: str
    id: int  # pylint: disable=C0103
    last_battle_at: datetime.datetime
    last_win_at: datetime.datetime
    leading_team_number: int
    league: int
    members_count: int
    name: str
    public_rating: int
    rank: int
    rating_realm: str
    realm: str
    season_number: int
    tag: str


class PlayerCBStats(BaseModel):
    """A Player's Clan Battle Stats for a season"""

    win_rate: float
    battles_count: int
    damage_per_battle: float
    frags_per_battle: float


class ClanRole(BaseModel):
    """A Clan Role"""

    rank: int
    name: str
    order: int


class ClanMemberVortexData(BaseModel):
    """A member's data, from Vortex API"""

    abnormal_results: bool
    # accumulative_clan_resource: None
    battles_count: Optional[int]
    days_in_clan: int
    exp_per_battle: Optional[float]
    frags_per_battle: Optional[float]
    is_banned: bool
    # is_bonus_activated: None
    is_hidden_statistics: bool
    is_press: bool
    # leveling: None
    name: str
    online_status: bool
    profile_link: str
    last_battle_time: int
    damage_per_battle: Optional[float]
    id: int  # pylint: disable= C0103
    rank: int
    role: str
    # season_rank: None
    season_id: int
    wins_percentage: Optional[float]

    # Data is not always present for this value
    battles_per_day: Optional[float] = None


class ClanMember(BaseModel):
    """A Clan Member From the clans API"""

    account_id: int
    account_name: str
    joined_at: datetime.datetime
    role: str


class Clan(BaseModel):
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

    # Parsed Later
    members: list[ClanMember] = []

    @property
    def title(self) -> str:
        """[Tag] Name"""
        return f"[{self.tag}] {self.name}"

    @property
    def region(self) -> Region:
        """Get a Region object based on the clan's ID number."""
        if 0 < self.clan_id < 500000000:
            raise ValueError("CIS is no longer supported")
        if 500000000 < self.clan_id < 999999999:
            return Region.EU
        if 1000000000 < self.clan_id < 1999999999:
            return Region.NA
        return Region.SEA


class ClanBuildings(BaseModel):
    """Generic Container for the clan base's buildings."""

    academy: list[int]
    coal_yard: list[int]
    design_department: list[int]
    dry_dock: list[int]
    headquarters: list[int]
    paragon_yard: list[int]
    shipbuilding_factory: list[int]
    steel_yard: list[int]
    treasury: list[int]
    university: list[int]

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
        """Get the Building's Bonus to XP earned"""
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


class ClanVortexData(BaseModel):
    """Data about a clan from the Vortex Endpoint"""

    clan_buildings: ClanBuildings

    # # Clan Battles Data
    battles_count: int
    color: int
    current_winning_streak: int
    division: int
    division_rating: int
    division_rating_max: int
    initial_public_rating: int
    id: int  # pylint: disable=C0103
    is_best_season_rating: bool
    is_disbanded: bool
    is_qualified: bool
    last_battle_at: Optional[datetime.datetime]
    last_win_at: Optional[datetime.datetime]
    leading_team_number: int
    league: int
    longest_winning_streak: int
    # max_division: int
    # max_league: str
    max_position: int
    max_public_rating: int
    # max_winning_streak: int
    members_count: int
    planned_prime_time: Optional[int]  # This value is weird, highest seen is 9
    prime_time: Optional[int]
    public_rating: int
    ratings: list[ClanSeasonStats]
    rating_realm: None
    realm: str
    season_number: int
    status: str
    team_number: int
    total_battles_count: int
    wins_count: int

    # # Misc
    is_banned: bool

    @property
    def _league(self) -> str:
        return {
            0: "Hurricane League",
            1: "Typhoon League",
            2: "Storm League",
            3: "Gale League",
            4: "Squall League",
        }[self.league]

    @property
    def max_rating_name(self) -> str:
        """Is Alpha or Bravo their best rating?"""
        return {1: "Alpha", 2: "Bravo"}[self.leading_team_number]

    @property
    def cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        if self.public_rating:
            return "Rating Not Found"

        if self.league == 0:
            return f"Hurricane ({self.public_rating - 2200} points)"
        else:
            div = self.division * "I" if self.division else ""
            return f"{self.league} {div} ({self.public_rating // 100} points)"

    # @property
    # def max_cb_rating(self) -> str:
    #     """Return a string in format League II (50 points)"""
    #     if self.max_league == 0:
    #         return f"Hurricane ({self.max_public_rating - 2200} points)"

    #     league = self.max_league
    #     div = self.max_division * "I"
    #     return f"{league} {div} ({self.max_public_rating // 100} points)"


class PartialClan(BaseModel):
    """A World of Warships clan."""

    clan_id: int
    created_at: datetime.datetime
    members_count: int
    name: str
    tag: str

    async def fetch_details(self) -> Clan:
        """Fetch clan information."""
        return await get_clan_details(self.clan_id, self.region)

    @property
    def title(self) -> str:
        """[Tag] and Name of clan"""
        return f"[{self.tag}] {self.name}"

    @property
    def region(self) -> Region:
        """Get a Region object based on the clan's ID number."""
        if 0 < self.clan_id < 500000000:
            raise ValueError("CIS is no longer supported")
        if 500000000 < self.clan_id < 999999999:
            return Region.EU
        if 1000000000 < self.clan_id < 1999999999:
            return Region.NA
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
        return [PlayerCBStats(**i) for i in season_stats["items"]]
