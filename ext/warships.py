"""Private world of warships related commands"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from discord import Embed, ButtonStyle, Message, Colour
from discord.app_commands import command, describe, default_permissions, autocomplete, Choice, guilds, Range
from discord.ext.commands import Cog
from discord.ui import View, Button
from unidecode import unidecode

from ext.utils.ship import Nation, ShipType, Ship
from ext.utils.wows_utils import Region, Map, Player, GameMode, ClanBuilding

if TYPE_CHECKING:
    from painezBot import PBot
    from typing import List
    from discord import Interaction

# TODO: Over-match command (Take Either Armour or Caliber [/or ship] param, compare against table).
# TODO: Browse all Ships command. Filter Dropdowns. Dropdown to show specific ships.
# TODO: Container drops / https://worldofwarships.eu/en/content/contents-and-drop-rates-of-containers/
# TODO: Clan Base Commands # https://api.worldofwarships.eu/wows/clans/glossary/
# TODO: Recent command. # https://api.worldofwarships.eu/wows/account/statsbydate/

# noinspection SpellCheckingInspection
ASLAIN = 'https://aslain.com/index.php?/topic/2020-download-%E2%98%85-world-of-warships-%E2%98%85-modpack/'
# noinspection SpellCheckingInspection
MODSTATION = 'https://worldofwarships.com/en/content/modstation/'
MOD_POLICY = 'https://worldofwarships.com/en/news/general-news/mods-policy/'

# noinspection SpellCheckingInspection
RAGNAR = "Ragnar is inherently underpowered. It lacks the necessary attributes to make meaningful impact on match " \
         "result. No burst damage to speak of, split turrets, and yet still retains a fragile platform. I would take" \
         " 1 Conqueror..Thunderer or 1 DM or even 1 of just about any CA over 2 Ragnars on my team any day of the" \
         " week. Now... If WG gave it the specialized repair party of the Nestrashimy ( and 1 more base charge)..." \
         " And maybe a few more thousand HP if could make up for where it is seriously lacking with longevity"

API_PATH = "https://api.worldofwarships.eu/wows/"
INFO = API_PATH + 'encyclopedia/info/'
CLAN = API_PATH + 'clans/glossary/'
# noinspection SpellCheckingInspection
MAPS = API_PATH + 'encyclopedia/battlearenas/'
# noinspection SpellCheckingInspection
MODES = API_PATH + 'encyclopedia/battletypes/'
SHIPS = API_PATH + 'encyclopedia/ships/'
PLAYERS = API_PATH + 'account/list/'

# TODO: Overmatch DD/CV
OM_BB = {13: ['Tier 2-5 Superstructure'],
         16: ['Tier 2-5 Superstructure', 'Tier 2-3 Bow/Stern', 'Tier 3-7 British Battlecruiser Bow/Stern'],
         19: ['Tier 2-5 Bow/Stern', 'All Superstructure', 'Tier 3-7 British Battlecruiser Bow/Stern'],
         25: ['Tier 2-5 Bow/Stern', 'All Superstructure',
              'Florida, Mackensen, Prinz Heinrich, Borodino, Constellation, Slava Bow/Stern',
              'All UK BattleCruiser Bow/Stern'],
         26: ['Tier 2-7 Bow/Stern', 'All Superstructure',
              'Florida/Borodino/Constellation/Slava Bow/Stern',
              'UK BattleCruiser Bow/Stern'],
         27: ['Tier 2-7 Bow/Stern', 'All Superstructure',
              'Florida/Borodino/Constellation/Slava Bow/Stern',
              'UK BattleCruiser Bow/Stern',
              'German Battlecruiser Upper Bow/Stern'],
         32: ['All Bow/Stern except German/Kremlin/Italian Icebreaker', 'French/British Casemates',
              'Slava Deck']}

OM_CA = {6: ['Tier 1-3 Cruiser'],
         10: ['Tier 1-3 Plating',
              'Tier 1-5 Superstructure', ],
         13: ['Tier 1-5 Plating',
              'Tier 1-7 Most Superstructures',
              'Tier 1-7 Super light (127mms) plating'],
         16: ['Tier 1-5 Plating',
              'Tier 1-7 Superstructure',
              'Tier 1-7 Bow/Stern (Except Pensacola/New Orleans/Yorck)',
              'All British CLs and Smolensk plating',
              '127mm and below equipped super lights',
              ''],
         19: ['Tier 1-7 CL Side plating',
              'Tier 1-7 Superstructure',
              'Tier 1-7 Bow/Stern (Except Pensacola/New Orleans/Yorck). ',
              'All British CLs and Smolensk plating',
              '127mm super lights plating'],
         25: ['Tier 1-7 everywhere',
              'Tier 1-10 CL side plating',
              'Supership bow/stern (except US & German Heavy, and icebreakers)',
              'All British CLs and Smolensk plating',
              ],
         27: ['Tier 1-9 decks',
              'Supership bow/stern',
              'All British CLs and smolensk plating',
              ],
         30: ['Supership Decks',
              'Supership bow/stern',
              'Supership plating'],
         32: ['Supership Decks', 'Supership bow/stern', 'Supership plating', 'Austin/Jinan Casemate'],
         35: ['Supership Decks', 'Supership bow/stern', 'Supership plating', 'Austin/Jinan Casemate', 'Riga Deck']
         }


# TODO: Calculation of player's PR
# https://wows-numbers.com/personal/rating

# Autocomplete.
async def map_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Autocomplete for the list of maps in World of Warships"""
    maps: List[Map] = getattr(interaction.client, 'maps', [])

    # Run Once
    if not maps:
        session = getattr(interaction.client, 'session')
        wg_id = getattr(interaction.client, 'WG_ID')

        p = {'application_id': wg_id, 'language': 'en'}
        async with session.get(MAPS, params=p) as resp:
            match resp.status:
                case 200:
                    items = await resp.json()
                case _:
                    print(resp.status, "Error accessing WG API")
                    return []

        maps = []

        _maps = items['data']
        for k, v in _maps.items():
            name = v['name']
            description = v['description']
            icon = v['icon']
            map_id = k
            maps.append(Map(name, description, map_id, icon))

        interaction.client.maps = maps

    filtered = sorted([i for i in maps if current.lower() in i.ac_row.lower()], key=lambda x: x.name)
    return [Choice(name=i.ac_row[:100], value=i.battle_arena_id) for i in filtered][:25]


async def mode_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Fetch a Game Mode"""
    bot: PBot = getattr(interaction, 'client')

    if not bot.modes:
        async with bot.session.get(MODES, params={'application_id': bot.WG_ID}) as resp:
            match resp.status:
                case 200:
                    modes = await resp.json()
                case _:
                    return []

        bot.modes = {GameMode(**v) for k, v in modes['data'].items()}
    return [Choice(name=i.name, value=i.tag) for i in bot.modes if current.lower() in i.name.lower()]


async def player_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Fetch player's account ID by searching for their name."""
    if len(current) < 3:
        return []

    bot: PBot = getattr(interaction, 'client')
    p = {'application_id': bot.WG_ID, "search": current, 'limit': 25}

    region = getattr(interaction.namespace, 'region', None)
    region = next((i for i in Region if i.db_key == region), Region.EU)

    link = PLAYERS.replace('eu', region.domain)
    async with bot.session.get(link, params=p) as resp:
        match resp.status:
            case 200:
                players = await resp.json()
            case _:
                return []

    data = players.pop('data', None)
    if data is None:
        return []

    choices = []
    for i in data:
        try:
            player = next(pl for pl in bot.players if pl.account_id == i['account_id'])
        except StopIteration:
            player = Player(bot, i['account_id'], region, i['nickname'])
            bot.players.append(player)

        if player.clan is None:
            choices.append(Choice(name=player.nickname, value=str(player.account_id)))
        else:
            choices.append(Choice(name=f"[{player.clan.tag}] {player.nickname}", value=str(player.account_id)))
    return choices


async def ship_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Autocomplete for the list of maps in World of Warships"""
    ships: List[Ship] = getattr(interaction.client, 'ships', [])
    filtered = sorted([i for i in ships if current.lower() in i.ac_row.lower()], key=lambda x: unidecode(x.name))
    return [Choice(name=i.ac_row[:100], value=i.ship_id_str) for i in filtered if hasattr(i, 'ship_id_str')][:25]


class Warships(Cog):
    """World of Warships related commands"""

    def __init__(self, bot: 'PBot') -> None:
        self.bot: PBot = bot

    async def cog_load(self) -> None:
        """Fetch Generics from API and store to bot."""
        p = {'application_id': self.bot.WG_ID, 'language': 'en'}
        if not self.bot.ship_types:
            async with self.bot.session.get(INFO, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        print('Unable to fetch ship type data.')
                        return

            for k, v in data['data']['ship_types'].items():
                images = data['data']['ship_type_images'][k]
                s_t = ShipType(k, v, images)
                self.bot.ship_types.append(s_t)

        if not self.bot.modes:
            async with self.bot.session.get(MODES, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        return

            for k, v in data['data'].items():
                self.bot.modes.append(GameMode(**v))

        if not self.bot.ships:
            self.bot.ships = await self.cache_ships()

        if not self.bot.clan_buildings:
            self.bot.clan_buildings = await self.cache_clan_base()

    async def cache_clan_base(self) -> List[ClanBuilding]:
        """Cache the CLan Buildings from the API"""
        return []  # TODO: NotImplemented
        # buildings = json.pop()
        # output = []
        # for i in buildings:
        #
        #     # self.building_id: int = building_id
        #     # self.building_type_id: int = kwargs.pop('building_type_id', None)
        #     # self.bonus_type: Optional[str] = kwargs.pop('bonus_type', None)
        #     # self.bonus_value: Optional[int] = kwargs.pop('bonus_value', None)
        #     # self.cost: Optional[int] = kwargs.pop('cost', None)  # Price in Oil
        #     # self.max_members: Optional[int] = kwargs.pop('max_members', None)
        #
        #     max_members = buildings.pop()
        #
        #     b = ClanBuilding()

    async def cache_ships(self) -> List[Ship]:
        """Cache the ships from the API."""
        # Run Once.
        if self.bot.ships:
            return self.bot.ships

        max_iter: int = 1
        count: int = 1
        ships: List[Ship] = []
        while count <= max_iter:
            # Initial Pull.
            p = {'application_id': self.bot.WG_ID, 'language': 'en', 'page_no': count}
            async with self.bot.session.get(SHIPS, params=p) as resp:
                match resp.status:
                    case 200:
                        items = await resp.json()
                        count += 1
                    case _:
                        print(resp.status, "Error accessing WG API")
                        break

            max_iter = items['meta']['page_total']

            for ship, data in items['data'].items():
                ship = Ship(self.bot)

                nation = data.pop("nation", None)
                if nation:
                    ship.nation = next(i for i in Nation if nation == i.match)

                ship.type = self.bot.get_ship_type(data.pop('type'))

                modules = data.pop('modules')
                ship._modules = modules
                for k, v in data.items():
                    setattr(ship, k, v)
                ships.append(ship)
        return ships

    async def send_code(self, code: str, contents: str, interaction: Interaction, **kwargs) -> Message:
        """Generate the Embed for the code."""
        e = Embed(title="World of Warships Redeemable Code")
        e.title = code
        e.description = ""
        e.set_author(name="World of Warships Bonus Code")
        e.set_thumbnail(url=interaction.client.user.avatar.url)
        if contents:
            e.description += f"Contents:\n```yaml\n{contents}```"
        e.description += "Click on a button below to redeem for your region"

        for k, v in kwargs.items():
            if v:
                print("kwarg", k, v)
                region = next(i for i in Region if k == i.db_key)
                e.colour = region.colour
                break

        view = View()
        for k, v in kwargs.items():
            if v:
                region = next(i for i in Region if k == i.db_key)
                url = f"https://{region.code_prefix}.wargaming.net/shop/redeem/?bonus_mode=" + code
                view.add_item(Button(url=url, label=region.name, style=ButtonStyle.url, emoji=region.emote))

        return await self.bot.reply(interaction, embed=e, view=view)

    @command()
    async def ragnar(self, interaction: Interaction) -> Message:
        """Ragnar is inherently underpowered"""
        return await self.bot.reply(interaction, content=RAGNAR)

    @command()
    @describe(code="Enter the code", contents="Enter the reward the code gives")
    @default_permissions(manage_messages=True)
    async def code(self, interaction: Interaction, code: str, contents: str,
                   eu: bool = True, na: bool = True, asia: bool = True) -> Message:
        """Send a message with region specific redeem buttons"""
        await interaction.response.defer(thinking=True)
        return await self.send_code(code, contents, interaction, eu=eu, na=na, sea=asia)

    @command()
    @describe(code="Enter the code", contents="Enter the reward the code gives")
    @default_permissions(manage_messages=True)
    async def code_cis(self, interaction: Interaction, code: str, contents: str) -> Message:
        """Send a message with a region specific redeem button"""
        await interaction.response.defer(thinking=True)
        return await self.send_code(code, contents, interaction, cis=True)

    @command()
    @describe(code_list="Enter a list of codes, | and , will be stripped, and a list will be returned.")
    async def code_parser(self, interaction: Interaction, code_list: str) -> Message:
        """Strip codes for world of warships CCs"""
        code_list = code_list.replace(';', '')
        code_list = code_list.split('|')
        code_list = "\n".join([i.strip() for i in code_list if i])
        return await self.bot.reply(interaction, content=f"```\n{code_list}```", ephemeral=True)

    @command()
    @autocomplete(name=map_ac)
    @describe(name="Search for a map by name")
    async def map(self, interaction: Interaction, name: str) -> Message:
        """Fetch a map from the world of warships API"""
        await interaction.response.defer()

        if not self.bot.maps:
            return await self.bot.error(interaction, f'Unable to fetch maps from API')

        try:
            map_ = next(i for i in self.bot.maps if i.battle_arena_id == name)
        except StopIteration:
            return await self.bot.error(interaction, f"Did not find map matching {name}, sorry.")

        return await self.bot.reply(interaction, embed=map_.embed)

    @command()
    async def mods(self, interaction: Interaction) -> Message:
        """information about where to get World of Warships modifications"""
        e = Embed(colour=Colour.red())
        e.set_thumbnail(url='http://i.imgur.com/2LiednG.jpg')
        e.title = "World of Warships Mods"
        e.description = "There are two official sources available for in-game modifications.\n" \
                        f"• [Modstation]({MODSTATION})\n• [Official Forum]({ASLAIN})\n\n" \
                        f"[Aslain's Modpack]({ASLAIN}) is a popular third party compilation of mods available from " \
                        f"the official forum\n"
        e.add_field(name='Mod Policy', value=MOD_POLICY)
        v = View()
        v.add_item(Button(url=MODSTATION, label="Modstation"))
        v.add_item(Button(url=ASLAIN, label="Aslain's Modpack"))
        return await self.bot.reply(interaction, embed=e)

    @command()
    async def builds(self, interaction: Interaction) -> Message:
        """The Help Me Build collection"""
        e = Embed(title="Help Me Builds", description="http://wo.ws/builds")
        return await self.bot.reply(interaction, embed=e)

    @command()
    async def guides(self, interaction: Interaction) -> Message:
        """Yurra's collection of guides"""
        yurra = self.bot.get_user(192601340244000769)
        e = Embed(title="Yurra's guides", description='https://bit.ly/yurraguides')
        e.set_thumbnail(url=yurra.avatar.url)
        return await self.bot.reply(interaction, embed=e)

    # Work In Progress.
    @command()
    @autocomplete(name=ship_ac)
    @guilds(250252535699341312)
    @describe(name="Search for a ship by it's name")
    async def ship(self, interaction: Interaction, name: str) -> Message:
        """Search for a ship in the World of Warships API"""
        await interaction.response.defer()

        if not self.bot.ships:
            return await self.bot.error(interaction, content='Unable to fetch ships from API')

        ship = await self.bot.get_ship(name)
        if ship is None:
            return await self.bot.error(interaction, f"Did not find map matching {name}, sorry.")

        return await ship.view(interaction).overview()

    @command()
    @autocomplete(player_name=player_ac, mode=mode_ac)
    @guilds(250252535699341312)
    @describe(player_name="Search for a player name", region="Which region is this player on",
              mode="battle mode type", division='1 = solo, 2 = 2man, 3 = 3man, 0 = Overall')
    async def stats(self, interaction: Interaction, region: Literal['eu', 'na', 'cis', 'sea'], player_name: str,
                    mode: str = 'PVP', division: Range[int, 0, 3] = 0) -> Message:
        """Search for a player's Stats"""
        await interaction.response.defer()

        region = next(i for i in Region if i.db_key == region)
        try:
            # This is transformed by autocomplete.
            player_id = int(player_name)
            player: Player = next(i for i in self.bot.players if i.account_id == player_id and i.region == region)
        except ValueError:
            try:
                player = next(i for i in self.bot.players if player_name in i.nickname and i.region == region)
            except StopIteration:
                return await self.bot.error(interaction, f"Could not find player_id for player {region.name} "
                                                         f"{player_name}")
        except StopIteration:
            return await self.bot.error(interaction, f'Something weird happened with {region.name} {player_name}')

        mode = next(i for i in self.bot.modes if i.tag == mode)
        v = player.view(interaction, mode, division)
        return await v.mode_stats()

    @command()
    @describe(shell_calibre='Calibre of shell to get over match value of')
    async def overmatch(self, interaction: Interaction, shell_calibre: int) -> Message:
        """Get information about what a shell's overmatch parameters"""
        await interaction.response.defer(thinking=True)
        value = round(shell_calibre / 14.3)
        e = Embed(title=f"{shell_calibre}mm Shells overmatch {value}mm of Armour", colour=0x0BCDFB)
        e.add_field(name="Cruisers", value='\n'.join(OM_CA[max(i for i in OM_CA if i < value)]), inline=False)
        e.add_field(name="Battleships", value='\n'.join(OM_BB[max(i for i in OM_BB if i < value)]), inline=False)
        om_image = 'https://media.discordapp.net/attachments/303154190362869761/990588535201484800/unknown.png'
        e.set_thumbnail(url=om_image)
        e.set_footer(text=f"{shell_calibre}mm / 14.3 = {value}mm")
        return await self.bot.reply(interaction, embed=e)

    @command()
    async def exterior_separation(self, interaction: Interaction) -> Message:
        """Send a list of all the exterior separation changes"""
        e = Embed()
        e.title = "Exterior Separation Change List"
        e.description = (
            "• Economic bonuses will now act as individual in-game entities that are separate from "
            "camouflages and signals. Camouflage patterns will change a ship's exterior only and will be applied "
            "separately from these bonuses. "
            "\n• Bonuses to XP will have no effect on Free XP and Commander XP. To compensate for this, we have changed"
            " all permanent and expendable economic bonuses."
            "\n• Basic Free XP earnings are now twice as large."
            "\n• Economic bonuses from permanent camouflages are purchased separately, and their effect will be applied"
            " towards a ship's economy on a permanent basis. Expendable bonuses can also be added on top of permanent "
            "ones."
            "\n• Only one economic bonus can be applied towards each of the resources (Credits, combat XP, Free XP, "
            "and Commander XP) at the same time. This limitation serves to simplify the way the system works. The "
            "values of these bonuses are designed in a way that they can cover even the most profitable combinations "
            "from the current system."
            "\n• Instead of reducing the post-battle service cost, permanent camouflages will provide a bonus to "
            "Credits so that your average earnings either remain unchanged or grow."
            "\n•The service cost for Tier IX and X researchable ships has been reduced from 120,000 to 115,000 and "
            "from 180,000 to 150,000 Credits, respectively."
            "\n• To account for the changes to bonuses applied towards service costs, the current service cost in "
            "Co-op Battles will be additionally reduced by 13.3% while Credits earnings will grow by 12.5%."
            "\n• We want camouflages to affect ship exteriors only, so we’re removing all the combat bonuses they used "
            "to offer. The bonus that provided a 3% reduction in the detectability range by sea is now included in all "
            "ships' tech specs by default. We also removed the bonus that increased the dispersion of incoming enemy "
            "shells by 4%."
            "\n• At present, the number of signals and camouflages displayed in the Exterior tab does not include "
            "those currently  mounted on your ships. When this change goes live, you will always know the exact number "
            "of reserves you have  in stock—the total number of signals and camouflage patterns you have on your "
            "account will be displayed. ")
        e.colour = Colour.yellow()
        e.set_thumbnail(url='https://wiki.wgcdn.co/images/7/7a/PCEC001_Camo_1.png')
        await self.bot.reply(interaction, embed=e)


async def setup(bot: 'PBot'):
    """Load the cog into the bot"""
    await bot.add_cog(Warships(bot))
