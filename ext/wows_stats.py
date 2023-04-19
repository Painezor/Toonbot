"""Private world of warships related commands"""
from __future__ import annotations

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
        mode: api.GameMode,
        ship: Optional[api.warships.Ship] = None,
        div_size: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(interaction.user, **kwargs)

        # Passed
        self.player: api.PartialPlayer = player
        self.ship: Optional[api.warships.Ship] = ship
        self.mode: api.GameMode = mode
        self.div_size: int = div_size

        # Fetched
        self.api_stats: Optional[api.PlayerStats] = None

        # Button Handling.
        if player.clan is None:
            self.remove_item(self.clan)
        else:
            self.clan.label = f"[{player.clan.tag}]"

        logger.info(player.__dict__)

        _ = player.wows_numbers
        logger.info(_)
        self.add_item(discord.ui.Button(url=_, label="WoWs Numbers", row=0))
        _ = player.community_link
        logger.info(_)
        self.add_item(discord.ui.Button(url=_, label="Profile Page", row=0))
        self.refresh_dropdown(interaction)

    def refresh_dropdown(self, interaction: Interaction) -> None:
        """Repopulate the dropdown's options"""
        opts: list[discord.SelectOption] = []
        for i in interaction.client.modes:
            if i == self.mode:
                continue

            if i.tag == "CLAN" and not self.player.clan:
                continue

            opt = discord.SelectOption(label=i.name, value=i.tag)
            opt.description = i.description[:100]
            try:
                opt.emoji = {
                    "BRAWL": api.BRAWL_EMOJI,
                    "CLAN": api.CLAN_EMOJI,
                    "COOPERATIVE": api.COOP_EMOJI,
                    "EVENT": api.EVENT_EMOJI,
                    "PVE": api.SCENARIO_EMOJI,
                    "PVE_PREMADE": api.SCENARIO_HARD_EMOJI,
                    "PVP": api.PVP_EMOJI,
                    "RANKED": api.RANKED_EMOJI,
                }[i.tag]
            except KeyError:
                logger.error("Dropdown Missing emoji for %s", i.tag)
            opts.append(opt)

        self.dropdown.options = opts

    @discord.ui.select(placeholder="Change Mode", row=2)
    async def dropdown(
        self, interaction: Interaction, sel: discord.ui.Select[PlayerView]
    ) -> None:
        """Dropdown allowing the user to change game mode selection"""
        _ = interaction.client.modes
        self.mode = next(i for i in _ if i.tag in sel.values)
        self.refresh_dropdown(interaction)
        embed = await self.parse_stats(interaction)
        await interaction.response.edit_message(view=self, embed=embed)

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
        self.div_size = 3
        embed = await self.parse_stats(interaction)
        await interaction.response.edit_message(view=self, embed=embed)

    @discord.ui.button(row=0)
    async def clan(self, interaction: Interaction, _) -> None:
        """Button to go to the player's clan"""
        assert self.player.clan is not None
        clan = await self.player.clan.fetch_details()
        view = ClanView(interaction.user, clan, parent=self)
        embed = await view.generate_overview(interaction)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

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

        self.refresh_dropdown(interaction)
        btns = [self.overall, self.solo_stats, self.duo_stats, self.trio_stats]
        if self.mode.tag in ["PVP", "PVE"]:
            if self.overall not in self.children:
                for i in btns:
                    self.add_item(i)
        else:
            if self.overall in self.children:
                for i in btns:
                    self.remove_item(i)

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
        win = format(wins, ",")
        lose = format(loss, ",")
        draws = f"/ {format(draws, ',')} D " if draws else ""
        rest = f"({format(played, ',')} Battles - {win} W {draws}/ {lose} L)"
        desc.append(f"**Win Rate**: {win_rate}% {rest}")
        sv_rt = round(survived / played * 100, 2)
        s_tot = format(survived, ",")
        txt = f"**Survival Rate (Overall)**: {sv_rt}% ({s_tot} Battles)"
        desc.append(txt)

        if wins:
            swr = round(suv_wins / wins * 100, 2)
            tot_w = format(suv_wins, ",")
            desc.append(f"**Survival Rate (Wins)**: {swr}% ({tot_w} Battles)")

        desc.append("\n**Statistics**: Average (Total)")
        ships = interaction.client.ships

        def add(
            label: str,
            rnd: Optional[int],
            val: Optional[int],
            games: int,
            record: Optional[int],
            ship_id: Optional[int],
        ) -> None:
            """Add rows to the fields"""
            if not val:
                return

            _ = f"**{label}**: "
            _ += f'{format(round(val / games, rnd), ",")}'
            _ += f" ({format(round(val), ',')})\n"

            if record:
                ship = next((i for i in ships if i.ship_id == ship_id), None)
                if ship is None:
                    shp = ""
                else:
                    emote = ship.emoji
                    flag = ship.nation.flag
                    shp = f"{flag} {emote} {ship.name}"
                _ += f"┗ {shp}: {format(round(record, rnd), ',')}\n"
            desc.append(_)

        top, _ = stats.max_damage_dealt, stats.max_damage_dealt_ship_id
        add("Damage", None, stats.damage_dealt, played, top, _)

        top, _ = stats.max_frags_battle, stats.max_frags_ship_id
        add("Kills", 2, stats.frags, played, top, _)

        add("XP", None, stats.xp, played, stats.max_xp, stats.max_xp_ship_id)

        top, _ = stats.max_total_agro, stats.max_total_agro_ship_id
        add("Potential", None, stats.potential_damage, played, top, _)

        top, _ = stats.max_damage_scouting, stats.max_scouting_damage_ship_id
        add("Spotting", None, stats.damage_scouting, played, top, _)

        top, _ = stats.max_ships_spotted, stats.max_ships_spotted_ship_id
        add("Ships Spotted", 2, stats.ships_spotted, played, top, _)

        top, _ = stats.max_planes_killed, stats.max_planes_killed_ship_id
        add("Planes Killed", 2, stats.planes_killed, played, top, _)

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


class WowsStats(commands.Cog):
    """World of Warships related commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

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
        div_size = 0 if division is None else division
        if mode is None:
            mode = next(i for i in self.bot.modes if i.tag == "PVP")
        view = PlayerView(interaction, player, mode, ship, div_size)
        embed = await view.parse_stats(interaction)
        await interaction.response.send_message(view=view, embed=embed)
        view.message = await interaction.original_response()


async def setup(bot: PBot) -> None:
    """Load the Warships Cog into the bot"""
    await bot.add_cog(WowsStats(bot))
