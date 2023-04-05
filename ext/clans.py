"""Information about world of warships clans"""
from __future__ import annotations

import importlib
import logging
import typing

import discord
from discord.ext import commands

from ext import wows_api as api
from ext.utils import embed_utils, timed_events, view_utils

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]


importlib.reload(api)

logger = logging.getLogger("clans.py")


class Leaderboard(view_utils.BaseView):
    """Leaderboard View with dropdowns."""

    def __init__(self, clans: list[api.ClanLeaderboardStats]) -> None:
        super().__init__()
        self.pages: list[list[api.ClanLeaderboardStats]]
        self.clans: list[api.ClanLeaderboardStats] = clans  # Rank, Clan

    async def update(
        self, interaction: Interaction, ssn_id: int | None
    ) -> None:
        """Push the latest version of the view to the user"""
        self.clear_items()

        embed = discord.Embed(colour=discord.Colour.purple())
        embed.title = f"Clan Battle Season {ssn_id} Ranking"
        embed.description = ""

        self.pages = embed_utils.paginate(self.clans, 10)
        clans = self.pages[self.index]

        dropdown = []
        for clan in clans:
            ban = "⛔" if clan else str(clan.public_rating)
            rank = f"#{clan.rank}."
            region = next(i for i in api.Region if i.realm == clan.realm)

            text = f"{rank} {region.emote} **[{clan.tag}]** {clan.name}\n"
            text += f"`{ban.rjust(4)}` {clan.battles_count} Battles"

            if clan.last_battle_at:
                lbt = timed_events.Timestamp(clan.last_battle_at).relative
                text += f", Last: {lbt}"
            embed.description += text + "\n"

            clan_details = await api.get_clan_details(clan.id, region)
            c_view = ClanView(clan_details, parent=self.update)

            label = f"{clan.tag} ({region.name})"
            btn = view_utils.Funcable(label, c_view.overview)
            btn.description = clan.name

            client = interaction.client
            ssn: list[api.ClanBattleSeason] = client.clan_battle_seasons
            season = next(i for i in ssn if i.season_id == clan.season_number)

            league = next(i for i in season.leagues if i.value == clan.league)
            btn.emoji = league.emote
            dropdown.append(btn)

        self.add_page_buttons()
        self.add_function_row(dropdown, 1, "Go To Clan")

        return await interaction.response.edit_message(embed=embed, view=self)


class ClanView(view_utils.BaseView):
    """A View representing a World of Warships Clan"""

    bot: PBot

    def __init__(self, clan: api.Clan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.clan: api.Clan = clan
        self.clan_member_vortex: list[api.ClanMemberVortexData] | None
        self.clan_vortex_data: api.ClanVortexData | None

    async def base_embed(self) -> discord.Embed:
        """Generic Embed for all view functions"""
        embed = discord.Embed()
        embed.set_author(name=self.clan.title)

        if self.clan_vortex_data is None:
            cid = self.clan.clan_id
            rgn = self.clan.region
            self.clan_vortex_data = await api.get_clan_vortex_data(cid, rgn)

        league = self.clan_vortex_data.league
        # TODO: Fix League
        embed.colour = league.colour
        embed.set_thumbnail(url=league.thumbnail)
        return embed

    def handle_buttons(self, current_function: typing.Callable) -> None:
        """Add Page Buttons to our view."""
        self.clear_items()

        # Parent.
        self.add_page_buttons()

        dropdown = []

        def add_button(label: str, func: typing.Callable):
            btn = view_utils.Funcable(label, func)
            btn.disabled = current_function is func
            dropdown.append(btn)

        add_button("Overview", self.overview)
        add_button("Members", self.members)
        add_button("New Members", self.new_members)
        self.add_function_row(dropdown, 1)

    async def overview(self, interaction: Interaction) -> None:
        """Get General overview of the clan"""
        embed = await self.base_embed()
        self.handle_buttons(self.overview)

        assert (vortex := self.clan_vortex_data) is not None

        desc = []
        if self.clan.updated_at is not None:
            time = timed_events.Timestamp(self.clan.updated_at).relative
            desc.append(f"**Information updated**: {time}\n")

        if self.clan.leader_name:
            desc.append(f"**Leader**: {self.clan.leader_name}")

        if self.clan.created_at:
            creator = self.clan.creator_name

            time = timed_events.Timestamp(self.clan.created_at).relative
            desc.append(f"**Founder**: {creator} ({time})")

        if self.clan.renamed_at:
            time = timed_events.Timestamp(self.clan.renamed_at).relative
            fmt = f"[{self.clan.old_tag}] {self.clan.old_name} ({time})"
            desc.append(f"**Former name**: {fmt}")

        if vortex.season_number:
            title = f"Clan Battles Season {vortex.season_number}"

            flag = vortex.max_rating_name
            cb_desc = [f"**Current Rating**: {vortex.cb_rating} ({flag})"]

            if vortex.cb_rating != vortex.max_cb_rating:
                cb_desc.append(f"**Highest Rating**: {vortex.max_cb_rating}")

            time = timed_events.Timestamp(vortex.last_battle_at).relative
            cb_desc.append(f"**Last Battle**: {time}")

            # Win Rate
            win_r = round(vortex.wins_count / vortex.battles_count * 100, 2)
            _ = f"{vortex.wins_count} / {vortex.battles_count}"
            cb_desc.append(f"**Win Rate**: {win_r}% ({_})")

            # Win streaks
            lws = vortex.max_winning_streak
            cws = vortex.current_winning_streak
            if cws:
                if cws == lws:
                    cb_desc.append(f"**Win Streak**: {cws}")
                else:
                    cb_desc.append(f"**Win Streak**: {cws} (Max: {lws})")
            elif lws:
                cb_desc.append(f"**Longest Win Streak**: {lws}")
            embed.add_field(name=title, value="\n".join(cb_desc))

        embed.set_footer(
            text=f"{self.clan.region.name} Clan #{self.clan.clan_id}"
        )
        embed.description = "\n".join(desc)

        if vortex.is_banned:
            val = "This clan is marked as 'banned'"
            embed.add_field(name="Banned Clan", value=val)

        embed.set_footer(text=self.clan.description)
        return await interaction.response.edit_message(embed=embed)

    async def members(self, interaction: Interaction) -> None:
        """Display an embed of the clan members"""
        embed = await self.base_embed()
        embed.title = f"Clan Members ({self.clan.members_count} Total)"
        mems = sorted(self.clan_member_vortex, key=lambda x: x.nickname)

        text = [
            f"`🟢` {i.nickname}" if i.is_online else i.nickname
            for i in mems
            if not i.is_banned
        ]

        embed.description = discord.utils.escape_markdown(", ".join(text))

        if banned := [i.nickname for i in mems if i.is_banned]:
            embed.add_field(name="Banned Members", value=", ".join(banned))

        # Clan Records:
        await api.get_clan_member_vortex_data()

        c_wr = round(sum(i.win_rate for i in mems) / len(mems), 2)

        avg_dmg = round(sum(i.average_damage for i in mems) / len(mems))
        c_dmg = format(avg_dmg, ",")

        avg_xp = round(sum(c.average_xp for c in mems) / len(mems), 2)
        c_xp = format(avg_xp, ",")

        c_kills = round(sum(c.average_kills for c in mems) / len(mems), 2)

        avg_games = round(sum(c.battles for c in mems) / len(mems))
        c_games = format(avg_games, ",")

        c_gpd = round(sum(c.battles_per_day for c in mems) / len(mems), 2)
        embed.add_field(
            name="Clan Averages",
            value=f"**Win Rate**: {c_wr}%\n"
            f"**Average Damage**: {c_dmg}\n"
            f"**Average Kills**: {c_kills}\n"
            f"**Average XP**: {c_xp}\n"
            f"**Total Battles**: {c_games}\n"
            f"**Battles Per Day**: {c_gpd}",
        )

        m_d = max(mems, key=lambda p: p.average_damage)
        max_xp = max(mems, key=lambda p: p.average_xp)
        max_wr = max(mems, key=lambda p: p.win_rate)
        max_games = max(mems, key=lambda p: p.battles)
        m_p = max(mems, key=lambda p: p.battles_per_day)
        m_a_k = max(mems, key=lambda p: p.average_kills)

        embed.add_field(
            name="Top Players",
            value=f"{round(max_wr.win_rate, 2)}% ({max_wr.nickname})\n"
            f'{format(round(m_d.average_damage), ",")} ({m_d.nickname})\n'
            f"{round(m_a_k.average_kills, 2)} ({m_a_k.nickname})\n"
            f'{format(round(max_xp.average_xp), ",")} ({max_xp.nickname})\n'
            f'{format(max_games.battles, ",")} ({max_games.nickname})\n'
            f"{round(m_p.battles_per_day, 2)} ({m_p.nickname})",
        )

        return await self.update(embed=embed)

    async def history(self) -> discord.InteractionMessage:
        """Get a clan's Clan Battle History"""
        # TODO: Clan Battle History
        self.handle_buttons(self.history)
        embed = await self.base_embed()
        embed.description = "```diff\n-Not Implemented Yet.```"
        return await self.update(embed=embed)

    async def new_members(self, interaction: Interaction) -> None:
        """Get a list of the clan's newest members"""
        self.handle_buttons(self.new_members)
        embed = await self.base_embed()
        embed.title = "Newest Clan Members"

        if self.clan_member_vortex is None:
            self.clan_member_vortex = await api.get_clan_member_vortex_data()

        vtx = self.clan_member_vortex
        members = sorted(vtx, key=lambda x: x.joined_clan_at, reverse=True)

        embed.description = ""
        for i in members[:10]:
            time = timed_events.Timestamp(i.joined_clan_at).relative
            embed.description += f"{time}: {i.nickname}"
        return await interaction.response.edit_message(embed=embed, view=self)


class Clans(commands.Cog):
    """Fetch data about world of warships clans"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        importlib.reload(api)

    async def cog_load(self) -> None:
        """Fetch Clan Related Data on startup"""
        self.bot.clan_battle_seasons = await api.get_cb_seasons()
        self.bot.clan_battle_winners = await api.get_cb_winners()

    clan = discord.app_commands.Group(
        name="clan", description="Get Clans", guild_ids=[250252535699341312]
    )

    # TODO: Conver to View with dropdowns.
    @clan.command()
    async def winners(
        self, interaction: Interaction
    ) -> discord.InteractionMessage:
        """Get a list of all past Clan Battle Season Winners"""
        await interaction.response.defer(thinking=True)

        def write_winner_row(clan: api.ClanBattleWinner) -> str:
            """Convert Clan Row to Winner Item"""

            try:
                rgn = next(i for i in api.Region if i.realm == clan.realm)
                emote = rgn.emote
            except StopIteration:
                emote = "<:CIS:993495488248680488>"

            rate = str(clan.public_rating).rjust(4)
            return f"{emote} `{rate}` **[{clan.tag}]** {clan.name}\n"

        embeds = []
        for season, clans in self.bot.clan_battle_winners.items():
            srt = sorted(clans, key=lambda c: c.public_rating, reverse=True)

            season = next(
                i
                for i in self.bot.clan_battle_seasons
                if i.season_id == clans[0].season_id
            )

            if season.ship_tier_min == season.ship_tier_max:
                tier = season.ship_tier_min
            else:
                tier = f"{season.ship_tier_min} - {season.ship_tier_max}"

            embed = discord.Embed(
                title=f"Season {season.season_id}: {season.name} (Tier {tier})"
            )
            embed.description = (
                f"{timed_events.Timestamp(season.start_time).date} - "
                f"{timed_events.Timestamp(season.finish_time).date} at "
                f"{''.join([write_winner_row(i) for i in srt])}"
            )
            embed.set_thumbnail(url=season.top_league.icon)
            embed.color = discord.Colour.from_str(season.top_league.color)
            embeds.append(embed)
        return await view_utils.Paginator(interaction, embeds).update()

    @clan.command()
    @discord.app_commands.describe(
        clan="Clan Name or Tag", region="Which region is this clan from"
    )
    async def search(
        self,
        interaction: Interaction,
        region: typing.Literal["eu", "na", "sea"],
        clan: api.transformers.clan_transform,
    ) -> discord.InteractionMessage:
        """Get information about a World of Warships clan"""
        del region  # Just to shut the linter up.

        await interaction.response.defer(thinking=True)
        return await ClanView(clan).overview(interaction)

    @clan.command()
    @discord.app_commands.describe(region="Get Rankings for a specific region")
    async def leaderboard(
        self,
        interaction: Interaction,
        region: typing.Optional[typing.Literal["eu", "na", "sea"]] = None,
        season: typing.Optional[discord.app_commands.Range[int, 1, 22]] = None,
    ) -> discord.InteractionMessage:
        """Get the Season Clan Battle Leaderboard"""
        url = "https://clans.worldofwarships.eu/api/ladder/structure/"
        params = {  # league: int, 0 = Hurricane.
            # division: int, 1-3
            "realm": "global"
        }

        if season is not None:
            params.update({"season": str(season)})

        if region is not None:
            rgn = next(i for i in api.Region if i.db_key == region)
            params.update({"realm": rgn.realm})

        async with self.bot.session.get(url, params=params) as resp:
            data = await resp.json()

        clans = [api.ClanLeaderboardStats(i) for i in data]
        return await Leaderboard(clans).update(interaction, season)

    async def cache_clan_base(self) -> list[api.ClanBuilding]:
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


async def setup(bot: PBot):
    """Add the clans cog to the bot"""
    await bot.add_cog(Clans(bot))
