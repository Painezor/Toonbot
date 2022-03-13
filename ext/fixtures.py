"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from copy import deepcopy
from typing import List, Optional, TYPE_CHECKING

# D.py
from discord import Embed, Colour, app_commands, Interaction
from discord.ext import commands

# Custom Utils
from ext.utils import timed_events, football, view_utils
# Type hinting
from ext.utils.football import Competition, Team, FlashScoreItem, TeamView

if TYPE_CHECKING:
    pass


# todo: News https://www.flashscore.com/team/newcastle-utd/p6ahwuwJ/news/
# TODO: Permissions Pass.
# TODO: Grouped Commands pass | Fixture / Team / Competition
# TODO: Autocomplete fetch for team/competition
# Maybe Todo: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# Maybe todo: League.Form table.


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot) -> None:
        self.bot = bot

    # Selection View/Filter/Pickers.
    async def search(self, interaction: Interaction, qry: str, mode=None, include_fs=False) -> FlashScoreItem | None:
        """Get Matches from Live Games & FlashScore Search Results"""
        # Handle Server Defaults
        if qry == "default":
            if interaction.guild is None:
                await self.bot.error(interaction, "You need to specify a search query.")
                return None

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
                await self.bot.error(interaction, err)
                return None

            page = await self.bot.browser.newPage()
            try:
                if mode == "team":
                    return await football.Team.by_id(default.split('/')[-1], page)
                else:
                    return await football.Competition.by_link(default, page)
            finally:
                await page.close()

        # Gather Other Search Results
        if include_fs:
            search_results = await football.get_fs_results(self.bot, qry)

            match mode:
                case "league":
                    cls = Competition
                case "team":
                    cls = Team
                case _:
                    cls = None

            if cls is not None:
                search_results = [i for i in search_results if isinstance(i, cls)]  # Check for specifics.

            fs_options = [(i.emoji, i.name, i.url) for i in search_results]
        else:
            fs_options = search_results = []

        markers = fs_options
        items = search_results

        if not markers:
            await self.bot.error(interaction, f"🚫 No results found for {qry}")
            return None

        if len(markers) == 1:
            return items[0]

        view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()

        return None if view.value is None else items[int(view.value)]

    # Autocompletes
    async def tm_ac(self, _: Interaction, current: str, __) -> List[app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = self.bot.teams.values()
        return [app_commands.Choice(name=t.name, value=t.url) for t in teams if current.lower() in t.name.lower()][:25]

    async def lg_ac(self, _: Interaction, current: str, __) -> List[app_commands.Choice[str]]:
        """Autocomplete from list of stored leagues"""
        lgs = self.bot.competitions.values()
        return [app_commands.Choice(name=i.name, value=i.url) for i in lgs if current.lower() in i.name.lower()][:25]

    async def fx_ac(self, _: Interaction, current: str, __) -> List[app_commands.Choice[str]]:
        """Check if user's typing is in list of live games"""
        games = self.bot.games.values()

        matches = []
        for g in games:
            if current.lower() not in f"{g.home.name.lower()} {g.away.name.lower()} {g.competition.name.lower()}":
                continue

            out = f":soccer: {g.home} {g.score} {g.away} ({g.competition.title})"
            matches.append(app_commands.Choice(name=out, value=g.url))
        return matches[:25]

    default = app_commands.Group(name="default", description="Set Server Defaults for team or league searches")

    @default.command()
    @app_commands.describe(query="pick a team to use for defaults")
    @app_commands.autocomplete(query=tm_ac)
    async def team(self, interaction: Interaction, query: str):
        """Set a default team for your server's Fixture commands"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_guild:
            err = "You need manage messages permissions to set a defaults."
            return await self.bot.error(interaction, err)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        url = fsr.url
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_team) VALUES ($1,$2)
                      ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1
                """, interaction.guild.id, url)
        finally:
            await self.bot.db.release(connection)

        e = await fsr.base_embed()
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default team'
        await self.bot.reply(interaction, embed=e)

    @default.command()
    @app_commands.describe(query="pick a league to use for defaults")
    @app_commands.autocomplete(query=lg_ac)
    async def league(self, interaction: Interaction, query: str):
        """Set a default league for your server's Fixture commands"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_guild:
            err = "You need manage messages permissions to set a defaults."
            return await self.bot.error(interaction, err)

        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True, mode="league")
            if fsr is None:
                return  # Rip

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                        ON CONFLICT (guild_id) DO UPDATE SET default_league = $2 WHERE excluded.guild_id = $1
                  """, interaction.guild.id, fsr.url)
        finally:
            await self.bot.db.release(connection)

        e = await fsr.base_embed()
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default league'
        await self.bot.reply(interaction, embed=e)

    # TEAM or LEAGUE commands
    @app_commands.command()
    @app_commands.describe(team="team name to search for", league="league name to search for")
    @app_commands.autocomplete(team=tm_ac, league=lg_ac)
    async def fixtures(self, interaction: Interaction, team: Optional[str], league: Optional[str]):
        """Fetch upcoming fixtures for a team or league."""
        await interaction.response.defer(thinking=True)

        if team is None and league is None:
            query = "default"
        else:
            query = team if team is not None else league

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True)
            if fsr is None:
                return

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        await view.push_fixtures()

    @app_commands.command()
    @app_commands.describe(team="team name to search for", league="league name to search for")
    @app_commands.autocomplete(team=tm_ac, league=lg_ac)
    async def results(self, interaction: Interaction, team: Optional[str], league: Optional[str]):
        """Get past results for a team or league."""
        await interaction.response.defer(thinking=True)

        if team is None and league is None:
            query = "default"
        else:
            query = team if team is not None else league

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True)
            if fsr is None:
                return

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        await view.push_results()

    @app_commands.command()
    @app_commands.describe(team="team name to search for", league="league name to search for")
    @app_commands.autocomplete(team=tm_ac, league=lg_ac)
    async def table(self, interaction: Interaction, team: Optional[str], league: Optional[str]):
        """Get table for a league"""
        await interaction.response.defer(thinking=True)

        if team is None and league is None:
            query = "default"
        else:
            query = team if team is not None else league

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True)
            if fsr is None:
                return

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())

        if isinstance(view, TeamView):
            await view.select_table()
        else:
            await view.push_table()

    @app_commands.command()
    @app_commands.describe(team="team name to search for", league="league name to search for")
    @app_commands.autocomplete(team=tm_ac, league=lg_ac)
    async def scorers(self, interaction: Interaction, team: Optional[str], league: Optional[str]):
        """Get top scorers from a league, or search for a team and get their top scorers in a league."""
        await interaction.response.defer(thinking=True)

        if team is None and league is None:
            query = "default"
        else:
            query = team if team is not None else league

        # Receive Autocomplete.
        if query in self.bot.competitions:
            fsr = self.bot.competitions[query]
        elif query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True)
            if fsr is None:
                return

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        await view.push_scorers()

    # LEAGUE only
    @app_commands.command()
    @app_commands.describe(query="league name to search for")
    @app_commands.autocomplete(query=lg_ac)
    async def scores(self, interaction: Interaction, query: Optional[str] = None):
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
        await view.update()

    @app_commands.command()
    @app_commands.describe(query="team name to search for")
    @app_commands.autocomplete(query=tm_ac)
    async def injuries(self, interaction: Interaction, query: Optional[str]):
        """Get a team's current injuries"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            if query is None:
                query = "default"
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        await view.push_injuries()

    @app_commands.command(description="Fetch the squad for a team")
    @app_commands.describe(query="team name to search for")
    @app_commands.autocomplete(query=tm_ac)
    async def squad(self, interaction: Interaction, query: Optional[str]):
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            if query is None:
                query = "default"
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        await view.push_squad()

    # FIXTURE commands
    @app_commands.command(description="Fetch the stats for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def stats(self, interaction: Interaction, query: str):
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        view = fsr.view(interaction, await self.bot.browser.newPage())
        await view.push_stats()

    @app_commands.command(description="Fetch the formations for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def formations(self, interaction: Interaction, query: str):
        """Look up the formation for a Fixture."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        page = await self.bot.browser.newPage()
        try:
            fsr = await fsr.pick_recent_game(interaction, page)
            if fsr is None:
                return await page.close()
        except AttributeError:
            pass

        view = fsr.view(interaction, page)
        await view.push_lineups()

    @app_commands.command(description="Fetch the summary for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def summary(self, interaction: Interaction, query: str):
        """Get a summary for one of today's games."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        page = await self.bot.browser.newPage()
        try:
            fsr = await fsr.pick_recent_game(interaction, page)
            if fsr is None:
                return await page.close()
        except AttributeError:
            pass

        view = fsr.view(interaction, page)
        await view.push_summary()

    @app_commands.command(description="Fetch the head-to-head info for a fixture")
    @app_commands.describe(query="fixture to search for")
    @app_commands.autocomplete(query=fx_ac)
    async def head_to_head(self, interaction: Interaction, query: str):
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        page = await self.bot.browser.newPage()
        try:
            fsr = await fsr.pick_recent_game(interaction, page)
            if fsr is None:
                return await page.close()
        except AttributeError:
            pass

        view = fsr.view(interaction, page)
        await view.push_head_to_head()

    # UNIQUE commands
    @app_commands.command(description="Fetch information about a stadium")
    @app_commands.describe(query="stadium to search for")
    async def stadium(self, interaction: Interaction, query: str):
        """Lookup information about a team's stadiums"""
        await interaction.response.defer(thinking=True)

        stadiums = await football.get_stadiums(query)
        if not stadiums:
            return await self.bot.error(interaction, f"🚫 No stadiums found matching `{query}`")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.name})") for i in stadiums]

        view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()

        if view.value is None:
            return None

        embed = await stadiums[view.value].to_embed
        await self.bot.reply(interaction, embed=embed)


def setup(bot):
    """Load the fixtures Cog into the bot"""
    bot.add_cog(Fixtures(bot))
