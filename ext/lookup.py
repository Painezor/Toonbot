"""Commands for fetching information about football entities from transfermarkt"""
from importlib import reload
from typing import Optional, Literal

from discord import Interaction
from discord.app_commands import command, describe, guilds
from discord.ext import commands

from ext.utils import transfer_tools
from ext.utils.transfer_tools import TeamView, CompetitionView


# TODO: HTTP Autocomplete



class Lookups(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot) -> None:
        self.bot = bot
        reload(transfer_tools)

    opts = Literal['player', 'team', 'staff', 'referee', 'competition', 'agent']

    @command()
    @describe(category='search within a category', query='enter search query')
    async def lookup(self, interaction: Interaction, category: Optional[opts], query: str):
        """Perform a transfermarkt search for the designated category."""
        await transfer_tools.SearchView(self.bot, interaction, query, category).update()

    @command()
    @describe(team_name="name of a team")
    async def transfers(self, interaction: Interaction, team_name: str):
        """Get this window's transfers for a team on transfermarkt"""
        view = transfer_tools.SearchView(self.bot, interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value is None:
            return

        await TeamView(self.bot, interaction, view.value).push_transfers()

    @command()
    @describe(team_name="name of a team")
    async def rumours(self, interaction: Interaction, team_name: str):
        """Get the latest transfer rumours for a team"""
        await interaction.response.defer(thinking=True)

        view = transfer_tools.SearchView(self.bot, interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value is None:
            return

        await TeamView(self.bot, interaction, view.value).push_rumours()

    @command()
    @describe(team_name="name of a team")
    async def contracts(self, interaction: Interaction, team_name: str):
        """Get a team's expiring contracts"""
        view = transfer_tools.SearchView(self.bot, interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value is None:
            return

        await TeamView(self.bot, interaction, view.value).push_contracts()

    @command()
    @describe(team_name="name of a team")
    async def trophies(self, interaction: Interaction, team_name: str):
        """Get a team's trophy case"""
        view = transfer_tools.SearchView(self.bot, interaction, team_name, category="team", fetch=True)
        await view.update()
        await view.wait()

        if view.value is None:
            return

        await TeamView(self.bot, interaction, view.value).push_trophies()

    @command()
    @describe(query="league name to search for")
    @guilds(250252535699341312)
    async def attendance(self, interaction: Interaction, query: str):
        """Get a list of a league's average attendances."""
        view = transfer_tools.SearchView(self.bot, interaction, query, category="competition", fetch=True)
        await view.update()
        await view.wait()

        if view.value is None:
            return

        await CompetitionView(self.bot, interaction, view.value).push_attendance()


async def setup(bot):
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookups(bot))
