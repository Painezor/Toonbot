"""Private world of warships related commands"""
from __future__ import annotations

import logging
import typing
from typing import Literal, Optional
import importlib

import discord
from discord.ext import commands

from ext.clans import ClanView
from ext.fitting import ship_ac
from ext.painezbot_utils import player as plr
from ext.painezbot_utils.ship import Ship
from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from painezBot import PBot

# TODO: Browse all Ships command. Filter Dropdowns.
# Dropdown to show specific ships.
# TODO: Clan Base Commands
# https://api.worldofwarships.eu/wows/clans/glossary/
# TODO: Recent command.
# https://api.worldofwarships.eu/wows/account/statsbydate/
# TODO: Refactor to take player stats from website instead.

logger = logging.getLogger("warships")


API_PATH = "https://api.worldofwarships.eu/wows/"
CLAN = API_PATH + "clans/glossary/"
PLAYERS = API_PATH + "account/list/"

REGION = Literal["eu", "na", "sea"]

# TODO: Calculation of player's PR
# https://wows-numbers.com/personal/rating


SHIP_KEYS = {
    "max_frags_battle": "max_frags_ship_id",
    "max_damage_dealt": "max_damage_dealt_ship_id",
    "max_xp": "max_xp_ship_id",
    "max_total_agro": "max_total_agro_ship_id",
    "max_damage_scouting": "max_scouting_damage_ship_id",
    "max_ships_spotted": "max_ships_spotted_ship_id",
    "max_planes_killed": "max_planes_killed_ship_id",
    "main_battery.max_frags_battle": "main_battery.max_frags_ship_id",
    "second_battery.max_frags_battle": "second_battery.max_frags_ship_id",
    "ramming.max_frags_battle": "ramming.max_frags_ship_id",
    "torpedoes.max_frags_battle": "torpedoes.max_frags_ship_id",
    "aircraft.max_frags_battle": "aircraft.max_frags_ship_id",
}


class ShipModal(discord.ui.Modal):
    # TODO: Popup, type in ship name, get next in bot.ships

    def __init__(self, *, title: str = ...) -> None:
        super().__init__(title=title)
        raise NotImplementedError


class ShipButton(discord.ui.Button):
    # TODO: Maake ShipModal
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.blurple, label="Ship")
        raise NotImplementedError


class PlayerView(view_utils.BaseView):
    """A View representing a World of Warships player"""

    bot: PBot
    interaction: discord.Interaction[PBot]

    def __init__(
        self,
        interaction: discord.Interaction[PBot],
        player: plr.Player,
        ship: Optional[Ship] = ...,
        **kwargs,
    ) -> None:
        super().__init__(interaction, **kwargs)

        # Passed
        self.player: plr.Player = player
        self.ship: Optional[Ship] = ship

    async def base_embed(self) -> discord.Embed:
        """Base Embed used for all sub embeds."""
        accid = self.player.account_id

        dom = self.player.region.domain
        _id = self.player.account_id
        url = f"https://vortex.worldofwarships.{dom}/api/accounts/{_id}/"

        logger.info("Fetching player stats...")
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                raise ConnectionError("Could not connect to %s", url)
            self.stats = await resp.json()

        e = discord.Embed()

        p = self.player
        if self.player.clan is None:
            await self.player.get_clan_info()

        if p.clan:
            e.set_author(name=f"[{p.clan.tag}] {p.nickname} ({p.region.name})")
        else:
            e.set_author(name=f"{p.nickname} ({p.region.name})")

        if self.stats["data"][str(accid)]["visibility_settings"]:
            e.set_footer(text="This player has hidden their stats.")
        logger.info("Player Stats fetched succesfully.")
        return e

    async def clan_battles(self, season: int) -> discord.InteractionMessage:
        """Attempt to fetch player's Clan Battles data."""
        raise NotImplementedError(season)

    #     if self.player.clan is None:
    #         raise AttributeError

    #     self.handle_buttons(self.clan_battles)

    #     if self.player.clan.season_number is None:
    #         await self.player.clan.get_data()
    #         sn = self.player.clan.season_number
    #     else:
    #         sn = None

    #     if season not in self.player.clan_battle_stats:
    #         await self.player.clan.get_member_clan_battle_stats(season)

    #     dd = []
    #     if sn is not None:
    #         func = self.clan_battles
    #         for x in range(sn):

    #             item = view_utils.Funcable(f"Season {x}", func)
    #             item.emoji = self.mode.emoji
    #             item.args = [x]
    #             dd.append(item)
    #     self.add_function_row(dd, 1, "Change Season")

    #     stats = self.player.clan_battle_stats[season]
    #     logging.info(f"Found clan battle stats {stats}")

    #     e = await self.base_embed()
    #     e.title = f"Clan Battles (Season {season})"
    #     wr = round(stats.win_rate, 2)
    #     n = stats.battles
    #     avg = format(round(stats.average_damage, 0), ",")
    #     kll = round(stats.average_kills, 2)
    #     e.description = (
    #         f"**Win Rate**: {wr}% ({n} battles played)\n"
    #         f"**Average Damage**: {avg}\n"
    #         f"**Average Kills**: {kll}\n"
    #     )
    #     return await self.update(e)

    def handle_buttons(
        self, current_function: typing.Callable, div_size: Optional[int] = None
    ) -> int:
        row_0: list[view_utils.Funcable] = []

        self.clear_items()

        # Summary
        ov = view_utils.Funcable("Profile", self.overview)
        ov.disabled = current_function == self.overview
        ov.emoji = "🔘"

        row_0.append(ov)

        # Clan
        if self.player.clan:
            i = self.interaction
            parent = current_function
            func = ClanView(i, self.player.clan, parent=parent).overview
            cln = view_utils.Funcable("Clan", func)
            row_0.append(cln)

        self.add_function_row(row_0)
        row = 1

        game_modes: list[view_utils.Funcable] = []
        for i in self.bot.modes:
            if i.tag in ["EVENT", "BRAWL", "PVE_PREMADE"]:
                continue
            # We can't fetch CB data without a clan.
            if i.tag == "CLAN" and not self.player.clan:
                continue

            func = {
                "CLAN": self.clan_battles,
                "PVP": self.randoms,
                "RANKED": self.ranked,
                "COOPERATIVE": self.coop,
                "PVE": self.operations,
            }[i.tag]

            btn = view_utils.Funcable(f"{i.name} ({i.tag})", func)
            btn.description = i.description
            btn.emoji = i.emoji
            btn.disabled = current_function == func
            game_modes.append(btn)

        if game_modes:
            self.add_function_row(game_modes, row, "Change Game Mode")
            row += 1

        div_buttons = []
        if current_function:  # TODO: != self.clan_battles:
            # Div Size Buttons
            # emoji = self.mode.emoji
            for i in range(0, 3):
                name = f"{i}" if i != 0 else "Overall"

                args = [i]
                btn = view_utils.Funcable(name, current_function, args=args)
                btn.disabled = div_size == i
                div_buttons.append(btn)

        if div_buttons:
            self.add_function_row(div_buttons, row)
            row += 1
        return row

    # Not in API
    # async def brawl(self) -> discord.InteractionMessage:
    #     self.handle_buttons(self.brawl)

    async def operations(
        self, mode: str, div_size: int = 0
    ) -> discord.InteractionMessage:
        # Can be gotten via normal API
        stats: dict = self.player.stats[self.ship][mode]

        e = await self.base_embed()

        dd = []
        bt = view_utils.Funcable("Solo", self.operations, args=["oper_solo"])
        bt.disabled = mode == "oper_solo"

        dd.append(bt)
        bt = view_utils.Funcable(
            "Pre-Made", self.operations, args=["oper_div"]
        )
        bt.disabled = mode == "oper_div"
        dd.append(bt)
        bt = view_utils.Funcable(
            "Hard Mode", self.operations, args=["oper_div_hard"]
        )
        bt.disabled = mode == "oper_div_hard"

        self.add_function_row(dd, 1)

        p_stats = stats.copy()
        # Overall Rates - Survival, WR, Wins, Loss, Draw
        survived = p_stats.pop("survived_battles", 0)
        suv_wins = p_stats.pop("survived_wins", 0)
        played = p_stats.pop("battles", 0)
        wins = p_stats.pop("wins", 0)
        loss = p_stats.pop("losses", 0)
        draws = p_stats.pop("draws", 0)

        desc = []
        try:
            wr = round(wins / played * 100, 2)
            rest = f" ({played} Battles - {wins} W / {draws} D / {loss} L )"
            desc.append(f"**Win Rate**: {wr}%{rest}")
        except ZeroDivisionError:
            pass

        try:
            sr = round(survived / played * 100, 2)
            s_tot = format(survived, ",")
            desc.append(f"**Survival Rate (Overall)**: {sr}% (Total: {s_tot})")
        except ZeroDivisionError:
            pass

        try:
            swr = round(suv_wins / wins * 100, 2)
            tot_w = format(suv_wins, ",")
            desc.append(f"**Survival Rate (Wins)**: {swr}% (Total: {tot_w})")
        except ZeroDivisionError:
            pass

        # Totals
        dmg = p_stats.pop("damage_dealt", 0)
        kills = p_stats.pop("frags", 0)
        tot_xp = p_stats.pop("xp", 0)
        spotted = p_stats.pop("ships_spotted", 0)
        spotting = p_stats.pop("damage_scouting", 0)
        potential = p_stats.pop("torpedo_agro", 0) + p_stats.pop("art_agro", 0)
        planes = p_stats.pop("planes_killed", 0)
        x_avg = format(round(tot_xp / played), ",")
        x_tot = format(tot_xp, ",")
        desc.append(f"**Average XP**: {x_avg}\n" f"**Total XP**: {x_tot}")

        # Averages - Kills, Damage, Spotting, Potential
        try:
            d_avg = format(round(dmg / played), ",")
            k_avg = round(kills / played, 2)
            x_avg = format(round(tot_xp / played), ",")
            p_avg = format(round(potential / played), ",")
            s_avg = format(round(spotting / played), ",")
            sp_av = format(round(spotted / played, 2), ",")
            pl_av = round(planes / played, 2)

            avg = (
                f"**Kills**: {k_avg}\n**Damage**: {d_avg}\n"
                f"**Potential**: {p_avg}\n**Spotting**: {s_avg}\n"
                f"**Ships Spotted**: {sp_av}\n**XP**: {x_avg}\n"
                f"**Planes**: {pl_av}"
            )
            e.add_field(name="Averages", value=avg)

            # Records
            r_dmg = format(p_stats.pop("max_damage_dealt", 0), ",")
            r_xp = format(p_stats.pop("max_xp", 0), ",")
            r_kills = p_stats.pop("max_frags_battle", 0)
            r_pot = format(p_stats.pop("max_total_agro", 0), ",")
            r_spot = format(p_stats.pop("max_damage_scouting", 0), ",")
            r_ship_max = p_stats.pop("max_ships_spotted", 0)
            r_planes = p_stats.pop("max_planes_killed", 0)

            s_dmg = self.bot.get_ship(
                p_stats.pop("max_damage_dealt_ship_id", None)
            )
            s_xp = self.bot.get_ship(p_stats.pop("max_xp_ship_id", None))
            s_kills = self.bot.get_ship(p_stats.pop("max_frags_ship_id", None))
            s_pot = self.bot.get_ship(
                p_stats.pop("max_total_agro_ship_id", None)
            )
            s_spot = self.bot.get_ship(
                p_stats.pop("max_scouting_damage_ship_id", None)
            )
            s_ship_max = self.bot.get_ship(
                p_stats.pop("max_ships_spotted_ship_id", None)
            )
            s_planes = self.bot.get_ship(
                p_stats.pop("max_planes_killed_ship_id", None)
            )

            # Records, Totals
            rec = []
            for record, ship in [
                (r_kills, s_kills),
                (r_dmg, s_dmg),
                (r_pot, s_pot),
                (r_ship_max, s_ship_max),
                (r_spot, s_spot),
                (r_xp, s_xp),
                (r_planes, s_planes),
            ]:
                try:
                    rec.append(f"{record} ({ship.name})")
                except AttributeError:
                    rec.append(f"{record}")

            e.add_field(name="Records", value="\n".join(rec))

            e.add_field(
                name="Totals",
                value=f"{format(kills, ',')}\n{format(dmg, ',')}\n"
                f"{format(potential, ',')}\n{format(spotting, ',')}\n"
                f"{format(spotted, ',')}\n{format(tot_xp, ',')}\n"
                f"{format(planes, ',')}",
            )
        except ZeroDivisionError:
            desc.append(
                "```diff\n- Could not find player stats for this"
                " game mode and division size```"
            )
            logging.error(
                "Could not find stats for size [%s] mode [%s]",
                div_size,
                mode,
            )

        # Operations specific stats.
        try:
            star_rate = sorted(
                [(k, v) for k, v in p_stats.pop("wins_by_tasks").items()],
                key=lambda st: int(st[0]),
            )

            s1, s2 = r"\⭐", r"\★"
            star_desc = [
                f"{x * s1}{(5 - x) * s2}: {star_rate[x][1]}"
                for x in range(0, 5)
            ]
            e.add_field(name="Star Breakdown", value="\n".join(star_desc))
        except KeyError:
            pass

        e.description = "\n".join(desc)
        return await self.update(embed=e)

    # Parse the VORTEX api for stats
    async def stats_embed_vortex(
        self, embed: discord.Embed, stats: dict
    ) -> discord.InteractionMessage:
        edit = self.interaction.edit_original_response

        embed.description = ""

        stats = stats.copy()
        # TODO: Page Buttons for other embeds.

        wins = stats.pop("wins")
        losses = stats.pop("losses")
        played = stats.pop("battles_count")
        draws = played - wins - losses
        surv = stats.pop("survived")

        wr = round(100 / played * wins, 2)
        sr = round(100 / played * surv, 2)

        embed.description += f"**Win Rate**: {wr}% ({wins}/{draws}/{losses})\n"
        embed.description += f"**Survival Rate**: {sr}% ({surv}/{played})\n"

        # Average Damage
        if damage := stats.pop("damage_dealt", {}):
            avg_dmg = round(damage / played)

            damage = format(damage, ",")
            embed.description += f"**Average Damage**: {avg_dmg}"
            if max_damage := stats.pop("max_damage_dealt", {}):
                max_damage = format(max_damage, ",")
                embed.description += f" (Max: {max_damage}"
                if ship_id := stats.pop("max_damage_dealt_vehicle", None):
                    if (ship := self.bot.get_ship(ship_id)) is None:
                        ship = f"{ship_id}"
                    else:
                        ship = ship.name
                    embed.description += f" - {ship}"
                embed.description += ")"
            embed.description += f" (Total: {damage})"
            embed.description += "\n"

        # Kill Breakdown
        if kills := stats.pop("frags", {}):
            kpg = round(kills / played, 2)
            embed.description += f"**KPG**: {kpg}"
            if max_kills := stats.pop("max_frags", {}):
                embed.description += f" (Max: {max_kills}"
                if ship_id := stats.pop("max_frags_vehicle", None):
                    if (ship := self.bot.get_ship(ship_id)) is None:
                        ship = f"{ship_id}"
                    else:
                        ship = ship.name
                    embed.description += f" - {ship}"
                embed.description += ")"
            embed.description += "\n"

        def handle_armament(alias: str, api_key: str):
            output = ""

            if kills := stats.pop(f"frags_by_{api_key}", {}):
                output += f"**{alias} Kills**: {kills}"
                if max_kills := stats.pop(f"max_frags_by_{api_key}", {}):
                    output += f" (Max: {max_kills}"
                    shp_id = stats.pop(f"max_frags_by_{api_key}_vehicle", None)
                    if shp_id:
                        if (ship := self.bot.get_ship(shp_id)) is None:
                            ship = f"{shp_id}"
                        else:
                            ship = ship.name
                        output += f" - {ship}"
                    output += ")"
                output += "\n"

                if shots := stats.pop(f"shots_by_{api_key}", None):
                    hits = stats.pop(f"hits_by_{api_key}")

                    accuracy = round(100 / shots * hits, 2)
                    shots = format(shots, ",")
                    hits = format(hits, ",")
                    output += f"**Accuracy**: {accuracy}% ({hits}/{shots})\n"
            else:
                if shots := stats.pop(f"shots_by_{api_key}", None):
                    hits = stats.pop(f"hits_by_{api_key}")

                    accuracy = round(100 / shots * hits, 2)
                    shots = format(shots, ",")
                    hits = format(hits, ",")
                    output += (
                        f"**{alias} Accuracy**: {accuracy}% ({hits}/{shots})\n"
                    )
            return output

        # Armaments.
        embed.description += handle_armament("Main Battery", "main")
        embed.description += handle_armament("Secondary Battery", "atba")
        embed.description += handle_armament("Torpedoes", "tpd")
        embed.description += handle_armament("Depth Charges", "dbomb")
        embed.description += handle_armament("Aircraft", "plane")
        embed.description += handle_armament("Bombs", "bomb")
        embed.description += handle_armament("Skip Bombs", "skip")
        embed.description += handle_armament("Rockets", "rocket")
        embed.description += handle_armament("Torpedo Bombers", "tbomb")

        # Misc
        if aa := stats.pop("planes_killed", None):
            aa = format(aa, ",")
            embed.description += f"**Planes Killed**: {aa}"
            if max_aa := stats.pop("max_planes_killed", None):
                embed.description += f" (Max: {max_aa}"
                if ship_id := stats.pop("max_planes_killed_vehicle", None):
                    if (ship := self.bot.get_ship(ship_id)) is None:
                        ship = f"{ship_id}"
                    else:
                        ship = ship.name
                    embed.description += f" - {ship}"
                embed.description += ")"
            embed.description += "\n"

        remainder = {
            "win_and_survived": 973,
            "exp": 20615052,
            "max_exp": 2833,
            "premium_exp": 9176275,
            "original_exp": 5595414,
            "max_exp_vehicle": 4282267344,
            "max_premium_exp": 4675,
            "max_premium_exp_vehicle": 4282267344,
            "ships_spotted": 18328,
            "max_ships_spotted": 12,
            "max_ships_spotted_vehicle": 4178556880,
            "scouting_damage": 184757494,
            "max_scouting_damage": 281148,
            "max_scouting_damage_vehicle": 3750639408,
            "art_agro": 3786491571,
            "tpd_agro": 440347415,
            "max_total_agro": 4123800,
            "max_total_agro_vehicle": 4075763504,
            "control_dropped_points": 30079,
            "control_captured_points": 92186,
            "team_control_captured_points": 813197,
            "team_control_dropped_points": 534402,
        }

        for k, v in stats.items():
            if "battles_count" in k:
                continue
            if not v:
                continue
            logger.info("PlayerView - Unparsed Data remains %s: %s", k, v)

        return await edit(embed=embed, view=self)

    async def overview(self) -> discord.InteractionMessage:
        # TODO: WoWs Player Overview
        raise NotImplementedError

    async def coop(self) -> discord.InteractionMessage:
        self.handle_buttons(self.coop, None)

        embed = await self.base_embed()
        acc_id = str(self.player.account_id)
        stats = self.stats["data"][acc_id]["statistics"]["pve"]
        embed.title = "Coop Battles"
        return await self.stats_embed_vortex(embed, stats)

    async def ranked(self, div_size: int = 1) -> discord.InteractionMessage:
        self.handle_buttons(self.ranked, None)

        embed = await self.base_embed()
        acc_id = str(self.player.account_id)

        if div_size == 1:
            stats = self.stats["data"][acc_id]["statistics"]["rank_solo"]
            embed.title = "Random Battles (Solo)"
            return await self.stats_embed_vortex(embed, stats)

        elif div_size == 2:
            stats = self.stats["data"]["statistiics"][acc_id]["rank_div2"]
            embed.title = "Random Battles (Division of 2)"
            return await self.stats_embed_vortex(embed, stats)

        else:
            stats = self.stats["data"][acc_id]["statistics"]["rank_div3"]
            embed.title = "Random Battles (Division of 3)"
            return await self.stats_embed_vortex(embed, stats)

    async def ranked_old(self) -> discord.InteractionMessage:
        # TODO: Old Ranked Stats
        raise NotImplementedError

    async def randoms(self, div_size: int = 0) -> discord.InteractionMessage:
        self.handle_buttons(self.randoms, div_size)
        # Add Randoms Div Size Buttons

        embed = await self.base_embed()

        mode = next(i for i in self.bot.modes if i.tag == "PVP")
        embed.set_thumbnail(url=mode.image)

        acc_id = str(self.player.account_id)
        if div_size == 0:
            logger.info("Heading to vortex")
            stats = self.stats["data"][acc_id]["statistics"]["pvp"]
            embed.title = "Random Battles (Overall)"
            return await self.stats_embed_vortex(embed, stats)

        elif div_size == 1:
            stats = self.stats["data"][acc_id]["statistics"]["pvp_solo"]
            embed.title = "Random Battles (Solo)"
            return await self.stats_embed_vortex(embed, stats)

        elif div_size == 2:
            stats = self.stats["data"][acc_id]["statistics"]["pvp_div2"]
            embed.title = "Random Battles (Division of 2)"
            return await self.stats_embed_vortex(embed, stats)

        else:
            stats = self.stats["data"][acc_id]["statistics"]["pvp_div3"]
            embed.title = "Random Battles (Division of 3)"
            return await self.stats_embed_vortex(embed, stats)

    async def update(self, embed: discord.Embed) -> discord.InteractionMessage:
        """Send the latest version of the embed to view"""
        self.clear_items()

        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


# Autocomplete.
async def mode_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Fetch a Game Mode"""
    choices = []

    current = current.casefold()
    for i in interaction.client.modes:
        if i.tag not in ["PVE_PREMADE", "EVENT", "BRAWL"]:
            continue
        if current not in i.name.casefold():
            continue
        choices.append(discord.app_commands.Choice(name=i.name, value=i.tag))

        if len(choices) == 25:
            break

    return choices


async def player_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Fetch player's account ID by searching for their name."""
    if len(current) < 3:
        return []

    bot: PBot = interaction.client
    p = {"application_id": bot.wg_id, "search": current, "limit": 25}

    region = getattr(interaction.namespace, "region", None)
    try:
        region = next(i for i in plr.Region if i.db_key == region)
    except StopIteration:
        region = plr.Region.EU

    link = PLAYERS.replace("eu", region.domain)
    async with bot.session.get(link, params=p) as resp:
        if resp.status != 200:
            logger.error("%s connecting to %s", resp.status, link)
            return []
        players = await resp.json()

    logger.info(players)
    data = players.pop("data", None)
    if data is None:
        return []

    choices = []
    for i in data:
        logger.info(i)
        player = bot.get_player(i["account_id"])

        if player is None:
            player = plr.Player(i["account_id"])
            player.nickname = i["nickname"]
            bot.players.append(player)

        if player.clan and player.clan.tag:
            name = f"[{player.clan.tag}] [{player.nickname}]"
        else:
            name = player.nickname

        value = str(player.account_id)
        choices.append(discord.app_commands.Choice(name=name, value=value))

        if len(choices) == 25:
            break

    return choices


class Warships(commands.Cog):
    """World of Warships related commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        importlib.reload(plr)

        # override our custom classes.
        plr.Player.bot = bot

    # TODO: Test - Clan Battles
    @discord.app_commands.command()
    @discord.app_commands.autocomplete(
        name=player_ac, mode=mode_ac, ship=ship_ac
    )
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(
        name="Search for a player name",
        region="Which region is this player on",
        mode="battle mode type",
        division="1 = solo, 2 = 2man, 3 = 3man, 0 = Overall",
        ship="Get statistics for a specific ship",
    )
    async def stats(
        self,
        interaction: discord.Interaction[PBot],
        name: str,
        region: REGION = "eu",
        mode: str = "PVP",
        division: discord.app_commands.Range[int, 0, 3] = 0,
        ship: typing.Optional[str] = None,
    ) -> discord.InteractionMessage:
        """Search for a player's Stats"""
        await interaction.response.defer(thinking=True)

        interaction.extras["region"] = region

        logger.info("Looking for player %s", name)
        try:
            player = self.bot.get_player(int(name))
        except ValueError:
            plr = self.bot.players
            player = next((i for i in plr if name in i.nickname), None)
        if player is None:
            raise

        logger.info("Grabbed player %s", player)

        g_mode = next(i for i in self.bot.modes if i.tag == mode)
        if ship:
            g_ship = self.bot.get_ship(ship)
        else:
            g_ship = None

        logger.info("Spawning View")
        v = PlayerView(interaction, player, g_ship)
        if g_mode.tag == "PVP":
            return await v.randoms(division)
        else:
            raise NotImplementedError(g_mode.tag)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(Warships(bot))
