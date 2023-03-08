"""Information about World of Warships Clans"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
import typing
from discord import Colour
import discord

from ext.painezbot_utils.player import Region, Player
from ext.utils import timed_events

if typing.TYPE_CHECKING:
    from painezBot import PBot


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

    bot: typing.ClassVar[PBot]

    def __init__(self, bot: PBot, clan_id: int):
        self.clan_id: int = clan_id

        if self.__class__.bot is None:
            self.__class__.bot = bot

        self.clan_id: int = clan_id
        self.tag: str
        self.name: str

        # Fetched legitimately from the API.
        self.api_data: dict = {}

        # Fetched ... illegitimately from the Clans Page
        self.clans_data: dict = {}

    async def get_api_data(self) -> dict:
        """Fetch clan information."""
        if self.clan_id is None:
            raise

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
            if resp.status != 200:
                raise ConnectionError("%s connecting to %s", resp.status, url)
            data: dict = await resp.json()

        self.data = data["data"].pop(str(self.clan_id))
        return self.data

        # # clan = json.pop('clan')
        # # This information is also already known to us

        # ladder = json.pop("wows_ladder")  # This info we care about.
        # if lbt := ladder.pop("last_battle_at", {}):
        #     self.current_winning_streak = ladder.pop(
        #         "current_winning_streak", 0
        #     )
        #     self.longest_winning_streak = ladder.pop(
        #         "longest_winning_streak", 0
        #     )
        #     self.leading_team_number = ladder.pop("leading_team_number", None)
        #     ts = datetime.strptime(lbt, "%Y-%m-%dT%H:%M:%S%z")
        #     self.last_battle_at = timed_events.Timestamp(ts)

        #     if lwt := ladder.pop("last_win_at", {}):
        #         ts2 = datetime.strptime(lwt, "%Y-%m-%dT%H:%M:%S%z")
        #         self.last_win_at = timed_events.Timestamp(ts2)

        #     self.wins_count = ladder.pop("wins_count", 0)
        #     self.battles_count = ladder.pop("battles_count", 0)
        #     self.total_battles_played = ladder.pop("total_battles_count", 0)

        #     self.season_number = ladder.pop("season_number", None)

        #     self.public_rating = ladder.pop("public_rating", None)
        #     self.max_public_rating = ladder.pop("max_public_rating", None)

        #     league = ladder.pop("league")
        #     self.league = next(i for i in League if i.value == league)

        #     if highest := ladder.pop("max_position", {}):
        #         self.max_league = next(
        #             i for i in League if i.value == highest.pop("league", None)
        #         )
        #         self.max_division = highest.pop("division", None)

        #     self.division = ladder.pop("division", None)
        #     self.colour: Colour = Colour(ladder.pop("colour", 0x000000))

        #     if ratings := ladder.pop("ratings", []):
        #         self._clan_battle_history = []

        #     for x in ratings:
        #         if (season_id := x.pop("season_number", 999)) > 99:
        #             continue  # Discard Brawls.

        #         season = ClanBattleStats(self, season_id)

        #         if maximums := x.pop("max_position", False):
        #             max_league = maximums.pop("league")
        #             season.max_league = next(
        #                 i for i in League if i.value == max_league
        #             )
        #             season.max_division = maximums.pop("division")
        #             season.max_rating = maximums.pop("public_rating", 0)

        #         season.max_win_streak = x.pop("longest_winning_streak", 0)
        #         season.battles_played = x.pop("battles_count", 0)
        #         season.games_won = season.games_won + x.pop("wins_count", 0)

        #         if last := x.pop("last_win_at", {}):
        #             season.last_win_at = last.strptime(
        #                 lwt, "%Y-%m-%dT%H:%M:%S%z"
        #             )

        #         season.final_rating = x.pop("public_rating", 0)
        #         season.final_league = next(
        #             i for i in League if i.value == x.pop("league", 4)
        #         )
        #         season.final_division = x.pop("division", 3)

        # if buildings := json.pop("buildings", {}):
        #     for k, v in buildings.items():
        #         setattr(self, k, v["modifiers"])
        # return self

    async def get_clans_page_data(self) -> dict:
        d = self.region.domain
        id_ = self.clan_id
        url = f"https://clans.worldofwarships.{d}/api/clanbase/{id_}/claninfo/"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                r = resp.status
                raise ConnectionError("%s fetching clans.warships api", r)
            data = await resp.json()
            json = data.pop("clanview")
        self.clans_data = json
        return json

    @property
    def title(self) -> str:
        return f"[{self.tag}] {self.name}"

    def embed(self) -> discord.Embed:
        """Generic Embed for all view functions"""
        e = discord.Embed()
        e.set_author(name=self.title)
        if ladder := self.clans_data.get("ladder", {}):
            if league := ladder.get("league", {}):
                league = next(i for i in League if i.alias == league)

                e.colour = league.colour
                e.set_thumbnail(url=league.thumbnail)
        return e

    @property
    def region(self) -> Region:
        """Get a Region object based on the player's ID number."""
        match self.clan_id:
            case self.clan_id if 0 < self.clan_id < 500000000:
                raise ValueError("CIS is no longer supported")
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
            len(self.clans_data["coal_yard"])
        ]

    @property
    def max_members(self) -> int:
        """Get maximum number of clan members"""
        return {
            1: 30,
            2: 35,
            3: 40,
            4: 45,
            5: 50,
        }[len(self.clans_data["headquarters"])]

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
        }[len(self.clans_data["shipbuilding_factory"])]

    @property
    def steel_bonus(self) -> str:
        """Clan Base's bonus Steel"""
        return {
            1: "No Bonus",
            2: "+5% Steel",
            3: "+7% Steel",
            4: "+10% Steel",
        }[len(self.clans_data["steel_yard"])]

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
        }[len(self.clans_data["dry_dock"])]

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
        }[len(self.clans_data["academy"])]

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
        }[len(self.clans_data["design_department"])]

    @property
    def research_points_bonus(self) -> str:
        """Get the Clan's Bonus to Research Points earned"""
        return {
            1: "No Bonus",
            2: "+1% Research Points",
            3: "+3% Research Points",
            4: "+5% Research Points",
        }[len(self.clans_data["paragon_yard"])]

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
        }[len(self.data.university)]

    @property
    def max_rating_name(self) -> str:
        """Is Alpha or Bravo their best rating?"""
        return {1: "Alpha", 2: "Bravo"}[
            self.clans_data.get("leading_team_number", 1)
        ]

    @property
    def cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        if not (rtg := self.clans_data.get("public_rating")):
            return "Rating Not Found"

        if self.league == League.HURRICANE:
            return f"Hurricane ({rtg - 2200} points)"
        else:
            league = self.league.alias
            d = (
                self.clans_data["division"] * "I"
                if self.clans_data["division"]
                else ""
            )
            return f"{league} {d} ({rtg // 100} points)"

    @property
    def max_cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        if self.max_league == League.HURRICANE:
            return f"Hurricane ({self.clans_data['max_public_rating'] - 2200} points)"
        league = self.max_league.alias
        d = self.max_division * "I"
        return f"{league} {d} ({self.clans_data['max_public_rating'] // 100} points)"

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
            player.clans_json = member
            return player

        self.members = [parse_member(member) for member in json.pop("items")]
