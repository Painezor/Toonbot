"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from copy import deepcopy
# Type hinting
from typing import List, TYPE_CHECKING, Literal

from asyncpg import Pool
from discord import Embed, Colour, Interaction, Message
# D.py
from discord.app_commands import Choice, command, describe, autocomplete, default_permissions, guild_only
from discord.ext.commands import Cog
from discord.ui import View

# Custom Utils
from ext.utils.flashscore import Competition, Team, Stadium, Fixture, search, get_stadiums, FlashScoreItem, fx_ac
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import ObjectSelectView, Paginator

if TYPE_CHECKING:
    from core import Bot


# TODO: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# TODO: League.Form table.


async def tm_ac(interaction: Interaction, current: str) -> List[Choice]:
    """Autocomplete from list of stored teams"""
    await interaction.response.defer()
    teams = sorted(getattr(interaction.client, 'teams'), key=lambda x: x.name)

    if not hasattr(interaction.extras, "default"):
        if interaction.guild is None:
            interaction.extras['default'] = None
        else:
            db: Pool = getattr(interaction.client, "db")
            connection = await db.acquire()
            try:
                async with connection.transaction():
                    r = await connection.fetchrow(
                        """SELECT default_team FROM fixtures_defaults WHERE (guild_id) = $1""",
                        interaction.guild.id)
            finally:
                await db.release(connection)

            if r is None or r['default_team'] is None:
                interaction.extras['default'] = None
            else:
                finder = getattr(interaction.client, "get_team")
                default = finder(r['default_team'])
                t = Choice(name=f"Server default: {default.name}"[:100], value=default.id)
                interaction.extras['default'] = t

    opts = [Choice(name=t.name[:100], value=t.id) for t in teams if current.lower() in t.name.lower()]

    if opts:
        if interaction.extras['default'] is not None:
            opts = [interaction.extras['default']] + opts
    return list(opts[:25])


async def lg_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Autocomplete from list of stored leagues"""
    lgs = sorted(getattr(interaction.client, 'competitions'), key=lambda x: x.title)

    if not hasattr(interaction.extras, "default"):
        if interaction.guild is None:
            interaction.extras['default'] = None
        else:
            db: Pool = getattr(interaction.client, "db")
            connection = await db.acquire()
            try:
                async with connection.transaction():
                    r = await connection.fetchrow(
                        """SELECT default_league FROM fixtures_defaults WHERE (guild_id) = $1""",
                        interaction.guild.id)
            finally:
                await db.release(connection)

            if r is None or r['default_league'] is None:
                interaction.extras['default'] = None
            else:
                finder = getattr(interaction.client, "get_competition")
                default = finder(r['default_league'])
                t = Choice(name=f"Server default: {default.title}"[:100], value=default.id)
                interaction.extras['default'] = t

    matches = [i for i in lgs if i.id is not None]
    opts = [Choice(name=lg.title[:100], value=lg.id) for lg in matches if current.lower() in lg.title.lower()]
    if opts:
        if interaction.extras['default'] is not None:
            opts = [interaction.extras['default']] + opts
    return opts[:25]


async def tm_lg_ac(interaction: Interaction, current: str) -> List[Choice]:
    """An Autocomplete that checks whether team or league is selected, then return appropriate autocompletes"""
    if interaction.namespace.mode == "team":
        return await tm_ac(interaction, current)
    elif interaction.namespace.mode == "league":
        return await lg_ac(interaction, current)
    else:
        return []


class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    # Selection View/Filter/Pickers.
    async def search(self, interaction: Interaction, qry: str, mode: Literal['team', 'league'] = None) \
            -> FlashScoreItem | Message:
        """Get Matches from Live Games & FlashScore Search Results"""
        # Gather Other Search Results
        return await search(self.bot, interaction, qry, competitions=mode == "league", teams=mode == "team")

    # Get Recent Game
    async def pick_recent_game(self, i: Interaction, fsr: Competition | Team) -> Fixture | Message:
        """Choose from recent games from FlashScore Object"""
        items: List[Fixture] = await fsr.results()

        _ = [("⚽", i.score_line, f"{i.competition}") for i in items]

        if not _:
            return await self.bot.error(i, f"No recent games found")

        view = ObjectSelectView(self.bot, i, objects=_, timeout=30)
        await view.update(content=f'⏬ Please choose a recent game.')
        await view.wait()

        if view.value is None:
            return await self.bot.error(i, 'Timed out waiting for your response')

        return items[view.value]

    @command()
    @guild_only()
    @autocomplete(query=tm_lg_ac)
    @default_permissions(manage_guild=True)
    @describe(mode="search for a team or a league?", query="enter a search query")
    async def default(self, i: Interaction, mode: Literal["team", "league"], query: str) -> Message:
        """Set a default team or league for your flashscore lookups"""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_competition(query)
        if fsr is None:
            fsr = self.bot.get_team(query)

            if fsr is None:
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
    async def fixtures(self, i: Interaction, mode: Literal["team", "league"], query) -> Message:
        """Fetch upcoming fixtures for a team or league."""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_competition(query)
        if fsr is None:
            fsr = self.bot.get_team(query)

            if fsr is None:
                fsr = await self.search(i, query, mode=mode)

                if isinstance(fsr, Message):
                    return fsr

        return await fsr.view(i).push_fixtures()

    @command()
    @describe(mode="search for a team or a league?", query="enter a search query")
    @autocomplete(query=tm_lg_ac)
    async def results(self, i: Interaction, mode: Literal["team", "league"], query: str) -> Message:
        """Get past results for a team or league."""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_competition(query)
        if fsr is None:
            fsr = self.bot.get_team(query)
            if fsr is None:
                fsr = await self.search(i, query, mode=mode)

                if isinstance(fsr, Message):
                    return fsr

        return await fsr.view(i).push_results()

    @command()
    @autocomplete(query=tm_lg_ac)
    @describe(mode="search for a team or a league?", query="enter a search query")
    async def table(self, i: Interaction, mode: Literal["team", "league"], *, query: str) -> Message:
        """Get table for a league"""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_competition(query)
        if fsr is None:
            fsr = self.bot.get_team(query)

            if fsr is None:
                fsr = await self.search(i, query, mode=mode)

                if isinstance(fsr, Message | None):
                    return fsr

        # Spawn Browser & Go.
        view = fsr.view(i)
        try:
            return await view.select_table()
        except AttributeError:
            return await view.push_table()

    @command()
    @autocomplete(query=tm_lg_ac)
    @describe(mode="search for a team or a league?", query="enter a search query")
    async def scorers(self, i: Interaction, mode: Literal["team", "league"], query: str) -> Message:
        """Get top scorers from a league, or search for a team and get their top scorers in a league."""
        await i.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_competition(query)
        if fsr is None:
            fsr = self.bot.get_team(query)

            if fsr is None:
                fsr = await self.search(i, query, mode=mode)

                if isinstance(fsr, Message):
                    return fsr

        # Spawn Browser & Go.
        view = fsr.view(i)
        return await view.push_scorers()

    # LEAGUE only
    @command()
    @describe(query="enter a search query")
    @autocomplete(query=lg_ac)
    async def scores(self, interaction: Interaction, query: str = None) -> Message | View:
        """Fetch current scores for a specified league"""
        await interaction.response.defer(thinking=True)

        if query:
            matches = [i for i in self.bot.games if i.competition.id == query]

            if not matches:
                _ = str(query).lower()
                matches = [i for i in self.bot.games if _.lower() in i.competition.title.lower()]
        else:
            matches = self.bot.games

        if not matches:
            err = "No live games found"
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
    async def news(self, interaction: Interaction, query: str) -> Message:
        """Get the latest news for a team"""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_team(query)
        if not fsr:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        view = fsr.view(interaction)
        return await view.push_news()

    @command()
    @autocomplete(query=tm_ac)
    @describe(query="enter a search query")
    async def injuries(self, interaction: Interaction, query: str) -> Message:
        """Get a team's current injuries"""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_team(query)
        if not fsr:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(interaction)
        return await view.push_injuries()

    @command()
    @describe(query="team name to search for")
    @autocomplete(query=tm_ac)
    async def squad(self, interaction: Interaction, query: str) -> Message:
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_team(query)
        if not fsr:
            fsr = await self.search(interaction, query, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        # Spawn Browser & Go.
        view = fsr.view(interaction)
        return await view.push_squad()

    # FIXTURE commands
    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def stats(self, interaction: Interaction, query: str) -> Message:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_fixture(query)
        if not fsr:
            fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            fsr = await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        view = fsr.view(interaction)
        return await view.push_stats()

    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def formations(self, interaction: Interaction, query: str) -> Message:
        """Look up the formation for a Fixture."""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_fixture(query)
        if fsr:
            view = fsr.view(interaction)
            return await view.push_lineups()

        fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            fsr = await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        view = fsr.view(interaction)
        return await view.push_lineups()

    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def summary(self, interaction: Interaction, query: str) -> Message:
        """Get a summary for a fixture"""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_fixture(query)
        if not fsr:
            fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            fsr = await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        view = fsr.view(interaction)
        return await view.push_summary()

    @command()
    @autocomplete(query=fx_ac)
    @describe(query="search by team names")
    async def head_to_head(self, interaction: Interaction, query: str) -> Message:
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)

        fsr = self.bot.get_fixture(query)
        if not fsr:
            fsr = await self.search(interaction, query, mode="team")

        if isinstance(fsr, Competition | Team):
            fsr = await self.pick_recent_game(interaction, fsr)

        if isinstance(fsr, Message):
            return fsr

        view = fsr.view(interaction)
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
            return await self.bot.error(interaction, content="Timed out waiting for you to reply", followup=False)

        embed = await stadiums[view.value].to_embed
        return await self.bot.reply(interaction, embed=embed)


async def setup(bot: 'Bot'):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
