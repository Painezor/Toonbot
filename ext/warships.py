"""Private world of warships related commands"""
from __future__ import annotations

import logging
from copy import deepcopy
import datetime
from typing import Literal, Optional
import typing

import discord

from discord.ext import commands
import flatten_dict

from ext.painezbot_utils.clan import ClanBuilding, League, Clan
from ext.painezbot_utils.player import Region, GameMode, Player
from ext.painezbot_utils.ship import Nation, ShipType, Ship

from ext.utils import view_utils, timed_events, embed_utils

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
INFO = API_PATH + "encyclopedia/info/"
CLAN = API_PATH + "clans/glossary/"
CLAN_SEARCH = "https://api.worldofwarships.eu/wows/clans/list/"
MODES = API_PATH + "encyclopedia/battletypes/"
SHIPS = API_PATH + "encyclopedia/ships/"
PLAYERS = API_PATH + "account/list/"

REGION = Literal["eu", "na", "cis", "sea"]

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


class Leaderboard(view_utils.BaseView):
    """Leaderboard View with dropdowns."""

    def __init__(
        self, interaction: discord.Interaction[PBot], clans: list[Clan]
    ) -> None:
        super().__init__(interaction)

        self.clans: list[Clan] = clans  # Rank, Clan

    async def update(self) -> discord.InteractionMessage:
        """Push the latest version of the view to the user"""
        self.clear_items()

        e = discord.Embed(colour=discord.Colour.purple())
        e.title = f"Clan Battle Season {self.clans[0].season_number} Ranking"
        e.set_thumbnail(url=League.HURRICANE.thumbnail)

        rows = []
        opts = []
        for num, clan in enumerate(self.clans):
            r = "⛔" if clan.is_clan_disbanded else str(clan.public_rating)
            rank = f"#{clan.rank}."
            region = clan.region

            lbt = clan.last_battle_at.relative
            rows.append(
                f"{rank} {region.emote} **[{clan.tag}]** {clan.name}\n"
                f"`{r.rjust(4)}` {clan.battles_count} Battles, Last: {lbt}\n"
            )

            opt = SelectOption(
                label=f"{clan.tag} ({clan.region.name})",
                description=clan.name,
                emoji=clan.league.emote,
                value=str(num),
            )

            v = clan.view(
                self.interaction, parent=(self, "Back to Leaderboard")
            )
            opts.append((opt, {}, v.from_dropdown))

        self.pages = embed_utils.rows_to_embeds(e, rows)

        self.add_page_buttons()
        self.add_item(FuncDropdown(options=opts, placeholder="View Clan Info"))
        return await self.bot.reply(
            self.interaction, embed=self.pages[self.index], view=self
        )


class PlayerView(view_utils.BaseView):
    """A View representing a World of Warships player"""

    bot: PBot

    def __init__(
        self,
        interaction: discord.Interaction[PBot],
        player: Player,
        mode: GameMode,
        div_size: int,
        ship: Optional[Ship] = None,
        **kwargs,
    ) -> None:
        super().__init__(interaction, **kwargs)

        # Passed
        self.player: Player = player
        self.div_size: int = div_size
        self.mode: GameMode = mode
        self.ship: Optional[Ship] = ship

        # Used
        self.cb_season: Optional[int] = None

    async def base_embed(self) -> discord.Embed:
        """Base Embed used for all sub embeds."""
        e = discord.Embed()

        p = self.player
        if self.player.clan is None:
            await self.player.get_clan_info()

        if p.clan:
            e.set_author(name=f"[{p.clan.tag}] {p.nickname} ({p.region.name})")
        else:
            e.set_author(name=f"{p.nickname} ({p.region.name})")

        e.set_thumbnail(url=self.mode.image)

        if self.player.hidden_profile:
            e.set_footer(text="This player has hidden their stats.")
        return e

    @staticmethod
    def sum_stats(dicts: list[dict]) -> dict:
        """Sum The Stats from multiple game modes."""
        output = {}

        dicts = [flatten_dict.flatten(d, reducer="dot") for d in dicts]

        for key in dicts[0].keys():
            if "ship_id" in key:
                pass
            elif "max" in key:
                ship_keys = SHIP_KEYS

                paired_keys = [
                    (n.get(key, 0), n.get(ship_keys[key]))
                    for n in dicts
                    if n.get(key, 0)
                ]
                filter_keys = filter(lambda x: x[1] is not None, paired_keys)
                try:
                    value = sorted(filter_keys, key=lambda x: x[0])[0]
                except IndexError:
                    value = (0, None)
                output.update({key: value[0], ship_keys[key]: value[1]})
            else:
                value = sum(
                    [
                        x
                        for x in [n.get(key, 0) for n in dicts]
                        if x is not None
                    ],
                    0,
                )
                output.update({key: value})
        output = flatten_dict.unflatten(output, splitter="dot")
        return output

    async def filter_stats(self) -> tuple[str, dict]:
        """Fetch the appropriate stats for the mode tag"""
        if self.ship not in self.player.statistics:
            await self.player.get_stats(self.ship)

        s = self.player.statistics[self.ship]
        match self.mode.tag, self.div_size:
            case "PVP", 1:
                return "Random Battles (Solo)", s["pvp_solo"]
            case "PVP", 2:
                return "Random Battles (2-person Division)", s["pvp_div2"]
            case "PVP", 3:
                return "Random Battles (3-person Division)", s["pvp_div3"]
            case "PVP", _:
                return "Random Battles (Overall)", s["pvp"]
            case "COOPERATIVE", 1:
                return "Co-op Battles (Solo)", s["pve_solo"]
            case "COOPERATIVE", 2:
                return "Co-op Battles (2-person Division)", s["pve_div2"]
            case "COOPERATIVE", 3:
                return "Co-op Battles (3-person Division)", s["pve_div3"]
            case "COOPERATIVE", _:
                return "Co-op Battles (Overall)", s["pve"]  # All
            case "RANKED", 1:
                return "Ranked Battles (Solo)", s["rank_solo"]
            case "RANKED", 2:
                return "Ranked Battles (2-Man Division)", s["rank_div2"]
            case "RANKED", 3:
                return "Ranked Battles (3-Man Division)", s["rank_div3"]
            case "RANKED", 0:  # Sum 3 Dicts.
                return "Ranked Battles (Overall)", self.sum_stats(
                    [s["rank_solo"], s["rank_div2"], s["rank_div3"]]
                )
            case "PVE", 0:
                return "Operations (Overall)", self.sum_stats(
                    [s["oper_solo"], s["oper_div"]]
                )
            case "PVE", 1:
                return "Operations (Solo)", s["oper_solo"]
            case "PVE", _:
                return "Operations (Pre-made)", s["oper_div"]
            case "PVE_PREMADE", _:
                return "Operations (Hard Pre-Made)", s["oper_div_hard"]
            case _:
                return (
                    f"Missing info for {self.mode.tag}, {self.div_size}",
                    s["pvp"],
                )

    async def clan_battles(self, season: int) -> discord.InteractionMessage:
        """Attempt to fetch player's Clan Battles data."""

        if self.player.clan is None:
            raise AttributeError

        if season not in self.player.clan_battle_stats:
            await self.player.clan.get_member_clan_battle_stats(season)

        stats = self.player.clan_battle_stats[season]

        logging.info(f"Found clan battle stats {stats}")

        e = await self.base_embed()
        e.title = f"Clan Battles (Season {self.cb_season})"
        wr = round(stats.win_rate, 2)
        n = stats.battles
        avg = format(round(stats.average_damage, 0), ",")
        kll = round(stats.average_kills, 2)
        e.description = (
            f"**Win Rate**: {wr}% ({n} battles played)\n"
            f"**Average Damage**: {avg}\n"
            f"**Average Kills**: {kll}\n"
        )
        self._disabled = self.clan_battles
        return await self.update(e)

    async def weapons(self) -> discord.InteractionMessage:
        """Get the Embed for a player's weapons breakdown"""
        e = await self.base_embed()
        e.title, p_stats = await self.filter_stats()

        if mb := p_stats.pop("main_battery", {}):
            mb_kills = mb.pop("frags")
            mb_ship = self.bot.get_ship(mb.pop("max_frags_ship_id"))
            mb_max = mb.pop("max_frags_battle")
            mb_shots = mb.pop("shots")
            mb_hits = mb.pop("hits")
            mb_acc = round(mb_hits / mb_shots * 100, 2)

            s = mb_ship.name
            h = format(mb_hits, ",")
            sh = format(mb_shots, ",")
            mb = (
                f"Kills: {format(mb_kills, ',')} (Max: {mb_max} - {s})\n"
                f"Accuracy: {mb_acc}% ({h} hits / {sh} shots)"
            )
            e.add_field(name="Main Battery", value=mb, inline=False)

        # Secondary Battery
        if sb := p_stats.pop("second_battery", {}):
            sb_kills = sb.pop("frags", 0)
            sb_ship = self.bot.get_ship(sb.pop("max_frags_ship_id", None))
            sb_max = sb.pop("max_frags_battle", 0)
            sb_shots = sb.pop("shots", 0)
            sb_hits = sb.pop("hits", 0)
            sb_acc = round(sb_hits / sb_shots * 100, 2)

            n = sb_ship.name if sb_ship else "?"
            h = format(sb_hits, ",")
            s = format(sb_shots, ",")
            sb = (
                f"Kills: {format(sb_kills, ',')} (Max: {sb_max} - {n})\n"
                f"Accuracy: {sb_acc}% ({h} hits / {s} shots)"
            )
            e.add_field(name="Secondary Battery", value=sb, inline=False)

        # Torpedoes
        trp = p_stats.pop("torpedoes", None)
        if trp is not None:
            trp_kills = trp.pop("frags")
            trp_ship = self.bot.get_ship(trp.pop("max_frags_ship_id", None))
            trp_max = trp.pop("max_frags_battle", 0)
            trp_shots = trp.pop("shots", 0)
            trp_hits = trp.pop("hits", 0)
            trp_acc = round(trp_hits / trp_shots * 100, 2)

            n = trp_ship.name
            h = format(trp_hits, ",")
            s = format(trp_shots, ",")

            trp = (
                f"Kills: {format(trp_kills, ',')} (Max: {trp_max} - {n})\n"
                f"Accuracy: {trp_acc}% ({h} hit / {s} launched)"
            )
            e.add_field(name="Torpedoes", value=trp, inline=False)

        # Ramming
        if ram := p_stats.pop("ramming", {}):
            out = f"Kills: {ram.pop('frags', 0)}"
            if r_ship := self.bot.get_ship(ram.pop("max_frags_ship_id", None)):
                kills = ram.pop("max_frags_battle", 0)
                out += f" (Max: {kills} - {r_ship.name})\n"
            e.add_field(name="Ramming", value=out)

        # Aircraft
        if cv := p_stats.pop("aircraft", {}):
            out = f"Kills: {cv.pop('frags')}"
            if cv_ship := self.bot.get_ship(cv.pop("max_frags_ship_id", None)):
                kills = cv.pop("max_frags_battle")
                out += f" (Max: {kills} - {cv_ship.name})\n"
            e.add_field(name="Aircraft", value=out)

        # Build the second embed.
        desc = []

        try:
            cap_solo = p_stats.pop("control_captured_points")
            cap_team = p_stats.pop("team_capture_points")
            cap_rate = round(cap_solo / cap_team * 100, 2)
            solo = format(cap_solo, ",")
            team = format(cap_team, ",")
            desc.append(f"Capture Contribution: {cap_rate}% ({solo} / {team})")
        except (KeyError, ZeroDivisionError):
            pass

        try:
            ds = p_stats.pop("control_dropped_points", 0)
            def_solo = format(ds, ", ")
            ts = p_stats.pop("team_dropped_capture_points", 0)
            team = format(ts, ", ")
            rate = round(ds / ts * 100, 2)
            desc.append(f"Defence Contribution: {rate}% ({def_solo} / {team})")
        except (KeyError, ZeroDivisionError):
            pass

        # Capture Points & Defends, Distance Travelled
        e.description = "\n".join(desc)
        self._disabled = self.weapons
        return await self.update(e)

    async def overview(self) -> discord.InteractionMessage:
        """Push an Overview of the player to the View"""
        desc = []  # Build The description piecemeal then join at the very end.
        e = await self.base_embed()
        e.title, p_stats = await self.filter_stats()

        if (updated := self.player.stats_updated_at) is not None:
            desc.append(f"**Stats updated**: {updated.relative}\n")

        if (created := self.player.created_at) is not None:
            desc.append(f"**Account Created**: {created.relative}")

        if (lbt := self.player.last_battle_time) is not None:
            desc.append(f"**Last Battle**: {lbt.relative}")

        if self.player.logout_at is not None:
            desc.append(f"**Last Logout**: {self.player.logout_at.relative}")

        # This is stored 1 level up.
        distance = self.player.statistics[None]["distance"]
        desc.append(f"**Total Distance Travelled**: {format(distance, ',')}km")

        if self.player.clan:
            clan = self.player.clan
            c_desc = []
            if clan.cb_rating is not None:
                c_desc.append(f"**Rating**: {clan.cb_rating}")

            if self.player.joined_clan_at:
                txt = self.player.joined_clan_at.relative
                c_desc.append(f"**Joined Date**: {txt}")

            if clan.old_name is not None:
                c_desc.append(
                    f"**Old Name**: [{clan.old_tag}] {clan.old_name}"
                )

            if clan.renamed_at:
                c_desc.append(f"**Renamed**: {clan.renamed_at.relative}")
            e.add_field(name=clan.title, value="\n".join(c_desc), inline=False)

        e.description = "\n".join(desc)
        self._disabled = self.overview
        return await self.update(embed=e)

    async def mode_stats(self, mode: GameMode, div_size: int = 0):
        """Get the player's stats for the specific game mode"""
        # Don't remove data from original player object.
        e = await self.base_embed()
        desc = []

        if mode.tag == "CLAN":
            return await self.clan_battles()

        e.title, p_stats = await self.filter_stats()

        p_stats = deepcopy(p_stats)
        # Overall Rates - Survival, WR, Wins, Loss, Draw
        survived = p_stats.pop("survived_battles", 0)
        suv_wins = p_stats.pop("survived_wins", 0)
        played = p_stats.pop("battles", 0)
        wins = p_stats.pop("wins", 0)
        loss = p_stats.pop("losses", 0)
        draws = p_stats.pop("draws", 0)

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

        # Averages - Kills, Damage, Spotting, Potential
        if mode.tag == "PVE":
            x_avg = format(round(tot_xp / played), ",")
            x_tot = format(tot_xp, ",")
            desc.append(f"**Average XP**: {x_avg}\n" f"**Total XP**: {x_tot}")
        else:
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
                s_kills = self.bot.get_ship(
                    p_stats.pop("max_frags_ship_id", None)
                )
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
        self._disabled = None
        return await self.update(embed=e)

    async def handle_buttons(self, current_function: typing.Callable) -> None:
        row_0: list[view_utils.Funcable] = []

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
            cln.emoji = self.player.clan.league.emote
            row_0.append(cln)

        if self.mode.tag != "Clan":
            # Weapons Button
            btn = view_utils.Funcable("Armaments", self.weapons)
            btn.disabled = current_function == self.weapons
            btn.emoji = Artillery.emoji
            row_0.append(btn)

        self.add_function_row(row_0)

    async def update(self, embed: discord.Embed) -> discord.InteractionMessage:
        """Send the latest version of the embed to view"""
        self.clear_items()

        f = self.mode_stats
        options: list[view_utils.Funcable] = []
        for num, i in enumerate(
            [
                i
                for i in self.bot.modes
                if i.tag not in ["EVENT", "BRAWL", "PVE_PREMADE"]
            ]
        ):
            # We can't fetch CB data without a clan.
            if i.tag == "CLAN" and not self.player.clan:
                continue

            opt = SelectOption(
                label=f"{i.name} ({i.tag})",
                description=i.description,
                emoji=i.emoji,
                value=num,
            )
            options.append((opt, {"mode": i}, f))
        self.add_item(
            FuncDropdown(placeholder="Change Game Mode", options=options)
        )

        buttons = []
        ds = self.div_size
        match self.mode.tag:
            # Event and Brawl aren't in API.
            case "BRAWL" | "EVENT":
                pass
            # Pre-made & Clan don't have div sizes.
            case "CLAN":
                opts = []

                if (
                    self.player.clan is not None
                    and self.player.clan.season_number is None
                ):
                    await self.player.clan.get_data()

                if self.player.clan:
                    sn = self.player.clan.season_number
                else:
                    sn = None

                dd = []
                if sn is not None:
                    func = self.clan_battles
                    for x in range(sn):

                        item = view_utils.Funcable(f"Season {x}", func)
                        item.emoji = self.mode.emoji
                        item.args = [x]
                        dd.append(item)
                self.add_function_row(dd, 1, "Change Season")

            case "PVE" | "PVE_PREMADE":
                easy = next(i for i in self.bot.modes if i.tag == "PVE")
                hard = next(
                    i for i in self.bot.modes if i.tag == "PVE_PREMADE"
                )
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"div_size": 0, "mode": easy},
                        label="Pre-Made",
                        row=1,
                        emoji=easy.emoji,
                        disabled=ds == 0,
                    )
                )
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"div_size": 1, "mode": easy},
                        label="Solo",
                        row=1,
                        emoji=easy.emoji,
                        disabled=ds == 1,
                    )
                )
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"mode": hard},
                        label="Hard Mode",
                        row=1,
                        emoji=hard.emoji,
                        disabled=ds == 1,
                    )
                )
            case _:
                emoji = self.mode.emoji
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"div_size": 0},
                        label="Overall",
                        row=1,
                        disabled=ds == 0,
                        emoji=emoji,
                    )
                )
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"div_size": 1},
                        label="Solo",
                        row=1,
                        disabled=ds == 1,
                        emoji=emoji,
                    )
                )
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"div_size": 2},
                        label="Division (2)",
                        row=1,
                        disabled=ds == 2,
                        emoji=emoji,
                    )
                )
                self.add_item(
                    FuncButton(
                        function=f,
                        kwargs={"div_size": 3},
                        label="Division (3)",
                        row=1,
                        disabled=ds == 3,
                        emoji=emoji,
                    )
                )

        r = self.interaction.edit_original_response
        return await r(embed=embed, view=self)


class ClanView(view_utils.BaseView):
    """A View representing a World of Warships Clan"""

    bot: PBot

    def __init__(
        self, interaction: discord.Interaction[PBot], clan: Clan, **kwargs
    ) -> None:
        super().__init__(interaction, **kwargs)
        self.clan: Clan = clan

    async def overview(self) -> discord.InteractionMessage:
        """Get General overview of the clan"""
        e = self.clan.embed()

        c = self.clan

        desc = []
        if c.updated_at is not None:
            desc.append(f"**Information updated**: {c.updated_at.relative}\n")

        if self.clan.leader_name:
            desc.append(f"**Leader**: {c.leader_name}")

        if self.clan.created_at:
            cr = self.clan.creator_name

            ts = timed_events.Timestamp(c.created_at).relative
            desc.append(f"**Founder**: {cr} ({ts})")

        if self.clan.renamed_at:
            ts = timed_events.Timestamp(c.renamed_at).relative
            desc.append(f"**Former name**: [{c.old_tag}] {c.old_name} ({ts})")

        if self.clan.season_number:
            title = f"Clan Battles Season {self.clan.season_number}"
            cb_desc = [
                f"**Current Rating**: {c.cb_rating} ({c.max_rating_name})"
            ]

            if self.clan.cb_rating != self.clan.max_cb_rating:
                cb_desc.append(f"**Highest Rating**: {c.max_cb_rating}")

            # Win Rate
            lbt = c.last_battle_at.relative
            cb_desc.append(f"**Last Battle**: {lbt}")
            wr = round(self.clan.wins_count / self.clan.battles_count * 100, 2)
            rest = f"{c.wins_count} / {c.battles_count}"
            cb_desc.append(f"**Win Rate**: {wr}% ({rest})")

            # Win streaks
            lws = self.clan.longest_winning_streak
            cws = c.current_winning_streak
            if cws:
                if cws == lws:
                    cb_desc.append(f"**Win Streak**: {cws}")
                else:
                    cb_desc.append(f"**Win Streak**: {cws} (Max: {lws})")
            elif self.clan.longest_winning_streak:
                cb_desc.append(f"**Longest Win Streak**: {lws}")
            e.add_field(name=title, value="\n".join(cb_desc))

        e.set_footer(text=f"{self.clan.region.name} Clan #{self.clan.clan_id}")
        e.description = "\n".join(desc)

        if self.clan.is_banned:
            e.add_field(
                name="Banned Clan",
                value="This clan is marked as 'banned'",
            )

        self._disabled = self.overview
        e.set_footer(text=self.clan.description)
        return await self.update(embed=e)

    async def members(self) -> discord.InteractionMessage:
        """Display an embed of the clan members"""
        self._disabled = self.members
        e = self.clan.embed
        e.title = f"Clan Members ({self.clan.members_count} Total)"

        members = sorted(self.clan.members, key=lambda x: x.nickname)
        members = [
            f"`🟢` {i.nickname}" if i.is_online else i.nickname
            for i in members
            if not i.is_banned
        ]

        e.description = discord.utils.escape_markdown(", ".join(members))

        if banned := [i for i in self.clan.members if i.is_banned]:
            e.add_field(name="Banned Members", value=", ".join(banned))

        # Clan Records:
        await self.clan.get_member_stats()

        mems = self.clan.members
        c_wr = round(sum(c.win_rate for c in mems) / len(members), 2)

        avg_dmg = round(sum(c.average_damage for c in mems) / len(mems))
        c_dmg = format(
            avg_dmg,
            ",",
        )

        avg_xp = round(sum(c.average_xp for c in mems) / len(mems), 2)
        c_xp = format(avg_xp, ",")

        c_kills = round(sum(c.average_kills for c in mems) / len(mems), 2)

        avg_games = round(sum(c.battles for c in mems) / len(mems))
        c_games = format(avg_games, ",")

        c_gpd = round(sum(c.battles_per_day for c in mems) / len(mems), 2)
        e.add_field(
            name="Clan Averages",
            value=f"**Win Rate**: {c_wr}%\n"
            f"**Average Damage**: {c_dmg}\n"
            f"**Average Kills**: {c_kills}\n"
            f"**Average XP**: {c_xp}\n"
            f"**Total Battles**: {c_games}\n"
            f"**Battles Per Day**: {c_gpd}",
        )

        m_d: Player = max(self.clan.members, key=lambda p: p.average_damage)
        max_xp: Player = max(self.clan.members, key=lambda p: p.average_xp)
        max_wr: Player = max(self.clan.members, key=lambda p: p.win_rate)
        max_games: Player = max(self.clan.members, key=lambda p: p.battles)
        m_p: Player = max(self.clan.members, key=lambda p: p.battles_per_day)
        m_a_k = max(self.clan.members, key=lambda p: p.max_avg_kills)

        e.add_field(
            name="Top Players",
            value=f"{round(max_wr.win_rate, 2)}% ({max_wr.nickname})\n"
            f'{format(round(m_d.average_damage), ",")} ({m_d.nickname})\n'
            f"{round(m_a_k.average_kills, 2)} ({m_a_k.nickname})\n"
            f'{format(round(max_xp.average_xp), ",")} ({max_xp.nickname})\n'
            f'{format(max_games.battles, ",")} ({max_games.nickname})\n'
            f"{round(m_p.battles_per_day, 2)} ({m_p.nickname})",
        )

        return await self.update(embed=e)

    async def history(self) -> discord.InteractionMessage:
        """Get a clan's Clan Battle History"""
        # https://clans.worldofwarships.eu/api/members/500140589/?battle_type=cvc&season=17
        # TODO: Clan Battle History
        self._disabled = self.history
        e = self.clan.embed()
        e.description = "```diff\n-Not Implemented Yet.```"
        return await self.update(embed=e)

    async def new_members(self) -> discord.InteractionMessage:
        """Get a list of the clan's newest members"""
        self._disabled = self.new_members
        e = self.clan.base_embed
        e.title = "Newest Clan Members"
        members = sorted(
            self.clan.members,
            key=lambda x: x.joined_clan_at.value,
            reverse=True,
        )
        e.description = "\n".join(
            [
                f"{i.joined_clan_at.relative}: {i.nickname}"
                for i in members[:10]
            ]
        )
        return await self.update(embed=e)

    async def from_dropdown(self) -> Message:
        """When initiated from a dropdown, we only have partial data,
        so we perform a fetch and then send to update"""
        self.clan = self.bot.get_clan(self.clan.clan_id)
        await self.clan.get_data()
        return await self.overview()

    async def update(self, embed: Embed) -> Message:
        """Push the latest version of the View to the user"""
        self.clear_items()

        if self.parent:
            self.add_item(Parent(label=self.parent_name))

        # TODO: Replace with Funcables
        for i in [
            FuncButton(
                label="Overview",
                disabled=self._disabled == self.overview,
                function=self.overview,
            ),
            FuncButton(
                label="Members",
                disabled=self._disabled == self.members,
                function=self.members,
            ),
            FuncButton(
                label="New Members",
                disabled=self._disabled == self.new_members,
                function=self.new_members,
            ),
        ]:
            # FuncButton(label='CB Season History'...)
            self.add_item(i)
        return await self.bot.reply(self.interaction, embed=embed, view=self)


# Autocomplete.
async def mode_ac(ctx: Interaction[PBot], cur: str) -> list[Choice[str]]:
    """Fetch a Game Mode"""
    choices = []

    cur = cur.casefold()
    for i in ctx.client.modes:
        if i.tag not in ["PVE_PREMADE", "EVENT", "BRAWL"]:
            continue
        if cur not in i.name.casefold():
            continue
        choices.append(Choice(name=i.name, value=i.tag))
    return choices[:25]


async def player_ac(
    interaction: Interaction[PBot], current: str
) -> list[Choice[str]]:
    """Fetch player's account ID by searching for their name."""
    bot: PBot = interaction.client
    p = {"application_id": bot.wg_id, "search": current, "limit": 25}

    region = getattr(interaction.namespace, "region", None)
    region = next((i for i in Region if i.db_key == region), Region.EU)

    link = PLAYERS.replace("eu", region.domain)
    async with bot.session.get(link, params=p) as resp:
        match resp.status:
            case 200:
                players = await resp.json()
            case _:
                return []

    data = players.pop("data", None)
    if data is None:
        return []

    choices = []
    for i in data:
        player = bot.get_player(i["account_id"])
        player.nickname = i["nickname"]

        if player.clan:
            name = f"[{player.clan.tag}] [{player.nickname}]"
        else:
            name = player.nickname

        value = str(player.account_id)
        choices.append(discord.app_commands.Choice(name=name, value=value))

        if len(choices) == 25:
            break

    return choices


async def clan_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for a list of clan names"""
    bot: PBot = interaction.client

    region = getattr(interaction.namespace, "region", None)
    region = next((i for i in Region if i.db_key == region), Region.EU)

    link = CLAN_SEARCH.replace("eu", region.domain)
    p = {"search": current, "limit": 25, "application_id": bot.wg_id}

    async with bot.session.get(link, params=p) as resp:
        match resp.status:
            case 200:
                clans = await resp.json()
            case _:
                return []

    choices = []
    for i in clans.pop("data", []):
        clan = interaction.client.get_clan(i["clan_id"])
        clan.tag = i["tag"]
        clan.name = i["name"]
        choices.append(
            discord.app_commands.Choice(
                name=f"[{clan.tag}] {clan.name}", value=str(clan.clan_id)
            )
        )
    return choices


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


class Warships(commands.Cog):
    """World of Warships related commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

        # override our custom classes.
        Player.bot = bot

    async def cog_load(self) -> None:
        """Fetch Generics from API and store to bot."""
        p = {"application_id": self.bot.wg_id, "language": "en"}
        if not self.bot.ship_types:
            async with self.bot.session.get(INFO, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        err = f"{resp.status} fetching ship type data {INFO}"
                        raise ConnectionError(err)

            for k, v in data["data"]["ship_types"].items():
                images = data["data"]["ship_type_images"][k]
                s_t = ShipType(k, v, images)
                self.bot.ship_types.append(s_t)

        if not self.bot.modes:
            async with self.bot.session.get(MODES, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        return

            for k, v in data["data"].items():
                self.bot.modes.append(GameMode(**v))

        if not self.bot.ships:
            self.bot.ships = await self.cache_ships()

        # if not self.bot.clan_buildings:
        #     self.bot.clan_buildings = await self.cache_clan_base()

    async def cache_clan_base(self) -> list[ClanBuilding]:
        """Cache the CLan Buildings from the API"""
        raise NotImplementedError  # TODO: Cache Clan Base
        # buildings = json.pop()
        # output = []
        # for i in buildings:
        #
        # self.building_id: int = building_id
        # self.building_type_id: int = kwargs.pop('building_type_id', None)
        # self.bonus_type: Optional[str] = kwargs.pop('bonus_type', None)
        # self.bonus_value: Optional[int] = kwargs.pop('bonus_value', None)
        # self.cost: Optional[int] = kwargs.pop('cost', None)  # Price in Oil
        # self.max_members: Optional[int] = kwargs.pop('max_members', None)
        #
        # max_members = buildings.pop()
        #
        # b = ClanBuilding()

    async def cache_ships(self) -> list[Ship]:
        """Cache the ships from the API."""
        # Run Once.
        if self.bot.ships:
            return self.bot.ships

        max_iter: int = 1
        count: int = 1
        ships: list[Ship] = []
        while count <= max_iter:
            # Initial Pull.
            p = {
                "application_id": self.bot.wg_id,
                "language": "en",
                "page_no": count,
            }
            async with self.bot.session.get(SHIPS, params=p) as resp:
                match resp.status:
                    case 200:
                        items = await resp.json()
                        count += 1
                    case _:
                        raise ConnectionError(
                            f"{resp.status} Error accessing {SHIPS}"
                        )

            max_iter = items["meta"]["page_total"]

            for ship, data in items["data"].items():
                ship = Ship(self.bot)

                nation = data.pop("nation", None)
                if nation:
                    ship.nation = next(i for i in Nation if nation == i.match)

                ship.type = self.bot.get_ship_type(data.pop("type"))

                modules = data.pop("modules")
                ship._modules = modules
                for k, v in data.items():
                    setattr(ship, k, v)
                ships.append(ship)
        return ships

    async def send_code(
        self,
        interaction: discord.Interaction[PBot],
        code: str,
        regions: list[str],
        contents: str,
    ) -> discord.Message:
        """Generate the Embed for the code."""
        e = discord.Embed(
            title=code,
            url=f"https://eu.wargaming.net/shop/redeem/?bonus_mode={code}",
            colour=discord.Colour.red(),
        )
        e.set_author(
            name="Bonus Code",
            icon_url=(
                "https://cdn.iconscout.com/icon/"
                "free/png-256/wargaming-1-283119.png"
            ),
        )
        e.set_thumbnail(
            url="https://wg-art.com/media/filer_public_thumbnails"
            "/filer_public/72/22/72227d3e-d42f-4e16-a3e9-012eb239214c/"
            "wg_wows_logo_mainversion_tm_fullcolor_ru_previewwebguide.png"
        )
        if contents:
            e.add_field(name="Contents", value=f"```yaml\n{contents}```")
        e.set_footer(text="Click on a button below to redeem for your region")

        view = discord.ui.View()
        for i in regions:
            region = next(r for r in Region if i == r.db_key)

            dom = region.code_prefix
            url = f"https://{dom}.wargaming.net/shop/redeem/?bonus_mode={code}"
            view.add_item(
                discord.ui.Button(
                    url=url,
                    label=region.name,
                    style=discord.ButtonStyle.url,
                    emoji=region.emote,
                )
            )
        return await self.bot.reply(interaction, embed=e, view=view)

    @discord.app_commands.command()
    @discord.app_commands.describe(
        code="Enter the code", contents="Enter the reward the code gives"
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def code(
        self,
        interaction: discord.Interaction[PBot],
        code: str,
        contents: str,
        eu: bool = True,
        na: bool = True,
        asia: bool = True,
    ) -> discord.InteractionMessage:
        """Send a message with region specific redeem buttons"""

        await interaction.response.defer(thinking=True)

        regions = []
        if eu:
            regions.append("eu")
        if na:
            regions.append("na")
        if asia:
            regions.append("sea")
        await self.send_code(interaction, code, regions, contents)

    @discord.app_commands.command()
    @discord.app_commands.describe(
        code="Enter the code", contents="Enter the reward the code gives"
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def code_cis(
        self, interaction: discord.Interaction[PBot], code: str, contents: str
    ) -> discord.InteractionMessage:
        """Send a message with a region specific redeem button"""

        await interaction.response.defer(thinking=True)
        await self.send_code(
            interaction, code, regions=["cis"], contents=contents
        )

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

        return await ship.view(interaction).overview()

    # TODO: Test - Clan Battles
    @discord.app_commands.command()
    @discord.app_commands.autocomplete(
        player_name=player_ac, mode=mode_ac, ship=ship_ac
    )
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(
        player_name="Search for a player name",
        region="Which region is this player on",
        mode="battle mode type",
        division="1 = solo, 2 = 2man, 3 = 3man, 0 = Overall",
        ship="Get statistics for a specific ship",
    )
    async def stats(
        self,
        interaction: discord.Interaction[PBot],
        region: REGION,
        player_name: Range[str, 3],
        mode: str = "PVP",
        division: Range[int, 0, 3] = 0,
        ship: Optional[str] = None,
    ) -> discord.InteractionMessage:
        """Search for a player's Stats"""
        _ = region  # Shut up linter.

        await interaction.response.defer(thinking=True)
        player = self.bot.get_player(int(player_name))
        g_mode = next(i for i in self.bot.modes if i.tag == mode)
        if ship:
            g_ship = self.bot.get_ship(ship)
        else:
            g_ship = None

        v = PlayerView(interaction, player, g_mode, division, g_ship)
        return await v.mode_stats(g_mode)

    clan = Group(name="clan", description="Get Clans")

    @clan.command()
    @discord.app_commands.describe(
        query="Clan Name or Tag", region="Which region is this clan from"
    )
    @discord.app_commands.autocomplete(query=clan_ac)
    async def search(
        self,
        interaction: discord.Interaction[PBot],
        region: REGION,
        query: Range[str, 2],
    ) -> discord.InteractionMessage:
        """Get information about a World of Warships clan"""
        _ = region  # Just to shut the linter up.

        await interaction.response.defer(thinking=True)
        clan = self.bot.get_clan(int(query))
        await clan.get_data()
        return await ClanView(interaction, clan).overview()

    @clan.command()
    @discord.app_commands.describe(
        region="Get only winners for a specific region"
    )
    async def winners(
        self,
        interaction: discord.Interaction[PBot],
        region: Optional[REGION] = None,
    ) -> discord.InteractionMessage:
        """Get a list of all past Clan Battle Season Winners"""

        await interaction.response.defer(thinking=True)

        async with self.bot.session.get(
            "https://clans.worldofwarships.eu/api/ladder/winners/"
        ) as resp:
            match resp.status:
                case 200:
                    winners = await resp.json()
                case _:
                    err = f"{resp.status} error accessing Hall of Fame"
                    raise ConnectionError(err)

        seasons = winners.pop("winners")
        if region is None:
            rows = []

            s = seasons.items()
            tuples = sorted(s, key=lambda x: int(x[0]), reverse=True)

            rat = "public_rating"
            for season, winners in tuples:
                wnr = [f"\n**Season {season}**"]

                srt = sorted(winners, key=lambda c: c[rat], reverse=True)
                for clan in srt:
                    tag = "realm"
                    rgn = next(i for i in Region if i.realm == clan[tag])
                    wnr.append(
                        f"{rgn.emote} `{str(clan[rat]).rjust(4)}`"
                        f" **[{clan['tag']}]** {clan['name']}"
                    )
                rows.append("\n".join(wnr))

            e = discord.Embed(
                title="Clan Battle Season Winners",
                colour=discord.Colour.purple(),
            )
            return await view_utils.Paginator(
                interaction, emmbed_utils.rows_to_embeds(e, rows, rows=1)
            ).update()
        else:
            rgn = next(i for i in Region if i.db_key == region)
            rows = []
            for season, winners in sorted(
                seasons.items(), key=lambda x: int(x[0]), reverse=True
            ):
                for clan in winners:
                    if clan["realm"] != rgn.realm:
                        continue
                    rows.append(
                        f"`{str(season).rjust(2)}.` **[{clan['tag']}]**"
                        f"{clan['name']} (`{clan['public_rating']}`)"
                    )

            e = discord.Embed(
                title="Clan Battle Season Winners",
                colour=discord.Colour.purple(),
            )
            return await view_utils.Paginator(
                interaction, embed_utils.rows_to_embeds(e, rows, rows=25)
            ).update()

    @clan.command()
    @discord.app_commands.describe(region="Get Rankings for a specific region")
    async def leaderboard(
        self,
        interaction: discord.Interaction[PBot],
        region: Optional[REGION] = None,
        season: typing.Range[int, 1, 20] = 20,
    ) -> discord.InteractionMessage:
        """Get the Season Clan Battle Leaderboard"""
        url = "https://clans.worldofwarships.eu/api/ladder/structure/"
        p = {  # league: int, 0 = Hurricane.
            # division: int, 1-3
            "realm": "global"
        }

        if season is not None:
            p.update({"season": str(season)})

        if region is not None:
            rgn = next(i for i in Region if i.db_key == region)
            p.update({"realm": rgn.realm})

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    raise ConnectionError(
                        f"Error {resp.status} connecting to {resp.url}"
                    )

        clans = []
        for c in json:
            clan = deepcopy(self.bot.get_clan(c["id"]))

            clan.tag = c["tag"]
            clan.name = c["name"]
            clan.league = next(i for i in League if i.value == c["league"])
            clan.public_rating = c["public_rating"]
            ts = datetime.strptime(c["last_battle_at"], "%Y-%m-%d %H:%M:%S%z")
            clan.last_battle_at = timed_events.Timestamp(ts)
            clan.is_clan_disbanded = c["disbanded"]
            clan.battles_count = c["battles_count"]
            clan.leading_team_number = c["leading_team_number"]
            clan.season_number = 17 if season is None else season
            clan.rank = c["rank"]

            clans.append(clan)

        return await Leaderboard(interaction, clans).update()


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(Warships(bot))
