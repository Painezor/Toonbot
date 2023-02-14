"""Utilities for World of Warships related commands."""
from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Callable, ClassVar

from discord import Colour, Embed, Message, SelectOption
from discord.ui import View, Button
from flatten_dict import flatten, unflatten

from ext.painezbot_utils.ship import Ship, Artillery
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import FuncButton, FuncDropdown

if TYPE_CHECKING:
    from ext.painezbot_utils.clan import PlayerCBStats, Clan
    from discord import Interaction
    from painezBot import PBot

# TODO: CommanderXP Command (Show Total Commander XP per Rank)
# TODO: Encyclopedia - Collections
# TODO: Pull Achievement Data to specifically get Jolly Rogers and Hurricane Emblems for player stats.
# TODO: Player's Ranked Battle Season History
# TODO: Clan Battle Season objects for Images for Leaderboard.


class Achievement:
    """A World of Warships Achievement"""


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
    def ac_match(self) -> str:
        """Autocomplete match for this map"""
        return f"{self.name}: {self.description} {self.icon}"

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

    def __init__(self, db_key: str, url: str, emote: str, colour: Colour, code_prefix: str, realm: str) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: Colour = colour
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
        """Return a link to the in-game version of the portal news"""
        return f"https://worldofwarships.{self.domain}/news_ingame"

    @property
    def recruiting(self) -> str:
        """Return a link to the 'Recruiting Station' page"""
        return f"https://friends.worldofwarships.{self.domain}/en/players/"

    # database key, domain, emote, colour, code prefix, realm
    EU = ('eu', 'eu', "<:EU:993495456988545124>", 0x0000ff, 'eu', 'eu')
    NA = ('na', 'com', "<:NA:993495467788869663>", 0x00ff00, 'na', 'us')
    SEA = ('sea', 'asia', "<:ASIA:993495476978589786>", 0x00ffff, 'asia', 'sg')
    CIS = ('cis', 'ru', "<:CIS:993495488248680488>", 0xff0000, 'ru', 'ru')


class Player:
    """A World of Warships player."""
    bot: ClassVar[PBot]

    def __init__(self, account_id: int, **kwargs) -> None:
        self.account_id: int = account_id
        self.nickname: str = kwargs.pop('nickname', None)

        # Additional Fetched Data.
        self.clan: Optional[Clan] = None
        self.created_at: Optional[Timestamp] = None  # Account Creation Date
        self.hidden_profile: bool = False  # Account has hidden stats
        self.joined_clan_at: Optional[Timestamp] = None  # Joined Clan at..
        self.clan_role: str = None  # Officer, Leader, Recruiter...
        self.karma: Optional[int] = None  # Player Karma (Hidden from API?)
        self.last_battle_time: Optional[Timestamp] = None  # Last Battle
        self.private: None = None  # Player's private data. We do not have access.
        self.levelling_tier: Optional[int] = None  # Player account level
        self.levelling_points: Optional[int] = None  # Player account XP
        self.logout_at: Optional[Timestamp] = None  # Last Logout
        self.stats_updated_at: Optional[Timestamp] = None  # Last Stats Update
        self.statistics: dict[Ship | None, dict] = {}  # Parsed Player Statistics

        # Data from CB Endpoint
        self.average_damage: float = 0
        self.average_xp: float = 0
        self.average_kills: float = 0
        self.battles_per_day: float = 0
        self.win_rate: float = 0

        self.battles: int = 0

        self.is_online: bool = False
        self.is_banned: bool = False

        # CB Season Stats
        self.clan_battle_stats: dict[int, PlayerCBStats] = {}  # Keyed By Season ID.

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
        return f"https://worldofwarships.{self.region.domain}/community/accounts/{self.account_id}-{self.nickname}/"

    @property
    def wows_numbers(self) -> str:
        """Get a link to this player's wows_numbers page."""
        match self.region:
            case Region.NA:
                region = "na."
            case Region.SEA:
                region = "asia."
            case Region.CIS:
                region = "ru."
            case _:
                region = ""
        return f"https://{region}wows-numbers.com/player/{self.account_id},{self.nickname}/"

    async def get_pr(self) -> int:
        """Calculate a player's personal rating"""
        if not self.bot.pr_data_updated_at:
            async with self.bot.session.get('https://api.wows-numbers.com/personal/rating/expected/json/') as resp:
                match resp.status:
                    case 200:
                        pass
                    case _:
                        raise ConnectionError(f'{resp.status} Error accessing {resp.url}')
        # TODO: Get PR
        raise NotImplementedError

    async def get_clan_info(self) -> Optional[Clan]:
        """Get a Player's clan"""
        link = f"https://api.worldofwarships.{self.region.domain}/wows/clans/accountinfo/"
        p = {'application_id': self.bot.WG_ID, 'account_id': self.account_id, 'extra': 'clan'}

        async with self.bot.session.get(link, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    return None

        if (data := json['data'].pop(str(self.account_id))) is None:
            self.clan = False
            return None

        self.joined_clan_at = Timestamp(datetime.utcfromtimestamp(data.pop('joined_at')))

        clan_id = data.pop('clan_id')
        clan = self.bot.get_clan(clan_id)

        clan_data = data.pop('clan')
        clan.created_at = Timestamp(datetime.utcfromtimestamp(clan_data.pop('created_at')))
        clan.members_count = clan_data.pop('members_count')
        clan.name = clan_data.pop('name')
        clan.tag = clan_data.pop('tag')

        self.clan = clan
        return self.clan

    async def get_stats(self, ship: Ship = None) -> None:
        """Get the player's stats as a dict"""
        p = {'application_id': self.bot.WG_ID, 'account_id': self.account_id}

        if ship is None:
            url = f"https://api.worldofwarships.{self.region.domain}/wows/account/info/"
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
        else:
            url = f'https://api.worldofwarships.{self.region.domain}/wows/ships/stats/'
            p.update({'ship_id': ship.ship_id})
            p.update({'extra': 'pvp_solo, pvp_div2, pvp_div3, '
                               'rank_solo, rank_div2, rank_div3, '
                               'pve, pve_div2, pve_div3, pve_solo, '
                               'oper_solo, oper_div, oper_div_hard'})

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    try:
                        raise ConnectionError(resp.status)
                    finally:
                        return []

        try:
            stats = json['data'].pop(str(self.account_id))  # Why the fuck is this randomly a string now, seriously WG?
        except KeyError:
            raise KeyError(f'Unable to find key "data" in {json}')

        self.created_at = Timestamp(datetime.utcfromtimestamp(stats.pop('created_at', None)))
        self.last_battle_time = Timestamp(datetime.utcfromtimestamp(stats.pop('last_battle_time', None)))
        self.stats_updated_at = Timestamp(datetime.utcfromtimestamp(stats.pop('stats_updated_at', None)))
        self.logout_at = Timestamp(datetime.utcfromtimestamp(stats.pop('logout_at', None)))
        self.hidden_profile = stats.pop('hidden_profile', False)
        if ship is None:
            self.statistics[None] = stats.pop('statistics')
        else:
            self.statistics[ship] = stats
        return

    def view(self, interaction: Interaction, mode: GameMode, div_size: int, ship: Ship = None) -> PlayerView:
        """Return a PlayerVIew of this Player"""
        return PlayerView(self.bot, interaction, self, mode, div_size, ship)


class ClanButton(Button):
    """Change to a view of a different ship"""

    def __init__(self, interaction: Interaction, clan: Clan, parent: View = None, row: int = 0) -> None:
        super().__init__(label="Clan", row=row)

        self.clan: Clan = clan
        self.interaction: Interaction = interaction
        self.emoji = self.clan.league.emote
        self.parent = parent

    async def callback(self, interaction: Interaction) -> Message:
        """Change message of interaction to a different ship"""
        await interaction.response.defer()
        return await self.clan.view(self.interaction, parent=self.parent).overview()


class PlayerView(View):
    """A View representing a World of Warships player"""
    bot: PBot = None

    def __init__(self, bot: PBot, interaction: Interaction, player: Player, mode: GameMode,
                 div_size: int, ship: Ship = None) -> None:
        super().__init__()
        self.bot: PBot = bot
        self.interaction: Interaction = interaction

        # Passed
        self.player: Player = player
        self.div_size: int = div_size
        self.mode: GameMode = mode
        self.ship: Ship = ship

        # Used
        self.cb_season: int = 17

        # Generated
        self._disabled: Optional[Callable] = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide buttons on view timeout"""
        return await self.bot.reply(self.interaction, view=None)

    @property
    async def base_embed(self) -> Embed:
        """Base Embed used for all sub embeds."""
        e = Embed()

        if self.player.clan is None:
            await self.player.get_clan_info()

        if self.player.clan:
            e.set_author(name=f'[{self.player.clan.tag}] {self.player.nickname} ({self.player.region.name})')
        else:
            e.set_author(name=f'{self.player.nickname} ({self.player.region.name})')

        e.set_thumbnail(url=self.mode.image)

        if self.player.hidden_profile:
            e.set_footer(text="This player has hidden their stats.")
        return e

    @staticmethod
    def sum_stats(dicts: list[dict]) -> dict:
        """Sum The Stats from multiple game modes."""
        output = {}

        dicts = [flatten(d, reducer='dot') for d in dicts]

        for key in dicts[0].keys():
            match key:
                case key if "ship_id" in key:
                    pass
                case key if 'max' in key:
                    ship_keys = {'max_frags_battle': 'max_frags_ship_id',
                                 'max_damage_dealt': 'max_damage_dealt_ship_id',
                                 'max_xp': 'max_xp_ship_id',
                                 'max_total_agro': 'max_total_agro_ship_id',
                                 'max_damage_scouting': 'max_scouting_damage_ship_id',
                                 'max_ships_spotted': 'max_ships_spotted_ship_id',
                                 'max_planes_killed': 'max_planes_killed_ship_id',
                                 'main_battery.max_frags_battle': 'main_battery.max_frags_ship_id',
                                 'second_battery.max_frags_battle': 'second_battery.max_frags_ship_id',
                                 'ramming.max_frags_battle': 'ramming.max_frags_ship_id',
                                 'torpedoes.max_frags_battle': 'torpedoes.max_frags_ship_id',
                                 'aircraft.max_frags_battle': 'aircraft.max_frags_ship_id',

                                 }

                    paired_keys = [(n.get(key, 0), n.get(ship_keys[key])) for n in dicts if n.get(key, 0)]
                    filter_keys = filter(lambda x: x[1] is not None, paired_keys)
                    try:
                        value = sorted(filter_keys, key=lambda x: x[0])[0]
                    except IndexError:
                        value = (0, None)
                    output.update({key: value[0], ship_keys[key]: value[1]})
                case _:
                    value = sum([x for x in [n.get(key, 0) for n in dicts] if x is not None], 0)
                    output.update({key: value})
        output = unflatten(output, splitter='dot')
        return output

    async def filter_stats(self) -> tuple[str, dict]:
        """Fetch the appropriate stats for the mode tag"""
        if self.ship not in self.player.statistics:
            await self.player.get_stats(self.ship)

        match self.mode.tag, self.div_size:
            case "PVP", 1:
                return "Random Battles (Solo)", self.player.statistics[self.ship]['pvp_solo']
            case "PVP", 2:
                return "Random Battles (2-person Division)", self.player.statistics[self.ship]['pvp_div2']
            case "PVP", 3:
                return "Random Battles (3-person Division)", self.player.statistics[self.ship]['pvp_div3']
            case "PVP", _:
                return "Random Battles (Overall)", self.player.statistics[self.ship]['pvp']
            case "COOPERATIVE", 1:
                return "Co-op Battles (Solo)", self.player.statistics[self.ship]['pve_solo']
            case "COOPERATIVE", 2:
                return "Co-op Battles (2-person Division)", self.player.statistics[self.ship]['pve_div2']
            case "COOPERATIVE", 3:
                return "Co-op Battles (3-person Division)", self.player.statistics[self.ship]['pve_div3']
            case "COOPERATIVE", _:  # All Stats.
                return "Co-op Battles (Overall)", self.player.statistics[self.ship]['pve']
            case "RANKED", 1:
                return "Ranked Battles (Solo)", self.player.statistics[self.ship]['rank_solo']
            case "RANKED", 2:
                return "Ranked Battles (2-Man Division)", self.player.statistics[self.ship]['rank_div2']
            case "RANKED", 3:
                return "Ranked Battles (3-Man Division)", self.player.statistics[self.ship]['rank_div3']
            case "RANKED", 0:  # Sum 3 Dicts.
                a = self.player.statistics[self.ship]['rank_solo']
                b = self.player.statistics[self.ship]['rank_div2']
                c = self.player.statistics[self.ship]['rank_div3']
                return "Ranked Battles (Overall)", self.sum_stats([a, b, c])
            case "PVE", 0:  # Sum 2 dicts
                a = self.player.statistics[self.ship]['oper_solo']
                b = self.player.statistics[self.ship]['oper_div']
                return "Operations (Overall)", self.sum_stats([a, b])
            case "PVE", 1:
                return "Operations (Solo)", self.player.statistics[self.ship]['oper_solo']
            case "PVE", _:
                return "Operations (Pre-made)", self.player.statistics[self.ship]['oper_div']
            case "PVE_PREMADE", _:
                return "Operations (Hard Pre-Made)", self.player.statistics[self.ship]['oper_div_hard']
            case _:
                return f"Missing info for {self.mode.tag}, {self.div_size}", self.player.statistics[self.ship]['pvp']

    async def clan_battles(self) -> Message:
        """Attempt to fetch player's Clan Battles data."""
        if self.cb_season not in self.player.clan_battle_stats:
            await self.player.clan.get_member_clan_battle_stats(self.cb_season)

        stats = self.player.clan_battle_stats[self.cb_season]

        print('Found clan battle stats')
        print(stats)

        e = await self.base_embed
        e.title = f"Clan Battles (Season {self.cb_season})"
        e.description = f"**Win Rate**: {round(stats.win_rate, 2)}% ({stats.battles} battles played)\n" \
                        f"**Average Damage**: {format(round(stats.average_damage, 0), ',')}\n" \
                        f"**Average Kills**: {round(stats.average_kills, 2)}\n"
        self._disabled = self.clan_battles
        return await self.update(e)

    async def weapons(self) -> Message:
        """Get the Embed for a player's weapons breakdown"""
        e = await self.base_embed
        e.title, p_stats = await self.filter_stats()

        if mb := p_stats.pop('main_battery', {}):
            mb_kills = mb.pop('frags')
            mb_ship = self.bot.get_ship(mb.pop('max_frags_ship_id'))
            mb_max = mb.pop('max_frags_battle')
            mb_shots = mb.pop('shots')
            mb_hits = mb.pop('hits')
            mb_acc = round(mb_hits / mb_shots * 100, 2)
            mb = f"Kills: {format(mb_kills, ',')} (Max: {mb_max} - {mb_ship.name})\n" \
                 f"Accuracy: {mb_acc}% ({format(mb_hits, ',')} hits / {format(mb_shots, ',')} shots)"
            e.add_field(name='Main Battery', value=mb, inline=False)

        # Secondary Battery
        if sb := p_stats.pop('second_battery', {}):
            sb_kills = sb.pop('frags', 0)
            sb_ship = self.bot.get_ship(sb.pop('max_frags_ship_id', None))
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
            trp_ship = self.bot.get_ship(trp.pop('max_frags_ship_id', None))
            trp_max = trp.pop('max_frags_battle', 0)
            trp_shots = trp.pop('shots', 0)
            trp_hits = trp.pop('hits', 0)
            trp_acc = round(trp_hits / trp_shots * 100, 2)
            trp = f"Kills: {format(trp_kills, ',')} (Max: {trp_max} - {trp_ship.name})\n" \
                  f"Accuracy: {trp_acc}% ({format(trp_hits, ',')} hit / {format(trp_shots, ',')} launched)"
            e.add_field(name='Torpedoes', value=trp, inline=False)

        # Ramming
        if ram := p_stats.pop('ramming', {}):
            out = f"Kills: {ram.pop('frags', 0)}"
            if ram_ship := self.bot.get_ship(ram.pop('max_frags_ship_id', None)):
                out += f" (Max: {ram.pop('max_frags_battle', 0)} - {ram_ship.name})\n"
            e.add_field(name='Ramming', value=out)

        # Aircraft
        if cv := p_stats.pop('aircraft', {}):
            out = f"Kills: {cv.pop('frags')}"
            if cv_ship := self.bot.get_ship(cv.pop('max_frags_ship_id', None)):
                out += f" (Max: {cv.pop('max_frags_battle')} - {cv_ship.name})\n"
            e.add_field(name='Aircraft', value=out)

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
        """Push an Overview of the player to the View"""
        desc = []  # Build The description piecemeal then join at the very end.
        e = await self.base_embed
        e.title, p_stats = await self.filter_stats()

        if self.player.stats_updated_at is not None:
            desc.append(f"**Stats updated**: {self.player.stats_updated_at.relative}\n")

        if self.player.created_at is not None:
            desc.append(f"**Account Created**: {self.player.created_at.relative}")

        if self.player.last_battle_time is not None:
            desc.append(f"**Last Battle**: {self.player.last_battle_time.relative}")

        if self.player.logout_at is not None:
            desc.append(f"**Last Logout**: {self.player.logout_at.relative}")

        distance = self.player.statistics[None]['distance']  # This is stored 1 level up.
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
        e = await self.base_embed
        desc = []

        match self.mode.tag:
            case "CLAN":
                return await self.clan_battles()
            case _:
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
            desc.append(f"**Survival Rate (Overall)**: {sr}% (Total: {format(survived, ',')})")
        except ZeroDivisionError:
            pass

        try:
            swr = round(suv_wins / wins * 100, 2)
            desc.append(f"**Survival Rate (Wins)**: {swr}% (Total: {format(suv_wins, ',')})")
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
        if self.mode.tag == "PVE":
            x_avg = format(round(tot_xp / played), ',')
            x_tot = format(tot_xp, ',')
            desc.append(f"**Average XP**: {x_avg}\n"
                        f"**Total XP**: {x_tot}")
        else:
            try:
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
                r_xp = format(p_stats.pop('max_xp', 0), ',')
                r_kills = p_stats.pop('max_frags_battle', 0)
                r_pot = format(p_stats.pop('max_total_agro', 0), ',')
                r_spot = format(p_stats.pop('max_damage_scouting', 0), ',')
                r_ship_max = p_stats.pop('max_ships_spotted', 0)
                r_planes = p_stats.pop('max_planes_killed', 0)

                s_dmg = self.bot.get_ship(p_stats.pop('max_damage_dealt_ship_id', None))
                s_xp = self.bot.get_ship(p_stats.pop('max_xp_ship_id', None))
                s_kills = self.bot.get_ship(p_stats.pop('max_frags_ship_id', None))
                s_pot = self.bot.get_ship(p_stats.pop('max_total_agro_ship_id', None))
                s_spot = self.bot.get_ship(p_stats.pop('max_scouting_damage_ship_id', None))
                s_ship_max = self.bot.get_ship(p_stats.pop('max_ships_spotted_ship_id', None))
                s_planes = self.bot.get_ship(p_stats.pop('max_planes_killed_ship_id', None))

                # Records, Totals
                rec = []
                for record, ship in [(r_kills, s_kills), (r_dmg, s_dmg), (r_pot, s_pot), (r_ship_max, s_ship_max),
                                     (r_spot, s_spot), (r_xp, s_xp), (r_planes, s_planes)]:
                    try:
                        rec.append(f"{record} ({ship.name})")
                    except AttributeError:
                        rec.append(f"{record}")

                e.add_field(name="Records",
                            value='\n'.join(rec))

                e.add_field(name="Totals", value=f"{format(kills, ',')}\n{format(dmg, ',')}\n{format(potential, ',')}\n"
                                                 f"{format(spotting, ',')}\n{format(spotted, ',')}\n"
                                                 f"{format(tot_xp, ',')}\n{format(planes, ',')}")
            except ZeroDivisionError:
                desc.append('```diff\n- Could not find player stats for this game mode and division size```')
                logging.error(f'Could not find stats for size [{self.div_size}] mode [{self.mode}]')

        # Operations specific stats.
        try:
            star_rate = [(k, v) for k, v in p_stats.pop('wins_by_tasks').items()]
            star_rate = sorted(star_rate, key=lambda st: int(st[0]))

            star_desc = []
            for x in range(0, 5):
                s1 = '\⭐'
                s2 = '\★'
                star_desc.append(f"{x * s1}{(5 - x) * s2}: {star_rate[x][1]}")

            e.add_field(name="Star Breakdown", value="\n".join(star_desc))
        except KeyError:
            pass

        e.description = "\n".join(desc)
        self._disabled = None
        return await self.update(embed=e)

    async def update(self, embed: Embed) -> Message:
        """Send the latest version of the embed to view"""
        self.clear_items()
        self.add_item(FuncButton(func=self.overview, label="Profile", emoji='🔘',
                                 disabled=self._disabled == self.overview, row=0))

        if self.player.clan:
            self.add_item(ClanButton(self.interaction, self.player.clan, parent=(self, self.player.nickname)))

        if self.mode.tag != "CLAN":
            self.add_item(FuncButton(func=self.weapons, label="Armaments", disabled=self._disabled == self.weapons,
                                     row=0, emoji=Artillery.emoji))

        f = self.mode_stats
        options = []
        for num, i in enumerate([i for i in self.bot.modes if i.tag not in ["EVENT", "BRAWL", "PVE_PREMADE"]]):
            # We can't fetch CB data without a clan.
            if i.tag == "CLAN" and not self.player.clan:
                continue

            opt = SelectOption(label=f"{i.name} ({i.tag})", description=i.description, emoji=i.emoji, value=num)
            options.append((opt, {'mode': i}, f))
        self.add_item(FuncDropdown(placeholder="Change Game Mode", options=options))

        ds = self.div_size
        match self.mode.tag:
            # Event and Brawl aren't in API.
            case "BRAWL" | "EVENT":
                pass
            # Pre-made & Cawaalan don't have div sizes.
            case "CLAN":
                opts = []

                if self.player.clan is not None and self.player.clan.season_number is None:
                    await self.player.clan.get_data()

                for x in range(self.player.clan.season_number):
                    opt = SelectOption(label=f"Season {x}", emoji=self.mode.emoji, value=str(x))
                    opts.append((opt, {'cb_season': x}, self.clan_battles))
                self.add_item(FuncDropdown(options=opts, row=1, placeholder="Change Season"))
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
