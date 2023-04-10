"""Discord Transformers for various flashscore entities"""
from __future__ import annotations
import typing

import discord

from ext.utils import view_utils

from .competitions import Competition
from .fixture import Fixture
from .team import Team
from .search import search

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
    User: typing.TypeAlias = discord.User | discord.Member


# TODO: Replace typing.casts with an overload on search


async def set_default(
    interaction: Interaction,
    param: typing.Literal["default_league", "default_team"],
) -> None:
    """Fetch the default team or default league for this server"""
    if interaction.guild is None:
        interaction.extras["default"] = None
        return

    records = interaction.client.fixture_defaults
    gid = interaction.guild.id
    record = next((i for i in records if i["guild_id"] == gid), None)

    if record is None or record[param] is None:
        interaction.extras["default"] = None
        return

    if param == "default_team":
        default = interaction.client.get_team(record[param])
    else:
        default = interaction.client.get_competition(record[param])

    if default is None:
        interaction.extras["default"] = None
        return

    if (def_id := default.id) is None or (name := default.name) is None:
        interaction.extras["default"] = None
        return

    name = f"⭐ Server default: {name}"[:100]
    default = discord.app_commands.Choice(name=name, value=def_id)
    interaction.extras["default"] = default
    return


class TeamSelect(view_utils.DropdownPaginator):
    """View for asking user to select a specific fixture"""

    def __init__(self, invoker: User, teams: list[Team]) -> None:
        embed = discord.Embed(title="Choose a Team")

        options = []
        rows = []

        for team in teams:
            if team.id is None:
                continue

            opt = discord.SelectOption(label=team.name, value=team.id)
            opt.description = team.url
            opt.emoji = team.emoji
            options.append(opt)
            rows.append(f"`{team.id}` {team.markdown}\n")

        self.teams = teams
        super().__init__(invoker, embed, rows, options)

        # Value
        self.interaction: Interaction
        self.team: Team

    @discord.ui.select(placeholder="Choose a team")
    async def dropdown(self, itr: Interaction, sel: discord.ui.Select) -> None:
        self.team = next(i for i in self.teams if i.id == sel.values[0])
        self.interaction = itr
        return


class FixtureSelect(view_utils.DropdownPaginator):
    """View for asking user to select a specific fixture"""

    def __init__(self, invoker: User, fixtures: list[Fixture]):
        embed = discord.Embed(title="Choose a Fixture")

        rows = []
        options = []
        for i in fixtures:
            if i.id is None:
                continue

            opt = discord.SelectOption(label=i.score_line, value=i.id)
            if i.competition:
                opt.description = i.competition.title
            options.append(opt)
            rows.append(f"`{i.id}` {i.bold_markdown}")

        self.fixtures = fixtures
        super().__init__(invoker, embed, rows, options)

        # Final result
        self.fixture: Fixture
        self.interaction: Interaction

    @discord.ui.select(placeholder="Choose a fixture")
    async def dropdown(self, itr: Interaction, sel: discord.ui.Select) -> None:
        self.fixture = next(i for i in self.fixtures if i.id in sel.values)
        self.interaction = itr
        return


class CompetitionSelect(view_utils.DropdownPaginator):
    """View for asking user to select a specific fixture"""

    def __init__(self, invoker: User, competitions: list[Competition]) -> None:
        embed = discord.Embed(title="Choose a Competition")

        rows = []
        options = []
        for i in competitions:
            if i.id is None:
                continue

            opt = discord.SelectOption(label=i.title, value=i.id)
            opt.description = i.url
            opt.emoji = i.emoji
            rows.append(f"`{i.id}` {i.markdown}")
            options.append(opt)

        self.comps = competitions
        super().__init__(invoker, embed, rows, options)

        self.competition: Competition
        self.interaction: Interaction

    @discord.ui.select(placeholder="Select a competition")
    async def dropdown(self, itr: Interaction, sel: discord.ui.Select) -> None:
        self.competition = next(i for i in self.comps if i.id == sel.values[0])
        self.interaction = itr
        return


async def choose_recent_fixture(
    interaction: Interaction, fsr: Competition | Team
) -> Fixture:
    """Allow the user to choose from the most recent games of a fixture"""
    cache = interaction.client.competitions
    page = await interaction.client.browser.new_page()
    try:
        fixtures = await fsr.results(page, cache)
    finally:
        await page.close()

    view = FixtureSelect(interaction.user, fixtures)
    await interaction.response.edit_message(view=view, embed=view.pages[0])
    await view.wait()

    if not view.fixture:
        raise TimeoutError
    return view.fixture


class TeamTransformer(discord.app_commands.Transformer):
    """Convert user Input to a Team Object"""

    async def autocomplete(
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = interaction.client.teams
        teams.sort(key=lambda x: x.name)

        # Run Once - Set Default for interaction.
        if "default" not in interaction.extras:
            await set_default(interaction, "default_team")

        curr = current.casefold()

        choices = []
        for i in teams:
            if i.id is None:
                continue

            if curr not in i.title.casefold():
                continue

            choice = discord.app_commands.Choice(name=i.name[:100], value=i.id)
            choices.append(choice)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [discord.app_commands.Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[Team]:
        await interaction.response.defer(thinking=True)

        if fsr := interaction.client.get_team(value):
            return fsr

        teams = await search(value, "team", interaction)
        teams = typing.cast(list[Team], teams)

        view = TeamSelect(interaction.user, teams)
        await interaction.response.edit_message(view=view, embed=view.pages[0])
        await view.wait()
        return view.team


# Autocompletes
class FixtureTransformer(discord.app_commands.Transformer):
    """Convert User Input to a fixture Object"""

    async def autocomplete(
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Check if user's typing is in list of live games"""
        cur = current.casefold()

        choices = []
        for i in interaction.client.games:
            ac_row = i.ac_row.casefold()
            if cur and cur not in ac_row:
                continue

            if i.id is None:
                continue

            name = i.ac_row[:100]
            choice = discord.app_commands.Choice(name=name, value=i.id)

            choices.append(choice)

            if len(choices) == 25:
                break

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [discord.app_commands.Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[Fixture]:
        if fix := interaction.client.get_fixture(value):
            return fix

        if fsr := interaction.client.get_team(value):
            return await choose_recent_fixture(interaction, fsr)

        teams = await search(value, "team", interaction)
        teams = typing.cast(list[Team], teams)

        view = TeamSelect(interaction.user, teams)
        embed = view.pages[0]
        await interaction.response.send_message(view=view, embed=embed)

        await view.wait()

        if not view.team:
            return None

        fsr = view.team
        await choose_recent_fixture(view.interaction, fsr)


class TFCompetitionTransformer(discord.app_commands.Transformer):
    """Converts user input to a Competition object"""

    async def autocomplete(
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored competitions"""
        lgs = sorted(interaction.client.competitions, key=lambda x: x.title)

        if "default" not in interaction.extras:
            await set_default(interaction, "default_league")

        curr = current.casefold()

        choices = []

        for i in lgs:
            if curr not in i.title.casefold() or i.id is None:
                continue

            opt = discord.app_commands.Choice(name=i.title[:100], value=i.id)

            choices.append(opt)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices[:24]

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [discord.app_commands.Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[Competition]:
        await interaction.response.defer(thinking=True)

        if fsr := interaction.client.get_competition(value):
            return fsr

        if "http" in value:
            return await Competition.by_link(interaction.client, value)

        comps = await search(value, "comp", interaction)
        comps = typing.cast(list[Competition], comps)

        view = CompetitionSelect(interaction.user, comps)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        await view.wait()
        return view.competition


Transform: typing.TypeAlias = discord.app_commands.Transform
comp_trnsf: typing.TypeAlias = Transform[Competition, TFCompetitionTransformer]
fix_trnsf: typing.TypeAlias = Transform[Fixture, FixtureTransformer]
team_trnsf: typing.TypeAlias = Transform[Team, TeamTransformer]
