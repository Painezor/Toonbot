"""Lookups of Live Football Data for teams, fixtures, and competitions."""
# TODO: Nuke page.content in favour of locator.inner_html()
# TODO: Team dropdown on Competition
# TODO: FixtureView.photos
# TODO: FixtureView.report
# TODO: FixtureView.scorers
# TODO: TeamView.fixtures => Dropdowns for Fixture Select
# TODO: TeamView.results => Dropdowns for Fixture Select
# TODO: TeamView.transfers => Dropdowns for Teams & Competitions
# TODO: TeamView.squad => Sort by Squad Number
# TODO: TeamView.squda => Enumerate when not sorting by squad number.
# TODO: GLOBAL change all .lower() to .casefold() because fuck you germans.


from __future__ import annotations

import asyncio
import io
import logging
import datetime
from importlib import reload
from typing import TYPE_CHECKING, Literal, Callable, Any, Optional
import typing

# D.py
import discord
from discord import (
    Interaction,
    Message,
)
from discord.app_commands import Choice, Group
from discord.ext.commands import Cog

# Custom Utils
from lxml import html
from playwright.async_api import Page

import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils.flashscore_search import fs_search
from ext.utils import view_utils, embed_utils, image_utils, timed_events

if TYPE_CHECKING:
    from core import Bot

logger = logging.getLogger("Fixtures")
semaphore = asyncio.Semaphore(5)

JS = "ads => ads.forEach(x => x.remove());"
TEAM_NAME = "Enter the name of a team to search for"
FIXTURE = "Search for a fixture by team name"
COMPETITION = "Enter the name of a competition to search for"


async def set_default(
    interaction: discord.Interaction[Bot],
    param: Literal["default_league", "default_team"],
):
    """Fetch the default team or default league for this server"""
    logger.info("Accessing set_default")

    q = f"""SELECT {param} FROM fixtures_defaults WHERE (guild_id) = $1"""

    if interaction.guild is None:
        interaction.extras["default"] = None
        return

    logger.info("Guild is not None")
    async with interaction.client.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            r = await connection.fetchrow(q, interaction.guild.id)
    logger.info("Fetched %s from db", r.__dict__)

    if r is None or r["param"] is None:
        interaction.extras["default"] = None
        return

    logger.info("r was not None")

    if param == "default_team":
        default = interaction.client.get_team(r[param])
    else:
        default = interaction.client.get_competition(r[param])

    if default is None:
        logger.info("%s was None.", param)
        interaction.extras["default"] = None
        return

    logger.info("%s was %s", param, default)

    if (def_id := default.id) is None or (name := default.name) is None:
        return

    name = rf"\⭐Server default: {name}"[:100]
    default = discord.app_commands.Choice(name=name, value=def_id)
    interaction.extras["default"] = default
    logger.info("Succesfully set interaction default", param, default)
    return


# Autocompletes
async def team_ac(ctx: Interaction[Bot], current: str) -> list[Choice[str]]:
    """Autocomplete from list of stored teams"""
    teams: list[fs.Team] = sorted(ctx.client.teams, key=lambda x: x.name)

    # Run Once - Set Default for interaction.
    if "default" not in ctx.extras:
        await set_default(ctx, "default_team")

    curr = current.lower()

    opts = []
    for t in teams:
        if t.id is None:
            continue

        if curr not in t.name.lower():
            continue

        c = discord.app_commands.Choice(name=t.name[:100], value=t.id)
        opts.append(c)

    if ctx.extras["default"] is not None:
        opts = [ctx.extras["default"]] + opts

    return opts[:25]


async def comp_ac(ctx: Interaction[Bot], current: str) -> list[Choice[str]]:
    """Autocomplete from list of stored competitions"""
    lgs = sorted(ctx.client.competitions, key=lambda x: x.title)

    if "default" not in ctx.extras:
        await set_default(ctx, "default_team")

    curr = current.lower()

    opts = []

    for lg in lgs:
        if curr in lg.title.lower() and lg.id is not None:
            opts.append(Choice(name=lg.title[:100], value=lg.id))

    if ctx.extras["default"] is not None:
        opts = [ctx.extras["default"]] + opts
    return list(opts[:25])


async def fx_ac(ctx: Interaction[Bot], current: str) -> list[Choice[str]]:
    """Check if user's typing is in list of live games"""
    cur = current.lower()

    choices = []
    for i in ctx.client.games:
        if cur and cur not in i.ac_row.lower():
            continue

        if i.id is None:
            continue

        choices.append(Choice(name=i.ac_row[:100], value=i.id))

    if current:
        v = f"🔎 Search for '{current}'"
        choices = choices[:24] + [Choice(name=v, value=current)]
    return choices


# Searching
async def fetch_comp(inter: Interaction[Bot], comp: str) -> fs.Competition:
    if fsr := inter.client.get_competition(comp):
        return fsr

    comps = await fs_search(inter, comp, mode="comp")
    comps = typing.cast(list[fs.Competition], comps)

    await (v := CompetitionSelect(inter, comps)).update()
    await v.wait()

    if not v.value:
        raise TimeoutError
    return next(i for i in comps if i.id == v.value[0])


class CompetitionSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, ctx: Interaction[Bot], comps: list[fs.Competition]):
        super().__init__(ctx)

        self.comps: list[fs.Competition] = comps

        # Pagination
        p = [self.comps[i : i + 25] for i in range(0, len(self.comps), 25)]
        self.pages: list[list[fs.Competition]] = p

    async def update(self):
        """Handle Pagination"""
        targets: list[fs.Competition] = self.pages[self.index]

        em = fs.Competition.emoji
        e = discord.Embed(title="Choose a Competition")
        e.description = ""

        sel = view_utils.ItemSelect(placeholder="Please choose a competition")

        for comp in targets:
            if comp.id is None:
                continue

            n = comp.title
            dsc = comp.url
            sel.add_option(label=n, description=dsc, emoji=em, value=comp.id)
            e.description += f"`{comp.id}` {comp.markdown}\n"

        self.add_item(sel)
        self.add_page_buttons(1)
        await self.interaction.edit_original_response(embed=e, view=self)


async def fetch_team(inter: Interaction[Bot], team: str) -> fs.Team:
    if fsr := inter.client.get_team(team):
        return fsr

    teams = await fs_search(inter, team, mode="team")
    teams = typing.cast(list[fs.Team], teams)

    await (v := TeamSelect(inter, teams)).update()
    await v.wait()

    if not v.value:
        raise TimeoutError
    return next(i for i in teams if i.id == v.value[0])


class TeamSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, interaction: Interaction[Bot], teams: list[fs.Team]):
        super().__init__(interaction)

        self.teams: list[fs.Team] = teams
        p = [self.teams[i : i + 25] for i in range(0, len(self.teams), 25)]
        self.pages: list[list[fs.Team]] = p

    async def update(self):
        """Handle Pagination"""
        targets: list[fs.Team] = self.pages[self.index]
        d = view_utils.ItemSelect(placeholder="Please choose a team")
        e = discord.Embed(title="Choose a Team")
        e.description = ""

        em = fs.Team.emoji
        for team in targets:
            if team.id is None:
                continue

            n = team.name
            dsc = team.url
            d.add_option(label=n, description=dsc, emoji=em, value=team.id)
            e.description += f"`{team.id}` {team.markdown}\n"

        self.add_item(d)
        self.add_page_buttons(1)
        await self.interaction.edit_original_response(embed=e, view=self)


class ItemView(view_utils.BaseView):

    bot: Bot
    interaction: Interaction[Bot]

    def __init__(self, interaction: Interaction[Bot], **kwargs) -> None:
        super().__init__(interaction, **kwargs)

    async def update(self) -> discord.InteractionMessage:
        """Use this to paginate."""
        # Remove our bottom row.

        children = self.children.copy()

        self.clear_items()
        [self.add_item(x) for x in children if x.row != 4]
        self.add_page_buttons(4)

        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = self.pages[-1]

        r = self.interaction.edit_original_response
        return await r(content=None, embed=embed, attachments=[], view=self)


class TeamView(ItemView):
    """The View sent to a user about a Team"""

    def __init__(
        self, interaction: Interaction[Bot], team: fs.Team, **kwargs
    ) -> None:
        super().__init__(interaction, **kwargs)
        self.team: fs.Team = team

        self._cached_function: Optional[Callable] = None

    async def handle_tabs(self, page: Page, current_function: Callable) -> int:
        """Generate our buttons"""
        self.clear_items()

        row_0 = []
        if self.team.competition is not None:
            cmp = self.team.competition
            p = self.news
            func = CompetitionView(self.interaction, cmp, parent=p).update
            row_0.append(view_utils.Funcable(cmp.title, func, emoji="🏆"))

        # key: [Item, Item, Item, ...]
        rows: dict[int, list[view_utils.Funcable]] = dict()

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

                if row == 1:
                    f.style = discord.ButtonStyle.blurple

                active = "aria-current"
                b = await sub_loc.nth(o).get_attribute(active) is not None
                f.disabled = b

                match text:
                    case "Fixtures":
                        f.function = self.fixtures
                        f.description = "Upcoming Fixtures"
                    case "News":
                        f.function = self.news
                        f.emoji = "📰"
                        f.description = f"News for {self.team.name}"
                    case "Results":
                        f.function = self.results
                        f.description = "Recent Results"
                    case "Standings":
                        f.function = self.standings
                        f.description = "Current League Table"
                    case "Squad":
                        f.function = self.squad
                        f.description = "Team Squad Members"
                    case "Summary":
                        pass  # Don't care.
                    case "Transfers":
                        f.function = self.transfers
                        f.emoji = "📹"
                        f.style = discord.ButtonStyle.red
                        f.description = "Recent Transfers"
                    case _:
                        inf = f"Team found extra tab named {text}"
                        logger.info(inf)
                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            ph = f"{', '.join([i.label for i in v])}"
            self.add_function_row(v, k, ph)
        return row

    async def fixtures(self) -> discord.InteractionMessage:
        """Push upcoming fixtures to Team View"""
        rows = await fs.parse_games(self.bot, self.team, "/fixtures/")
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.team.base_embed()
        embed.title = "Fixtures"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._cached_function = None
        return await self.update()

    async def news(self) -> discord.InteractionMessage:
        """Get a list of news articles related to a team in embed format"""
        page = await self.bot.browser.new_page()
        try:
            await page.goto(f"{self.team.url}/news", timeout=5000)

            locator = page.locator(".matchBox")
            await locator.wait_for()
            tree = html.fromstring(await locator.inner_html())
        finally:
            await page.close()

        items = []

        base_embed = await self.team.base_embed()

        for i in tree.xpath('.//div[@class="rssNews"]'):
            e = base_embed.copy()

            xpath = './/div[@class="rssNews__title"]/text()'
            e.title = "".join(i.xpath(xpath))

            xpath = ".//a/@href"
            e.url = fs.FLASHSCORE + "".join(i.xpath(xpath))

            e.set_image(url="".join(i.xpath(".//img/@src")))

            xpath = './/div[@class="rssNews__perex"]/text()'
            e.description = "".join(i.xpath(xpath))

            xpath = './/div[@class="rssNews__provider"]/text()'
            provider = "".join(i.xpath(xpath)).split(",")

            ts = datetime.datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
            e.timestamp = ts
            e.set_footer(text=provider[-1].strip())
            items.append(e)

        self.pages = items
        return await self.update()

    async def squad(
        self,
        to_click: Optional[str] = None,
        sort: Optional[str] = None,
        clear_index: bool = False,
    ) -> discord.InteractionMessage:
        page = await self.bot.browser.new_page()
        try:
            await page.goto(f"{self.team.url}/squad", timeout=5000)
            await page.locator(".lineup").wait_for()

            # to_click refers to a button press.
            if to_click is not None:
                await page.locator("button", has_text=to_click).click()

            tree = html.fromstring(await page.content())
        finally:
            await page.close()

        # tab += 1  # tab is Indexed at 0 but xpath indexes from [1]
        rows = tree.xpath('.//div[@class="lineup__title" or "lineup__row"]')

        players: list[fs.Player | str] = []

        e = await self.team.base_embed()
        e = e.copy()

        e.title = sort.title() if sort else "Squad"

        e.description = ""
        for i in rows:
            # A header row with the player's position.
            if position := "".join(i.xpath("/text()")).strip():
                if e.description:
                    # Double Line Breaks after the first.
                    e.description += "\n"
                if not sort:
                    players.append(f"**{position}**\n")
                continue  # There will not be additional data.

            xpath = './/div[contains(@class, "cell--name")]/a/'
            link = "".join(i.xpath(xpath + "@href"))
            name = "".join(i.xpath(xpath + "text()"))
            try:  # Name comes in reverse order.
                forename, surname = name.split(" ", 1)
            except ValueError:
                forename, surname = None, name

            player = fs.Player(forename, surname, link)

            xpath = './/span[contains(@class,"jersey")]/text()'
            player.squad_number = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"flag")]/@title'
            player.country = i.xpath(xpath)

            xpath = './/span[contains(@class,"cell--age")]/text()'
            player.age = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"cell--goal")]/text()'
            self.goals = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"matchesPlayed")]/text()'
            self.appearances = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"yellowCard")]/text()'
            self.yellows = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@class,"redCard")]/text()'
            self.reds = int("".join(i.xpath(xpath)))

            xpath = './/span[contains(@title,"Injury")]/@title'
            player.injury = "".join(i.xpath(xpath))
            players.append(player)

        if sort:
            # Remove the header rows.
            players = [i for i in players if isinstance(i, fs.Player)]

            players = [i for i in players if getattr(i, sort)]
            players = sorted(
                players,
                key=lambda x: getattr(x, sort),
                reverse=bool(sort in ["goals", "yellows", "reds"]),
            )

        if clear_index:
            self.index = 0

        players = embed_utils.paginate(players)[self.index]
        self.pages = players

        dropdown = []
        for i in players:
            if isinstance(i, str):
                continue

            flag = i.flag
            parent = self.squad()
            v = PlayerView(self.interaction, i, parent=parent).update
            dropdown.append(view_utils.Funcable(i.name, v, emoji=flag))

        for i in players:
            e.description += i.squad_row if isinstance(i, fs.Player) else i
            e.description += "\n"

        filters = []
        for label, filt, emoji in [
            ("Sort by Goals", "goals", "⚽"),
            ("Sort by Red Cards", "reds", "🟥"),
            ("Sort by Yellow Cards", "yellows", "🟨"),
            ("Sort by Appearances", "appearances", "🟨"),
            ("Sort by Age", "age", None),
            ("Show only injured", "injured", fs.INJURY_EMOJI),
        ]:
            opt = view_utils.Funcable(label, self.squad, [], emoji=emoji)

            tc = to_click
            opt.keywords = {"to_click": tc, "sort": filt, clear_index: True}
            opt.disabled = sort == filt
            filters.append(opt)

        self.add_function_row(filters, 3, "Sort or Filter")
        self.add_page_buttons(4)
        self._cached_function = self.squad

        r = self.interaction.edit_original_response
        return await r(embed=e, view=self)

    async def standings(
        self,
        first: str = "table",
        second: str = "overall",
        thirrd: Optional[str] = None,
    ) -> discord.InteractionMessage:
        """Send Specified Table to view"""
        e = await self.team.base_embed()

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.team.url}#/standings/{first}"
                e.title = f"{first.title().replace('_', '/')}"
                if second is not None:
                    e.title += f" ({second.title()}"
                    e.url += f"/{second}"
                    if thirrd:
                        e.title += f": {thirrd}"
                        e.url += f"/{thirrd}"
                    e.title += ")"
                await page.goto(e.url, timeout=5000)

                # Chaining Locators is fucking aids.
                # Thank you for coming to my ted talk.
                inner = page.locator(".tableWrapper")
                outer = page.locator("div", has=inner)
                table_div = page.locator("div", has=outer).last
                await table_div.wait_for(state="visible", timeout=5000)

                row = await self.handle_tabs(page, self.standings)
                rows = {}

                loc = page.locator(".subTabs")
                for i in range(await loc.count()):
                    rows[row] = []

                    sub = loc.nth(i).locator("a")
                    for o in range(await sub.count()):

                        text = await sub.nth(o).text_content()

                        if not text:
                            continue

                        f = view_utils.Funcable(text, self.standings)
                        a = "aria-current"
                        b = await sub.nth(o).get_attribute(a) is not None
                        f.disabled = b
                        match o:  # Buttons are always in the same order.
                            case 1:
                                args = [first, "home"]
                            case 2:
                                args = [first, "away"]
                            case _:
                                args = [first, "overall"]
                        if row == 4:
                            args += [text]
                        f.args = args
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    ph = f"{', '.join([i.label for i in v])}"
                    self.add_function_row(v, k, ph)

                await page.eval_on_selector_all(fs.ADS, JS)
                image = await table_div.screenshot(type="png")
                file = discord.File(fp=io.BytesIO(image), filename="table.png")
            finally:
                await page.close()
        e.set_image(url="attachment://table.png")

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[file], view=self)

    async def transfers(
        self, to_click: Optional[str] = "All"
    ) -> discord.InteractionMessage:
        """Get a list of the team's recent transfers."""
        e = await self.team.base_embed()
        e = e.copy()
        e.description = ""
        e.title = f"Transfers ({to_click})"

        async with semaphore:
            page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.team.url}/transfers/"
                await page.goto(e.url, timeout=5000)
                await page.wait_for_selector("section#transfers", timeout=5000)
                row = await self.handle_tabs(page, self.transfers)
                rows = {}

                if to_click is not None:
                    await page.locator("button", has_text=to_click).click()

                filters = page.locator("button.filter__filter")

                for o in range(await filters.count()):

                    text = await filters.nth(o).text_content()
                    if not text:
                        continue

                    a = "filter__filter--selected"
                    b = await filters.nth(o).get_attribute(a) is not None
                    f = view_utils.Funcable(text, self.transfers, disabled=b)
                    f.disabled = b
                    match o:
                        case 0:
                            f.args = ["All"]
                        case 1:
                            f.args = ["Arrivals"]
                        case 2:
                            f.args = ["Departures"]
                        case _:
                            logger.info("Extra Buttons Found: transf %s", text)
                    rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    ph = f"{', '.join([i.label for i in v])}"
                    self.add_function_row(v, k, ph)
                tree = html.fromstring(await page.inner_html(".transferTab"))
            finally:
                await page.close()

        players = []
        teams = []
        for row in tree.xpath('.//div[@class="transferTab__row"]'):
            xpath = './/div[@class="transferTab__season"]/text()'
            date = "".join(row.xpath(xpath))
            date = datetime.datetime.strptime(date, "%d/%m/%Y")
            date = timed_events.Timestamp(date).relative

            xpath = './/div[@class="transferTab__name"]/a'
            name = "".join(row.xpath(xpath + "/text()"))
            link = "".join(row.xpath(xpath + "@href"))

            try:
                forename, surname = name.split(" ", 1)
            except ValueError:
                forename, surname = None, name

            player = fs.Player(forename, surname, link)
            player.country = row.xpath('.//span[@class="flag"]/@title')

            if row.xpath('.//svg[@class="transferTab__icon--in]'):
                emoji = fs.INBOUND_EMOJI
            else:
                emoji = fs.OUTBOUND_EMOJI

            tf_type = row.xpath('.//div[@class="transferTab__text]/text()')

            xpath = './/div[@class="transferTab__href"]'
            team_name = "".join(row.xpath(xpath + "/text()"))
            team_link = "".join(row.xpath(xpath + "/@href"))

            link = team_link.split("/")[-1]
            team = self.bot.get_team(link)
            if team is None:
                team = fs.Team(None, team_name, team_link)

            pmd = player.markdown
            tmd = team.markdown
            e.description += f"{date} {pmd} {emoji} {tf_type} {tmd}\n"
            players.append(player)
            teams.append(team)

        r = self.interaction.edit_original_response
        return await r(embed=e, view=self)

    async def results(self) -> discord.InteractionMessage:
        """Push Previous Results Team View"""
        rows = await fs.parse_games(self.bot, self.team, "/results/")

        output = []
        for i in rows:
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

        rows = [i.upcoming for i in rows] if rows else ["No Results Found :("]
        embed = await self.team.base_embed()
        embed = embed.copy()
        embed.title = "Fixtures"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._cached_function = None
        return await self.update()

    async def update(self) -> discord.InteractionMessage:
        if self._cached_function is None:
            return await super().update()
        else:
            return await self._cached_function()


class CompetitionView(view_utils.BaseView):
    """The view sent to a user about a Competition"""

    bot: Bot

    def __init__(
        self,
        interaction: Interaction[Bot],
        competition: fs.Competition,
        **kwargs,
    ) -> None:

        self.competition: fs.Competition = competition
        super().__init__(interaction, **kwargs)

    async def update(self, content: Optional[str] = None) -> None:
        """Send the latest version of the CompetitionView to the user"""
        self.clear_items()

        buttons = [
            view_utils.Funcable("Table", self.push_table, emoji="🥇"),
            view_utils.Funcable("Scorers", self.push_scorers, emoji="⚽"),
            view_utils.Funcable("Fixtures", self.push_fixtures, emoji="📆"),
            view_utils.Funcable("Results", self.push_results, emoji="⚽"),
        ]
        self.add_function_row(buttons, 4)

        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = self.pages[-1]

        i = self.interaction
        await i.edit_original_response(content=content, view=self, embed=embed)

    async def push_table(self) -> None:
        """Push Team's Table for a Competition to View"""
        embed = await self.competition.base_embed()
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition}"
        if img := await self.competition.get_table():
            embed.set_image(url=img)
            embed.description = timed_events.Timestamp().long
        else:
            embed.description = "No Table Found"

        self.index = 0
        self.pages = [embed]
        await self.update()

    async def push_scorers(self) -> None:
        """PUsh the Scorers Embed to Competition View"""
        self.index = 0
        await self.update()

    async def push_assists(self) -> None:
        """PUsh the Scorers Embed to View"""
        self.index = 0
        await self.update()

    async def push_fixtures(self) -> None:
        """Push upcoming competition fixtures to View"""
        rows = await fs.parse_games(self.bot, self.competition, "/fixtures/")
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.competition.base_embed()
        embed.title = f"≡ Fixtures for {self.competition}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        await self.update()

    async def push_results(self) -> None:
        """Push results fixtures to View"""
        rows = await fs.parse_games(self.bot, self.competition, "/results/")
        rows = [i.upcoming for i in rows] if rows else ["No Results Found"]
        embed = await self.competition.base_embed()
        embed.title = f"≡ Results for {self.competition.title}"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        await self.update()


class PlayerView(view_utils.BaseView):
    bot: Bot

    def __init__(
        self, interaction: Interaction[Bot], player: fs.Player, **kwargs
    ):
        super().__init__(interaction, **kwargs)
        self.player: fs.Player = player

    async def update(self) -> discord.InteractionMessage:
        r = self.interaction.edit_original_response
        return await r(content="Coming Soon!")


class FixtureView(ItemView):
    """The View sent to users about a fixture."""

    bot: Bot
    interaction: Interaction[Bot]

    def __init__(
        self, interaction: Interaction[Bot], fixture: fs.Fixture
    ) -> None:
        self.fixture: fs.Fixture = fixture
        super().__init__(interaction)

    async def handle_tabs(self, page: Page, current_function: Callable) -> int:
        """Generate our buttons"""
        self.clear_items()

        row_0 = []
        if self.fixture.competition is not None:
            cmp = self.fixture.competition
            func = CompetitionView(
                self.interaction, cmp, parent=self.summary
            ).update
            row_0.append(view_utils.Funcable(cmp.title, func, emoji="🏆"))

        if self.fixture.home.id:
            hm = self.fixture.home
            func = TeamView(self.interaction, hm, parent=self.summary).update
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
        sl = f"{self.fixture.score_line}"

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

                if row == 1:
                    f.style = discord.ButtonStyle.blurple

                active = "aria-current"
                b = await sub_loc.nth(o).get_attribute(active) is not None
                f.disabled = b

                match text:
                    case "Form":
                        f.function = self.standings
                        f.args = ["form"]
                    case "H2H":
                        f.function = self.h2h
                        f.description = "Head to Head Data"
                        f.emoji = "⚔"
                    case "HT/FT":
                        f.function = self.standings
                        f.args = ["ht_ft"]
                    case "Lineups":
                        f.function = self.lineups
                    case "Live Standings":
                        f.function = self.standings
                        f.args = ["live", None]
                    case "Match":
                        f.function = self.summary
                    case "News":
                        f.function = self.news
                        f.emoji = "📰"
                        f.description = f"News for {sl}"
                    case "Odds":
                        # TODO: Figure out if we want to encourage Gambling
                        continue
                    case "Over/Under":
                        f.function = self.standings
                        f.args = ["over_under"]
                    case "Photos":
                        f.function = self.photos
                        f.emoji = "📷"
                        f.style = discord.ButtonStyle.red
                        f.description = f"Photos from {sl}"
                    case "Report":
                        f.function = self.report
                        f.emoji = "📰"
                    case "Standings":
                        f.function = self.standings
                    case "Stats":
                        f.function = self.stats
                    case "Summary":
                        f.function = self.summary
                        f.description = "A list of match events"
                    case "Top Scorers":
                        f.function = self.scorers
                        f.emoji = "⚽"
                        f.style = discord.ButtonStyle.red
                    case "Video":
                        f.function = self.video
                        f.emoji = "📹"
                        f.description = "Videos and Highlights"
                    case _:
                        inf = f"Fixture found extra tab named {text}"
                        logger.info(inf)
                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            ph = f"{', '.join([i.label for i in v])}"
            self.add_function_row(v, k, ph)
        return row

    async def h2h(
        self, team: Literal["overall", "home", "away"] = "overall"
    ) -> discord.InteractionMessage:
        """Get results of recent games for each team in the fixture"""
        e = await self.fixture.base_embed()
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
                    self.add_function_row(v, k, ph)
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
                ko = datetime.datetime.strptime(ko, "%d.%m.%y")
                ko = timed_events.Timestamp(ko).relative

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

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    async def lineups(self) -> discord.InteractionMessage:
        """Push Lineups & Formations Image to view"""
        e = await self.fixture.base_embed()
        e.title = "Lineups and Formations"

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}#/match-summary/lineups"
                await page.goto(e.url, timeout=5000)
                await page.eval_on_selector_all(fs.ADS, JS)
                await self.handle_tabs(page, self.lineups)
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
            file = [discord.File(fp=data, filename="lineups.png")]
        else:
            e.description = "Lineups and Formations unavailable."
            file = []
        e.set_image(url="attachment://lineups.png")

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=file, view=self)

    async def news(self) -> discord.InteractionMessage:
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
            ts = datetime.datetime.strptime(time, fmt)
            ts = timed_events.Timestamp(ts).relative
            e.description += f"> [{title}]({link})\n{source} {ts}\n\n"

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    async def photos(self) -> discord.InteractionMessage:
        """Push Photos to view"""
        e = await self.fixture.base_embed()
        e.title = "Fixture - Photos coming soon."
        logger.info(f"Fixture {self.fixture.score_line} has Photos tab")

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    async def report(self) -> discord.InteractionMessage:
        """Get the report in text format."""
        e = await self.fixture.base_embed()

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}#/report/"
                await page.goto(e.url, timeout=5000)
                await self.handle_tabs(page, self.summary)
                loc = ".reportTab"
                tree = html.fromstring(await page.inner_html(loc))
            finally:
                await page.close()

        title = "".join(tree.xpath(".//div[@class='reportTabTitle']/text()"))

        image = "".join(tree.xpath(".//img[@class='reportTabImage']/@src"))
        if image:
            e.set_image(url=image)
        ftr = "".join(tree.xpath(".//span[@class='reportTabInfo']/text()"))
        e.set_footer(text=ftr)

        xpath = ".//div[@class='reportTabContent']/p/text()"
        content = [f"{x}\n" for x in tree.xpath(xpath)]

        hdr = f"**{title}**\n\n"
        self.pages = embed_utils.rows_to_embeds(e, content, 5, hdr, "", 2500)
        return await self.update()

    async def scorers(self) -> discord.InteractionMessage:
        """Push Scorers to View"""
        e = await self.fixture.base_embed()
        e.title = "Fixture - Scorers coming soon."
        logger.info(f"Fixture {self.fixture.url} has Top Scorers tab")

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    async def stats(self, half: int = 0) -> discord.InteractionMessage:
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
                    self.add_function_row(v, k, ph)
            finally:
                await page.close()

        output = ""
        xp = './/div[@class="stat__category"]'
        for row in html.fromstring(src).xpath(xp):
            try:
                h = row.xpath('.//div[@class="stat__homeValue"]/text()')[0]
                s = row.xpath('.//div[@class="stat__categoryName"]/text()')[0]
                a = row.xpath('.//div[@class="stat__awayValue"]/text()')[0]
                output += f"{h.rjust(4)} [{s.center(19)}] {a.ljust(4)}\n"
            except IndexError:
                continue

        if output:
            e.description = f"```ini\n{output}```"
        else:
            e.description = "Could not find stats for this game."
        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    async def summary(self) -> discord.InteractionMessage:
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

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    async def standings(
        self,
        first: str = "table",
        second: str = "overall",
        thirrd: Optional[str] = None,
    ) -> discord.InteractionMessage:
        """Send Specified Table to view"""
        e = await self.fixture.base_embed()

        async with semaphore:
            page: Page = await self.bot.browser.new_page()
            try:
                e.url = f"{self.fixture.url}#/standings/{first}"
                e.title = f"{first.title().replace('_', '/')}"
                if second is not None:
                    e.title += f" ({second.title()}"
                    e.url += f"/{second}"
                    if thirrd:
                        e.title += f": {thirrd}"
                        e.url += f"/{thirrd}"
                    e.title += ")"
                await page.goto(e.url, timeout=5000)

                # Chaining Locators is fucking aids.
                # Thank you for coming to my ted talk.
                inner = page.locator(".tableWrapper")
                outer = page.locator("div", has=inner)
                table_div = page.locator("div", has=outer).last
                await table_div.wait_for(state="visible", timeout=5000)

                row = await self.handle_tabs(page, self.standings)
                rows = {}

                loc = page.locator(".subTabs")
                for i in range(await loc.count()):
                    rows[row] = []

                    sub = loc.nth(i).locator("a")
                    for o in range(await sub.count()):

                        text = await sub.nth(o).text_content()

                        if not text:
                            continue

                        f = view_utils.Funcable(text, self.standings)
                        a = "aria-current"
                        b = await sub.nth(o).get_attribute(a) is not None
                        f.disabled = b
                        match o:  # Buttons are always in the same order.
                            case 1:
                                args = [first, "home"]
                            case 2:
                                args = [first, "away"]
                            case _:
                                args = [first, "overall"]
                        if row == 4:
                            args += [text]
                        f.args = args
                        rows[row].append(f)
                    row += 1

                for k, v in rows.items():
                    ph = f"{', '.join([i.label for i in v])}"
                    self.add_function_row(v, k, ph)

                await page.eval_on_selector_all(fs.ADS, JS)
                image = await table_div.screenshot(type="png")
                file = discord.File(fp=io.BytesIO(image), filename="table.png")
            finally:
                await page.close()
        e.set_image(url="attachment://table.png")

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[file], view=self)

    async def video(self) -> discord.InteractionMessage:
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
                url = await page.locator("object").get_attribute("data")
                # OLD: https://www.youtube.com/embed/GUH3NIIGbpo
                # NEW: https://www.youtube.com/watch?v=GUH3NIIGbpo
                if url is None:
                    return await self.bot.error(i, "Error fetching video.")
                url = url.replace("embed/", "watch?v=")
            finally:
                await page.close()
        # e.description = f"[{video}]({video_url})"
        r = self.interaction.edit_original_response
        return await r(content=url, embed=None, attachments=[], view=self)


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
        e = discord.Embed(title="Choose a Fixture")
        e.description = ""

        for f in targets:
            if f.competition:
                desc = f.competition.title
            else:
                desc = None

            if f.id is not None:
                d.add_option(label=f.score_line, description=desc)
            e.description += f"`{f.id}` {f.bold_markdown}\n"

        self.add_item(d)
        self.add_page_buttons(1)
        await self.interaction.edit_original_response(embed=e, view=self)


async def choose_recent_fixture(
    interaction: Interaction[Bot], fsr: fs.Competition | fs.Team
):
    """Allow the user to choose from the most recent games of a fixture"""
    fixtures = await fs.parse_games(interaction.client, fsr, "/results/")
    await (v := FixtureSelect(interaction, fixtures)).update()
    await v.wait()
    return next(i for i in fixtures if i.score_line == v.value[0])


class Fixtures(Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(fs)
        reload(view_utils)
        reload(image_utils)
        reload(timed_events)
        reload(embed_utils)

    # Group Commands for those with multiple available subcommands.
    default = Group(
        name="default",
        guild_only=True,
        description="Set the server's default team and competition.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @default.command(name="team")
    @discord.app_commands.autocomplete(team=team_ac)
    @discord.app_commands.describe(team=TEAM_NAME)
    async def d_team(self, ctx: Interaction[Bot], team: str) -> None:
        """Set the default team for your flashscore lookups"""
        await ctx.response.defer(thinking=True)

        if ctx.guild is None:
            return

        fsr = await fetch_team(ctx, team)

        e = await fsr.base_embed()
        e.description = f"Commands will use {fsr.markdown} as default team"

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id)
                         VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, ctx.guild.id)

                q = """INSERT INTO fixtures_defaults (guild_id, default_team)
                       VALUES ($1,$2) ON CONFLICT (guild_id)
                       DO UPDATE SET default_team = $2
                       WHERE excluded.guild_id = $1"""
                await connection.execute(q, ctx.guild.id, fsr.id)
        await ctx.edit_original_response(embed=e)

    @default.command(name="competition")
    @discord.app_commands.autocomplete(competition=comp_ac)
    @discord.app_commands.describe(competition=COMPETITION)
    async def d_comp(self, ctx: Interaction[Bot], competition: str) -> None:
        """Set the default competition for your flashscore lookups"""
        await ctx.response.defer(thinking=True)

        if ctx.guild is None:
            raise

        fsr = await fetch_comp(ctx, competition)

        q = """INSERT INTO fixtures_defaults (guild_id, default_league)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET default_league = $2
                WHERE excluded.guild_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, ctx.guild.id, fsr.id)

        e = await fsr.base_embed()
        e.description = f"Default Competition is now {fsr.markdown}"
        await ctx.edit_original_response(embed=e)

    match = Group(
        name="match",
        description="Get information about a match from flashscore",
    )

    # FIXTURE commands
    @match.command(name="table")
    @discord.app_commands.autocomplete(fixture=fx_ac)
    @discord.app_commands.describe(fixture=FIXTURE)
    async def fx_table(
        self, ctx: Interaction[Bot], fixture: str
    ) -> discord.InteractionMessage:
        """Look up the table for a fixture."""
        await ctx.response.defer(thinking=True)

        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await fetch_team(ctx, fixture)
            fix = await choose_recent_fixture(ctx, team)
        return await FixtureView(ctx, fix).standings()

    @match.command()
    @discord.app_commands.autocomplete(fixture=fx_ac)
    @discord.app_commands.describe(fixture=FIXTURE)
    async def stats(
        self, ctx: Interaction[Bot], fixture: str
    ) -> discord.InteractionMessage:
        """Look up the stats for a fixture."""
        await ctx.response.defer(thinking=True)

        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await fetch_team(ctx, fixture)
            fix = await choose_recent_fixture(ctx, team)
        return await FixtureView(ctx, fix).stats()

    @match.command()
    @discord.app_commands.autocomplete(fixture=fx_ac)
    @discord.app_commands.describe(fixture=FIXTURE)
    async def lineups(
        self, ctx: Interaction[Bot], fixture: str
    ) -> discord.InteractionMessage:
        """Look up the lineups and/or formations for a Fixture."""
        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await fetch_team(ctx, fixture)
            fix = await choose_recent_fixture(ctx, team)
        return await FixtureView(ctx, fix).lineups()

    @match.command()
    @discord.app_commands.autocomplete(fixture=fx_ac)
    @discord.app_commands.describe(fixture=FIXTURE)
    async def summary(
        self, ctx: Interaction[Bot], fixture: str
    ) -> discord.InteractionMessage:
        """Get a summary for a fixture"""
        await ctx.response.defer(thinking=True)

        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await fetch_team(ctx, fixture)
            fix = await choose_recent_fixture(ctx, team)
        return await FixtureView(ctx, fix).summary()

    @match.command(name="h2h")
    @discord.app_commands.autocomplete(fixture=fx_ac)
    @discord.app_commands.describe(fixture=FIXTURE)
    async def h2h(
        self, interaction: Interaction[Bot], fixture: str
    ) -> discord.InteractionMessage:
        """Lookup the head-to-head details for a Fixture"""
        await interaction.response.defer(thinking=True)

        if (fix := self.bot.get_fixture(fixture)) is None:
            team = await fetch_team(interaction, fixture)
            fix = await choose_recent_fixture(interaction, team)
        return await FixtureView(interaction, fix).h2h()

    league = Group(
        name="competition",
        description="Get information about a competition from flashscore",
    )

    @league.command(name="fixtures")
    @discord.app_commands.autocomplete(competition=comp_ac)
    @discord.app_commands.describe(competition=COMPETITION)
    async def fx_comp(
        self, interaction: Interaction[Bot], competition: str
    ) -> discord.InteractionMessage:
        """Fetch upcoming fixtures for a competition."""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_comp(interaction, competition)
        return await CompetitionView(interaction, fsr).push_fixtures()

    @league.command(name="results")
    @discord.app_commands.autocomplete(competition=comp_ac)
    @discord.app_commands.describe(competition=COMPETITION)
    async def rx_comp(self, interaction: Interaction[Bot], competition: str):
        """Get recent results for a competition"""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_comp(interaction, competition)
        return await CompetitionView(interaction, fsr).push_results()

    @league.command(name="scorers")
    @discord.app_commands.autocomplete(competition=comp_ac)
    @discord.app_commands.describe(competition=COMPETITION)
    async def scorers_comp(
        self, ctx: Interaction[Bot], competition: str
    ) -> discord.InteractionMessage:
        """Get top scorers from a competition."""
        await ctx.response.defer(thinking=True)
        fsr = await fetch_comp(ctx, competition)
        return await CompetitionView(ctx, fsr).push_scorers()

    @league.command()
    @discord.app_commands.describe(competition=COMPETITION)
    @discord.app_commands.autocomplete(competition=comp_ac)
    async def scores(
        self, ctx: Interaction[Bot], competition: Optional[str]
    ) -> Message:
        """Fetch current scores for a specified competition,
        or if no competition is provided, all live games."""

        await ctx.response.defer(thinking=True)

        if not self.bot.games:
            return await self.bot.error(ctx, "No live games found")

        if competition:
            if res := self.bot.get_competition(competition):
                games = await fs.parse_games(self.bot, res, "/fixtures/")
            else:
                games = self.bot.games
                lwr = competition.lower()

                res = list(
                    filter(
                        lambda i: i.competition
                        and lwr in i.competition.title.lower(),
                        games,
                    )
                )

                if not res:
                    err = f"No live games found for `{competition}`"
                    return await self.bot.error(ctx, err)
        else:
            games = self.bot.games

        comp = None
        header = f"Scores as of: {timed_events.Timestamp().long}\n"
        base_embed = discord.Embed(color=discord.Colour.og_blurple())
        base_embed.title = "Current scores"
        base_embed.description = header
        e = base_embed.copy()
        e.description = ""
        embeds = []

        for x, y in [(i.competition, i.live_score_text) for i in games]:
            if x and x != comp:  # We need a new header if it's a new comp.
                comp = x
                output = f"\n**{x.title}**\n{y}\n"
            else:
                output = f"{y}\n"

            if len(e.description + output) < 2048:
                e.description = f"{e.description}{output}"
            else:
                embeds.append(e)
                e = base_embed.copy()
                e.description = f"\n**{x}**\n{y}\n"
        embeds.append(e)
        return await view_utils.Paginator(ctx, embeds).update()

    @league.command(name="table")
    @discord.app_commands.autocomplete(competition=comp_ac)
    @discord.app_commands.describe(
        competition="Enter the name of a competition"
    )
    async def comp_table(
        self, interaction: Interaction[Bot], competition: str
    ) -> None:
        """Get the Table of a competition"""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_comp(interaction, competition)
        return await CompetitionView(interaction, fsr).push_table()

    team = discord.app_commands.Group(
        name="team", description="Get information about a team "
    )

    @team.command(name="fixtures")
    @discord.app_commands.autocomplete(team=team_ac)
    @discord.app_commands.describe(team=TEAM_NAME)
    async def fx_team(
        self, interaction: Interaction[Bot], team: str
    ) -> discord.InteractionMessage:
        """Fetch upcoming fixtures for a team."""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_team(interaction, team)
        return await TeamView(interaction, fsr).fixtures()

    @team.command(name="results")
    @discord.app_commands.autocomplete(team=team_ac)
    @discord.app_commands.describe(team=TEAM_NAME)
    async def rx_team(
        self, interaction: Interaction[Bot], team: str
    ) -> discord.InteractionMessage:
        """Get recent results for a Team"""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_team(interaction, team)
        return await TeamView(interaction, fsr).results()

    @team.command(name="table")
    @discord.app_commands.autocomplete(team=team_ac)
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_table(
        self, interaction: Interaction[Bot], team: str
    ) -> discord.InteractionMessage:
        """Get the Table of one of a Team's competitions"""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_team(interaction, team)
        return await TeamView(interaction, fsr).standings()

    @team.command()
    @discord.app_commands.autocomplete(team=team_ac)
    @discord.app_commands.describe(team=TEAM_NAME)
    async def news(
        self, interaction: Interaction[Bot], team: str
    ) -> discord.InteractionMessage:
        """Get the latest news for a team"""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_team(interaction, team)
        return await TeamView(interaction, fsr).news()

    @team.command()
    @discord.app_commands.autocomplete(team=team_ac)
    @discord.app_commands.describe(team=TEAM_NAME)
    async def squad(
        self, interaction: Interaction[Bot], team: str
    ) -> discord.InteractionMessage:
        """Lookup a team's squad members"""
        await interaction.response.defer(thinking=True)
        fsr = await fetch_team(interaction, team)
        return await TeamView(interaction, fsr).squad()


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
