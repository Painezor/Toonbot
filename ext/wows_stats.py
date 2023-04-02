"""Private world of warships related commands"""
from __future__ import annotations

import logging
import typing
import importlib

import discord
from discord.ext import commands

from ext.clans import ClanView
from ext.fitting import ShipTransformer
from ext.painezbot_utils.ship import Ship
from ext.utils import view_utils, wows_api as api

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

REGION = typing.Literal["eu", "na", "sea"]

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


class PlayerView(view_utils.BaseView):
    """A View representing a World of Warships player"""

    bot: PBot
    interaction: discord.Interaction[PBot]

    def __init__(
        self,
        interaction: discord.Interaction[PBot],
        player: api.Player,
        ship: typing.Optional[Ship] = None,
        **kwargs,
    ) -> None:
        super().__init__(interaction, **kwargs)

        # Passed
        self.player: api.Player = player
        self.ship: typing.Optional[Ship] = ship

        # Fetched
        self.api_stats: typing.Optional[api.PlayerStats] = None

    async def push_stats(
        self, mode: api.GameMode, div_size: int = 0
    ) -> discord.InteractionMessage:
        """Send Stats Embed to View"""
        # Can be gotten via normal API
        embed = discord.Embed()
        embed.set_author(name=self.player.nickname, icon_url=mode.image)
        if self.api_stats is None:
            if self.ship is None:
                self.api_stats = await self.player.fetch_stats()
            else:
                self.api_stats = await self.player.fetch_ship_stats(self.ship)

        stats: api.PlayerModeStats
        stats, embed.title = {
            "BRAWL": {},
            "COOPERATIVE": {
                0: (self.api_stats.pve, "Co-op (Overall)"),
                1: (self.api_stats.pve_solo, "Co-op (Solo)"),
                2: (self.api_stats.pve_div2, "Co-op (Div 2)"),
                3: (self.api_stats.pve_div3, "Co-op (Div 3)"),
            },
            "PVP": {
                0: (self.api_stats.pvp, "PVP (Overall)"),
                1: (self.api_stats.pvp_solo, "PVP (Solo)"),
                2: (self.api_stats.pvp_div2, "PVP (Div 2)"),
                3: (self.api_stats.pvp_div3, "PVP (Div 3)"),
            },
            "PVE": {
                1: (self.api_stats.oper_solo, "Operations (Solo)"),
            },
            "PVE_PREMADE": {
                1: (self.api_stats.oper_div, "Operations (Premade)")
            },
        }[mode.tag][div_size]

        # Handle Buttons
        self.clear_items()

        # Row 0: Parent, Clan
        row_0: list[view_utils.Funcable] = []
        # Clan
        if self.parent:
            self.add_page_buttons(0)

        if self.player.clan:
            itr = self.interaction
            parent = self.push_stats
            func = ClanView(itr, self.player.clan, parent=parent).overview
            cln = view_utils.Funcable("Clan", func)
            row_0.append(cln)
        self.add_function_row(row_0, row=0)

        # Row 1: Change Div Size
        row_1: list[view_utils.Funcable] = []
        if mode.tag in ["RANKED", "PVP", "COOPERATIVE"]:
            for i in range(0, 3):
                if div_size != i:
                    name = f"{i}" if i != 0 else "Overall"

                    args = [i]
                    btn = view_utils.Funcable(name, self.push_stats, args=args)
                    btn.disabled = div_size == i
                    row_1.append(btn)

        self.add_function_row(row_1, row=1)

        # Row 2: Change Mode
        row_2: list[view_utils.Funcable] = []
        for i in self.bot.modes:
            if i.tag in ["EVENT", "BRAWL", "PVE_PREMADE"]:
                continue
            # We can't fetch CB data without a clan.
            if i.tag == "CLAN" and not self.player.clan:
                continue

            btn = view_utils.Funcable(f"{i.name} ({i.tag})", self.push_stats)
            btn.description = i.description
            btn.emoji = i.emoji
            btn.args = [mode]
            btn.disabled = mode == i
            row_2.append(btn)
        self.add_function_row(row_2, row=2)

        # Row 3 - Wows Numbers & Profile Page
        btn = discord.ui.Button(url=self.player.wows_numbers, row=3)
        btn.label = "WoWs Numbers"
        self.add_item(btn)

        btn = discord.ui.Button(url=self.player.community_link, row=3)
        btn.label = "Profile Page"
        self.add_item(btn)

        # Overall Rates - Survival, WR, Wins, Loss, Draw
        survived = stats.survived_battles
        suv_wins = stats.survived_wins
        played = stats.battles
        wins = stats.wins
        loss = stats.losses
        draws = stats.draws

        desc = []
        try:
            win_rate = round(wins / played * 100, 2)
            rest = f"({played} Battles - {wins} W / {draws} D / {loss} L )"
            desc.append(f"**Win Rate**: {win_rate}% {rest}")

            sv_rt = round(survived / played * 100, 2)
            s_tot = format(survived, ",")
            txt = f"**Survival Rate (Overall)**: {sv_rt}% (Total: {s_tot})"
            desc.append(txt)
        except ZeroDivisionError:
            desc.append("This player has not played any battles")

        try:
            swr = round(suv_wins / wins * 100, 2)
            tot_w = format(suv_wins, ",")
            desc.append(f"**Survival Rate (Wins)**: {swr}% (Total: {tot_w})")
        except ZeroDivisionError:
            pass  # 0% WR

        # Totals
        dmg = stats.damage_dealt
        kills = stats.frags
        tot_xp = stats.xp
        spotted = stats.ships_spotted
        spotting = stats.damage_scouting
        potential = stats.potential_damage
        planes = stats.planes_killed
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
            embed.add_field(name="Averages", value=avg)

            # Records
            r_dmg = format(stats.max_damage_dealt, ",")
            r_xp = format(stats.max_xp, ",")
            r_kills = stats.max_frags_battle
            r_pot = format(stats.max_total_agro, ",")
            r_spot = format(stats.max_damage_scouting, ",")
            r_ship_max = stats.max_ships_spotted
            r_planes = stats.max_planes_killed

            s_dmg = self.bot.get_ship(stats.max_damage_dealt_ship_id)
            s_xp = self.bot.get_ship(stats.max_xp_ship_id)
            s_kills = self.bot.get_ship(stats.max_frags_ship_id)
            s_pot = self.bot.get_ship(stats.max_total_agro_ship_id)
            s_spot = self.bot.get_ship(stats.max_scouting_damage_ship_id)
            s_ship_max = self.bot.get_ship(stats.max_ships_spotted_ship_id)
            s_planes = self.bot.get_ship(stats.max_planes_killed_ship_id)

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

            embed.add_field(name="Records", value="\n".join(rec))

            embed.add_field(
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
        if stats.wins_by_tasks is not None:
            star_rate = sorted(
                [(k, v) for k, v in stats.wins_by_tasks.items()],
                key=lambda st: int(st[0]),
            )

            star1, star2 = r"\⭐", r"\★"
            star_desc = [
                f"{x * star1}{(5 - x) * star2}: {star_rate[x][1]}"
                for x in range(0, 5)
            ]
            embed.add_field(name="Star Breakdown", value="\n".join(star_desc))

        embed.description = "\n".join(desc)
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


class ModeTransformer(discord.app_commands.Transformer):
    """Convert user input to API Game Mode"""

    async def autocomplete(
        self,
        interaction: discord.Interaction[PBot],
        current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        modes: list[api.GameMode] = interaction.client.modes
        modes = sorted(modes, key=lambda x: x.name)

        curr = current.casefold()

        choices = []
        for i in modes:
            if curr not in i.name.casefold():
                continue

            choice = discord.app_commands.Choice(name=i.name, value=i.name)
            choices.append(choice)
        return choices

    async def transform(
        self, interaction: discord.Interaction[PBot], value: str
    ) -> typing.Optional[api.GameMode]:
        return next(i for i in interaction.client.modes if i.name == value)


class PlayerTransformer(discord.app_commands.Transformer):
    """Conver User Input to Player Object"""

    async def autocomplete(
        self, interaction: discord.Interaction[PBot], current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Fetch player's account ID by searching for their name."""
        if len(current) < 3:
            return []

        bot: PBot = interaction.client
        params = {"application_id": api.WG_ID, "search": current, "limit": 25}

        region = getattr(interaction.namespace, "region", None)
        try:
            region = next(i for i in api.Region if i.db_key == region)
        except StopIteration:
            region = api.Region.EU

        link = PLAYERS.replace("eu", region.domain)
        async with bot.session.get(link, params=params) as resp:
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
                player = api.Player(i["account_id"])
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

    async def transform(
        self, interaction: discord.Interaction[PBot], value: str
    ) -> typing.Optional[api.Player]:
        try:
            player = interaction.client.get_player(int(value))
        except ValueError:
            plr = interaction.client.players
            player = next((i for i in plr if value in i.nickname), None)

        logger.info("Grabbed player %s", player)
        return player


class Warships(commands.Cog):
    """World of Warships related commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        importlib.reload(api)

    # TODO: Test - Clan Battles
    @discord.app_commands.command()
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(
        player="Search for a player name",
        region="Which region is this player on",
        mode="battle mode type",
        division="1 = solo, 2 = 2man, 3 = 3man, 0 = Overall",
        ship="Get statistics for a specific ship",
    )
    async def stats(
        self,
        interaction: discord.Interaction[PBot],
        region: REGION,
        player: discord.app_commands.Transform[api.Player, PlayerTransformer],
        mode: discord.app_commands.Transform[api.GameMode, ModeTransformer],
        division: discord.app_commands.Range[int, 0, 3] = 0,
        ship: typing.Optional[
            discord.app_commands.Transform[Ship, ShipTransformer]
        ] = None,
    ) -> discord.InteractionMessage:
        """Search for a player's Stats"""
        del region  # Shut up linter.
        await interaction.response.defer(thinking=True)

        view = PlayerView(interaction, player, ship)
        return await view.push_stats(mode, div_size=division)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(Warships(bot))
