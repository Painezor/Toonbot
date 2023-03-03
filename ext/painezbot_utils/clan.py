"""Information about World of Warships Clans"""
from __future__ import annotations

import logging
from dataclasses import dataclass
import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, ClassVar

from discord import Colour, Message, Embed, SelectOption
import discord

from ext.painezbot_utils.player import Region, Player
from ext.utils import view_utils, embed_utils, timed_events

if TYPE_CHECKING:
    from painezBot import PBot
    from discord import Interaction


class ClanBuilding:
    """A World of Warships Clan Building"""


class League(Enum):
    """Enum of Clan Battle Leagues"""

    def __new__(cls, *args, **kwargs) -> League:
        value = len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(
        self, alias: str, emote: str, colour: Colour, image: str
    ) -> None:
        self.alias: str = alias
        self.emote: str = emote
        self.colour: Colour = colour
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


@dataclass
class ClanBattleStats:
    """A Single Clan's statistics for a Clan Battles season"""

    clan: Clan

    season_number: int
    max_win_streak: int
    battles_played: int
    games_won: int

    final_rating: int
    final_league: League
    final_division: int

    max_rating: int
    max_league: League
    max_division: int

    last_win_at: timed_events.Timestamp


@dataclass
class PlayerCBStats:
    """A Player's Clan Battle Stats for a season"""

    win_rate: float
    battles: int
    average_damage: float
    average_kills: float


class Clan:
    """A World of Warships clan."""

    bot: ClassVar[PBot]

    def __init__(self, bot: PBot, clan_id: int):
        self.clan_id: int = clan_id

        if self.__class__.bot is None:
            self.__class__.bot = bot

        self.clan_id: int = clan_id
        self.created_at: datetime.datetime
        self.creator_id: int
        self.creator_name: str
        self.description: str
        self.is_clan_disbanded: bool
        self.leader_name: str
        self.leader_id: int
        self.members_count: int
        self.member_ids: list[int]
        self.name: str
        self.old_name: str
        self.old_tag: str
        self.renamed_at: datetime.datetime
        self.tag: str
        self.updated_at: datetime.datetime

        # Additional Data from clan API
        self.season_number: Optional[int] = None  # Current season number

        self.current_winning_streak: int = 0
        self.longest_winning_streak: int = 0  # Best Win Streak This Season

        self.last_battle_at: Optional[Timestamp] = None
        self.last_win_at: Optional[Timestamp] = None

        self.battles_count: int = 0  # Total Battles in this season
        self.wins_count: int = 0  # Total Wins in this Season
        self.total_battles_played: int = 0  # Total Battles played ever

        self.leading_team_number: Optional[int] = None  # Alpha or Bravo rating
        self.public_rating: Optional[int] = None  # Current rating this season
        self.league: League = (
            League.SQUALL
        )  # Current League, 0 is Hurricane, 1 is Typhoon...
        self.division: Optional[int] = 3  # Current Division within League
        self.max_public_rating: int = 0  # Highest rating this season
        self.max_league: Optional[League] = None  # Max League
        self.max_division: Optional[int] = None  # Max Division

        # Converted to discord Colour for Embed
        self.is_banned: bool = False  # Is the Clan banned?
        self.is_qualified: bool = False  # In qualifications?

        # List of Clan Building IDs
        self.academy: list[int] = []  # Academy - Commander XP
        self.dry_dock: list[int] = []  # Service Cost Reduction
        self.design_department: list[int] = []  # Design Bureau - Free XP
        self.headquarters: list[int] = []  # Officers' Club - Members Count

        # Shipbuilding yard - Purchase Cost Discount
        self.shipbuilding_factory: list[int] = []
        self.coal_yard: list[int] = []  # Bonus Coal
        self.steel_yard: list[int] = []  # Bonus Steel
        self.university: list[int] = []  # War College - Bonus XP
        self.paragon_yard: list[int] = []  # Research Institute - Reseearch Pts

        # Vanity Only.
        self.monument: list[int] = []  # Rostral Column - click 4 achiev
        self.vessels: list[int] = []  # Other Vessels in port, # of CBs played.
        self.ships: list[int] = []  # Ships in clan base, # of randoms played.
        self.treasury: list[int] = []  # Clan Treasury

        # Fetched and stored.
        # A list of ClanBattleSeason dataclasses
        self._clan_battle_history: list[ClanBattleStats] = []
        self.members: list[Player] = []

        # Dummy Data for leaderboard
        self.rank = None

    @property
    def title(self) -> str:
        return f"[{self.tag}] {self.name}"

    def embed(self) -> discord.Embed:
        """Generic Embed for all view functions"""
        e = discord.Embed(colour=self.league.colour)
        e.set_author(name=self.title)
        e.set_thumbnail(url=self.league.thumbnail)
        return e

    @property
    def region(self) -> Region:
        """Get a Region object based on the player's ID number."""
        match self.clan_id:
            case self.clan_id if 0 < self.clan_id < 500000000:
                return Region.CIS
            case self.clan_id if 500000000 < self.clan_id < 999999999:
                return Region.EU
            case self.clan_id if 1000000000 < self.clan_id < 1999999999:
                return Region.NA
            case _:
                return Region.SEA

    @property
    def coal_bonus(self) -> str:
        """Clan Base's bonus Coal"""
        return {1: "No Bonus", 2: "+5% Coal", 3: "+7% Coal", 4: "+10% Coal"}[
            len(self.coal_yard)
        ]

    @property
    def max_members(self) -> int:
        """Get maximum number of clan members"""
        return {1: 30, 2: 35, 3: 40, 4: 45, 5: 50}[len(self.headquarters)]

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
        if not self.public_rating:
            return "Rating Not Found"

        if self.league == League.HURRICANE:
            return f"Hurricane ({self.public_rating - 2200} points)"
        else:
            league = self.league.alias
            d = self.division * "I" if self.division else ""
            return f"{league} {d} ({self.public_rating // 100} points)"

    @property
    def max_cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        if self.max_league == League.HURRICANE:
            return f"Hurricane ({self.max_public_rating - 2200} points)"
        league = self.max_league.alias
        d = self.max_division * "I"
        return f"{league} {d} ({self.max_public_rating // 100} points)"

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

    async def get_member_clan_battle_stats(self, season: int) -> dict:
        """Attempt to fetch clan battle stats for members"""
        if season is None:
            season = self.season_number

        url = (
            f"https://clans.worldofwarships.{self.region.domain}"
            f"/api/members/{self.clan_id}/"
        )
        p = {"battle_type": "cvc", "season": season}

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    season_stats = await resp.json()
                case _:
                    err = f"{resp.status} error accessing {url}"
                    raise ConnectionError(err)

        logging.info("DEBUG: Season Stats\n%s", season_stats)

        for x in season_stats["items"]:
            player = self.bot.get_player(x["id"])

            wr = x["wins_percentage"]
            num = x["battles_count"]
            dmg = x["damage_per_battle"]
            kills = x["frags_per_battle"]
            stats = PlayerCBStats(wr, num, dmg, kills)
            player.clan_battle_stats[season] = stats

    async def get_member_stats(self) -> dict:
        """Attempt to fetch clan battle stats for members"""
        url = (
            f"https://clans.worldofwarships.{self.region.domain}/"
            f"api/members/{self.clan_id}/"
        )
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    err = f"Error {resp.status} fetching {url}"
                    raise ConnectionError(err)

        def parse_member(member: dict) -> Player:
            """Update Player Objects with available data from CB EndPoint"""
            player = self.bot.get_player(member["id"])
            player.clan = self

            # Account Info
            player.nickname = member["name"]
            player.levelling_tier = member["rank"]
            player.is_online = member["online_status"]
            player.is_banned = member["is_banned"]

            # Recent Activity
            lbt = member["last_battle_time"]

            ts = timed_events.Timestamp(datetime.utcfromtimestamp(lbt))
            player.last_battle_time = ts

            # Averages
            player.hidden_profile = member["is_hidden_statistics"]
            player.average_damage = member["damage_per_battle"]
            player.average_xp = member["exp_per_battle"]
            player.average_kills = member["frags_per_battle"]
            player.battles_per_day = member["battles_per_day"]
            player.win_rate = member["wins_percentage"]

            # Totals
            player.battles = member["battles_count"]
            player.oil = member["accumulative_clan_resource"]
            return player

        self.members = [parse_member(member) for member in json.pop("items")]

    async def get_data(self) -> Clan:
        """Fetch clan information."""
        if self.clan_id is None:
            return self

        p = {
            "application_id": self.bot.wg_id,
            "clan_id": self.clan_id,
            "extra": "members",
        }
        url = (
            "https://api.worldofwarships."
            f"{self.region.domain}/wows/clans/info/"
        )
        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    data: dict = await resp.json()
                case _:
                    return self

        data = data["data"].pop(str(self.clan_id))

        # Handle Timestamps.
        self.updated_at = Timestamp(
            datetime.utcfromtimestamp(data.pop("updated_at", None))
        )

        crt = data.pop("created_at", None)
        if crt:
            ts = timed_events.Timestamp(datetime.utcfromtimestamp(crt))
            self.created_at = ts

        if (rn := data.pop("renamed_at", None)) is not None:
            self.renamed_at = Timestamp(datetime.utcfromtimestamp(rn))

        for x in ["league", "max_league"]:
            try:
                _x = data.pop(x)
                league = next(i for i in League if _x == i)
                setattr(self, x, league)
            except KeyError:
                pass

        def parse_player(pl: dict) -> Player:
            """Convert Dict to Player Objects"""
            player = self.bot.get_player(pl["account_id"])
            player.nickname = pl["account_name"]

            ts = Timestamp(datetime.utcfromtimestamp(pl["joined_at"]))
            player.joined_clan_at = ts
            player.clan_role = pl["role"]
            return player

        self.members = [parse_player(m) for m in data.pop("members").values()]

        # Handle rest.
        for k, v in data.items():
            setattr(self, k, v)

        url = (
            f"https://clans.worldofwarships.{self.region.domain}"
            "/api/clanbase/{self.clan_id}/claninfo/"
        )
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                    json = data.pop("clanview")
                case _:
                    raise ConnectionError(
                        f"Http Error {resp.status} fetching clans.warships api"
                    )

        # clan = json.pop('clan')
        # This information is also already known to us

        ladder = json.pop("wows_ladder")  # This info we care about.
        if lbt := ladder.pop("last_battle_at", {}):
            self.current_winning_streak = ladder.pop(
                "current_winning_streak", 0
            )
            self.longest_winning_streak = ladder.pop(
                "longest_winning_streak", 0
            )
            self.leading_team_number = ladder.pop("leading_team_number", None)
            ts = datetime.strptime(lbt, "%Y-%m-%dT%H:%M:%S%z")
            self.last_battle_at = timed_events.Timestamp(ts)

            if lwt := ladder.pop("last_win_at", {}):
                ts2 = datetime.strptime(lwt, "%Y-%m-%dT%H:%M:%S%z")
                self.last_win_at = timed_events.Timestamp(ts2)

            self.wins_count = ladder.pop("wins_count", 0)
            self.battles_count = ladder.pop("battles_count", 0)
            self.total_battles_played = ladder.pop("total_battles_count", 0)

            self.season_number = ladder.pop("season_number", None)

            self.public_rating = ladder.pop("public_rating", None)
            self.max_public_rating = ladder.pop("max_public_rating", None)

            league = ladder.pop("league")
            self.league = next(i for i in League if i.value == league)

            if highest := ladder.pop("max_position", {}):
                self.max_league = next(
                    i for i in League if i.value == highest.pop("league", None)
                )
                self.max_division = highest.pop("division", None)

            self.division = ladder.pop("division", None)
            self.colour: Colour = Colour(ladder.pop("colour", 0x000000))

            if ratings := ladder.pop("ratings", []):
                self._clan_battle_history = []

            for x in ratings:
                if (season_id := x.pop("season_number", 999)) > 99:
                    continue  # Discard Brawls.

                season = ClanBattleStats(self, season_id)

                if maximums := x.pop("max_position", False):
                    max_league = maximums.pop("league")
                    season.max_league = next(
                        i for i in League if i.value == max_league
                    )
                    season.max_division = maximums.pop("division")
                    season.max_rating = maximums.pop("public_rating", 0)

                season.max_win_streak = x.pop("longest_winning_streak", 0)
                season.battles_played = x.pop("battles_count", 0)
                season.games_won = season.games_won + x.pop("wins_count", 0)

                if last := x.pop("last_win_at", {}):
                    season.last_win_at = last.strptime(
                        lwt, "%Y-%m-%dT%H:%M:%S%z"
                    )

                season.final_rating = x.pop("public_rating", 0)
                season.final_league = next(
                    i for i in League if i.value == x.pop("league", 4)
                )
                season.final_division = x.pop("division", 3)

        if buildings := json.pop("buildings", {}):
            for k, v in buildings.items():
                setattr(self, k, v["modifiers"])
        return self

    # achievements = json.pop('achievements')
    # This information is complete garbage.
