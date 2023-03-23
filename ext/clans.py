"""Information about world of warships clans"""
from __future__ import annotations

import discord
import typing
import logging
from discord.ext import commands

from ext.painezbot_utils.region import Region
from ext.painezbot_utils.clan import Clan, League
from ext.utils import view_utils, timed_events, embed_utils

if typing.TYPE_CHECKING:
    from painezBot import PBot

CLAN_SEARCH = "https://api.worldofwarships.eu/wows/clans/list/"
REGION = typing.Literal["eu", "na", "sea"]

logger = logging.getLogger("clans.py")


class Leaderboard(view_utils.BaseView):
    """Leaderboard View with dropdowns."""

    interaction: discord.Interaction[PBot]

    def __init__(
        self, interaction: discord.Interaction[PBot], clans: list[Clan]
    ) -> None:
        super().__init__(interaction)

        self.clans: list[Clan] = clans  # Rank, Clan

    async def update(self, season: int) -> discord.InteractionMessage:
        """Push the latest version of the view to the user"""
        self.clear_items()

        e = discord.Embed(colour=discord.Colour.purple())
        e.title = f"Clan Battle Season {season} Ranking"
        e.set_thumbnail(url=League.HURRICANE.thumbnail)
        e.description = ""

        self.pages = embed_utils.paginate(self.clans, 10)
        clans = self.pages[self.index]

        parent = self.update
        dd = []
        for clan in clans:
            r = "⛔" if clan.is_clan_disbanded else str(clan.public_rating)
            rank = f"#{clan.rank}."
            region = clan.region

            text = f"{rank} {region.emote} **[{clan.tag}]** {clan.name}\n"
            text += f"`{r.rjust(4)}` {clan.battles_count} Battles"

            if clan.last_battle_at:
                lbt = clan.last_battle_at.relative
                text += f", Last: {lbt}"
            e.description += text + "\n"

            v = ClanView(self.interaction, clan, parent=parent).from_dropdown
            label = f"{clan.tag} ({clan.region.name})"
            btn = view_utils.Funcable(label, v)
            btn.description = clan.name
            btn.emoji = clan.league.emote
            dd.append(btn)

        self.add_page_buttons()
        self.add_function_row(dd, 1, "Go To Clan")

        r = self.interaction.edit_original_response
        return await r(embed=e, view=self)


class ClanView(view_utils.BaseView):
    """A View representing a World of Warships Clan"""

    bot: PBot

    def __init__(
        self, interaction: discord.Interaction[PBot], clan: Clan, **kwargs
    ) -> None:
        super().__init__(interaction, **kwargs)
        self.clan: Clan = clan

    # Entry Point but not really a ClassMethod per se.
    async def from_dropdown(
        self, interaction: discord.Interaction[PBot], clan_id: int
    ) -> discord.InteractionMessage:
        """When initiated from a dropdown, we only have partial data,
        so we perform a fetch and then send to update"""
        clan = interaction.client.get_clan(clan_id)
        if clan is None:
            raise ValueError

        self.clan = clan
        await self.clan.get_data()
        return await self.overview()

    def handle_buttons(self, current_function: typing.Callable) -> None:
        """Add Page Buttons to our view."""
        self.clear_items()

        # Parent.
        self.add_page_buttons()

        dd = []
        for name, func in [
            ("Overview", self.overview),
            ("Members", self.members),
            ("New Members", self.new_members),
        ]:
            btn = view_utils.Funcable(name, func)
            btn.disabled = current_function == func
            dd.append(btn)
        self.add_function_row(dd, 1)

    async def overview(self) -> discord.InteractionMessage:
        """Get General overview of the clan"""
        e = self.clan.embed()
        self.handle_buttons(self.overview)

        c = self.clan.api_data

        desc = []
        if c["updated_at"] is not None:
            ts = timed_events.Timestamp(c.updated_at).relative
            desc.append(f"**Information updated**: {ts}\n")

        if c["leader_name"]:
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

            lbt = c.last_battle_at
            if lbt:
                ts = timed_events.Timestamp(lbt).relative
                cb_desc.append(f"**Last Battle**: {ts}")

            # Win Rate
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
            val = "This clan is marked as 'banned'"
            e.add_field(name="Banned Clan", value=val)

        e.set_footer(text=self.clan.description)
        return await self.update(embed=e)

    async def members(self) -> discord.InteractionMessage:
        """Display an embed of the clan members"""
        e = self.clan.embed
        e.title = f"Clan Members ({self.clan.members_count} Total)"

        mems = sorted(self.clan.members, key=lambda x: x.nickname)
        mems = [
            f"`🟢` {i.nickname}" if i.is_online else i.nickname
            for i in mems
            if not i.is_banned
        ]

        e.description = discord.utils.escape_markdown(", ".join(mems))

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
        m_a_k = max(self.clan.members, key=lambda p: p.average_kills)

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
        e = self.clan.embed()
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

    async def update(self, embed: discord.Embed) -> discord.InteractionMessage:
        """Push the latest version of the View to the user"""
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


async def clan_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete for a list of clan names"""
    region = getattr(interaction.namespace, "region", None)
    rgn = next((i for i in Region if i.db_key == region), Region.EU)

    link = CLAN_SEARCH.replace("eu", rgn.domain)
    p = {
        "search": current,
        "limit": 25,
        "application_id": interaction.client.wg_id,
    }

    async with interaction.client.session.get(link, params=p) as resp:
        if resp.status != 200:
            logger.error("%s on %s", resp.status, link)
            return []

        clans = await resp.json()

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


class Clans(commands.Cog):
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
        region: typing.Optional[REGION] = None,
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
                interaction, embed_utils.rows_to_embeds(e, rows, rows=1)
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
        region: typing.Optional[REGION] = None,
        season: discord.app_commands.Range[int, 1, 20] = 20,
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
    await bot.add_cog(Clans(bot))
