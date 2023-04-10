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

    lookup = discord.app_commands.Group(
        name="lookup", description="Search on transfermarkt"
    )

    @lookup.command(name="player")
    @discord.app_commands.describe(name="Enter a player name")
    async def lookup_playr(self, interaction: Interaction, name: str) -> None:
        """Search for a player on TransferMarkt"""
        await tfm.PlayerSearch.search(name, interaction)

    @lookup.command(name="team")
    @discord.app_commands.describe(name="Enter a team name")
    async def lookup_team(self, interaction: Interaction, name: str) -> None:
        """Search for a team on TransferMarkt"""
        await tfm.TeamSearch.search(name, interaction)

    @lookup.command(name="staff")
    @discord.app_commands.describe(name="Enter a club official name")
    async def lookup_staff(self, interaction: Interaction, name: str) -> None:
        """Search for a club official on TransferMarkt"""
        await tfm.StaffSearch.search(name, interaction)

    @lookup.command(name="referee")
    @discord.app_commands.describe(name="Enter a referee name")
    async def lookup_refer(self, interaction: Interaction, name: str) -> None:
        """Search for a referee on TransferMarkt"""
        await tfm.RefereeSearch.search(name, interaction)

    @lookup.command(name="competition")
    @discord.app_commands.describe(name="Enter a competition name")
    async def lookup_comp(self, interaction: Interaction, name: str) -> None:
        """Search for a competition on TransferMarkt"""
        await tfm.CompetitionSearch.search(name, interaction)

    @lookup.command(name="agent")
    @discord.app_commands.describe(name="Enter an agency name")
    async def lookup_agent(self, interaction: Interaction, name: str) -> None:
        """Search for an agency on TransferMarkt"""
        await tfm.AgentSearch.search(name, interaction)

    transfer = discord.app_commands.Group(
        name="transfer", description="Transfers & Rumours for a team"
    )

    @transfer.command(name="list")
    @discord.app_commands.describe(name="enter a team name to search for")
    async def listing(self, interaction: Interaction, name: str) -> None:
        """Get this window's transfers for a team on transfermarkt"""
        view = await tfm.TeamSearch.search(name, interaction)

        if view is None:
            return

        await view.wait()

        if not (team := view.value):
            return

        embeds = await team.get_transfers()
        view = tfm.TeamView(interaction.user, team, embeds)
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
        view = tfm.TeamView(interaction.user, team, embeds)
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
        view = tfm.TeamView(interaction.user, team, embeds)
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
        view = tfm.TeamView(interaction.user, team, embeds)
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

        embeds = await comp.get_attendance()
        view = tfm.CompetitionView(interaction.user, comp, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


async def setup(bot: Bot) -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookup(bot))
