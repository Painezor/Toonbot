"""Commands for fetching information about football entities from
   transfermarkt"""
from __future__ import annotations

import logging
from typing import TypeAlias, TYPE_CHECKING

import discord
from discord.ext import commands
from discord.app_commands import Group

from ext.utils import view_utils, flags, timed_events, embed_utils
import ext.toonbot_utils.transfermarkt as tfm


if TYPE_CHECKING:
    from core import Bot

    User: TypeAlias = discord.User | discord.Member
    Interaction: TypeAlias = discord.Interaction[Bot]

FAVICON = (
    "https://upload.wikimedia.org/wikipedia/commons/f/fb/"
    "Transfermarkt_favicon.png"
)

logger = logging.getLogger("ext.lookup")


def fmt_player(player: tfm.TFPlayer) -> str:
    flg = flags.get_flags(player.country)
    md = f"[{player.name}]({player.link})"
    desc = [" ".join(flg), md, player.age, player.position]

    if player.team is not None:
        desc.append(f"[{player.team.name}]({player.team.link})")
    return " ".join([str(i) for i in desc if i])


def fmt_team(team: tfm.TFTeam) -> str:
    flg = " ".join(flags.get_flags(team.country))
    md = f"[{team.name}]({team.link})"
    if team.league is not None:
        return f"{flg} {md} ([{team.league.name}]({team.league.link}))"
    return f"{flg} {md}"


class TFMEmbed(discord.Embed):
    def __init__(self, obj: tfm.SearchResult) -> None:
        super().__init__(colour=discord.Colour.dark_blue())
        self.set_author(name="TransferMarkt", icon_url=FAVICON)
        self.title = obj.name
        self.url = obj.link


class CompetitionEmbed(TFMEmbed):
    def __init__(self, competition: tfm.TFCompetition) -> None:
        super().__init__(competition)
        self.set_thumbnail(url=competition.picture)


class TeamEmbed(TFMEmbed):
    def __init__(self, team: tfm.TFTeam) -> None:
        super().__init__(team)
        self.set_thumbnail(url=team.badge)


def average_att(att: tfm.StadiumAttendance) -> str:
    markdown = f"[{att.team.name}]({att.team.link})"
    return f"[{att.name}]({att.link}) {att.average} ({markdown})"


def capacity(att: tfm.StadiumAttendance) -> str:
    markdown = f"[{att.team.name}]({att.team.link})"
    return f"[{att.name}]({att.link}) {att.capacity} ({markdown})"


def total_att(att: tfm.StadiumAttendance) -> str:
    markdown = f"[{att.team.name}]({att.team.link})"
    return f"[{att.name}]({att.link}) {att.total} ({markdown})"


async def attendance_embeds(comp: tfm.TFCompetition) -> list[discord.Embed]:
    rows = await comp.get_attendance()
    embeds: list[discord.Embed] = []
    # Average
    base = CompetitionEmbed(comp)
    base.url = comp.link.replace("startseite", "besucherzahlen")

    embed = base.copy()
    embed.title = f"Average Attendance data for {comp.name}"
    rows.sort(key=lambda x: x.average, reverse=True)

    enu = [f"{i[0]}: {average_att(i[1])}" for i in enumerate(rows, 1)]
    embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

    embed = base.copy()
    embed.title = f"Total Attendance data for {comp.name}"
    rows.sort(key=lambda x: x.total, reverse=True)

    enu = [f"{i[0]}: {total_att(i[1])}" for i in enumerate(rows, 1)]
    embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

    embed = base.copy()
    embed.title = f"Max Capacity data for {comp.name}"
    rows.sort(key=lambda x: x.capacity, reverse=True)

    enu = [f"{i[0]}: {capacity(i[1])}" for i in enumerate(rows, 1)]
    embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)
    return embeds


async def contract_embeds(team: tfm.TFTeam) -> list[discord.Embed]:
    contracts = await team.get_contracts()

    embed = TeamEmbed(team)
    embed.description = ""
    url = team.link.replace("startseite", "vertragsende")

    embed.title = f"Expiring contracts for {team.name}"
    embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
    embed.set_thumbnail(url=team.badge)

    rows: list[str] = []
    for i in contracts:
        flag = " ".join(flags.get_flags(i.player.country))
        expire = timed_events.Timestamp(i.expiry).countdown
        md = f"[{i.player.name}]({i.player.link})"
        opt = i.option if i.option else ""
        pos = i.player.position
        age = i.player.age
        rows.append(f"{expire} {flag} {md} ({age}, {pos}) {opt}")
    return embed_utils.rows_to_embeds(embed, rows)


async def rumour_embeds(team: tfm.TFTeam) -> list[discord.Embed]:
    """Generate a list of rumours embeds"""
    base = TeamEmbed(team)
    base.url = team.link.replace("startseite", "geruechte")
    base.title = f"Transfer rumours for {team.name}"

    rows: list[str] = []
    for i in await team.get_rumours():
        src = f"[Info]({i.url})"
        flg = " ".join(flags.get_flags(i.player.country))
        pmd = f"**[{i.player.name}]({i.player.link})**"
        tmd = f"[{i.team.name}]({i.team.link})"
        pos = i.player.position
        rows.append(f"{flg} {pmd} ({src})\n{i.player.age}, {pos} {tmd}\n")

    if not rows:
        rows = ["No rumours about new signings found."]

    return embed_utils.rows_to_embeds(base, rows)


async def transfer_embeds(team: tfm.TFTeam) -> list[discord.Embed]:
    url = team.link.replace("startseite", "transfers")

    inbound, outbound = await team.get_transfers()

    logger.info("Got %s inbound, %s outbound", len(inbound), len(outbound))
    base = TeamEmbed(team)
    base.url = url
    base.set_author(url=url, name=base.author.name)

    embeds: list[discord.Embed] = []
    if inbound:
        embed = base.copy()
        embed.title = f"Inbound Transfers for {embed.title}"
        embed.colour = discord.Colour.green()

        rows: list[str] = []
        for i in inbound:
            pmd = fmt_player(i.player)
            tmd = fmt_team(i.old_team)
            date = "" if i.date is None else f": {i.date}"
            fmd = f"[{i.fee.fee}]({i.fee.url}) {date}"

            rows.append(f"{pmd} {fmd}\nFrom: {tmd}\n")
        logger.info("in => sending %s rows", len(rows))
        inbeds = embed_utils.rows_to_embeds(embed, rows)
        logger.info("got %s inbeds", len(inbeds))
        embeds += inbeds

    if outbound:
        embed = base.copy()
        embed.title = f"Outbound Transfers for {embed.title}"
        embed.colour = discord.Colour.red()
        rows: list[str] = []
        for i in inbound:
            pmd = fmt_player(i.player)
            tmd = fmt_team(i.old_team)
            date = "" if i.date is None else f": {i.date}"
            fmd = f"[{i.fee.fee}]({i.fee.url}) {date}"
            rows.append(f"{pmd} {fmd}\nTo: {tmd}\n")
        logger.info("out => sending %s rows", len(rows))
        outbeds = embed_utils.rows_to_embeds(embed, rows)
        logger.info("got %s outbeds", len(outbeds))
        embeds += outbeds

    if not embeds:
        embed = base
        embed.title = f"No transfers found {embed.title}"
        embed.colour = discord.Colour.orange()
        embeds = [embed]
    return embeds


async def trophy_embeds(team: tfm.TFTeam) -> list[discord.Embed]:
    trophies = await team.get_trophies()

    url = team.link.replace("startseite", "erfolge")
    embed = TeamEmbed(team)
    embed.url = url
    embed.title = f"{team.name} Trophy Case"
    embed.set_author(name=embed.author.name, url=url)

    if not trophies:
        embed.description = "No Trophies found!"
        return [embed]

    rows: list[str] = []
    for i in trophies:
        rows.append(f"**{i.name}**\n{', '.join(i.dates)}\n")
    return embed_utils.rows_to_embeds(embed, rows, rows=5)


class SearchView(view_utils.Paginator):
    def __init__(
        self,
        invoker: User,
        search: tfm.TransfermarktSearch[tfm.ResultT],
        dropdown: bool = False,
    ) -> None:
        self.search: tfm.TransfermarktSearch[tfm.ResultT] = search
        self.value: tfm.ResultT | None = None

        max_pages = self.search.expected_results // 10

        super().__init__(invoker, max_pages)

        if not dropdown:
            self.remove_item(self.dropdown)
            return

        opts: list[discord.SelectOption] = []
        for i in self.search.results:
            desc = i.country[0] if i.country else ""
            if isinstance(i, tfm.TFTeam):
                desc += f"{i.league.name}" if i.league else ""
            opt = discord.SelectOption(label=i.name, value=i.link[:100])
            opt.description = desc
            try:
                opt.emoji = flags.get_flags(i.country)[0]
            except IndexError:
                pass
            opts.append(opt)

        if opts:
            self.dropdown.options = opts
        else:
            self.dropdown.disabled = True
            self.dropdown.placeholder = "No Results"
            self.dropdown.options = [discord.SelectOption(label="---")]

    @discord.ui.select(placeholder="Select matching result")
    async def dropdown(self, _: Interaction, sel: discord.ui.Select) -> None:
        res = self.search.results
        self.value = next(i for i in res if i.link[:100] in sel.values)
        self.stop()

    @classmethod
    async def browse(
        cls,
        interaction: Interaction,
        search: tfm.TransfermarktSearch[tfm.ResultT],
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)

        await search.get_page(1)
        srch = SearchView(interaction.user, search)
        embed = SearchEmbed(search)
        msg = await interaction.edit_original_response(embed=embed, view=srch)
        srch.message = msg

    @classmethod
    async def fetch(
        cls,
        interaction: Interaction,
        search: tfm.TransfermarktSearch[tfm.ResultT],
    ) -> SearchView:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)

        await search.get_page(1)
        ftch = SearchView(interaction.user, search, dropdown=True)
        embed = SearchEmbed(search)

        msg = await interaction.edit_original_response(embed=embed, view=ftch)
        ftch.message = msg
        return ftch

    async def handle_page(  # type: ignore
        self, interaction: Interaction
    ) -> None:
        await self.search.get_page(self.index + 1)
        self.update_buttons()
        embed = SearchEmbed(self.search)
        await interaction.response.edit_message(embed=embed, view=self)


class TeamView(view_utils.EmbedPaginator):
    """A View representing a Team on TransferMarkt"""

    def __init__(
        self, invoker: User, team: tfm.TFTeam, embeds: list[discord.Embed]
    ) -> None:
        super().__init__(invoker, embeds)
        self.team: tfm.TFTeam = team

    @discord.ui.button(label="Transfers", emoji="🔄", row=1)
    async def transfers(self, interaction: Interaction, _) -> None:
        """Push transfers to View"""
        await interaction.response.defer()
        embeds = await transfer_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.transfers.disabled = True
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Rumours", emoji="🕵", row=1)
    async def rumours(self, interaction: Interaction, _) -> None:
        """Send transfer rumours for a team to View"""
        await interaction.response.defer()
        embeds = await rumour_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.rumours.disabled = True
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Trophies", emoji="🏆")
    async def trophies(self, interaction: Interaction, _) -> None:
        """Send trophies for a team to View"""
        await interaction.response.defer()
        embeds = await trophy_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.trophies.disabled = True
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Contracts", emoji="📝")
    async def contracts(self, interaction: Interaction, _) -> None:
        """Push a list of a team's expiring contracts to the view"""
        await interaction.response.defer()
        embeds = await contract_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.contracts.disabled = True
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()


class CompetitionView(view_utils.EmbedPaginator):
    """A View representing a competition on TransferMarkt"""

    def __init__(
        self,
        invoker: User,
        comp: tfm.TFCompetition,
        embeds: list[discord.Embed],
    ) -> None:
        super().__init__(invoker, embeds)
        self.competition: tfm.TFCompetition = comp

    @discord.ui.button(label="Attendance", emoji="🏟️")
    async def attendance(self, interaction: Interaction, _) -> None:
        """Fetch attendances for league's stadiums."""
        embeds = await attendance_embeds(self.competition)
        atdv = CompetitionView(interaction.user, self.competition, embeds)
        await interaction.response.send_message(view=atdv, embed=embeds[0])


class SearchEmbed(discord.Embed):
    def __init__(self, search: tfm.TransfermarktSearch[tfm.ResultT]) -> None:
        super().__init__()
        self.title = f"{search.expected_results} results for {search.query}"
        self.url = search.current_url

        cat = search.category.title()
        self.set_author(name=f"TransferMarkt Search: {cat}", icon_url=FAVICON)
        if not search.results:
            self.description = "No Results Found"
        else:
            self.description = ""
            for i in search.results:
                flg = " ".join(flags.get_flags(i.country))
                self.description += f"{flg} [{i.name}]({i.link})\n"


class Lookup(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    lookup = Group(name="lookup", description="Search on transfermarkt")

    @lookup.command(name="player")
    @discord.app_commands.describe(name="Enter a player name")
    async def lookup_playr(self, interaction: Interaction, name: str) -> None:
        """Search for a player on TransferMarkt"""
        await SearchView.browse(interaction, tfm.PlayerSearch(name))

    @lookup.command(name="team")
    @discord.app_commands.describe(name="Enter a team name")
    async def lookup_team(self, interaction: Interaction, name: str) -> None:
        """Search for a team on TransferMarkt"""
        await SearchView.browse(interaction, tfm.TeamSearch(name))

    @lookup.command(name="staff")
    @discord.app_commands.describe(name="Enter a club official name")
    async def lookup_staff(self, interaction: Interaction, name: str) -> None:
        """Search for a club official on TransferMarkt"""
        await SearchView.browse(interaction, tfm.StaffSearch(name))

    @lookup.command(name="referee")
    @discord.app_commands.describe(name="Enter a referee name")
    async def lookup_refer(self, interaction: Interaction, name: str) -> None:
        """Search for a referee on TransferMarkt"""
        await SearchView.browse(interaction, tfm.RefereeSearch(name))

    @lookup.command(name="competition")
    @discord.app_commands.describe(name="Enter a competition name")
    async def lookup_comp(self, interaction: Interaction, name: str) -> None:
        """Search for a competition on TransferMarkt"""
        await SearchView.browse(interaction, tfm.CompetitionSearch(name))

    @lookup.command(name="agent")
    @discord.app_commands.describe(name="Enter an agency name")
    async def lookup_agent(self, interaction: Interaction, name: str) -> None:
        """Search for an agency on TransferMarkt"""
        await SearchView.browse(interaction, tfm.AgentSearch(name))

    transfer = Group(name="transfer", description="Transfers & Rumours")

    @transfer.command(name="list")
    @discord.app_commands.describe(name="enter a team name to search for")
    async def listing(self, interaction: Interaction, name: str) -> None:
        """Get this window's transfers for a team on transfermarkt"""
        await interaction.response.defer(thinking=True)
        view = await SearchView.fetch(interaction, tfm.TeamSearch(name))

        await view.wait()

        if not isinstance(team := view.value, tfm.TFTeam):
            return

        embeds = await transfer_embeds(team)
        view = TeamView(interaction.user, team, embeds)
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @transfer.command()
    @discord.app_commands.describe(name="enter a team name to search for")
    async def rumours(self, interaction: Interaction, name: str) -> None:
        """Get the latest transfer rumours for a team"""
        await interaction.response.defer(thinking=True)
        view = await SearchView.fetch(interaction, tfm.TeamSearch(name))

        await view.wait()

        if not isinstance(team := view.value, tfm.TFTeam):
            return

        embeds = await rumour_embeds(team)
        view = TeamView(interaction.user, team, embeds)
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(name="enter a team name to search for")
    async def contracts(self, interaction: Interaction, name: str) -> None:
        """Get a team's expiring contracts"""
        await interaction.response.defer(thinking=True)
        view = await SearchView.fetch(interaction, tfm.TeamSearch(name))

        await view.wait()

        if not isinstance(team := view.value, tfm.TFTeam):
            return

        embeds = await contract_embeds(team)
        view = TeamView(interaction.user, team, embeds)
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(name="enter a team name to search for")
    async def trophies(self, interaction: Interaction, name: str) -> None:
        """Get a team's trophy case"""
        await interaction.response.defer(thinking=True)
        view = await SearchView.fetch(interaction, tfm.TeamSearch(name))

        await view.wait()

        if not isinstance(team := view.value, tfm.TFTeam):
            return

        embeds = await trophy_embeds(team)
        view = TeamView(interaction.user, team, embeds)
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(name="enter a league name to search for")
    async def attendance(self, interaction: Interaction, name: str) -> None:
        """Get a list of a league's average attendances."""
        await interaction.response.defer(thinking=True)
        view = await SearchView.fetch(interaction, tfm.CompetitionSearch(name))

        await view.wait()

        if not isinstance(comp := view.value, tfm.TFCompetition):
            return

        embeds = await attendance_embeds(comp)
        view = CompetitionView(interaction.user, comp, embeds)
        await interaction.edit_original_response(view=view, embed=embeds[0])
        view.message = await interaction.original_response()


async def setup(bot: Bot) -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookup(bot))
