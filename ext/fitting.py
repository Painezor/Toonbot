from collections import defaultdict
import discord
from discord.ext import commands

import typing
import logging

if typing.TYPE_CHECKING:
    from painezBot import PBot

from ext.utils import view_utils
from ext.painezbot_utils import ship as _ship
from ext.painezbot_utils import modules

logger = logging.getLogger("fitting")


class ShipView(view_utils.BaseView):
    """A view representing a ship"""

    bot: PBot
    interaction: discord.Interaction[PBot]

    def __init__(
        self,
        interaction: discord.Interaction[PBot],
        ship: _ship.Ship,
        **kwargs,
    ) -> None:
        super().__init__(interaction, **kwargs)
        self.ship: _ship.Ship = ship
        self.modules: dict[
            typing.Type[modules.Module], int
        ] = self.default_fit()
        self.data: dict = {}
        self.default_fit
        self.available_modules: dict[int, modules.Module] = {}

    async def fetch_modules(self) -> dict[int, modules.Module]:
        """Grab all data related to the ship from the API"""
        # Get needed module IDs
        m = [s.module_id for s in self.bot.modules]

        avail = self.ship.available_modules
        existing = [x for x in avail.values() if x.module_id in m]
        avail.update({k.module_id: k for k in existing})

        m = self.bot.modules

        if targets := [str(i) for i in avail if i not in m]:
            # We want the module IDs as str for the purposes of params
            p = {
                "application_id": self.bot.wg_id,
                "module_id": ",".join(targets),
            }
            url = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"
            async with self.bot.session.get(url, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        s = resp.status
                        n = self.ship.name
                        err = f"{s} error fetching modules for {n} on {url}"
                        raise ConnectionError(err)

            for module_id, data in data["data"].items():
                args = {
                    k: data.pop(k)
                    for k in [
                        "name",
                        "image",
                        "tag",
                        "module_id_str",
                        "module_id",
                        "price_credit",
                    ]
                }

                module_type = data.pop("type")
                kwargs = data.pop("profile").popitem()[1]
                args.update(kwargs)

                item: modules.Module
                if module_type == "Artillery":
                    item = modules.Artillery(**args)
                elif module_type == "DiveBomber":
                    item = modules.DiveBomber(**args)
                elif module_type == "Engine":
                    item = modules.Engine(**args)
                elif module_type == "Fighter":
                    item = modules.RocketPlane(**args)
                elif module_type == "Suo":
                    item = modules.FireControl(**args)
                elif module_type == "Hull":
                    item = modules.Hull(**args)
                elif module_type == "TorpedoBomber":
                    item = modules.TorpedoBomber(**args)
                elif module_type == "Torpedoes":
                    item = modules.Torpedoes(**args)
                else:
                    logger.error(f"Unhandled Module type {module_type}")
                    item = modules.Module(**args)

                self.bot.modules.append(item)
                self.ship.available_modules.update({int(module_id): item})

        for k, v in self.ship.modules_tree.items():
            module = self.ship.available_modules.get(int(k))
            for sub_key, sub_value in v.items():
                setattr(module, sub_key, sub_value)
        return self.ship.available_modules

    def default_fit(self):
        """Generate a fitting from the default modules of this ship."""
        tree = self.ship.modules_tree

        dic = {int(k): v["type"] for k, v in tree.items() if v["is_default"]}

        for module_id, module_type in dic.items():
            match module_type:
                case "Artillery":
                    self.modules[modules.Artillery] = module_id
                case "DiveBomber":
                    self.modules[modules.DiveBomber] = module_id
                case "Engine":
                    self.modules[modules.Engine] = module_id
                case "Hull":
                    self.modules[modules.Hull] = module_id
                case "Fighter":
                    self.modules[modules.RocketPlane] = module_id
                case "Suo":
                    self.modules[modules.FireControl] = module_id
                case "Torpedoes":
                    self.modules[modules.Torpedoes] = module_id
                case "TorpedoBomber":
                    self.modules[modules.TorpedoBomber] = module_id
                case _:
                    m = module_type
                    i = module_id
                    err = f'Unhandled Module type "{m}" default fit, id: {i}'
                    logger.error(err)
        return self.modules

    async def get_params(self) -> dict:
        """Get the ship's specs with the currently selected modules."""
        p = {"application_id": self.bot.wg_id, "ship_id": self.ship.ship_id}

        tuples = [
            ("artillery_id", modules.Artillery),
            ("dive_bomber_id", modules.DiveBomber),
            ("engine_id", modules.Engine),
            ("fire_control_id", modules.FireControl),
            ("hull_id", modules.Hull),
            ("fighter_id", modules.RocketPlane),
            ("torpedoes_id", modules.Torpedoes),
            ("torpedo_bomber_id", modules.TorpedoBomber),
        ]
        # ('flight_control_id', FlightControl),
        p.update(
            {
                k: self.modules.get(v)
                for k, v in tuples
                if self.modules.get(v, None) is not None
            }
        )

        url = "https://api.worldofwarships.eu/wows/encyclopedia/shipprofile/"
        async with self.bot.session.get(url, params=p) as resp:
            if resp.status != 200:
                err = f"HTTP ERROR {resp.status} accessing {url}"
                raise ConnectionError(err)
            json = await resp.json()

        self.data = json["data"][str(self.ship.ship_id)]
        return self.data

    async def aircraft(self) -> discord.InteractionMessage:
        """Get information about the ship's Aircraft"""
        if not self.data:
            await self.get_params()

        e = self.ship.base_embed()

        # Rocket Planes are referred to as 'Fighters'
        if (rp := self.data["fighters"]) is not None:
            name = f"{rp['name']} (Tier {rp['plane_level']}, Rocket Planes)"
            value = [
                f"**Hit Points**: {format(rp['max_health'], ',')}",
                f"**Cruising Speed**: {rp['cruise_speed']} kts",
                "\n*Rocket Plane Damage not available in the API, sorry*",
            ]
            e.add_field(name=name, value="\n".join(value), inline=False)

        if (tb := self.data["torpedo_bomber"]) is not None:
            name = f"{tb['name']} (Tier {tb['plane_level']}, Torpedo Bombers"

            if tb["torpedo_name"] is None:
                t_name = "Unnamed Torpedo"
            else:
                t_name = tb["torpedo_name"]

            value = [
                f"**Hit Points**: {format(tb['max_health'], ',')}",
                f"**Cruising Speed**: {tb['cruise_speed']} kts",
                "",
                f"**Torpedo**: {t_name}",
                f"**Max Damage**: {format(tb['max_damage'])}",
                f"**Max Speed**: {tb['torpedo_max_speed']} kts",
            ]
            e.add_field(name=name, value="\n".join(value), inline=False)

        if (db := self.data["dive_bomber"]) is not None:
            name = f"{db['name']} (Tier {db['plane_level']}, Dive Bombers"

            if db["bomb_name"] is None:
                bomb_name = "Bomb Stats"
            else:
                bomb_name = db["bomb_name"]

            value = [
                f"**Hit Points**: {format(db['max_health'], ',')}",
                f"**Cruising Speed**: {db['cruise_speed']} kts",
                "",
                f"**{bomb_name}**",
                f"**Damage**: {format(db['max_damage'], ',')}",
                f"**Mass**: {db['bomb_bullet_mass']}kg",
                f"**Accuracy**: {db['accuracy']['min']}"
                f"- {db['accuracy']['max']}",
            ]

            if (fire_chance := db["bomb_burn_probability"]) is not None:
                value.append(f"**Fire Chance**: {round(fire_chance, 1)}%")
            e.add_field(name=name, value="\n".join(value), inline=False)

        self.disabled = self.aircraft
        e.set_footer(
            text="Rocket plane armaments, and Skip Bombers as a"
            "whole are currently not listed in the API."
        )
        return await self.update(embed=e)

    async def auxiliary(self) -> discord.InteractionMessage:
        """Get information on the ship's secondaries and anti-air."""
        if not self.data:
            await self.get_params()

        e = self.ship.base_embed()

        desc = []

        if (sec := self.data["atbas"]) is None:
            e.add_field(
                name="No Secondary Armament",
                value="```diff\n- This ship has no secondary armament.```",
            )
        elif "slots" not in sec:
            e.add_field(
                name="API Error",
                value="```diff\n" "- Secondary armament not found in API.```",
            )
        else:
            desc.append(f'**Secondary Range**: {sec["distance"]}')
            desc.append(
                "**Total Barrels**: " f'{self.data["hull"]["atba_barrels"]}'
            )

            for v in sec["slots"].values():
                name = v["name"]
                dmg = v["damage"]

                value = [
                    f"**Damage**: {format(dmg, ',')}",
                    f"**Shell Type**: {v['type']}",
                    f"**Reload Time**: {v['shot_delay']}s ("
                    f"{round(v['gun_rate'], 1)} rounds/minute)",
                    f"**Initial Velocity**: {v['bullet_speed']}m/s",
                    f"**Shell Weight**: {v['bullet_mass']}kg",
                ]

                if fire_chance := v["burn_probability"]:
                    value.append(f"**Fire Chance**: {round(fire_chance, 1)}")

                e.add_field(name=name, value="\n".join(value))

        if (aa := self.data["anti_aircraft"]) is None:
            aa_desc = [
                "```diff\n- This ship does not have any AA Capabilities.```"
            ]
        else:
            aa_guns: dict[str, list] = defaultdict(list)
            for v in aa["slots"].values():
                value = (
                    f'{v["guns"]}x{v["caliber"]}mm ({v["avg_damage"]} dps)\n'
                )
                aa_guns[v["name"]].append(value)

            aa_desc = []
            for k, v in aa_guns.items():
                aa_desc.append(f"**{k}**\n")
                aa_desc.append("\n".join(v))
                aa_desc.append("\n")

        e.add_field(name="AA Guns", value="".join(aa_desc), inline=False)

        e.description = "\n".join(desc)
        self.disabled = self.auxiliary
        return await self.update(embed=e)

    async def main_guns(self) -> discord.InteractionMessage:
        """Get information about the ship's main battery"""
        if not self.data:
            await self.get_params()

        e = self.ship.base_embed()

        # Guns
        mb = self.data["artillery"]
        guns = []
        caliber = ""
        for gun_type in mb["slots"].values():
            e.title = gun_type["name"]
            guns.append(f"{gun_type['guns']}x{gun_type['barrels']}")
            caliber = f"{str(e.title).split('mm')[0]}"

        reload_time: float = mb["shot_delay"]

        rlt = round(reload_time, 1)
        e.description = (
            f"**Guns**: {','.join(guns)} {caliber}mm\n"
            f"**Max Dispersion**: {mb['max_dispersion']}m\n"
            f"**Range**: {mb['distance']}km\n"
            f"**Reload Time**: {rlt}s ({mb['gun_rate']} rounds/minute)"
        )

        for shell_type in mb["shells"].values():
            vel = format(shell_type["bullet_speed"], ",")
            weight = format(shell_type["bullet_mass"], ",")
            shell_data = [
                f"**Damage**: {format(shell_type['damage'], ',')}",
                f"**Initial Velocity**: {vel}m/s",
                f"**Shell Weight**: {weight}kg",
            ]

            if (fire_chance := shell_type["burn_probability"]) is not None:
                shell_data.append(f"**Fire Chance**: {fire_chance}%")

            e.add_field(
                name=f"{shell_type['type']}: {shell_type['name']}",
                value="\n".join(shell_data),
            )
        self.disabled = self.main_guns

        e.set_footer(text="SAP Shells are currently not in the API, sorry.")
        return await self.update(embed=e)

    async def torpedoes(self) -> discord.InteractionMessage:
        """Get information about the ship's torpedoes"""
        if not self.data:
            await self.get_params()

        e = self.ship.base_embed()

        trp = self.data["torpedoes"]
        for tube in trp["slots"]:
            barrels = trp["slots"][tube]["barrels"]
            calibre = trp["slots"][tube]["caliber"]
            num_tubes = trp["slots"][tube]["guns"]
            e.add_field(
                name=trp["slots"][tube]["name"],
                value=f"{num_tubes}x{barrels}x{calibre}mm",
            )

        e.title = trp["torpedo_name"]

        reload_time: float = trp["reload_time"]

        trp_desc = [
            f"**Range**: {trp['distance']}km",
            f"**Speed**: {trp['torpedo_speed']}kts",
            f"**Damage**: {format(trp['max_damage'], ',')}",
            f"**Detectability**: {trp['visibility_dist']}km",
            f"**Reload Time**: {round(reload_time, 2)}s",
            f"**Launchers**: {self.data['hull']['torpedoes_barrels']}",
            f"**Launcher 180° Time**: {trp['rotation_time']}s",
        ]

        e.description = "\n".join(trp_desc)
        self.disabled = self.torpedoes
        return await self.update(embed=e)

    async def overview(self) -> discord.InteractionMessage:
        """Get a general overview of the ship"""
        if not self.data:
            await self.get_params()

        params = self.data

        e = self.ship.base_embed()
        tier = self.ship.tier
        slots = self.ship.mod_slots

        # Check for bonus Slots (Arkansas Beta, Z-35, …)
        if tier:
            if tier < 3:
                slts = 1
            elif tier < 5:
                slts = 2
            elif tier == 5:
                slts = 3
            elif tier < 7:
                slts = 4
            elif tier == 8:
                slts = 5
            else:
                slts = 6
            if slots != slts:
                text = f"This ship has {slots} upgrades instead of {slts}"
                e.add_field(name="Bonus Upgrade Slots", value=text)

        if self.ship.images:
            e.set_image(url=self.ship.images["large"])

        e.set_footer(text=self.ship.description)

        # Parse Modules for ship data
        rst = params["mobility"]["rudder_time"]
        detect = params["concealment"]["detect_distance_by_ship"]
        air_detect = params["concealment"]["detect_distance_by_plane"]
        desc = [
            f"**Hit Points**: {format(params['hull']['health'], ',')}",
            f"**Concealment**: {detect}km ({air_detect}km by air)",
            f"**Maximum Speed**: {params['mobility']['max_speed']}kts",
            f"**Rudder Shift Time**: {rst} seconds",
            f"**Turning Radius**: {params['mobility']['turning_radius']}m",
        ]

        # f"-{params['armour']['flood_prob']}% flood chance."
        #  This field appears to be Garbage.
        if params["armour"]["flood_prob"] != 0:
            desc.append(
                f"**Torpedo Belt**: -{params['armour']['flood_prob']}% damage"
            )

        # Build Rest of embed description
        if self.ship.price_gold != 0:
            cost = format(self.ship.price_gold, ",")
            desc.append(f"**Doubloon Price**: {cost}")

        if self.ship.price_credit != 0:
            cost = format(self.ship.price_credit, ",")
            desc.append(f"**Credit Price**: {cost}")

        if self.ship.has_demo_profile:
            e.add_field(
                name="Work in Progress",
                value="Ship Characteristics are not Final.",
            )

        e.description = "\n".join(desc)

        if self.ship.next_ships:
            vals: list[tuple] = []
            for ship_id, xp in self.ship.next_ships.items():  # ShipID, XP Cost
                nxt = self.bot.get_ship(int(ship_id))
                cr = format(nxt.price_credit, ",")
                xp = format(xp, ",")
                t = (
                    f"**{nxt.name}** (Tier {nxt.tier} {nxt.type.alias}):"
                    f"{xp} XP, {cr} credits"
                )
                vals.append((nxt.tier, t))

            if vals:
                keys = [i[1] for i in sorted(vals, key=lambda x: x[0])]
                e.add_field(
                    name="Next Researchable Ships", value="\n".join(keys)
                )

        self.disabled = self.overview
        return await self.update(embed=e)

    async def handle_buttons(self, current_function: typing.Callable) -> None:
        """Handle the Funcables"""
        self.clear_items()

        row = 1
        buttons = []
        ships = self.interaction.client.ships

        my_id = str(self.ship.ship_id)
        if prev := [i for i in ships if my_id in i.next_ships]:
            for ship in prev:
                fn = ShipView(self.interaction, ship).overview
                btn = view_utils.Funcable(f"Tier {ship.tier}: {ship.name}", fn)
                btn.emoji = "▶"
                buttons.append(btn)

        if self.ship.next_ships:
            for ship in self.ship.next_ships:
                fn = ShipView(self.interaction, ship).overview
                btn = view_utils.Funcable(f"Tier {ship.tier}: {ship.name}", fn)
                btn.emoji = "◀"
                buttons.append(btn)

        if buttons:
            self.add_function_row(buttons, row, "View Next/previous Ship")
            row += 1

        buttons.clear()
        # Module Stats
        # FuncButton - Overview, Armaments, Leaderboard.

        btn = view_utils.Funcable("Overview", self.overview)
        btn.disabled = current_function == self.overview
        btn.emoji = modules.Hull.emoji
        buttons.append(btn)

        if modules.Artillery in self.modules:
            btn = view_utils.Funcable("Main Battery", self.main_guns)
            btn.disabled = current_function == self.main_guns
            btn.emoji = modules.Artillery.emoji
            buttons.append(btn)

        if modules.Torpedoes in self.modules:
            btn = view_utils.Funcable("Torpedoes", self.torpedoes)
            btn.disabled = current_function == self.torpedoes
            btn.emoji = modules.Torpedoes.emoji
            buttons.append(btn)

        pln = [modules.TorpedoBomber, modules.DiveBomber, modules.RocketPlane]
        if any(x in self.modules for x in pln):
            btn = view_utils.Funcable("Aircraft", self.aircraft)
            btn.disabled = current_function == self.aircraft
            btn.emoji = next(i for i in pln if i in self.modules).emoji
            buttons.append(btn)

        # Secondaries & AA
        btn = view_utils.Funcable("Auxiliary", self.auxiliary)
        btn.disabled = current_function == self.auxiliary
        btn.emoji = modules.Module.emoji
        buttons.append(btn)

        self.add_function_row(buttons, row)

        if not self.modules:
            await self.fetch_modules()

        # Dropdown - setattr
        opts = []
        excluded = self.ship.available_modules.keys() - self.modules.values()
        for module_id in excluded:
            module = self.ship.available_modules[module_id]

            name = f"{module.name} ({module.__class__.__name__})"
            opt = discord.SelectOption(label=name, emoji=module.emoji)
            opt.value = str(module.module_id)

            if not module.is_default:
                opt.description = "Stock Module"
            else:
                d = []
                if module.price_credit != 0:
                    d.append(f"{format(module.price_credit, ',')} credits")
                if module.price_xp != 0:
                    d.append(f"{format(module.price_xp, ',')} xp")
                opt.description = ", ".join(d) if d else "No Cost"
            opts.append(opt)
        self.add_item(ModuleSelect(opts, 0, current_function))

    async def update(self, embed: discord.Embed) -> discord.InteractionMessage:
        """Push the latest version of the Ship view to the user"""
        return await self.bot.reply(self.interaction, embed=embed, view=self)


class ModuleSelect(discord.ui.Select):
    """A Dropdown to change equipped ship modules"""

    view: ShipView

    def __init__(
        self,
        options: list[discord.SelectOption],
        row: int,
        current_function: typing.Callable,
    ):
        super().__init__(
            options=options,
            placeholder="Change Equipped Modules",
            row=row,
            max_values=len(options),
        )
        self.current_function = current_function

    async def callback(self, interaction: discord.Interaction[PBot]) -> None:
        """Mount each selected module into the fitting."""

        await interaction.response.defer()
        for value in self.values:
            module = self.view.ship.available_modules[int(value)]
            self.view.modules[type(module)] = int(value)

        # Update Params.
        await self.view.get_params()

        # Invoke last function again.
        return await self.current_function()


async def ship_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for the list of maps in World of Warships"""

    current = current.casefold()
    choices = []
    for i in sorted(interaction.client.ships, key=lambda s: s.name):
        if not i.ship_id_str:
            continue
        if current not in i.ac_row:
            continue

        value = i.ship_id_str
        choice = discord.app_commands.Choice(name=i.ac_row[:100], value=value)
        choices.append(choice)

        if len(choices) == 25:
            break

    return choices


class Fittings(commands.Cog):
    """View Ship Fittiings in various states"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
    @discord.app_commands.autocomplete(name=ship_ac)
    @discord.app_commands.describe(name="Search for a ship by it's name")
    async def ship(
        self, interaction: discord.Interaction[PBot], name: str
    ) -> discord.InteractionMessage:
        """Search for a ship in the World of Warships API"""

        await interaction.response.defer()

        if not self.bot.ships:
            raise ConnectionError("Unable to fetch ships from API")

        if (ship := self.bot.get_ship(name)) is None:
            raise LookupError(f"Did not find map matching {name}, sorry.")

        return await ShipView(interaction, ship).overview()


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Fittings(bot))
