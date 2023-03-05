"""Utilities for World of Warships related commands."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, ClassVar

import typing

from ext.painezbot_utils.region import Region
from ext.painezbot_utils.ship import Ship
from ext.utils.timed_events import Timestamp

if typing.TYPE_CHECKING:
    from ext.painezbot_utils.clan import PlayerCBStats, Clan
    from painezBot import PBot


# TODO: CommanderXP Command (Show Total Commander XP per Rank)
# TODO: Encyclopedia - Collections
# TODO: Pull Achievement Data to specifically get Jolly Rogers
# and Hurricane Emblems for player stats.
# TODO: Player's Ranked Battle Season History
# TODO: Clan Battle Season objects for Images for Leaderboard.


API = "https://api.worldofwarships."


class Achievement:
    """A World of Warships Achievement"""


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
    def emoji(self) -> Optional[str]:
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


class Player:
    """A World of Warships player."""

    bot: ClassVar[PBot]

    def __init__(self, account_id: int, **kwargs) -> None:
        self.account_id: int = account_id
        self.nickname: str = kwargs.pop("nickname", None)

        # Additional Fetched Data.
        self.stats: dict = {}

        # CB Season Stats
        self.clan_battle_stats: dict[
            int, PlayerCBStats
        ] = {}  # Keyed By Season ID.

    @property
    def region(self) -> Region:
        """Get a Region object based on the player's ID number."""
        match self.account_id:
            case self.account_id if 0 < self.account_id < 500000000:
                return Region.CIS
            case self.account_id if 500000000 < self.account_id < 999999999:
                return Region.EU
            case self.account_id if 1000000000 < self.account_id < 1999999999:
                return Region.NA
            case _:
                return Region.SEA

    @property
    def community_link(self) -> str:
        """Get a link to this player's community page."""
        return (
            f"https://worldofwarships.{self.region.domain}/"
            f"community/accounts/{self.account_id}-{self.nickname}/"
        )

    @property
    def wows_numbers(self) -> str:
        """Get a link to this player's wows_numbers page."""
        prefix = {
            Region.NA: "na.",
            Region.SEA: "asia.",
            Region.CIS: "ru.",
            Region.EU: "",
        }[self.region]
        return (
            f"https://{prefix}wows-numbers.com/player/"
            f"{self.account_id},{self.nickname}/"
        )

    async def get_pr(self) -> int:
        """Calculate a player's personal rating"""
        if not self.bot.pr_data_updated_at:
            async with self.bot.session.get(
                "https://api.wows-numbers.com/personal/rating/expected/json/"
            ) as resp:
                match resp.status:
                    case 200:
                        pass
                    case _:
                        raise ConnectionError(
                            f"{resp.status} Error accessing {resp.url}"
                        )
        # TODO: Get PR
        raise NotImplementedError

    async def get_clan_info(self) -> Optional[Clan]:
        """Get a Player's clan"""
        link = API + self.region.domain + "/wows/clans/accountinfo/"
        p = {
            "application_id": self.bot.wg_id,
            "account_id": self.account_id,
            "extra": "clan",
        }

        async with self.bot.session.get(link, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    return None

        if (data := json["data"].pop(str(self.account_id))) is None:
            self.clan = None
            return None

        self.joined_clan_at = Timestamp(
            datetime.utcfromtimestamp(data.pop("joined_at"))
        )

        clan_id = data.pop("clan_id")
        clan = self.bot.get_clan(clan_id)
        if clan:
            clan_data = data.pop("clan")
            crt = clan_data.pop("created_at")
            clan.created_at = datetime.utcfromtimestamp(crt)
            clan.members_count = clan_data.pop("members_count")
            clan.name = clan_data.pop("name")
            clan.tag = clan_data.pop("tag")

        self.clan = clan
        return self.clan

    async def get_stats(self, ship: Optional[Ship] = None) -> None:
        """Get the player's stats as a dict"""
        p = {"application_id": self.bot.wg_id, "account_id": self.account_id}

        if ship is None:
            url = API + self.region.domain + "/wows/account/info/"
            p.update(
                {
                    "extra": "statistics.pvp_solo,"
                    "statistics.pvp_div2, "
                    "statistics.pvp_div3, "
                    "statistics.rank_solo, "
                    "statistics.rank_div2, "
                    "statistics.rank_div3, "
                    "statistics.pve, "
                    "statistics.pve_div2, "
                    "statistics.pve_div3, "
                    "statistics.pve_solo, "
                    "statistics.oper_solo, "
                    "statistics.oper_div, "
                    "statistics.oper_div_hard"
                }
            )
        else:
            url = API + self.region.domain + "/wows/ships/stats/"
            p.update({"ship_id": ship.ship_id})
            p.update(
                {
                    "extra": "pvp_solo, pvp_div2, pvp_div3, "
                    "rank_solo, rank_div2, rank_div3, "
                    "pve, pve_div2, pve_div3, pve_solo, "
                    "oper_solo, oper_div, oper_div_hard"
                }
            )

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    try:
                        raise ConnectionError(resp.status)
                    finally:
                        return

        try:
            stats = json["data"].pop(
                str(self.account_id)
            )  # Why the fuck is this randomly a string now, seriously WG?
        except KeyError:
            raise KeyError(f'Unable to find key "data" in {json}')

        self.created_at = Timestamp(
            datetime.utcfromtimestamp(stats["created_at"])
        )
        self.last_battle_time = Timestamp(
            datetime.utcfromtimestamp(stats["last_battle_time"])
        )
        self.stats_updated_at = Timestamp(
            datetime.utcfromtimestamp(stats["stats_updated_at"])
        )
        self.logout_at = Timestamp(
            datetime.utcfromtimestamp(stats["logout_at"])
        )
        self.hidden_profile = stats["hidden_profile"]
        if ship is None:
            self.stats[None] = stats["statistics"]
        else:
            self.stats[ship] = stats
        return
