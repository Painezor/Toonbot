"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from __future__ import annotations

import asyncio
import io
import logging
from copy import deepcopy
from datetime import datetime
from importlib import reload
from typing import TYPE_CHECKING, ClassVar, Literal, Callable

# D.py
import discord
from discord import Embed, Colour, Interaction, Message, Permissions, SelectOption
from discord.app_commands import Choice, command, describe, autocomplete, Group
from discord.ext.commands import Cog
from discord.ui import Select

# Custom Utils
from lxml import html
from playwright.async_api import Page

import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils.stadiums import get_stadiums
from ext.utils import view_utils, embed_utils, flags, image_utils
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot

# TODO: comp.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# TODO: comp.Form table.

logger = logging.getLogger('Fixtures')
semaphore = asyncio.Semaphore(5)


# Autocompletes
async def team_autocomplete_with_defaults(interaction: Interaction, current: str) -> list[Choice]:
    """Autocomplete from list of stored teams"""
    bot: Bot = interaction.client
    teams: list[fs.Team] = sorted(bot.teams, key=lambda x: x.name)

    if "default" not in interaction.extras:
        if interaction.guild is None:
            interaction.extras['default'] = None
        else:
            async with bot.db.acquire(timeout=60) as connection:
                q = """SELECT default_team FROM fixtures_defaults WHERE (guild_id) = $1"""
                async with connection.transaction():
                    r = await connection.fetchrow(q, interaction.guild.id)

            if r is None or r['default_team'] is None:
                interaction.extras['default'] = None
            else:
                default = bot.get_team(r['default_team'])
                t = Choice(name=f"Server default: {default.name}"[:100], value=default.id)
                interaction.extras['default'] = t

    if opts := [Choice(name=t.name[:100], value=t.id) for t in teams if current.lower() in t.name.lower()]:
        if interaction.extras['default'] is not None:
            opts = [interaction.extras['default']] + opts
    return list(opts[:25])


async def competition_autocomplete_with_defaults(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete from list of stored competitions"""
    lgs = sorted(interaction.client.competitions, key=lambda x: x.title)

    if "default" not in interaction.extras:
        if interaction.guild is None:
            interaction.extras['default'] = None
        else:
            async with interaction.client.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    q = """SELECT default_league FROM fixtures_defaults WHERE (guild_id) = $1"""
                    r = await connection.fetchrow(q, interaction.guild.id)

            if r is None or r['default_league'] is None:
                interaction.extras['default'] = None
            else:
                default = interaction.client.get_competition(r['default_league'])
                t = Choice(name=f"Server default: {default.title}"[:100], value=default.id)
                interaction.extras['default'] = t

    matches = [i for i in lgs if i.id is not None]
    if opts := [Choice(name=lg.title[:100], value=lg.id) for lg in matches if current.lower() in lg.title.lower()]:
        if interaction.extras['default'] is not None:
            opts = [interaction.extras['default']] + opts
    return opts[:25]


async def fixture_autocomplete(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Check if user's typing is in list of live games"""
    games = [i for i in interaction.client.games if i.id is not None]
    matches = [i for i in games if current.lower() in i.autocomplete.lower()]
    choices = [Choice(name=i.autocomplete[:100], value=i.id) for i in matches[:25]]
    if current:
        if len(choices) == 25:  # Replace Item #25
            choices[-1] = [Choice(name=f"🔎 Search for '{current}'", value=current)]
        else:  # Or Add
            choices.append(Choice(name=f"🔎 Search for '{current}'", value=current))
    return choices


class CompetitionView(view_utils.BaseView):
    """The view sent to a user about a Competition"""
    bot: ClassVar[Bot]

    def __init__(self, interaction: Interaction,
                 competition: fs.Competition, parent: view_utils.BaseView = None) -> None:
        super().__init__()

        self.competition: fs.Competition = competition
        self.interaction: Interaction = interaction

        # Embed and internal index.
        self.pages: list[Embed] = []
        self.index: int = 0
        self.parent: view_utils.BaseView = parent

        # Button Disabling
        self._disabled: str = None

        # Player Filtering
        self._nationality_filter: list[str] = []
        self._team_filter: list[str] = []
        self._filter_mode: str = "goals"

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.bot.user.id

    async def on_timeout(self) -> Message:
        """Cleanup"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = None) -> Message:
        """Send the latest version of the CompetitionView to the user"""
        self.clear_items()

        if self._filter_mode:
            # Generate New Dropdowns.
            players = await self.filter_players()

            # List of Unique team names as Option()s
            teams = set(i.team for i in players if i.team)
            teams = sorted(teams, key=lambda t: t.name)

            if opt := [('👕', i.name, i.link) for i in teams]:
                sel = view_utils.MultipleSelect(placeholder="Filter by Team…", options=opt,
                                                attribute='team_filter', row=2)
                if self._team_filter:
                    sel.placeholder = f"Teams: {', '.join(self._team_filter)}"
                self.add_item(sel)

            # List of Unique nationalities as Option()s
            if f := [(flags.get_flag(i), i, '') for i in sorted(set(i.country for i in players if i.country))]:
                ph = "Filter by Nationality…"
                sel = view_utils.MultipleSelect(placeholder=ph, options=f, attribute='nationality_filter', row=3)
                if self._nationality_filter:
                    sel.placeholder = f"Countries:{', '.join(self._nationality_filter)}"
                self.add_item(sel)

        for button in [view_utils.FuncButton(label="Table", func=self.push_table, emoji="🥇", row=4),
                       view_utils.FuncButton(label="Scorers", func=self.push_scorers, emoji='⚽', row=4),
                       view_utils.FuncButton(label="Fixtures", func=self.push_fixtures, emoji='📆', row=4),
                       view_utils.FuncButton(label="Results", func=self.push_results, emoji='⚽', row=4)]:
            button.disabled = True if self._disabled == button.label else False
            self.add_item(button)

        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = next(iter(self.pages), None)

        return await self.bot.reply(self.interaction, content=content, view=self, embed=embed)

    async def filter_players(self) -> list[fs.Player]:
        """Filter player list according to dropdowns."""
        embed = await self.competition.base_embed
        players = await self.competition.scorers()
        all_players = players.copy()

        if self._nationality_filter:
            players = [i for i in players if i.country in self._nationality_filter]

        if self._team_filter:
            players = [x for x in players if x.team.name in self._team_filter]

        match self._filter_mode:
            case "goals":
                srt = sorted([i for i in players if i.goals > 0], key=lambda p: p.goals, reverse=True)
                embed.title = f"≡ Top Scorers for {embed.title}"
                rows = [i.scorer_row for i in srt]
            case "assists":
                s = sorted([i for i in players if i.assists > 0], key=lambda p: p.assists, reverse=True)
                embed.title = f"≡ Top Assists for {embed.title}"
                rows = [i.assist_row for i in s]
            case _:
                logger.error(f"INVALID _filter_mode {self._filter_mode} in CompetitionView")
                rows = [str(i) for i in players]

        if not rows:
            rows = [f'```yaml\nNo Top Scorer Data Available matching your filters```']

        embeds = embed_utils.rows_to_embeds(embed, rows)
        self.pages = embeds
        return all_players

    async def push_table(self) -> Message:
        """Push Team's Table for a Competition to View"""
        embed = await self.competition.base_embed
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition}"
        if img := await self.competition.table():
            embed.set_image(url=img)
            embed.description = Timestamp().long
        else:
            embed.description = "No Table Found"

        self.index = 0
        self.pages = [embed]
        self._filter_mode = None
        self._disabled = "Table"
        return await self.update()

    async def push_scorers(self) -> Message:
        """PUsh the Scorers Embed to Competition View"""
        self.index = 0
        self._filter_mode = "goals"
        self._disabled = "Scorers"
        self._nationality_filter = None
        self._team_filter = None
        return await self.update()

    async def push_assists(self) -> Message:
        """PUsh the Scorers Embed to View"""
        self.index = 0
        self._filter_mode = "assists"
        self._disabled = "Assists"
        self._nationality_filter = []
        self._team_filter = []
        return await self.update()

    async def push_fixtures(self) -> Message:
        """Push upcoming competition fixtures to View"""
        rows = await self.competition.fixtures()
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.competition.base_embed
        embed.title = f"≡ Fixtures for {self.competition}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Fixtures"
        self._filter_mode = None
        return await self.update()

    async def push_results(self) -> Message:
        """Push results fixtures to View"""
        rows = await self.competition.results()
        rows = [i.upcoming for i in rows] if rows else ["No Results Found"]
        embed = await self.competition.base_embed
        embed.title = f"≡ Results for {self.competition.title}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Results"
        self._filter_mode = None
        return await self.update()


class TeamView(view_utils.BaseView):
    """The View sent to a user about a Team"""
    bot: ClassVar[Bot]

    def __init__(self, interaction: Interaction, team: fs.Team, parent: view_utils.BaseView = None):
        super().__init__()
        self.team: fs.Team = team
        self.interaction: interaction = interaction
        self.parent: view_utils.BaseView = parent

        # Pagination
        self.pages = []
        self.index = 0

        # Specific Selection
        self.league_select: list[fs.Competition] = []

        # Disable buttons when changing pages.
        # Page buttons have their own callbacks so cannot be directly passed to update
        self._disabled: str = None

    async def on_timeout(self) -> Message:
        """Cleanup"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = None) -> Message:
        """Push the latest version of the TeamView to the user"""
        self.clear_items()
        if self.league_select:
            self.add_item(LeagueTableSelect(leagues=self.league_select))
            self.league_select.clear()
        else:
            view_utils.add_page_buttons(self, row=4)

            opts = [(SelectOption(label="Squad", emoji='🏃'), {}, self.push_squad),
                    (SelectOption(label="Injuries", emoji=fs.INJURY_EMOJI), {}, self.push_injuries),
                    (SelectOption(label="Top Scorers", emoji='⚽'), {}, self.push_scorers),
                    (SelectOption(label="Table", emoji='🗓️'), {}, self.select_table),
                    (SelectOption(label="Fixtures", emoji='📆'), {}, self.push_fixtures),
                    (SelectOption(label="Results", emoji='🇼'), {}, self.push_results),
                    (SelectOption(label="News", emoji='📰'), {}, self.push_news)]

            for count, item in enumerate(opts):
                item[0].value = count

            self.add_item(view_utils.FuncDropdown(opts, placeholder="Additional info...", row=0))

        embed = self.pages[self.index] if self.pages else None
        return await self.bot.reply(self.interaction, content=content, view=self, embed=embed)

    async def push_news(self) -> Message:
        """Push News to View"""
        self.pages = await self.team.news()
        self.index = 0
        self._disabled = "News"
        return await self.update()

    async def push_squad(self) -> Message:
        """Push the Squad Embed to the team View"""
        players = await self.team.players()
        p = [i.squad_row for i in sorted(players, key=lambda x: x.number)]

        # Data must be fetched before embed url is updated.
        embed = await self.team.base_embed
        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, p)
        self._disabled = "Squad"
        return await self.update()

    async def push_injuries(self) -> Message:
        """Push the Injuries Embed to the team View"""
        embed = await self.team.base_embed
        players = await self.team.players()
        players = [i.injury_row for i in players if i.injury is not None] if players else ['No injuries found']
        embed.description = "\n".join(players)
        self.index = 0
        self.pages = [embed]
        self._disabled = "Injuries"
        return await self.update()

    async def push_scorers(self) -> Message:
        """Push the Scorers Embed to the team View"""
        embed = await self.team.base_embed
        players = await self.team.players()

        p = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
        rows = [i.scorer_row for i in p]

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Scorers"
        return await self.update()

    async def select_table(self) -> Message:
        """Select Which Table to push from"""
        self.index = 0
        fixtures = await self.team.fixtures()

        if len(comps := [i for i in set(x.competition for x in fixtures) if i.name != "Club Friendly"]) == 1:
            return await self.push_table(next(comps))

        self.league_select = comps
        leagues = [f"• {x.flag} {x.markdown}" for x in comps]

        e = await self.team.base_embed
        e.description = "**Use the dropdown to select a table**:\n\n " + "\n".join(leagues)
        self.pages = [e]
        return await self.update()

    async def push_table(self, res: fs.Competition) -> Message:
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.team.base_embed
        embed.title = f"≡ Table for {res.title}"
        if img := await res.table():
            embed.set_image(url=img)
            embed.description = Timestamp().long
        else:
            embed.description = f"No Table found."

        self.pages = [embed]
        self.index = 0
        self._disabled = "Table"
        return await self.update()

    async def push_fixtures(self) -> Message:
        """Push upcoming fixtures to Team View"""
        rows = await self.team.fixtures()
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.team.base_embed
        embed.title = f"≡ Fixtures for {self.team.name}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Fixtures"
        return await self.update()

    async def push_results(self) -> Message:  # Team
        """Push results fixtures to View"""
        output = []
        for i in await self.team.results():

            if i.home.url == self.team.url:
                home = True
            elif i.away.url == self.team.url:
                home = False
            else:
                home = None
                logger.info(f"team push_results: [HOME: {i.home.url}] [AWAY: {i.away.url}] [TARGET: {self.team.url}]")

            if home is None:
                emoji = ""
            else:
                if i.score_home > i.score_away:
                    emoji = '🇼' if home else '🇱'
                elif i.score_home < i.score_away:
                    emoji = '🇱' if home else '🇼'
                else:
                    if i.penalties_home is None:
                        emoji = '🇩'
                    else:
                        if i.penalties_home > i.penalties_away:
                            emoji = '🇼' if home else '🇱'
                        elif i.penalties_home < i.penalties_away:
                            emoji = '🇱' if home else '🇼'
                        else:
                            emoji = ''

            output.append(f'{emoji} {i.ko_relative}: {i.bold_markdown} ')

        if not output:
            output = ["No Results Found"]

        embed = await self.team.base_embed
        embed.title = f"≡ Results for {self.team.name}" if embed.title else "≡ Results "

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, output)
        self._disabled = "Results"
        return await self.update()


class FixtureView(view_utils.BaseView):
    """The View sent to users about a fixture."""
    bot: ClassVar[Bot]

    def __init__(self, interaction: Interaction, fixture: fs.Fixture) -> None:
        self.fixture: fs.Fixture = fixture
        self.interaction: Interaction = interaction
        super().__init__()

    async def on_timeout(self) -> Message:
        """Cleanup"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    async def handle_tabs(self, page: Page, current_function: Callable):
        """Generate our buttons"""
        self.clear_items()

        if self.fixture.home.id:
            h = TeamView(self.interaction, self.fixture.home, parent=self).update
            self.add_item(view_utils.FuncButton(self.fixture.home, h))

        if self.fixture.away.id:
            a = TeamView(self.interaction, self.fixture.away, parent=self).update
            self.add_item(view_utils.FuncButton(self.fixture.away, a))

        row_1: list[view_utils.Funcable] = []
        row_2: list[view_utils.Funcable] = []
        sl = f"{self.fixture.home.name} v {self.fixture.away.name}"
        for i in range(await (locator := page.locator('div.tabs__group > a')).count()):
            d = await locator.nth(i).get_attribute("aria-current") is not None
            match (text := await locator.nth(i).text_content()):
                case "Match": row_1.append(view_utils.Funcable("Match", self.summary, disabled=d))
                case "Standings":
                    logging.info('Found Standings button')
                    if text not in [r.label for r in row_1]:
                        logging.info('No Previous Standings button, adding a new one.')
                        row_1.append(view_utils.Funcable("Standings", self.table, disabled=d))
                    else:
                        logging.info(f'Standings Button already exists.')

                    # We need a duplicate
                    if current_function == self.table:
                        if text not in [r.label for r in row_2]:
                            row_2.append(view_utils.Funcable("Standings", self.table, disabled=d))
                case "H2H": row_1.append(view_utils.Funcable('H2H', self.h2h, disabled=d))
                case "Summary": row_1.append(view_utils.Funcable('Summary', self.summary, disabled=d))
                case "Lineups": row_1.append(view_utils.Funcable('Lineups', self.lineups, disabled=d))
                case "Stats": row_2.append(view_utils.Funcable('Stats', self.stats, disabled=d))
                case "Over/Under":
                    row_2.append(view_utils.Funcable('Over/Under', self.table, args=['over_under'], disabled=d))
                case "HT/FT": row_2.append(view_utils.Funcable('HT/FT', self.table, args=['ht_ft'], disabled=d))
                case "Form": row_2.append(view_utils.Funcable('Form', self.table, args=['form'], disabled=d))
                # TODO: Enable News
                case "News": row_1.append(view_utils.Funcable('News', self.news, disabled=True, emoji="📰",
                                                              description=f"News surrounding {sl}"))
                # TODO: Enable Photos
                case "Photos": row_1.append(view_utils.Funcable('News', self.photos, disabled=True, emoji="📷",
                                                                description=f"Photos from {sl}"))
                # TODO: Enable Videos
                case "Video": row_1.append(view_utils.Funcable('Video', self.video, disabled=True, emoji="📹",
                                                               description="Videos and highlights"))
                case "Odds":
                    # TODO: Figure out if we want to encourage Gambling
                    pass
                case _: logger.info(f'Handle_tabs found extra tab named {text}')
        view_utils.generate_function_row(self, row_1, 1, placeholder="Find more information")
        view_utils.generate_function_row(self, row_2, 2, placeholder=f"View more {current_function.__name__}s")

    async def h2h(self, team: Literal['overall', 'home', 'away'] = 'overall') -> dict[str, fs.Fixture]:
        """Get results of recent games related to the two teams in the fixture"""
        e: Embed = await self.fixture.base_embed
        e.description = ""  # Will be overwritten

        match team:
            case 'overall': e.title = "Head to Head: Overall"
            case 'home': e.title = f"Head to Head: {self.fixture.home.name} at Home"
            case 'away': e.title = f"Head to Head: {self.fixture.away.name} Away"

        async with semaphore:
            page = await self.bot.browser.new_page()

            try:
                await page.goto(f"{self.fixture.link}/#/h2h/{team}", timeout=5000)
                await page.wait_for_selector(".h2h", timeout=5000)
                await self.handle_tabs(page, self.h2h)

                for i in range(await (locator := page.locator('div.subTabs > a')).count()):
                    disabled = await locator.nth(i).get_attribute("aria-current") is not None
                    label = await locator.nth(i).text_content()
                    match i:
                        case 0:
                            self.add_item(
                                view_utils.FuncButton(label, self.h2h, ['overall'], disabled=disabled, row=3))
                        case 1:
                            self.add_item(
                                view_utils.FuncButton(label, self.h2h, ['home'], disabled=disabled, row=3))
                        case 2:
                            self.add_item(
                                view_utils.FuncButton(label, self.h2h, ['away'], disabled=disabled, row=3))

                tree: html.HtmlElement = html.fromstring(await page.inner_html('.h2h'))
            finally:
                await page.close()

        game: html.HtmlElement
        for row in tree.xpath('.//div[@class="rows" or @class="section__title"]'):
            if "section__title" in row.classes:
                header = row.xpath('.//text()')[0]
                e.description += f"\n**{header}**\n"
                continue

            else:
                for game in row:
                    home = ''.join(
                        game.xpath('.//span[contains(@class, "homeParticipant")]//text()')).strip().title()
                    away = ''.join(
                        game.xpath('.//span[contains(@class, "awayParticipant")]//text()')).strip().title()

                    # Compare HOME team of H2H fixture to base fixture.
                    kickoff = game.xpath('.//span[contains(@class, "date")]/text()')[0].strip()

                    kickoff = Timestamp(datetime.strptime(kickoff, "%d.%m.%y")).relative

                    try:
                        h, a = game.xpath('.//span[@class="h2h__result"]//text()')
                        # Directly set the private var to avoid the score setter methods.
                        e.description += f"{kickoff} {home} {h} - {a} {away}\n"
                    except ValueError:
                        string = game.xpath('.//span[@class="h2h__result"]//text()')
                        logger.error(f'ValueError trying to split string, {string}')
                        e.description += f"{kickoff} {home} {string} {away}\n"

        if not e.description:
            e.description = "Could not find Head to Head Data for this game"
        return await self.bot.reply(self.interaction, embed=e, view=self)

    async def lineups(self) -> str | None:
        """Get the formations used by both teams in the fixture as a link to an image"""
        e = await self.fixture.base_embed
        e.title = f"Lineups and Formations"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.fixture.link}#/match-summary/lineups", timeout=5000)
                await page.eval_on_selector_all(fs.ADS, "ads => ads.forEach(x => x.remove());")
                await self.handle_tabs(page, self.table)
                screenshots = []
                if await (formation := page.locator('.section', has=page.locator('.lf__fieldWrap'))).count():
                    screenshots.append(io.BytesIO(await formation.screenshot()))
                if await (lineup := page.locator('.lf__lineUp')).count():
                    screenshots.append(io.BytesIO(await lineup.screenshot()))
            finally:
                await page.close()

        if screenshots:
            data = await asyncio.to_thread(image_utils.stitch_vertical, screenshots)
            file = discord.File(fp=data, filename="lineups.png")
        else:
            e.description = "Lineups and Formations not found."
            file = None
        e.set_image(url="attachment://lineups.png")
        return await self.bot.reply(self.interaction, embed=e, view=self, file=file)

    async def stats(self, half: int = 0) -> Message:
        """Push Stats to View"""
        e = await self.fixture.base_embed

        match half:
            case 0:
                e.title = "Stats"
            case 1:
                e.title = "First Half Stats"
            case 2:
                e.title = "Second Half Stats"
            case _:
                logger.error(f'Unhandled Half found for fixture {self.fixture.url}')

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                uri = f"{self.fixture.link}#/match-summary/match-statistics/{half}"
                await page.goto(uri, timeout=5000)
                await page.wait_for_selector(".section", timeout=5000)
                src = await page.inner_html('.section')

                await self.handle_tabs(page, self.stats)

                for i in range(await (locator := page.locator('div.subTabs > a')).count()):
                    disabled = await locator.nth(i).get_attribute("aria-current") is not None
                    match (label := await locator.nth(i).text_content()):
                        case "Match":
                            self.add_item(view_utils.FuncButton(label, self.stats, [0], disabled=disabled, row=2))
                        case "1st Half":
                            self.add_item(view_utils.FuncButton(label, self.stats, [1], disabled=disabled, row=2))
                        case "2nd Half":
                            self.add_item(view_utils.FuncButton(label, self.stats, [2], disabled=disabled, row=2))
                        case _:
                            logger.info(f"stats: Unhandled locator {i} with label {label}")
            finally:
                await page.close()

        output = ""
        for row in html.fromstring(src).xpath('.//div[@class="stat__category"]'):
            try:
                h = row.xpath('.//div[@class="stat__homeValue"]/text()')[0]
                s = row.xpath('.//div[@class="stat__categoryName"]/text()')[0]
                a = row.xpath('.//div[@class="stat__awayValue"]/text()')[0]
                output += f"{h.rjust(3)} [{s.center(17)}] {a.ljust(3)}\n"
            except IndexError:
                continue

        if output:
            e.description = f"```ini\n{output}```"
        else:
            e.description = "Could not find stats for this game."
        return await self.bot.reply(self.interaction, embed=e, view=self)

    async def table(self, main_table: str = 'table', sub_table: str = 'overall') -> str | None:
        """Fetch an image of the league table appropriate to the fixture as a bytesIO object"""
        e = await self.fixture.base_embed
        e.title = f"{main_table.title()} ({sub_table.title()})"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.fixture.link}#/standings/{main_table}/{sub_table}", timeout=5000)

                # Chaining Locators is fucking aids. Thank you for coming to my ted talk.
                table_div = page.locator('div', has=page.locator('div', has=page.locator('.tableWrapper'))).last
                await table_div.wait_for(state="visible", timeout=5000)
                await self.handle_tabs(page, self.table)
                if count := (await (locator := page.locator('div.subTabs > a')).count()) > 5:
                    # We have more than 5 elements, we need to do a select instead
                    pass
                else:
                    for i in range(count):
                        d = await locator.nth(i).get_attribute("aria-current") is not None
                        label = await locator.nth(i).text_content()
                        match label:
                            case "Overall" | "Home" | "Away":
                                self.add_item(view_utils.FuncButton(label, self.table, [label], disabled=d, row=2))
                            case _:
                                self.add_item(view_utils.FuncButton(label, self.table, [label], disabled=d, row=2))
                                logger.info(f'Extra table type "{label}" found on fixture {self.fixture.link}')

                await page.eval_on_selector_all(fs.ADS, "ads => ads.forEach(x => x.remove());")
                image = await table_div.screenshot(type="png")
                file = discord.File(fp=io.BytesIO(image), filename="table.png")
                e.description = ""
            finally:
                await page.close()
        e.set_image(url="attachment://table.png")
        return await self.bot.reply(self.interaction, embed=e, view=self, file=file)

    async def video(self):
        """Highlights and other shit."""
        e = await self.fixture.base_embed
        e.title = f"Videos"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.fixture.link}#/video", timeout=5000)
                await self.handle_tabs(page, self.video)
            finally:
                await page.close()

    async def summary(self) -> str | None:
        """Fetch the summary of a Fixture as a link to an image"""
        await self.fixture.refresh()
        e = await self.fixture.base_embed

        e.description = "\n".join(str(i) for i in self.fixture.events)
        if self.fixture.referee:
            e.description += f"**Referee**: {self.fixture.referee}\n"
        if self.fixture.stadium:
            e.description += f"**Venue**: {self.fixture.stadium}\n"
        if self.fixture.attendance:
            e.description += f"**Attendance**: {self.fixture.attendance}\n"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                await page.goto(f"{self.fixture.link}#/match-summary/", timeout=5000)
                await self.handle_tabs(page, self.table)
            finally:
                await page.close()
        return await self.bot.reply(self.interaction, embed=e, view=self)

    # TODO:
    async def scorers(self) -> Message:
        """Push Scorers to View"""
        e = await self.fixture.base_embed
        e.title = "Fixture - Scorers coming soon."
        return await self.bot.reply(self.interaction, embed=e, view=self)

    # TODO:
    async def photos(self) -> Message:
        """Push Photos to view"""
        e = await self.fixture.base_embed
        e.title = "Fixture - Photos coming soon."
        return await self.bot.reply(self.interaction, embed=e, view=self)

    # TODO:
    async def news(self) -> Message:
        """Push News to view"""
        e = await self.fixture.base_embed
        e.title = "Fixture - Photos coming soon."
        return await self.bot.reply(self.interaction, embed=e, view=self)


# TODO

class LeagueTableSelect(Select):
    """Push a Specific League Table"""

    def __init__(self, leagues: list[fs.Competition]) -> None:
        self.objects = leagues
        super().__init__(placeholder="Select which league to get table from…")
        for num, league in enumerate(leagues):
            self.add_option(label=league.title, emoji='🏆', description=league.link, value=str(num))

    async def callback(self, interaction: Interaction) -> Message:
        """Upon Item Selection do this"""
        await interaction.response.defer()
        try:
            return await self.view.push_table(self.objects[int(next(self.values))])
        except StopIteration:
            return await self.view.update()


# TODO
class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(fs)
        reload(view_utils)
        reload(image_utils)

        CompetitionView.bot = bot
        FixtureView.bot = bot
        TeamView.bot = bot

    # Group Commands for those with multiple available subcommands.
    default = Group(name="default", description="Set the server's default team and competition for commands.",
                    default_permissions=Permissions(manage_guild=True), guild_only=True)

    fixture = Group(name="fixture", description="Get information about a fixture from flashscore")
    team = Group(name="team", description="Get information about a team from flashscore")
    league = Group(name="competition", description="Get information about a competition from flashscore")

    @default.command(name="team")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def default_team(self, interaction: Interaction, team: str) -> Message:
        """Set the default team for your flashscore lookups"""
        await interaction.response.defer(thinking=True)

        # Receive Autocomplete.
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance(fsr := await fs.search(interaction, team, mode="team"), Message):
                return fsr  # Not Found

        async with self.bot.db.acquire(timeout=60) as connection:
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
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance(fsr := await fs.search(interaction, competition, mode="comp"), Message):
                return fsr  # Not Found

        q = f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET default_league = $2  WHERE excluded.guild_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, interaction.guild.id, fsr.id)

        e = await fsr.base_embed
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default competition'
        return await self.bot.reply(interaction, embed=e)

    @team.command(name="fixtures")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def fx_team(self, interaction: Interaction, team: str) -> Message:
        """Fetch upcoming fixtures for a team."""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance((fsr := await fs.search(interaction, team, mode="team")), Message):
                return fsr
        return await TeamView(interaction, fsr).push_fixtures()

    @team.command(name="results")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def rx_team(self, interaction: Interaction, team: str) -> Message:
        """Get recent results for a Team"""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance((fsr := await fs.search(interaction, team, mode="team")), Message):
                return fsr
        return await TeamView(interaction, fsr).push_results()

    @team.command(name="scorers")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def scorers_team(self, interaction: Interaction, team: str) -> Message:
        """Get top scorers for a team in various competitions."""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance((fsr := await fs.search(interaction, team, mode="team")), Message):
                return fsr
        return await TeamView(interaction, fsr).push_scorers()

    @team.command(name="table")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def team_table(self, interaction: Interaction, team: str) -> Message:
        """Get the Table of one of a Team's competitions"""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance(fsr := await fs.search(interaction, team, mode="team"), Message | None):
                return fsr
        return await TeamView(interaction, fsr).select_table()

    @league.command(name="fixtures")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def fx_comp(self, interaction: Interaction, competition: str) -> Message:
        """Fetch upcoming fixtures for a competition."""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance((fsr := await fs.search(interaction, competition, mode="comp")), Message):
                return fsr
        return await CompetitionView(interaction, fsr).push_fixtures()

    @league.command(name="results")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def rx_comp(self, interaction: Interaction, competition: str) -> Message:
        """Get recent results for a competition"""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance((fsr := await fs.search(interaction, competition, mode="comp")), Message):
                return fsr
        return await CompetitionView(interaction, fsr).push_results()

    @league.command(name="scorers")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def scorers_comp(self, interaction: Interaction, competition: str) -> Message:
        """Get top scorers from a competition."""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance((fsr := await fs.search(interaction, competition, mode="comp")), Message):
                return fsr
        return await CompetitionView(interaction, fsr).push_scorers()

    # COMPETITION only
    @league.command()
    @describe(competition="Enter the name of a competition to search for")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    async def scores(self, interaction: Interaction, competition: str = None) -> Message:
        """Fetch current scores for a specified competition, or all live games."""
        await interaction.response.defer(thinking=True)

        if not self.bot.games:
            return await self.bot.error(interaction, "No live games found")

        if competition:
            if not (res := [i for i in self.bot.games if competition == i.competition.id]):
                if not (res := [i for i in self.bot.games if competition.lower() in i.competition.title.lower()]):
                    return await self.bot.error(interaction, f"No live games found for `{competition}`")
        else:
            res = self.bot.games

        comp = None
        header = f'Scores as of: {Timestamp().long}\n'
        e: Embed = Embed(color=Colour.og_blurple(), title="Current scores", description=header)

        embeds = []
        for x, y in [(i.competition.title, i.live_score_text) for i in res]:
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

        return await view_utils.Paginator(interaction, embeds).update()

    @team.command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def injuries(self, interaction: Interaction, team: str) -> Message:
        """Get a team's current injuries"""
        await interaction.response.defer(thinking=True)
        if not (fsr := self.bot.get_team(team)):
            if isinstance(fsr := await fs.search(interaction, team, mode="team"), Message | None):
                return fsr
        return await TeamView(interaction, fsr).push_injuries()

    # TEAM only
    @team.command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def news(self, interaction: Interaction, team: str) -> Message:
        """Get the latest news for a team"""
        await interaction.response.defer(thinking=True)
        if not (fsr := self.bot.get_team(team)):
            if isinstance((fsr := await fs.search(interaction, team, mode="team")), Message | None):
                return fsr
        return await TeamView(interaction, fsr).push_news()

    @team.command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def squad(self, interaction: Interaction, team: str) -> Message:
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)
        if not (fsr := self.bot.get_team(team)):
            if isinstance(fsr := await fs.search(interaction, team, mode="team"), Message | None):
                return fsr
        return await TeamView(interaction, fsr).push_squad()

    @league.command(name="table")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def comp_table(self, interaction: Interaction, competition: str) -> Message:
        """Get the Table of a competition"""
        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance(fsr := await fs.search(interaction, competition, mode="comp"), Message | None):
                return fsr
        return await CompetitionView(interaction, fsr).push_table()

    # FIXTURE commands
    @fixture.command(name="table")
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def table_fx(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the table for a fixture."""
        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance((fix := await fs.search(interaction, fixture, mode="team", get_recent=True)), Message | None):
                return fix
        return await FixtureView(interaction, fix).table()

    @fixture.command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def stats(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance((fix := await fs.search(interaction, fixture, mode="team", get_recent=True)), Message | None):
                return fix
        return await FixtureView(interaction, fix).stats()

    @fixture.command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def lineups(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the lineups and/or formations for a Fixture."""
        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance((fix := await fs.search(interaction, fixture, mode="team", get_recent=True)), Message | None):
                return fix
        return await FixtureView(interaction, fix).lineups()

    @fixture.command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def summary(self, interaction: Interaction, fixture: str) -> Message:
        """Get a summary for a fixture"""
        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance((fix := await fs.search(interaction, fixture, mode="team", get_recent=True)), Message | None):
                return fix
        return await FixtureView(interaction, fix).summary()

    @fixture.command(name="h2h")
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def h2h(self, interaction: Interaction, fixture: str) -> Message:
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance((fix := await fs.search(interaction, fixture, mode="team", get_recent=True)), Message | None):
                return fix
        return await FixtureView(interaction, fix).h2h()

    # UNIQUE commands
    @command()
    @describe(stadium="Search for a stadium by it's name")
    async def stadium(self, interaction: Interaction, stadium: str) -> Message:
        """Lookup information about a team's stadiums"""
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(thinking=True)

        if not (stadiums := await get_stadiums(self.bot, stadium)):
            return await self.bot.error(interaction, f"🚫 No stadiums found matching `{stadium}`")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.name})") for i in stadiums]

        view = view_utils.ObjectSelectView(interaction, objects=markers, timeout=30)
        await view.update()
        await view.wait()
        if view.value is None:
            return await self.bot.error(interaction, content="Timed out waiting for you to reply", followup=False)
        embed = await stadiums[view.value].to_embed
        return await self.bot.reply(interaction, embed=embed)


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
