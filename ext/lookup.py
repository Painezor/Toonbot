"""Commands for fetching information about football entities from
   transfermarkt"""
from __future__ import annotations

from importlib import reload
import typing

import discord
from discord.ext import commands

import ext.toonbot_utils.transfermarkt as tfm


if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]


class Lookup(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(tfm)

    lookup = discord.app_commands.Group(description="Search on transfermarkt")

    @lookup.command(name="player")
    @discord.app_commands.describe(query="Enter a player name")
    async def lookup_player(
        self, interaction: Interaction, query: str
    ) -> None:
        """Search for a player on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.PlayerSearch(query).update(interaction)

    @lookup.command(name="team")
    @discord.app_commands.describe(query="Enter a team name")
    async def lookup_team(self, interaction: Interaction, query: str) -> None:
        """Search for a team on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.TeamSearch(query).update(interaction)

    @lookup.command(name="staff")
    @discord.app_commands.describe(query="Enter a club official name")
    async def lookup_staff(self, interaction: Interaction, query: str) -> None:
        """Search for a club official on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.StaffSearch(query).update(interaction)

    @lookup.command(name="referee")
    @discord.app_commands.describe(query="Enter a referee name")
    async def lookup_referee(
        self, interaction: Interaction, query: str
    ) -> None:
        """Search for a referee on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.RefereeSearch(query).update(interaction)

    @lookup.command(name="competition")
    @discord.app_commands.describe(query="Enter a competition name")
    async def lookup_competition(
        self, interaction: Interaction, query: str
    ) -> None:
        """Search for a competition on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.CompetitionSearch(query).update(interaction)

    @lookup.command(name="agent")
    @discord.app_commands.describe(query="Enter an agency name")
    async def lookup_agent(self, interaction: Interaction, query: str) -> None:
        """Search for an agency on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.AgentSearch(query).update(interaction)

    transfer = discord.app_commands.Group(
        name="transfer", description="Transfers & Rumours for a team"
    )

    @transfer.command(name="list")
    @discord.app_commands.describe(team_name="enter a team name to search for")
    async def listing(self, interaction: Interaction, team_name: str) -> None:
        """Get this window's transfers for a team on transfermarkt"""

        await interaction.response.defer(thinking=True)
        view = tfm.TeamSearch(team_name, fetch=True)
        await view.update(interaction)
        await view.wait()

        return await tfm.TeamView(view.value).push_transfers(interaction)

    @transfer.command()
    @discord.app_commands.describe(team_name="enter a team name to search for")
    async def rumours(self, interaction: Interaction, team_name: str) -> None:
        """Get the latest transfer rumours for a team"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(team_name, fetch=True)
        await view.update(interaction)
        await view.wait()

        return await tfm.TeamView(view.value).push_rumours(interaction)

    @discord.app_commands.command()
    @discord.app_commands.describe(team="enter a team name to search for")
    async def contracts(self, interaction: Interaction, team: str) -> None:
        """Get a team's expiring contracts"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(team, fetch=True)
        await view.update(interaction)
        await view.wait()

        return await tfm.TeamView(view.value).push_contracts(interaction)

    @discord.app_commands.command()
    @discord.app_commands.describe(team="enter a team name to search for")
    async def trophies(self, interaction: Interaction, team: str) -> None:
        """Get a team's trophy case"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(team, fetch=True)
        await view.update(interaction)
        await view.wait()
        return await tfm.TeamView(view.value).push_trophies(interaction)

    @discord.app_commands.command()
    @discord.app_commands.describe(
        league_name="enter a league name to search for"
    )
    async def attendance(
        self, interaction: Interaction, league_name: str
    ) -> None:
        """Get a list of a league's average attendances."""

        await interaction.response.defer(thinking=True)

        view = tfm.CompetitionSearch(league_name, fetch=True)
        await view.update(interaction)
        await view.wait()

        comp = view.value
        if comp is None:
            await interaction.edit_original_response(content="Not found")
            return  # shrug

        view = tfm.CompetitionView(comp)
        return await view.attendance(interaction)


async def setup(bot: Bot) -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookup(bot))
