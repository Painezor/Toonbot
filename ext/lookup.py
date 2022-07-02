"""Commands for fetching information about football entities from transfermarkt"""
from typing import Optional, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from core import Bot

from discord import Interaction, Message
from discord.app_commands import command, describe
from discord.ext.commands import Cog
from ext.utils.transfer_tools import SearchView

# TODO: HTTP Autocomplete


class Lookups(Cog):
    """Transfer market lookups"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    opts = Literal['player', 'team', 'staff', 'referee', 'competition', 'agent']

    @command()
    @describe(category='search within a category', query='enter search query')
    async def lookup(self, interaction: Interaction, category: Optional[opts], query: str) -> Message:
        """Perform a transfermarkt search for the designated category."""
        return await SearchView(interaction, query, category).update()

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


async def setup(bot: 'Bot') -> None:
    """Load the lookup cog into the bot"""
    await bot.add_cog(Lookups(bot))
