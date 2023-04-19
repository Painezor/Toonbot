"""Get ship Parameters with various modules equipped"""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any, Optional, TypeAlias

import discord
from discord.ext import commands

import ext.wows_api as api
from ext.utils import view_utils

WIP = (
    "```diff\n- This ship is still in testing and marked as Work in Progress\n"
    "- These values may not be final."
)


if TYPE_CHECKING:
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[PBot]


# TODO: Random Ship Command.
logger = logging.getLogger("fitting")


async def get_modules(interaction: Interaction, ship: api.Ship) -> None:
    """Grab all data related to the ship from the API"""
    # Get needed module IDs
    current_ids = interaction.client.modules.keys()
    ship_module_ids = ship.modules.all
    to_fetch = [i for i in ship_module_ids if i not in current_ids]
    logger.info("Fetching %s", to_fetch)
    interaction.client.modules.update(await api.fetch_modules(to_fetch))
    return


class ShipButton(discord.ui.Button["ShipView"]):
    """A button that changes to a view of a new ship"""

    def __init__(self, parent: ShipView, ship: api.Ship, emoji: str):
        label = f"Tier {ship.tier}: {ship.name}"
        super().__init__(emoji=emoji, label=label, row=4)

        self.parent = parent
        self.ship = ship

    async def callback(self, interaction: Interaction) -> None:  # type: ignore
        """Create the new view, and send it back with the interaction"""
        await get_modules(interaction, self.ship)
        view = ShipView(interaction, self.ship, parent=self.parent)
        embed = OverviewEmbed(view.fitting)
        await interaction.response.edit_message(view=view, embed=embed)


class ShipEmbed(discord.Embed):
    """Generic Embed for a ship, most likely subclassed."""

    def __init__(self, ship: api.Ship):
        super().__init__()

        if any([ship.is_premium, ship.is_special]):
            icon_url = ship.type.image_premium
        else:
            icon_url = ship.type.image
        cls_ = ship.type.name

        nation = ship.nation.sane
        tier = f"Tier {ship.tier}"

        name = [i for i in [tier, nation, cls_, ship.name] if i]

        self.set_author(name=" ".join(name), icon_url=icon_url)

        if ship.images:
            self.set_thumbnail(url=ship.images.contour)


class AircraftEmbed(ShipEmbed):
    """Embed with the stats of each of the aircraft armaments."""

    def __init__(self, fitting: api.ShipFit):
        super().__init__(fitting.ship)

        # Rocket Planes are referred to as 'Fighters'
        if (rkt := fitting.profile.fighters) is not None:
            name = f"{rkt.name} (Tier {rkt.plane_level}, Rocket Planes)"
            value = [
                f"**Hit Points**: {format(rkt.max_health, ',')}",
                f"**Cruising Speed**: {rkt.cruise_speed} kts",
                # TODO: Flesh out rest of rocket plane data
                "\n*Rocket Plane Damage not available in the API, sorry*",
            ]
            self.add_field(name=name, value="\n".join(value), inline=False)

        if (t_b := fitting.profile.torpedo_bomber) is not None:
            name = f"{t_b.name} (Tier {t_b.plane_level}, Torpedo Bombers"

            value = [
                f"**Hit Points**: {format(t_b.max_health, ',')}",
                f"**Cruising Speed**: {t_b.cruise_speed} kts",
                f"**Torpedo**: {t_b.torpedo_name}",
                f"**Max Damage**: {format(t_b.max_damage)}",
                f"**Max Speed**: {t_b.torpedo_max_speed} kts",
            ]
            self.add_field(name=name, value="\n".join(value), inline=False)

        if (d_b := fitting.profile.dive_bomber) is not None:
            name = f"{d_b.name} (Tier {d_b.plane_level}, Dive Bombers"

            value = [
                f"**Hit Points**: {format(d_b.max_health, ',')}",
                f"**Cruising Speed**: {d_b.cruise_speed} kts",
                "",
                f"**{d_b.bomb_name}**",
                f"**Damage**: {format(d_b.max_damage, ',')}",
                f"**Mass**: {d_b.bomb_bullet_mass}kg",
                f"**Accuracy**: {d_b.accuracy.min} - {d_b.accuracy.max}",
            ]

            if fire_chance := d_b.bomb_burn_probability:
                value.append(f"**Fire Chance**: {round(fire_chance, 1)}%")
            self.add_field(name=name, value="\n".join(value), inline=False)

        self.set_footer(text="Rocket planes & Skip Bombs are not in the API.")


class AuxiliaryEmbed(ShipEmbed):
    """Embed for secondaries and anti-air"""

    def __init__(self, fitting: api.ShipFit):
        super().__init__(fitting.ship)

        desc: list[str] = []

        if fitting.profile.atbas is None or not fitting.profile.atbas.slots:
            i = "```diff\n- This ship has no secondary armament.```"
            self.add_field(name="No Secondary Armament", value=i)

        else:
            sec = fitting.profile.atbas
            if not fitting.profile.hull:
                barrel = "?"
            else:
                barrel = fitting.profile.hull.atba_barrels
            desc.append(f"**Secondary Range**: {sec.distance}")
            desc.append(f"**Total Barrels**: {barrel}")

            if sec.slots:
                for i in sec.slots.values():
                    name = i.name

                    text = [
                        f"**Damage**: {format(i.damage, ',')}",
                        f"**Shell Type**: {i.type}",
                        f"**Reload Time**: {i.shot_delay}s ("
                        f"{round(i.gun_rate, 1)} rounds/minute)",
                        f"**Initial Velocity**: {i.bullet_speed}m/s",
                        f"**Shell Weight**: {i.bullet_mass}kg",
                    ]

                    if fires := i.burn_probability:
                        text.append(f"**Fire Chance**: {round(fires, 1)}")

                    self.add_field(name=name, value="\n".join(text))

        if (a_a := fitting.profile.anti_aircraft) is None:
            desc.append("```diff\n- This ship has no AA Capability.```")
        else:
            assert a_a.slots is not None
            rows: list[str] = []
            for i in a_a.slots.values():
                row = f"{i.name}: {i.guns}x{i.caliber}mm"
                if i.avg_damage is not None:
                    row += f" ({format(i.avg_damage, ',')} dps)"

                rows.append(row)

            self.add_field(name="AA Guns", value="\n".join(rows), inline=False)

        self.description = "\n".join(desc)


class MainGunEmbed(ShipEmbed):
    """Shooty shooty bang bangs embed"""

    def __init__(self, fitting: api.ShipFit):
        super().__init__(fitting.ship)

        # Guns
        mains = fitting.profile.artillery

        if not mains:
            self.description = "No main guns found for this ship."
            return

        guns: list[str] = []
        caliber = ""
        if mains.slots:
            for i in mains.slots.values():
                self.title = i.name
                guns.append(f"{i.guns}x{i.barrels}")
                caliber = f"{str(self.title).split('mm', maxsplit=1)[0]}"

        reload_time: float = mains.shot_delay

        rlt = round(reload_time, 1)
        self.description = (
            f"**Guns**: {','.join(guns)} {caliber}mm\n"
            f"**Max Dispersion**: {mains.max_dispersion}m\n"
            f"**Range**: {mains.distance}km\n"
            f"**Reload Time**: {rlt}s ({mains.gun_rate} rounds/minute)"
        )

        for i in mains.shells.values():
            shell_data = [
                f"**Damage**: {format(i.damage, ',')}",
                f"**Initial Velocity**: {format(i.bullet_speed, ',')}m/s",
                f"**Shell Weight**: {format(i.bullet_mass, ',')}kg",
            ]

            if i.burn_probability:
                shell_data.append(f"**Fire Chance**: {i.burn_probability}%")

            name = f"{i.type}: {i.name}"
            self.add_field(name=name, value="\n".join(shell_data))

        self.set_footer(text="SAP Shells are currently not in the API.")


class OverviewEmbed(ShipEmbed):
    """Generic overview for the ship including it's meta progression"""

    def __init__(self, fitting: api.ShipFit):
        super().__init__(fitting.ship)

        ship = fitting.ship
        tier = ship.tier
        slots = ship.mod_slots

        # Check for bonus Slots (Arkansas Beta, Z-35, …)
        if tier:
            if tier < 3:
                slts = 1
            elif tier < 5:
                slts = 2
            elif tier < 6:
                slts = 3
            elif tier < 7:
                slts = 4
            elif tier < 8:
                slts = 5
            else:
                slts = 6

            if slots != slts:
                text = f"This ship has {slots} upgrades instead of {slts}"
                self.add_field(name="Special Upgrade Slots", value=text)

        if ship.images:
            self.set_image(url=fitting.ship.images.large)

        self.set_footer(text=fitting.ship.description)

        # Parse Modules for ship data
        desc: list[str] = []
        if fitting.profile.hull:
            hp = format(fitting.profile.hull.health, ",")
            desc.append(f"**Hit Points**: {hp}")

        if fitting.profile.concealment:
            detect = fitting.profile.concealment.detect_distance_by_ship
            air_detect = fitting.profile.concealment.detect_distance_by_plane
            desc.append(f"**Concealment**: {detect}km ({air_detect}km by air)")

        if fitting.profile.mobility:
            if _ := fitting.profile.mobility.max_speed:
                desc.append(f"**Maximum Speed**: {_}kts")
            if _ := fitting.profile.mobility.rudder_time:
                desc.append(f"**Rudder Shift Time**: {_} seconds")
            if _ := fitting.profile.mobility.turning_radius:
                desc.append(f"**Turning Radius**: {_}m")

        # f"-{params['armour']['flood_prob']}% flood chance."
        #  This field appears to be Garbage.
        if fitting.profile.armour:
            if (belt := fitting.profile.armour.flood_damage) != 0:
                desc.append(f"**Torpedo Belt**: -{belt}% damage")

        # Build Rest of embed description
        if ship.price_gold != 0:
            cost = format(fitting.ship.price_gold, ",")
            desc.append(f"**Doubloon Price**: {cost}")

        elif ship.price_credit != 0:
            cost = format(fitting.ship.price_credit, ",")
            desc.append(f"**Credit Price**: {cost}")

        if ship.has_demo_profile:
            self.add_field(name="WIP", value=WIP)

        self.description = "\n".join(desc)

        if ship.next_ship_objects:
            desc: list[str] = []

            tup = sorted(ship.next_ship_objects, key=lambda x: x[0].tier)
            for nxt, xp_ in tup:
                creds = format(nxt.price_credit, ",")
                xp_ = format(xp_, ",")
                desc.append(f"**{nxt.name}**: {xp_} XP, {creds} credits")

            if desc:
                self.add_field(name="Next Ships", value="\n".join(desc))


class TorpedoesEmbed(ShipEmbed):
    """Embed with details about ship-launched torpedoes"""

    def __init__(self, fitting: api.ShipFit):
        super().__init__(fitting.ship)
        torps = fitting.profile.torpedoes

        if torps is None:
            self.description = "Torpedoes Not Found :concern:"
            return

        if torps.slots:
            tpd: list[str] = []
            for i in torps.slots.values():
                _ = f"**{i.name}**\n{i.guns}x{i.barrels}x{i.caliber}mm"
                tpd.append(_)

            if tpd:
                self.add_field(name="Slots", value="\n\n".join(tpd))

        self.title = torps.torpedo_name

        react = torps.distance * 0.384 / torps.torpedo_speed
        trp_desc = [
            f"**Range**: {torps.distance}km",
            f"**Speed**: {torps.torpedo_speed}kts",
            f"**Reaction Time**: {react}s"
            f"**Damage**: {format(torps.max_damage, ',')}",
            f"**Detectability**: {torps.visibility_dist}km",
            f"**Reload Time**: {round(torps.reload_time, 2)}s",
            f"**Launcher 180° Time**: {torps.rotation_time}s",
        ]
        if hull := fitting.profile.hull:
            trp_desc.append(f"**Launchers**: {hull.torpedoes_barrels}")

        self.description = "\n".join(trp_desc)


# TODO: WowsBuilder Button
class ShipView(view_utils.BaseView):
    """A view representing a ship"""

    def __init__(
        self, interaction: Interaction, ship: api.Ship, **kwargs: Any
    ) -> None:
        super().__init__(interaction.user, **kwargs)

        self.ship: api.Ship = ship

        matches: list[api.Module] = []
        modules = list(ship.modules_tree.values()) if ship.modules_tree else []
        for i in [j for j in modules if j.is_default]:
            try:
                matches.append(interaction.client.modules[str(i.module_id)])
            except KeyError:
                logger.error("ShipView Failed module id %s", i.module_id)

        self.fitting = api.ShipFit(ship, matches)

        if not self.fitting.profile.artillery:
            self.remove_item(self.main_guns)

        if not self.fitting.profile.torpedoes:
            self.remove_item(self.torpedoes)

        if self.fitting.profile.dive_bomber is not None:
            self.aircraft.emoji = api.DIVE_BOMBER_EMOJI
        elif self.fitting.profile.fighters is not None:
            self.aircraft.emoji = api.ROCKET_PLANE_EMOJII
        elif self.fitting.profile.torpedo_bomber is not None:
            self.aircraft.emoji = api.TORPEDO_PLANE_EMOJI
        else:
            self.remove_item(self.aircraft)

        for i in ship.previous_ships:
            self.add_item(ShipButton(self, i, "◀️"))

        for i in ship.next_ship_objects:
            self.add_item(ShipButton(self, i[0], "▶️"))

        self.update_dropdown(interaction)

    def update_dropdown(self, interaction: Interaction) -> None:
        """Refressh the options of the dropdown"""
        options: list[discord.SelectOption] = []
        for i in self.ship.modules.all:
            if i in [i.module_id for i in self.fitting.modules.values()]:
                continue

            try:
                module = interaction.client.modules[str(i)]
            except KeyError:
                logger.info(f"Module {i} not in bot")
                continue

            i = str(i)
            tree = self.ship.modules_tree.items()
            orig = next(val for k, val in tree if k == i)

            name = module.name
            opt = discord.SelectOption(label=name, emoji=module.profile.emoji)
            opt.value = str(module.module_id)

            if orig.is_default:
                opt.description = "Stock Module"
                options.append(opt)
                continue

            desc: list[str] = []
            if orig.price_credit != 0:
                desc.append(f"{format(orig.price_credit, ',')} credits")

            if orig.price_xp != 0:
                desc.append(f"{format(orig.price_xp, ',')} xp")
            opt.description = ", ".join(desc) if desc else "No Cost"
            options.append(opt)

        self.modules.options = options
        self.modules.max_values = len(options)
        id_str = self.ship.ship_id_str
        self.builder.url = f"https://app.wowssb.com/ship?shipIndexes={id_str}"

    @discord.ui.button(emoji=api.HULL_EMOJI)
    async def overview(self, interaction: Interaction, _) -> None:
        """Get a general overview of the ship"""
        embed = OverviewEmbed(self.fitting)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji=api.ARTILLERY_EMOJI)
    async def main_guns(self, interaction: Interaction, _) -> None:
        """Get information about the ship's main battery"""
        embed = MainGunEmbed(self.fitting)
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji=api.TORPEDOES_EMOJI)
    async def torpedoes(self, interaction: Interaction, _) -> None:
        """Get information about the ship's torpedoes"""
        embed = TorpedoesEmbed(self.fitting)
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji=api.AUXILIARY_EMOJI)
    async def auxiliary(self, interaction: Interaction, _) -> None:
        """Get information on the ship's secondaries and anti-air."""
        embed = AuxiliaryEmbed(self.fitting)
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji=api.ROCKET_PLANE_EMOJII)
    async def aircraft(self, interaction: Interaction, _) -> None:
        """Get information about the ship's Aircraft"""
        embed = AircraftEmbed(self.fitting)
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(placeholder="Change modules", row=3)
    async def modules(
        self, itr: Interaction, sel: discord.ui.Select[ShipView]
    ) -> None:
        """Dropdown to change modules."""
        last: str = "Hull"
        for value in sel.values:
            module = itr.client.modules[value]
            self.fitting.set_module(module)
            last = module.type

        await self.fitting.get_params()

        try:
            embed = {
                "Artillery": MainGunEmbed(self.fitting),
                "Hull": OverviewEmbed(self.fitting),
                "Torpedoes": TorpedoesEmbed(self.fitting),
                "cock": AuxiliaryEmbed(self.fitting),
                "fuck": AircraftEmbed(self.fitting),
            }[last]
        except KeyError:
            embed = OverviewEmbed(self.fitting)

        self.update_dropdown(itr)
        await itr.response.edit_message(embed=embed, view=self)

    @discord.ui.button(row=5, style=discord.ButtonStyle.url, label="WoWsSB")
    async def builder(
        self, itr: Interaction, btn: discord.ui.Button[ShipView]
    ) -> None:
        """Open a link to wows ShipBuilder"""
        return


class Fittings(commands.Cog):
    """View Ship Fittiings in various states"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    async def cog_load(self) -> None:
        """Fetch Generics from API and store to bot."""
        self.bot.ships = await api.get_ships()

    @discord.app_commands.command()
    @discord.app_commands.describe(ship="Search for a ship by it's name")
    @discord.app_commands.guilds()
    async def ship(
        self,
        interaction: Interaction,
        ship: api.ship_transform,
    ) -> None:
        """Search for a ship in the World of Warships API"""
        await get_modules(interaction, ship)
        view = ShipView(interaction, ship)
        embed = OverviewEmbed(view.fitting)
        await interaction.response.send_message(view=view, embed=embed)
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.rename(class_="class")
    @discord.app_commands.describe(
        nation="Ship Nation", tier="Ship Tier", _class="Ship Class"
    )
    async def random_ship(
        self,
        interaction: Interaction,
        tier: Optional[discord.app_commands.Range[int, 1, 11]],
        class_: Optional[api.class_transform],
        nation: Optional[api.Nation],
    ) -> None:
        """Get a random ship"""
        ships = interaction.client.ships
        if tier:
            ships = [i for i in ships if i.tier == tier]
        if class_:
            ships = [i for i in ships if i.type == class_]
        if nation:
            ships = [i for i in ships if i.nation == nation]

        if not ships:
            embed = discord.Embed(color=discord.Color.red())
            embed.description = "❌ No ships match your filters!"
            resp = interaction.response.send_message
            await resp(embed=embed, ephemeral=True)
            return

        ship = random.choice(ships)
        await get_modules(interaction, ship)
        view = ShipView(interaction, ship)
        embed = OverviewEmbed(view.fitting)
        await interaction.response.send_message(view=view, embed=embed)
        view.message = await interaction.original_response()


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Fittings(bot))
