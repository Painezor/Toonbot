"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from copy import deepcopy
from typing import Union, List, Optional

# D.py
from discord import Embed, Colour, app_commands, Interaction
from discord.ext import commands

# Custom Utils
from ext.utils import timed_events, football, embed_utils, view_utils
# Type hinting
from ext.utils.football import Competition, Team, Fixture


# todo: News https://www.flashscore.com/team/newcastle-utd/p6ahwuwJ/news/
# TODO: Permissions Pass.
# TODO: Grouped Commands pass | Fixture / Team / Competition
# TODO: Autocomplete fetch for team/competition
# Maybe Todo: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# Maybe todo: League.Form table.

# Selection View/Filter/Pickers.
async def search(interaction: Interaction, qry, mode=None, include_live=False, include_fs=False) \
        -> Union[Team, Competition, Fixture, None]:
    """Get Matches from Live Games & FlashScore Search Results"""
    # Handle Server Defaults
    if qry == "default":
        if interaction.guild is None:
            await interaction.client.error(interaction, "You need to specify a search query.")
            return None

        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                r = await connection.fetchrow("""SELECT * FROM fixtures_defaults WHERE (guild_id) = $1
                     AND (default_league is NOT NULL OR default_team IS NOT NULL)""", interaction.guild.id)
        finally:
            await interaction.client.db.release(connection)

        default = r["default_team"] if mode == "team" else r["default_league"]
        if default is None:
            if interaction.permissions.manage_guild:
                err = f"Your server does not have a default {mode} set.\nUse `/default_{mode}`"
            else:
                err = f"You need to specify a search query, or ask the server mods to use " \
                      f"`/default_{mode}` to set a server default {mode}."
            await interaction.client.error(interaction, err)
            return None

        page = await interaction.client.browser.newPage()
        try:
            if mode == "team":
                return await football.Team.by_id(default.split('/')[-1], page)
            else:
                return await football.Competition.by_link(default, page)
        finally:
            await page.close()

    # Gather live games.
    query = str(qry).lower()

    if include_live:
        if mode == "team":
            live = [i for i in interaction.client.games.values() if query in f"{i.home.lower()} {i.away.lower()}"]
        else:
            live = [i for i in interaction.client.games.values() if query in (str(i.competition)).lower()]

        live_options = [("⚽", f"{i.home} {i.score} {i.away}", f"{i.competition}") for i in live]
    else:
        live = live_options = []

    # Gather Other Search Results
    if include_fs:
        search_results = await football.get_fs_results(interaction.client, qry)
        cls = Competition if mode == "league" else Team if mode == "team" else None  # Mode is a hard override.
        if cls is not None:
            search_results = [i for i in search_results if isinstance(i, cls)]  # Check for specifics.

        fs_options = [(i.emoji, i.name, i.url) for i in search_results]
    else:
        fs_options = search_results = []

    markers = live_options + fs_options
    items = live + search_results

    if not markers:
        await interaction.client.error(interaction, f"🚫 No results found for {qry}")
        return None

    if len(markers) == 1:
        return items[0]

    view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
    await view.update()
    await view.wait()

    return None if view.value is None else items[int(view.value)]


# TEAM or LEAGUE commands
# Autocomplete
async def team_or_league(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Get a team or league"""
    client = interaction.client
    teams = sorted(set([i.home for i in client.games.values()] + [i.away for i in client.games.values()]))
    leagues = sorted(set([i.competition.name for i in client.games.values()]))

    unique = list(teams + leagues)
    return [app_commands.Choice(name=item, value=item) for item in unique if current.lower() in item.lower()]


@app_commands.command()
@app_commands.describe(query="team or league name to search for")
@app_commands.autocomplete(query=team_or_league)
async def fixtures(interaction: Interaction, query: Optional[str]):
    """Fetch upcoming fixtures for a team or league."""
    await interaction.response.defer(thinking=True)

    if query is None:
        query = "default"

    fsr = await search(interaction, query, include_fs=True)
    if fsr is None:
        return

    # Spawn Browser & Go.
    page = await interaction.client.browser.newPage()
    view = fsr.view(interaction, page)
    await view.push_fixtures()


@app_commands.command()
@app_commands.describe(query="team or league name to search for")
@app_commands.autocomplete(query=team_or_league)
async def results(interaction: Interaction, query: Optional[str]):
    """Get past results for a team or league."""
    await interaction.response.defer(thinking=True)

    if query is None:
        query = "default"

    fsr = await search(interaction, query, include_fs=True)
    if fsr is None:
        return

    # Spawn Browser & Go.
    page = await interaction.client.browser.newPage()
    view = fsr.view(interaction, page)
    await view.push_results()


@app_commands.command()
@app_commands.describe(query="team or league name to search for")
@app_commands.autocomplete(query=team_or_league)
async def table(interaction: Interaction, query: Optional[str]):
    """Get table for a league"""
    await interaction.response.defer(thinking=True)

    if query is None:
        query = "default"

    fsr = await search(interaction, query, include_fs=True)
    if fsr is None:
        return

    # Spawn Browser & Go.
    page = await interaction.client.browser.newPage()
    view = fsr.view(interaction, page)

    try:  # Only work for Team.
        await view.select_table()
    except AttributeError:
        await view.push_table()


@app_commands.command()
@app_commands.describe(query="team or league name to search for")
@app_commands.autocomplete(query=team_or_league)
async def scorers(interaction: Interaction, query: Optional[str]):
    """Get top scorers from a league, or search for a team and get their top scorers in a league."""
    await interaction.response.defer(thinking=True)

    if query is None:
        query = "default"

    fsr = await search(interaction, query, include_fs=True)
    if fsr is None:
        return

    # Spawn Browser & Go.
    page = await interaction.client.browser.newPage()
    view = fsr.view(interaction, page)
    await view.push_scorers()


# LEAGUE only
# Autocomplete
async def atc_league(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Return list of live leagues"""
    comps = list(set([i.competition.name for i in interaction.client.games.values()]))
    return [app_commands.Choice(name=item, value=item) for item in comps if current.lower() in item.lower()]


@app_commands.command()
@app_commands.describe(query="league name to search for")
@app_commands.autocomplete(query=atc_league)
async def scores(interaction: Interaction, query: Optional[str] = None):
    """Fetch current scores for a specified league"""
    await interaction.response.defer(thinking=True)

    if query is None:
        matches = interaction.client.games.values()
    else:
        _ = str(query).lower()
        matches = [i for i in interaction.client.games.values() if _ in (str(i.competition)).lower()]

    if not matches:
        _ = "No live games found!"
        if query is not None:
            _ += f" matching search query `{query}`"
        return await interaction.client.error(interaction, _)

    matches = [(str(i.competition), i.live_score_text) for i in matches]
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


# TEAM only
# Autocomplete
async def team(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Return list of live leagues"""
    home = list([i.home.name for i in interaction.client.games.values()])
    away = list([i.away.name for i in interaction.client.games.values()])
    teams = sorted(set(home + away))
    return [app_commands.Choice(name=item, value=item) for item in teams if current.lower() in item.lower()]


@app_commands.command()
@app_commands.describe(query="team name to search for")
@app_commands.autocomplete(query=team)
async def injuries(interaction: Interaction, query: Optional[str]):
    """Get a team's current injuries"""
    await interaction.response.defer(thinking=True)

    if query is None:
        query = "default"

    fsr = await search(interaction, query, include_fs=True, mode="team")
    if fsr is None:
        return  # Rip

    # Spawn Browser & Go.
    page = await interaction.client.browser.newPage()
    view = fsr.view(interaction, page)
    await view.push_injuries()


@app_commands.command(description="Fetch the squad for a team")
@app_commands.describe(query="team name to search for")
@app_commands.autocomplete(query=team)
async def squad(interaction: Interaction, query: Optional[str]):
    """Lookup a team's squad members"""
    await interaction.response.defer(thinking=True)

    if query is None:
        query = "default"

    fsr = await search(interaction, query, include_fs=True, include_live=True, mode="team")
    if fsr is None:
        return  # Rip

    # Spawn Browser & Go.
    page = await interaction.client.browser.newPage()
    view = fsr.view(interaction, page)
    await view.push_squad()


# FIXTURE commands
# Autocomplete
async def live_games(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Check if user's typing is in list of live games"""
    games = interaction.client.games.values()
    return [app_commands.Choice(name=f'⚽ {i.home} {i.score} {i.away}: {i.competition.name}', value=i.id)
            for i in games if current.lower() in f'⚽ {i.home} {i.score} {i.away}: {i.competition.name}'.lower()]


@app_commands.command(description="Fetch the stats for a fixture")
@app_commands.describe(query="fixture to search for")
@app_commands.autocomplete(query=live_games)
async def stats(interaction: Interaction, query: str):
    """Look up the stats for a fixture."""
    await interaction.response.defer(thinking=True)

    if query in interaction.client.games:
        fsr = interaction.client.games[query]
    else:
        fsr = await search(interaction, query, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

    page = await interaction.client.browser.newPage()

    view = fsr.view(interaction, page)
    await view.push_stats()


@app_commands.command(description="Fetch the formations for a fixture")
@app_commands.describe(query="fixture to search for")
@app_commands.autocomplete(query=live_games)
async def formations(interaction: Interaction, query: str):
    """Look up the formation for a Fixture."""
    await interaction.response.defer(thinking=True)

    if query in interaction.client.games:
        fsr = interaction.client.games[query]
    else:
        fsr = await search(interaction, query, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

    page = await interaction.client.browser.newPage()
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
@app_commands.autocomplete(query=live_games)
async def summary(interaction: Interaction, query: str):
    """Get a summary for one of today's games."""
    await interaction.response.defer(thinking=True)

    if query in interaction.client.games:
        fsr = interaction.client.games[query]
    else:
        fsr = await search(interaction, query, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

    page = await interaction.client.browser.newPage()
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
@app_commands.autocomplete(query=live_games)
async def head_to_head(interaction: Interaction, query: str):
    """Lookup the head-to-head details for a Fixture"""
    await interaction.response.defer(thinking=True)

    if query in interaction.client.games:
        fsr = interaction.client.games[query]
    else:
        fsr = await search(interaction, query, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

    page = await interaction.client.browser.newPage()
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
async def stadium(interaction: Interaction, query: str):
    """Lookup information about a team's stadiums"""
    await interaction.response.defer(thinking=True)

    stadiums = await football.get_stadiums(query)
    if not stadiums:
        return await interaction.client.error(interaction, f"🚫 No stadiums found matching `{query}`")

    markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.name})") for i in stadiums]

    view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
    await view.update()
    await view.wait()

    if view.value is None:
        return None

    embed = await stadiums[view.value].to_embed
    await interaction.client.reply(interaction, embed=embed, view=None)


class Default(app_commands.Group):
    """Set Server Defaults for team or league searches"""

    @app_commands.command()
    @app_commands.describe(query="pick a team to use for defaults")
    @app_commands.autocomplete(query=team)
    async def team(self, interaction: Interaction, query: str):
        """Set a default team for your server's Fixture commands"""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_guild:
            err = "You need manage messages permissions to set a defaults."
            return await interaction.client.error(interaction, err)

        if query in interaction.client.games:
            fsr = interaction.client.games[query]
        else:
            fsr = await search(interaction, query, include_fs=True, mode="team")
            if fsr is None:
                return  # Rip

        url = fsr.url
        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_team) VALUES ($1,$2)
                     ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1
               """, interaction.guild.id, url)
        finally:
            await interaction.client.db.release(connection)

        e = Embed(description=f'Your Fixtures commands will now use {fsr.markdown} as a default team')
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        await interaction.client.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.describe(query="pick a league to use for defaults")
    @app_commands.autocomplete(query=atc_league)
    async def league(self, interaction: Interaction, query: str):
        """Set a default league for your server's Fixture commands"""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_guild:
            err = "You need manage messages permissions to set a defaults."
            return await interaction.client.error(interaction, err)

        if query in interaction.client.games:
            fsr = interaction.client.games[query]
        else:
            fsr = await search(interaction, query, include_fs=True, mode="league")
            if fsr is None:
                return  # Rip

        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                       ON CONFLICT (guild_id) DO UPDATE SET default_league = $2 WHERE excluded.guild_id = $1
                 """, interaction.guild.id, fsr.url)
        finally:
            await interaction.client.db.release(connection)

        e = Embed(description=f'Your Fixtures commands will now use {fsr.markdown} as a default league')
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        await interaction.client.reply(interaction, embed=e)


cmd = [fixtures, results, table, scores, scorers, squad, injuries, stats, formations, summary, head_to_head, stadium,
       Default()]


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot):
        self.bot = bot
        for x in cmd:
            self.bot.tree.add_command(x)


def setup(bot):
    """Load the fixtures Cog into the bot"""
    bot.add_cog(Fixtures(bot))


def teardown(bot):
    """Remove all commands from the bot"""
    for x in cmd:
        bot.tree.remove_command(x)
