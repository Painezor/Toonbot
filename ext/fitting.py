"""Get ship Parameters with various modules equipped"""
from __future__ import annotations

import collections
import logging
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils
from ext import wows_api as api

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]


logger = logging.getLogger("fitting")


class ShipView(view_utils.BaseView):
    """A view representing a ship"""

    bot: PBot
    interaction: Interaction

    def __init__(self, interaction: Interaction, ship: api.Ship) -> None:
        super().__init__(interaction)
        self.ship: api.Ship = ship

        fitting = api.ShipFit([i for i in ship.module_tree if i.is_default])
        self.fitting = fitting
        self.profile: typing.Optional[api.ShipProfile] = None

    async def base_embed(self) -> discord.Embed:
        """Get a generic embed for the ship"""

        if any([self.ship.is_premium, self.ship.is_special]):
            icon_url = self.ship.type.images.image_premium
        else:
            icon_url = self.ship.type.images.image
        cls_ = self.ship.type.alias

        nation = self.ship.nation.alias
        tier = f"Tier {self.ship.tier}"

        name = [i for i in [tier, nation, cls_, self.ship.name] if i]

        embed = discord.Embed()
        embed.set_author(name=" ".join(name), icon_url=icon_url)

        if self.ship.images:
            embed.set_thumbnail(url=self.ship.images.contour)
        return embed

    async def fetch_modules(self) -> None:
        """Grab all data related to the ship from the API"""
        # Get needed module IDs
        m_ids = [s.module_id for s in self.bot.modules]

        avail = self.ship.modules.all_modules
        to_fetch = [str(i) for i in avail if i not in m_ids]

        if to_fetch:
            # We want the module IDs as str for the purposes of params
            ids = ",".join(to_fetch)
            params = {"application_id": api.WG_ID, "module_id": ids}
            url = "https://api.worldofwarships.eu/wows/encyclopedia/modules/"
            async with self.bot.session.get(url, params=params) as resp:
                if resp.status != 200:
                    stat = resp.status
                    name = self.ship.name
                    err = f"{stat} error fetching modules for {name} on {url}"
                    raise ConnectionError(err)
                data = await resp.json()

            for module_id, data in data["data"].items():
                self.bot.modules[module_id] = api.Module(data)
        return

    async def handle_buttons(self, current_function: typing.Callable) -> None:
        """Handle the Funcables"""

        try:
            language = {
                discord.Locale.czech: "cs",
                discord.Locale.german: "de",
                discord.Locale.spain_spanish: "es",
                discord.Locale.french: "fr",
                discord.Locale.japanese: "ja",
                discord.Locale.polish: "pl",
                discord.Locale.russian: "ru",
                discord.Locale.thai: "th",
                discord.Locale.taiwan_chinese: "zh-tw",
                discord.Locale.turkish: "tr",
                discord.Locale.chinese: "zh-cn",
                discord.Locale.brazil_portuguese: "pt-br",
            }[self.interaction.locale]
        except KeyError:
            pass

        if self.profile is None:
            self.profile = await self.fitting.get_params(self.interaction)

        await self.fetch_modules()

        self.clear_items()

        row = 1

        def make_ship_button(i: api.warships.Ship, emoji: str):
            func = ShipView(self.interaction, i).overview
            btn = view_utils.Funcable(f"Tier {i.tier}: {i.name}", func)
            btn.emoji = emoji
            return btn

        ships = self.interaction.client.ships
        prv = [i for i in ships if str(self.ship.ship_id) in i.next_ships]
        buttons = [make_ship_button(i, "▶") for i in prv]
        buttons += [make_ship_button(i, "◀") for i in self.ship.next_ships]

        if buttons:
            self.add_function_row(buttons, row, "View Next/previous Ship")
            row += 1

        buttons.clear()

        # TODO: Wows Numbers Ship Leaderboard Button
        def add_button(label: str, function: typing.Callable, emoji: str):
            btn = view_utils.Funcable(label, function)
            btn.disabled = current_function is function
            btn.emoji = emoji
            buttons.append(btn)

        add_button("Overview", self.overview, self.profile.hull.emoji)

        if self.profile.artillery:
            add_button(
                "Main Battery", self.main_guns, self.profile.artillery.emoji
            )

        if self.profile.torpedoes:
            add_button("Torpedoes", self.torpedoes, self.profile.torpedoes.emoji)

        planes = [
            self.profile.dive_bomber,
            self.profile.fighters,
            self.profile.torpedo_bomber,
        ]

        if any(planes):
            _ = next(i for i in planes if i).emoji
            add_button("Aircraft", self.aircraft, _)

        # Secondaries & AA
        add_button("Auxiliary", self.auxiliary, self.profile..emoji)
        self.add_function_row(buttons, row)

        # Dropdown - setattr
        del buttons

        buttons = []
        excluded = []
        for i in self.ship.modules.all_modules:
            if i not in self.fitting.all_modules:
                excluded.append(i)

        for module_id in excluded:
            module = self.ship.modules[module_id]

            name = f"{module.name} ({module.__class__.__name__})"
            opt = discord.SelectOption(label=name, emoji=module.emoji)
            opt.value = str(module.module_id)

            if module.is_default:
                opt.description = "Stock Module"
                buttons.append(opt)
                continue

            desc = []
            if module.price_credit != 0:
                desc.append(f"{format(module.price_credit, ',')} credits")
            if module.price_xp != 0:
                desc.append(f"{format(module.price_xp, ',')} xp")
            opt.description = ", ".join(desc) if desc else "No Cost"
            buttons.append(opt)
        self.add_item(ModuleSelect(buttons, 0, current_function))

    async def aircraft(self) -> discord.InteractionMessage:
        """Get information about the ship's Aircraft"""
        embed = await self.base_embed()

        await self.handle_buttons(self.aircraft)
        assert self.profile is not None

        # Rocket Planes are referred to as 'Fighters'
        if (rkt := self.profile.fighters) is not None:
            name = f"{rkt.name} (Tier {rkt.plane_level}, Rocket Planes)"
            value = [
                f"**Hit Points**: {format(rkt.max_health, ',')}",
                f"**Cruising Speed**: {rkt.cruise_speed} kts",
                # TODO: Flesh out rest of rocket plane data
                "\n*Rocket Plane Damage not available in the API, sorry*",
            ]
            embed.add_field(name=name, value="\n".join(value), inline=False)

        if (t_b := self.profile.torpedo_bomber) is not None:
            name = f"{t_b.name} (Tier {t_b.plane_level}, Torpedo Bombers"

            if (t_name := t_b.torpedo_name) is None:
                t_name = "Unnamed Torpedo"

            value = [
                f"**Hit Points**: {format(t_b.max_health, ',')}",
                f"**Cruising Speed**: {t_b.cruise_speed} kts",
                "",
                f"**Torpedo**: {t_name}",
                f"**Max Damage**: {format(t_b.max_damage)}",
                f"**Max Speed**: {t_b.torpedo_max_speed} kts",
            ]
            embed.add_field(name=name, value="\n".join(value), inline=False)

        if (d_b := self.profile.dive_bomber) is not None:
            name = f"{d_b.name} (Tier {d_b.plane_level}, Dive Bombers"

            if (bomb_name := d_b.bomb_name) is None:
                bomb_name = "Bomb Stats"

            value = [
                f"**Hit Points**: {format(d_b.max_health, ',')}",
                f"**Cruising Speed**: {d_b.cruise_speed} kts",
                "",
                f"**{bomb_name}**",
                f"**Damage**: {format(d_b.max_damage, ',')}",
                f"**Mass**: {d_b.bomb_bullet_mass}kg",
                f"**Accuracy**: {d_b.accuracy.min} - {d_b.accuracy.max}",
            ]

            if (fire_chance := d_b.bomb_burn_probability) is not None:
                value.append(f"**Fire Chance**: {round(fire_chance, 1)}%")
            embed.add_field(name=name, value="\n".join(value), inline=False)

        embed.set_footer(text="Rocket planes & Skip Bombs are not in the API.")
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)

    async def auxiliary(self) -> discord.InteractionMessage:
        """Get information on the ship's secondaries and anti-air."""
        await self.handle_buttons(self.auxiliary)
        assert self.profile is not None

        embed = await self.base_embed()

        desc = []

        if (sec := self.profile.atbas) is None:
            i = "```diff\n- This ship has no secondary armament.```"
            embed.add_field(name="No Secondary Armament", value=i)

        elif not sec.slots:
            i = "```diff\n" "- Secondary armament not found in API.```"
            embed.add_field(name="API Error", value=i)

        else:
            desc.append(f"**Secondary Range**: {sec.distance}")
            desc.append(f"**Total Barrels**: {self.profile.hull.atba_barrels}")

            for i in sec.slots:
                name = i.name

                text = [
                    f"**Damage**: {format(i.damage, ',')}",
                    f"**Shell Type**: {i.type}",
                    f"**Reload Time**: {i.shot_delay}s ("
                    f"{round(i.gun_rate, 1)} rounds/minute)",
                    f"**Initial Velocity**: {i.bullet_speed}m/s",
                    f"**Shell Weight**: {i.bullet_mass}kg",
                ]

                if fire_chance := i.burn_probability:
                    text.append(f"**Fire Chance**: {round(fire_chance, 1)}")

                embed.add_field(name=name, value="\n".join(text))

        if (a_a := self.profile.anti_air) is None:
            aad = ["```diff\n- This ship has no AA Capability.```"]
        else:
            aa_guns: dict[str, list] = collections.defaultdict(list)
            for i in a_a.slots:
                row = f"{i.guns}x{i.calibre}mm ({i.avg_damage} dps)\n"
                aa_guns[i.name].append(row)

            aad = []
            for k, val in aa_guns.items():
                aad.append(f"**{k}**\n")
                aad.append("\n".join(val))
                aad.append("\n")

        embed.add_field(name="AA Guns", value="".join(aad), inline=False)

        embed.description = "\n".join(desc)
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)

    async def main_guns(self) -> discord.InteractionMessage:
        """Get information about the ship's main battery"""
        await self.handle_buttons(self.main_guns)
        assert self.profile is not None

        embed = await self.base_embed()

        # Guns
        mains = self.profile.artillery
        guns = []
        caliber = ""
        for i in mains.slots:
            embed.title = i.name
            guns.append(f"{i.guns}x{i.barrels}")
            caliber = f"{str(embed.title).split('mm', maxsplit=1)[0]}"

        reload_time: float = mains.shot_delay

        rlt = round(reload_time, 1)
        embed.description = (
            f"**Guns**: {','.join(guns)} {caliber}mm\n"
            f"**Max Dispersion**: {mains.max_dispersion}m\n"
            f"**Range**: {mains.distance}km\n"
            f"**Reload Time**: {rlt}s ({mains.gun_rate} rounds/minute)"
        )

        for i in mains.shells:
            shell_data = [
                f"**Damage**: {format(i.damage, ',')}",
                f"**Initial Velocity**: {format(i.bullet_speed, ',')}m/s",
                f"**Shell Weight**: {format(i.bullet_mass, ',')}kg",
            ]

            if (fire_chance := i.burn_probability) is not None:
                shell_data.append(f"**Fire Chance**: {fire_chance}%")

            name = f"{i.type}: {i.name}"
            embed.add_field(name=name, value="\n".join(shell_data))

        embed.set_footer(text="SAP Shells are currently not in the API.")
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)

    async def torpedoes(self) -> discord.InteractionMessage:
        """Get information about the ship's torpedoes"""
        await self.handle_buttons(self.torpedoes)
        assert self.profile is not None

        embed = await self.base_embed()

        torps = self.profile.torpedoes
        for i in torps.slots:
            value = f"{i.guns}x{i.barrels}x{i.caliber}mm"
            embed.add_field(name=i.name, value=value)

        embed.title = torps.torpedo_name

        reload_time: float = torps.reload_time

        # TODO: Calculate Reaction Time
        trp_desc = [
            f"**Range**: {torps.distance}km",
            f"**Speed**: {torps.torpedo_speed}kts",
            f"**Damage**: {format(torps.max_damage, ',')}",
            f"**Detectability**: {torps.visibility_dist}km",
            f"**Reload Time**: {round(reload_time, 2)}s",
            f"**Launchers**: {self.profile.hull.torpedoes_barrels}",
            f"**Launcher 180° Time**: {torps.rotation_time}s",
        ]

        embed.description = "\n".join(trp_desc)
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)

    async def overview(self) -> discord.InteractionMessage:
        """Get a general overview of the ship"""
        await self.handle_buttons(self.overview)
        assert self.profile is not None

        params = self.profile

        embed = await self.base_embed()
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
                embed.add_field(name="Special Upgrade Slots", value=text)

        if self.ship.images:
            embed.set_image(url=self.ship.images.large)

        embed.set_footer(text=self.ship.description)

        # Parse Modules for ship data
        rst = params.mobility.rudder_time
        detect = params.concealment.detect_distance_by_ship
        air_detect = params.concealment.detect_distance_by_plane
        desc = [
            f"**Hit Points**: {format(params.hull.health, ',')}",
            f"**Concealment**: {detect}km ({air_detect}km by air)",
            f"**Maximum Speed**: {params.mobility.max_speed}kts",
            f"**Rudder Shift Time**: {rst} seconds",
            f"**Turning Radius**: {params.mobility.turning_radius}m",
        ]

        # f"-{params['armour']['flood_prob']}% flood chance."
        #  This field appears to be Garbage.
        if (belt := params.armour.flood_damage) != 0:
            desc.append(f"**Torpedo Belt**: -{belt}% damage")

        # Build Rest of embed description
        if self.ship.price_gold != 0:
            cost = format(self.ship.price_gold, ",")
            desc.append(f"**Doubloon Price**: {cost}")

        if self.ship.price_credit != 0:
            cost = format(self.ship.price_credit, ",")
            desc.append(f"**Credit Price**: {cost}")

        if self.ship.has_demo_profile:
            embed.add_field(name="WIP", value="Parameters are not Final.")

        embed.description = "\n".join(desc)

        if self.ship.next_ships:
            vals: list[tuple] = []
            for (ship_id, xp_) in self.ship.next_ships:  # ShipID, XP Cost
                nxt = self.bot.get_ship(int(ship_id))
                if nxt is None:
                    continue

                creds = format(nxt.price_credit, ",")
                xp_ = format(xp_, ",")
                text = (
                    f"**{nxt.name}** (Tier {nxt.tier} {nxt.type.alias}):"
                    f"{xp_} XP, {creds} credits"
                )
                vals.append((nxt.tier, text))

            if vals:
                keys = [i[1] for i in sorted(vals, key=lambda x: x[0])]
                embed.add_field(name="Next Ships", value="\n".join(keys))

        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


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

    async def callback(self, interaction: Interaction) -> None:
        """Mount each selected module into the fitting."""

        await interaction.response.defer()
        for value in self.values:
            self.view.fitting.set_module(value)

        # Update fitting.
        self.view.profile = await self.view.fitting.get_params(interaction)

        # Invoke last function again.
        return await self.current_function()


class Fittings(commands.Cog):
    """View Ship Fittiings in various states"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    async def cog_load(self) -> None:
        """Fetch Generics from API and store to bot."""
        self.bot.modes = await api.get_game_modes()
        self.bot.ships = await api.get_ships()

        # if not self.bot.clan_buildings:
        #     self.bot.clan_buildings = await self.cache_clan_base()

    @discord.app_commands.command()
    @discord.app_commands.describe(ship="Search for a ship by it's name")
    @discord.app_commands.guilds(250252535699341312)
    async def ship(
        self,
        interaction: Interaction,
        ship: api.ship_transform,
    ) -> discord.InteractionMessage:
        """Search for a ship in the World of Warships API"""
        await interaction.response.defer(thinking=True)

        if ship is None:
            ship = next(i for i in self.bot.ships)
        return await ShipView(interaction, ship).overview()


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(Fittings(bot))
