"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from copy import deepcopy

# D.py
import discord
from discord.commands import Option
from discord.ext import commands

# Custom Utils
from ext.utils import timed_events, football, embed_utils, view_utils

# Long ass strings.
DF = "Use `.tb default team <team name>` to set a default team\nUse `.tb default league <league name>` to set a " \
     "default league.\n\nThis will allow you to skip the selection process to get information about your favourites."


async def team_or_league(ctx):
    """Check if user's typing is in list of autocompletes."""
    teams = sorted(set([i.home for i in ctx.bot.games] + [i.away for i in ctx.bot.games]))
    leagues = sorted(set([i.league for i in ctx.bot.games]))

    unique = list(teams + leagues)
    queries = ctx.value.lower().split(' ')

    matches = []
    for x in unique:
        if all(q in x.lower() for q in queries):
            matches.append(x)

    return matches


async def live_teams(ctx):
    """Return list of live leagues"""
    teams = sorted([i.home for i in ctx.bot.games] + [i.away for i in ctx.bot.games])
    return [i for i in teams if ctx.value.lower() in i.lower()]


async def live_leagues(ctx):
    """Return list of live leagues"""
    leagues = set([i.league for i in ctx.bot.games if ctx.value.lower() in i.league.lower()])
    return sorted(list(leagues))


async def live_games(ctx):
    """Check if user's typing is in list of live games"""
    games = [f'⚽ {i.home} {i.score} {i.away}: {i.league} ({i.country.lower()})' for i in ctx.bot.games]
    unique = sorted(list(set(games)))
    queries = ctx.value.lower().split(' ')

    matches = []
    for x in unique:
        if all(q in x.lower() for q in queries):
            matches.append(x)
    return sorted(list(set(matches)))


# Autocomplete Search pools.
SEARCH = Option(str, "Search for a Team or League", required=False, autocomplete=team_or_league, default="default")
LEAGUES = Option(str, "Search for a competition", required=False, autocomplete=live_leagues, default="default")
DEF_TEAM = Option(str, "Search for a team to set as the default", autocomplete=live_teams)
DEF_LEAGUES = Option(str, "Search for a league to set as the default", autocomplete=live_leagues)
TEAMS = Option(str, "Search for a team", required=False, autocomplete=live_teams, default="default")
LIVE = Option(str, "Search for a live game", autocomplete=live_games)


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot):
        self.bot = bot

    # Selection View/Filter/Pickers.
    async def search(self, ctx, qry, message, mode=None, include_live=False, include_fs=False) \
            -> football.Team or football.Competition or football.Fixture or None:
        """Get Matches from Live Games & FlashScore Search Results"""
        # Handle Server Defaults
        if qry == "default":
            if ctx.guild is None:
                await self.bot.error(ctx, "You need to specify a search query.")
                return None

            connection = await self.bot.db.acquire()
            async with connection.transaction():
                r = await connection.fetchrow("""SELECT * FROM fixtures_defaults WHERE (guild_id) = $1
                     AND (default_league is NOT NULL OR default_team IS NOT NULL)""", ctx.guild.id)
            await self.bot.db.release(connection)

            if r is None or all(x is None for x in [r["default_team"], r['default_league']]):
                if ctx.channel.permissions_for(ctx.author).manage_guild:
                    await self.bot.error(ctx, "Your server does not have defaults set.\nCheck `/default_league`")
                else:
                    await self.bot.error(ctx, "You need to specify a search query.", ephemeral=True)
                return None

            team = r["default_team"]
            league = r["default_league"]
            if mode == "team":
                default = team if team else league
            else:
                default = league if league else team

            if default is None:
                return await self.bot.error(ctx, "Your server does not have any defaults set.\n"
                                                 "Use the /default_league and /default_team commands.")

            page = await self.bot.browser.newPage()
            try:
                if mode == "team":
                    team_id = default.split('/')[-1]
                    fsr = await football.Team.by_id(team_id, page)
                else:
                    fsr = await football.Competition.by_link(default, page)
            except Exception as e:
                raise e  # Re raise, this is specifically to assure page closure.
            finally:
                await page.close()
            return fsr

        # Gather live games.
        query = str(qry).lower()

        if include_live:
            if mode == "team":
                live = [i for i in ctx.bot.games if query in f"{i.home.lower()} vs {i.away.lower()}"]
            else:
                live = [i for i in ctx.bot.games if query in (i.home + i.away + i.league + i.country).lower()]

            live_options = [("⚽", f"{i.home} {i.score} {i.away}", f"{i.country.upper()}: {i.league}") for i in live]
        else:
            live = live_options = []

        # Gather Other Search Results
        if include_fs:
            search_results = await football.get_fs_results(self.bot, qry)
            pt = 0 if mode == "league" else 1 if mode == "team" else None  # Mode is a hard override.
            if pt is not None:
                search_results = [i for i in search_results if i.participant_type_id == pt]  # Check for specifics.

            for result in search_results:
                result.emoji = '👕' if result.participant_type_id == 1 else '🏆'

            fs_options = [(i.emoji, i.title, i.url) for i in search_results]
        else:
            fs_options = search_results = []

        markers = live_options + fs_options
        items = live + search_results

        if not markers:
            e = discord.Embed()
            e.colour = discord.Colour.red()
            e.description = f'🚫 {ctx.command.name.title()}: No results found for {qry}'
            await message.edit(content="", embed=e)
            return None

        if len(markers) == 1:
            return items[0]

        view = view_utils.ObjectSelectView(ctx, objects=markers, timeout=30)
        view.message = message

        await view.update()
        await view.wait()

        return None if view.value is None else items[int(view.value)]

    # TEAM or LEAGUE commands
    @commands.slash_command()
    async def fixtures(self, ctx, query: SEARCH):
        """Fetch upcoming fixtures for a team or league."""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        fsr = await self.search(ctx, query, message, include_fs=True)
        if fsr is None:
            return

        # Make pretty while waiting.
        e = await fsr.base_embed
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.description = f"Fetching fixtures data for [{fsr.title}][{fsr.url}]..."
        await message.edit(embed=e, content="", view=None)

        # Spawn Browser & Go.
        page = await self.bot.browser.newPage()
        view = fsr.view(ctx, page)
        view.message = message
        await view.push_fixtures()

    @commands.slash_command()
    async def results(self, ctx, query: SEARCH):
        """Get past results for a team or league."""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        fsr = await self.search(ctx, query, message, include_fs=True)
        if fsr is None:
            return

        # Make pretty while waiting.
        e = await fsr.base_embed
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.description = f"Fetching results data for [{fsr.title}][{fsr.url}]..."
        await message.edit(embed=e, content="", view=None)

        # Spawn Browser & Go.
        page = await self.bot.browser.newPage()
        view = fsr.view(ctx, page)
        view.message = message
        await view.push_results()

    @commands.slash_command()
    async def table(self, ctx, query: SEARCH):
        """Get table for a league"""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        fsr = await self.search(ctx, query, message, include_fs=True)
        if fsr is None:
            return

        # Make pretty while waiting.
        e = await fsr.base_embed
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.description = f"Fetching table for {fsr.title}..."
        await message.edit(embed=e, content="", view=None)

        # Spawn Browser & Go.
        page = await self.bot.browser.newPage()
        view = fsr.view(ctx, page)
        view.message = message

        try:  # Only work for Team.
            await view.select_table()
        except AttributeError:
            await view.push_table()

    @commands.slash_command()
    async def scorers(self, ctx, query: SEARCH):
        """Get top scorers from a league, or search for a team and get their top scorers in a league."""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        fsr = await self.search(ctx, query, message, include_fs=True)
        if fsr is None:
            return

        # Make pretty while waiting.
        e = await fsr.base_embed
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.description = f"Fetching Top Scorer Data for [{fsr.title}][{fsr.url}]..."
        await message.edit(embed=e, content="", view=None)

        # Spawn Browser & Go.
        page = await self.bot.browser.newPage()
        view = fsr.view(ctx, page)
        view.message = message
        await view.push_scorers()

    # LEAGUE commands
    @commands.slash_command()
    async def scores(self, ctx, query: LEAGUES):
        """Fetch current scores for a specified league"""
        _ = "all games" if query is None else f"games matching `{query}`"
        message = await self.bot.reply(ctx, content=f"Fetching scores for {_}")

        e = discord.Embed(color=discord.Colour.og_blurple())
        e.title = "Current scores"

        if query is None:
            matches = self.bot.games
        else:
            _ = str(query).lower()
            matches = [i for i in self.bot.games if _ in (i.home + i.away + i.league + i.country).lower()]

        if not matches:
            e.colour = discord.Colour.red()
            _ = "No live games found!"
            if query is not None:
                _ += f" matching search query `{query}`"
            e.description = _
            return await message.edit(content="", embed=e)

        header = f'Scores as of: {timed_events.Timestamp().long}\n'

        matches = [(i.full_league, i.scores_row) for i in matches]
        _ = None
        e.description = header

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

        view = view_utils.Paginator(ctx, embeds)
        view.message = message
        await view.update()

    # TEAM commands.
    @commands.slash_command(description="Fetch a team's current injuries")
    async def injuries(self, ctx, query: TEAMS):
        """Get a team's current injuries"""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        fsr = await self.search(ctx, query, message, include_fs=True, mode="team")
        if fsr is None:
            return  # Rip

        # Make pretty while waiting.
        e = await fsr.base_embed
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.description = f"Fetching injury Data for [{fsr.title}][{fsr.url}]..."
        await message.edit(embed=e, content="", view=None)

        # Spawn Browser & Go.
        page = await self.bot.browser.newPage()
        view = fsr.view(ctx, page)
        view.message = message
        await view.push_injuries()

    @commands.slash_command(description="Fetch the squad for a team")
    async def squad(self, ctx, query: TEAMS):
        """Lookup a team's squad members"""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        fsr = await self.search(ctx, query, message, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

        # Make pretty while waiting.
        e = await fsr.base_embed
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        e.description = f"Fetching Squad Data for [{fsr.title}][{fsr.url}]"
        await message.edit(embed=e, content="", view=None)

        # Spawn Browser & Go.
        page = await self.bot.browser.newPage()
        view = fsr.view(ctx, page)
        view.message = message
        await view.push_squad()

    # FIXTURE commands
    @commands.slash_command(description="Fetch the stats for a fixture")
    async def stats(self, ctx, query: LIVE):
        """Look up the stats for a fixture."""
        if "⚽" in query:
            fsr = [i for i in self.bot.games if i.home in query and i.away in query and i.league in query][0]

            e = await fsr.base_embed
            e.description = f"Fetching Stats..."
            message = await self.bot.reply(ctx, embed=e)
            page = await self.bot.browser.newPage()
        else:
            message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
            fsr = await self.search(ctx, query, message, include_fs=True, include_live=True, mode="team")
            if fsr is None:
                return  # Rip

            page = await self.bot.browser.newPage()
            try:
                fsr = await fsr.pick_recent_game(ctx, message, page)
                if fsr is None:
                    return await page.close()
            except AttributeError:
                pass

        view = fsr.view(ctx, page)
        view.message = message
        await view.push_stats()

    @commands.slash_command(description="Fetch the formations for a fixture")
    async def formations(self, ctx, query: LIVE):
        """Look up the formation for a Fixture."""
        if "⚽" in query:
            fsr = [i for i in self.bot.games if i.home in query and i.away in query and i.league in query][0]

            e = await fsr.base_embed
            e.description = f"Fetching formations..."
            message = await self.bot.reply(ctx, embed=e)
            page = await self.bot.browser.newPage()
        else:
            message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
            fsr = await self.search(ctx, query, message, include_fs=True, include_live=True, mode="team")
            if fsr is None:
                return  # Rip

            page = await self.bot.browser.newPage()
            try:
                fsr = await fsr.pick_recent_game(ctx, message, page)
                if fsr is None:
                    return await page.close()
            except AttributeError:
                pass

            await message.edit(content=f"Fetching Formations for {fsr.home} vs {fsr.away}")

        view = fsr.view(ctx, page)
        view.message = message
        await view.push_lineups()

    @commands.slash_command(description="Fetch the summary for a fixture")
    async def summary(self, ctx, query: LIVE):
        """Get a summary for one of today's games."""
        if "⚽" in query:
            fsr = [i for i in self.bot.games if i.home in query and i.away in query and i.league in query][0]

            e = await fsr.base_embed
            e.description = f"Fetching summary..."
            message = await self.bot.reply(ctx, embed=e)
            page = await self.bot.browser.newPage()
        else:
            message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
            fsr = await self.search(ctx, query, message, include_fs=True, include_live=True, mode="team")
            if fsr is None:
                return  # Rip

            page = await self.bot.browser.newPage()
            try:
                fsr = await fsr.pick_recent_game(ctx, message, page)
                if fsr is None:
                    return await page.close()
            except AttributeError:
                pass

        view = fsr.view(ctx, page)
        view.message = message
        await view.push_summary()

    @commands.slash_command(description="Fetch the head-to-head info for a fixture")
    async def h2h(self, ctx, query: LIVE):
        """Lookup the head-to-head details for a Fixture"""
        if "⚽" in query:
            fsr = [i for i in self.bot.games if i.home in query and i.away in query and i.league in query][0]
            e = await fsr.base_embed
            e.description = f"Fetching Head-To-Head data..."
            message = await self.bot.reply(ctx, embed=e)
            page = await self.bot.browser.newPage()
        else:
            message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
            fsr = await self.search(ctx, query, message, include_fs=True, include_live=True, mode="team")
            if fsr is None:
                return  # Rip

            page = await self.bot.browser.newPage()
            try:
                fsr = await fsr.pick_recent_game(ctx, message, page)
                if fsr is None:
                    return await page.close()
            except AttributeError:
                pass

        view = fsr.view(ctx, page)
        view.message = message
        await view.push_head_to_head()

    # UNIQUE commands
    @commands.slash_command(description="Fetch information about a stadium")
    async def stadium(self, ctx, query: Option(str, "Enter a search query")):
        """Lookup information about a team's stadiums"""
        message = await self.bot.reply(ctx, content=f"Searching for `{query}`...")
        stadiums = await football.get_stadiums(query)
        if not stadiums:
            return await message.edit(content=f"🚫 No stadiums found matching search: {query}")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.league})") for i in stadiums]

        view = view_utils.ObjectSelectView(ctx, objects=markers, timeout=30)
        view.message = message
        await view.update()
        await view.wait()

        if view.value is None:
            return None

        embed = await stadiums[view.value].to_embed
        await message.edit(content="", embed=embed, view=None)

    @commands.slash_command()
    async def default_team(self, ctx, team: DEF_TEAM):
        """Set a default team for your server's Fixture commands"""
        e = discord.Embed()
        e.colour = discord.Colour.red()

        if ctx.guild is None:
            e.description = "This command cannot be ran in DMs"
            await self.bot.reply(ctx, embed=e)
            return

        if not ctx.channel.permissions_for(ctx.author).manage_guild:
            e.description = "You need manage messages permissions to set a defaults."
            await self.bot.reply(ctx, embed=e, ephemeral=True)
            return

        message = await self.bot.reply(ctx, content=f"Searching for {team}...")
        fsr = await self.search(ctx, team, message=message, mode="team", include_fs=True)

        if fsr is None:
            return

        url = fsr.url
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_team) VALUES ($1,$2)
                     ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1
               """, ctx.guild.id, url)
        finally:
            await self.bot.db.release(connection)

        e = discord.Embed()
        e.colour = discord.Colour.green()
        e.description = f'Your Fixtures commands will now use [{fsr.title}]({fsr.url}) as a default team'
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        await message.edit(content="", embed=e, view=None)

    @commands.slash_command()
    async def default_league(self, ctx, league: DEF_LEAGUES):
        """Set a default league for your server's Fixture commands"""
        if ctx.guild is None:
            await self.bot.reply(ctx, content="This command cannot be ran in DMs, sorry!", ephemeral=True)
            return

        if not ctx.channel.permissions_for(ctx.author).manage_guild:
            await self.bot.reply(ctx, content="You need manage messages permissions to set a defaults.", ephemeral=True)
            return

        message = await self.bot.reply(ctx, content=f'Searching for {league}...')
        fsr = await self.search(ctx, league, message=message, mode="league", include_fs=True)

        if fsr is None:
            return

        url = fsr.url
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                       ON CONFLICT (guild_id) DO UPDATE SET default_league = $2 WHERE excluded.guild_id = $1
                 """, ctx.guild.id, url)
        finally:
            await self.bot.db.release(connection)

        e = discord.Embed()
        e.colour = discord.Colour.green()
        e.description = f'Your Fixtures commands will now use [{fsr.title}]({fsr.url}) as a default league'
        if fsr.logo_url is not None:
            logo = "http://www.flashscore.com/res/image/data/" + fsr.logo_url
            e.colour = await embed_utils.get_colour(logo)
            e.set_thumbnail(url=logo)
        await message.edit(content="", embed=e, view=None)


def setup(bot):
    """Load the fixtures Cog into the bot"""
    bot.add_cog(Fixtures(bot))

# Maybe To do?: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# Maybe to do?: League.Form table.
