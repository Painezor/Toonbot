"""Utilities for World of Warships related commands."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Dict, Optional

from discord import Colour, Embed, Message
from discord.ui import View

from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import add_page_buttons, FuncButton

if TYPE_CHECKING:
    from painezBot import PBot
    from discord import Interaction
    from typing import List

# TODO: Pull Achievement Data to specifically get Jolly Rogers and Hurricane Emblems for player stats.

# TODO: BB OM, DD OM
cruiser_om = {6: ['Tier 3 Cruiser'],
              10: ['Tier 3 Plating',
                   'Tier 5 Superstructure', ],
              13: ['Tier 5 Plating',
                   'Tier 7 Most Superstructures',
                   'Tier 7 Super light (127mms) plating'],
              16: ['Tier 5 Plating',
                   'Tier 7 Superstructure',
                   'Tier 7 Bow/Stern (Except Pensacola/New Orleans/Yorck)',
                   'All British CLs',
                   '127mm and below equipped super lights',
                   'Smolensk'],
              19: ['Tier 7 CL Side plating',
                   'Tier 7 Superstructure',
                   'Tier 7 Bow/Stern (Except Pensacola/New Orleans/Yorck). ',
                   'All British CLs and smolensk plating',
                   '127mm super lights plating'],
              25: ['Tier 7 everywhere',
                   'Tier 10 CL side plating',
                   'Supership bow/stern (except US & German Heavy, and icebreakers)',
                   'All British CLs and smolensk plating',
                   ],
              27: ['Tier 9 decks',
                   'Supership bow/stern',
                   'All British CLs and smolensk plating',
                   ],
              30: ['Supership Decks',
                   'Supership bow/stern',
                   'Supership plating'],
              32: ['Supership Decks', 'Supership bow/stern', 'Supership plating', 'Austin Main Belt']
              }

bb_om = {}

armor = {
    10: ['Tier 4-5 cruiser superstructure',
         'Tier 4-5 destroyer plating'],
    13: ['Tier 4-5 battleship superstructure',
         'Tier 4-5 cruiser bow/stern',
         'Most tier 6-7 cruiser superstructure',
         'Tier 8-11 Destroyer Superstructure'],
    16: ['Tier 3 battleship bow/stern',
         'Tier 6-7 cruiser superstructure',
         'British CL, Smolensk',
         'Tier 6-7 destroyer plating'],
    19: ['Tier 4-5 battleship bow/stern',
         'Tier 6-7 light cruiser side plating',
         'Tier 8-11 Battleship & Cruiser superstructure'],
    25: ['Tier 6-7 cruiser decks',
         'Yorck, Pensacola, New Orleans bow/stern',
         'Florida, Mackensen, Prinz Heinrich, Borodino, Constellation, Slava, Incomparable Bow/Stern',
         'Most Tier 8-11 cruiser bow/stern',
         'Tier 8-10 light cruiser side plating',
         'Elbing, Ragnar Belt'],
    26: ['Tier 6-7 battleship bow/stern/some casemate'],
    27: ['Tier 8-9 cruiser deck',
         'Tier 8-11 US/German Heavy Cruiser Bow/Stern',
         'Tier 8-10 German BC Bow/Stern'],
    30: ['Most Tier 10-11 Cruiser Decks',
         'Most Tier 10-11 Heavy Cruiser sides',
         'Ägir, Siegfried, Albemarle, Cheshire, Drake, Haarlem and Johan de Witt decks'],
    32: ['Tier 8-11 Battleship Bow/Stern',
         'Tier 8-11 French/British Battleship Casemate',
         'Slava deck'],
    35: ['Riga, Fuso Deck']
}


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

    #     db_key  | domain                       | emote                             | colour   | code prefix
    EU = ('eu', 'https://worldofwarships.eu/', "<:painezBot:928654001279471697>", 0x0000ff, 'eu')
    NA = ('na', 'https://worldofwarships.com/', "<:Bonk:746376831296471060>", 0x00ff00, 'na')
    SEA = ('sea', 'https://worldofwarships.asia/', "<:painezRaid:928653997680754739>", 0x00ffff, 'asia')
    CIS = ('cis', 'https://worldofwarships.ru/', "<:Button:826154019654991882>", 0xff0000, 'ru')


class Mode(Enum):
    """"An Enum representing different Game Modes"""

    def __new__(cls, *args, **kwargs) -> Mode:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, image: str, tag: str, mode_name: str, description: str) -> None:
        self.tag: str = tag
        self.mode_name: str = mode_name
        self.image: str = image
        self.description: str = description

    # noinspection SpellCheckingInspection
    CLAN = ("https://glossary-wows-global.gcdn.co/icons//battle_types/"
            "ClanBattle_6dc3e9dfa28cae753464c4ccaaf8f262fe780ed2b694b0064fa86bfbb698e613.png", 'CLAN', 'Clan Battles',
            "Assemble a Division with your clanmates and fight against other clans.")

    PVP = ("https://glossary-wows-global.gcdn.co/icons//battle_type/"
           "RandomBattle_d894566a260274247767e463763e912d6686989e8518906492c07e93b58c0ef9.png", "PVP", "Random Battles",
           "Fight against real players. The matchmaker will create teams randomly.")

    # noinspection SpellCheckingInspection
    BRAWL = ("https://glossary-wows-global.gcdn.co/icons//battle_type"
             "/BrawlBattle_98c4bfa304ebaa0169616913d9cd3e90ecb21eeb22c74213c5d4f96ac2bd6fd9.png", 'BRAWL', 'Brawl',
             "Battle against real players. Teams are matched based on player skill level. Ship restrictions apply.")

    RANKED = ("https://glossary-wows-global.gcdn.co/icons//battle_types"
              "/RankedBattle_3d9a6cf986dde60a519e878b0ca941f1d1d051840e7f9e83027a84253493f91f.png", 'RANKED',
              'Ranked Battles', "Fight against real players and earn Ranks.")

    SCENARIO = ("https://glossary-wows-global.gcdn.co/icons//battle_types"
                "/PVEBattle_f91d97a4c0964a4a8f7dbb070f8f449a21c4d36665dc17635239b7cb11b1c15d.png", 'PVE', 'Scenarios',
                "Complete tasks as described in the scenario and receive rewards.")

    # noinspection SpellCheckingInspection
    SCENARIO_HARD = ("https://glossary-wows-global.gcdn.co/icons//battle_types"
                     "/PVEBattle_event_d42173715a8861cc91879806fba4cbe5c4a1a0047b75b297f874ea34b29fe24f.png",
                     "PVE_PREMADE", 'Scenarios', "Complete tasks as described in the scenario and receive rewards.")

    COOP = ("https://glossary-wows-global.gcdn.co/icons//battle_types"
            "/CooperativeBattle_6cf88424226cf0427f6eb026a9c232c51bc29cb86eb89ca7eb3b0e0b73d08fab.png", "COOPERATIVE",
            "Co-op Battle", "Fight against bots in cooperation with other players.")

    # noinspection SpellCheckingInspection
    EVENT = ("https://glossary-wows-global.gcdn.co/icons//battle_types"
             "/EventBattle_89d294a1ddbb1a92416427fe0143dff8b72d9022c0acbe28a6a2763e750c2b55.png", "EVENT",
             "Temporary battle type", "Test the super battleships out in battles at sea in the Grand Battle!")


class Nation(Enum):
    """An Enum representing different nations."""

    def __new__(cls, *args, **kwargs) -> Nation:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, alias: str, match: str, flag: str) -> None:
        self.alias: str = alias
        self.match: str = match
        self.flag: str = flag

    COMMONWEALTH = ("Commonwealth", 'commonwealth', '')
    EUROPE = ('Pan-European', 'europe', '')
    FRANCE = ('French', 'france', '')
    GERMANY = ('German', 'germany', '')
    ITALY = ('Italian', 'italy', '')
    JAPAN = ('Japanese', 'japan', '')
    NETHERLANDS = ('Dutch', 'netherlands', '')
    PAN_ASIA = ('Pan-Asian', 'pan_asia', '')
    PAN_AMERICA = ('Pan-American', 'pan_america', '')
    SPAIN = ('Spanish', 'spain', '')
    UK = ('British', 'uk', '')
    USSR = ('Soviet', 'ussr', '')
    USA = ('American', 'usa', '')


class ShipType:
    """Submarine, Cruiser, etc."""

    def __init__(self, match: str, alias: str, images: dict):
        self.match: str = match
        self.alias: str = alias

        self.image = images['image']
        self.image_elite = images['image_elite']
        self.image_premium = images['image_premium']


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


class Clan:
    """A World of Warships clan."""
    bot: PBot = None

    def __init__(self, bot: 'PBot', clan_id: int, **kwargs):
        self.clan_id: int = clan_id
        self.bot: PBot = bot
        for k, v in kwargs.items():
            setattr(self, k, v)

        if TYPE_CHECKING:
            self.clan_id: int
            self.created_at: Timestamp
            self.creator_id: int
            self.creator_name: str
            self.description: str
            self.is_clan_disbanded: bool
            self.leader_name: str
            self.leader_id: int
            self.members_count: int
            self.member_ids: List[int]
            self.name: str
            self.old_name: str
            self.old_tag: str
            self.renamed_at: Timestamp
            self.tag: str
            self.updated_at: Timestamp

    async def get_data(self) -> None:
        """Fetch clan information."""
        p = {'application_id': self.bot.WG_ID, 'clan_id': self.clan_id}

        async with self.bot.session.get("https://api.worldofwarships.eu/wows/clans/info/", params=p) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                case _:
                    return

        data = data.pop(str(self.clan_id))
        # Handle Timestamps.
        setattr(self, 'updated_at', Timestamp(datetime.utcfromtimestamp(data.pop('updated_at'))))
        setattr(self, 'created_at', Timestamp(datetime.utcfromtimestamp(data.pop('created_at'))))
        setattr(self, 'renamed_at', Timestamp(datetime.utcfromtimestamp(data.pop('renamed_at'))))

        # Handle rest.
        for k, v in data:
            setattr(self, k, v)


class Player:
    """A World of Warships player."""
    bot: PBot = None

    def __init__(self, bot: 'PBot', account_id: int, region: Region, nickname: str) -> None:
        self.bot: PBot = bot
        self.nickname: str = nickname
        self.account_id: int = account_id
        self.region: Region = region

        # Additional Data.
        if TYPE_CHECKING:
            self.clan: Clan
            self.joined_clan_at: Timestamp  # Joined Clan at..
            self.stats_updated_at: Timestamp  # Last Stats Update
            self.created_at: Timestamp  # Account Creation Date
            self.last_battle_time: Timestamp  # Last Battle

        # Stats
        self.stats: dict = {}

    async def get_clan_info(self) -> Optional[Clan]:
        """Get Player's clan"""
        link = "https://api.worldofwarships.eu/wows/clans/accountinfo/"
        p = {'application_id': self.bot.WG_ID, 'account_id': self.account_id, 'extras': 'clan'}

        async with self.bot.session.get(link, params=p) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                case _:
                    return None

        data = data.pop(str(self.account_id))
        if data is None:
            setattr(self, 'clan', False)
            return None

        setattr(self, 'joined_clan_at', Timestamp(datetime.utcfromtimestamp(data.pop('joined_at'))))
        clan = data.pop('clan')
        created = Timestamp(datetime.utcfromtimestamp(clan.pop('created_at')))
        player_clan = Clan(self.bot, tag=clan.pop('tag'), clan_id=clan.pop('clan_id'), name=clan.pop('name'),
                           members_count=clan.pop('members_count'), created_at=created)

        if clan:
            print('Unhandled Clan Data remains in player.get_clan', clan)

        setattr(self, 'clan', player_clan)
        return player_clan

    async def get_stats(self, ship: Ship = None) -> dict:
        """Get the player's stats as a dict"""
        p = {'application_id': self.bot.WG_ID, 'account_id': self.account_id}

        if ship is None:
            url = "https://api.worldofwarships.eu/wows/account/info/"
        else:
            url = 'https://api.worldofwarships.eu/wows/ships/stats/'
            p.update({'ship_id': ship.ship_id})
            p.update({'extra': 'pvp_solo, pvp_div2, pvp_div3, rank_solo, rank_div2, rank_div3, '
                               'pve, pve_div2, pve_div3, pve_solo, oper_solo, oper_div, oper_div_hard'})

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    stats = await resp.json()
                case _:
                    return {}

        stats = stats['data'][str(self.account_id)]  # Why the fuck is this randomly a string now, seriously WG?
        setattr(self, 'created_at', Timestamp(datetime.utcfromtimestamp(stats.pop('created_at'))))
        setattr(self, 'last_battle_time', Timestamp(datetime.utcfromtimestamp(stats['last_battle_time'])))
        setattr(self, 'stats_updated_at', Timestamp(datetime.utcfromtimestamp(stats['stats_updated_at'])))
        for k, v in stats:
            setattr(self, k, v)
        # Generate Header Area -- Login Info
        # These ints are all Unix Timestamps.
        return stats

    def view(self, interaction: Interaction) -> PlayerView:
        """Return a PlayerVIew of this Player"""
        return PlayerView(self.bot, interaction, self)


class Module:
    """A Module that can be mounted on a ship"""
    pass


class Artillery(Module):
    """An 'Artillery' Module"""
    pass


class DiveBomber(Module):
    """A 'Dive Bomber' Module"""
    pass


class Engine(Module):
    """An 'Engine' Module"""
    pass


class Fighter(Module):
    """A 'Fighter' Module"""
    pass


class FireControl(Module):
    """A 'Fire Control' Module"""
    pass


class FlightControl(Module):
    """A 'Flight Control' Module"""
    pass


class Hull(Module):
    """A 'Hull' Module"""
    pass


class Torpedoes(Module):
    """A 'Torpedoes' Module"""
    pass


class TorpedoBomber(Module):
    """A 'Torpedo Bomber' Module"""
    pass


class PlayerView(View):
    """A View representing a World of Warships player"""
    bot: PBot = None

    def __init__(self, bot: 'PBot', interaction: Interaction, player: Player) -> None:
        super().__init__()
        self.bot: PBot = bot
        self.interaction: Interaction = interaction
        self.player: Player = player

        self.pages: List[Embed] = []
        self.index: int = 0

        # Solo / 2 Man / 3 Man
        self.div_size: int = 1

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of command."""
        return self.interaction.user.id == interaction.user.id

    async def push_stats(self, mode: Mode, div_size: int) -> Message:
        """Generate the stats embeds"""
        e = Embed()
        e.set_thumbnail(url=mode.image)
        desc = []  # Build The description piecemeal then join at the very end.

        clan = getattr(self.player, 'clan', await self.player.get_clan_info())

        # CLan Info
        if hasattr(clan, 'tag'):
            e.set_author(name=f'[{clan.tag}] {self.player.nickname} ({self.player.region.name})')
        else:
            e.set_author(name=f'{self.player.nickname} ({self.player.region.name})')

        match mode, div_size:
            case mode.PVP, 1:
                p_stats = self.player.stats['statistics']['pvp_solo']
                e.title = "Random Battles (Solo)"
            case mode.PVP, 2:
                p_stats = self.player.stats['statistics']['pvp_div2']
                e.title = "Random Battles (2-person Division)"
            case mode.PVP, 3:
                p_stats = self.player.stats['statistics']['pvp_div3']
                e.title = "Random Battles (3-person Division)"
            case mode.PVP, _:
                p_stats = self.player.stats['statistics']['pvp']
                e.title = "Random Battles (Overall)"
            case mode.COOP, 1:
                p_stats = self.player.stats['statistics']['pve_solo']
                e.title = "Co-op Battles (Solo)"
            case mode.COOP, 2:
                p_stats = self.player.stats['statistics']['pve_div2']
                e.title = "Co-op Battles (2-person Division)"
            case mode.COOP, 3:
                p_stats = self.player.stats['statistics']['pve_div3']
                e.title = "Co-op Battles (3-person Division)"
            case mode.COOP, _:  # All Stats.
                p_stats = self.player.stats['statistics']['pve']
                e.title = "Co-op Battles (Overall)"
            case mode.RANKED, 2:
                p_stats = self.player.stats['statistics']['rank_div2']
                e.title = "Ranked Battles (2-Man Division)"
            case mode.RANKED, 3:
                p_stats = self.player.stats['statistics']['rank_div3']
                e.title = "Ranked Battles (3-Man Division)"
            case mode.RANKED, _:  # Solo Stats.
                p_stats = self.player.stats['statistics']['rank_solo']
                e.title = "Ranked Battles (Solo)"
            case _:
                p_stats = self.player.stats['statistics']

        e2 = deepcopy(e)

        if hasattr(self.player, 'created'):
            desc.append(f"Account Created: {self.player.created.relative}")

        if hasattr(self.player, 'last_battle'):
            desc.append(f"Last Battle: {self.player.last_battle.relative}")

        # Don't remove data from original player object.
        p_stats = deepcopy(p_stats)

        # Overall Rates - Survival, WR, Wins, Loss, Draw
        survived = p_stats.pop('survived_battles')
        suv_wins = p_stats.pop('survived_wins')
        played = p_stats.pop('battles')
        wins = p_stats.pop('wins')
        losses = p_stats.pop('losses')
        draws = p_stats.pop('draws')

        desc.append(f"Win Rate: {wins / played * 100}% ({wins}W - {draws}D - {losses}L)\n")
        desc.append(f"Survival Rate: {survived / played * 100}% ({survived} total)\n")

        # Totals
        dmg = p_stats.pop('damage_dealt')
        kills = p_stats.pop('frags')
        tot_xp = p_stats.pop('xp')
        spotted = p_stats.pop('ships_spotted')
        spotting = p_stats.pop('damage_scouting')
        potential = p_stats.pop('torpedo_agro') + p_stats.pop('art_agro')
        planes = p_stats.pop('planes_killed')

        # Averages - Kills, Damage, Spotting, Potential
        d_avg = round(dmg / played)
        k_avg = round(kills / played, 2)
        x_avg = round(tot_xp / played)
        p_avg = round(potential / played)
        s_avg = round(spotting / played)
        sp_av = round(spotted / played, 2)
        pl_av = round(planes / played, 2)

        avg = (f"**Kills**: {k_avg}\n**Damage**: {d_avg}\n**Potential**: {p_avg}\n**Spotting**: {s_avg}\n"
               f"**Ships Spotted**: {sp_av}\n**XP**: {x_avg}\n**Planes Destroyed**: {pl_av}")
        e.add_field(name="Averages", value=avg)

        # Records
        r_dmg = p_stats.pop('max_damage_dealt')
        s_dmg = await self.bot.get_ship(p_stats.pop('max_damage_dealt_ship_id'))

        r_xp = p_stats.pop('max_xp')
        s_xp = await self.bot.get_ship(p_stats.pop('max_xp_ship_id'))

        r_kills = p_stats.pop('max_frags_battle')
        s_kills = await self.bot.get_ship(p_stats.pop('max_frags_ship_id'))

        r_pot = p_stats.pop('max_total_agro')
        s_pot = await self.bot.get_ship(p_stats.pop('max_total_agro_ship_id'))

        r_spot = p_stats.pop('max_damage_scouting')
        s_spot = await self.bot.get_ship(p_stats.pop('max_scouting_damage_ship_id'))

        r_ship_max = p_stats.pop('max_ships_spotted')
        s_ship_max = await self.bot.get_ship(p_stats.pop('max_ships_spotted_ship_id'))

        r_planes = p_stats.pop('max_planes_killed')
        s_planes = await self.bot.get_ship(p_stats.pop('max_planes_killed_ship_id'))

        rec = f"**Damage**: {r_dmg} ({getattr(s_dmg, 'name', 'Unknown ship')})\n" \
              f"**Kills**: {r_kills} ({getattr(s_kills, 'name', 'Unknown ship')})\n" \
              f"**Potential**: {r_pot} ({getattr(s_pot, 'name', 'Unknown ship')})\n" \
              f"**Spotting**: {r_spot} ({getattr(s_spot, 'name', 'Unknown ship')})\n" \
              f"**Ships Spotted**: {r_ship_max} ({getattr(s_ship_max, 'name', 'Unknown ship')})\n" \
              f"**XP**: {r_xp} ({getattr(s_xp, 'name', 'Unknown ship')})\n" \
              f"**Planes Destroyed**: {r_planes} ({getattr(s_planes, 'name', 'Unknown ship')})"
        e.add_field(name="Records", value=rec)

        # Totals
        tot = f"Damage: {dmg}\nKills: {kills}\nXP: {tot_xp}\nPotential: {potential}\nSpotting: " \
              f"{spotting}\nShips Spotted: {spotted}\nPlanes Destroyed: {planes}"
        e.add_field(name="Totals", value=tot)

        if hasattr(self.player, 'stats_updated_at'):
            desc.append(self.player.stats_updated_at.relative)
        e.description = '\n'.join(desc)
        desc.clear()

        # Additional Garbage -> Second Embed.
        # Weapon Breakdowns
        # Main Battery
        mb = p_stats.pop('main_battery')
        mb_kills = mb.pop('frags')
        mb_ship = await self.bot.get_ship(mb.pop('max_frags_ship_id'))
        mb_max = mb.pop('max_frags_battle')
        mb_shots = mb.pop('shots')
        mb_hits = mb.pop('hits')
        mb_acc = mb_hits / mb_shots * 100
        mb = f"Kills: {mb_kills} (Max: {mb_max} - {mb_ship.name})\n" \
             f"Accuracy: {mb_hits} hits / {mb_shots} shots ({mb_acc}%)"

        # Secondary Battery
        sb = p_stats.pop('second_battery')
        sb_kills = sb.pop('frags')
        sb_ship = await self.bot.get_ship(sb.pop('max_frags_ship_id'))
        sb_max = sb.pop('max_frags_battle')
        sb_shots = sb.pop('shots')
        sb_hits = sb.pop('hits')
        sb_acc = sb_hits / sb_shots * 100
        sb = f"Kills: {sb_kills} (Max: {sb_max} - {sb_ship.name})\n" \
             f"Accuracy: {sb_hits} hits / {sb_shots} shots ({sb_acc}%)"

        # Torpedoes
        trp = p_stats.pop('torpedoes')
        trp_kills = trp.pop('frags')
        trp_ship = await self.bot.get_ship(trp.pop('max_frags_ship_id'))
        trp_max = trp.pop('max_frags_battle')
        trp_shots = trp.pop('shots')
        trp_hits = trp.pop('hits')
        trp_acc = trp_hits / trp_shots * 100
        trp = f"Kills: {trp_kills} (Max: {trp_max} - {trp_ship.name})\n" \
              f"Accuracy: {trp_hits} hit / {trp_shots} launched ({trp_acc}%)"

        # Ramming
        ram = p_stats.pop('ramming')
        ram_ship = await self.bot.get_ship(ram.pop('max_frags_ship_id'))
        ram = f"Kills: {ram.pop('frags')} (Max: {ram.pop('max_frags_battle')} - {ram_ship.name})\n"

        # Aircraft
        cv = p_stats.pop('aircraft')
        cv_ship = await self.bot.get_ship(cv.pop('max_frags_ship_id'))
        cv = f"Kills: {cv.pop('frags')} (Max: {cv.pop('max_frags_battle')} - {cv_ship.name})\n"

        # Build the second embed.
        e2.set_author(name=f'[{self.player.region.name}] {self.player.nickname}')
        e2.add_field(name='Main Battery', value=mb)
        e2.add_field(name='Secondary Battery', value=sb)
        e2.add_field(name='Torpedoes', value=trp)
        e2.add_field(name='Ramming', value=ram)
        e2.add_field(name='Aircraft', value=cv)

        cap_solo = p_stats.pop('control_captured_points')
        cap_team = p_stats.pop('team_capture_points')
        cap_rate = cap_solo / cap_team * 100

        def_solo = p_stats.pop('control_dropped_points')
        def_team = p_stats.pop('team_dropped_capture_points')
        def_rate = def_solo / def_team * 100

        # Capture Points & Defends, Distance Travelled
        e2.description = (f"Distance Travelled: {p_stats['distance']}"
                          f"Capture Contribution: {cap_solo} / {cap_rate} ({cap_team}%)\n"
                          f"Defence Contribution: {def_solo} / {def_team} ({def_rate})")

        print("wows_utils - stats - Unhandled Data remaining", p_stats)
        self.pages = [e, e2]
        return await self.update(mode=mode, div_size=div_size)

    async def update(self, mode: Mode, content: str = "", div_size: int = 0) -> Message:
        """Send the latest version of the embed to view"""
        self.add_item(FuncButton(func=self.push_stats, label=Mode.PVP.mode_name, kwargs={'mode': Mode.PVP},
                                 disabled=mode == mode.PVP))
        self.add_item(FuncButton(func=self.push_stats, label=Mode.RANKED.mode_name, kwargs={'mode': Mode.RANKED},
                                 disabled=mode == Mode.RANKED))
        self.add_item(FuncButton(func=self.push_stats, label=Mode.COOP.mode_name, kwargs={'mode': Mode.COOP},
                                 disabled=mode == Mode.COOP))

        self.add_item(FuncButton(func=self.push_stats, kwargs={'div_size': 0, 'mode': mode}, label="Overall",
                                 row=1, disabled=div_size == 0))
        self.add_item(FuncButton(func=self.push_stats, kwargs={'div_size': 1, 'mode': mode}, label="Solo",
                                 row=1, disabled=div_size == 1))
        self.add_item(FuncButton(func=self.push_stats, kwargs={'div_size': 2, 'mode': mode}, label="Division (2)",
                                 row=1, disabled=div_size == 2))
        self.add_item(FuncButton(func=self.push_stats, kwargs={'div_size': 3, 'mode': mode}, label="Division (3)",
                                 row=1, disabled=div_size == 3))
        return await self.bot.reply(self.interaction, content=content, embed=self.pages[self.index], view=self)


MODULES = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"


class Ship:
    """A World of Warships Ship."""
    # Class attr.
    bot: PBot = None

    def __init__(self, bot: 'PBot') -> None:
        self.bot: PBot = bot
        self.name: str = 'Unknown Ship'
        self.ship_id: int = 0
        self.ship_id_str: str = ''

        if TYPE_CHECKING:
            self.description: str  # Ship description
            self.has_demo_profile: bool  # Indicates that ship characteristics are for illustration, and may be changed.
            self.is_premium: bool  # Indicates if the ship is Premium ship
            self.is_special: bool  # Indicates if the ship is on a special offer
            self.mod_slots: int  # Number of slots for upgrades
            self.nation: Nation  # Ship Nation
            self.next_ships: List[Dict]  # List of ships available for research in form of pairs
            self.price_credit: int  # Cost in credits
            self.price_gold: int  # Cost in doubloons
            self.tier: int  # Tier of the ship (1 - 11 for super)
            self.type: ShipType  # Type of ship
            self.upgrades: List[int]  # List of compatible Modifications IDs

    @classmethod
    async def by_id(cls, bot: 'PBot', ship_id_str: str):
        """Get a ship via it's ID number from the API"""
        # TODO: By_ID
        raise NotImplementedError

    @property
    def ac_row(self) -> str:
        """Autocomplete text"""
        tier = getattr(self, 'tier', '')
        name = getattr(self, 'name', 'Unknown Ship')
        nation = getattr(self, 'nation', None)
        nation = 'Unknown nation' if nation is None else nation.alias
        type_ = getattr(self, 'type', None)
        type_ = 'Unknown class' if type_ is None else type_.alias
        return f"{tier}: {name} {nation} {type_}"

    async def fetch_modules(self) -> List[Module]:
        """Grab all data related to the ship from the API"""
        modules = getattr(self, 'modules', dict())
        # Get all module IDs
        modules = sorted({x for v in modules.values() for x in v if x not in self.bot.modules})

        print('Fetching data for modules', modules)

        p = {'application_id': self.bot.WG_ID, 'modules': ','.join(modules)}
        async with self.bot.session.get(MODULES, params=p) as resp:
            match resp.status:
                case 200:
                    data = await resp.json()
                case _:
                    print(f'Unable to fetch modules for {getattr(self, "name", "Unknown Ship")}')

        for k, v in data['data'].items():
            print('Printing Module Data')
            for sub_k, sub_v in v.items():
                print('---', sub_k, sub_v)

            match k['profile']:
                case 'artillery':
                    module = Artillery()
                case 'dive_bomber':
                    module = DiveBomber()
                case 'engine':
                    module = Engine()
                case 'fighter':
                    module = Fighter()
                case 'fire_control':
                    module = FireControl()
                case 'flight_control':
                    module = FlightControl()
                case 'hull':
                    module = Hull()
                case 'torpedo_bomber':
                    module = TorpedoBomber()
                case 'torpedoes':
                    module = Torpedoes()
                case _:
                    module = Module()
                    print('unhandled profile ', k['profile'])

            self.bot.modules.append(module)

        return modules

    async def save_to_db(self) -> None:
        """Save the ship to the painezBot database"""
        sql = """INSERT INTO ships (id, name, nation, premium, special, tier, type, description) 
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8"""

        id_ = getattr(self, 'id', None)
        if id_ is None:
            return

        name = getattr(self, 'name', None)
        if name is None:
            return

        # Default attrs.
        nation = getattr(self, 'nation', None)
        premium = getattr(self, 'premium', None)
        special = getattr(self, 'special', None)
        tier = getattr(self, 'tier', None)
        type_ = getattr(self, 'type', None)
        description = getattr(self, 'description', None)

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(sql, id_, name, nation, premium, special, tier, type_, description)
        finally:
            await self.bot.db.release(connection)

    def view(self, interaction: Interaction):
        """Get a view to browse this ship's data"""
        return ShipView(self.bot, interaction, self)


class ShipView(View):
    """A view representing a ship, with buttons to change between different menus."""

    def __init__(self, bot: 'PBot', interaction: Interaction, ship: Ship) -> None:
        super().__init__()
        self.bot: PBot = bot
        self.interaction: Interaction = interaction
        self.ship: Ship = ship

        self.index: int = 0
        self.pages: List[Embed] = []

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of command."""
        return self.interaction.user.id == interaction.user.id

    async def overview(self) -> Message:
        """Get a general overview of the ship"""
        prem = any([getattr(self.ship, 'is_premium', False), getattr(self.ship, 'is_special', False)])

        cl: ShipType = getattr(self.ship, 'type', '')
        if cl:
            icon_url = cl.image_premium if prem else cl.image
            cl: str = cl.alias
        else:
            icon_url = None

        tier = getattr(self.ship, 'tier', '')
        slots = getattr(self.ship, 'mod_slots', 0)

        # Check for bonus Slots (Arkansas Beta, Z-35, ...)
        slt = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 5, 9: 6, 10: 6, 11: 6, '': ''}.pop(tier)
        if tier:
            tier = f"Tier {tier}"

        nation: Nation = getattr(self.ship, 'nation', '')
        if nation:
            nation: str = nation.alias

        e = Embed(title=getattr(self.ship, 'name', 'Unknown Ship'))
        e.set_author(name=" ".join([i for i in [tier, nation, cl] if i]), icon_url=icon_url)
        if slots != slt:
            e.add_field(name="Bonus Upgrade Slots", value=f"This ship has {slots} upgrades instead of {slt[tier]}")

        if hasattr(self.ship, 'images'):
            e.set_image(url=self.ship.images['large'])
            e.set_thumbnail(url=self.ship.images['contour'])

        if hasattr(self.ship, 'description'):
            e.set_footer(text=self.ship.description)

        desc = []
        doubloons = getattr(self.ship, 'price_gold', 0)
        if doubloons:
            desc.append(f"Doubloon Price: {doubloons}")

        creds = getattr(self.ship, 'price_credit', 0)
        if creds:
            desc.append(f"Credit Price: {format(creds, ',')}")

        nda = getattr(self.ship, 'has_demo_profile', True)
        if nda:
            e.add_field(name='Work in Progress', value="Ship Characteristics are not Final.")

        e.description = '\n'.join(desc)

        modules = await self.ship.fetch_modules()

        for k, v in self.ship.__dict__.items():
            match k:
                case 'tier' | 'nation' | 'name' | 'type' | 'images' | 'description' | 'is_premium' | 'is_special' | \
                     'ship_id_str' | 'price_gold' | 'price_credit' | 'next_ships' | 'has_demo_profile' | 'mod_slots':
                    pass
                case 'upgrades':
                    print(k, v)
                case 'default_profile':
                    print(k)
                    for sub_k, sub_v in v.items():
                        if sub_v is not None:
                            print(' ---- ', sub_k, sub_v)
                case _:
                    print(k, v)

        self.pages = [e]
        return await self.update()

    async def update(self, content="") -> Message:
        """Push the latest version of the view to the user"""
        self.clear_items()
        add_page_buttons(self)

        nxt = getattr(self.ship, 'next_ships', None)
        for ship in nxt:
            print("Hello yes please add button for next ship", ship)
            # TODO: Add Button to change to next ship.
            pass

        # FuncButton - Overview, Armaments

        return await self.bot.reply(self.interaction, content=content, embed=self.pages[self.index], view=self)
