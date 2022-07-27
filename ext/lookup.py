"""Commands for fetching information about football entities from transfermarkt"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from discord import Interaction, Message
from discord.app_commands import command, describe, Group
from discord.ext.commands import Cog

from ext.toonbot_utils.transfermarkt import SearchView

if TYPE_CHECKING:
    from core import Bot


class Lookups(Cog):
    """Transfer market lookups"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    lookup = Group(name="lookup", description="Search for something on transfermarkt")

    @lookup.command(name="player")
    @describe(query="Enter a player name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for a player on TransferMarkt"""
        return await SearchView(interaction, query, 'player').update()

    @lookup.command(name="team")
    @describe(query="Enter a team name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for a team on TransferMarkt"""
        return await SearchView(interaction, query, 'team').update()

    @lookup.command(name="staff")
    @describe(query="Enter a club official name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for a club official on TransferMarkt"""
        return await SearchView(interaction, query, 'staff').update()

    @lookup.command(name="referee")
    @describe(query="Enter a referee name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for a referee on TransferMarkt"""
        return await SearchView(interaction, query, 'referee').update()

    @lookup.command(name="competition")
    @describe(query="Enter a competition name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for a competition on TransferMarkt"""
        return await SearchView(interaction, query, 'competition').update()

    @lookup.command(name="agent")
    @describe(query="Enter an agency name")
    async def lookup_player(self, interaction: Interaction, query: str):
        """Search for an agency on TransferMarkt"""
        return await SearchView(interaction, query, 'agent').update()

    @command()
    @describe(team_name="enter a team name to search for")
    async def transfers(self, interaction: Interaction, team_name: str) -> Message:
        """Get this window's transfers for a team on transfermarkt"""
        await interaction.response.defer(thinking=True)
        view = SearchView(interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_transfers()

    @command()
    @describe(team_name="name of a team")
    async def rumours(self, interaction: Interaction, team_name: str) -> Optional[Message]:
        """Get the latest transfer rumours for a team"""
        await interaction.response.defer(thinking=True)

        view = SearchView(interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_rumours()

    @command()
    @describe(team_name="name of a team")
    async def contracts(self, interaction: Interaction, team_name: str) -> Message:
        """Get a team's expiring contracts"""
        view = SearchView(interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_contracts()

    @command()
    @describe(team_name="name of a team")
    async def trophies(self, interaction: Interaction, team_name: str) -> Message:
        """Get a team's trophy case"""
        view = SearchView(interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).push_trophies()

    @command()
    @describe(query="league name to search for")
    async def attendance(self, interaction: Interaction, query: str) -> Message:
        """Get a list of a league's average attendances."""
        view = SearchView(interaction, query, category="competition", fetch=True)
        await view.update()
        await view.wait()

        if view.value:
            return await view.value.view(interaction).attendance()


async def setup(bot: Bot) -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookups(bot))
