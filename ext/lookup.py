"""Commands for fetching information about football entities from
   transfermarkt"""
from __future__ import annotations

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


def player_to_string(player: tfm.TFPlayer) -> str:
    flg = flags.get_flags(player.country)
    md = f"[{player.name}]({player.link})"
    desc = [" ".join(flg), md, player.age, player.position]

    if player.team is not None:
        desc.append(f"[{player.team.name}]({player.team.link})")
    return " ".join([str(i) for i in desc if i])


def team_to_string(team: tfm.TFTeam) -> str:
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
        flag = [i for i in flags.get_flags(i.country) if i]
        expire = timed_events.Timestamp(i.expiry).countdown
        md = f"[{i.name}]({i.link})"
        opt = i.option if i.option else ""
        rows.append(f"{flag} {md} ({i.position} {i.age}){expire} {opt}")
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
            pmd = player_to_string(i.player)
            tmd = team_to_string(i.old_team)
            date = "" if i.date is None else f": {i.date}"
            fmd = f"[{i.fee.fee}]({i.fee.url}) {date}"

            rows.append(f"{pmd} {fmd}\nFrom: {tmd}\n")
        embeds += embed_utils.rows_to_embeds(embed, rows)

    if outbound:
        embed = base.copy()
        embed.title = f"Outbound Transfers for {embed.title}"
        embed.colour = discord.Colour.red()
        rows: list[str] = []
        for i in inbound:
            pmd = player_to_string(i.player)
            tmd = team_to_string(i.old_team)
            date = "" if i.date is None else f": {i.date}"
            fmd = f"[{i.fee.fee}]({i.fee.url}) {date}"
            rows.append(f"{pmd} {fmd}\nTo: {tmd}\n")
        embeds += embed_utils.rows_to_embeds(embed, rows)

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


class SearchView(view_utils.AsyncPaginator):
    def __init__(
        self, invoker: User, search: tfm.TransfermarktSearch[tfm.ResultT]
    ) -> None:
        self.search: tfm.TransfermarktSearch[tfm.ResultT] = search
        max_pages = self.search.expected_results // 10
        super().__init__(invoker, max_pages)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        search: tfm.TransfermarktSearch[tfm.ResultT],
    ) -> None:
        view = SearchView(interaction.user, search)
        await search.get_page(1)
        embed = SearchEmbed(search)
        await interaction.response.send_message(embed=embed, view=view)

    async def handle_page(  # type: ignore
        self, interaction: Interaction
    ) -> None:
        await self.search.get_page(self.index + 1)
        embed = SearchEmbed(self.search)
        await interaction.response.edit_message(embed=embed, view=self)


class TeamView(view_utils.Paginator):
    """A View representing a Team on TransferMarkt"""

    def __init__(
        self, invoker: User, team: tfm.TFTeam, embeds: list[discord.Embed]
    ) -> None:
        super().__init__(invoker, embeds)
        self.team: tfm.TFTeam = team

    @discord.ui.button(label="Transfers", emoji="🔄", row=1)
    async def transfers(self, interaction: Interaction, _) -> None:
        """Push transfers to View"""
        embeds = await transfer_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.transfers.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Rumours", emoji="🕵", row=1)
    async def rumours(self, interaction: Interaction, _) -> None:
        """Send transfer rumours for a team to View"""
        embeds = await rumour_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.rumours.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Trophies", emoji="🏆")
    async def trophies(self, interaction: Interaction, _) -> None:
        """Send trophies for a team to View"""
        embeds = await trophy_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.trophies.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Contracts", emoji="📝")
    async def contracts(self, interaction: Interaction, _) -> None:
        """Push a list of a team's expiring contracts to the view"""
        embeds = await contract_embeds(self.team)
        view = TeamView(interaction.user, self.team, embeds)
        view.contracts.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


class CompetitionView(view_utils.Paginator):
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
        view = CompetitionView(interaction.user, self.competition, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])


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
            self.description = "\n".join(str(i) for i in search.results)


class TFPaginator(view_utils.AsyncPaginator):
    value: tfm.SearchResult
    interaction: Interaction

    def __init__(
        self, invoker: User, search: tfm.TransfermarktSearch[tfm.ResultT]
    ):
        max_pages = search.expected_results // 10
        super().__init__(invoker, max_pages)

        self.search = search

        options: list[discord.SelectOption] = []
        rows: list[str] = []
        for i in search.results:
            desc = i.country[0] if i.country else ""

            if isinstance(i, tfm.TFTeam):
                desc += f": {i.league.name}" if i.league else ""

            option = discord.SelectOption(label=i.name, value=i.link)
            option.description = desc[:100]
            option.emoji = flags.get_flags(i.country)[0]
            options.append(option)
            rows.append(desc)

    async def handle_page(  # type: ignore
        self, interaction: Interaction
    ) -> None:
        await self.search.get_page(self.index + 1)  # We index from 1.
        return await super().handle_page(interaction)

    @discord.ui.select(row=4, placeholder="Select correct item")
    async def dropdown(
        self,
        itr: Interaction,
        sel: discord.ui.Select[TFPaginator],
    ) -> None:
        """Set self.value to target object"""
        self.value = next(
            i for i in self.search.results if i.link in sel.values
        )
        self.interaction = itr


class Lookup(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    lookup = Group(name="lookup", description="Search on transfermarkt")

    @lookup.command(name="player")
    @discord.app_commands.describe(name="Enter a player name")
    async def lookup_playr(self, interaction: Interaction, name: str) -> None:
        """Search for a player on TransferMarkt"""
        await SearchView.start(interaction, tfm.PlayerSearch(name))

    @lookup.command(name="team")
    @discord.app_commands.describe(name="Enter a team name")
    async def lookup_team(self, interaction: Interaction, name: str) -> None:
        """Search for a team on TransferMarkt"""
        await SearchView.start(interaction, tfm.TeamSearch(name))

    @lookup.command(name="staff")
    @discord.app_commands.describe(name="Enter a club official name")
    async def lookup_staff(self, interaction: Interaction, name: str) -> None:
        """Search for a club official on TransferMarkt"""
        await SearchView.start(interaction, tfm.StaffSearch(name))

    @lookup.command(name="referee")
    @discord.app_commands.describe(name="Enter a referee name")
    async def lookup_refer(self, interaction: Interaction, name: str) -> None:
        """Search for a referee on TransferMarkt"""
        await SearchView.start(interaction, tfm.RefereeSearch(name))

    @lookup.command(name="competition")
    @discord.app_commands.describe(name="Enter a competition name")
    async def lookup_comp(self, interaction: Interaction, name: str) -> None:
        """Search for a competition on TransferMarkt"""
        await SearchView.start(interaction, tfm.CompetitionSearch(name))

    @lookup.command(name="agent")
    @discord.app_commands.describe(name="Enter an agency name")
    async def lookup_agent(self, interaction: Interaction, name: str) -> None:
        """Search for an agency on TransferMarkt"""
        await SearchView.start(interaction, tfm.AgentSearch(name))

    transfer = Group(name="transfer", description="Transfers & Rumours")

    @transfer.command(name="list")
    @discord.app_commands.describe(name="enter a team name to search for")
    async def listing(self, interaction: Interaction, name: str) -> None:
        """Get this window's transfers for a team on transfermarkt"""
        search = tfm.TeamSearch(name)
        await SearchView(interaction.user, search).start(interaction)

        if view is None:
            return

        await view.wait()

        if not (team := view.value):
            return

        embeds = await team.get_transfers()
        view = TeamView(interaction.user, team, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @transfer.command()
    @discord.app_commands.describe(name="enter a team name to search for")
    async def rumours(self, interaction: Interaction, name: str) -> None:
        """Get the latest transfer rumours for a team"""
        view = await tfm.TeamSearch.search(name, interaction)

        if view is None:
            return

        await view.wait()

        if not (team := view.value):
            return

        embeds = await team.get_rumours()
        view = TeamView(interaction.user, team, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(name="enter a team name to search for")
    async def contracts(self, interaction: Interaction, name: str) -> None:
        """Get a team's expiring contracts"""
        view = await tfm.TeamSearch.search(name, interaction)

        if view is None:
            return

        await view.wait()

        if not (team := view.value):
            return

        embeds = await team.get_contracts()
        view = TeamView(interaction.user, team, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(name="enter a team name to search for")
    async def trophies(self, interaction: Interaction, name: str) -> None:
        """Get a team's trophy case"""
        view = await tfm.TeamSearch.search(name, interaction)

        if view is None:
            return

        await view.wait()

        if not (team := view.value):
            return

        embeds = await team.get_trophies()
        view = TeamView(interaction.user, team, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(name="enter a league name to search for")
    async def attendance(self, interaction: Interaction, name: str) -> None:
        """Get a list of a league's average attendances."""
        view = await tfm.CompetitionSearch.search(name, interaction)
        if view is None:
            return

        await view.wait()

        if not (comp := view.value):
            return

        embeds = await attendance_embeds(comp)
        view = CompetitionView(interaction.user, comp, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


async def setup(bot: Bot) -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookup(bot))
