"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from __future__ import annotations

import asyncio
import io
import logging
from copy import deepcopy
from datetime import datetime
from importlib import reload
from typing import TYPE_CHECKING, Literal, Callable, Any

# D.py
import discord
from discord import Embed, Colour, Interaction, Message, Permissions
from discord.app_commands import Choice, command, describe, autocomplete, Group
from discord.ext.commands import Cog
from discord.ui import Select

# Custom Utils
from lxml import html
from playwright.async_api import Page

import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils import stadiums
from ext.toonbot_utils.flashscore_search import fs_search
from ext.toonbot_utils.stadiums import get_stadiums
from ext.utils import view_utils, embed_utils, image_utils
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot

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
    # TODO: Team dropdown
    def __init__(self, interaction: Interaction, competition: fs.Competition, parent: discord.ui.View = None) -> None:
        super().__init__(interaction)
        self.competition: fs.Competition = competition

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

    async def update(self, content: str = None) -> Message:
        """Send the latest version of the CompetitionView to the user"""
        self.clear_items()

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
        embed = await self.competition.base_embed()
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
        embed = await self.competition.base_embed()
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
        embed = await self.competition.base_embed()
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
        embed = await self.competition.base_embed()
        embed.title = f"≡ Results for {self.competition.title}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Results"
        self._filter_mode = None
        return await self.update()


class TeamView(view_utils.BaseView):
    """The View sent to a user about a Team"""
    def __init__(self, interaction: Interaction, team: fs.Team, parent: view_utils.BaseView = None):
        super().__init__(interaction)
        self.team: fs.Team = team
        self.parent: view_utils.BaseView = parent

        # Pagination
        self.pages = []
        self.index = 0

        # Specific Selection
        self.league_select: list[fs.Competition] = []

        # Disable buttons when changing pages.
        # Page buttons have their own callbacks so cannot be directly passed to update
        self._disabled: str = None

    async def update(self, content: str = None) -> Message:
        """Push the latest version of the TeamView to the user"""
        self.clear_items()
        if self.league_select:
            self.add_item(LeagueTableSelect(leagues=self.league_select))
            self.league_select.clear()
        else:
            view_utils.add_page_buttons(self, row=4)
            opts = [view_utils.Funcable("Squad", self.squad, emoji='🏃'),
                    view_utils.Funcable("Injuries", self.injuries, emoji=fs.INJURY_EMOJI),
                    view_utils.Funcable("Top Scorers", self.scorers, emoji='⚽'),
                    view_utils.Funcable("Table", self.table, emoji='🗓️'),
                    view_utils.Funcable("Fixtures", self.fixtures, emoji='📆'),
                    view_utils.Funcable("Results", self.results, emoji='🇼'),
                    view_utils.Funcable("News", self.news, emoji='📰'),
                    ]
            view_utils.generate_function_row(opts, ', '.join(i.label for i in opts))
        embed = self.pages[self.index] if self.pages else None
        return await self.bot.reply(self.interaction, content=content, view=self, embed=embed)

    async def news(self) -> Message:
        """Push News to View"""
        self.pages = await self.team.news()
        self.index = 0
        self._disabled = "News"
        return await self.update()

    async def squad(self) -> Message:
        """Push the Squad Embed to the team View"""
        players = await self.team.players()
        p = [i.squad_row for i in sorted(players, key=lambda x: x.number)]

        # Data must be fetched before embed url is updated.
        embed = await self.team.base_embed()
        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, p)
        self._disabled = "Squad"
        return await self.update()

    async def injuries(self) -> Message:
        """Push the Injuries Embed to the team View"""
        embed = await self.team.base_embed()
        players = await self.team.players()
        players = [i.injury_row for i in players if i.injury is not None] if players else ['No injuries found']
        embed.description = "\n".join(players)
        self.index = 0
        self.pages = [embed]
        self._disabled = "Injuries"
        return await self.update()

    async def scorers(self) -> Message:
        """Push the Scorers Embed to the team View"""
        embed = await self.team.base_embed()
        players = await self.team.players()

        p = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
        rows = [i.scorer_row for i in p]

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Scorers"
        return await self.update()

    async def table(self) -> Message:
        """Select Which Table to push from"""
        self.index = 0
        fixtures = await self.team.fixtures()

        if len(comps := [i for i in set(x.competition for x in fixtures) if i.name != "Club Friendly"]) == 1:
            return await self.push_table(next(comps))

        self.league_select = comps
        leagues = [f"• {x.flag} {x.markdown}" for x in comps]

        e = await self.team.base_embed()
        e.description = "**Use the dropdown to select a table**:\n\n " + "\n".join(leagues)
        self.pages = [e]
        return await self.update()

    async def push_table(self, res: fs.Competition) -> Message:
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.team.base_embed()
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

    async def fixtures(self) -> Message:
        """Push upcoming fixtures to Team View"""
        rows = await self.team.fixtures()
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.team.base_embed()
        embed.title = f"≡ Fixtures for {self.team.name}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._disabled = "Fixtures"
        return await self.update()

    async def results(self) -> Message:  # Team
        """Push results to TeamView"""
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

        embed = await self.team.base_embed()
        embed.title = f"≡ Results for {self.team.name}" if embed.title else "≡ Results "

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, output)
        self._disabled = "Results"
        return await self.update()


class FixtureView(view_utils.BaseView):
    """The View sent to users about a fixture."""
    def __init__(self, interaction: Interaction, fixture: fs.Fixture) -> None:
        self.fixture: fs.Fixture = fixture
        super().__init__(interaction)

    async def send(self, embed, file=None):
        """Handle refreshing of file more gracefully."""
        return await self.bot.reply(self.interaction, embed=embed, file=file, view=self)

    async def handle_tabs(self, page: Page, current_function: Callable) -> int:
        """Generate our buttons"""
        self.clear_items()

        if self.fixture.competition.id:
            func = CompetitionView(self.interaction, self.fixture.competition, parent=self).update
            self.add_item(view_utils.FuncButton(self.fixture.competition.title, func, emoji="🏆"))

        if self.fixture.home.id:
            func = TeamView(self.interaction, self.fixture.home, parent=self).update
            self.add_item(view_utils.FuncButton(self.fixture.home.name, func, emoji="👕"))

        if self.fixture.away.id:
            func = TeamView(self.interaction, self.fixture.away, parent=self).update
            self.add_item(view_utils.FuncButton(self.fixture.away.name, func, emoji="👕"))

        rows: dict[int, list[view_utils.Funcable]] = dict()  # key: [Item, Item, Item, ...]
        sl = f"{self.fixture.home.name} v {self.fixture.away.name}"

        row = 1
        # Main Tabs
        for i in range(await (locator := page.locator('div.tabs__group')).count()):
            rows[row] = []
            for o in range(await (sub_loc := locator.nth(i).locator('a')).count()):
                f = view_utils.Funcable(text := await sub_loc.nth(o).text_content(), current_function)
                f.disabled = await sub_loc.nth(o).get_attribute("aria-current") is not None

                match text:
                    case "Match": f.function = self.summary
                    case "Standings": f.function = self.table
                    case "Live Standings":
                        f.function = self.table
                        f.args = ["live", None]
                    case "H2H":
                        f.function = self.h2h
                        f.description = "Head to Head Data"
                        f.emoji = "⚔"
                    case "Summary":
                        f.function = self.summary
                        f.description = "A list of match events"
                    case "Lineups": f.function = self.lineups
                    case "Stats": f.function = self.stats
                    case "Over/Under":
                        f.function = self.table
                        f.args = ['over_under']
                    case "HT/FT":
                        f.function = self.table
                        f.args = ['ht_ft']
                    case "Form":
                        f.function = self.table
                        f.args = ['form']
                    case "News":
                        f.function = self.news
                        f.emoji = "📰"
                        f.desc = f"News for {sl}"
                    case "Photos":
                        f.function = self.photos
                        f.emoji = "📷"
                        f.style = discord.ButtonStyle.red
                        f.desc = f"Photos from {sl}"
                    case "Video":
                        f.function = self.video
                        f.emoji = "📹"
                        f.desc = "Videos and Highlights"
                    case "Odds": continue  # TODO: Figure out if we want to encourage Gambling
                    case "Top Scorers":
                        f.function = self.scorers
                        f.emoji = '⚽'
                        f.style = discord.ButtonStyle.red
                    case _:
                        logger.info(f'Handle_tabs found extra tab named {text}')
                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            view_utils.generate_function_row(self, v, k, placeholder=f"{', '.join([i.label for i in v])}")
        return row

    async def h2h(self, team: Literal['overall', 'home', 'away'] = 'overall') -> dict[str, fs.Fixture]:
        """Get results of recent games related to the two teams in the fixture"""
        e: Embed = await self.fixture.base_embed()

        match team:
            case 'overall': e.title = "Head to Head: Overall"
            case 'home': e.title = f"Head to Head: {self.fixture.home.name} at Home"
            case 'away': e.title = f"Head to Head: {self.fixture.away.name} Away"

        async with semaphore:
            page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.link}/#/h2h/{team}"
                await page.goto(e.url, timeout=5000)
                await page.wait_for_selector(".h2h", timeout=5000)
                row = await self.handle_tabs(page, self.h2h)
                rows = {}
                for i in range(await (locator := page.locator('.subTabs')).count()):
                    rows[row] = []
                    for o in range(await (sub_loc := locator.nth(i).locator('a')).count()):
                        f = view_utils.Funcable(text := await sub_loc.nth(o).text_content(), self.h2h)
                        f.disabled = await sub_loc.nth(o).get_attribute("aria-current") is not None
                        match o:
                            case 0: f.args = ['overall']
                            case 1: f.args = ['home']
                            case 2: f.args = ['away']
                            case _: logging.info(f"Extra Buttons Found: fixtures.H2H -- {text}")
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    view_utils.generate_function_row(self, v, k, placeholder=f"{', '.join([i.label for i in v])}")
                tree: html.HtmlElement = html.fromstring(await page.inner_html('.h2h'))
            finally:
                await page.close()

        game: html.HtmlElement
        for row in tree.xpath('.//div[@class="rows" or @class="section__title"]'):
            if "section__title" in row.classes:
                header = row.xpath('.//text()')[0]
                e.description += f"\n**{header}**\n"
                continue

            for game in row:
                home = ''.join(game.xpath('.//span[contains(@class, "homeParticipant")]//text()')).strip().title()
                away = ''.join(game.xpath('.//span[contains(@class, "awayParticipant")]//text()')).strip().title()

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
        return await self.send(e)

    async def lineups(self) -> Message:
        """Get the formations used by both teams in the fixture as a link to an image"""
        e = await self.fixture.base_embed()
        e.title = f"Lineups and Formations"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.link}#/match-summary/lineups"
                await page.goto(e.url, timeout=5000)
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
            e.description = "Lineups and Formations unavailable."
            file = None
        e.set_image(url="attachment://lineups.png")
        return await self.send(e, file=file)

    async def stats(self, half: int = 0) -> Message:
        """Push Stats to View"""
        e = await self.fixture.base_embed()

        match half:
            case 0: e.title = "Stats"
            case 1: e.title = "First Half Stats"
            case 2: e.title = "Second Half Stats"
            case _:
                logger.error(f'Unhandled Half found for fixture {self.fixture.url}')

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.link}#/match-summary/match-statistics/{half}"
                await page.goto(e.url, timeout=5000)
                await page.wait_for_selector(".section", timeout=5000)
                src = await page.inner_html('.section')

                row = await self.handle_tabs(page, self.stats)
                rows = {}
                for i in range(await (locator := page.locator('.subTabs')).count()):
                    rows[row] = []
                    for o in range(await (sub_loc := locator.nth(i).locator('a')).count()):
                        f = view_utils.Funcable(text := await sub_loc.nth(o).text_content(), self.stats)
                        f.disabled = await sub_loc.nth(o).get_attribute("aria-current") is not None
                        match text:
                            case "Match": f.args = [0]
                            case "1st Half": f.args = [1]
                            case "2nd Half": f.args = [2]
                            case _: logger.error(f'Found extra stats row {text}')
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    view_utils.generate_function_row(self, v, k, placeholder=f"{', '.join([i.label for i in v])}")
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
        return await self.send(e)

    async def table(self, main_table: str = 'table', sub_table: str = 'overall', sub_sub_table: str = None) -> Message:
        """Send Specified Table to view"""
        e = await self.fixture.base_embed()

        e.title = f"{main_table.title().replace('_', '/')}"
        if sub_table is not None:
            e.title += f" ({sub_table.title()}{': ' + sub_sub_table if sub_sub_table else ''})"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.link}#/standings/{main_table}"
                if sub_table is not None:
                    e.url += f"/{sub_table}"
                    if sub_sub_table:
                        e.url += f"/{sub_sub_table}"
                await page.goto(e.url, timeout=5000)

                # Chaining Locators is fucking aids. Thank you for coming to my ted talk.
                table_div = page.locator('div', has=page.locator('div', has=page.locator('.tableWrapper'))).last
                await table_div.wait_for(state="visible", timeout=5000)

                row = await self.handle_tabs(page, self.table)

                # SubTabs --- Fuck it let's just handle these inside their own functions ...
                rows = {}
                for i in range(await (locator := page.locator('.subTabs')).count()):
                    rows[row] = []
                    for o in range(await (sub_loc := locator.nth(i).locator('a')).count()):
                        f = view_utils.Funcable(text := await sub_loc.nth(o).text_content(), self.table)
                        f.disabled = await sub_loc.nth(o).get_attribute("aria-current") is not None
                        match o:  # Buttons are always in the same order.
                            case 1: args = [main_table, 'home']
                            case 2: args = [main_table, 'away']
                            case _: args = [main_table, 'overall']
                        if row == 4:
                            args += [text]
                        f.args = args
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    view_utils.generate_function_row(self, v, k, placeholder=f"{', '.join([i.label for i in v])}")

                await page.eval_on_selector_all(fs.ADS, "ads => ads.forEach(x => x.remove());")
                image = await table_div.screenshot(type="png")
                file = discord.File(fp=io.BytesIO(image), filename="table.png")
            finally:
                await page.close()
        e.set_image(url="attachment://table.png")
        return await self.send(e, file=file)

    async def video(self) -> Message:
        """Highlights and other shit."""
        e = await self.fixture.base_embed()

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.link}#/video"
                await page.goto(e.url, timeout=5000)
                await self.handle_tabs(page, self.video)

                e.title = "Videos"
                video = (await page.locator('.keyMoments').inner_text()).title()
                video_url = await page.locator('object').get_attribute('data')
                # https://www.youtube.com/embed/GUH3NIIGbpo -> https://www.youtube.com/watch?v=GUH3NIIGbpo
                video_url = video_url.replace('embed/', 'watch?v=')
            finally:
                await page.close()
        e.description = f"[{video}]({video_url})"
        return await self.bot.reply(self.interaction, content=video_url, view=self, embed=None)

    async def summary(self) -> Message:
        """Fetch the summary of a Fixture as a link to an image"""
        await self.fixture.refresh()
        e = await self.fixture.base_embed()

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
                e.url = f"{self.fixture.link}#/match-summary/"
                await page.goto(e.url, timeout=5000)
                await self.handle_tabs(page, self.summary)
            finally:
                await page.close()
        return await self.send(e)

    async def news(self) -> Message:
        """Push News to view"""
        e = await self.fixture.base_embed()
        e.title = "News"
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.link}#/news"
                await page.goto(e.url, timeout=5000)
                await self.handle_tabs(page, self.news)
                tree = html.fromstring(await page.inner_html('section.newsTab__section'))
            finally:
                await page.close()

        row: html.HtmlEntity
        for row in tree.xpath('.//a | .//div[@class="section__title"]'):
            logging.info('Iterating row')
            if "section__title" in row.classes:
                header = row.xpath('.//text()')[0]
                logger.info(f'Header Detected. {header}')
                e.description += f"\n**{header}**\n"
                continue
            link = fs.FLASHSCORE + row.xpath('.//@href')[0]
            title = row.xpath('.//div[@class="rssNews__title"]/text()')[0]
            description: str = row.xpath('.//div[@class="rssNews__description"]/text()')[0]
            time, source = description.split(',')
            time = Timestamp(datetime.strptime(time, "%d.%m.%Y %H:%M")).relative
            e.description += f"> [{title}]({link})\n{source} {time}\n\n"
        return await self.send(e)

    # TODO:
    async def scorers(self) -> Message:
        """Push Scorers to View"""
        e = await self.fixture.base_embed()
        e.title = "Fixture - Scorers coming soon."
        logger.info(f'Fixture {self.fixture.score_line} has Top Scorers tab')
        return await self.bot.reply(self.interaction, embed=e, view=self)

    # TODO:
    async def photos(self) -> Message:
        """Push Photos to view"""
        e = await self.fixture.base_embed()
        e.title = "Fixture - Photos coming soon."
        logger.info(f'Fixture {self.fixture.score_line} has Photos tab')
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


class FixtureSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, interaction: Interaction, fixtures: list[fs.Fixture]):
        super().__init__(interaction)

        self.interaction: Interaction = interaction
        self.fixtures: list[fs.Fixture] = fixtures

        # Pagination
        self.index: int = 0
        self.pages: list[list[fs.Fixture]] = [self.fixtures[i:i + 25] for i in range(0, len(self.fixtures), 25)]

        # Final result
        self.value: Any = None  # As Yet Unset

    async def update(self):
        """Handle Pagination"""
        targets: list[fs.Fixture] = self.pages[self.index]
        d = view_utils.ItemSelect(placeholder="Please choose a Fixture")
        e = Embed(title='Choose a Fixture', description="")

        for fixture in targets:
            d.add_option(label=fixture.score_line, description=fixture.competition, value=fixture.score_line)
            e.description += f"{fixture.bold_markdown}\n"
        self.add_item(d)
        view_utils.add_page_buttons(self, 1)
        return await self.interaction.client.reply(embed=e, view=self)


class StadiumSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, interaction: Interaction, stadium_list: list[stadiums.Stadium]):
        super().__init__(interaction)

        self.interaction: Interaction = interaction
        self.stadiums: list[stadiums.Stadium] = stadium_list

        # Pagination
        self.index: int = 0
        self.pages: list[list[stadiums.Stadium]] = [self.stadiums[i:i + 25] for i in range(0, len(self.stadiums), 25)]

        # Final result
        self.value: Any = None  # As Yet Unset

    async def update(self):
        """Handle Pagination"""
        targets: list[stadiums.Stadium] = self.pages[self.index]

        d = view_utils.ItemSelect(placeholder="Please choose a Stadium")
        e = Embed(title='Choose a Stadium', description="")

        for i in targets:
            desc = f"{i.team} ({i.country.upper()}: {i.name})"
            d.add_option(label=i.name, description=desc, value=i.url)
            e.description += f"[{desc}]({i.url})\n"
        self.add_item(d)
        view_utils.add_page_buttons(self, 1)
        return await self.interaction.client.reply(embed=e, view=self)


async def choose_recent_fixture(interaction: Interaction, fsr: fs.Competition | fs.Team):
    """Allow the user to choose from the most recent games of a fixture"""
    await (v := FixtureSelect(interaction, (fixtures := await fsr.fixtures()))).update()
    await v.wait()

    return next(i for i in fixtures if i.score_line == v.value)


class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(fs)
        reload(view_utils)
        reload(image_utils)

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
            if isinstance(fsr := await fs_search(interaction, team, mode="team"), Message):
                return fsr  # Not Found

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, interaction.guild.id)

                q = """INSERT INTO fixtures_defaults (guild_id, default_team) VALUES ($1,$2)
                       ON CONFLICT (guild_id) DO UPDATE SET default_team = $2  WHERE excluded.guild_id = $1"""
                await connection.execute(q, interaction.guild.id, fsr.id)

        e = await fsr.base_embed()
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
            if isinstance(fsr := await fs_search(interaction, competition, mode="comp"), Message):
                return fsr  # Not Found

        q = f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET default_league = $2  WHERE excluded.guild_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, interaction.guild.id, fsr.id)

        e = await fsr.base_embed()
        e.description = f'Your Fixtures commands will now use {fsr.markdown} as a default competition'
        return await self.bot.reply(interaction, embed=e)

    @team.command(name="fixtures")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def fx_team(self, interaction: Interaction, team: str) -> Message:
        """Fetch upcoming fixtures for a team."""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance((fsr := await fs_search(interaction, team, mode="team")), Message):
                return fsr
        return await TeamView(interaction, fsr).fixtures()

    @team.command(name="results")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def rx_team(self, interaction: Interaction, team: str) -> Message:
        """Get recent results for a Team"""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance((fsr := await fs_search(interaction, team, mode="team")), Message):
                return fsr
        return await TeamView(interaction, fsr).results()

    @team.command(name="scorers")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def scorers_team(self, interaction: Interaction, team: str) -> Message:
        """Get top scorers for a team in various competitions."""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance((fsr := await fs_search(interaction, team, mode="team")), Message):
                return fsr
        return await TeamView(interaction, fsr).scorers()

    @team.command(name="table")
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def team_table(self, interaction: Interaction, team: str) -> Message:
        """Get the Table of one of a Team's competitions"""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_team(team)) is None:
            if isinstance(fsr := await fs_search(interaction, team, mode="team"), Message | None):
                return fsr
        return await TeamView(interaction, fsr).table()

    @league.command(name="fixtures")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def fx_comp(self, interaction: Interaction, competition: str) -> Message:
        """Fetch upcoming fixtures for a competition."""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance((fsr := await fs_search(interaction, competition, mode="comp")), Message):
                return fsr
        return await CompetitionView(interaction, fsr).push_fixtures()

    @league.command(name="results")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def rx_comp(self, interaction: Interaction, competition: str) -> Message:
        """Get recent results for a competition"""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance((fsr := await fs_search(interaction, competition, mode="comp")), Message):
                return fsr
        return await CompetitionView(interaction, fsr).push_results()

    @league.command(name="scorers")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def scorers_comp(self, interaction: Interaction, competition: str) -> Message:
        """Get top scorers from a competition."""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance((fsr := await fs_search(interaction, competition, mode="comp")), Message):
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
            if isinstance(fsr := await fs_search(interaction, team, mode="team"), Message | None):
                return fsr
        return await TeamView(interaction, fsr).injuries()

    # TEAM only
    @team.command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def news(self, interaction: Interaction, team: str) -> Message:
        """Get the latest news for a team"""

        await interaction.response.defer(thinking=True)
        if not (fsr := self.bot.get_team(team)):
            if isinstance((fsr := await fs_search(interaction, team, mode="team")), Message | None):
                return fsr
        return await TeamView(interaction, fsr).news()

    @team.command()
    @autocomplete(team=team_autocomplete_with_defaults)
    @describe(team="Enter the name of a team to search for")
    async def squad(self, interaction: Interaction, team: str) -> Message:
        """Lookup a team's squad members"""

        await interaction.response.defer(thinking=True)
        if not (fsr := self.bot.get_team(team)):
            if isinstance(fsr := await fs_search(interaction, team, mode="team"), Message | None):
                return fsr
        return await TeamView(interaction, fsr).squad()

    @league.command(name="table")
    @autocomplete(competition=competition_autocomplete_with_defaults)
    @describe(competition="Enter the name of a competition to search for")
    async def comp_table(self, interaction: Interaction, competition: str) -> Message:
        """Get the Table of a competition"""

        await interaction.response.defer(thinking=True)
        if (fsr := self.bot.get_competition(competition)) is None:
            if isinstance(fsr := await fs_search(interaction, competition, mode="comp"), Message | None):
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
            if isinstance(fsr := await fs_search(interaction, fixture, mode="team"), Message | None):
                return fsr
            fix = await choose_recent_fixture(interaction, fsr)
        return await FixtureView(interaction, fix).table()

    @fixture.command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def stats(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the stats for a fixture."""

        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance(fsr := await fs_search(interaction, fixture, mode="team"), Message | None):
                return fsr
            fix = await choose_recent_fixture(interaction, fsr)
        return await FixtureView(interaction, fix).stats()

    @fixture.command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def lineups(self, interaction: Interaction, fixture: str) -> Message:
        """Look up the lineups and/or formations for a Fixture."""

        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance(fsr := await fs_search(interaction, fixture, mode="team"), Message | None):
                return fsr
            fix = await choose_recent_fixture(interaction, fsr)
        return await FixtureView(interaction, fix).lineups()

    @fixture.command()
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def summary(self, interaction: Interaction, fixture: str) -> Message:
        """Get a summary for a fixture"""

        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance(fsr := await fs_search(interaction, fixture, mode="team"), Message | None):
                return fsr
            fix = await choose_recent_fixture(interaction, fsr)
        return await FixtureView(interaction, fix).summary()

    @fixture.command(name="h2h")
    @autocomplete(fixture=fixture_autocomplete)
    @describe(fixture="Search for a fixture by team name")
    async def h2h(self, interaction: Interaction, fixture: str) -> Message:
        """Lookup the head-to-head details for a Fixture"""

        await interaction.response.defer(thinking=True)
        if (fix := self.bot.get_fixture(fixture)) is None:
            if isinstance(fsr := await fs_search(interaction, fixture, mode="team"), Message | None):
                return fsr
            fix = await choose_recent_fixture(interaction, fsr)
        return await FixtureView(interaction, fix).h2h()

    # UNIQUE commands
    @command()
    @describe(stadium="Search for a stadium by it's name")
    async def stadium(self, interaction: Interaction, stadium: str) -> Message:
        """Lookup information about a team's stadiums"""

        await interaction.response.defer(thinking=True)

        if not (std := await get_stadiums(self.bot, stadium)):
            return await self.bot.error(interaction, f"No stadiums found matching `{stadium}`")

        view = StadiumSelect(interaction, std)

        await view.update()
        await view.wait()
        if view.value is None:
            return await self.bot.error(interaction, "Timed out waiting for you to reply", followup=False)
        target = next(i for i in std if i.url == view.value[0])
        return await self.bot.reply(interaction, embed=await target.to_embed())


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
