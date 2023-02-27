"""Commands for fetching information about football entities from
   transfermarkt"""
from __future__ import annotations

from importlib import reload
from typing import Optional, TYPE_CHECKING

import discord
from discord import Interaction, Message
from discord.app_commands import Group
from discord.ext.commands import Cog

import ext.toonbot_utils.transfermarkt as tfm

if TYPE_CHECKING:
    from core import Bot


class Lookup(Cog):
    """Transfer market lookups"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(tfm)

    lookup = Group(name="lookup", description="Search on transfermarkt")

    @lookup.command(name="player")
    @discord.app_commands.describe(query="Enter a player name")
    async def lookup_player(self, interaction: Interaction[Bot], query: str):
        """Search for a player on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.PlayerSearch(interaction, query).update()

    @lookup.command(name="team")
    @discord.app_commands.describe(query="Enter a team name")
    async def lookup_team(self, interaction: Interaction[Bot], query: str):
        """Search for a team on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.TeamSearch(interaction, query).update()

    @lookup.command(name="staff")
    @discord.app_commands.describe(query="Enter a club official name")
    async def lookup_staff(self, interaction: Interaction[Bot], query: str):
        """Search for a club official on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.StaffSearch(interaction, query).update()

    @lookup.command(name="referee")
    @discord.app_commands.describe(query="Enter a referee name")
    async def lookup_referee(self, interaction: Interaction[Bot], query: str):
        """Search for a referee on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.RefereeSearch(interaction, query).update()

    @lookup.command(name="competition")
    @discord.app_commands.describe(query="Enter a competition name")
    async def lookup_competition(
        self, interaction: Interaction[Bot], query: str
    ):
        """Search for a competition on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.CompetitionSearch(interaction, query).update()

    @lookup.command(name="agent")
    @discord.app_commands.describe(query="Enter an agency name")
    async def lookup_agent(self, interaction: Interaction[Bot], query: str):
        """Search for an agency on TransferMarkt"""

        await interaction.response.defer(thinking=True)
        return await tfm.AgentSearch(interaction, query).update()

    transfer = Group(
        name="transfer", description="Transfers & Rumours for a team"
    )

    @transfer.command(name="list")
    @discord.app_commands.describe(team_name="enter a team name to search for")
    async def listing(
        self, interaction: Interaction[Bot], team_name: str
    ) -> None:
        """Get this window's transfers for a team on transfermarkt"""

        await interaction.response.defer(thinking=True)
        view = tfm.TeamSearch(interaction, team_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            await view.value.view(interaction).push_transfers()

    @transfer.command()
    @discord.app_commands.describe(team_name="enter a team name to search for")
    async def rumours(
        self, interaction: Interaction[Bot], team_name: str
    ) -> discord.InteractionMessage:
        """Get the latest transfer rumours for a team"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(interaction, team_name, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_rumours()

    @discord.app_commands.command()
    @discord.app_commands.describe(team="enter a team name to search for")
    async def contracts(self, ctx: Interaction[Bot], team: str) -> None:
        """Get a team's expiring contracts"""

        await ctx.response.defer(thinking=True)

        view = tfm.TeamSearch(ctx, team, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(ctx).push_contracts()

    @discord.app_commands.command()
    @discord.app_commands.describe(team="enter a team name to search for")
    async def trophies(self, interaction: Interaction[Bot], team: str) -> None:
        """Get a team's trophy case"""

        await interaction.response.defer(thinking=True)

        view = tfm.TeamSearch(interaction, team, fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_trophies()

    @discord.app_commands.command()
    @discord.app_commands.describe(
        league_name="enter a league name to search for"
    )
    async def attendance(
        self, interaction: Interaction[Bot], league_name: str
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
