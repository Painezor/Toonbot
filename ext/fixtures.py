"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from __future__ import annotations

from copy import deepcopy
from importlib import reload
from typing import TYPE_CHECKING

# D.py
from discord import Embed, Colour, Interaction, Message, Permissions
from discord.app_commands import Choice, command, describe, autocomplete, Group
from discord.app_commands import locale_str as _T
from discord.ext.commands import Cog
from discord.ui import View

# Custom Utils
import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils.stadiums import get_stadiums
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import ObjectSelectView, Paginator

if TYPE_CHECKING:
    from core import Bot


# TODO: comp.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# TODO: comp.Form table.


async def team_autocomplete_with_defaults(interaction: Interaction, current: str) -> list[Choice]:
    """Autocomplete from list of stored teams"""
    bot: Bot = interaction.client
    teams: list[fs.Team] = sorted(bot.teams, key=lambda x: x.name)

    if "default" not in interaction.extras:
        if interaction.guild is None:
            interaction.extras['default'] = None
        else:
            async with bot.db.acquire() as connection:
                q = """SELECT default_team FROM fixtures_defaults WHERE (guild_id) = $1"""
                async with connection.transaction():
                    r = await connection.fetchrow(q, interaction.guild.id)

            if r is None or r['default_team'] is None:
                interaction.extras['default'] = None
            else:
                default = bot.get_team(r['default_team'])
                t = Choice(name=f"Server default: {default.name}"[:100], value=default.id)
                interaction.extras['default'] = t

    opts = [Choice(name=t.name[:100], value=t.id) for t in teams if current.lower() in t.name.lower()]

    if opts:
        if interaction.extras['default'] is not None:
            opts = [interaction.extras['default']] + opts
    return list(opts[:25])


async def competition_autocomplete_with_defaults(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete from list of stored competitions"""
    bot: Bot = interaction.client

    lgs = sorted(bot.competitions, key=lambda x: x.title)

    if "default" not in interaction.extras:
        if interaction.guild is None:
            interaction.extras['default'] = None
        else:
            async with bot.db.acquire() as connection:
                async with connection.transaction():
                    q = """SELECT default_league FROM fixtures_defaults WHERE (guild_id) = $1"""
                    r = await connection.fetchrow(q, interaction.guild.id)

            if r is None or r['default_league'] is None:
                interaction.extras['default'] = None
            else:
                default = bot.get_competition(r['default_league'])
                t = Choice(name=f"Server default: {default.title}"[:100], value=default.id)
                interaction.extras['default'] = t

    matches = [i for i in lgs if i.id is not None]
    opts = [Choice(name=lg.title[:100], value=lg.id) for lg in matches if current.lower() in lg.title.lower()]
    if opts:
        if interaction.extras['default'] is not None:
            opts = [interaction.extras['default']] + opts
    return opts[:25]


async def fixture_autocomplete(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Check if user's typing is in list of live games"""
    bot: Bot = interaction.client
    games = [i for i in bot.games if i.id is not None]
    matches = [i for i in games if current.lower() in i.autocomplete.lower()]
    return [Choice(name=i.autocomplete[:100], value=i.id) for i in matches[:25]]


class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(fs)

    # Group Commands for those with multiple available subcommands.
    default = Group(name="default", description="Set the server's default team and competition for commands.",
                    default_permissions=Permissions(manage_guild=True), guild_only=True)

    @default.command(name="team")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def default_team(self, interaction: Interaction, team: str) -> Message:
        """Set the default team for your flashscore lookups"""
        await interaction.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_team(team)

        if fsr is None:
            fsr = await fs.search(interaction, team, mode="team")

            if isinstance(fsr, Message):
                return fsr  # Not Found

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, interaction.guild.id)

                q = """INSERT INTO fixtures_defaults (guild_id, default_team) VALUES ($1,$2)
                       ON CONFLICT (guild_id) DO UPDATE SET default_team = $2  WHERE excluded.guild_id = $1"""
                await connection.execute(q, interaction.guild.id, fsr.id)

        e = await fsr.base_embed
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default team.'
        return await self.bot.reply(interaction, embed=e)

    @default.command(name="competition")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def default_comp(self, interaction: Interaction, competition: str) -> Message:
        """Set the default competition for your flashscore lookups"""
        await interaction.response.defer(thinking=True)

        # Receive Autocomplete.
        fsr = self.bot.get_competition(competition)

        if fsr is None:
            fsr = await fs.search(interaction, competition, mode="comp")

            if isinstance(fsr, Message):
                return fsr  # Not Found

        q = f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET default_league = $2  WHERE excluded.guild_id = $1"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute(q, interaction.guild.id, fsr.id)

        e = await fsr.base_embed
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default competition'
        return await self.bot.reply(interaction, embed=e)

    table = Group(name="table", description="Search for the standings table for a Competition or a Team")

    @table.command(name="competition")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def comp_table(self, interaction: Interaction, competition: str) -> Message:
        """Get the Table of a competition"""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_competition(competition)
        if fsr is None:
            fsr = await fs.search(interaction, competition, mode="comp")
        if isinstance(fsr, Message | None):
            return fsr
        return await fsr.view(interaction).push_table()

    @table.command(name="team")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def team_table(self, interaction: Interaction, team: str) -> Message:
        """Get the Table of one of a Team's competitions"""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_team(team)
        if fsr is None:
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).select_table()

    fixtures = Group(name="fixtures", description="Get the upcoming fixtures for a team or competition")

    @fixtures.command(name="team")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def fx_team(self, interaction: Interaction, team: str) -> Message:
        """Fetch upcoming fixtures for a team."""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_team(team)

        if fsr is None:
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr

        return await fsr.view(interaction).push_fixtures()

    @fixtures.command(name="competition")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def fx_comp(self, interaction: Interaction, competition: str) -> Message:
        """Fetch upcoming fixtures for a competition."""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_competition(competition)
        if fsr is None:
            fsr = await fs.search(interaction, competition, mode="comp")
            if isinstance(fsr, Message):
                return fsr
        return await fsr.view(interaction).push_fixtures()

    results = Group(name="results", description="Get the recent results for a team or competition")

    @results.command(name="team")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def rx_team(self, interaction: Interaction, team: str) -> Message:
        """Get recent results for a Team"""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_team(team)
        if fsr is None:
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).push_results()

    @results.command(name="competition")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def rx_comp(self, interaction: Interaction, competition: str) -> Message:
        """Get recent results for a competition"""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_competition(competition)
        if fsr is None:
            fsr = await fs.search(interaction, competition, mode="comp")
            if isinstance(fsr, Message):
                return fsr
        return await fsr.view(interaction).push_results()

    scorers = Group(name="scorers", description="Get the recent results for a team or competition")

    @scorers.command(name="team")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def scorers_team(self, interaction: Interaction, team: str) -> Message:
        """Get top scorers for a team in various competitions."""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_team(team)
        if fsr is None:
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).push_scorers()

    @scorers.command(name="competition")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def scorers_comp(self, interaction: Interaction, competition: str) -> Message:
        """Get top scorers from a competition."""
        await interaction.response.defer(thinking=True)
        fsr = self.bot.get_competition(competition)
        if fsr is None:
            fsr = await fs.search(interaction, competition, mode="comp")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).push_scorers()

    # COMPETITION only
    @command()
    @describe(competition="Enter the name of a competition to search for")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    async def scores(self, interaction: Interaction, competition: str = None) -> Message | View:
        """Fetch current scores for a specified competition, or all live games."""
        await interaction.response.defer(thinking=True)

        if not self.bot.games:
            return await self.bot.error(interaction, "No live games found")

        if competition:
            if not (matches := [i for i in self.bot.games if i.competition.id == competition]):
                if not (matches := [i for i in self.bot.games if competition.lower() in i.competition.title.lower()]):
                    return await self.bot.error(interaction, f"No live games found for `{competition}`")
        else:
            matches = self.bot.games

        matches = [(i.competition.title, i.live_score_text) for i in matches]
        comp = None
        header = f'Scores as of: {Timestamp().long}\n'
        e: Embed = Embed(color=Colour.og_blurple(), title="Current scores", description=header)

        embeds = []
        for x, y in matches:
            if x != comp:  # We need a new header if it's a new comp.
                comp = x
                output = f"\n**{x}**\n{y}\n"
            else:
                output = f"{y}\n"

            if len(e.description + output) < 2048:
                e.description = f"{e.description}{output}"
            else:
                embeds.append(deepcopy(e))
                e.description = f"{header}\n**{x}**\n{y}\n"
        else:
            embeds.append(deepcopy(e))

        return await Paginator(interaction, embeds).update()

    # TEAM only
    @command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def news(self, interaction: Interaction, team: str) -> Message:
        """Get the latest news for a team"""
        await interaction.response.defer(thinking=True)

        if not (fsr := self.bot.get_team(team)):
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).push_news()

    @command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def injuries(self, interaction: Interaction, team: str) -> Message:
        """Get a team's current injuries"""
        await interaction.response.defer(thinking=True)

        if not (fsr := self.bot.get_team(team)):
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).push_injuries()

    @command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def squad(self, interaction: Interaction, team: str) -> Message:
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)

        if not (fsr := self.bot.get_team(team)):
            fsr = await fs.search(interaction, team, mode="team")
            if isinstance(fsr, Message | None):
                return fsr
        return await fsr.view(interaction).push_squad()

    # FIXTURE commands
    @command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture=_T("Search for a fixture by team name"))
    async def stats(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)
        fix = self.bot.get_fixture(fixture)
        if fix is None:
            fix = await fs.search(interaction, fixture, mode="team", get_recent=True)
        if isinstance(fix, Message | None):
            return fix
        return await fix.view(interaction).push_stats()

    @command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture=_T("Search for a fixture by team name"))
    async def formations(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the formation for a Fixture."""
        await interaction.response.defer(thinking=True)
        fix = self.bot.get_fixture(fixture)
        if fix is None:
            fix = await fs.search(interaction, fixture, mode="team", get_recent=True)
        if isinstance(fix, Message | None):
            return fix
        return await fix.view(interaction).push_lineups()

    @command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def summary(self, interaction: Interaction, fixture: str) -> Message:
        """Get a summary for a fixture"""
        await interaction.response.defer(thinking=True)
        fix = self.bot.get_fixture(fixture)
        if fix is None:
            fix = await fs.search(interaction, fixture, mode="team", get_recent=True)
        if isinstance(fix, Message | None):
            return fix
        return await fix.view(interaction).push_summary()

    @command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture=_T("Search for a fixture by team name"))
    async def head_to_head(self, interaction: Interaction, fixture: str) -> Message:
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)

        if not (fix := self.bot.get_fixture(fixture)):
            fix = await fs.search(interaction, fixture, mode="team", get_recent=True)
        if isinstance(fix, Message):
            return fix
        return await fix.view(interaction).push_head_to_head()

    # UNIQUE commands
    @command()
    @describe(stadium="Search for a stadium by it's name")
    async def stadium(self, interaction: Interaction, stadium: str) -> Message:
        """Lookup information about a team's stadiums"""
        await interaction.response.defer(thinking=True)

        if not (stadiums := await get_stadiums(self.bot, stadium)):
            return await self.bot.error(interaction, f"🚫 No stadiums found matching `{stadium}`")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.name})") for i in stadiums]

        view = ObjectSelectView(interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()
        if view.value is None:
            return await self.bot.error(interaction, content="Timed out waiting for you to reply", followup=False)
        embed = await stadiums[view.value].to_embed
        return await self.bot.reply(interaction, embed=embed)


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
