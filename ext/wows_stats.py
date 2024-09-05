"""Private world of warships related commands"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeAlias

import discord
from discord.ui import Button, Select
from discord.ext import commands

from ext import wows_api as api
from ext.clans import ClanView
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

logger = logging.getLogger("warships")

# REGION = Literal["eu", "na", "sea"]

# TODO: Calculation of player's PR
# https://wows-numbers.com/personal/rating

API_MISSING_MODES = ["BRAWL", "CLAN"]


class StatsView(view_utils.BaseView):
    """A View representing a World of Warships player"""

    def __init__(
        self,
        interaction: Interaction,
        player: api.PartialPlayer,
        mode: api.GameMode,
        ship: api.warships.Ship | None = None,
        div_size: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(interaction.user, **kwargs)

        # Passed
        self.player: api.PartialPlayer = player
        self.ship: api.warships.Ship | None = ship
        self.mode: api.GameMode = mode
        self.div_size: int = div_size

        # Fetched
        self.api_stats: api.PlayerStats | api.PlayerShipStats | None = None

    def handle_buttons(self, interaction: Interaction) -> None:
        """Repopulate the dropdown's options"""
        self.clear_items()

        _ = self.player.wows_numbers
        self.add_item(Button(url=_, label="WoWs Numbers", row=0))
        _ = self.player.community_link
        self.add_item(Button(url=_, label="Profile Page", row=0))
        self.handle_buttons(interaction)

        if self.player.clan:
            self.clan.label = f"[{self.player.clan.tag}]"
            self.add_item(self.clan)

        if self.mode.tag in ["PVP", "PVE"]:
            self.add_item(self.overall)
            self.add_item(self.solo_stats)
            self.add_item(self.duo_stats)
            self.add_item(self.trio_stats)
            self.add_item(self.weaponry)

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

            if i.tag in API_MISSING_MODES:
                continue
            opts.append(opt)

        self.dropdown.options = opts

    @discord.ui.select(placeholder="Change Mode", row=2)
    async def dropdown(self, interaction: Interaction, sel: Select) -> None:
        """Dropdown allowing the user to change game mode selection"""
        _ = interaction.client.modes
        self.mode = next(i for i in _ if i.tag in sel.values)
        self.handle_buttons(interaction)
        self.div_size = 0
        await self.totals.callback(interaction)

    @discord.ui.button(row=0)
    async def clan(
        self, interaction: Interaction, _: Button[StatsView]
    ) -> None:
        """Button to go to the player's clan"""
        assert self.player.clan is not None
        clan = await self.player.clan.fetch_details()
        view = ClanView(interaction.user, clan, parent=self)
        embed = await view.generate_overview(interaction)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @discord.ui.button(label="Overall", row=1)
    async def overall(
        self, interaction: Interaction, _: Button[StatsView]
    ) -> None:
        """Get Solo Stats for the game mode"""
        self.div_size = 0
        await self.totals.callback(interaction)

    @discord.ui.button(label="Solo", row=1)
    async def solo_stats(
        self, interaction: Interaction, _: Button[StatsView]
    ) -> None:
        """Get Solo Stats for the game mode"""
        self.div_size = 1
        await self.totals.callback(interaction)

    @discord.ui.button(label="Div 2", row=1)
    async def duo_stats(
        self, interaction: Interaction, _: Button[StatsView]
    ) -> None:
        """Get 2 man div Stats for the game mode"""
        self.div_size = 2
        await self.totals.callback(interaction)

    @discord.ui.button(label="Div 3", row=1)
    async def trio_stats(
        self, interaction: Interaction, _: Button[StatsView]
    ) -> None:
        """Get 3 man div stats for the game mode"""
        self.div_size = 3
        await self.totals.callback(interaction)

    def base_embed(self) -> discord.Embed:
        """Generic Embed with Mode Info"""
        num = {0: "Overall", 1: "Solo", 2: "Div 2", 3: "Div 3"}[self.div_size]
        embed = discord.Embed(title=f"{self.mode.tag.title()} ({num})")
        embed.set_author(name=self.player.nickname, icon_url=self.mode.image)
        return embed

    async def get_mode_stats(self) -> api.ModeBattleStats | None:
        """Handle parsing of stats by mode & div size"""
        if self.ship is None:
            if self.api_stats is None:
                p_stats = await api.fetch_player_stats([self.player])
                self.api_stats = p_stats[0]
            assert isinstance(self.api_stats, api.PlayerStats)
            statistics = self.api_stats.statistics
        else:
            if self.api_stats is None:
                dct = await api.fetch_player_ship_stats(self.player, self.ship)
                self.api_stats = dct[str(self.ship.ship_id)]
            assert isinstance(self.api_stats, api.PlayerShipStats)
            statistics = self.api_stats
        dct = {
            "BRAWL": None,
            "CLAN": None,
            "COOPERATIVE": {
                0: statistics.pve,
                1: statistics.pve_solo,
                2: statistics.pve_div2,
                3: statistics.pve_div3,
            },
            "EVENT": None,
            "PVP": {
                0: statistics.pvp,
                1: statistics.pvp_solo,
                2: statistics.pvp_div2,
                3: statistics.pvp_div3,
            },
            "PVE": statistics.oper_solo,
            "PVE_PREMADE": statistics.oper_div_hard,
        }[self.mode.tag]

        if self.mode.tag == "PVE" and self.div_size != 1:
            return statistics.oper_div
        else:
            return dct[self.div_size] if isinstance(dct, dict) else dct

    @discord.ui.button(label="Armaments")
    async def weaponry(self, interaction: Interaction, _: Button[StatsView]):
        """Click this, view weaponry breakdown"""
        stats = await self.get_mode_stats()
        embed = self.base_embed()
        self.handle_buttons(interaction)
        self.add_item(self.weaponry)
        self.remove_item(self.totals)

        embed.title = f"{embed.title} Armament Breakdown"

        if stats is None:
            embed.description = "No Player Stats found in API for this mode"
            await interaction.response.edit_message(embed=embed, view=self)
            return

        for k, val in stats:
            if not isinstance(val, api.ModeArmamentStats):
                continue

            out = ""
            if val.hits and val.shots:
                accr = round(val.hits / val.shots, 2)
                hits = format(val.hits, ",")
                shots = format(val.shots, ",")
                out += f"**Accuracy**: {accr}% ({hits} / {shots})\n"
            out += f"**Kills**: {val.frags}\n"

            ships = interaction.client.ships
            ship_id = val.max_frags_ship_id
            record = val.max_frags_battle
            if self.ship is None and record:
                ship = next((i for i in ships if i.ship_id == ship_id), None)
                if ship is None:
                    shp = ""
                else:
                    emote = ship.emoji
                    flag = ship.nation.flag
                    shp = f"{flag} {emote} {ship.name}"
                out += f"┗ {shp}: {round(record, 2), ','}"

            embed.add_field(name=k, value=out)
        self.remove_item(self.weaponry)
        self.add_item(self.overall)

    @discord.ui.button(label="Totals")
    async def totals(
        self, interaction: Interaction, btn: Button[StatsView]
    ) -> None:
        """Convert the user's stats into an embed"""
        embed = self.base_embed()
        stats = await self.get_mode_stats()
        self.handle_buttons(interaction)
        self.add_item(self.weaponry)
        self.remove_item(self.totals)

        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message

        if stats is None:
            embed.description = "No Player Stats found in API for this mode"
            await edit(view=self, embed=embed)
            return

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
            await edit(view=self, embed=embed)
            return

        win_rate = round(wins / played * 100, 2)
        win = format(wins, ",")
        lose = format(loss, ",")
        draws = f"/ {format(draws, ',')} D " if draws else ""
        rest = f"({format(played, ',')} G - {win} W {draws}/ {lose} L)"
        desc.append(f"**Win Rate**: {win_rate}% {rest}")
        sv_rt = round(survived / played * 100, 2)
        s_tot = format(survived, ",")
        txt = f"**Survival Rate**: {sv_rt}% ({s_tot} G)"
        desc.append(txt)

        if wins:
            swr = round(suv_wins / wins * 100, 2)
            tot_w = format(suv_wins, ",")
            desc.append(f"**Survival Rate (Wins)**: {swr}% ({tot_w} G)")

        desc.append("\n**Statistics**: Average (Total)")
        ships = interaction.client.ships

        def add(
            label: str,
            rnd: int | None,
            val: int | None,
            games: int,
            record: int | None,
            ship_id: int | None,
        ) -> None:
            """Add rows to the fields"""
            if not val:
                return

            _ = f"**{label}**: "
            _ += f'{format(round(val / games, rnd), ",")}'  # Average
            _ += f" ({format(round(val), ',')})\n"  # Total

            if record:
                ship = next((i for i in ships if i.ship_id == ship_id), None)
                if ship is None:
                    shp = ""
                else:
                    emote = ship.emoji
                    flag = ship.nation.flag
                    shp = f"{flag} {emote} {ship.name}"
                _ += f"┗ {shp}: {format(round(record, rnd), ',')}"
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
            star1, star2 = r"\★", r"\“☆"

            stars: list[str] = []
            for k, val in stats.wins_by_tasks.items():
                _ = f"{k * star1} {(5 - k) * star2}: {val}"
                stars.append(_)
            embed.add_field(name="Star Breakdown", value="\n".join(stars))

        embed.description = "\n".join(desc)
        await edit(view=self, embed=embed)


class WowsStats(commands.Cog):
    """World of Warships related commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
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
        ship: api.ship_transform | None = None,
        mode: api.mode_transform | None = None,
        division: discord.app_commands.Range[int, 0, 3] | None = None,
    ) -> None:
        """Search for a player's Stats"""
        del region  # Shut up linter.
        await interaction.response.defer(thinking=True)
        div_size = 0 if division is None else division
        if mode is None:
            mode = next(i for i in self.bot.modes if i.tag == "PVP")
        view = StatsView(interaction, player, mode, ship, div_size)
        await view.totals.callback(interaction)
        view.message = await interaction.original_response()


async def setup(bot: PBot) -> None:
    """Load the Warships Cog into the bot"""
    await bot.add_cog(WowsStats(bot))
