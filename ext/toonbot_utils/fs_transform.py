"""Discord Transformers for various flashscore entities"""
from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    TypeAlias,
    Literal,
    TypeVar,
    Generic,
    overload,
)
from urllib.parse import quote

from discord.app_commands import Transform, Transformer, Choice
from discord.ui import Select
import discord
from discord import (
    Interaction as Itr,
    User as usr,
    Member,
    Locale,
    SelectOption,
    Embed,
)

import ext.flashscore as fs
from ext.flashscore.abc import BaseTeam, BaseCompetition, BaseFixture
from ext.utils import view_utils

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


def get_lang_id(interaction: Interaction) -> int:
    """Get languagee id"""
    try:
        return locales[interaction.locale]
    except KeyError:
        try:
            if interaction.guild_locale is None:
                return 1
            else:
                return locales[interaction.guild_locale]
        except KeyError:
            return 1


@overload
async def search(
    query: str, mode: Literal["comp"], interaction: Interaction
) -> list[BaseCompetition]:
    ...


@overload
async def search(
    query: str, mode: Literal["team"], interaction: Interaction
) -> list[BaseTeam]:
    ...


async def search(
    query: str,
    mode: Literal["comp", "team"],
    interaction: Interaction,
) -> list[BaseCompetition] | list[BaseTeam]:
    """Fetch a list of items from flashscore matching the user's query"""
    replace = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))
    query = quote(replace)

    lang_id = get_lang_id(interaction)

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

    parser = FSParser(res, interaction)

    comps = parser.comps
    teams = parser.teams
    if lang_id == 1:
        bot = interaction.client
        bot.loop.create_task(bot.cache.save_competitions(comps), name="cmp_sv")
        bot.loop.create_task(bot.cache.save_teams(teams), name="team_sv")
    if mode == "comp":
        return comps
    return teams


class FSParser:
    """Parse FS Objects"""

    def __init__(
        self, data: list[dict[str, Any]], interaction: Interaction
    ) -> None:
        self.comps: list[BaseCompetition] = []
        self.teams: list[BaseTeam] = []
        self.interaction: Interaction = interaction
        self.parse(data)

    def parse(self, res: list[dict[str, Any]]) -> None:
        for i in res:
            if i["participantTypes"] is None:
                self.parse_competition(i)
            else:
                for type_ in i["participantTypes"]:
                    t_name = type_["name"]
                    if t_name in ["National", "Team"]:
                        self.parse_team(i)
                    elif t_name == "TournamentTemplate":
                        self.parse_competition(i)

    def parse_competition(self, i: dict[str, Any]) -> BaseCompetition | None:
        """Parse a competition object"""
        if i["type"]["name"] == "TournamentTemplate":
            id_ = i["id"]
            name = i["name"]
            ctry = i["defaultCountry"]["name"]
            url = i["url"]

            comp = self.interaction.client.cache.get_competition(id=id_)

            if comp is None:
                comp = BaseCompetition(
                    id=id_, name=name, country=ctry, url=url
                )

            if i["images"]:
                logo_url = i["images"][0]["path"]
                logger.info("setting logo_url to %s", logo_url)
                # If bad: FLASHSCORE + "/res/image/data/"
                comp.logo_url = logo_url

            self.comps.append(comp)
        else:
            types = i["participantTypes"]
            logger.info("unhandled particpant types %s", types)

    def parse_team(self, i: dict[str, Any]) -> None:
        team = self.interaction.client.cache.get_team(i["id"])
        if team is None:
            team = fs.Team.parse_obj(i)
        try:
            team.logo_url = i["images"][0]["path"]
            logger.info("setting team logo_url to %s", team.logo_url)
            # todo: if bad FLASHSCORE + "/res/image/data/"
        except IndexError:
            pass
        team.gender = i["gender"]["name"]
        self.teams.append(team)


async def set_default(
    interaction: Interaction,
    param: Literal["default_league", "default_team"],
) -> None:
    """Fetch the default team or default league for this server"""
    if interaction.guild is None:
        interaction.extras["default"] = None
        return

    from ext.fixtures import FixturesCog

    if (fxcog := interaction.client.get_cog(FixturesCog.__cog_name__)) is None:
        return

    assert isinstance(fxcog, FixturesCog)
    del FixturesCog

    records = fxcog.fixture_defaults
    gid = interaction.guild.id
    record = next((i for i in records if i["guild_id"] == gid), None)

    if record is None or record[param] is None:
        interaction.extras["default"] = None
        return

    id_ = record[param]
    if param == "default_team":
        default = interaction.client.cache.get_team(id_)
    else:
        default = interaction.client.cache.get_competition(id=id_)

    if default is None:
        interaction.extras["default"] = None
        return

    if (def_id := default.id) is None:
        interaction.extras["default"] = None
        return

    name = f"⭐ Server default: {default.name}"[:100]
    default = Choice(name=name, value=def_id)
    interaction.extras["default"] = default


T = TypeVar("T", BaseTeam, BaseCompetition, BaseFixture)


class FSSelect(view_utils.DropdownPaginator, Generic[T]):
    """View for asking user to select a specific team/competition"""

    def __init__(self, invoker: User, objects: list[T]) -> None:
        embed = Embed(title="Choose an item")

        options: list[SelectOption] = []
        rows: list[str] = []

        for i in objects:
            if i.id is None:
                continue

            opt = SelectOption(label=i.title, value=i.id)
            opt.description = f"{i.id}: {i.url}"

            comp = getattr(i, "competition", None)
            if isinstance(comp, BaseCompetition):
                opt.description = comp.title

            opt.emoji = i.emoji
            options.append(opt)
            rows.append(f"`{i.id}` [{i.title}]({i.url})")

        self.objects: list[T] = objects
        super().__init__(invoker, embed, rows, options)

        # Value
        self.interaction: Interaction
        self.object: T | None = None

    @discord.ui.select(placeholder="Choose item")
    async def dropdown(self, interaction: Interaction, sel: Select) -> None:
        """Spawn Team Clan View"""
        self.object = next(i for i in self.objects if i.id in sel.values)
        self.interaction = interaction


async def choose_recent_fixture(
    interaction: Interaction, fsr: BaseCompetition | BaseTeam
) -> BaseFixture:
    """Allow the user to choose from the most recent games of a fixture"""
    page = await interaction.client.browser.new_page()

    if isinstance(fsr, BaseCompetition):
        fsr = fs.Competition.parse_obj(fsr)
    else:
        fsr = fs.Team.parse_obj(fsr)
    try:
        fixtures = await fsr.results(page, interaction.client.cache)
    finally:
        await page.close()

    view = FSSelect(interaction.user, fixtures)
    await interaction.response.send_message(view=view, embed=view.embeds[0])
    view.message = await interaction.original_response()
    await view.wait()

    if not view.object:
        raise TimeoutError
    return view.object


class TeamTransformer(Transformer):
    """Convert user Input to a Team Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = list(interaction.client.cache.teams)
        teams.sort(key=lambda x: x.title)

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

            choice = Choice(name=i.title[:100], value=i.id)
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
    ) -> BaseTeam | None:
        if fsr := interaction.client.cache.get_team(value):
            return fs.Team.parse_obj(fsr)

        teams = await search(value, "team", interaction)

        view = FSSelect(interaction.user, teams)
        emb = view.embeds[0]
        await interaction.response.send_message(view=view, embed=emb)
        view.message = await interaction.original_response()
        await view.wait()
        if not view.object:
            raise TimeoutError
        return view.object


# Autocompletes
class FixtureTransformer(Transformer):
    """Convert User Input to a fixture Object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Check if user's typing is in list of live games"""
        cur = current.casefold()

        choices: list[Choice[str]] = []
        for i in interaction.client.cache.games:
            if i.id is None:
                continue

            ac_row = i.title.casefold()
            if cur not in ac_row:
                continue

            name = f"{i.emoji} {i.title}"[:100]
            choices.append(Choice(name=name, value=i.id))

            if len(choices) == 25:
                break

        if current:
            src = f"🔎 Search for '{current}'"
            srch = [Choice(name=src, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> BaseFixture | None:
        """Try to convert input to a fixture"""
        games = interaction.client.cache.games
        if fix := next((i for i in games if i.id == value), None):
            return fix

        if fsr := interaction.client.cache.get_team(value):
            return await choose_recent_fixture(interaction, fsr)

        teams = await search(value, "team", interaction)

        view = FSSelect(interaction.user, teams)
        emb = view.embeds[0]
        await interaction.response.send_message(view=view, embed=emb)
        view.message = await interaction.original_response()
        await view.wait()

        if not view.object:
            return None

        if isinstance(fsr := view.object, BaseTeam | BaseCompetition):
            return await choose_recent_fixture(view.interaction, fsr)


class TFCompetitionTransformer(Transformer):
    """Converts user input to a Competition object"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored competitions"""

        comps = interaction.client.cache.competitions
        lgs = sorted(comps, key=lambda x: x.title)

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
    ) -> BaseCompetition | None:
        if fsr := interaction.client.cache.get_competition(id=value):
            return fsr

        if "http" in value:
            await interaction.response.defer(thinking=True)
            page = await interaction.client.browser.new_page()
            try:
                comp = await fs.Competition.by_link(page, value)
                return BaseCompetition.parse_obj(comp)
            finally:
                await page.close()

        comps = await search(value, "comp", interaction)

        view = FSSelect(interaction.user, comps)
        emb = view.embeds[0]
        await interaction.response.send_message(view=view, embed=emb)
        view.message = await interaction.original_response()
        await view.wait()
        return view.object


class LiveCompTransformer(TFCompetitionTransformer):
    """Get only live competitions"""

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored competitions"""

        leagues = set(i.competition for i in interaction.client.cache.games)
        leagues = [i for i in leagues if i is not None]
        leagues.sort(key=lambda i: i.name)
        curr = current.casefold()

        choices: list[Choice[str]] = []

        for i in leagues:
            if curr not in i.title.casefold() or i.id is None:
                continue

            opt = Choice(name=i.title[:100], value=i.id)

            choices.append(opt)

            if len(choices) == 25:
                break
        return choices[:25]


fixture_only = [""]
team_or_comp = ["fixtures", "results"]
team_or_fixture = ["news`"]


class UniversalTransformer(Transformer):
    """
    A Universal Flashscore Transformer that can return
    a Fixture, Competition, or Team
    """

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str
    ) -> List[Choice[str]]:
        """Grab all current Fixtures, Teams, and Competitions matching value"""

        cur = value.casefold()
        opts: list[Choice[str]] = []

        cln = interaction.client.cache

        pool = None
        if interaction.command is None:
            pass
        elif interaction.command.name in fixture_only:
            pool = cln.games
        elif interaction.command.name in team_or_comp:
            pool = cln.teams + cln.competitions
        elif interaction.command.name in team_or_fixture:
            pool = cln.teams + cln.games

        if pool is None:
            pool = cln.games + cln.teams + cln.competitions

        for i in sorted(pool, key=lambda i: (i.emoji, i.title)):
            if cur not in i.title.casefold() or i.id is None:
                continue

            opts.append(
                Choice(name=f"{i.emoji} {i.title}"[:100], value=i.emoji + i.id)
            )

        src = f"🔎 Search for team '{cur}'"
        srch = [
            Choice(name=src, value=f"T:{cur}"),
            Choice(name=src, value=f"C:{cur}"),
        ]
        opts = opts[:23] + srch
        return opts[:23]

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str
    ) -> Any:
        """Return the first Fixture, Competition, or Team Found"""
        cln = interaction.client.cache
        pool = cln.teams + cln.competitions + cln.games

        if result := next(
            (i for i in pool if f"{i.emoji}{i.id}" == value), None
        ):
            return result

        if value.startswith("T:"):
            value = value.split(":", maxsplit=1)[-1]
            items = await search(value, "team", interaction)
            view = FSSelect(interaction.user, items)
        elif value.startswith("C:"):
            value = value.split(":", maxsplit=1)[-1]
            items = await search(value, "comp", interaction)
            view = FSSelect(interaction.user, items)
        else:
            raise ValueError("Unhandled value %s", value)

        emb = view.embeds[0]
        await interaction.response.send_message(view=view, embed=emb)
        view.message = await interaction.original_response()
        await view.wait()

        if not view.object:
            return None

        return view.object


universal: TypeAlias = Transform[
    BaseCompetition | BaseFixture | BaseTeam, UniversalTransformer
]
comp_: TypeAlias = Transform[BaseCompetition, TFCompetitionTransformer]
live_comp: TypeAlias = Transform[BaseCompetition, LiveCompTransformer]
fixture_: TypeAlias = Transform[BaseFixture, FixtureTransformer]
team_: TypeAlias = Transform[BaseTeam, TeamTransformer]
