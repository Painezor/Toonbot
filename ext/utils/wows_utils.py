"""Utilities for World of Warships related commands."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Tuple, Callable

from discord import Colour, Embed, Message, SelectOption
from discord.ui import View, Button

from ext.utils.ship import Ship
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import FuncButton, FuncDropdown, Parent

if TYPE_CHECKING:
    from painezBot import PBot
    from discord import Interaction
    from typing import List
    from typing_extensions import Self

# TODO: CommanderXP Command (Show Total Commander XP per Rank)
# TODO: Encyclopedia - Collections
# TODO: Pull Achievement Data to specifically get Jolly Rogers and Hurricane Emblems for player stats.
# TODO: Player's Ranked Battle Season History
# TODO: Player's Stats By Ship
# TODO: Secret Clan API endpoint - Leaderboard.
# Leaderboard: https://clans.worldofwarships.com/api/ladder/structure/?league=0&division=1&season=17&realm=global


class Achievement:
    """A World of Warships Achievement"""


class ClanBuilding:
    """A World of Warships Clan Building"""


class Map:
    """A Generic container class representing a map"""

    def __init__(self, name: str, description: str, battle_arena_id: int, icon: str) -> None:
        self.name: str = name
        self.description: str = description
        self.battle_arena_id = battle_arena_id
        self.icon: str = icon

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    @property
    def ac_row(self) -> str:
        """Autocomplete row for this map"""
        return f"{self.name}: {self.description}"

    @property
    def embed(self) -> Embed:
        """Return an embed representing this map"""
        e = Embed(title=self.name, colour=Colour.greyple())
        e.set_image(url=self.icon)
        e.set_footer(text=self.description)
        return e


class GameMode:
    """"An Object representing different Game Modes"""

    def __init__(self, image: str, tag: str, name: str, description: str) -> None:
        self.tag: str = tag
        self.name: str = name
        self.image: str = image
        self.description: str = description

    @property
    def emoji(self) -> Optional[str]:
        """Get the Emoji Representation of the game mode."""
        return {'BRAWL': '<:Brawl:989921560901058590>', 'CLAN': '<:Clan:989921285918294027>',
                'COOPERATIVE': '<:Coop:989844738800746516>', 'EVENT': '<:Event:989921682007420938>',
                'PVE': '<:Scenario:989921800920109077>', 'PVE_PREMADE': '<:Scenario_Hard:989922089303687230>',
                'PVP': '<:Randoms:988865875824222338>', 'RANKED': '<:Ranked:989845163989950475>'
                }.get(self.tag, None)


class Region(Enum):
    """A Generic object representing a region"""

    def __new__(cls, *args, **kwargs) -> Region:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, db_key: str, url: str, emote: str, colour: Colour, code_prefix: str) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: Colour = colour
        self.code_prefix: str = code_prefix

    # TODO: Web links command
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
        return f"https://clans.worldofwarships.{self.domain}/clans/gateway/wows/profile"

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
        """Return a link to the 'Dockyard' page"""
        return f"https://worldofwarships.{self.domain}/news_ingame"

    @property
    def recruiting(self) -> str:
        """Return a link to the 'Recruiting Station' page"""
        return f"https://friends.worldofwarships.{self.domain}/en/players/"

    @property
    def how_it_works(self) -> str:
        """Return a link to the How it Works Series"""
        return f"https://worldofwarships.{self.domain}/en/content/in-game/education/?consumer=game-browser"

    # database key, domain, emote, colour, code prefix
    EU = ('eu', 'eu', "<:painezBot:928654001279471697>", 0x0000ff, 'eu')
    NA = ('na', 'com', "<:Bonk:746376831296471060>", 0x00ff00, 'na')
    SEA = ('sea', 'asia', "<:painezRaid:928653997680754739>", 0x00ffff, 'asia')
    CIS = ('cis', 'ru', "<:Button:826154019654991882>", 0xff0000, 'ru')


class Player:
    """A World of Warships player."""
    bot: PBot = None

    def __init__(self, bot: 'PBot', account_id: int, region: Region, nickname: str) -> None:
        self.bot: PBot = bot
        self.nickname: str = nickname
        self.account_id: int = account_id
        self.region: Region = region

        # Additional Fetched Data.
        self.clan: Optional[Clan] = None
        self.created_at: Optional[Timestamp] = None  # Account Creation Date
        self.hidden_profile: bool = False  # Account has hidden stats
        self.joined_clan_at: Optional[Timestamp] = None  # Joined Clan at..
        self.karma: Optional[int] = None  # Player Karma (Hidden from API?)
        self.last_battle_time: Optional[Timestamp] = None  # Last Battle
        self.private: None = None  # Player's private data. We do not have access.
        self.levelling_tier: Optional[int] = None  # Player account level
        self.levelling_points: Optional[int] = None  # Player account XP
        self.logout_at: Optional[Timestamp] = None  # Last Logout
        self.stats_updated_at: Optional[Timestamp] = None  # Last Stats Update
        self.statistics: dict = {}  # Parsed Player Statistics

    async def get_pr(self) -> int:
        """Calculate a player's personal rating"""
        if not self.bot.pr_data_updated_at:
            async with self.bot.session.get('https://api.wows-numbers.com/personal/rating/expected/json/') as resp:
                match resp.status:
                    case 200:
                        pass
                    case _:
                        print('Error accessing PR data on wows-numbers')
                        return
        # TODO: Get PR
        raise NotImplementedError

    async def get_clan_info(self, region: Region) -> Optional[Clan]:
        """Get Player's clan"""
        link = f"https://api.worldofwarships.{region.domain}/wows/clans/accountinfo/"
        p = {'application_id': self.bot.WG_ID, 'account_id': self.account_id, 'extras': 'clan'}

        async with self.bot.session.get(link, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    return None

        data = json['data'].pop(str(self.account_id))
        if data is None:
            self.clan = False
            return None

        self.joined_clan_at = Timestamp(datetime.utcfromtimestamp(data.pop('joined_at')))

        clan_id = data.pop('clan_id')
        self.clan = await self.bot.get_clan(clan_id, region)
        return self.clan

    async def get_stats(self, ship: Ship = None) -> None:
        """Get the player's stats as a dict"""
        p = {'application_id': self.bot.WG_ID, 'account_id': self.account_id}

        if ship is None:
            url = f"https://api.worldofwarships.{self.region.domain}/wows/account/info/"
        else:
            url = f'https://api.worldofwarships.{self.region.domain}/wows/ships/stats/'
            p.update({'ship_id': ship.ship_id})

        p.update({'extra': 'statistics.pvp_solo,'
                           'statistics.pvp_div2, '
                           'statistics.pvp_div3, '
                           'statistics.rank_solo, '
                           'statistics.rank_div2, '
                           'statistics.rank_div3, '
                           'statistics.pve, '
                           'statistics.pve_div2, '
                           'statistics.pve_div3, '
                           'statistics.pve_solo, '
                           'statistics.oper_solo, '
                           'statistics.oper_div, '
                           'statistics.oper_div_hard'})

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    try:
                        raise ConnectionError(resp.status)
                    finally:
                        return []

        stats = json['data'].pop(str(self.account_id))  # Why the fuck is this randomly a string now, seriously WG?

        self.created_at = Timestamp(datetime.utcfromtimestamp(stats.pop('created_at', None)))
        self.last_battle_time = Timestamp(datetime.utcfromtimestamp(stats.pop('last_battle_time', None)))
        self.stats_updated_at = Timestamp(datetime.utcfromtimestamp(stats.pop('stats_updated_at', None)))
        self.logout_at = Timestamp(datetime.utcfromtimestamp(stats.pop('logout_at', None)))
        self.hidden_profile = stats.pop('hidden_profile', False)
        self.statistics = stats.pop('statistics')
        return

    def view(self, interaction: Interaction, mode: GameMode, div_size: int) -> PlayerView:
        """Return a PlayerVIew of this Player"""
        return PlayerView(self.bot, interaction, self, mode, div_size)


class League(Enum):
    """Enum of Clan Battle Leagues"""

    def __new__(cls, *args, **kwargs) -> League:
        value = len(cls.__members__)
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, alias: str, emote: str, colour: Colour) -> None:
        self.alias: str = alias
        self.emote: str = emote
        self.colour: Colour = colour

    HURRICANE = ('Hurricane', '<:Hurricane:990599761574920332>', 0xCDA4FF)
    TYPHOON = ('Typhoon', '<:Typhoon:990599751584067584>', 0xBEE7BD)
    STORM = ('Storm', '<:Storm:990599740079104070>', 0xE3D6A0)
    GALE = ('Gale', "<:Gale:990599200905527329>", 0xCCE4E4)
    SQUALL = ('Squall', "<:Squall:990597783817965568>", 0xCC9966)


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


class ClanButton(Button):
    """Change to a view of a different ship"""

    def __init__(self, interaction: Interaction, clan: Clan, row: int = 0) -> None:
        super().__init__(label=f"[{clan.tag}]", row=row)

        self.clan: Clan = clan
        self.interaction: Interaction = interaction
        self.emoji = self.clan.league.emote

    async def callback(self, interaction: Interaction) -> Message:
        """Change message of interaction to a different ship"""
        await interaction.response.defer()
        return await self.clan.view(self.interaction).overview()


class Clan:
    """A World of Warships clan."""
    bot: PBot = None

    def __init__(self, bot: 'PBot', clan_id: int, region: Region, **kwargs):
        self.clan_id: int = clan_id
        self.bot: PBot = bot

        self.clan_id: int = clan_id
        self.created_at: Optional[Timestamp] = kwargs.pop('created_at', None)
        self.creator_id: Optional[int] = kwargs.pop('creator_id', None)
        self.creator_name: Optional[str] = kwargs.pop('creator_name', None)
        self.description: Optional[str] = kwargs.pop('description', None)
        self.is_clan_disbanded: Optional[bool] = kwargs.pop('is_clan_disbanded', None)
        self.leader_name: Optional[str] = kwargs.pop('leader_name', None)
        self.leader_id: Optional[int] = kwargs.pop('leader_id', None)
        self.members_count: Optional[int] = kwargs.pop('members_count', None)
        self.member_ids: Optional[List[int]] = kwargs.pop('member_ids', None)
        self.name: Optional[str] = kwargs.pop('name', None)
        self.old_name: Optional[str] = kwargs.pop('old_name', None)
        self.old_tag: Optional[str] = kwargs.pop('old_tag', None)
        self.renamed_at: Optional[Timestamp] = kwargs.pop('renamed_at', None)
        self.region: Region = region
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
        self.league: Optional[League] = None  # Current League, 0 is Hurricane, 1 is Typhoon...
        self.division: Optional[int] = None  # Current Division within League
        self.max_public_rating: Optional[int] = None  # Highest rating this season
        self.max_league: Optional[League] = None  # Max League
        self.max_division: Optional[int] = None  # Max Division
        self.colour: Colour = None  # Converted to discord Colour for Embed
        self.is_banned: bool = False  # Is the Clan banned?
        self.is_qualified: bool = False  # In qualifications?

        # List of Clan Building IDs
        self.academy: List[int] = []  # Academy - Commander XP
        self.dry_dock: List[int] = []  # Service Cost Reduction
        self.design_department: List[int] = []  # Design Bureau - Free XP
        self.headquarters: List[int] = []  # Officers' Club - Members Count
        self.shipbuilding_factory: List[int] = []  # Shipbuilding yard - Purchase Cost Discount
        self.coal_yard: List[int] = []  # Bonus Coal
        self.steel_yard: List[int] = []  # Bonus Steel
        self.university: List[int] = []  # War College - Bonus XP
        self.paragon_yard: List[int] = []  # Research Institute - Research Points

        # Vanity Only.
        self.monument: List[int] = []  # Rostral Column - Can be clicked for achievements.
        self.vessels: List[int] = []  # Other Vessels in port, based on number of clan battles
        self.ships: List[int] = []  # Ships in clan base, based on number of randoms played.
        self.treasury: List[int] = []  # Clan Treasury

        # Fetched and stored.
        self._clan_battle_history: List[ClanBattleStats] = []  # A list of ClanBattleSeason dataclasses
        self.members: List[Player] = []

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

    async def get_member_stats(self) -> None:
        """Fetch Data about all clan members"""
        missing = []
        for x in self.member_ids:
            (missing, self.members)[x in [p.account_id for p in self.bot.players]].append(x)

        # TODO: API call - fetch data for missing player IDs

    async def get_data(self) -> Self:
        """Fetch clan information."""
        if self.clan_id is None:
            return self

        p = {'application_id': self.bot.WG_ID, 'clan_id': self.clan_id}
        url = f"https://api.worldofwarships.{self.region.domain}/wows/clans/info/"
        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                case _:
                    return self

        data = data['data'].pop(str(self.clan_id))

        # Handle Timestamps.
        self.updated_at = Timestamp(datetime.utcfromtimestamp(data.pop('updated_at', None)))
        self.created_at = Timestamp(datetime.utcfromtimestamp(data.pop('created_at', None)))

        rn = data.pop('renamed_at', None)
        if rn is not None:
            self.renamed_at = Timestamp(datetime.utcfromtimestamp(rn))

        for x in ['league', 'max_league']:
            _x = data.pop(x, None)

            if _x is not None:
                league = next(i for i in League if _x == i)
                setattr(self, x, league)

        # Handle rest.
        for k, v in data.items():
            setattr(self, k, v)

        await self.fetch_cb_data()
        return self

    async def fetch_cb_data(self):
        """Fetch CB data from the hidden clans.worldofwarships api"""
        if self.clan_id is None:
            return

        url = f"https://clans.worldofwarships.{self.region.domain}/api/clanbase/{self.clan_id}/claninfo/"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                    json = data.pop('clanview')
                case _:
                    print(f"Http Error {resp.status} fetching clans.warships api")

        # clan = json.pop('clan')  # This information is also already known to us

        ladder = json.pop('wows_ladder')  # This info we care about.
        lbt = ladder.pop('last_battle_at', None)
        if lbt is not None:
            self.current_winning_streak = ladder.pop('current_winning_streak', 0)
            self.longest_winning_streak = ladder.pop('longest_winning_streak', 0)
            self.leading_team_number: int = ladder.pop('leading_team_number', None)
            ts = datetime.strptime(lbt, "%Y-%m-%dT%H:%M:%S%z")
            self.last_battle_at = Timestamp(ts)

            lwt = ladder.pop('last_win_at', None)
            ts2 = datetime.strptime(lwt, "%Y-%m-%dT%H:%M:%S%z")
            self.last_win_at = Timestamp(ts2)

            self.wins_count = ladder.pop('wins_count', 0)
            self.total_battles_played = ladder.pop('total_battles_count', 0)

            self.season_number = ladder.pop('season_number', None)

            self.public_rating = ladder.pop('public_rating', None)
            self.max_public_rating = ladder.pop('max_public_rating', None)

            league = ladder.pop('league')
            self.league = next(i for i in League if i.value == league)

            highest = ladder.pop('max_position', {})
            if highest:
                max_league = highest.pop('league', None)
                self.max_league = next(i for i in League if i.value == max_league)
                self.max_division = highest.pop('division', None)

            self.division = ladder.pop('division', None)
            self.colour: Colour = Colour(ladder.pop('colour', 0x000000))

            ratings = ladder.pop('ratings', [])

            if ratings:
                self._clan_battle_history = []

            for x in ratings:
                season_id = x.pop('season_number', 999)
                if season_id > 99:
                    continue  # Discard Brawls.

                try:
                    season = next(i for i in self._clan_battle_history if i.season_id == season_id)
                except StopIteration:
                    season = ClanBattleStats(self, season_id)

                maximums = x.pop('max_position', None)
                if maximums is not None:
                    max_league = min(season.max_league.value, maximums.pop('league'), 4)
                    season.max_league = next(i for i in League if i.value == max_league)
                    season.max_division = min(season.max_division, maximums.pop('division'), 3)
                    season.max_rating = max(season.max_rating, maximums.pop('public_rating', 0))

                season.max_win_streak = max(season.max_win_streak, x.pop('longest_winning_streak', 0))
                season.battles_played = season.battles_played + x.pop('battles_count', 0)
                season.games_won = season.games_won + x.pop('wins_count', 0)

                last = x.pop('last_win_at', None)
                ts3 = datetime.fromordinal(1) if last is None else datetime.strptime(lwt, "%Y-%m-%dT%H:%M:%S%z")

                if season.last_win_at is None or season.last_win_at < ts3:
                    season.final_rating = x.pop('public_rating', 0)
                    season.final_league = next(i for i in League if i.value == x.pop('league', 4))
                    season.final_division = x.pop('division', 3)

        buildings = json.pop('buildings', None)
        if buildings is not None:
            for k, v in buildings.items():
                setattr(self, k, v['modifiers'])

        # achievements = json.pop('achievements')  # This information is complete garbage.

    def view(self, interaction: Interaction) -> ClanView:
        """Return a view representing this clan"""
        return ClanView(self.bot, interaction, self)


class ClanView(View):
    """A View representing a World of Warships Clan"""
    bot: PBot = None

    def __init__(self, bot: 'PBot', interaction: Interaction, clan: Clan, parent: Tuple[View, str] = None) -> None:
        super().__init__()
        self.bot: PBot = bot
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
        e = Embed(title=f"[{self.clan.tag}] {self.clan.name}")
        e.colour = self.clan.league.colour
        e.set_footer(text=self.clan.description)
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
            desc.append(f"**Creator**: {self.clan.creator_name} {self.clan.created_at.relative}")

        if self.clan.renamed_at:
            d = f"**Former name**: [{self.clan.old_tag}] {self.clan.old_name} (renamed {self.clan.renamed_at.relative})"
            desc.append(d)

        if self.clan.season_number:
            title = f'Clan Battles Season {self.clan.season_number}'
            cb_desc = [f"**Current Rating**: {self.clan.cb_rating} ({self.clan.max_rating_name})"]

            if self.clan.cb_rating != self.clan.max_cb_rating:
                cb_desc.append(f"**Highest Rating**: {self.clan.max_cb_rating}")

            # Win Rate
            cb_desc.append(f"**Last Battle**: {self.clan.last_battle_at.relative}")
            wr = round(self.clan.wins_count / self.clan.total_battles_played * 100, 2)
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
        return await self.update(embed=e)

    async def members(self) -> Message:
        """Display an embed of the clan members"""
        # TODO: Clan Members
        # self.members_count: Optional[int] = kwargs.pop('members_count', None)
        # self.member_ids: Optional[List[int]] = kwargs.pop('member_ids', None)
        self._disabled = self.members
        e = self.base_embed
        e.description = "Not Implemented Yet."
        return await self.update(embed=e)

    async def history(self) -> Message:
        """Get a clan's Clan Battle History"""
        # TODO: Clan History
        self._disabled = self.history
        e = self.base_embed
        e.description = "Not Implemented Yet."
        return await self.update(embed=e)

    async def update(self, embed: Embed) -> Message:
        """Push the latest version of the View to the user"""
        self.clear_items()

        if self.parent:
            self.add_item(Parent(label=self.parent_name))

        self.add_item(FuncButton(label='Overview', disabled=self._disabled == self.overview, func=self.overview))
        self.add_item(FuncButton(label='Members', disabled=self._disabled == self.members, func=self.members))
        self.add_item(FuncButton(label='Recent Battles', disabled=self._disabled == self.history, func=self.history))
        return await self.bot.reply(self.interaction, embed=embed, view=self)


class PlayerView(View):
    """A View representing a World of Warships player"""
    bot: PBot = None

    def __init__(self, bot: 'PBot', interaction: Interaction, player: Player, mode: GameMode, div_size: int) -> None:
        super().__init__()
        self.bot: PBot = bot
        self.interaction: Interaction = interaction

        # Passed
        self.player: Player = player
        self.div_size: int = div_size
        self.mode: GameMode = mode

        # Generated
        self._disabled: Optional[Callable] = None
        self.embed: Embed = self.base_embed

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide buttons on view timeout"""
        return await self.bot.reply(self.interaction, view=None)

    @property
    def base_embed(self) -> Embed:
        """Base Embed used for all sub embeds."""
        e = Embed()
        if self.player.clan is not None:
            e.set_author(name=f'[{self.player.clan.tag}] {self.player.nickname} ({self.player.region.name})')
        else:
            e.set_author(name=f'{self.player.nickname} ({self.player.region.name})')

        e.set_thumbnail(url=self.mode.image)

        if self.player.hidden_profile:
            e.set_footer(text="This player has hidden their stats.")
        return e

    async def filter_stats(self) -> Tuple[str, dict]:
        """Fetch the appropriate stats for the mode tag"""
        if not self.player.statistics:
            await self.player.get_stats()

        match self.mode.tag, self.div_size:
            case "PVP", 1:
                return "Random Battles (Solo)", self.player.statistics['pvp_solo']
            case "PVP", 2:
                return "Random Battles (2-person Division)", self.player.statistics['pvp_div2']
            case "PVP", 3:
                return "Random Battles (3-person Division)", self.player.statistics['pvp_div3'],
            case "PVP", _:
                return "Random Battles (Overall)", self.player.statistics['pvp']
            case "COOPERATIVE", 1:
                return "Co-op Battles (Solo)", self.player.statistics['pve_solo']
            case "COOPERATIVE", 2:
                return "Co-op Battles (2-person Division)", self.player.statistics['pve_div2']
            case "COOPERATIVE", 3:
                return "Co-op Battles (3-person Division)", self.player.statistics['pve_div3']
            case "COOPERATIVE", _:  # All Stats.
                return "Co-op Battles (Overall)", self.player.statistics['pve']
            case "RANKED", 1:
                return "Ranked Battles (Solo)", self.player.statistics['rank_solo']
            case "RANKED", 2:
                return "Ranked Battles (2-Man Division)", self.player.statistics['rank_div2']
            case "RANKED", 3:
                return "Ranked Battles (3-Man Division)", self.player.statistics['rank_div3']
            case "RANKED", 0:  # Sum 3 Dicts.
                x = self.player.statistics['rank_solo']
                y = self.player.statistics['rank_div2']
                z = self.player.statistics['rank_div3']
                d = {x.get(k, 0) + y.get(k, 0) + z.get(k, 0) for k in set(x) | set(y) | set(z)}
                return "Ranked Battles (Overall)", d
            case "PVE", 0:  # Sum 2 dicts
                x = self.player.statistics['oper_solo']
                y = self.player.statistics['oper_div']
                return "Operations (Overall)", {x.get(k, 0) + y.get(k, 0) for k in set(x) | set(y)}
            case "PVE", 1:
                return "Operations (Solo)", self.player.statistics['oper_solo']
            case "PVE", _:
                return "Operations (Pre-made)", self.player.statistics['oper_div']
            case "PVE_PREMADE", _:
                return "Operations (Hard Pre-Made)", self.player.statistics['oper_div_hard']
            case _:
                return f"Missing info for {self.mode.tag}, {self.div_size}", self.player.statistics['pvp']

    async def weapons(self) -> Message:
        """Get the Embed for a player's weapons breakdown"""
        e = self.base_embed
        e.title, p_stats = await self.filter_stats()

        mb = p_stats.pop('main_battery', {})
        if mb:
            mb_kills = mb.pop('frags')
            mb_ship = await self.bot.get_ship(mb.pop('max_frags_ship_id'))
            mb_max = mb.pop('max_frags_battle')
            mb_shots = mb.pop('shots')
            mb_hits = mb.pop('hits')
            mb_acc = round(mb_hits / mb_shots * 100, 2)
            mb = f"Kills: {format(mb_kills, ',')} (Max: {mb_max} - {mb_ship.name})\n" \
                 f"Accuracy: {mb_acc}% ({format(mb_hits, ',')} hits / {format(mb_shots, ',')} shots)"
            e.add_field(name='Main Battery', value=mb, inline=False)

        # Secondary Battery
        sb = p_stats.pop('second_battery', {})
        if sb:
            sb_kills = sb.pop('frags', 0)
            sb_ship = await self.bot.get_ship(sb.pop('max_frags_ship_id', None))
            sb_max = sb.pop('max_frags_battle', 0)
            sb_shots = sb.pop('shots', 0)
            sb_hits = sb.pop('hits', 0)
            sb_acc = round(sb_hits / sb_shots * 100, 2)
            sb = f"Kills: {format(sb_kills, ',')} (Max: {sb_max} - {sb_ship.name})\n" \
                 f"Accuracy: {sb_acc}% ({format(sb_hits, ',')} hits / {format(sb_shots, ',')} shots)"
            e.add_field(name='Secondary Battery', value=sb, inline=False)

        # Torpedoes
        trp = p_stats.pop('torpedoes', None)
        if trp is not None:
            trp_kills = trp.pop('frags')
            trp_ship = await self.bot.get_ship(trp.pop('max_frags_ship_id', None))
            trp_max = trp.pop('max_frags_battle', 0)
            trp_shots = trp.pop('shots', 0)
            trp_hits = trp.pop('hits', 0)
            trp_acc = round(trp_hits / trp_shots * 100, 2)
            trp = f"Kills: {format(trp_kills, ',')} (Max: {trp_max} - {trp_ship.name})\n" \
                  f"Accuracy: {trp_acc}% ({format(trp_hits, ',')} hit / {format(trp_shots, ',')} launched)"
            e.add_field(name='Torpedoes', value=trp, inline=False)

        # Ramming
        ram = p_stats.pop('ramming', None)
        if ram is not None:
            ram_ship = await self.bot.get_ship(ram.pop('max_frags_ship_id', None))
            ram = f"Kills: {ram.pop('frags', 0)} (Max: {ram.pop('max_frags_battle', 0)} - {ram_ship.name})\n"
            e.add_field(name='Ramming', value=ram)

        # Aircraft
        cv = p_stats.pop('aircraft', {})
        if cv:
            cv_ship = await self.bot.get_ship(cv.pop('max_frags_ship_id'))
            cv = f"Kills: {cv.pop('frags')} (Max: {cv.pop('max_frags_battle')} - {cv_ship.name})\n"
            e.add_field(name='Aircraft', value=cv)

        # Build the second embed.
        desc = []

        try:
            cap_solo = p_stats.pop('control_captured_points')
            cap_team = p_stats.pop('team_capture_points')
            cap_rate = round(cap_solo / cap_team * 100, 2)
            desc.append(f"Capture Contribution: {cap_rate}% ({format(cap_solo, ',')} / {format(cap_team, ',')})")
        except (KeyError, ZeroDivisionError):
            pass

        try:
            def_solo = p_stats.pop('control_dropped_points', 0)
            def_team = p_stats.pop('team_dropped_capture_points', 0)
            def_rate = round(def_solo / def_team * 100, 2)
            desc.append(f"Defence Contribution: {def_rate}% ({format(def_solo, ',')} / {format(def_team, ',')})")
        except (KeyError, ZeroDivisionError):
            pass

        # Capture Points & Defends, Distance Travelled
        e.description = '\n'.join(desc)
        self._disabled = self.weapons
        return await self.update(e)

    async def overview(self) -> Message:
        """Generate the stats embeds"""
        desc = []  # Build The description piecemeal then join at the very end.
        e = self.base_embed
        e.title, p_stats = await self.filter_stats()

        if self.player.clan is None:
            await self.player.get_clan_info(self.player.region)

        if self.player.stats_updated_at is not None:
            desc.append(f"**Stats updated**: {self.player.stats_updated_at.relative}\n")

        if self.player.created_at is not None:
            desc.append(f"**Account Created**: {self.player.created_at.relative}")

        if self.player.last_battle_time is not None:
            desc.append(f"**Last Battle**: {self.player.last_battle_time.relative}")

        if self.player.logout_at is not None:
            desc.append(f"**Last Logout**: {self.player.logout_at.relative}")

        distance = self.player.statistics['distance']  # This is stored 1 level up.
        desc.append(f"**Total Distance Travelled**: {format(distance, ',')}km")

        if self.player.clan:
            clan = self.player.clan
            c_desc = []
            if clan.cb_rating is not None:
                c_desc.append(f"**Rating**: {clan.cb_rating}")

            c_desc.append(f"**Joined Date**: {self.player.joined_clan_at.relative}")

            if clan.old_name is not None:
                c_desc.append(f"**Old Name**: [{clan.old_tag}] {clan.old_name}")
                c_desc.append(f"**Renamed**: {clan.renamed_at.relative}")
            e.add_field(name=f"[{clan.tag}] {clan.name}", value='\n'.join(c_desc), inline=False)

        e.description = '\n'.join(desc)
        self._disabled = self.overview
        return await self.update(embed=e)

    async def mode_stats(self):
        """Get the player's stats for the specific game mode"""
        # Don't remove data from original player object.
        e = self.base_embed
        desc = []

        e.title, p_stats = await self.filter_stats()

        p_stats = deepcopy(p_stats)
        # Overall Rates - Survival, WR, Wins, Loss, Draw
        survived = p_stats.pop('survived_battles', 0)
        suv_wins = p_stats.pop('survived_wins', 0)
        played = p_stats.pop('battles', 0)
        wins = p_stats.pop('wins', 0)
        losses = p_stats.pop('losses', 0)
        draws = p_stats.pop('draws', 0)

        try:
            wr = round(wins / played * 100, 2)
            desc.append(f"**Win Rate**: {wr}% ({played} Battles - {wins} W / {draws} D / {losses} L)  ")
        except ZeroDivisionError:
            pass

        try:
            sr = round(survived / played * 100, 2)
            desc.append(f"**Survival Rate (Overall)**: {sr}% (Total: {survived})")
        except ZeroDivisionError:
            pass

        try:
            swr = round(suv_wins / wins * 100, 2)
            desc.append(f"**Survival Rate (Wins)**: {swr}% (Total: {suv_wins})")
        except ZeroDivisionError:
            pass

        # Totals
        dmg = p_stats.pop('damage_dealt', 0)
        kills = p_stats.pop('frags', 0)
        tot_xp = p_stats.pop('xp', 0)
        spotted = p_stats.pop('ships_spotted', 0)
        spotting = p_stats.pop('damage_scouting', 0)
        potential = p_stats.pop('torpedo_agro', 0) + p_stats.pop('art_agro', 0)
        planes = p_stats.pop('planes_killed', 0)

        # Averages - Kills, Damage, Spotting, Potential
        d_avg = format(round(dmg / played), ',')
        k_avg = round(kills / played, 2)
        x_avg = format(round(tot_xp / played), ',')
        p_avg = format(round(potential / played), ',')
        s_avg = format(round(spotting / played), ',')
        sp_av = format(round(spotted / played, 2), ',')
        pl_av = round(planes / played, 2)

        avg = (f"**Kills**: {k_avg}\n**Damage**: {d_avg}\n**Potential**: {p_avg}\n**Spotting**: {s_avg}\n"
               f"**Ships Spotted**: {sp_av}\n**XP**: {x_avg}\n**Planes**: {pl_av}")
        e.add_field(name="Averages", value=avg)

        # Records
        r_dmg = format(p_stats.pop('max_damage_dealt', 0), ',')
        s_dmg = await self.bot.get_ship(p_stats.pop('max_damage_dealt_ship_id', None))

        r_xp = format(p_stats.pop('max_xp', 0), ',')
        s_xp = await self.bot.get_ship(p_stats.pop('max_xp_ship_id', None))

        r_kills = p_stats.pop('max_frags_battle', 0)
        s_kills = await self.bot.get_ship(p_stats.pop('max_frags_ship_id', None))

        r_pot = format(p_stats.pop('max_total_agro', 0), ',')
        s_pot = await self.bot.get_ship(p_stats.pop('max_total_agro_ship_id', None))

        r_spot = format(p_stats.pop('max_damage_scouting', 0), ',')

        _ship = p_stats.pop('max_scouting_damage_ship_id', None)
        s_spot = await self.bot.get_ship(_ship)

        r_ship_max = p_stats.pop('max_ships_spotted', 0)
        s_ship_max = await self.bot.get_ship(p_stats.pop('max_ships_spotted_ship_id', None))

        r_planes = p_stats.pop('max_planes_killed', 0)
        s_planes = await self.bot.get_ship(p_stats.pop('max_planes_killed_ship_id', None))

        # Operations specific stats.
        try:
            star_rate = [(k, v) for k, v in p_stats.pop('wins_by_tasks').items()]
            star_rate = sorted(star_rate, key=lambda st: st[1], reverse=True)

            star_desc = []
            for x in range(0, 5):
                star_desc.append(f"{(x * '⭐').ljust(5, '★')}: {star_rate[str(x)]}")

            e.add_field(name="Star Breakdown", value="\n".join(star_desc))
        except KeyError:
            pass

        # Records, Totals
        e.add_field(name="Records",
                    value=f"{r_kills} ({s_kills.name})\n"
                          f"{r_dmg} ({s_dmg.name})\n"
                          f"{r_pot} ({s_pot.name})\n"
                          f"{r_spot} ({s_spot.name})\n"
                          f"{r_ship_max} ({s_ship_max.name})\n"
                          f"{r_xp} ({s_xp.name})\n"
                          f"{r_planes} ({s_planes.name})")

        e.add_field(name="Totals", value=f"{format(kills, ',')}\n{format(dmg, ',')}\n{format(potential, ',')}\n"
                                         f"{format(spotting, ',')}\n{format(spotted, ',')}\n{format(tot_xp, ',')}\n"
                                         f"{format(planes, ',')}")
        return await self.update(embed=e)

    async def update(self, embed: Embed) -> Message:
        """Send the latest version of the embed to view"""
        self.clear_items()
        self.add_item(FuncButton(func=self.overview, label="Profile", disabled=self._disabled == self.overview, row=0))

        if self.player.clan:
            self.add_item(ClanButton(self.interaction, self.player.clan))

        self.add_item(FuncButton(func=self.weapons, label="Weapons", disabled=self._disabled == self.weapons, row=0))

        f = self.mode_stats
        opt, attrs, funcs = [], [], []
        for num, i in enumerate(self.bot.modes):
            if i.tag in ["EVENT", "BRAWL", "PVE_PREMADE"]:
                continue  # Not In API

            opt.append(SelectOption(label=f"{i.name} ({i.tag})", description=i.description, emoji=i.emoji, value=num))
            attrs.append({'mode': i})
            funcs.append(f)
        self.add_item(FuncDropdown(placeholder="Select a Game Mode", options=opt, funcs=funcs, attrs=attrs))

        ds = self.div_size
        match self.mode.tag:
            case "BRAWL" | "CLAN" | "EVENT":
                # Event and Brawl aren't in API.
                # Pre-made & Clan don't have div sizes.
                pass
            case "PVE" | "PVE_PREMADE":
                easy = next(i for i in self.bot.modes if i.tag == "PVE")
                hard = next(i for i in self.bot.modes if i.tag == "PVE_PREMADE")
                self.add_item(FuncButton(func=f, kwargs={'div_size': 0, 'mode': easy},
                                         label="Pre-Made", row=1, emoji=easy.emoji, disabled=ds == 0))
                self.add_item(FuncButton(func=f, kwargs={'div_size': 1, 'mode': easy},
                                         label="Solo", row=1, emoji=easy.emoji, disabled=ds == 1))
                self.add_item(FuncButton(func=f, kwargs={'mode': hard}, label="Hard Mode", row=1,
                                         emoji=hard.emoji, disabled=ds == 1))
            case _:
                emoji = self.mode.emoji
                self.add_item(FuncButton(func=f, kwargs={'div_size': 0}, label="Overall", row=1, disabled=ds == 0,
                                         emoji=emoji))
                self.add_item(FuncButton(func=f, kwargs={'div_size': 1}, label="Solo", row=1, disabled=ds == 1,
                                         emoji=emoji))
                self.add_item(FuncButton(func=f, kwargs={'div_size': 2}, label="Division (2)", row=1, disabled=ds == 2,
                                         emoji=emoji))
                self.add_item(FuncButton(func=f, kwargs={'div_size': 3}, label="Division (3)", row=1, disabled=ds == 3,
                                         emoji=emoji))

        return await self.bot.reply(self.interaction, embed=embed, view=self)
