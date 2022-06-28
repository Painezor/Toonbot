"""Ship Objects and associated classes"""
from __future__ import annotations

from copy import deepcopy
from enum import Enum
from types import DynamicClassAttribute
from typing import TYPE_CHECKING, Type, Callable

import unidecode as unidecode
from discord import Interaction, Message, Embed, SelectOption
from discord.ui import View, Button, Select

from ext.utils.view_utils import FuncButton

if TYPE_CHECKING:
    from painezBot import PBot
    from typing import Optional, List, Dict
    from typing_extensions import Self


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
    EUROPE = ('Pan-European', 'europe', '🇪🇺')
    FRANCE = ('French', 'france', '🇫🇷')
    GERMANY = ('German', 'germany', '🇩🇪')
    ITALY = ('Italian', 'italy', '🇮🇹')
    JAPAN = ('Japanese', 'japan', '🇯🇵')
    NETHERLANDS = ('Dutch', 'netherlands', '🇳🇱')
    PAN_ASIA = ('Pan-Asian', 'pan_asia', '')
    PAN_AMERICA = ('Pan-American', 'pan_america', '')
    SPAIN = ('Spanish', 'spain', '🇪🇸')
    UK = ('British', 'uk', '🇬🇧')
    USSR = ('Soviet', 'ussr', '')
    USA = ('American', 'usa', '🇺🇸')


class Fitting:
    """A Ship Configuration"""
    bot: PBot = None

    def __init__(self, ship: Ship, data: dict = None) -> None:
        self.ship: Ship = ship

        if self.__class__.bot is None:
            self.__class__.bot = ship.bot

        # Current Configuration
        self.modules: Dict[Type[Module], int] = {}
        # self.artillery: Artillery = None
        # self.dive_bomber: DiveBomber = None
        # self.engine: Engine = None
        # self.fire_control: FireControl = None
        # self.flight_control: FlightControl = None
        # self.hull: Hull = None
        # self.rocket_planes: RocketPlane = None
        # self.torpedo_bomber: TorpedoBomber = None
        # self.torpedoes: Torpedoes = None

        # Parsed Data
        self.data: dict = data

    async def get_params(self) -> dict:
        """Get the ship's specs with the currently selected modules."""
        p = {'application_id': self.bot.WG_ID, 'ship_id': self.ship.ship_id}

        tuples = [('artillery_id', Artillery), ('dive_bomber_id', DiveBomber), ('engine_id', Engine),
                  ('fire_control_id', FireControl),  # ('flight_control_id', FlightControl),
                  ('hull_id', Hull), ('fighter_id', RocketPlane), ('torpedoes_id', Torpedoes),
                  ('torpedo_bomber_id', TorpedoBomber)]

        p.update({k: self.modules.get(v) for k, v in tuples if self.modules.get(v, None) is not None})

        url = "https://api.worldofwarships.eu/wows/encyclopedia/shipprofile/"
        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    print(f'HTTP ERROR {resp.status} accessing {url}')

        self.data = json['data'][str(self.ship.ship_id)]
        return self.data


class ShipType:
    """Submarine, Cruiser, etc."""

    def __init__(self, match: str, alias: str, images: dict):
        self.match: str = match
        self.alias: str = alias

        self.image = images['image']
        self.image_elite = images['image_elite']
        self.image_premium = images['image_premium']


class Ship:
    """A World of Warships Ship."""
    # Class attr.
    bot: PBot = None

    def __init__(self, bot: 'PBot') -> None:
        self.bot: PBot = bot
        self.name: str = 'Unknown Ship'
        self.ship_id: Optional[int] = None
        self.ship_id_str: Optional[str] = None

        # Initial Data
        self.description: Optional[str] = None  # Ship description
        self.has_demo_profile: bool = False  # Indicates that ship characteristics may be changed.
        self.is_premium: bool = False  # Indicates if the ship is Premium ship
        self.is_special: bool = False  # Indicates if the ship is on a special offer
        self.images: dict = {}  # A list of images
        self.mod_slots: int = 0  # Number of slots for upgrades
        self._modules: dict = {}  # Dict of Lists of available modules.
        self.modules_tree: dict = {}  #
        self.nation: Optional[Nation] = None  # Ship Nation
        self.next_ships: Dict = {}  # {k: ship_id as str, v: xp required as int }
        self.price_credit: int = 0  # Cost in credits
        self.price_gold: int = 0  # Cost in doubloons
        self.tier: Optional[int] = None  # Tier of the ship (1 - 11 for super)
        self.type: Optional[ShipType] = None  # Type of ship
        self.upgrades: List[int] = []  # List of compatible Modifications IDs

        # Fetched Modules
        self.modules: Dict[int, Module] = {}

        # Params Data
        self.default_profile: dict = None

    @property
    def ac_row(self) -> str:
        """Autocomplete text"""
        nation = 'Unknown nation' if self.nation is None else self.nation.alias
        type_ = 'Unknown class' if self.type is None else self.type.alias

        # Remove Accents.
        decoded = unidecode.unidecode(self.name)
        return f"{self.tier}: {decoded} {nation} {type_}"

    @property
    def default_fit(self) -> Fitting:
        """Generate a fitting from the default modules of this ship."""
        tree = self.modules_tree
        fit = Fitting(self, data=self.default_profile)
        for module_id, module_type in {int(k): v['type'] for k, v in tree.items() if v['is_default']}.items():
            match module_type:
                case 'Artillery':
                    fit.modules[Artillery] = module_id
                case 'DiveBomber':
                    fit.modules[DiveBomber] = module_id
                case 'Engine':
                    fit.modules[Engine] = module_id
                case 'Hull':
                    fit.modules[Hull] = module_id
                case 'Fighter':
                    fit.modules[RocketPlane] = module_id
                case 'Suo':
                    fit.modules[FireControl] = module_id
                case 'Torpedoes':
                    fit.modules[Torpedoes] = module_id
                case 'TorpedoBomber':
                    fit.modules[TorpedoBomber] = module_id
                case _:
                    print('Unhandled Module type when setting default fit', module_id, module_type)
                    continue
        return fit

    async def fetch_modules(self) -> List[Module]:
        """Grab all data related to the ship from the API"""
        # Get needed module IDs
        targets = [str(x) for v in self._modules.values() for x in v if x not in self.bot.modules]
        existing = [x for x in self._modules.values() if x in [s.module_id for s in self.bot.modules]]

        # We use a deepcopy, because we're editing values with data from modules tree, but each module can be used on
        # a number of different ships, and we do not want to contaminate *their* data.
        self.modules.update({k.module_id: deepcopy(k) for k in existing})

        if targets:
            # We want the module IDs as str for the purposes of params
            p = {'application_id': self.bot.WG_ID, 'module_id': ','.join(targets)}
            url = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"
            async with self.bot.session.get(url, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        print(f'Unable to fetch modules for {self.name}')

            for module_id, data in data['data'].items():
                args = {k: data.pop(k) for k in ['name', 'image', 'tag', 'module_id_str', 'module_id', 'price_credit']}

                module_type = data.pop('type')
                kwargs = data.pop('profile').popitem()[1]
                args.update(kwargs)

                match module_type:
                    case 'Artillery':
                        module = Artillery(**args)
                    case 'DiveBomber':
                        module = DiveBomber(**args)
                    case 'Engine':
                        module = Engine(**args)
                    case 'Fighter':
                        module = RocketPlane(**args)
                    case 'Suo':
                        module = FireControl(**args)
                    case 'Hull':
                        module = Hull(**args)
                    case 'TorpedoBomber':
                        module = TorpedoBomber(**args)
                    case 'Torpedoes':
                        module = Torpedoes(**args)
                    case 'flight_control':
                        print('Somehow found a flight_control module with id', module_id, 'on ship id', self.ship_id)
                        module = Module(**args)
                    case _:
                        print('Unhandled Module type', module_type)
                        module = Module(**args)

                self.bot.modules.append(module)
                self.modules.update({int(module_id): deepcopy(module)})

        for k, v in self.modules_tree.items():
            module = self.modules.get(int(k))
            for sub_key, sub_value in v.items():
                setattr(module, sub_key, sub_value)
        return self.modules

    def view(self, interaction: Interaction):
        """Get a view to browse this ship's data"""
        return ShipView(self.bot, interaction, self)


class ShipSentinel(Enum):
    """A special Sentinel Ship object if we cannot find the original ship"""

    def __new__(cls, *args, **kwargs) -> Self:
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, ship_id: int, name: str, tier: int) -> None:
        self.id: str = ship_id
        self._name: str = name
        self.tier: int = tier

    @DynamicClassAttribute
    def name(self) -> str:
        """Override 'name' attribute."""
        return self._name

    # IJN DD Split
    FUBUKI_OLD = (4287510224, 'Fubuki (pre 01-12-2016)', 8)
    HATSUHARU_OLD = (4288558800, 'Hatsuharu (pre 01-12-2016)', 7)
    KAGERO_OLD = (4284364496, 'Kagero (pre 01-12-2016)', 9)
    MUTSUKI_OLD = (4289607376, 'Mutsuki (pre 01-12-2016)', 6)

    # Soviet DD Split
    GNEVNY_OLD = (4184749520, 'Gnevny (pre 06-03-2017)', 5)
    OGNEVOI_OLD = (4183700944, 'Ognevoi (pre 06-03-2017)', 6)
    KIEV_OLD = (4180555216, 'Kiev (pre 06-03-2017)', 7)
    TASHKENT_OLD = (4181603792, 'Tashkent (pre 06-03-2017)', 8)

    # US Cruiser Split
    CLEVELAND_OLD = (4287543280, 'Cleveland (pre 31-05-2018)', 6)
    PENSACOLA_OLD = (4282300400, 'Pensacola (pre 31-05-2018)', 7)
    NEW_ORLEANS_OLD = (4280203248, 'New Orleans (pre 31-05-2018)', 8)
    BALTIMORE_OLD = (4277057520, 'Baltimore (pre 31-05-2018)', 9)

    # CV Rework
    HOSHO_OLD = (4292851408, 'Hosho (pre 30-01-2019)', 4)
    ZUIHO_OLD = (4288657104, 'Zuiho (pre 30-01-2019)', 5)
    RYUJO_OLD = (4285511376, 'Ryujo (pre 30-01-2019)', 6)
    HIRYU_OLD = (4283414224, 'Hiryu (pre 30-01-2019)', 7)
    SHOKAKU_OLD = (4282365648, 'Shokaku (pre 30-01-2019)', 8)
    TAIHO_OLD = (4279219920, 'Taiho (pre 30-01-2019)', 9)
    HAKURYU_OLD = (4277122768, 'Hakuryu (pre 30-01-2019)', 10)

    LANGLEY_OLD = (4290754544, 'Langley (pre 30-01-2019)', 4)
    BOGUE_OLD = (4292851696, 'Bogue (pre 30-01-2019)', 5)
    INDEPENDENCE_OLD = (4288657392, 'Independence (pre 30-01-2019)', 6)
    RANGER_OLD = (4284463088, 'Ranger (pre 30-01-2019)', 7)
    LEXINGTON_OLD = (4282365936, 'Lexington (pre 30-01-2019)', 8)
    ESSEX_OLD = (4281317360, 'Essex (pre 30-01-2019)', 9)
    MIDWAY_OLD = (4279220208, 'Midway (pre 30-01-2019)', 10)

    KAGA_OLD = (3763320528, 'Kaga (pre 30-01-2019)', 7)
    SAIPAN_OLD = (3763320816, 'Saipan (pre 30-01-2019)', 7)
    ENTERPRISE_OLD = (3762272240, 'Enterprise (pre 30-01-2019)', 8)
    GRAF_ZEPPELIN_OLD = (3762272048, 'Graf Zeppelin (pre 30-01-2019)', 8)


class ShipButton(Button):
    """Change to a view of a different ship"""

    def __init__(self, interaction: Interaction, ship: Ship, row: int = 0, higher: bool = False) -> None:
        self.ship: Ship = ship
        self.interaction: Interaction = interaction

        super().__init__(label=f"Tier {ship.tier}: {ship.name}", row=row, emoji="▶" if higher else "◀")

    async def callback(self, interaction: Interaction) -> Message:
        """Change message of interaction to a different ship"""
        await interaction.response.defer()
        return await self.ship.view(self.interaction).overview()


class ShipView(View):
    """A view representing a ship, with buttons to change between different menus."""

    def __init__(self, bot: 'PBot', interaction: Interaction, ship: Ship) -> None:
        super().__init__()
        self.bot: PBot = bot
        self.interaction: Interaction = interaction
        self.ship: Ship = ship

        self.fitting: Fitting = ship.default_fit
        self.disabled: Optional[Callable] = None

    @property
    def base_embed(self) -> Embed:
        """Get a generic embed for the ship"""
        prem = any([self.ship.is_premium, self.ship.is_special])

        e = Embed()
        _class = self.ship.type
        if _class is not None:
            icon_url = _class.image_premium if prem else _class.image
            _class = _class.alias
        else:
            icon_url = None

        nation = self.ship.nation.alias if self.ship.nation else ''
        tier = f'Tier {self.ship.tier}' if self.ship.tier else ''
        e.set_author(name=" ".join([i for i in [tier, nation, _class, self.ship.name] if i]), icon_url=icon_url)

        if self.ship.images:
            e.set_thumbnail(url=self.ship.images['contour'])
        return e

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Clear the view"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def aircraft(self) -> Message:
        """Get information about the ship's Aircraft"""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed

        # Rocket Planes are referred to as 'Fighters'
        rp = self.fitting.data['fighters']
        if rp is not None:
            name = f"{rp['name']} (Tier {rp['plane_level']}, Rocket Planes)"
            value = [f"**Hit Points**: {format(rp['max_health'], ',')}",
                     f"**Cruising Speed**: {rp['cruise_speed']} kts",
                     f"\n*Rocket Plane Damage is not available in the API, sorry*"]
            e.add_field(name=name, value='\n'.join(value))

        tb = self.fitting.data['torpedo_bomber']
        if tb is not None:
            name = f"{tb['name']} (Tier {tb['plane_level']}, Torpedo Bombers"

            torp_name = 'Unnamed Torpedo' if tb['torpedo_name'] is None else tb['torpedo_name']
            value = [f"**Hit Points**: {format(tb['max_health'], ',')}",
                     f"**Cruising Speed**: {tb['cruise_speed']} kts",
                     "",
                     f"**{torp_name}**"
                     f"**Max Damage**: {format(tb['max_damage'])}",
                     f"**Max Speed**: {tb['torpedo_max_speed']} kts"
                     ]
            e.add_field(name=name, value='\n'.join(value))

        db = self.fitting.data['dive_bomber']
        if db is not None:
            name = f"{db['name']} (Tier {db['plane_level']}, Dive Bombers"

            bomb_name = 'Unnamed Bomb' if db['bomb_name'] is None else db['bomb_name']
            value = [f"**Hit Points**: {format(db['max_health'], ',')}",
                     f"**Cruising Speed**: {db['cruise_speed']} kts",
                     "",
                     f"**{bomb_name}**",
                     f"**Damage**: {format(db['max_damage'], ',')}",
                     f"**Mass**: {db['bomb_bullet_mass']}kg",
                     f"**Accuracy**: {db['accuracy']['min']} - {db['accuracy']['max']}"
                     ]

            fire_chance: float = db['bomb_burn_probability']
            if fire_chance is not None:
                value.append(f"**Fire Chance**: {round(fire_chance, 1)}%")

            e.add_field(name=name, value=value)

        fc = self.fitting.data['flight_control']
        if fc is not None:
            print('We have somehow found a Flight Control Module. This was not expected.'
                  'Printing FlightControl Dict\n', fc)

        self.disabled = self.aircraft
        e.set_footer(text='Rocket plane armaments, and Skip Bombers as a whole are currently not listed in the API.')
        return await self.update(embed=e)

    async def auxiliary(self) -> Message:
        """Get information on the ship's secondaries and anti-air."""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed

        # TODO: Parse auxiliary armaments.
        # Secondaries
        # AA

        self.disabled = self.auxiliary
        return await self.update(embed=e)

    async def main_guns(self) -> Message:
        """Get information about the ship's main battery"""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed

        # Guns
        mb = self.fitting.data['artillery']
        guns = []
        caliber = ""
        for gun_type in mb['slots'].values():
            e.title = gun_type['name']
            guns.append(f"{gun_type['guns']}x{gun_type['barrels']}")
            caliber = f"{e.title.split('mm')[0]}"

        reload_time: float = mb['shot_delay']

        mb_desc = [f"**Guns**: {','.join(guns)} {caliber}mm",
                   f"**Max Dispersion**: {mb['max_dispersion']}m",
                   f"**Range**: {mb['distance']}km",
                   f"**Reload Time**: {round(reload_time, 1)}s ({mb['gun_rate']} rounds/minute)"]

        e.description = "\n".join(mb_desc)

        for shell_type in mb['shells'].values():
            shell_data = [f"**Damage**: {format(shell_type['damage'], ',')}",
                          f"**Initial Velocity**: {format(shell_type['bullet_speed'], ',')}m/s",
                          f"**Shell Weight**: {format(shell_type['bullet_mass'], ',')}kg"]
            fire_chance = shell_type['burn_probability']
            if fire_chance is not None:
                shell_data.append(f"**Fire Chance**: {fire_chance}%")

            e.add_field(name=f"{shell_type['type']}: {shell_type['name']}", value="\n".join(shell_data))
        self.disabled = self.main_guns

        e.set_footer(text='SAP Shells are currently not listed in the API, sorry.')
        return await self.update(embed=e)

    async def torpedoes(self) -> Message:
        """Get information about the ship's torpedoes"""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed

        trp = self.fitting.data['torpedoes']
        for tube in trp['slots']:
            barrels = trp['slots'][tube]['barrels']
            calibre = trp['slots'][tube]['caliber']
            num_tubes = trp['slots'][tube]['guns']
            e.add_field(name=trp['slots'][tube]['name'], value=f"{num_tubes}x{barrels}x{calibre}mm")

        e.title = trp['torpedo_name']

        reload_time: float = trp['reload_time']

        trp_desc = [f"**Range**: {trp['distance']}km",
                    f"**Speed**: {trp['torpedo_speed']}kts",
                    f"**Damage**: {format(trp['max_damage'], ',')}",
                    f"**Detectability**: {trp['visibility_dist']}km",
                    f"**Reload Time**: {round(reload_time, 2)}s",
                    f"**Launchers**: {self.fitting.data['hull']['torpedoes_barrels']}",
                    f"**Launcher 180° Time**: {trp['rotation_time']}s",
                    ]

        e.description = "\n".join(trp_desc)
        self.disabled = self.torpedoes
        return await self.update(embed=e)

    async def overview(self) -> Message:
        """Get a general overview of the ship"""
        if not self.fitting.data:
            await self.fitting.get_params()

        params = self.fitting.data

        e = self.base_embed
        tier = self.ship.tier
        slots = self.ship.mod_slots

        # Check for bonus Slots (Arkansas Beta, Z-35, …)
        slt = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 5, 9: 6, 10: 6, 11: 6, '': ''}.pop(self.ship.tier)
        if slots != slt:
            e.add_field(name="Bonus Upgrade Slots", value=f"This ship has {slots} upgrades instead of {slt[tier]}")

        if self.ship.images:
            e.set_image(url=self.ship.images['large'])

        e.set_footer(text=self.ship.description)

        # Parse Modules for ship data
        desc = [f"**Hit Points**: {format(params['hull']['health'], ',')}",
                f"**Concealment**: {params['concealment']['detect_distance_by_ship']}km "
                f"({params['concealment']['detect_distance_by_plane']}km by air)",
                f"**Maximum Speed**: {params['mobility']['max_speed']}kts",
                f"**Rudder Shift Time**: {params['mobility']['rudder_time']} seconds",
                f"**Turning Radius**: {params['mobility']['turning_radius']}m",
                # f"-{params['armour']['flood_prob']}% flood chance."  This field appears to be Garbage.
                f"**Torpedo Belt**: -{params['armour']['flood_prob']}% damage"]

        # Build Rest of embed description
        if self.ship.price_gold != 0:
            desc.append(f"**Doubloon Price**: {format(self.ship.price_gold, ',')}")

        if self.ship.price_credit != 0:
            desc.append(f"**Credit Price**: {format(self.ship.price_credit, ',')}")

        if self.ship.has_demo_profile:
            e.add_field(name='Work in Progress', value="Ship Characteristics are not Final.")

        e.description = '\n'.join(desc)

        if self.ship.next_ships:
            vals = []
            for ship_id, xp in self.ship.next_ships.items():  # ShipID, XP Cost
                nxt = await self.bot.get_ship(int(ship_id))
                cr = format(nxt.price_credit, ',')
                xp = format(xp, ',')
                vals.append((nxt.tier, f"**{nxt.name}** (Tier {nxt.tier} {nxt.type.alias}): {xp} XP, {cr} credits"))

            if vals:
                vals = [i[1] for i in sorted(vals, key=lambda x: x[0])]
                e.add_field(name=f"Next Researchable Ships", value="\n".join(vals))

        self.disabled = self.overview
        return await self.update(embed=e)

    async def update(self, embed: Embed) -> Message:
        """Push the latest version of the Ship view to the user"""
        self.clear_items()

        prev = [i for i in self.bot.ships if str(self.ship.ship_id) in i.next_ships if i.next_ships is not None]
        for ship in prev:
            self.add_item(ShipButton(self.interaction, ship, row=3))

        if self.ship.next_ships:
            nxt = [await self.bot.get_ship(int(ship)) for ship in self.ship.next_ships]
            for ship in sorted(nxt, key=lambda x: x.tier):
                self.add_item(ShipButton(self.interaction, ship, higher=True, row=3))

        # FuncButton - Overview, Armaments, Leaderboard.
        self.add_item(FuncButton(func=self.overview, label="Overview",
                                 disabled=self.disabled == self.overview, emoji=Hull.emoji))

        if Artillery in self.fitting.modules:
            self.add_item(FuncButton(func=self.main_guns, label="Main Battery",
                                     disabled=self.disabled == self.main_guns, emoji=Artillery.emoji))

        if Torpedoes in self.fitting.modules:
            self.add_item(FuncButton(func=self.torpedoes, label="Torpedoes",
                                     disabled=self.disabled == self.torpedoes, emoji=Torpedoes.emoji))

        try:
            emoji = next(i for i in [TorpedoBomber, DiveBomber, RocketPlane] if i in self.fitting.modules).emoji
            self.add_item(FuncButton(func=self.aircraft, label="Aircraft", disabled=self.disabled == self.aircraft,
                                     emoji=emoji))
        except StopIteration:
            pass

        # Secondaries & AA
        self.add_item(FuncButton(func=self.auxiliary, label="Auxiliary",
                                 disabled=self.disabled == self.auxiliary, emoji=None))

        if not self.ship.modules:
            await self.ship.fetch_modules()

        # Dropdown - setattr
        excluded = self.ship.modules.keys() - self.fitting.modules.values()
        if excluded:
            available_modules = [self.ship.modules[module_id].select_option for module_id in excluded]
            self.add_item(ModuleSelect(options=available_modules))

        return await self.bot.reply(self.interaction, embed=embed, view=self)


class ModuleSelect(Select):
    """A Dropdown to change equipped ship modules"""

    def __init__(self, options: List[SelectOption], row: int = 0):
        super().__init__(options=options, placeholder="Change Equipped Modules", row=row, max_values=len(options))

    async def callback(self, interaction: Interaction) -> None:
        """Mount each selected module into the fitting."""
        await interaction.response.defer()
        v: ShipView = self.view
        for value in self.values:
            module = v.ship.modules[int(value)]
            v.fitting.modules[type(module)] = int(value)

        # Update Params.
        await v.fitting.get_params()

        # Repush last function.
        return await v.disabled()


class Module:
    """A Module that can be mounted on a ship"""
    emoji = None

    def __init__(self, name: str, image: str, tag: str, module_id: int, module_id_str: str, price_credit: int) -> None:
        self.image: Optional[str] = image
        self.name: Optional[str] = name
        self.module_id: Optional[int] = module_id
        self.module_id_str: Optional[str] = module_id_str
        self.price_credit: Optional[int] = price_credit
        self.tag: Optional[str] = tag

        # Extra
        self.is_default: bool = None
        self.price_xp: Optional[int] = None

    @property
    def select_option(self) -> SelectOption:
        """Get a Dropdown Select Option for this Module"""
        name = f"{self.name} ({self.__class__.__name__})"

        if self.is_default:
            d = "Stock Module"
        else:
            d = []
            if self.price_credit != 0:
                d.append(f"{format(self.price_credit, ',')} credits")
            if self.price_xp != 0:
                d.append(f"{format(self.price_xp, ',')} xp")

            d = ', '.join(d) if d else "No Cost"
        return SelectOption(label=name, value=self.module_id, emoji=self.emoji, description=d)


class Artillery(Module):
    """An 'Artillery' Module"""
    emoji = "<:Artillery:991026648935718952>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.gun_rate: float = kwargs.pop('gun_rate', 0)  # Fire Rate
        self.max_damage_AP: int = kwargs.pop('max_damage_AP', 0)  # Maximum Armour Piercing Damage
        self.max_damage_HE: int = kwargs.pop('max_damage_HE', 0)  # Maximum High Explosive Damage
        self.rotation_time: float = kwargs.pop('rotation_time', 0)  # Turret Traverse Time in seconds

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for Artillery", k, v)


class DiveBomber(Module):
    """A 'Dive Bomber' Module"""
    emoji = "<:DiveBomber:991027856496791682>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.bomb_burn_probability: float = kwargs.pop('bomb_burn_probability', 0.0)  # FIre Chance, e.g. 52.0
        self.accuracy: Dict[str, float] = kwargs.pop('accuracy', {'min': 0.0, 'max': 0.0})  # Accuracy, float.
        self.max_damage: int = kwargs.pop('max_damage', 0)  # Max Bomb Damage
        self.max_health: int = kwargs.pop('max_health', 0)  # Max Plane HP
        self.cruise_speed: int = kwargs.pop('cruise_speed', 0)  # Max Plane Speed in knots

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for DiveBomber", k, v)


class Engine(Module):
    """An 'Engine' Module"""
    emoji = "<:Engine:991025095772373032>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.max_speed: float = kwargs.pop('max_speed', 0)  # Maximum Speed in kts

        for k, v in kwargs.items():
            print('Unhandled extra attribute For Engine', k, v)
            setattr(self, k, v)


class RocketPlane(Module):
    """A 'Fighter' Module"""
    emoji = "<:RocketPlane:991027006554656898>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.cruise_speed: int = kwargs.pop('cruise_speed', 0)  # Speed in kts
        self.max_health: int = kwargs.pop('max_health', 0)  # HP e.g. 1440

        # Garbage
        self.avg_damage: int = kwargs.pop('avg_damage', 0)
        self.max_ammo: int = kwargs.pop('max_ammo', 0)

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for RocketPlane", k, v)


class FireControl(Module):
    """A 'Fire Control' Module"""
    emoji = "<:FireControl:991026256722161714>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.distance: int = kwargs.pop('distance', 0)
        self.distance_increase: int = kwargs.pop('distance_increase', 0)

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for FireControl", k, v)


# class FlightControl(Module):
#     """A 'Flight Control' Module"""
#     emoji = None  # Flight Control Module Emoji?
#
#     def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
#         super().__init__(name, image, tag, module_id, module_id_str, price_credit)
#
#         for k, v in kwargs.items():
#             setattr(self, k, v)
#             print("Unhandled leftover data for FlightControl", k, v)


class Hull(Module):
    """A 'Hull' Module"""
    emoji = "<:Hull:991022247546347581>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.health: int = kwargs.pop('health', 0)
        self.anti_aircraft_barrels: int = kwargs.pop('anti_aircraft_barrels', 0)
        self.range: Dict[str, int] = kwargs.pop('range')  # This info is complete Garbage. Min - Max Armour.

        self.artillery_barrels: int = kwargs.pop('artillery_barrels', 0)  # Number of Main Battery Slots
        self.atba_barrels: int = kwargs.pop('atba_barrels', 0)  # Number of secondary battery mounts.
        self.torpedoes_barrels: int = kwargs.pop('torpedoes_barrels', 0)  # Number of torpedo launchers.
        self.hangar_size: int = kwargs.pop('planes_amount', 0)  # Not returned by API.

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for Hull", k, v)


class Torpedoes(Module):
    """A 'Torpedoes' Module"""
    emoji = '<:Torpedoes:990731144565764107>'

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.distance: Optional[int] = kwargs.pop('distance', 0)  # Maximum Range of torpedo
        self.max_damage: Optional[int] = kwargs.pop('max_damage', 0)  # Maximum damage of a torpedo
        self.shot_speed: Optional[float] = kwargs.pop('shot_speed', 0)  # Reload Speed of the torpedo
        self.torpedo_speed: Optional[int] = kwargs.pop('torpedo_speed', 0)  # Maximum speed of the torpedo (knots)

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for Torpedoes", k, v)


class TorpedoBomber(Module):
    """A 'Torpedo Bomber' Module"""
    emoji = "<:TorpedoBomber:991028330251829338>"

    def __init__(self, name, image, tag, module_id, module_id_str, price_credit, **kwargs) -> None:
        super().__init__(name, image, tag, module_id, module_id_str, price_credit)

        self.cruise_speed: int = kwargs.pop('cruise_speed', 0)  # Cruise Speed in knots, e.g. 120
        self.torpedo_damage: int = kwargs.pop('torpedo_damage', 0)  # Max Damage, e.g.  6466
        self.max_damage: int = kwargs.pop('max_damage', 0)  # Exactly the same as torpedo_damage.
        self.max_health: int = kwargs.pop('max_health', 0)  # Plane HP, e.g. 1800
        self.torpedo_max_speed: int = kwargs.pop('torpedo_max_speed', 0)  # Torpedo Speed in knots, e.g. 35

        # Garbage
        self.distance: float = kwargs.pop('distance', 0.0)  # "Firing Range" ?
        self.torpedo_name: str = kwargs.pop('torpedo_name', None)  # IDS_PAPT108_LEXINGTON_STOCK

        for k, v in kwargs.items():
            setattr(self, k, v)
            print("Unhandled leftover data for TorpedoBomber", k, v)
