"""Utilities for World of Warships related commands."""
from __future__ import annotations

import dataclasses
import datetime
import enum
import json
import logging
import typing

import aiohttp
import discord

from ext.painezbot_utils.ship import Ship


with open("credentials.json", encoding="utf-8") as f:
    credentials = json.load(f)
WG_ID: str = credentials["Wargaming"]["client_id"]

# TODO: CommanderXP Command (Show Total Commander XP per Rank)
# TODO: Encyclopedia - Collections
# TODO: Pull Achievement Data to specifically get Jolly Rogers
# and Hurricane Emblems for player stats.
# TODO: Player's Ranked Battle Season History
# TODO: Clan Battle Season objects for Images for Leaderboard.


API = "https://api.worldofwarships."

logger = logging.getLogger("player")


API_MODES = [
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

ARMAMENT_TYPES = [
    "aircraft",
    "main_battery",
    "ramming",
    "second_battery",
    "torpedoes",
]


@dataclasses.dataclass
class PlayerStats:
    """Generics for a Player"""

    oper_div: PlayerModeStats
    oper_div_hard: PlayerModeStats
    oper_solo: PlayerModeStats
    pve: PlayerModeStats
    pve_div2: PlayerModeStats
    pve_div3: PlayerModeStats
    pve_solo: PlayerModeStats
    pvp: PlayerModeStats
    pvp_div2: PlayerModeStats
    pvp_div3: PlayerModeStats
    pvp_solo: PlayerModeStats

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            if k == "club":
                continue  # Dead data.

            if k in API_MODES:
                setattr(self, k, PlayerModeStats(val))
            else:
                setattr(self, k, val)


@dataclasses.dataclass
class PlayerModeStats:
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
    xp: int

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


class Player:
    """A World of Warships player."""

    def __init__(self, account_id: int, **kwargs) -> None:
        # Player Search Endpoint
        self.account_id: int = account_id
        self.nickname: str = kwargs.pop("nickname", None)

        # Player Personal Data Endpoint.
        self.created_at: datetime.datetime  # Player Account creation
        self.hidden_profile: bool  # Player Stats are hidden?
        self.karma: int  # Player Karma
        self.last_battle_time: datetime.datetime
        self.levelling_points: int  # Player level - Garbage
        self.levelling_tier: int  # Smae.
        self.logout_at: datetime.datetime
        self.stats_updated_at: datetime.datetime

        # CB Season Stats
        self.clan: typing.Optional[Clan] = None

        # Keyed By Season ID.
        self.clan_battle_stats: dict[int, PlayerCBStats] = {}

    async def fetch_stats(self) -> PlayerStats:
        """Fetch Player Stats from API"""
        parmas = {"application_id": WG_ID, "account_id": self.account_id}

        url = API + self.region.domain + "/wows/account/info/"

        extra = ", ".join(f"statistics.{i}" for i in API_MODES)
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
        url = API + self.region.domain + "/wows/ships/stats/"
        params = {"application_id": WG_ID, "account_id": self.account_id}
        params.update({"ship_id": ship.ship_id, "extra": ", ".join(API_MODES)})

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

    async def get_clan_info(self) -> typing.Optional[Clan]:
        """Get a Player's clan"""
        link = API + self.region.domain + "/wows/clans/accountinfo/"
        parms = {
            "application_id": WG_ID,
            "account_id": self.account_id,
            "extra": "clan",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(link, params=parms) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, link)
                    return None
                data = await resp.json()

        if (data := data["data"].pop(str(self.account_id))) is None:
            self.clan = None
            return None

        self.joined_clan_at = datetime.datetime.utcfromtimestamp(
            data.pop("joined_at")
        )

        clan_id = data.pop("clan_id")
        clan = Clan(clan_id)
        clan_data = data.pop("clan")
        clan.name = clan_data.pop("name")
        clan.tag = clan_data.pop("tag")

        self.clan = clan
        return self.clan


class GameMode:
    """ "An Object representing different Game Modes"""

    def __init__(
        self, image: str, tag: str, name: str, description: str
    ) -> None:
        self.tag: str = tag
        self.name: str = name
        self.image: str = image
        self.description: str = description

    @property
    def emoji(self) -> typing.Optional[str]:
        """Get the Emoji Representation of the game mode."""
        return {
            "BRAWL": "<:Brawl:989921560901058590>",
            "CLAN": "<:Clan:989921285918294027>",
            "COOPERATIVE": "<:Coop:989844738800746516>",
            "EVENT": "<:Event:989921682007420938>",
            "PVE": "<:Scenario:989921800920109077>",
            "PVE_PREMADE": "<:Scenario_Hard:989922089303687230>",
            "PVP": "<:Randoms:988865875824222338>",
            "RANKED": "<:Ranked:989845163989950475>",
        }.get(self.tag, None)


class ClanBuilding:
    """A World of Warships Clan Building"""


class League(enum.Enum):
    """Enum of Clan Battle Leagues"""

    def __new__(cls, *args, **kwargs) -> League:
        value = len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(
        self, alias: str, emote: str, colour: discord.Colour, image: str
    ) -> None:
        self.alias: str = alias
        self.emote: str = emote
        self.colour: discord.Colour = colour
        self.image: str = image

    @property
    def thumbnail(self) -> str:
        """Return a link to the image version of the clan's league"""
        return (
            "https://glossary-wows-global.gcdn.co/"
            f"icons//clans/leagues/{self.image}"
        )

    # noinspection SpellCheckingInspection
    HURRICANE = (
        "Hurricane",
        "<:Hurricane:990599761574920332>",
        0xCDA4FF,
        (
            "cvc_league_0_small_1ffb7bdd0346e4a10eaa1"
            "befbd53584dead5cd5972212742d015fdacb34160a1.png"
        ),
    )
    TYPHOON = (
        "Typhoon",
        "<:Typhoon:990599751584067584>",
        0xBEE7BD,
        (
            "cvc_league_1_small_73d5594c7f6ae307721fe89a845b"
            "81196382c08940d9f32c9923f5f2b23e4437.png"
        ),
    )
    STORM = (
        "Storm",
        "<:Storm:990599740079104070>",
        0xE3D6A0,
        (
            "cvc_league_2_small_a2116019add2189c449af6497873"
            "ef87e85c2c3ada76120c27e7ec57d52de163.png"
        ),
    )

    GALE = (
        "Gale",
        "<:Gale:990599200905527329>",
        0xCCE4E4,
        (
            "cvc_league_3_small_d99914b661e711deaff0bdb614"
            "77d82a4d3d4b83b9750f5d1d4b887e6b1a6546.png"
        ),
    )
    SQUALL = (
        "Squall",
        "<:Squall:990597783817965568>",
        0xCC9966,
        (
            "cvc_league_4_small_154e2148d23ee9757568a144e06"
            "c0e8b904d921cc166407e469ce228a7924836.png"
        ),
    )


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

    clan: Clan

    battles_count: int
    is_clan_disbanded: bool
    last_battle_at: datetime.datetime
    leading_team_number: int
    league: League
    public_rating: int
    rank: int
    season_number: int

    def __init__(self, clan: Clan, data: dict) -> None:

        self.clan = clan

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
    battles: int
    average_damage: float
    average_kills: float


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

        for k, value in ladder:
            if k in ["last_battle_at", "last_win_at"]:
                value = datetime.datetime.strptime(
                    value, "%Y-%m-%dT%H:%M:%S%z"
                )
            elif k in ["league", "max_league"]:
                value = next(i for i in League if value == i)
            elif k == "ratings":
                _v = []
                for i in value:
                    _v.append(ClanSeasonStats(i))
                value = _v
            elif k == "buildings":
                for _k, _v in value.items():
                    setattr(self, _k, _v["modifiers"])
            setattr(self, k, value)

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
        tr_1 = "Allocation of resources"
        tr_2 = "More Resources Bundles"
        tr_3 = "Try Your Luck Bundles"
        tr_4 = "Supercontainer Bundles"
        tr = {
            1: f"{tr_1} only",
            2: f"{tr_1}, {tr_2}",
            3: f"{tr_1}, {tr_2}, {tr_3}",
            4: f"{tr_1}, {tr_2}, {tr_3}, {tr_4}",
            5: f"{tr_1}, {tr_2}' {tr_3}, {tr_4} & 'additional' bundles",
        }
        return tr[len(self.treasury)]


class Clan:
    """A World of Warships clan."""

    def __init__(self, clan_id: int):
        self.clan_id: int = clan_id

        self.tag: str
        self.name: str

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

    async def fetch_clan_vortex_data(self) -> ClanVortexData:
        """Get clan data from the vortex api"""
        d = self.region.domain
        id_ = self.clan_id
        url = f"https://clans.worldofwarships.{d}/api/clanbase/{id_}/claninfo/"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise ConnectionError("%s clans.warships api", resp.status)
            data = await resp.json()
            json = data.pop("clanview")

        return ClanVortexData(json)

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

    async def fetch_cb_stats(self, season: int) -> list[PlayerCBStats]:
        """Attempt to fetch clan battle stats for members"""

        dm = self.region.domain
        url = f"https://clans.worldofwarships.{dm}/api/members/{self.clan_id}/"
        params = {"battle_type": "cvc", "season": season}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    err = f"{resp.status} {await resp.text()} on {url}"
                    raise ConnectionError(err)
                season_stats = await resp.json()

        logging.info("DEBUG: Season Stats\n%s", season_stats)

        stats = []
        for i in season_stats["items"]:

            win_rate = i["wins_percentage"]
            num = i["battles_count"]
            dmg = i["damage_per_battle"]
            kills = i["frags_per_battle"]

            player = PlayerCBStats(win_rate, num, dmg, kills)
            stats.append(player)
        return stats

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


class Region(enum.Enum):
    """A Generic object representing a region"""

    def __new__(cls, *args, **kwargs) -> Region:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(
        self,
        db_key: str,
        url: str,
        emote: str,
        colour: discord.Colour,
        code_prefix: str,
        realm: str,
    ) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: discord.Colour = colour
        self.code_prefix: str = code_prefix
        self.realm: str = realm

    @property
    def inventory(self) -> str:
        """Returns a link to the 'Inventory Management' webpage"""
        return f"https://warehouse.worldofwarships.{self.domain}"

    @property
    def armory(self) -> str:
        """Returns a link to the 'Armory' webpage"""
        return f"https://armory.worldofwarships.{self.domain}/en/"

    @property
    def clans(self) -> str:
        """Returns a link to the 'Clans' webpage"""
        return (
            f"https://clans.worldofwarships.{self.domain}"
            "/clans/gateway/wows/profile"
        )

    @property
    def logbook(self) -> str:
        """Returns a link to the 'Captains Logbook' page"""
        return f"https://logbook.worldofwarships.{self.domain}/"

    @property
    def dockyard(self) -> str:
        """Return a link to the 'Dockyard' page"""
        return f"http://dockyard.worldofwarships.{self.domain}/en/"

    @property
    def news(self) -> str:
        """Return a link to the in-game version of the portal news"""
        return f"https://worldofwarships.{self.domain}/news_ingame"

    @property
    def recruiting(self) -> str:
        """Return a link to the 'Recruiting Station' page"""
        return f"https://friends.worldofwarships.{self.domain}/en/players/"

    # database key, domain, emote, colour, code prefix, realm
    EU = ("eu", "eu", "<:EU:993495456988545124>", 0x0000FF, "eu", "eu")
    NA = ("na", "com", "<:NA:993495467788869663>", 0x00FF00, "na", "us")
    SEA = ("sea", "asia", "<:ASIA:993495476978589786>", 0x00FFFF, "asia", "sg")


class Map:
    """A Generic container class representing a map"""

    def __init__(self, name: str, desc: str, map_id: int, icon: str) -> None:
        self.name: str = name
        self.description: str = desc
        self.battle_arena_id = map_id
        self.icon: str = icon

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    @property
    def ac_row(self) -> str:
        """Autocomplete row for this map"""
        return f"{self.name}: {self.description}"

    @property
    def ac_match(self) -> str:
        """Autocomplete match for this map"""
        return f"{self.name}: {self.description} {self.icon}".casefold()

    @property
    def embed(self) -> discord.Embed:
        """Return an embed representing this map"""
        embed = discord.Embed(title=self.name, colour=discord.Colour.greyple())
        embed.set_image(url=self.icon)
        embed.set_footer(text=self.description)
        return embed
