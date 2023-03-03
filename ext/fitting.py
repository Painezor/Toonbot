import discord
from discord.ext import commands

import typing

if typing.TYPE_CHECKING:
    from painezBot import PBot

from ext.utils import view_utils
from ext.painezbot_utils.ship import Ship


class ShipButton(discord.ui.Button):
    """Change to a view of a different ship"""

    def __init__(
        self,
        interaction: discord.Interaction[PBot],
        ship: Ship,
        row: int = 0,
        higher: bool = False,
    ) -> None:
        self.ship: Ship = ship
        self.interaction: discord.Interaction[PBot] = interaction

        emoji = "▶" if higher else "◀"

        super().__init__(
            label=f"Tier {ship.tier}: {ship.name}", row=row, emoji=emoji
        )

    async def callback(
        self, interaction: discord.Interaction
    ) -> discord.InteractionMessage:
        """Change message of interaction to a different ship"""
        await interaction.response.defer()
        return await ShipView(self.interaction, self.ship).overview()


class ShipView(view_utils.BaseView):
    """A view representing a ship"""

    bot: PBot
    interaction: discord.Interaction[PBot]

    def __init__(
        self, interaction: discord.Interaction[PBot], ship: Ship
    ) -> None:
        super().__init__(interaction)
        self.ship: Ship = ship

        self.fitting: Fitting = ship.default_fit

    async def aircraft(self) -> discord.InteractionMessage:
        """Get information about the ship's Aircraft"""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.ship.base_embed()

        # Rocket Planes are referred to as 'Fighters'
        if (rp := self.fitting.data["fighters"]) is not None:
            name = f"{rp['name']} (Tier {rp['plane_level']}, Rocket Planes)"
            value = [
                f"**Hit Points**: {format(rp['max_health'], ',')}",
                f"**Cruising Speed**: {rp['cruise_speed']} kts",
                "\n*Rocket Plane Damage not available in the API, sorry*",
            ]
            e.add_field(name=name, value="\n".join(value), inline=False)

        if (tb := self.fitting.data["torpedo_bomber"]) is not None:
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

        if (db := self.fitting.data["dive_bomber"]) is not None:
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

    async def auxiliary(self) -> Message:
        """Get information on the ship's secondaries and anti-air."""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed()

        desc = []

        if (sec := self.fitting.data["atbas"]) is None:
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
                "**Total Barrels**: "
                f'{self.fitting.data["hull"]["atba_barrels"]}'
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

        if (aa := self.fitting.data["anti_aircraft"]) is None:
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

    async def main_guns(self) -> Message:
        """Get information about the ship's main battery"""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed()

        # Guns
        mb = self.fitting.data["artillery"]
        guns = []
        caliber = ""
        for gun_type in mb["slots"].values():
            e.title = gun_type["name"]
            guns.append(f"{gun_type['guns']}x{gun_type['barrels']}")
            caliber = f"{e.title.split('mm')[0]}"

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

    async def torpedoes(self) -> Message:
        """Get information about the ship's torpedoes"""
        if not self.fitting.data:
            await self.fitting.get_params()

        e = self.base_embed()

        trp = self.fitting.data["torpedoes"]
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

        e = self.base_embed()
        tier = self.ship.tier
        slots = self.ship.mod_slots

        # Check for bonus Slots (Arkansas Beta, Z-35, …)
        slt = {
            1: 1,
            2: 1,
            3: 2,
            4: 2,
            5: 3,
            6: 4,
            7: 4,
            8: 5,
            9: 6,
            10: 6,
            11: 6,
            "": "",
        }.pop(self.ship.tier)
        if slots != slt:
            e.add_field(
                name="Bonus Upgrade Slots",
                value=f"This ship has {slots} upgrades instead of {slt[tier]}",
            )

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
            vals = []
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
                vals = [i[1] for i in sorted(vals, key=lambda x: x[0])]
                e.add_field(
                    name="Next Researchable Ships", value="\n".join(vals)
                )

        self.disabled = self.overview
        return await self.update(embed=e)

    async def update(self, embed: discord.Embed) -> discord.InteractionMessage:
        """Push the latest version of the Ship view to the user"""
        self.clear_items()

        prev = [
            i
            for i in self.interaction.client.ships
            if str(self.ship.ship_id) in i.next_ships
            and i.next_ships is not None
        ]
        for ship in prev:
            self.add_item(ShipButton(self.interaction, ship, row=3))

        if self.ship.next_ships:
            nxt = map(
                lambda x: self.bot.get_ship(int(x)), self.ship.next_ships
            )
            for ship in sorted(nxt, key=lambda x: x.tier):
                self.add_item(
                    ShipButton(self.interaction, ship, higher=True, row=3)
                )

        # FuncButton - Overview, Armaments, Leaderboard.
        self.add_item(
            FuncButton(
                function=self.overview,
                label="Overview",
                disabled=self.disabled == self.overview,
                emoji=Hull.emoji,
            )
        )

        if Artillery in self.fitting.modules:
            self.add_item(
                FuncButton(
                    function=self.main_guns,
                    label="Main Battery",
                    disabled=self.disabled == self.main_guns,
                    emoji=Artillery.emoji,
                )
            )

        if Torpedoes in self.fitting.modules:
            self.add_item(
                FuncButton(
                    function=self.torpedoes,
                    label="Torpedoes",
                    disabled=self.disabled == self.torpedoes,
                    emoji=Torpedoes.emoji,
                )
            )

        try:
            emoji = next(
                i
                for i in [TorpedoBomber, DiveBomber, RocketPlane]
                if i in self.fitting.modules
            ).emoji
            self.add_item(
                FuncButton(
                    function=self.aircraft,
                    label="Aircraft",
                    disabled=self.disabled == self.aircraft,
                    emoji=emoji,
                )
            )
        except StopIteration:
            pass

        # Secondaries & AA
        self.add_item(
            FuncButton(
                function=self.auxiliary,
                label="Auxiliary",
                disabled=self.disabled == self.auxiliary,
                emoji=Module.emoji,
            )
        )

        if not self.ship.modules:
            await self.ship.fetch_modules()

        # Dropdown - setattr
        if (
            excluded := self.ship.modules.keys()
            - self.fitting.modules.values()
        ):
            available_modules = [
                self.ship.modules[module_id].select_option
                for module_id in excluded
            ]
            self.add_item(ModuleSelect(options=available_modules))

        return await self.bot.reply(self.interaction, embed=embed, view=self)


class ModuleSelect(discord.ui.Select):
    """A Dropdown to change equipped ship modules"""

    def __init__(self, options: list[discord.ui.SelectOption], row: int = 0):
        super().__init__(
            options=options,
            placeholder="Change Equipped Modules",
            row=row,
            max_values=len(options),
        )

    async def callback(self, interaction: Interaction) -> None:
        """Mount each selected module into the fitting."""

        await interaction.response.defer()
        v: ShipView = self.view
        for value in self.values:
            module = v.ship.modules[int(value)]
            v.fitting.modules[type(module)] = int(value)

        # Update Params.
        await v.fitting.get_params()

        # Invoke last function again.
        return await v.disabled()


class Fitting(commands.Cog):
    """View Ship Fittiings in various states"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Fitting(bot))
