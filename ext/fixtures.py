"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime
from importlib import reload
from typing import TYPE_CHECKING, Literal, Callable, Any, Optional
import typing
from urllib.parse import quote_plus

# D.py
import discord
from discord import Embed, Colour, Guild, Interaction, Message, Permissions
from discord.app_commands import Choice, command, describe, autocomplete, Group
from discord.ext.commands import Cog
from discord.ui import Select

# Custom Utils
from lxml import html
from playwright.async_api import Page

import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils.flashscore_search import fs_search
from ext.toonbot_utils.stadiums import Stadium
from ext.utils import view_utils, embed_utils, image_utils
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot

logger = logging.getLogger("Fixtures")
semaphore = asyncio.Semaphore(5)

JS = "ads => ads.forEach(x => x.remove());"


async def set_default(
    interaction: Interaction[Bot],
    param: Literal["default_league", "default_team"],
):
    """Fetch the default team or default league for this server"""

    q = f"""SELECT {param} FROM fixtures_defaults WHERE (guild_id) = $1"""

    if interaction.guild is None:
        interaction.extras["default"] = None
        return

    async with interaction.client.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            r = await connection.fetchrow(q, interaction.guild.id)

    if r is None or r["param"] is None:
        interaction.extras["default"] = None
        return

    if param == "default_team":
        default = interaction.client.get_team(r[param])
    else:
        default = interaction.client.get_competition(r[param])

    if default is None:
        interaction.extras["default"] = None
        return

    assert default.id is not None

    name = rf"\⭐Server default: {default.name}"[:100]
    default = Choice(name=name, value=default.id)
    interaction.extras["default"] = default
    return


# Autocompletes
async def team_ac(interaction: Interaction[Bot], current: str) -> list[Choice]:
    """Autocomplete from list of stored teams"""
    bot: Bot = interaction.client
    teams: list[fs.Team] = sorted(bot.teams, key=lambda x: x.name)

    # Run Once - Set Default for interaction.
    if "default" not in interaction.extras:
        await set_default(interaction, "default_team")
    opts = []
    curr = current.lower()
    for t in teams:
        if curr in t.name.lower() and t.id is not None:
            opts.append(Choice(name=t.name[:100], value=t.id))
    if interaction.extras["default"] is not None:
        opts = [interaction.extras["default"]] + opts
    print(f"Found {opts}")
    return opts[:25]


async def comp_ac(
    interaction: Interaction[Bot], current: str
) -> list[Choice[str]]:
    """Autocomplete from list of stored competitions"""
    bot: Bot = interaction.client
    lgs: list[fs.Competition] = sorted(bot.competitions, key=lambda x: x.title)

    if "default" not in interaction.extras:
        await set_default(interaction, "default_team")

    opts = []
    curr = current.lower()
    for lg in lgs:
        if curr in lg.title.lower() and lg.id is not None:
            opts.append(Choice(name=lg.title[:100], value=lg.id))

    if interaction.extras["default"] is not None:
        opts = [interaction.extras["default"]] + opts
    return list(opts[:25])


async def fx_ac(
    interaction: Interaction[Bot], current: str
) -> list[Choice[str]]:
    """Check if user's typing is in list of live games"""
    cur = current.lower()
    games = interaction.client.games
    games = [i for i in games if cur in i.autocomplete.lower()]
    games = [i for i in games if i.fs_id is not None]

    choices = []
    for i in games:
        if i.fs_id is not None:
            choices.append(Choice(name=i.autocomplete[:100], value=i.fs_id))

    if current:
        v = f"🔎 Search for '{current}'"
        choices = choices[:24] + [Choice(name=v, value=current)]
    return choices


class CompetitionView(view_utils.BaseView):
    """The view sent to a user about a Competition"""

    # TODO: Team dropdown
    def __init__(
        self,
        interaction: Interaction[Bot],
        competition: fs.Competition,
        parent: Optional[view_utils.BaseView] = None,
    ) -> None:
        super().__init__(interaction)
        self.competition: fs.Competition = competition

        # Embed and internal index.
        self.pages: list[Embed] = []
        self.index: int = 0
        self.parent: Optional[view_utils.BaseView] = parent

        # Player Filtering
        self._nationality_filter: list[str] = []
        self._team_filter: list[str] = []

    async def update(self, content: Optional[str] = None) -> Message:
        """Send the latest version of the CompetitionView to the user"""
        self.clear_items()

        # TODO: Funcable.

        buttons = [
            view_utils.Funcable("Table", self.push_table, emoji="🥇"),
            view_utils.Funcable("Scorers", self.push_scorers, emoji="⚽"),
            view_utils.Funcable("Fixtures", self.push_fixtures, emoji="📆")
            ),
            view_utils.FuncButton(
                "Results", self.push_results, emoji="⚽", row=4
            ),
        ]:
            self.add_item(button)

        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = next(iter(self.pages), None)

        i = self.interaction
        return await self.bot.reply(i, content, view=self, embed=embed)

    async def push_table(self) -> Message:
        """Push Team's Table for a Competition to View"""
        embed = await self.competition.base_embed()
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition}"
        if img := await self.competition.get_table():
            embed.set_image(url=img)
            embed.description = Timestamp().long
        else:
            embed.description = "No Table Found"

        self.index = 0
        self.pages = [embed]
        return await self.update()

    async def push_scorers(self) -> Message:
        """PUsh the Scorers Embed to Competition View"""
        self.index = 0
        return await self.update()

    async def push_assists(self) -> Message:
        """PUsh the Scorers Embed to View"""
        self.index = 0
        return await self.update()

    async def push_fixtures(self) -> Message:
        """Push upcoming competition fixtures to View"""
        rows = await self.competition.fixtures()
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.competition.base_embed()
        embed.title = f"≡ Fixtures for {self.competition}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        return await self.update()

    async def push_results(self) -> Message:
        """Push results fixtures to View"""
        rows = await self.competition.results()
        rows = [i.upcoming for i in rows] if rows else ["No Results Found"]
        embed = await self.competition.base_embed()
        embed.title = f"≡ Results for {self.competition.title}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        return await self.update()


class TeamView(view_utils.BaseView):
    """The View sent to a user about a Team"""

    def __init__(
        self,
        interaction: Interaction[Bot],
        team: fs.Team,
        parent: Optional[view_utils.BaseView] = None,
    ) -> None:
        super().__init__(interaction)
        self.team: fs.Team = team
        self.parent: Optional[view_utils.BaseView] = parent

        # Specific Selection
        self.league_select: list[fs.Competition] = []

    async def update(self, content: Optional[str] = None) -> Message:
        """Push the latest version of the TeamView to the user"""
        self.clear_items()
        if self.league_select:
            self.add_item(LeagueTableSelect(leagues=self.league_select))
            self.league_select.clear()
        else:
            self.add_page_buttons(row=4)
            opts = [
                view_utils.Funcable("Squad", self.squad, emoji="🏃"),
                view_utils.Funcable(
                    "Injuries", self.injuries, emoji=fs.INJURY_EMOJI
                ),
                view_utils.Funcable("Top Scorers", self.scorers, emoji="⚽"),
                view_utils.Funcable("Table", self.table, emoji="🗓️"),
                view_utils.Funcable("Fixtures", self.fixtures, emoji="📆"),
                view_utils.Funcable("Results", self.results, emoji="🇼"),
                view_utils.Funcable("News", self.news, emoji="📰"),
            ]
            lbl = ", ".join(i.label for i in opts)
            view_utils.generate_function_row(self, opts, 1, lbl)
        embed = self.pages[self.index] or None
        return await self.bot.reply(
            self.interaction, content, view=self, embed=embed
        )

    async def news(self) -> Message:
        """Push News to View"""
        self.pages = await self.team.news()
        self.index = 0
        return await self.update()

    async def squad(self) -> Message:
        """Push the Squad Embed to the team View"""
        players = await self.team.players()
        srt = sorted(players, key=lambda x: x.squad_number or 99)
        p = [i.squad_row for i in srt]

        # Data must be fetched before embed url is updated.
        embed = await self.team.base_embed()
        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, p)
        return await self.update()

    async def injuries(self) -> Message:
        """Push the Injuries Embed to the team View"""
        embed = await self.team.base_embed()
        players = await self.team.players()

        if players:
            txt = [i.injury_row for i in players if i.injury is not None]
        else:
            txt = ["No injuries found"]

        embed.description = "\n".join(txt)
        self.index = 0
        self.pages = [embed]
        return await self.update()

    async def scorers(self) -> Message:
        """Push the Scorers Embed to the team View"""
        embed = await self.team.base_embed()
        players = await self.team.players()
        p = sorted(players, key=lambda x: x.goals or -1, reverse=True)
        rows = [i.scorer_row for i in p if i.goals]

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        return await self.update()

    async def table(self) -> Message:
        """Select Which Table to push from"""
        self.index = 0
        fixtures = await self.team.fixtures()

        unique = set(x.competition for x in fixtures if x.competition)
        if len(comps := [i for i in unique if i.name != "Club Friendly"]) == 1:
            return await self.push_table(comps[0])

        self.league_select = comps
        leagues = [f"• {x.flag} {x.markdown}" for x in comps]

        e = await self.team.base_embed()
        e.description = (
            "**Use the dropdown to select a table**:\n\n " + "\n".join(leagues)
        )
        self.pages = [e]
        return await self.update()

    async def push_table(self, res: fs.Competition) -> Message:
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.team.base_embed()
        embed.title = f"≡ Table for {res.title}"
        if img := await res.get_table():
            embed.set_image(url=img)
            embed.description = Timestamp().long
        else:
            embed.description = "No Table found."

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
                logger.info(
                    f"team push_results: [HOME: {i.home.url}] "
                    f"[AWAY: {i.away.url}] [TARGET: {self.team.url}]"
                )

            if None in [home, i.score_home, i.score_away]:
                emoji = ""
            else:
                if i.score_home is not None and i.score_away is not None:
                    if (
                        i.penalties_home is not None
                        and i.penalties_away is not None
                    ):
                        if i.penalties_home > i.penalties_away:
                            emoji = "🇼" if home else "🇱"
                        else:
                            emoji = "🇱" if home else "🇼"
                    else:
                        if i.score_home > i.score_away:
                            emoji = "🇼" if home else "🇱"
                        elif i.score_home < i.score_away:
                            emoji = "🇱" if home else "🇼"
                        else:
                            emoji = "🇩"
                else:
                    emoji = ""

            output.append(f"{emoji} {i.ko_relative}: {i.bold_markdown} ")

        if not output:
            output = ["No Results Found"]

        embed = await self.team.base_embed()
        embed.title = "Results"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, output)
        self._disabled = "Results"
        return await self.update()


class FixtureView(view_utils.BaseView):
    """The View sent to users about a fixture."""

    def __init__(
        self, interaction: Interaction[Bot], fixture: fs.Fixture
    ) -> None:
        self.fixture: fs.Fixture = fixture
        super().__init__(interaction)

    async def send(self, embed, file=None) -> Message:
        """Handle refreshing of file more gracefully."""
        i = self.interaction
        return await self.bot.reply(i, embed=embed, file=file, view=self)

    async def handle_tabs(self, page: Page, current_function: Callable) -> int:
        """Generate our buttons"""
        self.clear_items()

        if self.fixture.competition is not None:
            func = CompetitionView(
                self.interaction, self.fixture.competition, parent=self
            ).update
            self.add_item(
                view_utils.FuncButton(
                    self.fixture.competition.title, func, emoji="🏆"
                )
            )

        if self.fixture.home.id:
            func = TeamView(
                self.interaction, self.fixture.home, parent=self
            ).update
            self.add_item(
                view_utils.FuncButton(self.fixture.home.name, func, emoji="👕")
            )

        if self.fixture.away.id:
            func = TeamView(
                self.interaction, self.fixture.away, parent=self
            ).update
            self.add_item(
                view_utils.FuncButton(self.fixture.away.name, func, emoji="👕")
            )

        # key: [Item, Item, Item, ...]
        rows: dict[int, list[view_utils.Funcable]] = dict()
        sl = f"{self.fixture.home.name} v {self.fixture.away.name}"

        row = 1
        # Main Tabs
        tag = "div.tabs__group"
        for i in range(await (loc := page.locator(tag)).count()):
            rows[row] = []
            for o in range(await (sub_loc := loc.nth(i).locator("a")).count()):
                text = await sub_loc.nth(o).text_content()

                if not text:
                    continue

                f = view_utils.Funcable(text, current_function)

                active = "aria-current"
                b = await sub_loc.nth(o).get_attribute(active) is not None
                f.disabled = b

                match text:
                    case "Match":
                        f.function = self.summary
                    case "Standings":
                        f.function = self.table
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
                    case "Lineups":
                        f.function = self.lineups
                    case "Stats":
                        f.function = self.stats
                    case "Over/Under":
                        f.function = self.table
                        f.args = ["over_under"]
                    case "HT/FT":
                        f.function = self.table
                        f.args = ["ht_ft"]
                    case "Form":
                        f.function = self.table
                        f.args = ["form"]
                    case "News":
                        f.function = self.news
                        f.emoji = "📰"
                        f.description = f"News for {sl}"
                    case "Photos":
                        f.function = self.photos
                        f.emoji = "📷"
                        f.style = discord.ButtonStyle.red
                        f.description = f"Photos from {sl}"
                    case "Video":
                        f.function = self.video
                        f.emoji = "📹"
                        f.description = "Videos and Highlights"
                    case "Odds":
                        # TODO: Figure out if we want to encourage Gambling
                        continue
                    case "Top Scorers":
                        f.function = self.scorers
                        f.emoji = "⚽"
                        f.style = discord.ButtonStyle.red
                    case _:
                        inf = f"Handle_tabs found extra tab named {text}"
                        logger.info(inf)
                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            ph = f"{', '.join([i.label for i in v])}"
            view_utils.generate_function_row(self, v, k, ph)
        return row

    async def h2h(
        self, team: Literal["overall", "home", "away"] = "overall"
    ) -> Message:
        """Get results of recent games for each team in the fixture"""
        e: Embed = await self.fixture.base_embed()
        e.description = e.description or ""

        match team:
            case None | "overall":
                e.title = "Head to Head: Overall"
            case "home":
                e.title = f"Head to Head: {self.fixture.home.name} at Home"
            case "away":
                e.title = f"Head to Head: {self.fixture.away.name} Away"

        async with semaphore:
            page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}/#/h2h/{team}"
                await page.goto(e.url, timeout=5000)
                await page.wait_for_selector(".h2h", timeout=5000)
                row = await self.handle_tabs(page, self.h2h)
                rows = {}

                locator = page.locator(".subTabs")

                for i in range(await locator.count()):
                    rows[row] = []

                    sub_loc = locator.nth(i).locator("a")

                    for o in range(await sub_loc.count()):

                        text = await sub_loc.nth(o).text_content()
                        if not text:
                            continue

                        a = "aria-current"
                        b = await sub_loc.nth(o).get_attribute(a) is not None
                        f = view_utils.Funcable(text, self.h2h, disabled=b)
                        f.disabled = b
                        match o:
                            case 0:
                                f.args = ["overall"]
                            case 1:
                                f.args = ["home"]
                            case 2:
                                f.args = ["away"]
                            case _:
                                logger.info(
                                    "Extra Buttons Found: H2H %s", text
                                )
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    ph = f"{', '.join([i.label for i in v])}"
                    view_utils.generate_function_row(self, v, k, ph)
                tree = html.fromstring(await page.inner_html(".h2h"))
            finally:
                await page.close()

        game: html.HtmlElement
        xp = './/div[@class="rows" or @class="section__title"]'
        for row in tree.xpath(xp):
            if "section__title" in row.classes:
                header = row.xpath(".//text()")[0]
                e.description += f"\n**{header}**\n"
                continue

            for game in row:
                xp = './/span[contains(@class, "homeParticipant")]//text()'
                home = "".join(game.xpath(xp)).strip().title()

                xp = './/span[contains(@class, "awayParticipant")]//text()'
                away = "".join(game.xpath(xp)).strip().title()

                # Compare HOME team of H2H fixture to base fixture.
                xp = './/span[contains(@class, "date")]/text()'
                ko = game.xpath(xp)[0].strip()
                ko = datetime.strptime(ko, "%d.%m.%y")
                ko = Timestamp(ko).relative

                try:
                    h, a = game.xpath('.//span[@class="h2h__result"]//text()')
                    # Directly set the private var to avoid the score setter.
                    e.description += f"{ko} {home} {h} - {a} {away}\n"
                except ValueError:
                    strng = game.xpath('.//span[@class="h2h__result"]//text()')
                    logger.error(f"ValueError trying to split string, {strng}")
                    e.description += f"{ko} {home} {strng} {away}\n"

        if not e.description:
            e.description = "Could not find Head to Head Data for this game"
        return await self.send(e)

    async def lineups(self) -> Message:
        """Push Lineups & Formations Image to view"""
        e = await self.fixture.base_embed()
        e.title = "Lineups and Formations"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}#/match-summary/lineups"
                await page.goto(e.url, timeout=5000)
                await page.eval_on_selector_all(fs.ADS, JS)
                await self.handle_tabs(page, self.table)
                screenshots = []

                if await (fm := page.locator(".lf__fieldWrap")).count():
                    screenshots.append(io.BytesIO(await fm.screenshot()))

                if await (lineup := page.locator(".lf__lineUp")).count():
                    screenshots.append(io.BytesIO(await lineup.screenshot()))
            finally:
                await page.close()

        if screenshots:
            func = image_utils.stitch_vertical
            data = await asyncio.to_thread(func, screenshots)
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
            case 0:
                e.title = "Stats"
            case 1:
                e.title = "First Half Stats"
            case 2:
                e.title = "Second Half Stats"
            case _:
                logger.error(f"Fix Half found for fixture {self.fixture.url}")

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                lnk = self.fixture.url
                e.url = f"{lnk}#/match-summary/match-statistics/{half}"
                await page.goto(e.url, timeout=5000)
                await page.wait_for_selector(".section", timeout=5000)
                src = await page.inner_html(".section")

                row = await self.handle_tabs(page, self.stats)
                rows = {}

                loc = page.locator(".subTabs")
                for i in range(await (loc).count()):
                    rows[row] = []

                    sub = loc.nth(i).locator("a")
                    for o in range(await sub.count()):

                        text = await sub.nth(o).text_content()
                        if not text:
                            continue

                        f = view_utils.Funcable(text, self.stats)

                        a = "aria-current"
                        b = await sub.nth(o).get_attribute(a) is not None
                        f.disabled = b
                        match text:
                            case "Match":
                                f.args = [0]
                            case "1st Half":
                                f.args = [1]
                            case "2nd Half":
                                f.args = [2]
                            case _:
                                err = f"Found extra stats row {text}"
                                logger.error(err)
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    ph = f"{', '.join([i.label for i in v])}"
                    view_utils.generate_function_row(self, v, k, ph)
            finally:
                await page.close()

        output = ""
        xp = './/div[@class="stat__category"]'
        for row in html.fromstring(src).xpath(xp):
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

    async def table(
        self,
        main_table: str = "table",
        sub_table: str = "overall",
        sub_sub_table: Optional[str] = None,
    ) -> Message:
        """Send Specified Table to view"""
        e = await self.fixture.base_embed()

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}#/standings/{main_table}"
                e.title = f"{main_table.title().replace('_', '/')}"
                if sub_table is not None:
                    e.title += f" ({sub_table.title()}"
                    e.url += f"/{sub_table}"
                    if sub_sub_table:
                        e.title += f": {sub_sub_table}"
                        e.url += f"/{sub_sub_table}"
                    e.title += ")"
                await page.goto(e.url, timeout=5000)

                # Chaining Locators is fucking aids.
                # Thank you for coming to my ted talk.
                inner = page.locator(".tableWrapper")
                outer = page.locator("div", has=inner)
                table_div = page.locator("div", has=outer).last
                await table_div.wait_for(state="visible", timeout=5000)

                row = await self.handle_tabs(page, self.table)
                rows = {}

                loc = page.locator(".subTabs")
                for i in range(await loc.count()):
                    rows[row] = []

                    sub = loc.nth(i).locator("a")
                    for o in range(await sub.count()):

                        text = await sub.nth(o).text_content()

                        if not text:
                            continue

                        f = view_utils.Funcable(text, self.table)
                        a = "aria-current"
                        b = await sub.nth(o).get_attribute(a) is not None
                        f.disabled = b
                        match o:  # Buttons are always in the same order.
                            case 1:
                                args = [main_table, "home"]
                            case 2:
                                args = [main_table, "away"]
                            case _:
                                args = [main_table, "overall"]
                        if row == 4:
                            args += [text]
                        f.args = args
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    ph = f"{', '.join([i.label for i in v])}"
                    view_utils.generate_function_row(self, v, k, ph)

                await page.eval_on_selector_all(fs.ADS, JS)
                image = await table_div.screenshot(type="png")
                file = discord.File(fp=io.BytesIO(image), filename="table.png")
            finally:
                await page.close()
        e.set_image(url="attachment://table.png")
        return await self.send(e, file=file)

    async def video(self) -> Message:
        """Highlights and other shit."""
        # e = await self.fixture.base_embed()
        i = self.interaction
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                # e.url = f"{self.fixture.link}#/video"
                url = f"{self.fixture.url}#/video"
                await page.goto(url, timeout=5000)
                await self.handle_tabs(page, self.video)

                # e.title = "Videos"
                # loc = '.keyMoments'
                # video = (await page.locator(loc).inner_text()).title()
                video_url = await page.locator("object").get_attribute("data")
                # OLD: https://www.youtube.com/embed/GUH3NIIGbpo
                # NEW: https://www.youtube.com/watch?v=GUH3NIIGbpo
                if video_url is None:
                    return await self.bot.error(i, "Error fetching video.")
                video_url = video_url.replace("embed/", "watch?v=")
            finally:
                await page.close()
        # e.description = f"[{video}]({video_url})"
        return await self.bot.reply(i, video_url, view=self, embed=None)

    async def summary(self) -> Message:
        """Fetch the summary of a Fixture as a link to an image"""
        await self.fixture.refresh(self.bot)
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
                e.url = f"{self.fixture.url}#/match-summary/"
                await page.goto(e.url, timeout=5000)
                await self.handle_tabs(page, self.summary)
            finally:
                await page.close()
        return await self.send(e)

    async def news(self) -> Message:
        """Push News to view"""
        e = await self.fixture.base_embed()
        e.title = "News"
        e.description = ""
        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}#/news"
                await page.goto(e.url, timeout=5000)
                await self.handle_tabs(page, self.news)
                loc = "section.newsTab__section"
                tree = html.fromstring(await page.inner_html(loc))
            finally:
                await page.close()

        row: html.HtmlEntity
        for row in tree.xpath('.//a | .//div[@class="section__title"]'):
            logging.info("Iterating row")
            if "section__title" in row.classes:
                header = row.xpath(".//text()")[0]
                logger.info(f"Header Detected. {header}")
                e.description += f"\n**{header}**\n"
                continue
            link = fs.FLASHSCORE + row.xpath(".//@href")[0]
            title = row.xpath('.//div[@class="rssNews__title"]/text()')[0]

            xp = './/div[@class="rssNews__description"]/text()'
            description: str = row.xpath(xp)[0]
            time, source = description.split(",")

            fmt = "%d.%m.%Y %H:%M"
            time = Timestamp(datetime.strptime(time, fmt)).relative
            e.description += f"> [{title}]({link})\n{source} {time}\n\n"
        return await self.send(e)

    # TODO:
    async def scorers(self) -> Message:
        """Push Scorers to View"""
        e = await self.fixture.base_embed()
        e.title = "Fixture - Scorers coming soon."
        logger.info(f"Fixture {self.fixture.score_line} has Top Scorers tab")
        return await self.bot.reply(self.interaction, embed=e, view=self)

    # TODO:
    async def photos(self) -> Message:
        """Push Photos to view"""
        e = await self.fixture.base_embed()
        e.title = "Fixture - Photos coming soon."
        logger.info(f"Fixture {self.fixture.score_line} has Photos tab")
        return await self.bot.reply(self.interaction, embed=e, view=self)


# TODO
class LeagueTableSelect(Select):
    """Push a Specific League Table"""

    view: TeamView

    def __init__(self, leagues: list[fs.Competition]) -> None:
        self.objects = leagues
        super().__init__(placeholder="Select a league")
        for num, league in enumerate(leagues):
            desc = league.url
            label = league.title
            self.add_option(
                label=label, emoji="🏆", description=desc, value=str(num)
            )

    async def callback(self, interaction: Interaction) -> Message:
        """Upon Item Selection do this"""

        await interaction.response.defer()
        try:
            args = self.objects[int(self.values[0])]
            return await self.view.push_table(args)
        except IndexError:
            return await self.view.update()


class FixtureSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(
        self, interaction: Interaction[Bot], fixtures: list[fs.Fixture]
    ):
        super().__init__(interaction)

        # Pagination
        self.fixtures: list[fs.Fixture] = fixtures
        self.index: int = 0

        p = [fixtures[i : i + 25] for i in range(0, len(fixtures), 25)]
        self.pages: list[list[fs.Fixture]] = p

        # Final result
        self.value: Any = None  # As Yet Unset

    async def update(self) -> None:
        """Handle Pagination"""
        targets: list[fs.Fixture] = self.pages[self.index]
        d = view_utils.ItemSelect(placeholder="Please choose a Fixture")
        e = Embed(title="Choose a Fixture", description="")
        e.description = ""

        for f in targets:
            if f.competition:
                desc = f.competition.title
            else:
                desc = None

            if f.fs_id is not None:
                d.add_option(
                    label=f.score_line,
                    value=f.fs_id,
                    description=desc,
                )
            e.description += f"{f.bold_markdown}\n"

        self.add_item(d)
        view_utils.add_page_buttons(self, 1)
        await self.interaction.edit_original_response(embed=e, view=self)


class TeamSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, interaction: Interaction[Bot], teams: list[fs.Team]):
        super().__init__(interaction)

        self.teams: list[fs.Team] = teams

        # Pagination
        self.index: int = 0

        p = [self.teams[i : i + 25] for i in range(0, len(self.teams), 25)]
        self.pages: list[list[fs.Team]] = p

        # Final result
        self.value: Any = None

    async def update(self):
        """Handle Pagination"""
        targets: list[fs.Team] = self.pages[self.index]
        d = view_utils.ItemSelect(placeholder="Please choose a team")
        e = Embed(title="Choose a Team")
        e.description = ""

        em = fs.Team.emoji
        for team in targets:
            n = team.name
            dsc = team.url
            d.add_option(label=n, description=dsc, emoji=em, value=team.id)
            e.description += f"`{team.id}` {team.markdown}\n"
        self.add_item(d)
        view_utils.add_page_buttons(self, 1)
        await self.interaction.edit_original_response(embed=e, view=self)


class StadiumSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, interaction: Interaction[Bot], stadiums: list[Stadium]):
        super().__init__(interaction)

        self.stadiums: list[Stadium] = stadiums

        # Pagination
        self.index: int = 0

        s = [stadiums[i : i + 25] for i in range(0, len(stadiums), 25)]
        self.pages: list[list[Stadium]] = s

        # Final result
        self.value: Any = None

    async def update(self):
        """Handle Pagination"""
        targets: list[Stadium] = self.pages[self.index]

        d = view_utils.ItemSelect(placeholder="Please choose a Stadium")
        e = Embed(title="Choose a Stadium")
        e.description = ""

        for i in targets:
            desc = f"{i.team} ({i.country.upper()}: {i.name})"
            d.add_option(label=i.name, description=desc, value=i.url)
            e.description += f"[{desc}]({i.url})\n"
        self.add_item(d)
        view_utils.add_page_buttons(self, 1)
        await self.interaction.edit_original_response(embed=e, view=self)


async def choose_recent_fixture(
    interaction: Interaction[Bot], fsr: fs.Competition | fs.Team
):
    """Allow the user to choose from the most recent games of a fixture"""
    fixtures = await fsr.fixtures()
    await (v := FixtureSelect(interaction, fixtures)).update()
    await v.wait()
    return next(i for i in fixtures if i.score_line == v.value)


async def get_stadiums(
    interaction: Interaction[Bot], query: str
) -> list[Stadium]:
    """Fetch a list of Stadium objects matching a user query"""
    uri = f"https://www.footballgroundmap.com/search/{quote_plus(query)}"

    async with interaction.client.session.get(uri) as resp:
        tree = html.fromstring(await resp.text())

    stadiums: list[Stadium] = []

    xp = ".//div[@class='using-grid'][1]/div[@class='grid']/div"
    for i in tree.xpath(xp):

        xp = ".//small/preceding-sibling::a//text()"
        team = "".join(i.xpath(xp)).title()
        badge = i.xpath(".//img/@src")[0]

        if not (comp_info := i.xpath(".//small/a//text()")):
            continue

        country = comp_info.pop(0)
        league = comp_info[0] if comp_info else None

        for s in i.xpath(".//small/following-sibling::a"):
            name = "".join(s.xpath(".//text()")).title()
            if query.lower() not in name.lower() + team.lower():
                continue  # Filtering.

            stadium = Stadium()
            stadium.name = name
            stadium.url = "".join(s.xpath("./@href"))
            stadium.team = team
            stadium.team_badge = badge
            stadium.country = country
            stadium.league = league

            stadiums.append(stadium)
    return stadiums


class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(fs)
        reload(view_utils)
        reload(image_utils)

    # Group Commands for those with multiple available subcommands.
    default = Group(
        name="default",
        guild_only=True,
        description="Set the server's default team and competition.",
        default_permissions=Permissions(manage_guild=True),
    )

    @default.command(name="team")
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def default_team(self, ctx: Interaction[Bot], team: str) -> Message:
        """Set the default team for your flashscore lookups"""
        await ctx.response.defer(thinking=True)

        g = typing.cast(Guild, ctx.guild)

        fsr = await self.fetch_team(ctx, team)

        e = await fsr.base_embed()
        e.description = f"Commands will use {fsr.markdown} as default team"

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id)
                         VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, g.id)

                q = """INSERT INTO fixtures_defaults (guild_id, default_team)
                       VALUES ($1,$2) ON CONFLICT (guild_id)
                       DO UPDATE SET default_team = $2
                       WHERE excluded.guild_id = $1"""
                await connection.execute(q, g.id, fsr.id)
        return await self.bot.reply(ctx, embed=e)

    @default.command(name="competition")
    @autocomplete(competition=comp_ac)
    @describe(competition="Enter the name of a competition to search for")
    async def default_comp(
        self, interaction: Interaction[Bot], competition: str
    ) -> Message:
        """Set the default competition for your flashscore lookups"""

        await interaction.response.defer(thinking=True)

        g = typing.cast(Guild, interaction.guild)

        fsr = await self.fetch_competition(interaction, competition)

        q = """INSERT INTO fixtures_defaults (guild_id, default_league)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET default_league = $2
                WHERE excluded.guild_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, g.id, fsr.id)

        e = await fsr.base_embed()
        e.description = (
            f"Commands will use {fsr.markdown} as default competition"
        )

        return await self.bot.reply(interaction, embed=e)

    fixture = Group(
        name="fixture",
        description="Get information about a fixture from flashscore",
    )

    # FIXTURE commands
    @fixture.command(name="table")
    @autocomplete(fixture=fx_ac)
    @describe(fixture="Search for a fixture by team name")
    async def table_fx(
        self, interaction: Interaction[Bot], fixture: str
    ) -> Message:
        """Look up the table for a fixture."""
        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await self.fetch_team(interaction, fixture)
            fix = await choose_recent_fixture(interaction, team)
        return await FixtureView(interaction, fix).table()

    @fixture.command()
    @autocomplete(fixture=fx_ac)
    @describe(fixture="Search for a fixture by team name")
    async def stats(
        self, interaction: Interaction[Bot], fixture: str
    ) -> Message:
        """Look up the stats for a fixture."""
        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await self.fetch_team(interaction, fixture)
            fix = await choose_recent_fixture(interaction, team)
        return await FixtureView(interaction, fix).stats()

    @fixture.command()
    @autocomplete(fixture=fx_ac)
    @describe(fixture="Search for a fixture by team name")
    async def lineups(
        self, interaction: Interaction[Bot], fixture: str
    ) -> Message:
        """Look up the lineups and/or formations for a Fixture."""
        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await self.fetch_team(interaction, fixture)
            fix = await choose_recent_fixture(interaction, team)
        return await FixtureView(interaction, fix).lineups()

    @fixture.command()
    @autocomplete(fixture=fx_ac)
    @describe(fixture="Search for a fixture by team name")
    async def summary(
        self, interaction: Interaction[Bot], fixture: str
    ) -> Message:
        """Get a summary for a fixture"""
        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await self.fetch_team(interaction, fix)
            fix = await choose_recent_fixture(interaction, team)
        return await FixtureView(interaction, fix).summary()

    @fixture.command(name="h2h")
    @autocomplete(fixture=fx_ac)
    @describe(fixture="Search for a fixture by team name")
    async def h2h(self, ctx: Interaction[Bot], fixture: str) -> Message:
        """Lookup the head-to-head details for a Fixture"""
        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await self.fetch_team(ctx, fix)
            fix = await choose_recent_fixture(ctx, team)
        return await FixtureView(ctx, fix).h2h()

    league = Group(
        name="competition",
        description="Get information about a competition from flashscore",
    )

    async def fetch_competition(
        self, inter: Interaction[Bot], comp: str
    ) -> fs.Competition:
        await inter.response.defer(thinking=True)
        if fsr := self.bot.get_competition(comp):
            return fsr

        teams = await fs_search(inter, comp, mode="comp")
        teams = typing.cast(list[fs.Team], teams)

        await (v := TeamSelect(inter, teams)).update()
        await v.wait()

        if not v.value:
            raise TimeoutError
        return next(i for i in teams if i.id == v.value[0])

    @league.command(name="fixtures")
    @autocomplete(competition=comp_ac)
    @describe(competition="Enter the name of a competition to search for")
    async def fx_comp(self, interaction: Interaction[Bot], competition: str):
        """Fetch upcoming fixtures for a competition."""
        await interaction.response.defer(thinking=True)
        fsr = await self.fetch_competition(interaction, competition)
        return await CompetitionView(interaction, fsr).push_fixtures()

    @league.command(name="results")
    @autocomplete(competition=comp_ac)
    @describe(competition="Enter the name of a competition to search for")
    async def rx_comp(self, interaction: Interaction[Bot], competition: str):
        """Get recent results for a competition"""
        await interaction.response.defer(thinking=True)
        fsr = await self.fetch_competition(interaction, competition)
        return await CompetitionView(interaction, fsr).push_results()

    @league.command(name="scorers")
    @autocomplete(competition=comp_ac)
    @describe(competition="Enter the name of a competition to search for")
    async def scorers_comp(
        self, interaction: Interaction[Bot], competition: str
    ):
        """Get top scorers from a competition."""
        await interaction.response.defer(thinking=True)
        fsr = await self.fetch_competition(interaction, competition)
        return await CompetitionView(interaction, fsr).push_scorers()

    @league.command()
    @describe(competition="Enter the name of a competition to search for")
    @autocomplete(competition=comp_ac)
    async def scores(
        self, interaction: Interaction[Bot], competition: Optional[str]
    ) -> Message:
        """Fetch current scores for a specified competition,
        or if no competition is provided, all live games."""

        await interaction.response.defer(thinking=True)

        if not self.bot.games:
            return await self.bot.error(interaction, "No live games found")

        if competition:
            if not (res := self.bot.get_competition(competition)):
                games = self.bot.games
                lwr = competition.lower()
                res = [i for i in games if lwr in i.competition.title.lower()]
                if not res:
                    err = f"No live games found for `{competition}`"
                    return await self.bot.error(interaction, err)
        else:
            res = self.bot.games

        comp = None
        header = f"Scores as of: {Timestamp().long}\n"
        base_embed = Embed(
            color=Colour.og_blurple(),
            title="Current scores",
            description=header,
        )
        e = base_embed.copy()
        e.description = ""
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
                embeds.append(e)
                e = base_embed.copy()
                e.description = f"\n**{x}**\n{y}\n"
        embeds.append(e)
        return await view_utils.Paginator(interaction, embeds).update()

    @league.command(name="table")
    @autocomplete(competition=comp_ac)
    @describe(competition="Enter the name of a competition to search for")
    async def comp_table(
        self, interaction: Interaction[Bot], competition: str
    ) -> Message:
        """Get the Table of a competition"""
        await interaction.response.defer(thinking=True)
        fsr = await self.fetch_competition(interaction, competition)
        return await CompetitionView(interaction, fsr).push_table()

    team = Group(name="team", description="Get information about a team ")

    async def fetch_team(self, inter: Interaction[Bot], team: str) -> fs.Team:
        await inter.response.defer(thinking=True)
        if fsr := self.bot.get_team(team):
            return fsr

        teams = await fs_search(inter, team, mode="team")
        teams = typing.cast(list[fs.Team], teams)

        await (v := TeamSelect(inter, teams)).update()
        await v.wait()

        if not v.value:
            raise TimeoutError
        return next(i for i in teams if i.id == v.value[0])

    @team.command(name="fixtures")
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def fx_team(
        self, interaction: Interaction[Bot], team: str
    ) -> Message:
        """Fetch upcoming fixtures for a team."""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).fixtures()

    @team.command(name="results")
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def rx_team(
        self, interaction: Interaction[Bot], team: str
    ) -> Message:
        """Get recent results for a Team"""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).results()

    @team.command(name="scorers")
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def sc_team(
        self, interaction: Interaction[Bot], team: str
    ) -> Message:
        """Get top scorers for a team in various competitions."""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).scorers()

    @team.command(name="table")
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def team_table(
        self, interaction: Interaction[Bot], team: str
    ) -> Message:
        """Get the Table of one of a Team's competitions"""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).scorers()

    @team.command()
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def injuries(
        self, interaction: Interaction[Bot], team: str
    ) -> Message:
        """Get a team's current injuries"""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).injuries()

    @team.command()
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def news(self, interaction: Interaction[Bot], team: str) -> Message:
        """Get the latest news for a team"""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).news()

    @team.command()
    @autocomplete(team=team_ac)
    @describe(team="Enter the name of a team to search for")
    async def squad(self, interaction: Interaction[Bot], team: str) -> Message:
        """Lookup a team's squad members"""
        fsr = await self.fetch_team(interaction, team)
        return await TeamView(interaction, fsr).squad()

    # UNIQUE commands
    @command()
    @describe(stadium="Search for a stadium by it's name")
    async def stadium(self, ctx: Interaction[Bot], stadium: str) -> Message:
        """Lookup information about a team's stadiums"""

        await ctx.response.defer(thinking=True)

        if not (std := await get_stadiums(ctx, stadium)):
            err = f"No stadiums found matching `{stadium}`"
            return await self.bot.error(ctx, err)

        await (view := StadiumSelect(ctx, std)).update()
        await view.wait()
        if view.value is None:
            err = "Timed out waiting for you to reply"
            return await self.bot.error(ctx, err, followup=False)
        target = next(i for i in std if i.url == view.value[0])
        return await self.bot.reply(ctx, embed=await target.to_embed())


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
