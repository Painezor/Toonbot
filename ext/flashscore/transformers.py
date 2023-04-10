"""Discord Transformers for various flashscore entities"""
from __future__ import annotations

import logging
import typing
from urllib.parse import quote

import discord

from ext.utils import view_utils

from .competitions import Competition
from .fixture import Fixture
from .team import Team

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
    User: typing.TypeAlias = discord.User | discord.Member

logger = logging.getLogger("flashscore.transformers")

# TODO: Replace typing.casts with an overload on search


# slovak - 7
# Hebrew - 17
# Slovenian - 24
# Estonian - 26
# Indonesian - 35
# Catalan - 43
# Georgian - 44

locales = {
    discord.Locale.american_english: 1,  # 'en-US'
    discord.Locale.british_english: 1,  # 'en-GB' flashscore.co.uk
    discord.Locale.bulgarian: 40,  # 'bg'
    discord.Locale.chinese: 19,  # 'zh-CN'
    discord.Locale.taiwan_chinese: 19,  # 'zh-TW'
    discord.Locale.french: 16,  # 'fr'    flashscore.fr
    discord.Locale.croatian: 14,  # 'hr'  # Could also be 25?
    discord.Locale.czech: 2,  # 'cs'
    discord.Locale.danish: 8,  # 'da'
    discord.Locale.dutch: 21,  # 'nl'
    discord.Locale.finnish: 18,  # 'fi'
    discord.Locale.german: 4,  # 'de'
    discord.Locale.greek: 11,  # 'el'
    discord.Locale.hindi: 1,  # 'hi'
    discord.Locale.hungarian: 15,  # 'hu'
    discord.Locale.italian: 6,  # 'it'
    discord.Locale.japanese: 42,  # 'ja'
    discord.Locale.korean: 38,  # 'ko'
    discord.Locale.lithuanian: 27,  # 'lt'
    discord.Locale.norwegian: 23,  # 'no'
    discord.Locale.polish: 3,  # 'pl'
    discord.Locale.brazil_portuguese: 20,  # 'pt-BR'   # Could also be 31
    discord.Locale.romanian: 9,  # 'ro'
    discord.Locale.russian: 12,  # 'ru'
    discord.Locale.spain_spanish: 13,  # 'es-ES'
    discord.Locale.swedish: 28,  # 'sv-SE'
    discord.Locale.thai: 1,  # 'th'
    discord.Locale.turkish: 10,  # 'tr'
    discord.Locale.ukrainian: 41,  # 'uk'
    discord.Locale.vietnamese: 37,  # 'vi'
}


async def search(
    query: str,
    mode: typing.Literal["comp", "team"],
    interaction: Interaction,
) -> list[Competition | Team]:
    """Fetch a list of items from flashscore matching the user's query"""
    replace = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))
    query = quote(replace)

    try:
        lang_id = locales[interaction.locale]
    except KeyError:
        try:
            if interaction.guild_locale is None:
                lang_id = 1
            else:
                lang_id = locales[interaction.guild_locale]
        except KeyError:
            lang_id = 1

    # Type IDs: 1 - Team | Tournament, 2 - Team, 3 - Player 4 - PlayerInTeam
    url = (
        f"https://s.livesport.services/api/v2/search/?q={query}"
        f"&lang-id={lang_id}&type-ids=1,2,3,4&sport-ids=1"
    )

    async with interaction.client.session.get(url) as resp:
        if resp.status != 200:
            logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
        res = await resp.json()

    results: list[Competition | Team] = []

    for i in res:
        if i["participantTypes"] is None:
            if i["type"]["name"] == "TournamentTemplate":
                id_ = i["id"]
                name = i["name"]
                ctry = i["defaultCountry"]["name"]
                url = i["url"]

                comp = interaction.client.get_competition(id_)

                if comp is None:
                    comp = Competition(id_, name, ctry, url)
                    await comp.save(interaction.client)

                if i["images"]:
                    logo_url = i["images"][0]["path"]
                    comp.logo_url = logo_url

                results.append(comp)
            else:
                types = i["participantTypes"]
                logging.info("unhandled particpant types %s", types)
        else:
            for type_ in i["participantTypes"]:
                t_name = type_["name"]
                if t_name in ["National", "Team"]:
                    if mode == "comp":
                        continue

                    if not (team := interaction.client.get_team(i["id"])):
                        team = Team(i["id"], i["name"], i["url"])
                        try:
                            team.logo_url = i["images"][0]["path"]
                        except IndexError:
                            pass
                        team.gender = i["gender"]["name"]
                        await team.save(interaction.client)
                    results.append(team)
                elif t_name == "TournamentTemplate":
                    if mode == "team":
                        continue

                    comp = interaction.client.get_competition(i["id"])
                    if not comp:
                        ctry = i["defaultCountry"]["name"]
                        nom = i["name"]
                        comp = Competition(i["id"], nom, ctry, i["url"])
                        try:
                            comp.logo_url = i["images"][0]["path"]
                        except IndexError:
                            pass
                        await comp.save(interaction.client)
                        results.append(comp)
                else:
                    continue  # This is a player, we don't want those.

    return results


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

        options: list[discord.SelectOption] = []
        rows: list[str] = []

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
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[TeamSelect]
    ) -> None:
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

        rows: list[str] = []
        options: list[discord.SelectOption] = []
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
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[CompetitionSelect]
    ) -> None:
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

        choices: list[discord.app_commands.Choice[str]] = []
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
