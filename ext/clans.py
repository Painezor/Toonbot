"""Information about world of warships clans"""
from __future__ import annotations

import logging
import typing

import discord
from discord.ext import commands

from ext.utils import embed_utils, timed_events, view_utils
from ext.utils import wows_api as api

if typing.TYPE_CHECKING:
    from painezBot import PBot

CLAN_SEARCH = "https://api.worldofwarships.eu/wows/clans/list/"
WINNERS = "https://clans.worldofwarships.eu/api/ladder/winners/"
REGION = typing.Literal["eu", "na", "sea"]

logger = logging.getLogger("clans.py")

Interaction: typing.TypeAlias = discord.Interaction[PBot]


class Leaderboard(view_utils.BaseView):
    """Leaderboard View with dropdowns."""

    interaction: Interaction

    def __init__(
        self, interaction: Interaction, clans: list[api.Clan]
    ) -> None:
        super().__init__(interaction)

        self.clans: list[api.Clan] = clans  # Rank, Clan

    async def update(self, season: int) -> discord.InteractionMessage:
        """Push the latest version of the view to the user"""
        self.clear_items()

        embed = discord.Embed(colour=discord.Colour.purple())
        embed.title = f"Clan Battle Season {season} Ranking"
        embed.set_thumbnail(url=api.League.HURRICANE.thumbnail)
        embed.description = ""

        self.pages = embed_utils.paginate(self.clans, 10)
        clans = self.pages[self.index]

        parent = self.update
        dropdown = []
        for clan in clans:
            ban = "⛔" if clan.is_clan_disbanded else str(clan.public_rating)
            rank = f"#{clan.rank}."
            region = clan.region

            text = f"{rank} {region.emote} **[{clan.tag}]** {clan.name}\n"
            text += f"`{ban.rjust(4)}` {clan.battles_count} Battles"

            if clan.last_battle_at:
                lbt = clan.last_battle_at.relative
                text += f", Last: {lbt}"
            embed.description += text + "\n"

            fun = ClanView(self.interaction, clan, parent=parent).from_dropdown
            label = f"{clan.tag} ({clan.region.name})"
            btn = view_utils.Funcable(label, fun)
            btn.description = clan.name
            btn.emoji = clan.league.emote
            dropdown.append(btn)

        self.add_page_buttons()
        self.add_function_row(dropdown, 1, "Go To Clan")

        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


class ClanView(view_utils.BaseView):
    """A View representing a World of Warships Clan"""

    bot: PBot

    def __init__(
        self, interaction: Interaction, clan: api.Clan, **kwargs
    ) -> None:
        super().__init__(interaction, **kwargs)
        self.clan: api.Clan = clan
        self.clan_details: api.ClanDetails | None
        self.clan_member_vortex: list[api.ClanMemberVortexData] | None
        self.clan_vortex_data: api.ClanVortexData | None

    async def base_embed(self) -> discord.Embed:
        """Generic Embed for all view functions"""
        embed = discord.Embed()
        embed.set_author(name=self.clan.title)

        if self.clan_details is None:
            self.clan_details = await self.clan.fetch_details()

        if self.clan_vortex_data is None:
            self.clan_vortex_data = await self.clan.fetch_clan_vortex_data()

        league = self.clan_vortex_data.league
        embed.colour = league.colour
        embed.set_thumbnail(url=league.thumbnail)
        return embed

    # Entry Point but not really a ClassMethod per se.
    async def from_dropdown(
        self, interaction: Interaction, clan_id: int
    ) -> discord.InteractionMessage:
        """When initiated from a dropdown, we only have partial data,
        so we perform a fetch and then send to update"""
        clan = interaction.client.get_clan(clan_id)
        if clan is None:
            raise ValueError

        self.clan = clan
        self.clan_details = await self.clan.fetch_details()
        return await self.overview()

    def handle_buttons(self, current_function: typing.Callable) -> None:
        """Add Page Buttons to our view."""
        self.clear_items()

        # Parent.
        self.add_page_buttons()

        dropdown = []
        func: typing.Callable
        for name, func in [
            ("Overview", self.overview),
            ("Members", self.members),
            ("New Members", self.new_members),
        ]:
            btn = view_utils.Funcable(name, func)
            btn.disabled = current_function == func
            dropdown.append(btn)
        self.add_function_row(dropdown, 1)

    async def overview(self) -> discord.InteractionMessage:
        """Get General overview of the clan"""
        embed = await self.base_embed()
        self.handle_buttons(self.overview)

        assert (details := self.clan_details) is not None
        assert (vortex := self.clan_vortex_data) is not None

        desc = []
        if details.updated_at is not None:
            time = timed_events.Timestamp(details.updated_at).relative
            desc.append(f"**Information updated**: {time}\n")

        if details.leader_name:
            desc.append(f"**Leader**: {details.leader_name}")

        if details.created_at:
            creator = details.creator_name

            time = timed_events.Timestamp(details.created_at).relative
            desc.append(f"**Founder**: {creator} ({time})")

        if details.renamed_at:
            time = timed_events.Timestamp(details.renamed_at).relative
            fmt = f"[{details.old_tag}] {details.old_name} ({time})"
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
            rest = f"{vortex.wins_count} / {vortex.battles_count}"
            cb_desc.append(f"**Win Rate**: {win_r}% ({rest})")

            # Win streaks
            lws = vortex.max_winning_streak
            cws = vortex.current_winning_streak
            if cws:
                if cws == lws:
                    cb_desc.append(f"**Win Streak**: {cws}")
                else:
                    cb_desc.append(f"**Win Streak**: {cws} (Max: {lws})")
            elif vortex.max_winning_streak:
                cb_desc.append(f"**Longest Win Streak**: {lws}")
            embed.add_field(name=title, value="\n".join(cb_desc))

        embed.set_footer(
            text=f"{self.clan.region.name} Clan #{self.clan.clan_id}"
        )
        embed.description = "\n".join(desc)

        if vortex.is_banned:
            val = "This clan is marked as 'banned'"
            embed.add_field(name="Banned Clan", value=val)

        embed.set_footer(text=details.description)
        return await self.update(embed=embed)

    async def members(self) -> discord.InteractionMessage:
        """Display an embed of the clan members"""
        embed = await self.base_embed()

        assert (details := self.clan_details) is not None

        embed.title = f"Clan Members ({details.members_count} Total)"

        if self.clan_member_vortex is None:
            self.clan_member_vortex = await self.clan.get_members_vortex()

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
        await self.clan.get_members_vortex()

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
        # https://clans.worldofwarships.eu/api/members/500140589/?battle_type=cvc&season=17
        # TODO: Clan Battle History
        raise NotImplementedError
        self._disabled = self.history
        embed = await self.base_embed()
        embed.description = "```diff\n-Not Implemented Yet.```"
        return await self.update(embed=embed)

    async def new_members(self) -> discord.InteractionMessage:
        """Get a list of the clan's newest members"""
        self._disabled = self.new_members
        embed = await self.base_embed()
        embed.title = "Newest Clan Members"

        if self.clan_member_vortex is None:
            self.clan_member_vortex = await self.clan.get_members_vortex()

        vtx = self.clan_member_vortex
        members = sorted(vtx, key=lambda x: x.joined_clan_at, reverse=True)

        embed.description = ""
        for i in members[:10]:
            time = timed_events.Timestamp(i.joined_clan_at).relative
            embed.description += f"{time}: {i.nickname}"
        return await self.update(embed=embed)

    async def update(self, embed: discord.Embed) -> discord.InteractionMessage:
        """Push the latest version of the View to the user"""
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


async def clan_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for a list of clan names"""
    region = getattr(interaction.namespace, "region", None)
    rgn = next((i for i in api.Region if i.db_key == region), api.Region.EU)

    link = CLAN_SEARCH.replace("eu", rgn.domain)
    params = {
        "search": current,
        "limit": 25,
        "application_id": api.WG_ID,
    }

    async with interaction.client.session.get(link, params=params) as resp:
        if resp.status != 200:
            logger.error("%s on %s", resp.status, link)
            return []

        clans = await resp.json()

    choices = []
    for i in clans.pop("data", []):
        clan = api.Clan(i["clan_id"])
        clan.tag = i["tag"]
        clan.name = i["name"]
        choices.append(
            discord.app_commands.Choice(
                name=f"[{clan.tag}] {clan.name}", value=str(clan.clan_id)
            )
        )
    return choices


class Clans(commands.Cog):
    """Fetch data about world of warships clans"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    clan = discord.app_commands.Group(name="clan", description="Get Clans")

    @clan.command()
    @discord.app_commands.describe(
        query="Clan Name or Tag", region="Which region is this clan from"
    )
    @discord.app_commands.autocomplete(query=clan_ac)
    async def search(
        self,
        interaction: discord.Interaction[PBot],
        region: REGION,
        query: discord.app_commands.Range[str, 2],
    ) -> discord.InteractionMessage:
        """Get information about a World of Warships clan"""
        _ = region  # Just to shut the linter up.

        await interaction.response.defer(thinking=True)
        return await ClanView(interaction, api.Clan(int(query))).overview()

    @clan.command()
    @discord.app_commands.describe(region="Get winners for a specific region")
    async def winners(
        self,
        interaction: discord.Interaction[PBot],
        region: typing.Optional[REGION] = None,
    ) -> discord.InteractionMessage:
        """Get a list of all past Clan Battle Season Winners"""

        await interaction.response.defer(thinking=True)

        async with self.bot.session.get(WINNERS) as resp:
            match resp.status:
                case 200:
                    winners = await resp.json()
                case _:
                    err = f"{resp.status} error accessing Hall of Fame"
                    raise ConnectionError(err)

        seasons = winners.pop("winners")
        if region is None:
            rows = []

            ssn = seasons.items()
            tuples = sorted(ssn, key=lambda x: int(x[0]), reverse=True)

            rat = "public_rating"
            for season, winners in tuples:
                wnr = [f"\n**Season {season}**"]

                srt = sorted(winners, key=lambda c: c[rat], reverse=True)
                for clan in srt:
                    tag = "realm"
                    rgn = next(i for i in api.Region if i.realm == clan[tag])
                    wnr.append(
                        f"{rgn.emote} `{str(clan[rat]).rjust(4)}`"
                        f" **[{clan['tag']}]** {clan['name']}"
                    )
                rows.append("\n".join(wnr))

            embed = discord.Embed(
                title="Clan Battle Season Winners",
                colour=discord.Colour.purple(),
            )

            embeds = embed_utils.rows_to_embeds(embed, rows, rows=1)
            return await view_utils.Paginator(interaction, embeds).update()

        rgn = next(i for i in api.Region if i.db_key == region)
        rows = []

        tuples = sorted(seasons.items(), key=lambda x: int(x[0]), reverse=True)

        for season, winners in tuples:
            for clan in winners:
                if clan["realm"] != rgn.realm:
                    continue
                rows.append(
                    f"`{str(season).rjust(2)}.` **[{clan['tag']}]**"
                    f"{clan['name']} (`{clan['public_rating']}`)"
                )

        embed = discord.Embed(
            title="Clan Battle Season Winners",
            colour=discord.Colour.purple(),
        )
        return await view_utils.Paginator(
            interaction, embed_utils.rows_to_embeds(embed, rows, rows=25)
        ).update()

    @clan.command()
    @discord.app_commands.describe(region="Get Rankings for a specific region")
    async def leaderboard(
        self,
        interaction: discord.Interaction[PBot],
        region: typing.Optional[REGION] = None,
        season: discord.app_commands.Range[int, 1, 22] = 22,
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
            if resp.status != 200:
                raise ConnectionError(f"{resp.status} on {resp.url}")
            json = await resp.json()

        clans = []
        for data in json:
            clan = api.Clan(data["id"])

            clan.tag = data["tag"]
            clan.name = data["name"]

            stats = api.ClanLeaderboardStats(clan, data)
            clans.append(stats)

        return await Leaderboard(interaction, clans).update(season=season)


async def setup(bot: PBot):
    """Add the clans cog to the bot"""
    await bot.add_cog(Clans(bot))
