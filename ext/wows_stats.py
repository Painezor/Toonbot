"""Private world of warships related commands"""
from __future__ import annotations

import importlib
import logging
from typing import Any, TYPE_CHECKING, TypeAlias, Optional  # , Literal

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

# REGION = Literal["eu", "na", "sea"]

# TODO: Calculation of player's PR
# https://wows-numbers.com/personal/rating


class PlayerView(view_utils.BaseView):
    """A View representing a World of Warships player"""

    def __init__(
        self,
        interaction: Interaction,
        player: api.PartialPlayer,
        ship: Optional[api.warships.Ship] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(interaction.user, **kwargs)

        # Passed
        self.player: api.PartialPlayer = player
        self.ship: Optional[api.warships.Ship] = ship

        # Fetched
        self.api_stats: Optional[api.PlayerStats] = None

        if player.clan is None:
            self.remove_item(self.clan)
        else:
            self.clan.label = f"[{player.clan.tag}]"

        self.mode: api.GameMode
        self.div_size: int

        _ = self.player.wows_numbers
        self.add_item(discord.ui.Button(url=_, label="WoWs Numbers", row=4))
        _ = self.player.community_link
        self.add_item(discord.ui.Button(url=_, label="Profile Page", row=4))

        opts: list[discord.SelectOption] = []
        for i in interaction.client.modes:
            opt = discord.SelectOption(name=i.name, value=i.tag)
            opt.emoji = {"PVP": api.PVP_EMOJI}

            opts.append(discord.SelectOption(name=))

        self.dropdown.options = opts

    @discord.ui.select(placeholder="Change Mode", row=2)
    async def dropdown(
        self, interaction: Interaction, sel: discord.ui.Select[PlayerView]
    ) -> None:
        """Dropdown allowing the user to change game mode selection"""
        _ = inteaction.client.modes 
        mode = next(i for i in _ if i.tag in sel.values)



    @discord.ui.button(label="Overall", row=1)
    async def overall(
        self, interaction: Interaction, _: discord.ui.Button[PlayerView]
    ) -> None:
        """Get Solo Stats for the game mode"""
        self.div_size = 0
        embed = await self.parse_stats(interaction)
        await interaction.response.edit_message(view=self, embed=embed)

    @discord.ui.button(label="Solo", row=1)
    async def solo_stats(
        self, interaction: Interaction, _: discord.ui.Button[PlayerView]
    ) -> None:
        """Get Solo Stats for the game mode"""
        self.div_size = 1
        embed = await self.parse_stats(interaction)
        await interaction.response.edit_message(view=self, embed=embed)

    @discord.ui.button(label="Div 2", row=1)
    async def duo_stats(
        self, interaction: Interaction, _: discord.ui.Button[PlayerView]
    ) -> None:
        """Get 2 man div Stats for the game mode"""
        self.div_size = 2
        embed = await self.parse_stats(interaction)
        await interaction.response.edit_message(view=self, embed=embed)

    @discord.ui.button(label="Div 3", row=1)
    async def trio_stats(
        self, interaction: Interaction, _: discord.ui.Button[PlayerView]
    ) -> None:
        """Get 3 man div stats for the game mode"""
        self.dive_size = 3
        embed = await self.parse_stats(interaction)
        await interaction.response.edit_message(view=self, embed=embed)

    @discord.ui.button(row=4)
    async def clan(self, interaction: Interaction, _) -> None:
        """Button to go to the player's clan"""
        assert self.player.clan is not None
        clan = await self.player.clan.fetch_details()
        view = ClanView(interaction.user, clan, parent=self)
        embed = await view.generate_overview(interaction)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    def add_div_buttons(self) -> None:
        """Bulk add the div buttons."""
        if self.overall in self.children:
            return

        btns = [self.overall, self.solo_stats, self.duo_stats, self.trio_stats]
        for i in btns:
            self.add_item(i)

    def remove_div_buttons(self) -> None:
        """Bulk remove the div buttons"""
        if self.overall not in self.children:
            return
        btns = [self.overall, self.solo_stats, self.duo_stats, self.trio_stats]
        for i in btns:
            self.remove_item(i)

    async def parse_stats(
        self,
        interaction: Interaction,
    ) -> discord.Embed:
        """Convert the user's stats into an embed"""
        embed = discord.Embed()
        embed.set_author(name=self.player.nickname, icon_url=self.mode.image)
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
        }[self.mode.tag][self.div_size]

        if self.mode.tag in ["PVP", "PVE"]:
            self.add_div_buttons()
        else:
            self.remove_div_buttons()

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
            return embed

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
        return embed

    async def push_stats(self, interaction: Interaction) -> None:
        """Send Stats Embed to View"""
        # Can be gotten via normal API

        # Handle Buttons
        # Row 1: Change Div Size
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
