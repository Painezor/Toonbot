"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from copy import deepcopy
from typing import List, TYPE_CHECKING, Literal

# Type hinting
from discord import Embed, Colour, app_commands, Interaction, Message
from discord.app_commands import Choice
# D.py
from discord.ext import commands
from discord.ui import View

# Custom Utils
from ext.utils import timed_events, football, view_utils
from ext.utils.football import Competition, Team, FlashScoreItem, TeamView, Stadium

if TYPE_CHECKING:
    from core import Bot


# TODO: News https://www.flashscore.com/team/newcastle-utd/p6ahwuwJ/news/
# TODO: Permissions Pass.
# TODO: Grouped Commands pass | Fixture / Team / Competition
# TODO: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# TODO: League.Form table.


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    # Selection View/Filter/Pickers.
    async def search(self, interaction: Interaction, qry: str, mode=None) -> FlashScoreItem | Message:
        """Get Matches from Live Games & FlashScore Search Results"""
        # Handle Server Defaults
        if qry == "default":
            if interaction.guild is None:
                return await self.bot.error(interaction, "You need to specify a search query.")

            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    r = await connection.fetchrow("""SELECT * FROM fixtures_defaults WHERE (guild_id) = $1
                         AND (default_league is NOT NULL OR default_team IS NOT NULL)""", interaction.guild.id)
            finally:
                await self.bot.db.release(connection)

            if r is None:
                default = None
            else:
                default = r["default_team"] if mode == "team" else r["default_league"]

            if default is None:
                if interaction.permissions.manage_guild:
                    err = f"Your server does not have a default {mode} set.\nUse `/default_{mode}`"
                else:
                    err = f"You need to specify a search query, or ask the server mods to use " \
                          f"`/default_{mode}` to set a server default {mode}."
                return await self.bot.error(interaction, err)
            else:
                return self.bot.teams[default] if mode == default else self.bot.competitions[default]

        # Gather Other Search Results
        items = await football.get_fs_results(self.bot, qry)

        match mode:
            case "league":
                cls = Competition
            case "team":
                cls = Team
            case _:
                cls = Team | Competition

        items = [i for i in items if isinstance(i, cls)]  # Check for specifics.
        if not items:
            return await self.bot.error(interaction, f"🚫 No results found for {qry}")
        elif len(items) == 1:
            return items[0]

        markers = [(x.emoji, x.title if isinstance(cls, Competition) else x.name, x.url) for x in items]

        view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()
        return None if view.value is None else items[int(view.value)]

    # Autocompletes
    async def tm_ac(self, _: Interaction, current: str, __: app_commands.Namespace) -> List[Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = self.bot.teams.values()
        return [Choice(name=t.name, value=t.id) for t in teams if current.lower() in t.name.lower()][:25]

    async def lg_ac(self, _: Interaction, current: str, __: app_commands.Namespace) -> List[Choice[str]]:
        """Autocomplete from list of stored leagues"""
        lgs = self.bot.competitions.values()
        return [Choice(name=i.title, value=i.id) for i in lgs if current.lower() in i.title.lower()][:25]

    async def tm_lg_ac(self, _: Interaction, current: str, namespace: app_commands.Namespace) -> List[Choice[str]]:
        """An Autocomplete that checks whether team or league is selected, then return appropriate autocompletes"""
        if namespace.mode == "team":
            return await self.tm_ac(_, current, namespace)
        elif namespace.mode == "league":
            return await self.lg_ac(_, current, namespace)

    async def fx_ac(self, _: Interaction, current: str, __) -> List[Choice[str]]:
        """Check if user's typing is in list of live games"""
        games = self.bot.games.values()

        matches = []
        for g in games:
            if current.lower() not in f"{g.home.name.lower()} {g.away.name.lower()} {g.competition.name.lower()}":
                continue

            out = f":soccer: {g.home} {g.score} {g.away} ({g.competition.title})"
            matches.append(Choice(name=out, value=g.url))
        return matches[:25]

    default = app_commands.Group(name="default", description="Set Server Defaults for team or league searches")

    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=tm_lg_ac)
    async def default(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> Message:
        """Set a default team or league for your flashscore lookups"""
        await i.response.defer(thinking=True)

        if i.guild is None:
            return await self.bot.error(i, "This command cannot be ran in DMs")
        if not i.permissions.manage_guild:
            err = "You need manage messages permissions to set a defaults."
            return await self.bot.error(i, err)

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(i, query, mode=mode)
            if isinstance(fsr, Message):
                return fsr  # Not Found

        c = await self.bot.db.acquire()

        q = f"""INSERT INTO fixtures_defaults (guild_id, default_{mode}) VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET default_{mode} = $2  WHERE excluded.guild_id = $1"""

        try:
            async with c.transaction():
                await c.execute(q, i.guild.id, fsr.id)
        finally:
            await self.bot.db.release(c)

        e = await fsr.base_embed
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default {mode}'
        return await self.bot.reply(i, embed=e)

    # TEAM or LEAGUE commands
    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=tm_lg_ac)
    async def fixtures(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> View | None:
        """Fetch upcoming fixtures for a team or league."""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(i, query, mode=mode)
            if isinstance(fsr, Message):
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        return await view.push_fixtures()

    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=tm_lg_ac)
    async def fixtures(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> View | None:
        """Get past results for a team or league."""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(i, query, mode=mode)
            if isinstance(fsr, Message):
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        return await view.push_results()

    # TODO: Literal['team', 'league'] & query, rewrite autocomplete using namespace

    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=tm_lg_ac)
    async def table(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> View | None:
        """Get table for a league"""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(i, query, mode=mode)
            if isinstance(fsr, Message):
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        if isinstance(view, TeamView):
            return await view.select_table()
        else:
            return await view.push_table()

    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=tm_lg_ac)
    async def scorers(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> View | None:
        """Get top scorers from a league, or search for a team and get their top scorers in a league."""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(i, query, mode=mode)
            if isinstance(fsr, Message):
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        return await view.push_scorers()

    # LEAGUE only
    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=lg_ac)
    async def scores(self, interaction: Interaction, query: str = 'default') -> Message | View:
        """Fetch current scores for a specified league"""
        await interaction.response.defer(thinking=True)

        if query is None:
            matches = self.bot.games.values()
        elif query in self.bot.competitions:
            matches = [i for i in self.bot.games.values() if query in (str(i.competition)).lower()]
        else:
            _ = str(query).lower()
            matches = [i for i in self.bot.games.values() if _ in (str(i.competition)).lower()]

        if not matches:
            err = "No live games found!"
            if query is not None:
                err += f" matching search query `{query}`"
            return await self.bot.error(interaction, err)

        matches = [(i.competition.title, i.live_score_text) for i in matches]
        _ = None
        header = f'Scores as of: {timed_events.Timestamp().long}\n'
        e = Embed(color=Colour.og_blurple(), title="Current scores", description=header)

        embeds = []
        for x, y in matches:
            if x != _:  # We need a new header if it's a new league.
                _ = x
                output = f"\n**{x}**\n{y}\n"
            else:
                output = f"{y}\n"

            if len(e.description + output) < 2048:
                e.description += output
            else:
                embeds.append(deepcopy(e))
                e.description = header + f"\n**{x}**\n{y}\n"
        else:
            embeds.append(deepcopy(e))

        view = view_utils.Paginator(interaction, embeds)
        return await view.update()

    @app_commands.command()
    @app_commands.describe(mode="search for a team or a league?", query="enter a search query")
    @app_commands.autocomplete(query=tm_ac)
    async def injuries(self, interaction: Interaction, query: str = 'default') -> View | None:
        """Get a team's current injuries"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            if query is None:
                query = "default"
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_injuries()

    @app_commands.command(description="Fetch the squad for a team")
    @app_commands.describe(query="team name to search for")
    @app_commands.autocomplete(query=tm_ac)
    async def squad(self, interaction: Interaction, query: str = 'default') -> View | None:
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            if query is None:
                query = "default"
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_squad()

    # FIXTURE commands
    @app_commands.command(description="Fetch the stats for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def stats(self, interaction: Interaction, query: str) -> View | None:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return  # Rip

        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_stats()

    @app_commands.command(description="Fetch the formations for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def formations(self, interaction: Interaction, query: str) -> View | None:
        """Look up the formation for a Fixture."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return  # Rip

        page = await self.bot.browser.newPage()
        try:
            fsr = await fsr.pick_recent_game(interaction, page)
            if isinstance(fsr, Message):
                await page.close()
                return
        except AttributeError:
            pass

        view = fsr.view(interaction, page)
        return await view.push_lineups()

    @app_commands.command(description="Fetch the summary for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def summary(self, interaction: Interaction, query: str):
        """Get a summary for one of today's games."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return  # Rip

        page = await self.bot.browser.newPage()
        try:
            fsr = await fsr.pick_recent_game(interaction, page)
            if isinstance(fsr, Message):
                await page.close()
                return
        except AttributeError:
            pass

        view = fsr.view(interaction, page)
        return await view.push_summary()

    @app_commands.command(description="Fetch the head-to-head info for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def head_to_head(self, interaction: Interaction, query: str) -> View | None:
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return  # Rip

        page = await self.bot.browser.newPage()
        try:
            if isinstance(fsr, Message):
                await page.close()
                return
        except AttributeError:
            pass

        view = fsr.view(interaction, page)
        return await view.push_head_to_head()

    # UNIQUE commands
    @app_commands.command(description="Fetch information about a stadium")
    @app_commands.describe(query="stadium to search for")
    async def stadium(self, interaction: Interaction, query: str) -> Message | None:
        """Lookup information about a team's stadiums"""
        await interaction.response.defer(thinking=True)

        stadiums: List[Stadium] = await football.get_stadiums(query)
        if not stadiums:
            return await self.bot.error(interaction, f"🚫 No stadiums found matching `{query}`")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.name})") for i in stadiums]

        view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()

        if view.value is None:
            return

        embed = await stadiums[view.value].to_embed
        return await self.bot.reply(interaction, embed=embed)


async def setup(bot: 'Bot'):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
