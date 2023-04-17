"""Private world of warships related commands"""
from __future__ import annotations

import importlib
import logging
from typing import Any, TYPE_CHECKING, TypeAlias, Optional, Literal

import discord
from discord.ext import commands

from ext.clans import ClanView
from ext import wows_api as api
from ext.utils import view_utils

if TYPE_CHECKING:
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[PBot]
    User: TypeAlias = discord.User | discord.Member

# TODO: Wows Numbers Ship Leaderboard Command.
# TODO: Browse all Ships command. Filter Dropdowns.
# Dropdown to show specific ships.
# TODO: Clan Base Commands
# https://api.worldofwarships.eu/wows/clans/glossary/
# TODO: Recent command.
# https://api.worldofwarships.eu/wows/account/statsbydate/
# TODO: Refactor to take player stats from website instead.

logger = logging.getLogger("warships")

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


class PlayerView(view_utils.BaseView):
    """A View representing a World of Warships player"""

    def __init__(
        self,
        invoker: User,
        player: api.PartialPlayer,
        ship: Optional[api.warships.Ship] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(invoker, **kwargs)

        # Passed
        self.player: api.PartialPlayer = player
        self.ship: Optional[api.warships.Ship] = ship

        # Fetched
        self.api_stats: Optional[api.PlayerStats] = None

        if player.clan is None:
            self.remove_item(self.clan)
        else:
            self.clan.label = f"[{player.clan.tag}]"

        self.wows_numbers.url = self.player.wows_numbers
        self.profile.url = self.player.community_link

    @discord.ui.button()
    async def clan(self, interaction: Interaction, _) -> None:
        """Button to go to the player's clan"""
        assert self.player.clan is not None
        clan = await self.player.clan.fetch_details()
        view = ClanView(interaction.user, clan, parent=self)
        embed = await view.generate_overview(interaction)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @discord.ui.button(label="WoWs Numbers", style=discord.ButtonStyle.url)
    async def wows_numbers(
        self, _: Interaction, __: discord.ui.Button[PlayerView]
    ) -> None:
        """A button with a link to the player's wowsnumbers page"""
        return

    @discord.ui.button(label="Profile", style=discord.ButtonStyle.url)
    async def profile(
        self, _: Interaction, __: discord.ui.Button[PlayerView]
    ) -> None:
        """A button with a link to the player's profile page"""
        return

    async def push_stats(
        self, interaction: Interaction, mode: api.GameMode, div_size: int = 0
    ) -> None:
        """Send Stats Embed to View"""
        # Can be gotten via normal API
        embed = discord.Embed()
        embed.set_author(name=self.player.nickname, icon_url=mode.image)
        if self.api_stats is None:
            if self.ship is None:
                p_stats = await api.fetch_stats([self.player])
                self.api_stats = p_stats[0]
            else:
                self.api_stats = await self.player.fetch_ship_stats(self.ship)

        stats: api.ModeStats
        stats, embed.title = {
            "BRAWL": {},
            "COOPERATIVE": {
                0: (self.api_stats.statistics.pve, "Co-op (Overall)"),
                1: (self.api_stats.statistics.pve_solo, "Co-op (Solo)"),
                2: (self.api_stats.statistics.pve_div2, "Co-op (Div 2)"),
                3: (self.api_stats.statistics.pve_div3, "Co-op (Div 3)"),
            },
            "PVP": {
                0: (self.api_stats.statistics.pvp, "PVP (Overall)"),
                1: (self.api_stats.statistics.pvp_solo, "PVP (Solo)"),
                2: (self.api_stats.statistics.pvp_div2, "PVP (Div 2)"),
                3: (self.api_stats.statistics.pvp_div3, "PVP (Div 3)"),
            },
            "PVE": {
                1: (self.api_stats.statistics.oper_solo, "Operations (Solo)"),
            },
            "PVE_PREMADE": {
                1: (self.api_stats.statistics.oper_div, "Operations (Premade)")
            },
        }[mode.tag][div_size]

        # Handle Buttons
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
        for i in interaction.client.modes:
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

        # Overall Rates - Survival, WR, Wins, Loss, Draw
        survived = stats.survived_battles
        suv_wins = stats.survived_wins
        played = stats.battles
        wins = stats.wins
        loss = stats.losses
        draws = stats.draws

        desc: list[str] = []
        if not played:
            embed.description = "This player has not played any battles"
            await interaction.response.edit_message(embed=embed, view=self)
            return

        win_rate = round(wins / played * 100, 2)
        draws = f"/ {draws} D " if draws else ""
        rest = f"({played} Battles - {wins} W {draws}/ {loss} L)"
        desc.append(f"**Win Rate**: {win_rate}% {rest}")
        sv_rt = round(survived / played * 100, 2)
        s_tot = format(survived, ",")
        txt = f"**Survival Rate (Overall)**: {sv_rt}% (Total: {s_tot})"
        desc.append(txt)

        if wins:
            swr = round(suv_wins / wins * 100, 2)
            tot_w = format(suv_wins, ",")
            desc.append(f"**Survival Rate (Wins)**: {swr}% (Total: {tot_w})")

        # Averages - Kills, Damage, Spotting, Potential
        averages: list[str] = []
        totals: list[str] = []

        def add_lines(
            label: str, rnd: Optional[int], val: Optional[int], games: int
        ) -> None:
            """Add rows to the fields"""
            if not val:
                return
            _ = f"**{label}**: "
            averages.append(f'{_}{format(round(val / games, rnd), ",")}')
            totals.append(f"{_}{format(round(val), ',')}")

        add_lines("Damage", None, stats.damage_dealt, played)
        add_lines("Kills", 2, stats.frags, played)
        add_lines("Experience", None, stats.xp, played)
        add_lines("Potential Damage", None, stats.max_total_agro, played)
        add_lines("Spotting Damage", None, stats.damage_scouting, played)
        add_lines("Ships Spotted", 2, stats.ships_spotted, played)
        add_lines("Planes Killed", 2, stats.planes_killed, played)

        embed.add_field(name="Averages", value="\n".join(averages))
        embed.add_field(name="Totals", value="\n".join(totals))

        records: list[str] = []
        ships = interaction.client.ships

        def handle_record(
            label: str, stat: tuple[Optional[int], Optional[int]]
        ) -> None:
            """Fetch Ship & Add rows to the record field"""
            value, ship_id = stat

            if value is None:
                return

            ship = next((i for i in ships if i.ship_id == ship_id), None)
            if ship is None:
                shp = ""
            else:
                emote = ship.emoji
                shp = f"{ship.nation.flag} {emote} {ship.name} T{ship.tier}"
            records.append(f"**{label}**: {format(stat)} {shp}")

        _ = (stats.max_damage_dealt, stats.max_damage_dealt_ship_id)
        handle_record("Damage", _)
        handle_record("Experience", (stats.max_xp, stats.max_xp_ship_id))
        _ = (stats.max_frags_battle, stats.max_frags_ship_id)
        handle_record("Kills", _)
        _ = (stats.max_total_agro, stats.max_total_agro_ship_id)
        handle_record("Potential Damage", _)
        _ = (stats.max_damage_scouting, stats.max_scouting_damage_ship_id)
        handle_record("Spotting Damage", _)
        _ = (stats.max_ships_spotted, stats.max_ships_spotted_ship_id)
        handle_record("Ships Spotted", _)
        _ = (stats.max_planes_killed, stats.max_planes_killed_ship_id)
        handle_record("Planes Killed", _)

        embed.add_field(name="Records", value="\n".join(records))

        # Operations specific stats.
        if stats.wins_by_tasks:
            star1, star2 = r"\⭐", r"\★"

            stars: list[str] = []
            for k, val in stats.wins_by_tasks.items():
                _ = f"{k * star1} + {(5 - k) * star2}: {val}"
                stars.append(_)
            embed.add_field(name="Star Breakdown", value="\n".join(stars))

        embed.description = "\n".join(desc)
        return await interaction.response.edit_message(embed=embed, view=self)


class WowsStats(commands.Cog):
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
        interaction: Interaction,
        region: api.region_transform,
        player: api.player_transform,
        mode: Optional[api.mode_transform],
        division: Optional[discord.app_commands.Range[int, 0, 3]],
        ship: Optional[api.ship_transform] = None,
    ) -> None:
        """Search for a player's Stats"""
        del region  # Shut up linter.
        view = PlayerView(interaction.user, player, ship)
        if mode is None:
            mode = next(i for i in self.bot.modes if i.tag == "PVP")
        division = 0 if division is None else division
        await view.push_stats(interaction, mode, div_size=division)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(WowsStats(bot))
