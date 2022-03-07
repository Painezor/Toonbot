"""Commands for fetching information about football entities from transfermarkt"""
from importlib import reload

from discord import app_commands, Interaction
from discord.ext import commands

from ext.utils import transfer_tools


# TODO: Permissions Pass.

class Lookup(app_commands.Group):
    """Look a query up on TransferMarkt"""

    @app_commands.command()
    @app_commands.describe(player_name="search for a player by name")
    async def player(self, interaction: Interaction, player_name):
        """Search for a player on transfermarkt"""
        view = transfer_tools.SearchView(interaction, player_name, category="Players")
        await view.update()

    @app_commands.command()
    @app_commands.describe(team_name="search for a team by name")
    async def team(self, interaction: Interaction, team_name):
        """Lookup a team on transfermarkt"""
        view = transfer_tools.SearchView(interaction, team_name, category="Clubs")
        await view.update()

    @app_commands.command()
    @app_commands.describe(name="search for a club official by name")
    async def staff(self, interaction: Interaction, name):
        """Lookup a manager, trainer, or club official on transfermarkt"""
        view = transfer_tools.SearchView(interaction, name, category="Managers")
        await view.update()

    @app_commands.command()
    @app_commands.describe(name="search for a referee by name")
    async def referee(self, interaction: Interaction, name):
        """Lookup a referee on transfermarkt"""
        view = transfer_tools.SearchView(interaction, name, category="Referees")
        await view.update()

    @app_commands.command()
    @app_commands.describe(name="search for a competition by name")
    async def competition(self, interaction: Interaction, name):
        """Lookup a competition on transfermarkt"""
        view = transfer_tools.SearchView(interaction, name, category="Competitions")
        await view.update()

    @app_commands.command()
    @app_commands.describe(name="search for an agent by name")
    async def agent(self, interaction: Interaction, name):
        """Lookup an agent on transfermarkt"""
        view = transfer_tools.SearchView(interaction, name, category="Agents")
        await view.update()


@app_commands.command()
@app_commands.describe(team_name="name of a team")
async def transfers(interaction: Interaction, team_name):
    """Get this window's transfers for a team on transfermarkt"""
    view = transfer_tools.SearchView(interaction, team_name, category="Clubs", fetch=True)
    await view.update()

    if view.value is None:
        return

    view = view.value.view(interaction)
    await view.push_transfers()


@app_commands.command()
@app_commands.describe(team_name="name of a team")
async def rumours(interaction: Interaction, team_name):
    """Get the latest transfer rumours for a team"""
    view = transfer_tools.SearchView(interaction, team_name, category="Clubs", fetch=True)
    await view.update()

    if view.value is None:
        return

    view = view.value.view(interaction)
    await view.push_rumours()


@app_commands.command()
@app_commands.describe(team_name="name of a team")
async def contracts(interaction: Interaction, team_name):
    """Get a team's expiring contracts"""
    view = transfer_tools.SearchView(interaction, team_name, category="Clubs", fetch=True)
    await view.update()

    if view.value is None:
        return

    view = view.value.view(interaction)
    await view.push_contracts()


@app_commands.command()
@app_commands.describe(team_name="name of a team")
async def trophies(interaction: Interaction, team_name):
    """Get a team's trophy case"""
    view = transfer_tools.SearchView(interaction, team_name, category="Clubs", fetch=True)
    await view.update()

    if view.value is None:
        return

    view = view.value.view(interaction)
    await view.push_trophies()


# TODO: Attendance Command
@app_commands.command()
@app_commands.describe(query="league name to search for")
async def attendance(interaction: Interaction, query):
    """Get a list of a league's average attendances."""
    if interaction.user.id != interaction.client.owner_id:
        return await interaction.client.error(interaction, "You do not own this bot.")

    view = transfer_tools.SearchView(interaction, query, category="Competitions", fetch=True)
    await view.update()

    if view.value is None:
        return

    view = view.value.view(interaction)
    if view is not None:
        await view.push_attendance()


class Lookups(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(Lookup())
        self.bot.tree.add_command(transfers)
        self.bot.tree.add_command(rumours)
        reload(transfer_tools)


def setup(bot):
    """Load the lookup cog into the bot"""
    bot.add_cog(Lookups(bot))
