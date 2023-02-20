"""Information about World of Warships Clans"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, ClassVar

from discord import Colour, Message, Embed, SelectOption
from discord.ui import View

from ext.painezbot_utils.player import Region, Player
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Parent, FuncButton, FuncDropdown, add_page_buttons, BaseView

if TYPE_CHECKING:
    from painezBot import PBot
    from discord import Interaction


class ClanBuilding:
    """A World of Warships Clan Building"""


SQL_ICO = ()


class League(Enum):
    """Enum of Clan Battle Leagues"""

    def __new__(cls, *args, **kwargs) -> League:
        value = len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, alias: str, emote: str, colour: Colour, image: str) -> None:
        self.alias: str = alias
        self.emote: str = emote
        self.colour: Colour = colour
        self.image: str = image

    @property
    def thumbnail(self) -> str:
        """Return a link to the image version of the clan's league"""
        return f"https://glossary-wows-global.gcdn.co/icons//clans/leagues/{self.image}"

    # noinspection SpellCheckingInspection
    HURRICANE = ('Hurricane', '<:Hurricane:990599761574920332>', 0xCDA4FF,
                 "cvc_league_0_small_1ffb7bdd0346e4a10eaa1befbd53584dead5cd5972212742d015fdacb34160a1.png")
    TYPHOON = ('Typhoon', '<:Typhoon:990599751584067584>', 0xBEE7BD,
               "cvc_league_1_small_73d5594c7f6ae307721fe89a845b81196382c08940d9f32c9923f5f2b23e4437.png")
    STORM = ('Storm', '<:Storm:990599740079104070>', 0xE3D6A0,
             "cvc_league_2_small_a2116019add2189c449af6497873ef87e85c2c3ada76120c27e7ec57d52de163.png")
    # noinspection SpellCheckingInspection
    GALE = ('Gale', "<:Gale:990599200905527329>", 0xCCE4E4,
            "cvc_league_3_small_d99914b661e711deaff0bdb61477d82a4d3d4b83b9750f5d1d4b887e6b1a6546.png")
    SQUALL = ('Squall', "<:Squall:990597783817965568>", 0xCC9966,
              "cvc_league_4_small_154e2148d23ee9757568a144e06c0e8b904d921cc166407e469ce228a7924836.png")


@dataclass
class ClanBattleStats:
    """A Single Clan's statistics for a Clan Battles season"""
    clan: Clan

    season_number: int
    max_win_streak: int = 0
    battles_played: int = 0
    games_won: int = 0

    final_rating: int = 0
    final_league: League = League.SQUALL
    final_division: int = 0

    max_rating: int = 0
    max_league: League = League.SQUALL
    max_division: int = 0

    last_win_at: Optional[Timestamp] = None


@dataclass
class PlayerCBStats:
    """A Player's Clan Battle Stats for a season"""
    win_rate: float = 0
    battles: int = 0
    average_damage: float = 0
    average_kills: float = 0


class Clan:
    """A World of Warships clan."""
    bot: ClassVar[PBot] = None

    def __init__(self, bot: PBot, clan_id: int, **kwargs):
        self.clan_id: int = clan_id

        if self.__class__.bot is None:
            self.__class__.bot = bot

        self.clan_id: int = clan_id
        self.created_at: Optional[Timestamp] = kwargs.pop('created_at', None)
        self.creator_id: Optional[int] = kwargs.pop('creator_id', None)
        self.creator_name: Optional[str] = kwargs.pop('creator_name', None)
        self.description: Optional[str] = kwargs.pop('description', None)
        self.is_clan_disbanded: Optional[bool] = kwargs.pop('is_clan_disbanded', None)
        self.leader_name: Optional[str] = kwargs.pop('leader_name', None)
        self.leader_id: Optional[int] = kwargs.pop('leader_id', None)
        self.members_count: Optional[int] = kwargs.pop('members_count', None)
        self.member_ids: Optional[list[int]] = kwargs.pop('member_ids', None)
        self.name: Optional[str] = kwargs.pop('name', None)
        self.old_name: Optional[str] = kwargs.pop('old_name', None)
        self.old_tag: Optional[str] = kwargs.pop('old_tag', None)
        self.renamed_at: Optional[Timestamp] = kwargs.pop('renamed_at', None)
        self.tag: Optional[str] = kwargs.pop('tag', None)
        self.updated_at: Optional[Timestamp] = kwargs.pop('updated_at', None)

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
        self.league: League = League.SQUALL  # Current League, 0 is Hurricane, 1 is Typhoon...
        self.division: Optional[int] = 3  # Current Division within League
        self.max_public_rating: int = 0  # Highest rating this season
        self.max_league: Optional[League] = None  # Max League
        self.max_division: Optional[int] = None  # Max Division
        self.colour: Colour = None  # Converted to discord Colour for Embed
        self.is_banned: bool = False  # Is the Clan banned?
        self.is_qualified: bool = False  # In qualifications?

        # List of Clan Building IDs
        self.academy: list[int] = []  # Academy - Commander XP
        self.dry_dock: list[int] = []  # Service Cost Reduction
        self.design_department: list[int] = []  # Design Bureau - Free XP
        self.headquarters: list[int] = []  # Officers' Club - Members Count
        self.shipbuilding_factory: list[int] = []  # Shipbuilding yard - Purchase Cost Discount
        self.coal_yard: list[int] = []  # Bonus Coal
        self.steel_yard: list[int] = []  # Bonus Steel
        self.university: list[int] = []  # War College - Bonus XP
        self.paragon_yard: list[int] = []  # Research Institute - Research Points

        # Vanity Only.
        self.monument: list[int] = []  # Rostral Column - Can be clicked for achievements.
        self.vessels: list[int] = []  # Other Vessels in port, based on number of clan battles
        self.ships: list[int] = []  # Ships in clan base, based on number of randoms played.
        self.treasury: list[int] = []  # Clan Treasury

        # Fetched and stored.
        self._clan_battle_history: list[ClanBattleStats] = []  # A list of ClanBattleSeason dataclasses
        self.members: list[Player] = []

        # Dummy Data for leaderboard
        self.rank: int = None

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
        return {1: "No Bonus", 2: "+5% Coal", 3: "+7% Coal", 4: "+10% Coal"}[len(self.coal_yard)]

    @property
    def max_members(self) -> int:
        """Get maximum number of clan members"""
        return {1: 30, 2: 35, 3: 40, 4: 45, 5: 50}[len(self.headquarters)]

    @property
    def purchase_cost_discount(self) -> str:
        """Clan's Ship Purchase Cost Discount"""
        return {1: "No Bonus", 2: "-10% Cost of ships up to Tier IV", 3: "-10% Cost of ships up to Tier VIII",
                4: "-10% Cost of ships up to Tier X", 5: "-12% Cost of ships up to Tier X",
                6: "-14% Cost of ships up to Tier X",
                7: "-15% Cost of ships up to Tier X"}[len(self.shipbuilding_factory)]

    @property
    def steel_bonus(self) -> str:
        """Clan Base's bonus Steel"""
        return {1: "No Bonus", 2: "+5% Steel", 3: "+7% Steel", 4: "+10% Steel"}[len(self.steel_yard)]

    @property
    def service_cost_bonus(self) -> str:
        """Clan Base's bonus Service Cost Reduction"""
        return {1: "No Bonus", 2: "-5% Service Cost (up to Tier IV)", 3: "-5% Service Cost (up to Tier VIII)",
                4: "-5% Service Cost (up to Tier IX)", 5: "-5% Service Cost (up to Tier X)",
                6: "-7% Service Cost (up to Tier X)", 7: "-10% Service Cost (up to Tier X)"}[len(self.dry_dock)]

    @property
    def commander_xp_bonus(self) -> str:
        """Clan's Bonus to XP Earned"""
        return {1: "No Bonus", 2: "+2% Commander XP", 3: "+4% Commander XP", 4: "+6% Commander XP",
                5: "+8% Commander XP", 6: "+10% Commander XP"}[len(self.academy)]

    @property
    def free_xp_bonus(self) -> str:
        """Clan's Bonus to Free XP Earned"""
        return {1: "No Bonus", 2: "+10% Free XP up to Tier VI", 3: "+10% Free XP up to Tier VIII",
                4: "+10% Free XP up to Tier X", 5: "+15% Free XP up to Tier X",
                6: "+20% Free XP up to Tier X", 7: "+25% Free XP up to Tier X"}[len(self.design_department)]

    @property
    def research_points_bonus(self) -> str:
        """Get the Clan's Bonus to Research Points earned"""
        return {1: "No Bonus", 2: "+1% Research Points", 3: "+3% Research Points",
                4: "+5% Research Points"}[len(self.paragon_yard)]

    @property
    def xp_bonus(self) -> str:
        """Get the Clan's Bonus to XP earned"""
        return {1: "No Bonus", 2: "+2% XP up to Tier VI", 3: "+2% Up to Tier VIII", 4: "+2% Up to Tier X",
                5: "+3% Up to Tier X", 6: "+4% Up to Tier X", 7: "+5% Up to Tier X"}[len(self.university)]

    @property
    def max_rating_name(self) -> str:
        """Is Alpha or Bravo their best rating?"""
        return {1: "Alpha", 2: "Bravo"}[self.leading_team_number]

    @property
    def cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        match self.league:
            case League.HURRICANE:
                return f"Hurricane ({self.public_rating - 2200} points)"
            case _:
                return f"{self.league.alias} {self.division * 'I'} ({self.public_rating // 100} points)"

    @property
    def max_cb_rating(self) -> str:
        """Return a string in format League II (50 points)"""
        match self.max_league:
            case League.HURRICANE:
                return f"Hurricane ({self.max_public_rating - 2200} points)"
            case _:
                return f"{self.max_league.alias} {self.max_division * 'I'} ({self.max_public_rating // 100} points)"

    @property
    def treasury_rewards(self) -> str:
        """Get a list of available treasury operations for the clan"""
        tr = {1: "Allocation of resources only", 2: "Allocation of resources, 'More Resources' clan bundles",
              3: "Allocation of resources, 'More Resources' & 'Try Your Luck' clan bundles",
              4: "Allocation of resources, 'More Resources', 'Try Your Luck' & 'Supercontainer' clan bundles",
              5: "Allocation of resources & 'More Resources', 'Try Your Luck', 'Supercontainer' & 'additional' bundles"}
        return tr[len(self.treasury)]

    async def get_member_clan_battle_stats(self, season: int = None) -> dict:
        """Attempt to fetch clan battle stats for members"""
        if season is None:
            season = self.season_number

        url = f"https://clans.worldofwarships.{self.region.domain}/api/members/{self.clan_id}/"
        p = {'battle_type': 'cvc', 'season': season}

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    season_stats = await resp.json()
                case _:
                    raise ConnectionError(f'{resp.status} error accessing {url}')

        logging.info('DEBUG: Season Stats')
        logging.info(season_stats)

        for x in season_stats['items']:
            player = self.bot.get_player(x['id'])

            stats = PlayerCBStats()
            player.clan_battle_stats[season] = stats
            stats.win_rate = x['wins_percentage']
            stats.battles = x['battles_count']
            stats.average_damage = x['damage_per_battle']
            stats.average_kills = x['frags_per_battle']

    async def get_member_stats(self) -> dict:
        """Attempt to fetch clan battle stats for members"""
        url = f"https://clans.worldofwarships.{self.region.domain}/api/members/{self.clan_id}/"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    raise ConnectionError(f'Error {resp.status} fetching {url}')

        def parse_member(member: dict) -> Player:
            """Update Player Objects with available data from CB EndPoint"""
            player = self.bot.get_player(member['id'])
            player.clan = self

            # Account Info
            player.nickname = member['name']
            player.levelling_tier = member['rank']
            player.is_online = member['online_status']
            player.is_banned = member['is_banned']

            # Recent Activity
            lbt = member['last_battle_time']
            player.last_battle_time = Timestamp(datetime.utcfromtimestamp(lbt))

            # Averages
            player.hidden_profile = member['is_hidden_statistics']
            player.average_damage = member['damage_per_battle']
            player.average_xp = member['exp_per_battle']
            player.average_kills = member['frags_per_battle']
            player.battles_per_day = member['battles_per_day']
            player.win_rate = member['wins_percentage']

            # Totals
            player.battles = member['battles_count']
            player.oil = member['accumulative_clan_resource']
            return player

        self.members = [parse_member(member) for member in json.pop('items')]

    async def get_data(self) -> Clan:
        """Fetch clan information."""
        if self.clan_id is None:
            return self

        p = {'application_id': self.bot.WG_ID, 'clan_id': self.clan_id, 'extra': 'members'}
        url = f"https://api.worldofwarships.{self.region.domain}/wows/clans/info/"
        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    data: dict = await resp.json()
                case _:
                    return self

        data = data['data'].pop(str(self.clan_id))

        # Handle Timestamps.
        self.updated_at = Timestamp(datetime.utcfromtimestamp(data.pop('updated_at', None)))
        self.created_at = Timestamp(datetime.utcfromtimestamp(data.pop('created_at', None)))

        if (rn := data.pop('renamed_at', None)) is not None:
            self.renamed_at = Timestamp(datetime.utcfromtimestamp(rn))

        for x in ['league', 'max_league']:
            try:
                _x = data.pop(x)
                league = next(i for i in League if _x == i)
                setattr(self, x, league)
            except KeyError:
                pass

        def parse_player(pl: dict) -> Player:
            """Convert Dict to Player Objects"""
            player = self.bot.get_player(pl['account_id'])
            player.nickname = pl['account_name']
            player.joined_clan_at = Timestamp(datetime.utcfromtimestamp(pl['joined_at']))
            player.clan_role = pl['role']
            return player

        self.members = [parse_player(member) for member in data.pop('members').values()]

        # Handle rest.
        for k, v in data.items():
            setattr(self, k, v)

        url = f"https://clans.worldofwarships.{self.region.domain}/api/clanbase/{self.clan_id}/claninfo/"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                    json = data.pop('clanview')
                case _:
                    raise ConnectionError(f"Http Error {resp.status} fetching clans.warships api")

        # clan = json.pop('clan')  # This information is also already known to us

        ladder = json.pop('wows_ladder')  # This info we care about.
        if lbt := ladder.pop('last_battle_at', {}):
            self.current_winning_streak = ladder.pop('current_winning_streak', 0)
            self.longest_winning_streak = ladder.pop('longest_winning_streak', 0)
            self.leading_team_number: int = ladder.pop('leading_team_number', None)
            ts = datetime.strptime(lbt, "%Y-%m-%dT%H:%M:%S%z")
            self.last_battle_at = Timestamp(ts)

            if lwt := ladder.pop('last_win_at', {}):
                ts2 = datetime.strptime(lwt, "%Y-%m-%dT%H:%M:%S%z")
                self.last_win_at = Timestamp(ts2)

            self.wins_count = ladder.pop('wins_count', 0)
            self.battles_count = ladder.pop('battles_count', 0)
            self.total_battles_played = ladder.pop('total_battles_count', 0)

            self.season_number = ladder.pop('season_number', None)

            self.public_rating = ladder.pop('public_rating', None)
            self.max_public_rating = ladder.pop('max_public_rating', None)

            league = ladder.pop('league')
            self.league = next(i for i in League if i.value == league)

            if highest := ladder.pop('max_position', {}):
                self.max_league = next(i for i in League if i.value == highest.pop('league', None))
                self.max_division = highest.pop('division', None)

            self.division = ladder.pop('division', None)
            self.colour: Colour = Colour(ladder.pop('colour', 0x000000))

            if ratings := ladder.pop('ratings', []):
                self._clan_battle_history = []

            for x in ratings:
                if (season_id := x.pop('season_number', 999)) > 99:
                    continue  # Discard Brawls.

                season = ClanBattleStats(self, season_id)

                if maximums := x.pop('max_position', False):
                    max_league = maximums.pop('league')
                    season.max_league = next(i for i in League if i.value == max_league)
                    season.max_division = maximums.pop('division')
                    season.max_rating = maximums.pop('public_rating', 0)

                season.max_win_streak = x.pop('longest_winning_streak', 0)
                season.battles_played = x.pop('battles_count', 0)
                season.games_won = season.games_won + x.pop('wins_count', 0)

                if last := x.pop('last_win_at', {}):
                    season.last_win_at = last.strptime(lwt, "%Y-%m-%dT%H:%M:%S%z")

                season.final_rating = x.pop('public_rating', 0)
                season.final_league = next(i for i in League if i.value == x.pop('league', 4))
                season.final_division = x.pop('division', 3)

        if buildings := json.pop('buildings', {}):
            for k, v in buildings.items():
                setattr(self, k, v['modifiers'])
        return self

    # achievements = json.pop('achievements')  # This information is complete garbage.

    def view(self, interaction: Interaction, parent: View = None) -> ClanView:
        """Return a view representing this clan"""
        return ClanView(interaction, self, parent)


class ClanView(BaseView):
    """A View representing a World of Warships Clan"""
    bot: PBot = None

    def __init__(self, interaction: Interaction, clan: Clan, parent: tuple[View, str] = None) -> None:
        super().__init__()
        self.__class__.bot = interaction.client

        self.interaction: Interaction = interaction
        self.clan: Clan = clan
        self.embed: Optional[Embed] = None
        self.index: int = 0

        if parent:
            self.parent: View = parent[0]
            self.parent_name: str = parent[1]
        else:
            self.parent, self.parent_name = None, None

        self._disabled: Optional[str] = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide buttons on view timeout"""
        return await self.bot.reply(self.interaction, view=None)

    @property
    def base_embed(self) -> Embed:
        """Generic Embed for all view functions"""
        e = Embed(colour=self.clan.league.colour)
        e.set_author(name=f"[{self.clan.tag}] {self.clan.name}")
        e.set_thumbnail(url=self.clan.league.thumbnail)
        return e

    async def overview(self) -> Message:
        """Get General overview of the clan"""
        e = self.base_embed

        desc = []
        if self.clan.updated_at is not None:
            desc.append(f"**Information updated**: {self.clan.updated_at.relative}\n")

        if self.clan.leader_name:
            desc.append(f"**Leader**: {self.clan.leader_name}")

        if self.clan.created_at:
            desc.append(f"**Founder**: {self.clan.creator_name} ({self.clan.created_at.relative})")

        if self.clan.renamed_at:
            d = f"**Former name**: [{self.clan.old_tag}] {self.clan.old_name} ({self.clan.renamed_at.relative})"
            desc.append(d)

        if self.clan.season_number:
            title = f'Clan Battles Season {self.clan.season_number}'
            cb_desc = [f"**Current Rating**: {self.clan.cb_rating} ({self.clan.max_rating_name})"]

            if self.clan.cb_rating != self.clan.max_cb_rating:
                cb_desc.append(f"**Highest Rating**: {self.clan.max_cb_rating}")

            # Win Rate
            cb_desc.append(f"**Last Battle**: {self.clan.last_battle_at.relative}")
            wr = round(self.clan.wins_count / self.clan.battles_count * 100, 2)
            cb_desc.append(f"**Win Rate**: {wr}% ({self.clan.wins_count} / {self.clan.battles_count})")

            # Win streaks
            max_i = self.clan.longest_winning_streak
            if self.clan.current_winning_streak:
                if self.clan.current_winning_streak == max_i:
                    cb_desc.append(f'**Win Streak**: {self.clan.current_winning_streak}')
                else:
                    cb_desc.append(f'**Win Streak**: {self.clan.current_winning_streak} (Max: {max_i})')
            elif self.clan.longest_winning_streak:
                cb_desc.append(f'**Longest Win Streak**: {max_i}')

            e.add_field(name=title, value='\n'.join(cb_desc))

        e.set_footer(text=f"{self.clan.region.name} Clan #{self.clan.clan_id}")
        e.description = "\n".join(desc)

        if self.clan.is_banned:
            e.add_field(name='Banned Clan', value="This information is from a clan that is marked as 'banned'")

        self._disabled = self.overview
        e.set_footer(text=self.clan.description)
        return await self.update(embed=e)

    async def members(self) -> Message:
        """Display an embed of the clan members"""
        self._disabled = self.members
        e = self.base_embed
        e.title = f"Clan Members ({self.clan.members_count} Total)"

        members = sorted(self.clan.members, key=lambda x: x.nickname)
        members = [f'`🟢` {i.nickname}' if i.is_online else i.nickname for i in members if not i.is_banned]

        e.description = ', '.join(members).replace('_', '\\_')  # Discord formatting.

        if banned := [i for i in self.clan.members if i.is_banned]:
            e.add_field(name="Banned Members", value=', '.join(banned))

        # Clan Records:
        await self.clan.get_member_stats()

        c_wr = round(sum(c.win_rate for c in self.clan.members) / len(self.clan.members), 2)
        c_dmg = format(round(sum(c.average_damage for c in self.clan.members) / len(self.clan.members)), ',')
        c_xp = format(round(sum(c.average_xp for c in self.clan.members) / len(self.clan.members), 2), ',')
        c_kills = round(sum(c.average_kills for c in self.clan.members) / len(self.clan.members), 2)
        c_games = format(round(sum(c.battles for c in self.clan.members) / len(self.clan.members)), ',')
        c_gpd = round(sum(c.battles_per_day for c in self.clan.members) / len(self.clan.members), 2)
        e.add_field(name="Clan Averages",
                    value=f'**Win Rate**: {c_wr}%\n'
                          f'**Average Damage**: {c_dmg}\n'
                          f'**Average Kills**: {c_kills}\n'
                          f'**Average XP**: {c_xp}\n'
                          f'**Total Battles**: {c_games}\n'
                          f'**Battles Per Day**: {c_gpd}')

        max_damage: Player = max(self.clan.members, key=lambda p: p.average_damage)
        max_xp: Player = max(self.clan.members, key=lambda p: p.average_xp)
        max_wr: Player = max(self.clan.members, key=lambda p: p.win_rate)
        max_games: Player = max(self.clan.members, key=lambda p: p.battles)
        max_play: Player = max(self.clan.members, key=lambda p: p.battles_per_day)
        e.add_field(name="Top Players",
                    value=f'{round(max_wr.win_rate, 2)}% ({max_wr.nickname})\n'
                          f'{format(round(max_damage.average_damage), ",")} ({max_damage.nickname})\n'
                          f'{round(max_damage.average_kills, 2)} ({max_damage.nickname})\n'
                          f'{format(round(max_xp.average_xp), ",")} ({max_xp.nickname})\n'
                          f'{format(max_games.battles, ",")} ({max_games.nickname})\n'
                          f'{round(max_play.battles_per_day, 2)} ({max_play.nickname})')

        return await self.update(embed=e)

    async def history(self) -> Message:
        """Get a clan's Clan Battle History"""
        # https://clans.worldofwarships.eu/api/members/500140589/?battle_type=cvc&season=17
        # TODO: Clan Battle History
        self._disabled = self.history
        e = self.base_embed
        e.description = "```diff\n-Not Implemented Yet.```"
        return await self.update(embed=e)

    async def new_members(self) -> Message:
        """Get a list of the clan's newest members"""
        self._disabled = self.new_members
        e = self.base_embed
        e.title = "Newest Clan Members"
        members = sorted(self.clan.members, key=lambda x: x.joined_clan_at.value, reverse=True)
        e.description = '\n'.join([f"{i.joined_clan_at.relative}: {i.nickname}" for i in members[:10]])
        return await self.update(embed=e)

    async def from_dropdown(self) -> Message:
        """When initiated from a dropdown, we only have partial data, so we perform a fetch and then send to update"""
        self.clan = self.bot.get_clan(self.clan.clan_id)
        await self.clan.get_data()
        return await self.overview()

    async def update(self, embed: Embed) -> Message:
        """Push the latest version of the View to the user"""
        self.clear_items()

        if self.parent:
            self.add_item(Parent(label=self.parent_name))
        for i in [FuncButton(label='Overview', disabled=self._disabled == self.overview, func=self.overview),
                  FuncButton(label='Members', disabled=self._disabled == self.members, func=self.members),
                  FuncButton(label='New Members', disabled=self._disabled == self.new_members, func=self.new_members)]:
            # FuncButton(label='CB Season History', disabled=self._disabled == self.history, func=self.history)
            self.add_item(i)
        return await self.bot.reply(self.interaction, embed=embed, view=self)


class Leaderboard(BaseView):
    """Leaderboard View with dropdowns."""
    bot: ClassVar[PBot] = None

    def __init__(self, interaction: Interaction, clans: list[Clan]) -> None:
        super().__init__()

        self.interaction: interaction = interaction
        self.index: int = 0  # Pages.
        self.pages: list[Embed] = []  # Embeds
        self.clans: list[Clan] = clans  # Rank, Clan

        self.__class__.bot = interaction.client

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Only invoker may browse data."""
        return self.interaction.user.id == interaction.user.id

    async def update(self) -> Message:
        """Push the latest version of the view to the user"""
        self.clear_items()

        e = Embed(title=f"Clan Battle Season {self.clans[0].season_number} Ranking", colour=Colour.purple())
        e.set_thumbnail(url=League.HURRICANE.thumbnail)

        rows = []
        opts = []
        for num, clan in enumerate(self.clans):
            r = '⛔' if clan.is_clan_disbanded else str(clan.public_rating)
            rank = f"#{clan.rank}."
            region = clan.region

            rows.append(f"{rank} {region.emote} **[{clan.tag}]** {clan.name}\n"
                        f"`{r.rjust(4)}` {clan.battles_count} Battles, Last: {clan.last_battle_at.relative}\n")

            opt = SelectOption(label=f"{clan.tag} ({clan.region.name})", description=clan.name, emoji=clan.league.emote,
                               value=str(num))

            v = clan.view(self.interaction, parent=(self, "Back to Leaderboard"))
            opts.append((opt, {}, v.from_dropdown))

        self.pages = rows_to_embeds(e, rows)

        add_page_buttons(self)
        self.add_item(FuncDropdown(options=opts, placeholder="View Clan Info"))
        return await self.bot.reply(self.interaction, embed=self.pages[self.index], view=self)
