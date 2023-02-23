"""Commands for fetching information about football entities from
   transfermarkt"""
from __future__ import annotations

from importlib import reload
from typing import Optional, TYPE_CHECKING

from discord import Interaction, Message
from discord.app_commands import command, describe, Group
from discord.ext.commands import Cog

import ext.toonbot_utils.transfermarkt as tfm

if TYPE_CHECKING:
    from core import Bot


class Lookup(Cog):
    """Transfer market lookups"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(tfm)

    lookup = Group(
        name="lookup", description="Search for something on transfermarkt"
    )

    @lookup.command(name="player")
    @describe(query="Enter a player name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for a player on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.PlayerSearch(interaction, query).update()

    @lookup.command(name="team")
    @describe(query="Enter a team name")
    async def lookup_team(self, interaction: Interaction, query: str):
        """Search for a team on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.TeamSearch(interaction, query).update()

    @lookup.command(name="staff")
    @describe(query="Enter a club official name")
    async def lookup_staff(self, interaction: Interaction, query: str):
        """Search for a club official on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.StaffSearch(interaction, query).update()

    @lookup.command(name="referee")
    @describe(query="Enter a referee name")
    async def lookup_referee(self, interaction: Interaction, query: str):
        """Search for a referee on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.RefereeSearch(interaction, query).update()

    @lookup.command(name="competition")
    @describe(query="Enter a competition name")
    async def lookup_competition(self, interaction: Interaction, query: str):
        """Search for a competition on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.CompetitionSearch(interaction, query).update()

    @lookup.command(name="agent")
    @describe(query="Enter an agency name")
    async def lookup_agent(self, interaction: Interaction, query: str):
        """Search for an agency on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.AgentSearch(interaction, query).update()

    transfer = Group(
        name="transfer", description="Transfers & Rumours for a team"
    )

    @transfer.command(name="list")
    @describe(team_name="enter a team name to search for")
    async def listing(
        self, interaction: Interaction, team_name: str
    ) -> Message:
        """Get this window's transfers for a team on transfermarkt"""

        await interaction.response.defer(thinking=True)
        view = tfm.TeamSearch(interaction, team_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_transfers()

    @transfer.command()
    @describe(team_name="enter a team name to search for")
    async def rumours(
        self, interaction: Interaction, team_name: str
    ) -> Optional[Message]:
        """Get the latest transfer rumours for a team"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(interaction, team_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_rumours()

    @command()
    @describe(team_name="enter a team name to search for")
    async def contracts(
        self, interaction: Interaction, team_name: str
    ) -> Message:
        """Get a team's expiring contracts"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(interaction, team_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_contracts()

    @command()
    @describe(team_name="enter a team name to search for")
    async def trophies(
        self, interaction: Interaction, team_name: str
    ) -> Message:
        """Get a team's trophy case"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(interaction, team_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_trophies()

    @command()
    @describe(league_name="enter a league name to search for")
    async def attendance(
        self, interaction: Interaction, league_name: str
    ) -> Message:
        """Get a list of a league's average attendances."""

        await interaction.response.defer(thinking=True)

        view = tfm.CompetitionSearch(interaction, league_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).attendance()


async def setup(bot: Bot) -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookup(bot))
