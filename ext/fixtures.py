"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from copy import deepcopy
# Type hinting
from typing import List, TYPE_CHECKING, Literal

from discord import Embed, Colour, Interaction, Message
# D.py
from discord.app_commands import Choice, command, describe, autocomplete, default_permissions, guild_only
from discord.ext.commands import Cog
from discord.ui import View

# Custom Utils
from ext.utils.football import Competition, Team, Stadium, Fixture, fs_search, get_stadiums
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import ObjectSelectView, Paginator

if TYPE_CHECKING:
    from core import Bot


# TODO: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# TODO: League.Form table.


class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    # Selection View/Filter/Pickers.
    async def search(self, interaction: Interaction, qry: str, mode: Literal['team', 'league'] = None) \
            -> Competition | Fixture | Team | Message:
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
                return self.bot.teams[default] if mode == "team" else self.bot.competitions[default]

        # Gather Other Search Results
        return await fs_search(self.bot, interaction, qry, competitions=mode == "league", teams=mode == "team")

    # Get Recent Game
    async def pick_recent_game(self, i: Interaction, fsr: Competition | Team) -> Fixture | Message:
        """Choose from recent games from FlashScore Object"""
        items: List[Fixture] = await fsr.get_fixtures(subpage="/results")

        _ = [("⚽", i.score_line, f"{i.competition}") for i in items]

        if not _:
            return await self.bot.error(i, f"No recent games found")

        view = ObjectSelectView(self.bot, i, objects=_, timeout=30)
        await view.update(content=f'⏬ Please choose a recent game.')
        await view.wait()

        if view.value is None:
            return await self.bot.error(i, 'Timed out waiting for your response')

        return items[view.value]

    # Autocompletes
    async def tm_ac(self, interaction: Interaction, current: str) -> List[Choice[str]]:
        """Autocomplete from list of stored teams"""
        await interaction.response.defer(thinking=True)
        teams = sorted(list(self.bot.teams.values()), key=lambda x: x.name)
        return [Choice(name=t.name, value=t.id) for t in teams if current.lower() in t.name.lower()][:25]

    async def lg_ac(self, _: Interaction, current: str) -> List[Choice[str]]:
        """Autocomplete from list of stored leagues"""
        lgs = sorted(list(self.bot.competitions.values()), key=lambda x: x.title)
        return [Choice(name=i.title[:100], value=i.id) for i in lgs if current.lower() in i.title.lower()][:25]

    async def tm_lg_ac(self, interaction: Interaction, current: str) -> List[Choice[str]]:
        """An Autocomplete that checks whether team or league is selected, then return appropriate autocompletes"""
        if interaction.namespace.mode == "team":
            return await self.tm_ac(interaction, current)
        elif interaction.namespace.mode == "league":
            return await self.lg_ac(interaction, current)
        else:
            return []

    async def fx_ac(self, _: Interaction, current: str) -> List[Choice[str]]:
        """Check if user's typing is in list of live games"""
        games = self.bot.games.values()

        matches = []
        for g in games:
            try:
                if current.lower() not in f"{g.home.name.lower()} {g.away.name.lower()} {g.competition.title.lower()}":
                    continue
            except AttributeError:
                print(f'DEBUG Could not find lower for: {g.home.name} | {g.away.name} | {g.competition.title}')
                continue

            out = f"⚽ {g.home} {g.score} {g.away} ({g.competition.title})"[:100]
            matches.append(Choice(name=out, value=g.id))
        return matches[:25]

    @command()
    @guild_only()
    @autocomplete(query=tm_lg_ac)
    @default_permissions(manage_guild=True)
    @describe(mode="search for a team or a league?", query="enter a search query")
    async def default(self, i: Interaction, mode: Literal["team", "league"], query: str) -> Message:
        """Set a default team or league for your flashscore lookups"""
        await i.response.defer(thinking=True)

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
    @command()
    @describe(mode="search for a team or a league?", query="enter a search query")
    @autocomplete(query=tm_lg_ac)
    async def fixtures(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> Message:
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
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        return await view.push_fixtures()

    @command()
    @describe(mode="search for a team or a league?", query="enter a search query")
    @autocomplete(query=tm_lg_ac)
    async def results(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> Message:
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
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        return await view.push_results()

    @command()
    @autocomplete(query=tm_lg_ac)
    @describe(mode="search for a team or a league?", query="enter a search query")
    async def table(self, i: Interaction, mode: Literal["team", "league"], *, query: str = 'default') -> Message:
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
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        try:
            return await view.select_table()
        except AttributeError:
            return await view.push_table()

    @command()
    @autocomplete(query=tm_lg_ac)
    @describe(mode="search for a team or a league?", query="enter a search query")
    async def scorers(self, i: Interaction, mode: Literal["team", "league"], query: str = 'default') -> Message:
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
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(i, await self.bot.browser.newPage())
        return await view.push_scorers()

    # LEAGUE only
    @command()
    @describe(query="enter a search query")
    @autocomplete(query=lg_ac)
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
        header = f'Scores as of: {Timestamp().long}\n'
        e: Embed = Embed(color=Colour.og_blurple(), title="Current scores", description=header)

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

        view = Paginator(self.bot, interaction, embeds)
        return await view.update()

    # TEAM only
    @command()
    @autocomplete(query=tm_ac)
    @describe(query="enter a search query")
    async def news(self, interaction: Interaction, query: str = 'default') -> Message:
        """Get the latest news for a team"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_news()

    @command()
    @autocomplete(query=tm_ac)
    @describe(query="enter a search query")
    async def injuries(self, interaction: Interaction, query: str = 'default') -> Message:
        """Get a team's current injuries"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_injuries()

    @command()
    @describe(query="team name to search for")
    @autocomplete(query=tm_ac)
    async def squad(self, interaction: Interaction, query: str = 'default') -> Message:
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.teams:
            fsr = self.bot.teams[query]
        else:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_squad()

    # FIXTURE commands
    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def stats(self, interaction: Interaction, query: str) -> Message:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        view = fsr.view(interaction, await self.bot.browser.newPage())
        return await view.push_stats()

    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def formations(self, interaction: Interaction, query: str) -> Message:
        """Look up the formation for a Fixture."""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
            page = await self.bot.browser.newPage()
            view = fsr.view(interaction, page)
            return await view.push_lineups()

        fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        page = await self.bot.browser.newPage()
        view = fsr.view(interaction, page)
        return await view.push_lineups()

    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def summary(self, interaction: Interaction, query: str) -> Message:
        """Get a summary for a fixture"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        page = await self.bot.browser.newPage()
        view = fsr.view(interaction, page)
        return await view.push_summary()

    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def head_to_head(self, interaction: Interaction, query: str) -> Message:
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)

        if query in self.bot.games:
            fsr = self.bot.games[query]
        else:
            fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        page = await self.bot.browser.newPage()
        view = fsr.view(interaction, page)
        return await view.push_head_to_head()

    # UNIQUE commands
    @command()
    @describe(query="enter a stadium name")
    async def stadium(self, interaction: Interaction, query: str) -> Message:
        """Lookup information about a team's stadiums"""
        await interaction.response.defer(thinking=True)

        stadiums: List[Stadium] = await get_stadiums(self.bot, query)
        if not stadiums:
            return await self.bot.error(interaction, f"🚫 No stadiums found matching `{query}`")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.name})") for i in stadiums]

        view = ObjectSelectView(self.bot, interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()

        if view.value is None:
            return await self.bot.error(interaction, "Timed out waiting for you to reply", followup=False)

        embed = await stadiums[view.value].to_embed
        return await self.bot.reply(interaction, embed=embed)


async def setup(bot: 'Bot'):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
