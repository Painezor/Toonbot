"""Discord Transformers for various flashscore entities"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeAlias, Literal, overload, Optional
from urllib.parse import quote

from discord.app_commands import Transform, Transformer, Choice
from discord.ui import Select, select
from discord import (
    Interaction as Itr,
    User as usr,
    Member,
    Locale,
    SelectOption,
    Embed,
)


from ext.utils import view_utils

from .abc import Competition, Team, Fixture

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = Itr[Bot]
    User: TypeAlias = usr | Member

logger = logging.getLogger("flashscore.transformers")


# slovak - 7
# Hebrew - 17
# Slovenian - 24
# Estonian - 26
# Indonesian - 35
# Catalan - 43
# Georgian - 44

locales = {
    Locale.american_english: 1,  # 'en-US'
    Locale.british_english: 1,  # 'en-GB' flashscore.co.uk
    Locale.bulgarian: 40,  # 'bg'
    Locale.chinese: 19,  # 'zh-CN'
    Locale.taiwan_chinese: 19,  # 'zh-TW'
    Locale.french: 16,  # 'fr'    flashscore.fr
    Locale.croatian: 14,  # 'hr'  # Could also be 25?
    Locale.czech: 2,  # 'cs'
    Locale.danish: 8,  # 'da'
    Locale.dutch: 21,  # 'nl'
    Locale.finnish: 18,  # 'fi'
    Locale.german: 4,  # 'de'
    Locale.greek: 11,  # 'el'
    Locale.hindi: 1,  # 'hi'
    Locale.hungarian: 15,  # 'hu'
    Locale.italian: 6,  # 'it'
    Locale.japanese: 42,  # 'ja'
    Locale.korean: 38,  # 'ko'
    Locale.lithuanian: 27,  # 'lt'
    Locale.norwegian: 23,  # 'no'
    Locale.polish: 3,  # 'pl'
    Locale.brazil_portuguese: 20,  # 'pt-BR'   # Could also be 31
    Locale.romanian: 9,  # 'ro'
    Locale.russian: 12,  # 'ru'
    Locale.spain_spanish: 13,  # 'es-ES'
    Locale.swedish: 28,  # 'sv-SE'
    Locale.thai: 1,  # 'th'
    Locale.turkish: 10,  # 'tr'
    Locale.ukrainian: 41,  # 'uk'
    Locale.vietnamese: 37,  # 'vi'
}


@overload
async def search(
    query: str, mode: Literal["comp"], interaction: Interaction
) -> list[Competition]:
    ...


@overload
async def search(
    query: str, mode: Literal["team"], interaction: Interaction
) -> list[Team]:
    ...


async def search(
    query: str,
    mode: Literal["comp", "team"],
    interaction: Interaction,
) -> list[Competition] | list[Team]:
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
            rsn = await resp.text()
            logger.error("%s %s: %s", resp.status, rsn, resp.url)
        res = await resp.json()

    teams: list[Team] = []
    comps: list[Competition] = []
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

                comps.append(comp)
            else:
                types = i["participantTypes"]
                logging.info("unhandled particpant types %s", types)
        else:
            for type_ in i["participantTypes"]:
                t_name = type_["name"]
                if t_name in ["National", "Team"]:
                    if mode == "comp":
                        continue

                    team = Team(i["id"], i["name"], i["url"])
                    try:
                        team.logo_url = i["images"][0]["path"]
                    except IndexError:
                        pass
                    team.gender = i["gender"]["name"]

                    if lang_id == 1:
                        await team.save(interaction.client)
                    teams.append(team)
                elif t_name == "TournamentTemplate":
                    if mode == "team":
                        continue

                    ctry = i["defaultCountry"]["name"]
                    nom = i["name"]
                    comp = Competition(i["id"], nom, ctry, i["url"])
                    try:
                        comp.logo_url = i["images"][0]["path"]
                    except IndexError:
                        pass

                    if lang_id == 1:
                        await comp.save(interaction.client)
                        comps.append(comp)
                else:
                    continue  # This is a player, we don't want those.

    if mode == "comp":
        return comps
    return teams


async def set_default(
    interaction: Interaction,
    param: Literal["default_league", "default_team"],
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

    if (def_id := default.id) is None:
        interaction.extras["default"] = None
        return

    name = f"⭐ Server default: {default.name}"[:100]
    default = Choice(name=name, value=def_id)
    interaction.extras["default"] = default
    return


class TeamSelect(view_utils.DropdownPaginator):
    """View for asking user to select a specific Team"""

    def __init__(self, invoker: User, teams: list[Team]) -> None:
        embed = Embed(title="Choose a Team")

        options: list[SelectOption] = []
        rows: list[str] = []

        for team in teams:
            if team.id is None:
                continue

            opt = SelectOption(label=team.name, value=team.id)
            opt.description = f"{team.id}: {team.url}"
            opt.emoji = team.emoji
            options.append(opt)
            rows.append(f"`{team.id}` {team.markdown}")

        self.teams = teams
        super().__init__(invoker, embed, rows, options)

        # Value
        self.interaction: Interaction
        self.team: Team

    @select(placeholder="Choose a team")
    async def dropdown(
        self, itr: Interaction, sel: Select[TeamSelect]
    ) -> None:
        self.team = next(i for i in self.teams if i.id == sel.values[0])
        self.interaction = itr
        return


class FixtureSelect(view_utils.DropdownPaginator):
    """View for asking user to select a specific fixture"""

    def __init__(self, invoker: User, fixtures: list[Fixture]):
        embed = Embed(title="Choose a Fixture")

        rows: list[str] = []
        options: list[SelectOption] = []
        for i in fixtures:
            if i.id is None:
                continue

            opt = SelectOption(label=i.score_line, value=i.id)
            if i.competition:
                opt.description = i.competition.title
            options.append(opt)
            rows.append(f"`{i.id}` {i.bold_markdown}")

        self.fixtures = fixtures
        super().__init__(invoker, embed, rows, options)

        # Final result
        self.fixture: Fixture
        self.interaction: Interaction

    @select(placeholder="Choose a fixture")
    async def dropdown(
        self, itr: Interaction, sel: Select[FixtureSelect]
    ) -> None:
        self.fixture = next(i for i in self.fixtures if i.id in sel.values)
        self.interaction = itr
        return


class CompetitionSelect(view_utils.DropdownPaginator):
    """View for asking user to select a specific fixture"""

    def __init__(self, invoker: User, competitions: list[Competition]) -> None:
        embed = Embed(title="Choose a Competition")

        rows: list[str] = []
        options: list[SelectOption] = []
        for i in competitions:
            if i.id is None:
                continue

            opt = SelectOption(label=i.title, value=i.id)
            opt.description = i.url
            opt.emoji = i.emoji
            rows.append(f"`{i.id}` {i.markdown}")
            options.append(opt)

        self.comps = competitions
        super().__init__(invoker, embed, rows, options)

        self.competition: Competition
        self.interaction: Interaction

    @select(placeholder="Select a competition")
    async def dropdown(
        self, itr: Interaction, sel: Select[CompetitionSelect]
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
    await interaction.response.send_message(view=view, embed=view.pages[0])
    view.message = await interaction.original_response()
    await view.wait()

    if not view.fixture:
        raise TimeoutError
    return view.fixture


class TeamTransformer(Transformer):
    """Convert user Input to a Team Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = interaction.client.teams
        teams.sort(key=lambda x: x.name)

        # Run Once - Set Default for interaction.
        if "default" not in interaction.extras:
            await set_default(interaction, "default_team")

        curr = current.casefold()

        choices: list[Choice[str]] = []
        for i in teams:
            if i.id is None:
                continue

            if curr not in i.title.casefold():
                continue

            choice = Choice(name=i.name[:100], value=i.id)
            choices.append(choice)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Optional[Team]:
        if fsr := interaction.client.get_team(value):
            return fsr

        teams = await search(value, "team", interaction)

        view = TeamSelect(interaction.user, teams)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        await view.wait()
        if not view.team:
            raise TimeoutError
        return view.team


# Autocompletes
class FixtureTransformer(Transformer):
    """Convert User Input to a fixture Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Check if user's typing is in list of live games"""
        cur = current.casefold()

        choices: list[Choice[str]] = []
        for i in interaction.client.games:
            ac_row = i.ac_row.casefold()
            if cur and cur not in ac_row:
                continue

            if i.id is None:
                continue

            name = i.ac_row[:100]
            choice = Choice(name=name, value=i.id)

            choices.append(choice)

            if len(choices) == 25:
                break

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Optional[Fixture]:
        if fix := interaction.client.get_fixture(value):
            return fix

        if fsr := interaction.client.get_team(value):
            return await choose_recent_fixture(interaction, fsr)

        teams = await search(value, "team", interaction)

        view = TeamSelect(interaction.user, teams)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        await view.wait()

        if not view.team:
            return None

        fsr = view.team
        await choose_recent_fixture(view.interaction, fsr)


class TFCompetitionTransformer(Transformer):
    """Converts user input to a Competition object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored competitions"""
        lgs = sorted(interaction.client.competitions, key=lambda x: x.title)

        if "default" not in interaction.extras:
            await set_default(interaction, "default_league")

        curr = current.casefold()

        choices: list[Choice[str]] = []

        for i in lgs:
            if curr not in i.title.casefold() or i.id is None:
                continue

            opt = Choice(name=i.title[:100], value=i.id)

            choices.append(opt)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices[:24]

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Optional[Competition]:
        if fsr := interaction.client.get_competition(value):
            return fsr

        if "http" in value:
            return await Competition.by_link(interaction.client, value)

        comps = await search(value, "comp", interaction)

        view = CompetitionSelect(interaction.user, comps)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()
        await view.wait()
        return view.competition


comp_trnsf: TypeAlias = Transform[Competition, TFCompetitionTransformer]
fix_trnsf: TypeAlias = Transform[Fixture, FixtureTransformer]
team_trnsf: TypeAlias = Transform[Team, TeamTransformer]
