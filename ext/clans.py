"""Information about world of warships clans"""
from __future__ import annotations

import importlib
import logging

from typing import Optional, TYPE_CHECKING, TypeAlias, Any

import discord
from discord import SelectOption, Embed, Colour
from discord.ext import commands
from discord.utils import escape_markdown

from ext import wows_api as api
from ext.utils import view_utils
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[PBot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("clans.py")


class Leaderboard(view_utils.DropdownPaginator):
    """Leaderboard View with dropdowns."""

    def __init__(
        self,
        invoker: User,
        clans: list[api.ClanLeaderboardStats],
        season: Optional[api.ClanBattleSeason],
        region: Optional[api.Region],
    ) -> None:
        embed = Embed(colour=Colour.purple())

        title = ["Clan Battle"]
        if season is not None:
            title.append(f" Season {season.season_id}: {season.name}")
            if (tier := season.ship_tier_max) != season.ship_tier_min:
                tier = f"{season.ship_tier_min} - {season.ship_tier_max}"
            embed.set_footer(text=f"Tier {tier}")

        title.append(" Leaderboard")

        if region is not None:
            title.append(f" ({region.name})")

        embed.title = "".join(title)

        rows: list[str] = []
        options: list[SelectOption] = []
        for clan in clans:
            ban = "⛔" if clan.disbanded else str(clan.public_rating)
            rank = f"`{str(clan.rank).rjust(2)}.`"
            region = next(i for i in api.Region if i.realm == clan.realm)

            text = f"{rank} {region.emote} **[{clan.tag}]** "
            text += f"`{ban.rjust(4)}` {clan.battles_count} Battles"

            if clan.last_battle_at:
                lbt = Timestamp(clan.last_battle_at).relative
                text += f", Last: {lbt}"
            rows.append(text)

            option = SelectOption(label=clan.tag, value=str(clan.id))
            option.emoji = region.emote
            option.description = clan.name
            options.append(option)

        super().__init__(invoker, embed, rows, options)
        # Store so it can be accessed by dropdown
        self.clans: list[api.ClanLeaderboardStats] = clans

    @discord.ui.select(row=1, options=[], placeholder="View Clan")
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[Leaderboard]
    ) -> None:
        """Push the latest version of the view to the user"""
        clan = next(i for i in self.clans if str(i.id) in sel.values)
        region = next(i for i in api.Region if i.realm == clan.realm)
        clan_details = await api.get_clan_details(clan.id, region)
        view = ClanView(itr.user, clan_details, parent=self)
        embed = await view.base_embed(itr)
        await itr.response.edit_message(embed=embed, view=view)
        view.message = await itr.original_response()


# TODO: URL Button - Wows Numbers
# https://wows-numbers.com/clan/500140589,-PTA-penta-gg/
# TODO: URL Button - CLans Page
# https://clans.worldofwarships.eu/clan-profile/500140589
class ClanView(view_utils.BaseView):
    """A View representing a World of Warships Clan"""

    def __init__(self, invoker: User, clan: api.Clan, **kwargs: Any) -> None:
        super().__init__(invoker, **kwargs)
        self.clan: api.Clan = clan

        self._clan_vortex: Optional[api.ClanVortexData] = None
        self._member_vortex: list[api.ClanMemberVortexData] = []

    async def clan_vortex(self) -> api.ClanVortexData:
        """Fetch Clan Vortex data or return cached"""
        if self._clan_vortex is None:
            cid = self.clan.clan_id
            rgn = self.clan.region
            self._clan_vortex = await api.get_clan_vortex_data(cid, rgn)
        return self._clan_vortex

    async def member_vortex(self) -> list[api.ClanMemberVortexData]:
        """Fetch Member Clan Vortex data or return cached"""
        if not self._member_vortex:
            cid = self.clan.clan_id
            rgn = self.clan.region
            self._member_vortex = await api.get_member_vortex(cid, rgn)
        return self._member_vortex

    async def base_embed(self, interaction: Interaction) -> Embed:
        """Generic Embed for all view functions"""

        clan_vortex = await self.clan_vortex()
        embed = Embed(color=clan_vortex.color)
        embed.set_author(name=self.clan.title)

        seasons = interaction.client.clan_battle_seasons
        seasons = sorted(seasons, key=lambda i: i.season_id, reverse=True)
        targ = clan_vortex.league
        league = next(i for i in seasons[0].leagues if i.value == targ)
        embed.set_thumbnail(url=league.icon)
        return embed

    async def generate_overview(self, interaction: Interaction) -> Embed:
        """Entry point for a clan view"""
        embed = await self.base_embed(interaction)
        data = await self.clan_vortex()

        time = Timestamp(self.clan.updated_at).relative
        desc = [f"**Information updated**: {time}\n"]

        if self.clan.leader_name:
            desc.append(f"**Leader**: {self.clan.leader_name}")

        if self.clan.created_at:
            creator = self.clan.creator_name

            time = Timestamp(self.clan.created_at).relative
            desc.append(f"**Founder**: {creator} ({time})")

        if self.clan.renamed_at:
            time = Timestamp(self.clan.renamed_at).relative
            fmt = f"[{self.clan.old_tag}] {self.clan.old_name} ({time})"
            desc.append(f"**Former name**: {fmt}")

        if data.season_number:
            title = f"Clan Battles Season {data.season_number}"

            flag = data.max_rating_name
            cb_desc = [f"**Current Rating**: {data.cb_rating} ({flag})"]

            if hasattr(data, "max_cb_rating"):
                logger.error("You also nuked max_cb_rating here.")
            # if vortex.cb_rating != vortex.max_cb_rating:
            #     cb_desc.append(f"**Highest Rating**: {vortex.max_cb_rating}")

            time = Timestamp(data.last_battle_at).relative
            cb_desc.append(f"**Last Battle**: {time}")

            # Win Rate
            if data.battles_count:
                win_r = round(data.wins_count / data.battles_count * 100, 2)
                _ = f"{data.wins_count} / {data.battles_count}"
                cb_desc.append(f"**Win Rate**: {win_r}% ({_})")

            # Win streaks
            # lws = vortex.max_winning_streak
            cws = data.current_winning_streak

            if hasattr(data, "max_winning_streak"):
                logger.error("You removed longest winning streak, fuckface")
            if cws:
                # if cws == lws:
                cb_desc.append(f"**Win Streak**: {cws}")
                # cb_desc.append(f"**Win Streak**: {cws} (Max: {lws})")
            # elif lws:
            #     cb_desc.append(f"**Longest Win Streak**: {lws}")
            embed.add_field(name=title, value="\n".join(cb_desc))

        embed.set_footer(
            text=f"{self.clan.region.name} Clan #{self.clan.clan_id}"
        )
        embed.description = "\n".join(desc)

        if data.is_banned:
            val = "This clan is marked as 'banned'"
            embed.add_field(name="Banned Clan", value=val)

        embed.set_footer(text=self.clan.description)
        return embed

    @discord.ui.button(label="Overview")
    async def overview(self, interaction: Interaction, _) -> None:
        """Get General overview of the clan"""
        embed = await self.generate_overview(interaction)
        return await interaction.response.edit_message(embed=embed)

    # TODO: Dropdown Paginator, Sort by Clan Role for Embed, name for pages.
    @discord.ui.button(label="Members")
    async def members(self, interaction: Interaction, _) -> None:
        """Display an embed of the clan members"""
        embed = await self.base_embed(interaction)
        embed.title = f"Clan Members ({self.clan.members_count} Total)"
        mems = await self.member_vortex()
        mems.sort(key=lambda i: (i.online_status, i.name.lower()))

        if not mems:
            embed.description = "No members found"
            return await interaction.response.edit_message(embed=embed)

        # fr means format {} but use raw for backslash
        names = [rf"\🟢 {i.name}" if i.online_status else i.name for i in mems]
        embed.description = escape_markdown(", ".join(names))

        if banned := [i.name for i in mems if i.is_banned]:
            embed.add_field(name="Banned Members", value=", ".join(banned))

        return await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="Averages")
    async def clan_averages(self, interaction: Interaction, _) -> None:
        """Get Clan Aveerages"""
        # Clan Records:
        embed = await self.base_embed(interaction)
        embed.title = "Clan Averages"

        mems = await self.member_vortex()
        avg: list[str] = []
        rec: list[str] = []

        high = max(mems, key=lambda i: i.wins_percentage or 0)
        if high.wins_percentage:
            _ = "**Win Rate**: "
            valid = [i.wins_percentage for i in mems if i.wins_percentage]
            avg.append(f"{_}{round(sum(valid) / len(valid), 2)}%")
            rec.append(f"{_}{round(high.wins_percentage, 2)}% ({high.name})")

        high = max(mems, key=lambda i: i.damage_per_battle or 0)
        if high.damage_per_battle:
            _ = "**Damage Per Battle**: "
            valid = [i.damage_per_battle for i in mems if i.damage_per_battle]
            avg.append(f"{_}{format(round(sum(valid) / len(valid)), ',')}")
            fmt = format(round(high.damage_per_battle), ",")
            rec.append(f"{_}{fmt} ({high.name})")

        high = max(mems, key=lambda i: i.exp_per_battle or 0)
        if high.exp_per_battle:
            _ = "**Exp Per Battle**: "
            valid = [i.exp_per_battle for i in mems if i.exp_per_battle]
            avg.append(f"{_}{format(round(sum(valid) / len(valid)), ',')}")
            fmt = format(round(high.exp_per_battle), ",")
            rec.append(f"{_}{fmt} ({high.name})")

        high = max(mems, key=lambda i: i.frags_per_battle or 0)
        if high.frags_per_battle:
            _ = "**Kills Per Battle**: "
            valid = [i.frags_per_battle for i in mems if i.frags_per_battle]
            avg.append(f"{_}{round(sum(valid) / len(valid), 2)}")
            rec.append(f"{_}{round(high.frags_per_battle, 2)} ({high.name})")

        _ = "**Battles Played**: "
        high = max(mems, key=lambda i: i.battles_count or 0)
        valid = [i.battles_count for i in mems if i.battles_count]
        avg.append(f"{_}{format(round(sum(valid) / len(valid)), ',')}")
        rec.append(f"{_}{format(high.battles_count, ',')} ({high.name})")

        # _ = "**Battles Per Day**: "
        # high = max(mems, key=lambda i: i.battles_per_day or 0)
        # valid = [i.battles_per_day for i in mems if i.battles_per_day]
        # avg.append(f"{_}{round(sum(valid) / len(valid))}\n")
        # rec.append(f"{_}{high.battles_per_day} ({high.name})\n")

        embed.add_field(name="Averages", value="\n".join(avg), inline=False)
        _ = "Best Averages"
        embed.add_field(name=_, value="\n".join(rec), inline=False)
        return await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="New Members")
    async def new_members(self, interaction: Interaction, _) -> None:
        """Get a list of the clan's newest members"""
        embed = await self.base_embed(interaction)
        embed.title = "Newest Clan Members"

        vtx = await self.member_vortex()

        members = sorted(vtx, key=lambda x: x.days_in_clan)

        embed.description = ""
        for i in members[:10]:
            # delta = datetime.timedelta(days=i.days_in_clan)
            # time = Timestamp(self.clan.created_at - delta).relative
            embed.description += f"{i.days_in_clan} Days: {i.name}\n"
        return await interaction.response.edit_message(embed=embed, view=self)


class WinnerView(view_utils.DropdownPaginator):
    """Paginated View of Clan Battle Season Winners"""

    def __init__(
        self,
        invoker: User,
        winners: dict[int, list[api.ClanBattleWinner]],
        seasons: list[api.ClanBattleSeason],
    ) -> None:
        embeds: list[Embed] = []
        options: list[list[SelectOption]] = []

        for k, val in sorted(winners.items(), reverse=True):
            val.sort(key=lambda c: c.public_rating)

            k = next(i for i in seasons if i.season_id == val[0].season_id)

            if k.ship_tier_min == k.ship_tier_max:
                tier = k.ship_tier_min
            else:
                tier = f"{k.ship_tier_min} - {k.ship_tier_max}"

            embed = Embed()
            embed.set_thumbnail(url=k.top_league.icon)
            embed.color = Colour.from_str(k.top_league.color)
            embed.title = f"Season {k.season_id}: {k.name} (Tier {tier})"
            embed.description = f"{Timestamp(k.start_time).date} - "
            embed.description += f"{Timestamp(k.finish_time).date}\n\n"

            opts: list[SelectOption] = []
            for i in val:
                try:
                    rgn = next(j for j in api.Region if j.realm == i.realm)
                    emote = rgn.emote
                    opt = SelectOption(label=i.tag, value=str(i.clan_id))
                    opt.description = i.name
                    opt.emoji = emote
                    opts.append(opt)
                except StopIteration:
                    # Deprecated region.
                    emote = "<:CIS:993495488248680488>"

                rate = str(i.public_rating).rjust(4)
                embed.description += f"{emote} `{rate}` **[{i.tag}]**\n"
            embeds.append(embed)
            options.append(opts)

        emb = embeds[0]
        super().__init__(invoker, emb, [], options[0], 1)

        # Override Data since we're kinda spoofing it.
        self.dropdowns = options
        self.dropdown.options = self.dropdowns[0]
        self.pages = embeds
        self.update_buttons()

        self.clans: list[api.ClanBattleWinner] = []
        for i in winners.values():
            self.clans += i

    @discord.ui.select(placeholder="View Clan")
    async def dropdown(
        self, itr: Interaction, select: discord.ui.Select[WinnerView]
    ) -> None:
        """Go to clan mentioned"""
        winner = next(i for i in self.clans if str(i.clan_id) in select.values)
        region = next(i for i in api.Region if winner.realm == i.realm)
        clan = await api.get_clan_details(winner.clan_id, region)

        view = ClanView(itr.user, clan, parent=self)
        embed = await view.generate_overview(itr)
        await itr.response.edit_message(view=view, embed=embed)
        view.message = self.message


class Clans(commands.Cog):
    """Fetch data about world of warships clans"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        importlib.reload(view_utils)

    async def cog_load(self) -> None:
        """Fetch Clan Related Data on startup"""
        self.bot.clan_battle_seasons = await api.get_cb_seasons()
        self.bot.clan_battle_winners = await api.get_cb_winners()

    clan = discord.app_commands.Group(
        name="clan",
        description="Get Information about World of Warships Clans",
        guild_ids=[250252535699341312],
    )

    @clan.command()
    async def winners(self, interaction: Interaction) -> None:
        """Get a list of all past Clan Battle Season Winners"""
        winners = self.bot.clan_battle_winners
        seasons = self.bot.clan_battle_seasons
        view = WinnerView(interaction.user, winners, seasons)
        await interaction.response.send_message(view=view, embed=view.pages[0])

    @clan.command()
    @discord.app_commands.describe(
        clan="Clan Name or Tag", region="Which region is this clan from"
    )
    async def search(
        self,
        interaction: Interaction,
        region: api.region_transform,
        clan: api.transformers.clan_transform,
    ) -> None:
        """Get information about a World of Warships clan"""
        full_clan = await api.get_clan_details(clan.clan_id, region)
        view = ClanView(interaction.user, full_clan)
        embed = await view.generate_overview(interaction)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    # TODO: Transformer reading max season from the bot.seasons
    @clan.command()
    @discord.app_commands.describe(
        region="Get Rankings for a specific region",
        season="Get rankings for a previous season",
    )
    async def leaderboard(
        self,
        interaction: Interaction,
        region: api.region_transform,
        season: Optional[discord.app_commands.Range[int, 1, 20]] = None,
    ) -> None:
        """Get the Season Clan Battle Leaderboard"""
        clans = await api.get_cb_leaderboard(region=region, season=season)
        seasons = interaction.client.clan_battle_seasons
        ssn = next((i for i in seasons if season == i.season_id), None)
        view = Leaderboard(interaction.user, clans, ssn, region)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


async def setup(bot: PBot):
    """Add the clans cog to the bot"""
    await bot.add_cog(Clans(bot))
