"""Lookups of Live Football Data for teams, fixtures, and competitions."""
# TODO: GLOBAL Nuke page.content in favour of locator.inner_html()
# TODO: Standings => Team Dropdown
# TODO: Fixture => photos
# TODO: Fixture => report
# TODO: Top Scorers
# TODO: Fixtures => Dropdowns for Fixture Select
# TODO: Results => Dropdowns for Fixture Select
# TODO: Transfers => Dropdowns for Teams & Competitions
# TODO: TeamView.squad => Enumerate when not sorting by squad number.
# TODO: Hybridise .news
# TODO: File=None in all r()
# TODO: Globally Nuke _ac for Transformers


from __future__ import annotations

import asyncio
import io
import logging
import datetime
import importlib
import typing

# D.py
import discord
from discord.ext import commands

# Custom Utils
from lxml import html

import ext.toonbot_utils.flashscore as fs
from ext.utils import view_utils, embed_utils, image_utils, timed_events, flags

from playwright.async_api import Page, TimeoutError as PlayWrightTimeoutError

if typing.TYPE_CHECKING:
    from core import Bot


logger = logging.getLogger("Fixtures")

JS = "ads => ads.forEach(x => x.remove());"
TEAM_NAME = "Enter the name of a team to search for"
FIXTURE = "Search for a fixture by team name"
COMPETITION = "Enter the name of a competition to search for"


async def set_default(
    interaction: discord.Interaction[Bot],
    param: typing.Literal["default_league", "default_team"],
) -> None:
    """Fetch the default team or default league for this server"""
    if interaction.guild is None:
        interaction.extras["default"] = None
        return

    records = interaction.client.fixture_defaults
    gid = interaction.guild.id
    record = next((i for i in records if i["guild_id"] == gid), None)

    if record is None or record[param] is None:
        interaction.extras["default"] = None
        return

    if param == "default_team":
        default = interaction.client.get_team(record[param])
    else:
        default = interaction.client.get_competition(record[param])

    if default is None:
        interaction.extras["default"] = None
        return

    if (def_id := default.id) is None or (name := default.name) is None:
        interaction.extras["default"] = None
        return

    name = f"⭐ Server default: {name}"[:100]
    default = discord.app_commands.Choice(name=name, value=def_id)
    interaction.extras["default"] = default
    return


async def choose_recent_fixture(
    interaction: discord.Interaction[Bot], fsr: fs.Competition | fs.Team
):
    """Allow the user to choose from the most recent games of a fixture"""
    fixtures = await fs.parse_games(interaction.client, fsr, "/results/")
    await (v := FixtureSelect(interaction, fixtures)).update()
    await v.wait()
    return next(i for i in fixtures if i.score_line == v.value[0])


# Autocompletes
class FixtureTransformer(discord.app_commands.Transformer):
    async def autocomplete(
        self, interaction: discord.Interaction[Bot], current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Check if user's typing is in list of live games"""
        cur = current.casefold()

        choices = []
        for i in interaction.client.games:
            ac = i.ac_row.casefold()
            if cur and cur not in ac:
                continue

            if i.id is None:
                continue

            name = i.ac_row[:100]
            choice = discord.app_commands.Choice(name=name, value=i.id)

            choices.append(choice)

            if len(choices) == 25:
                break

        if current:
            v = f"🔎 Search for '{current}'"

            srch = [discord.app_commands.Choice(name=v, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: discord.Interaction[Bot], value: str
    ) -> typing.Optional[fs.Fixture]:
        await interaction.response.defer(thinking=True)

        if fix := interaction.client.get_fixture(value):
            return fix

        if not (fsr := interaction.client.get_team(value)):
            teams = await fs.search(value, "team", interaction=interaction)
            teams = typing.cast(list[fs.Team], teams)

            await (v := TeamSelect(interaction, teams)).update()
            await v.wait()

            if not v.value:
                return None
            fsr = next(i for i in teams if i.id == v.value[0])
        return await choose_recent_fixture(interaction, fsr)


class TeamTransformer(discord.app_commands.Transformer):
    async def autocomplete(
        self,
        interaction: discord.Interaction[Bot],
        current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = interaction.client.teams
        teams: list[fs.Team] = sorted(teams, key=lambda x: x.name)

        # Run Once - Set Default for interaction.
        if "default" not in interaction.extras:
            await set_default(interaction, "default_team")

        curr = current.casefold()

        choices = []
        for t in teams:
            if t.id is None:
                continue

            if curr not in t.title.casefold():
                continue

            c = discord.app_commands.Choice(name=t.name[:100], value=t.id)
            choices.append(c)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices

        if current:
            v = f"🔎 Search for '{current}'"

            srch = [discord.app_commands.Choice(name=v, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: discord.Interaction[Bot], value: str
    ) -> typing.Optional[fs.Team]:
        await interaction.response.defer(thinking=True)

        if fsr := interaction.client.get_team(value):
            return fsr

        teams = await fs.search(value, "team", interaction=interaction)
        teams = typing.cast(list[fs.Team], teams)

        await (v := TeamSelect(interaction, teams)).update()
        await v.wait()

        if not v.value:
            return None
        return next(i for i in teams if i.id == v.value[0])


class CompetitionTransformer(discord.app_commands.Transformer):
    async def autocomplete(
        self,
        interaction: discord.Interaction[Bot],
        current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored competitions"""
        lgs = sorted(interaction.client.competitions, key=lambda x: x.title)

        if "default" not in interaction.extras:
            await set_default(interaction, "default_league")

        curr = current.casefold()

        choices = []

        for lg in lgs:
            if curr not in lg.title.casefold() or lg.id is None:
                continue

            opt = discord.app_commands.Choice(name=lg.title[:100], value=lg.id)

            choices.append(opt)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices[:24]

        if current:
            v = f"🔎 Search for '{current}'"

            srch = [discord.app_commands.Choice(name=v, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: discord.Interaction[Bot], value: str
    ) -> typing.Optional[fs.Competition]:
        await interaction.response.defer(thinking=True)

        if fsr := interaction.client.get_competition(value):
            return fsr

        if "http" in value:
            return await fs.Competition.by_link(interaction.client, value)

        comps = await fs.search(value, "comp", interaction=interaction)
        comps = typing.cast(list[fs.Competition], comps)

        await (v := CompetitionSelect(interaction, comps)).update()
        await v.wait()

        if not v.value:
            return None
        return next(i for i in comps if i.id == v.value[0])


# Searching
class ItemView(view_utils.BaseView):

    bot: Bot
    interaction: discord.Interaction[Bot]

    def __init__(
        self, interaction: discord.Interaction[Bot], page: Page, **kwargs
    ) -> None:
        super().__init__(interaction, **kwargs)

        self.page: Page = page

        # For Functions that require pagination over multiple items
        # we don't use the generic "update".
        self._cached_function: typing.Optional[typing.Callable] = None

    @property
    def object(self) -> fs.Team | fs.Competition | fs.Fixture:
        if isinstance(self, TeamView):
            return self.team
        elif isinstance(self, FixtureView):
            return self.fixture
        elif isinstance(self, CompetitionView):
            return self.competition
        else:
            raise

    async def on_timeout(self) -> None:
        if not self.page.is_closed():
            await self.page.close()

        r = self.interaction.edit_original_response
        try:
            await r(view=None)
        except discord.NotFound:
            pass

    async def handle_tabs(self) -> int:
        """Generate our buttons. Returns the next free row number"""
        self.clear_items()

        # key: [Item, Item, Item, ...]
        rows: dict[int, list[view_utils.Funcable]] = dict()
        row = 1
        # Main Tabs
        tag = "div.tabs__group"

        # While we're here, let's also grab the logo url.
        if not isinstance(self, FixtureView):
            if not isinstance(self.object, fs.Fixture):
                if self.object.logo_url is None:
                    logo = self.page.locator("img.heading__logo")
                    logo_url = await logo.get_attribute("src")
                    if logo_url is not None:
                        logo_url = fs.FLASHSCORE + logo_url
                        self.object.logo_url = logo_url

        for i in range(await (loc := self.page.locator(tag)).count()):
            rows[row] = []
            for o in range(await (sub_loc := loc.nth(i).locator("a")).count()):
                text = await sub_loc.nth(o).text_content()

                if not text:
                    continue

                link = await sub_loc.nth(o).get_attribute("href")

                if text == "Archive":
                    f = view_utils.Funcable(text, self.archive)
                    f.description = "Previous Season Results"
                    f.emoji = "🗄️"

                elif text == "Fixtures":
                    f = view_utils.Funcable(text, self.fixtures)
                    f.description = "Upcoming Fixtures"
                    f.emoji = "🗓️"

                elif text == "H2H":
                    f = view_utils.Funcable(text, self.h2h)
                    f.description = "Head to Head Data"
                    f.emoji = "⚔"

                elif text == "Lineups":
                    f = view_utils.Funcable(text, self.lineups)
                    f.emoji = "🧑‍🤝‍🧑"

                elif text == "News":
                    f = view_utils.Funcable(text, self.news)
                    f.emoji = "📰"

                elif text == "Photos":
                    f = view_utils.Funcable(text, self.photos)
                    f.emoji = "📷"
                    f.style = discord.ButtonStyle.red

                elif text == "Report":
                    f = view_utils.Funcable(text, self.report)
                    f.emoji = "📰"

                elif text == "Results":
                    f = view_utils.Funcable(text, self.results)
                    f.description = "Recent Results"
                    f.emoji = "📋"

                elif text == "Standings":
                    f = view_utils.Funcable(text, self.standings)
                    f.description = "Current League Table"
                    f.emoji = "🏅"

                elif text in ["Form", "HT/FT", "Live Standings", "Over/Under"]:
                    f = view_utils.Funcable(text, self.standings)
                    f.emoji = "🏅"

                    if link:
                        link = f"{self.object.url}standings/{link}"
                    f.args = [link]

                elif text == "Squad":
                    f = view_utils.Funcable(text, self.squad)
                    f.description = "Team Squad Members"
                    f.emoji = "🧑‍🤝‍🧑"

                elif text == "Stats":
                    f = view_utils.Funcable(text, self.stats)
                    f.emoji = "📊"

                elif text in ["Summary", "Match"]:
                    if not isinstance(self, FixtureView):
                        continue  # Summary is garbage on everything else.

                    f = view_utils.Funcable(text, self.summary)
                    f.description = "A list of match events"

                elif text == "Odds":
                    # Let's not support gambling.
                    # Unless I get an affiliate link ...
                    continue

                elif text == "Top Scorers":
                    f = view_utils.Funcable(text, self.top_scorers)
                    f.emoji = "⚽"
                    f.args = [f"{self.object.url}/standings/{link}"]
                    f.style = discord.ButtonStyle.red

                elif text == "Transfers":
                    f = view_utils.Funcable(text, self.transfers)
                    f.style = discord.ButtonStyle.red
                    f.description = "Recent Transfers"
                    f.emoji = "<:inbound:1079808760194814014>"

                elif text == "Video":
                    f = view_utils.Funcable(text, self.video)
                    f.emoji = "📹"
                    f.description = "Videos and Highlights"

                else:
                    logger.info("%s found extra tab %s", type(self), text)
                    continue

                if row == 1 and f.style is None:
                    f.style = discord.ButtonStyle.blurple

                active = "aria-current"
                b = await sub_loc.nth(o).get_attribute(active) is not None
                f.disabled = b

                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            ph = f"{', '.join([i.label for i in v])}"
            self.add_function_row(v, k, ph)
        return row

    async def archive(self) -> discord.InteractionMessage:
        """Get a list of Archives for a competition"""
        if not isinstance(self, CompetitionView):
            raise NotImplementedError

        if self._cached_function != self.archive:
            self.index = 0

        await self.page.goto(f"{self.competition.url}/archive/")
        row = await self.handle_tabs()

        embed = await self.competition.base_embed()
        embed.url = self.page.url
        sel = self.page.locator("#tournament-page-archiv")
        await sel.wait_for(timeout=5000)
        tree = html.fromstring(await sel.inner_html())

        teams: list[fs.Team] = []
        comps: list[fs.Competition] = []
        rows: list[str] = []
        for i in tree.xpath('.//div[@class="archive__row"]'):
            # Get Archive as Competition
            xpath = ".//div[@class='archive__season']/a"
            c_name = "".join(i.xpath(xpath + "/text()")).strip()
            c_link = "".join(i.xpath(xpath + "/@href")).strip()

            c_link = fs.FLASHSCORE + "/" + c_link.strip("/")

            country = self.competition.country
            comps.append(fs.Competition(None, c_name, country, c_link))

            # Get Winner
            xpath = ".//div[@class='archive__winner']//a"
            tm_name = "".join(i.xpath(xpath + "/text()")).strip()
            if tm_name:
                # if tm_name:
                tm_link = "".join(i.xpath(xpath + "/@href")).strip()
                tm_link = fs.FLASHSCORE + tm_link

                team = fs.Team(None, tm_name, tm_link)
                teams.append(team)
                rows.append(f"[{c_name}]({c_link}): 🏆 {team.markdown}")
            else:
                rows.append(f"[{c_name}]({c_link})")

        parent = view_utils.FuncButton(self.archive)

        self.pages = embed_utils.rows_to_embeds(embed, rows, 20)

        embed = self.pages[self.index]
        comps = embed_utils.paginate(comps, 20)[self.index]
        teams = embed_utils.paginate(teams, 20)[self.index]

        lg_dropdown: list[view_utils.Funcable] = []
        for comp in comps:
            itr = self.interaction
            view = CompetitionView(itr, self.page, comp, parent=parent)
            fn = view.standings
            lg_dropdown.append(view_utils.Funcable(comp.title, fn, emoji="🏆"))

        if lg_dropdown:
            self.add_function_row(lg_dropdown, row, "View Season")
            row += 1

        tm_dropdown: list[view_utils.Funcable] = []
        for team in set(teams):
            itr = self.interaction
            fn = TeamView(itr, self.page, team, parent=parent).fixtures
            tm_dropdown.append(view_utils.Funcable(team.name, fn, emoji="👕"))

        if tm_dropdown:
            self.add_function_row(tm_dropdown, row, "View Team")
            row += 1

        self._cached_function = self.archive
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self, attachments=[])

    # Fixture Only
    async def h2h(
        self, team: typing.Literal["overall", "home", "away"] = "overall"
    ) -> discord.InteractionMessage:
        """Get results of recent games for each team in the fixture"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        e = await self.object.base_embed()
        e.description = e.description or ""

        if not isinstance(self, FixtureView):
            raise

        e.title = {
            "overall": "Head to Head: Overall",
            "home": f"Head to Head: {self.fixture.home.name} at Home",
            "away": f"Head to Head: {self.fixture.away.name} Away",
        }[team]

        e.url = f"{self.fixture.url}/#/h2h/{team}"
        await self.page.goto(e.url, timeout=5000)
        await self.page.wait_for_selector(".h2h", timeout=5000)
        row = await self.handle_tabs()
        rows = {}

        locator = self.page.locator(".subTabs")

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

                try:
                    f.args = {0: ["overall"], 1: ["home"], 2: ["away"]}[o]
                except KeyError:
                    logger.info("Extra Buttons Found: H2H %s", text)
                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            ph = f"{', '.join([i.label for i in v])}"
            self.add_function_row(v, k, ph)

        tree = html.fromstring(await self.page.inner_html(".h2h"))

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

    # Competition, Team
    async def fixtures(self) -> discord.InteractionMessage:
        """Push upcoming competition fixtures to View"""
        if isinstance(self, FixtureView):
            raise NotImplementedError

        if isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        rows = await fs.parse_games(self.bot, self.object, "/fixtures/")
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]

        embed = await self.object.base_embed()

        embed.title = "Fixtures"
        embed.url = f"{self.object.url}/fixtures"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._cached_function = None
        return await self.update()

    # Fixture Only
    async def lineups(self) -> discord.InteractionMessage:
        """Push Lineups & Formations Image to view"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.fixture.base_embed()
        embed.title = "Lineups and Formations"

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        embed.url = f"{self.fixture.url}#/match-summary/lineups"
        await self.page.goto(embed.url, timeout=5000)
        await self.page.eval_on_selector_all(fs.ADS, JS)
        screenshots = []

        if await (fm := self.page.locator(".lf__fieldWrap")).count():
            screenshots.append(io.BytesIO(await fm.screenshot()))

        if await (lineup := self.page.locator(".lf__lineUp")).count():
            screenshots.append(io.BytesIO(await lineup.screenshot()))

        if screenshots:
            stitch = image_utils.stitch_vertical
            data = await asyncio.to_thread(stitch, screenshots)
            file = [discord.File(fp=data, filename="lineups.png")]
        else:
            embed.description = "Lineups and Formations unavailable."
            file = []
        embed.set_image(url="attachment://lineups.png")

        await self.handle_tabs()
        r = self.interaction.edit_original_response
        return await r(embed=embed, attachments=file, view=self)

    # Fixture Only
    async def photos(self) -> discord.InteractionMessage:
        """Push Photos to view"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.fixture.base_embed()
        embed.title = "Photos"
        embed.url = f"{self.fixture.url}#/photos"

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        await self.page.goto(embed.url)
        body = self.page.locator(".section")

        await body.wait_for()
        tree = html.fromstring(await body.inner_html())

        images = tree.xpath('.//div[@class="photoreportInner"]')

        self.pages = []
        for i in images:
            e = embed.copy()
            image = "".join(i.xpath(".//img/@src"))
            e.set_image(url=image)
            xp = './/div[@class="liveComment"]/text()'
            e.description = "".join(i.xpath(xp))
            self.pages.append(e)

        self._cached_function = None
        self.index = 0  # Pagination is handled purely by update()
        return await self.update()

    # Subclassed on Fixture & Team
    async def news(self) -> discord.InteractionMessage:
        raise NotImplementedError  # This is subclassed.

    # Fixture Only
    async def report(self) -> discord.InteractionMessage:
        """Get the report in text format."""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.fixture.base_embed()

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        embed.url = f"{self.fixture.url}#/report/"
        await self.page.goto(embed.url, timeout=5000)
        loc = ".reportTab"
        tree = html.fromstring(await self.page.inner_html(loc))

        title = "".join(tree.xpath(".//div[@class='reportTabTitle']/text()"))

        image = "".join(tree.xpath(".//img[@class='reportTabImage']/@src"))
        if image:
            embed.set_image(url=image)
        ftr = "".join(tree.xpath(".//span[@class='reportTabInfo']/text()"))
        embed.set_footer(text=ftr)

        xpath = ".//div[@class='reportTabContent']/p/text()"
        content = [f"{x}\n" for x in tree.xpath(xpath)]

        hdr = f"**{title}**\n\n"
        self.pages = embed_utils.rows_to_embeds(
            embed, content, 5, hdr, "", 2500
        )
        await self.handle_tabs()
        return await self.update()

    # Competition, Team
    async def results(self) -> discord.InteractionMessage:
        """Push Previous Results Team View"""
        if isinstance(self, FixtureView):
            # This one actually invalidates properly if we're using an "old"
            # fs.Fixture object
            raise NotImplementedError

        if isinstance(self.object, fs.Fixture):
            # This one just unfucks the typechecking for self.object.
            raise NotImplementedError  # No.

        rows = await fs.parse_games(self.bot, self.object, "/results/")

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        rows = [i.finished for i in rows] if rows else ["No Results Found :("]
        embed = await self.object.base_embed()
        embed = embed.copy()
        embed.title = "Results"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._cached_function = None
        await self.handle_tabs()
        return await self.update()

    # Competition, Fixture, Team
    async def top_scorers(
        self,
        link: typing.Optional[str] = None,
        clear_index: bool = False,
        nat_filter: set[str] = set(),
        tm_filter: set[str] = set(),
    ) -> discord.InteractionMessage:
        """Push Scorers to View"""
        embed = await self.object.base_embed()

        if clear_index:
            self.index = 0

        if link is None:
            oj = self.object

            # Example link "#/nunhS7Vn/top_scorers"
            # This requires a competition ID, annoyingly.
            link = f"{oj.url}/standings/"

        if link not in self.page.url:
            logger.info("Forcing page change %s -> %s", self.page.url, link)
            await self.page.goto(link)

        top_scorer_button = self.page.locator("a", has_text="Top Scorers")
        await top_scorer_button.wait_for(timeout=5000)

        if await top_scorer_button.get_attribute("aria-current") != "page":
            await top_scorer_button.click()

        tab_class = self.page.locator("#tournament-table-tabs-and-content")
        await tab_class.wait_for()

        await self.handle_tabs()

        embed.url = self.page.url
        embed.title = "Top Scorers"

        btn = self.page.locator(".topScorers__showMore")
        while await (btn).count():
            await btn.last.click()

        raw = await tab_class.inner_html()
        tree = html.fromstring(raw)

        players: list[fs.Player] = []

        rows = tree.xpath('.//div[@class="ui-table__body"]/div')

        for i in rows:
            xp = "./div[1]//text()"
            name = "".join(i.xpath(xp))

            xp = "./div[1]//@href"
            url = fs.FLASHSCORE + "".join(i.xpath(xp))

            player = fs.Player(None, name, url)

            xp = "./span[1]//text()"
            player.rank = int("".join(i.xpath(xp)).strip("."))

            xp = './/span[contains(@class,"flag")]/@title'
            player.country = i.xpath(xp)

            xp = './/span[contains(@class, "--goals")]/text()'
            try:
                player.goals = int("".join(i.xpath(xp)))
            except ValueError:
                pass

            xp = './/span[contains(@class, "--gray")]/text()'
            try:
                player.assists = int("".join(i.xpath(xp)))
            except ValueError:
                pass

            team_url = fs.FLASHSCORE + "".join(i.xpath("./a/@href"))
            team_id = team_url.split("/")[-2]

            tmn = "".join(i.xpath("./a/text()"))

            if (team := self.bot.get_team(team_id)) is None:
                team_link = "".join(i.xpath(".//a/@href"))
                team = fs.Team(team_id, tmn, team_link)

                comp_id = url.split("/")[-2]
                team.competition = self.bot.get_competition(comp_id)
            else:
                if team.name != tmn:
                    logger.info("Overrode team name %s -> %s", team.name, tmn)
                    team.name = tmn
                    await fs.save_team(self.bot, team)

            player.team = team

            players.append(player)

        self.add_item(NationalityFilter(self.interaction, players))
        self.add_item(TeamFilter(self.interaction, players))

        if nat_filter:
            players = [i for i in players if i.country[0] in nat_filter]

            filt = ", ".join(nat_filter)
            embed.set_footer(text=f"Filtered by nationalities: {filt}")
        elif tm_filter:
            plr = players
            players = [i for i in plr if i.team and i.team.name in tm_filter]
            filt = ", ".join(tm_filter)
            embed.set_footer(text=f"Filtered by teams: {filt}")

        embed.description = ""

        per_page = 20
        self.pages = embed_utils.paginate(players, per_page)
        players = self.pages[self.index]

        for i in players:
            num = f"`{str(i.rank).rjust(3)}.` ⚽ {i.goals} (+{i.assists})"
            tmd = f" ({i.team.markdown})" if i.team else ""
            embed.description += f"{num} {i.flag} {i.markdown}{tmd}\n"

        self.add_page_buttons(0)

        self._cached_function = self.top_scorers
        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self, attachments=[])

    # Team Only
    async def squad(
        self,
        tab_number: int = 0,
        sort: typing.Optional[str] = None,
        clear_index: bool = False,
    ) -> discord.InteractionMessage:
        """Get the squad of the team, filter or sort, push to view"""
        if not isinstance(self, TeamView):
            raise NotImplementedError

        # If we're changing the current sort or filter, we reset the index
        # to avoid an index error if we were on a later page and this has
        # fewer items.
        if clear_index:
            self.index = 0

        e = await self.team.base_embed()
        e = e.copy()
        e.url = f"{self.team.url}/squad"

        e.title = "Squad"
        e.description = ""

        btns = {}

        await self.page.goto(e.url, timeout=5000)
        loc = self.page.locator(".lineup").nth(tab_number)
        await loc.wait_for()

        # to_click refers to a button press.
        tree = html.fromstring(await loc.inner_html())

        def parse_row(row, position: str) -> fs.Player:
            xpath = './/div[contains(@class, "cell--name")]/a/@href'
            link = fs.FLASHSCORE + "".join(row.xpath(xpath))

            xpath = './/div[contains(@class, "cell--name")]/a/text()'
            name = "".join(row.xpath(xpath)).strip()
            try:  # Name comes in reverse order.
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            player = fs.Player(forename, surname, link)
            player.position = position

            xpath = './/div[contains(@class,"jersey")]/text()'
            player.squad_number = int("".join(row.xpath(xpath)) or 0)
            logger.info("#%s", player.squad_number)

            xpath = './/div[contains(@class,"flag")]/@title'
            player.country = [str(x.strip()) for x in row.xpath(xpath) if x]
            logger.info(player.country)

            xpath = './/div[contains(@class,"cell--age")]/text()'
            if age := "".join(row.xpath(xpath)).strip():
                player.age = int(age)

            xpath = './/div[contains(@class,"cell--goal")]/text()'
            if goals := "".join(row.xpath(xpath)).strip():
                player.goals = int(goals)

            xpath = './/div[contains(@class,"matchesPlayed")]/text()'
            if appearances := "".join(row.xpath(xpath)).strip():
                player.appearances = int(appearances)

            xpath = './/div[contains(@class,"yellowCard")]/text()'
            if yellows := "".join(row.xpath(xpath)).strip():
                player.yellows = int(yellows)

            xpath = './/div[contains(@class,"redCard")]/text()'
            if reds := "".join(row.xpath(xpath)).strip():
                player.reds = int(reds)

            xpath = './/div[contains(@title,"Injury")]/@title'
            player.injury = "".join(row.xpath(xpath)).strip()
            logger.info("injury %s", player.injury)

            return player

        # Grab All Players.
        players: list[fs.Player | str] = []
        for i in tree.xpath('.//div[@class="lineup__rows"]'):
            # A header row with the player's position.
            xpath = "./div[@class='lineup__title']/text()"
            position = "".join(i.xpath(xpath)).strip()

            if not sort:
                players.append(f"\n**{position}**\n\n")

            pl_rows = i.xpath('.//div[@class="lineup__row"]')
            players += [parse_row(i, position) for i in pl_rows]

        # Sort our Players
        if sort:
            # Remove the header rows.
            players = [i for i in players if getattr(i, sort)]

            e.set_footer(text=f"Sorted by {sort.replace('_', ' ').title()}")

            players = sorted(
                players,
                key=lambda x: getattr(x, sort),
                reverse=bool(sort in ["goals", "yellows", "reds"]),
            )

        # Paginate this shit.
        self.pages = embed_utils.paginate(players, 40)
        row = await self.handle_tabs()

        subloc = self.page.locator("role=tablist")
        for i in range(await loc.count()):
            btns[row] = []

            sub = subloc.nth(i).locator("button")
            for o in range(await sub.count()):

                text = await sub.nth(o).text_content()

                if not text:
                    continue

                if tab_number == o:
                    e.title += f" ({text})"
                    await sub.nth(o).click(force=True)

                f = view_utils.Funcable(text, self.squad)
                a = "aria-current"
                b = await sub.nth(o).get_attribute(a) is not None
                f.disabled = b
                f.args = [tab_number]
                btns[row].append(f)
            row += 1

        players = self.pages[self.index]

        for label, filt, emoji in [
            ("Sort by Squad Number", "squad_number", "#️⃣"),
            ("Sort by Goals", "goals", "⚽"),
            ("Sort by Red Cards", "reds", "🟥"),
            ("Sort by Yellow Cards", "yellows", "🟨"),
            ("Sort by Appearances", "appearances", "👕"),
            ("Sort by Age", "age", None),
            ("Show only injured", "injury", fs.INJURY_EMOJI),
        ]:
            chk = [i for i in players if isinstance(i, fs.Player)]
            if not any(getattr(i, filt) for i in chk):
                continue

            opt = view_utils.Funcable(label, self.squad, [], emoji=emoji)

            tab = tab_number
            opt.keywords = {
                "tab_number": tab,
                "sort": filt,
                "clear_index": True,
            }
            opt.disabled = sort == filt
            try:
                btns[row].append(opt)
            except KeyError:
                btns[row] = [opt]

        for k, v in btns.items():
            ph = f"{', '.join([i.label for i in v])}"
            self.add_function_row(v, k, ph)

        # Build our description & Dropdown.
        dropdown = []
        for i in players:
            if isinstance(i, str):
                e.description += f"{i}\n"
                continue

            text = []

            # First Item:
            if sort:
                first = str(getattr(i, sort))
                text.append(f"`{str(first).rjust(2)}.`")

            sqd = i.squad_number
            if sqd:  # We don't want an empty squad number.
                text.append(f"`{str(sqd).rjust(2)}.`")

            text.append(i.flag)
            text.append(i.markdown)

            if sort != "age":
                text.append(f"({i.age})")

            attrs = []
            for attr, emoji in [
                ("appearances", "👕"),
                ("goals", "⚽"),
                ("reds", "🟥"),
                ("🟨", "yellows"),
            ]:
                if sort != attr and getattr(i, attr):
                    attrs.append(f"{emoji} {attr}")

            if attrs:
                text.append(f'`{" ".join(attrs)}`')

            if i.injury:
                text.append(f"\n{fs.INJURY_EMOJI} *{i.injury}*")

            flag = i.flag
            parent = view_utils.FuncButton(self.squad, emoji="🏃‍♂️")
            v = PlayerView(self.interaction, i, parent=parent).update
            dropdown.append(view_utils.Funcable(i.name, v, emoji=flag))

        self._cached_function = self.squad

        edit = self.interaction.edit_original_response
        return await edit(embed=e, view=self, attachments=[])

    # Team only
    async def transfers(
        self,
        click_number: int = 0,
        label: typing.Optional[str] = "All",
        clear_index: bool = False,
    ) -> discord.InteractionMessage:
        """Get a list of the team's recent transfers."""
        if not isinstance(self, TeamView):
            raise NotImplementedError

        if clear_index:
            self.index = 0

        e = await self.object.base_embed()
        e = e.copy()
        e.description = ""
        e.title = f"Transfers ({label})"

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        e.url = f"{self.object.url}/transfers/"
        await self.page.goto(e.url, timeout=5000)
        await self.page.wait_for_selector("section#transfers", timeout=5000)

        tree = html.fromstring(await self.page.inner_html(".transferTab"))
        players: list[fs.Player] = []
        teams: list[fs.Team] = []
        embed_rows: list[str] = []
        for elem in tree.xpath('.//div[@class="transferTab__row"]'):
            xpath = './/div[@class="transferTab__season"]/text()'
            date = "".join(elem.xpath(xpath))
            date = datetime.datetime.strptime(date, "%d.%m.%Y")
            date = timed_events.Timestamp(date).date

            xpath = './/div[contains(@class, "team--from")]/div/a'
            name = "".join(elem.xpath(xpath + "/text()"))
            link = fs.FLASHSCORE + "".join(elem.xpath(xpath + "/@href"))

            try:
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            player = fs.Player(forename, surname, link)
            player.country = elem.xpath('.//span[@class="flag"]/@title')
            players.append(player)

            pmd = player.markdown

            inbound = "".join(elem.xpath(".//svg[1]/@class"))
            if "icon--in" in inbound:
                emoji = fs.INBOUND_EMOJI
            else:
                emoji = fs.OUTBOUND_EMOJI

            tf_type = elem.xpath('.//div[@class="transferTab__text"]/text()')
            tf_type = "".join(tf_type)

            xpath = './/div[contains(@class, "team--to")]/div/a'
            team_name = "".join(elem.xpath(xpath + "/text()"))
            if team_name:
                tm_lnk = fs.FLASHSCORE + "".join(elem.xpath(xpath + "/@href"))

                team_id = tm_lnk.split("/")[-2]
                team = self.bot.get_team(team_id)
                if team is None:
                    team = fs.Team(team_id, team_name, tm_lnk)

                player.team = team
                teams.append(team)

                tmd = team.markdown
            else:
                tmd = "Free Agent"

            embed_rows.append(f"{pmd} {emoji} {tmd}\n{date} {tf_type}\n")

        self.pages = embed_utils.rows_to_embeds(e, embed_rows, 5)
        row = await self.handle_tabs()

        tf_buttons = []
        filters = self.page.locator("button.filter__filter")
        for o in range(await filters.count()):

            text = await filters.nth(o).text_content()
            if o == click_number:
                await filters.nth(o).click(force=True)

            if not text:
                continue

            show_more = self.page.locator("Show more")
            max_clicks = 20
            for _ in range(max_clicks):
                if await show_more.count():
                    await show_more.click()

            a = "filter__filter--selected"
            b = await filters.nth(o).get_attribute(a) is not None
            f = view_utils.Funcable(text, self.transfers, disabled=b)
            f.disabled = b

            try:
                f.args = {
                    0: [0, "All", True],
                    1: [1, "Arrivals", True],
                    2: [2, "Departures", True],
                }[o]
            except KeyError:
                logger.error("Transfers Extra Buttons Found: transf %s", text)
            tf_buttons.append(f)

        self.add_function_row(tf_buttons, row, "Filter Transfers")
        row += 1

        teams = embed_utils.paginate(teams, 5)[self.index]
        players = embed_utils.paginate(players, 5)[self.index]
        embed = self.pages[self.index]

        parent = view_utils.FuncButton(self.transfers)
        parent.emoji = self.object.emoji

        if teams:
            dropdown = []
            for team in teams:
                itr = self.interaction
                v = TeamView(itr, self.page, team, parent=parent)
                func = v.transfers
                f = view_utils.Funcable(team.title, func, emoji="👕")
                f.description = team.url
                dropdown.append(f)
            self.add_function_row(dropdown, row, "Go to Team")

        self._cached_function = self.transfers

        r = self.interaction.edit_original_response
        return await r(embed=embed, view=self, attachments=[])

    # Competition, Fixture, Team
    async def standings(
        self, link: typing.Optional[str] = None
    ) -> discord.InteractionMessage:
        """Send Specified Table to view"""
        self.pages = []  # discard.

        e = await self.object.base_embed()
        e.title = "Standings"

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        # Link is an optional passed in override fetched by the
        # buttons themselves.
        e.url = link if link else f"{self.object.url}standings/"
        await self.page.goto(e.url, timeout=5000)

        # Chaining Locators is fucking aids.
        # Thank you for coming to my ted talk.
        inner = self.page.locator(".tableWrapper, .draw__wrapper")
        outer = self.page.locator("div", has=inner)
        table_div = self.page.locator("div", has=outer).last

        try:
            await table_div.wait_for(state="visible", timeout=5000)
        except PlayWrightTimeoutError:
            # Entry point not handled on fixtures from leagues.
            logger.error("Failed to find standings on %s", e.url)
            await self.handle_tabs()
            edit = self.interaction.edit_original_response
            e.description = "❌ No Standings Available"
            await edit(embed=e, view=self)

        row = await self.handle_tabs()
        rows = {}

        loc = self.page.locator(".subTabs")
        for i in range(await loc.count()):
            rows[row] = []

            sub = loc.nth(i).locator("a")
            for o in range(await sub.count()):

                text = await sub.nth(o).text_content()

                if not text:
                    continue

                url = await sub.nth(o).get_attribute("href")
                f = view_utils.Funcable(text, self.standings)
                a = "aria-current"
                b = await sub.nth(o).get_attribute(a) is not None
                f.disabled = b
                f.args = [f"{self.object.url}/standings/{url}"]
                rows[row].append(f)
            row += 1

        for k, v in rows.items():
            ph = f"{', '.join([i.label for i in v])}"
            self.add_function_row(v, k, ph)

        await self.page.eval_on_selector_all(fs.ADS, JS)
        image = await table_div.screenshot(type="png")
        file = discord.File(fp=io.BytesIO(image), filename="standings.png")

        e.set_image(url="attachment://standings.png")

        edit = self.interaction.edit_original_response
        return await edit(embed=e, attachments=[file], view=self)

    # Fixture Only
    async def stats(self, half: int = 0) -> discord.InteractionMessage:
        """Push Stats to View"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        e = await self.fixture.base_embed()

        try:
            e.title = {
                0: "Stats",
                1: "First Half Stats",
                2: "Second Half Stats",
            }[half]
        except KeyError:
            uri = self.fixture.url
            logger.error("bad Half %s fixture %s", half, uri)

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        lnk = self.fixture.url
        e.url = f"{lnk}#/match-summary/match-statistics/{half}"
        await self.page.goto(e.url, timeout=5000)
        await self.page.wait_for_selector(".section", timeout=5000)
        src = await self.page.inner_html(".section")

        row = await self.handle_tabs()
        rows = {}

        loc = self.page.locator(".subTabs")
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

    # Fixture Only
    async def summary(self) -> discord.InteractionMessage:
        """Fetch the summary of a Fixture as a text formatted embed"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        await self.fixture.refresh(self.bot)
        e = await self.fixture.base_embed()

        e.description = "\n".join(str(i) for i in self.fixture.events)
        if self.fixture.referee:
            e.description += f"**Referee**: {self.fixture.referee}\n"
        if self.fixture.stadium:
            e.description += f"**Venue**: {self.fixture.stadium}\n"
        if self.fixture.attendance:
            e.description += f"**Attendance**: {self.fixture.attendance}\n"

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        e.url = f"{self.fixture.url}#/match-summary/"
        await self.page.goto(e.url, timeout=5000)
        await self.handle_tabs()

        r = self.interaction.edit_original_response
        return await r(embed=e, attachments=[], view=self)

    # Fixture Only
    async def video(self) -> discord.InteractionMessage:
        """Highlights and other shit."""
        if not isinstance(self, FixtureView):
            raise

        # e.url = f"{self.fixture.link}#/video"
        url = f"{self.object.url}#/video"
        await self.page.goto(url, timeout=5000)
        await self.handle_tabs()

        # e.title = "Videos"
        # loc = '.keyMoments'
        # video = (await page.locator(loc).inner_text()).title()
        url = await self.page.locator("object").get_attribute("data")
        # OLD: https://www.youtube.com/embed/GUH3NIIGbpo
        # NEW: https://www.youtube.com/watch?v=GUH3NIIGbpo
        if url is not None:
            url = url.replace("embed/", "watch?v=")

        # e.description = f"[{video}]({video_url})"
        r = self.interaction.edit_original_response
        return await r(content=url, embed=None, attachments=[], view=self)

    async def update(self) -> discord.InteractionMessage:
        """Use this to paginate."""
        # Remove our bottom row.
        if self._cached_function is not None:
            return await self._cached_function()

        for i in self.children:
            if i.row == 0:
                self.remove_item(i)
        self.add_page_buttons()
        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = self.pages[-1]

        await self.handle_tabs()

        edit = self.interaction.edit_original_response
        return await edit(content=None, embed=embed, attachments=[], view=self)


class CompetitionView(ItemView):
    """The view sent to a user about a Competition"""

    bot: Bot

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        page: Page,
        competition: fs.Competition,
        **kwargs,
    ) -> None:

        self.competition: fs.Competition = competition
        super().__init__(interaction, page, **kwargs)


class FixtureView(ItemView):
    """The View sent to users about a fixture."""

    bot: Bot
    interaction: discord.Interaction[Bot]

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        page: Page,
        fixture: fs.Fixture,
        **kwargs,
    ) -> None:
        self.fixture: fs.Fixture = fixture
        super().__init__(interaction, page, **kwargs)

    # fixture.news
    async def news(self) -> discord.InteractionMessage:
        """Push News to view"""
        e = await self.fixture.base_embed()
        e.title = "News"
        e.description = ""

        if self.page is None:
            self.page = await self.bot.browser.new_page()

        e.url = f"{self.fixture.url}#/news"
        await self.page.goto(e.url, timeout=5000)
        await self.handle_tabs()
        loc = ".container__detail"
        tree = html.fromstring(await self.page.inner_html(loc))

        row: html.HtmlEntity
        for row in tree.xpath('.//a | .//div[@class="section__title"]'):
            logging.info("Iterating row")
            if "section__title" in row.classes:
                header = row.xpath(".//text()")[0]
                logger.info(f"News -- Header Detected. {header}")
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


class TeamView(ItemView):
    """The View sent to a user about a Team"""

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        page: Page,
        team: fs.Team,
        **kwargs,
    ) -> None:
        super().__init__(interaction, page, **kwargs)
        self.team: fs.Team = team

    # Team.news
    async def news(self) -> discord.InteractionMessage:
        """Get a list of news articles related to a team in embed format"""
        if self.page is None:
            self.page = await self.bot.browser.new_page()

        await self.page.goto(f"{self.team.url}/news", timeout=5000)
        locator = self.page.locator(".matchBox").nth(0)
        await locator.wait_for()
        await self.handle_tabs()
        tree = html.fromstring(await locator.inner_html())

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


class PlayerView(view_utils.BaseView):
    bot: Bot

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        player: fs.Player,
        **kwargs,
    ):
        super().__init__(interaction, **kwargs)
        self.player: fs.Player = player

    async def update(self) -> discord.InteractionMessage:
        r = self.interaction.edit_original_response
        return await r(content="Coming Soon!")


class CompetitionSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(
        self, ctx: discord.Interaction[Bot], comps: list[fs.Competition]
    ) -> None:
        super().__init__(ctx)

        self.comps: list[fs.Competition] = comps

        # Pagination
        p = [self.comps[i : i + 25] for i in range(0, len(self.comps), 25)]
        self.pages: list[list[fs.Competition]] = p

    async def update(self) -> discord.InteractionMessage:
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
        r = self.interaction.edit_original_response
        return await r(embed=e, view=self)


class TeamSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(
        self, interaction: discord.Interaction[Bot], teams: list[fs.Team]
    ) -> None:
        super().__init__(interaction)

        self.teams: list[fs.Team] = teams
        p = [self.teams[i : i + 25] for i in range(0, len(self.teams), 25)]
        self.pages: list[list[fs.Team]] = p

    async def update(self) -> discord.InteractionMessage:
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
        r = self.interaction.edit_original_response
        return await r(embed=e, view=self)


class FixtureSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(
        self, interaction: discord.Interaction[Bot], fixtures: list[fs.Fixture]
    ):
        super().__init__(interaction)

        # Pagination
        self.fixtures: list[fs.Fixture] = fixtures

        p = [fixtures[i : i + 25] for i in range(0, len(fixtures), 25)]
        self.pages: list[list[fs.Fixture]] = p

        # Final result
        self.value: typing.Any = None  # As Yet Unset

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


class NationalityFilter(discord.ui.Button):
    view: ItemView

    def __init__(
        self, interaction: discord.Interaction[Bot], players: list[fs.Player]
    ):
        super().__init__(row=4, label="Filter by Nationality", emoji="🌍")
        self.players: list[fs.Player] = players
        self.interaction: discord.Interaction[Bot] = interaction

    async def callback(self, interaction: discord.Interaction[Bot]
                       ) -> discord.InteractionMessage:
        await interaction.response.defer()
        nations = set(i.country[0] for i in self.players)

        opts = []
        for i in sorted(nations):
            flg = flags.get_flag(i)
            opts.append(discord.SelectOption(label=i, emoji=flg, value=i))

        view = view_utils.PagedItemSelect(self.interaction, opts)
        await view.update()

        await view.wait()

        link = self.view.page.url

        return await self.view.top_scorers(link, True, nat_filter=view.values)


class TeamFilter(discord.ui.Button):
    view: ItemView

    def __init__(
        self, interaction: discord.Interaction[Bot], players: list[fs.Player]
    ):
        super().__init__(row=4, label="Filter by Team", emoji="👕")
        self.players: list[fs.Player] = players
        self.interaction: discord.Interaction[Bot] = interaction

    async def callback(self, interaction: discord.Interaction[Bot]
                       ) -> discord.InteractionMessage:
        await interaction.response.defer()
        teams = set(i.team.name for i in self.players if i.team)

        opts = []
        for i in sorted(teams):
            opts.append(discord.SelectOption(label=i, emoji="👕", value=i))

        view = view_utils.PagedItemSelect(self.interaction, opts)
        await view.update()

        await view.wait()

        link = self.view.page.url

        logger.info("Sending Team filter of %s to view", view.values)
        return await self.view.top_scorers(link, True, tm_filter=view.values)


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        importlib.reload(fs)
        importlib.reload(view_utils)
        importlib.reload(image_utils)
        importlib.reload(timed_events)
        importlib.reload(embed_utils)

    async def cog_load(self) -> None:
        """When cog loads, load up our defaults cache"""
        await self.update_cache()

    async def update_cache(self) -> None:
        """Cache our fixture defaults."""
        sql = """SELECT * FROM FIXTURES_DEFAULTS"""
        async with self.bot.db.acquire(timeout=10) as connection:
            async with connection.transaction():
                rows = await connection.fetch(sql)

        self.bot.fixture_defaults = rows

    # Group Commands for those with multiple available subcommands.
    default = discord.app_commands.Group(
        name="default",
        guild_only=True,
        description="Set the server's default team and competition.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @default.command(name="team")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def d_team(
        self,
        interaction: discord.Interaction[Bot],
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> discord.InteractionMessage:
        """Set the default team for your flashscore lookups"""
        e = await team.base_embed()
        e.description = f"Commands will use {team.markdown} as default team"

        if interaction.guild is None:
            raise

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id)
                         VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, interaction.guild.id)

                q = """INSERT INTO fixtures_defaults (guild_id, default_team)
                       VALUES ($1,$2) ON CONFLICT (guild_id)
                       DO UPDATE SET default_team = $2
                       WHERE excluded.guild_id = $1"""
                await connection.execute(q, interaction.guild.id, team.id)
        return await interaction.edit_original_response(embed=e)

    @default.command(name="competition")
    @discord.app_commands.describe(competition=COMPETITION)
    async def d_comp(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> None:
        """Set the default competition for your flashscore lookups"""
        if interaction.guild is None:
            raise
        fsr = competition
        q = """INSERT INTO fixtures_defaults (guild_id, default_league)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET default_league = $2
                WHERE excluded.guild_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, interaction.guild.id, fsr.id)

        e = await fsr.base_embed()
        e.description = f"Default Competition is now {fsr.markdown}"
        await interaction.edit_original_response(embed=e)

    match = discord.app_commands.Group(
        name="match",
        description="Get information about a match from flashscore",
    )

    # FIXTURE commands
    @match.command(name="table")
    @discord.app_commands.describe(match=FIXTURE)
    async def fx_table(
        self,
        interaction: discord.Interaction[Bot],
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> discord.InteractionMessage:
        """Look up the table for a fixture."""
        page = await self.bot.browser.new_page()
        return await FixtureView(interaction, page, match).standings()

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def stats(
        self,
        interaction: discord.Interaction[Bot],
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> discord.InteractionMessage:
        """Look up the stats for a fixture."""
        page = await self.bot.browser.new_page()
        return await FixtureView(interaction, page, match).stats()

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def lineups(
        self,
        interaction: discord.Interaction[Bot],
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> discord.InteractionMessage:
        """Look up the lineups and/or formations for a Fixture."""
        page = await self.bot.browser.new_page()
        return await FixtureView(interaction, page, match).lineups()

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def summary(
        self,
        interaction: discord.Interaction[Bot],
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> discord.InteractionMessage:
        """Get a summary for a fixture"""
        page = await self.bot.browser.new_page()
        return await FixtureView(interaction, page, match).summary()

    @match.command(name="h2h")
    @discord.app_commands.describe(match=FIXTURE)
    async def h2h(
        self,
        interaction: discord.Interaction[Bot],
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> discord.InteractionMessage:
        """Lookup the head-to-head details for a Fixture"""
        page = await self.bot.browser.new_page()
        return await FixtureView(interaction, page, match).h2h()

    team = discord.app_commands.Group(
        name="team", description="Get information about a team "
    )

    @team.command(name="fixtures")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_fixtures(
        self,
        interaction: discord.Interaction[Bot],
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> discord.InteractionMessage:
        """Fetch upcoming fixtures for a team."""
        page = await self.bot.browser.new_page()
        return await TeamView(interaction, page, team).fixtures()

    @team.command(name="results")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_results(
        self,
        interaction: discord.Interaction[Bot],
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> discord.InteractionMessage:
        """Get recent results for a Team"""
        page = await self.bot.browser.new_page()
        return await TeamView(interaction, page, team).results()

    @team.command(name="table")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_table(
        self,
        interaction: discord.Interaction[Bot],
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> discord.InteractionMessage:
        """Get the Table of one of a Team's competitions"""
        page = await self.bot.browser.new_page()
        return await TeamView(interaction, page, team).standings()

    @team.command(name="news")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_news(
        self,
        interaction: discord.Interaction[Bot],
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> discord.InteractionMessage:
        """Get the latest news for a team"""
        page = await self.bot.browser.new_page()
        return await TeamView(interaction, page, team).news()

    @team.command(name="squad")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_squad(
        self,
        interaction: discord.Interaction[Bot],
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> discord.InteractionMessage:
        """Lookup a team's squad members"""
        page = await self.bot.browser.new_page()
        return await TeamView(interaction, page, team).squad()

    league = discord.app_commands.Group(
        name="competition",
        description="Get information about a competition from flashscore",
    )

    @league.command(name="fixtures")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_fixtures(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> discord.InteractionMessage:
        """Fetch upcoming fixtures for a competition."""
        page = await self.bot.browser.new_page()
        return await CompetitionView(interaction, page, competition).fixtures()

    @league.command(name="results")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_results(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> discord.InteractionMessage:
        """Get recent results for a competition"""
        page = await self.bot.browser.new_page()
        return await CompetitionView(interaction, page, competition).results()

    @league.command(name="top_scorers")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_scorers(
        self,
        ctx: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> discord.InteractionMessage:
        """Get top scorers from a competition."""
        page = await self.bot.browser.new_page()
        return await CompetitionView(ctx, page, competition).top_scorers()

    @league.command(name="table")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_table(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> discord.InteractionMessage:
        """Get the Table of a competition"""
        page = await self.bot.browser.new_page()
        return await CompetitionView(
            interaction, page, competition
        ).standings()

    @discord.app_commands.command()
    async def scores(
        self,
        interaction: discord.Interaction[Bot],
    ) -> discord.InteractionMessage:
        """Fetch current scores for a specified competition,
        or if no competition is provided, all live games."""
        await interaction.response.defer(thinking=True)
        if not self.bot.games:
            return await self.bot.error(interaction, "No live games found")

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
        return await view_utils.Paginator(interaction, embeds).update()


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
