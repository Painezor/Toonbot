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

import discord
from discord.ext import commands
from lxml import html
from playwright.async_api import Page, TimeoutError as PlayWrightTimeoutError

import ext.flashscore as fs
from ext.utils import view_utils, embed_utils, image_utils, timed_events, flags

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]


logger = logging.getLogger("Fixtures")

JS = "ads => ads.forEach(x => x.remove());"
TEAM_NAME = "Enter the name of a team to search for"
FIXTURE = "Search for a fixture by team name"
COMPETITION = "Enter the name of a competition to search for"
H2H = typing.Literal["overall", "home", "away"]


async def set_default(
    interaction: Interaction,
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
    interaction: Interaction, fsr: fs.Competition | fs.Team
):
    """Allow the user to choose from the most recent games of a fixture"""
    fixtures = await fs.parse_games(interaction.client, fsr, "/results/")
    await (view := FixtureSelect(fixtures)).update(interaction)
    await view.wait()
    return next(i for i in fixtures if i.score_line == view.value[0])


# Autocompletes
class FixtureTransformer(discord.app_commands.Transformer):
    """Convert User Input to a fixture Object"""

    async def autocomplete(
        self, interaction: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Check if user's typing is in list of live games"""
        cur = current.casefold()

        choices = []
        for i in interaction.client.games:
            ac_row = i.ac_row.casefold()
            if cur and cur not in ac_row:
                continue

            if i.id is None:
                continue

            name = i.ac_row[:100]
            choice = discord.app_commands.Choice(name=name, value=i.id)

            choices.append(choice)

            if len(choices) == 25:
                break

        if current:
            search = f"🔎 Search for '{current}'"
            srch = [discord.app_commands.Choice(name=search, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[fs.Fixture]:
        await interaction.response.defer(thinking=True)

        if fix := interaction.client.get_fixture(value):
            return fix

        if not (fsr := interaction.client.get_team(value)):
            teams = await fs.search(value, "team", interaction)
            teams = typing.cast(list[fs.Team], teams)

            await (view := TeamSelect(teams)).update(interaction)
            await view.wait()

            if not view.value:
                return None
            fsr = next(i for i in teams if i.id == view.value[0])
        return await choose_recent_fixture(interaction, fsr)


class TeamTransformer(discord.app_commands.Transformer):
    """Convert user Input to a Team Object"""

    async def autocomplete(
        self,
        interaction: Interaction,
        current: str,
        /,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored teams"""
        teams = interaction.client.teams
        teams: list[fs.Team] = sorted(teams, key=lambda x: x.name)

        # Run Once - Set Default for interaction.
        if "default" not in interaction.extras:
            await set_default(interaction, "default_team")

        curr = current.casefold()

        choices = []
        for i in teams:
            if i.id is None:
                continue

            if curr not in i.title.casefold():
                continue

            choice = discord.app_commands.Choice(name=i.name[:100], value=i.id)
            choices.append(choice)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices

        if current:
            search = f"🔎 Search for '{current}'"
            srch = [discord.app_commands.Choice(name=search, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[fs.Team]:
        await interaction.response.defer(thinking=True)

        if fsr := interaction.client.get_team(value):
            return fsr

        teams = await fs.search(value, "team", interaction)
        teams = typing.cast(list[fs.Team], teams)

        await (view := TeamSelect(teams)).update(interaction)
        await view.wait()

        if not view.value:
            return None
        return next(i for i in teams if i.id == view.value[0])


class CompetitionTransformer(discord.app_commands.Transformer):
    """Converts user input to a Competition object"""

    async def autocomplete(
        self,
        interaction: Interaction,
        current: str,
        /,
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored competitions"""
        lgs = sorted(interaction.client.competitions, key=lambda x: x.title)

        if "default" not in interaction.extras:
            await set_default(interaction, "default_league")

        curr = current.casefold()

        choices = []

        for i in lgs:
            if curr not in i.title.casefold() or i.id is None:
                continue

            opt = discord.app_commands.Choice(name=i.title[:100], value=i.id)

            choices.append(opt)

            if len(choices) == 25:
                break

        if interaction.extras["default"] is not None:
            choices = [interaction.extras["default"]] + choices[:24]

        if current:
            search = f"🔎 Search for '{current}'"
            srch = [discord.app_commands.Choice(name=search, value=current)]
            choices = choices[:24] + srch
        return choices

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[fs.Competition]:
        await interaction.response.defer(thinking=True)

        if fsr := interaction.client.get_competition(value):
            return fsr

        if "http" in value:
            return await fs.Competition.by_link(interaction.client, value)

        comps = await fs.search(value, "comp", interaction)
        comps = typing.cast(list[fs.Competition], comps)

        await (view := CompetitionSelect(comps)).update(interaction)
        await view.wait()

        if not view.value:
            return None
        return next(i for i in comps if i.id == view.value[0])


# Searching
class ItemView(view_utils.BaseView):
    """A Generic for Fixture/Team/Competition Views"""

    def __init__(self, page: Page, **kwargs) -> None:
        super().__init__(**kwargs)

        self.page: Page = page

        # For Functions that require pagination over multiple items
        # we don't use the generic "update".
        self._cached_function: typing.Optional[typing.Callable] = None

    @property
    def object(self) -> fs.Team | fs.Competition | fs.Fixture:
        """Return the underlying object of the parent class"""
        if isinstance(self, TeamView):
            return self.team
        elif isinstance(self, FixtureView):
            return self.fixture
        elif isinstance(self, CompetitionView):
            return self.object
        else:
            raise TypeError

    async def on_timeout(self) -> None:
        if not self.page.is_closed():
            await self.page.close()
        await super().on_timeout()

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

            num = await (sub_loc := loc.nth(i).locator("a")).count()
            for count in range(num):
                text = await sub_loc.nth(count).text_content()

                if not text:
                    continue

                link = await sub_loc.nth(count).get_attribute("href")

                if text == "Archive":
                    btn = view_utils.Funcable(text, self.archive)
                    btn.description = "Previous Season Results"
                    btn.emoji = "🗄️"

                elif text == "Fixtures":
                    btn = view_utils.Funcable(text, self.fixtures)
                    btn.description = "Upcoming Fixtures"
                    btn.emoji = "🗓️"

                elif text == "H2H":
                    btn = view_utils.Funcable(text, self.h2h)
                    btn.description = "Head to Head Data"
                    btn.emoji = "⚔"

                elif text == "Lineups":
                    btn = view_utils.Funcable(text, self.lineups)
                    btn.emoji = "🧑‍🤝‍🧑"

                elif text == "News":
                    btn = view_utils.Funcable(text, self.news)
                    btn.emoji = "📰"

                elif text == "Photos":
                    btn = view_utils.Funcable(text, self.photos)
                    btn.emoji = "📷"
                    btn.style = discord.ButtonStyle.red

                elif text == "Report":
                    btn = view_utils.Funcable(text, self.report)
                    btn.emoji = "📰"

                elif text == "Results":
                    btn = view_utils.Funcable(text, self.results)
                    btn.description = "Recent Results"
                    btn.emoji = "📋"

                elif text == "Standings":
                    btn = view_utils.Funcable(text, self.standings)
                    btn.description = "Current League Table"
                    btn.emoji = "🏅"

                elif text in ["Form", "HT/FT", "Live Standings", "Over/Under"]:
                    btn = view_utils.Funcable(text, self.standings)
                    btn.emoji = "🏅"

                    if link:
                        link = f"{self.object.url}standings/{link}"
                    btn.args = [link]

                elif text == "Squad":
                    btn = view_utils.Funcable(text, self.squad)
                    btn.description = "Team Squad Members"
                    btn.emoji = "🧑‍🤝‍🧑"

                elif text == "Stats":
                    btn = view_utils.Funcable(text, self.stats)
                    btn.emoji = "📊"

                elif text in ["Summary", "Match"]:
                    if not isinstance(self, FixtureView):
                        continue  # Summary is garbage on everything else.

                    btn = view_utils.Funcable(text, self.summary)
                    btn.description = "A list of match events"

                elif text == "Odds":
                    # Let's not support gambling.
                    # Unless I get an affiliate link ...
                    continue

                elif text == "Top Scorers":
                    btn = view_utils.Funcable(text, self.top_scorers)
                    btn.emoji = "⚽"
                    btn.args = [f"{self.object.url}/standings/{link}"]
                    btn.style = discord.ButtonStyle.red

                elif text == "Transfers":
                    btn = view_utils.Funcable(text, self.transfers)
                    btn.style = discord.ButtonStyle.red
                    btn.description = "Recent Transfers"
                    btn.emoji = "<:inbound:1079808760194814014>"

                elif text == "Video":
                    btn = view_utils.Funcable(text, self.video)
                    btn.emoji = "📹"
                    btn.description = "Videos and Highlights"

                else:
                    logger.info("%s found extra tab %s", type(self), text)
                    continue

                if row == 1 and btn.style is None:
                    btn.style = discord.ButtonStyle.blurple

                aria = "aria-current"
                dis = await sub_loc.nth(count).get_attribute(aria) is not None
                btn.disabled = dis

                rows[row].append(btn)
            row += 1

        for k, value in rows.items():
            placeholder = f"{', '.join([i.label for i in value])}"
            self.add_function_row(value, k, placeholder)
        return row

    async def archive(self, interaction: Interaction) -> None:
        """Get a list of Archives for a competition"""
        if not isinstance(self, CompetitionView):
            raise NotImplementedError

        if self._cached_function is not self.archive:
            self.index = 0

        await self.page.goto(f"{self.object.url}/archive/")
        row = await self.handle_tabs()

        embed = await self.object.base_embed()
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

            country = self.object.country
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
            view = CompetitionView(self.page, comp, parent=parent)
            func = view.standings
            args = [interaction]
            lg_dropdown.append(
                view_utils.Funcable(comp.title, func, args, emoji="🏆")
            )

        if lg_dropdown:
            self.add_function_row(lg_dropdown, row, "View Season")
            row += 1

        tm_dropdown: list[view_utils.Funcable] = []
        args = [interaction]
        for team in set(teams):
            func = TeamView(self.page, team, parent=parent).fixtures
            btn = view_utils.Funcable(team.name, func, args, emoji="👕")
            tm_dropdown.append(btn)

        if tm_dropdown:
            self.add_function_row(tm_dropdown, row, "View Team")
            row += 1

        self._cached_function = self.archive
        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self, attachments=[])

    # Fixture Only
    async def h2h(
        self, interaction: Interaction, team: H2H = "overall"
    ) -> None:
        """Get results of recent games for each team in the fixture"""
        if not isinstance(self, FixtureView):
            raise TypeError

        embed = await self.object.base_embed()
        embed.description = embed.description or ""

        assert isinstance(self.object, fs.Fixture)

        embed.title = {
            "overall": "Head to Head: Overall",
            "home": f"Head to Head: {self.object.home.name} at Home",
            "away": f"Head to Head: {self.object.away.name} Away",
        }[team]

        embed.url = f"{self.object.url}/#/h2h/{team}"
        await self.page.goto(embed.url, timeout=5000)
        await self.page.wait_for_selector(".h2h", timeout=5000)
        row = await self.handle_tabs()
        rows = {}

        locator = self.page.locator(".subTabs")

        for i in range(await locator.count()):
            rows[row] = []

            sub_loc = locator.nth(i).locator("a")

            for count in range(await sub_loc.count()):
                text = await sub_loc.nth(count).text_content()
                if not text:
                    continue

                aria = "aria-current"
                dis = await sub_loc.nth(count).get_attribute(aria) is not None
                btn = view_utils.Funcable(text, self.h2h, disabled=dis)
                btn.disabled = dis
                btn.args = {0: ["overall"], 1: ["home"], 2: ["away"]}[count]
                rows[row].append(btn)
            row += 1

        for k, value in rows.items():
            placeholder = f"{', '.join([i.label for i in value])}"
            self.add_function_row(value, k, placeholder)

        tree = html.fromstring(await self.page.inner_html(".h2h"))

        game: html.HtmlElement
        xpath = './/div[@class="rows" or @class="section__title"]'

        for row in tree.xpath(xpath):
            if "section__title" in row.classes:
                header = row.xpath(".//text()")[0]
                embed.description += f"\n**{header}**\n"
                continue

            for game in row:
                xpath = './/span[contains(@class, "homeParticipant")]//text()'
                home = "".join(game.xpath(xpath)).strip().title()

                xpath = './/span[contains(@class, "awayParticipant")]//text()'
                away = "".join(game.xpath(xpath)).strip().title()

                # Compare HOME team of H2H fixture to base fixture.
                xpath = './/span[contains(@class, "date")]/text()'
                k_o = game.xpath(xpath)[0].strip()
                k_o = datetime.datetime.strptime(k_o, "%d.%m.%y")
                k_o = timed_events.Timestamp(k_o).relative

                try:
                    tms = game.xpath('.//span[@class="h2h__result"]//text()')
                    tms = f"{tms[0]} - {tms[1]}"
                    # Directly set the private var to avoid the score setter.
                    embed.description += f"{k_o} {home} {tms} {away}\n"
                except ValueError:
                    txt = game.xpath('.//span[@class="h2h__result"]//text()')
                    logger.error("ValueError trying to split string, %s", txt)
                    embed.description += f"{k_o} {home} {txt} {away}\n"

        if not embed.description:
            embed.description = (
                "Could not find Head to Head Data for this game"
            )

        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=[], view=self)

    # Competition, Team
    async def fixtures(self, interaction: Interaction) -> None:
        """Push upcoming competition fixtures to View"""
        if isinstance(self, FixtureView):
            raise NotImplementedError

        if isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        rows = await fs.parse_games(
            interaction.client, self.object, "/fixtures/"
        )
        rows = [i.upcoming for i in rows] if rows else ["No Fixtures Found :("]

        embed = await self.object.base_embed()

        embed.title = "Fixtures"
        embed.url = f"{self.object.url}/fixtures"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._cached_function = None
        return await self.update(interaction)

    # Fixture Only
    async def lineups(self, interaction: Interaction) -> None:
        """Push Lineups & Formations Image to view"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.object.base_embed()
        embed.title = "Lineups and Formations"

        embed.url = f"{self.object.url}#/match-summary/lineups"
        await self.page.goto(embed.url, timeout=5000)
        await self.page.eval_on_selector_all(fs.ADS, JS)
        screenshots = []

        if await (formation := self.page.locator(".lf__fieldWrap")).count():
            screenshots.append(io.BytesIO(await formation.screenshot()))

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
        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=file, view=self)

    # Fixture Only
    async def photos(self, interaction: Interaction) -> None:
        """Push Photos to view"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.object.base_embed()
        embed.title = "Photos"
        embed.url = f"{self.object.url}#/photos"

        await self.page.goto(embed.url)
        body = self.page.locator(".section")

        await body.wait_for()
        tree = html.fromstring(await body.inner_html())

        images = tree.xpath('.//div[@class="photoreportInner"]')

        self.pages = []
        for i in images:
            embed = embed.copy()
            image = "".join(i.xpath(".//img/@src"))
            embed.set_image(url=image)
            xpath = './/div[@class="liveComment"]/text()'
            embed.description = "".join(i.xpath(xpath))
            self.pages.append(embed)

        self._cached_function = None
        self.index = 0  # Pagination is handled purely by update()
        return await self.update(interaction)

    # Subclassed on Fixture & Team
    async def news(self, interaction: Interaction) -> None:
        """Get News for a Fixture or Team"""
        raise NotImplementedError  # This is subclassed.

    # Fixture Only
    async def report(self, interaction: Interaction) -> None:
        """Get the report in text format."""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.object.base_embed()

        embed.url = f"{self.object.url}#/report/"
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
        return await self.update(interaction)

    # Competition, Team
    async def results(self, interaction: Interaction) -> None:
        """Push Previous Results Team View"""
        if isinstance(self, FixtureView):
            # This one actually invalidates properly if we're using an "old"
            # fs.Fixture object
            raise NotImplementedError

        if isinstance(self.object, fs.Fixture):
            # This one just unfucks the typechecking for self.object.
            raise NotImplementedError  # No.

        rows = await fs.parse_games(
            interaction.client, self.object, "/results/"
        )

        rows = [i.finished for i in rows] if rows else ["No Results Found :("]
        embed = await self.object.base_embed()
        embed = embed.copy()
        embed.title = "Results"

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._cached_function = None
        await self.handle_tabs()
        return await self.update(interaction)

    # Competition, Fixture, Team
    async def top_scorers(
        self,
        interaction: Interaction,
        link: typing.Optional[str] = None,
        clear_index: bool = False,
        nat_filter: typing.Optional[set[str]] = None,
        tm_filter: typing.Optional[set[str]] = None,
    ) -> None:
        """Push Scorers to View"""
        embed = await self.object.base_embed()

        if clear_index:
            self.index = 0

        if link is None:
            obj = self.object

            # Example link "#/nunhS7Vn/top_scorers"
            # This requires a competition ID, annoyingly.
            link = f"{obj.url}/standings/"

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
        while await btn.count():
            await btn.last.click()

        raw = await tab_class.inner_html()
        tree = html.fromstring(raw)

        players: list[fs.Player] = []

        rows = tree.xpath('.//div[@class="ui-table__body"]/div')

        for i in rows:
            xpath = "./div[1]//text()"
            name = "".join(i.xpath(xpath))

            xpath = "./div[1]//@href"
            url = fs.FLASHSCORE + "".join(i.xpath(xpath))

            player = fs.Player(None, name, url)

            xpath = "./span[1]//text()"
            player.rank = int("".join(i.xpath(xpath)).strip("."))

            xpath = './/span[contains(@class,"flag")]/@title'
            player.country = i.xpath(xpath)

            xpath = './/span[contains(@class, "--goals")]/text()'
            try:
                player.goals = int("".join(i.xpath(xpath)))
            except ValueError:
                pass

            xpath = './/span[contains(@class, "--gray")]/text()'
            try:
                player.assists = int("".join(i.xpath(xpath)))
            except ValueError:
                pass

            team_url = fs.FLASHSCORE + "".join(i.xpath("./a/@href"))
            team_id = team_url.split("/")[-2]

            tmn = "".join(i.xpath("./a/text()"))

            if (team := interaction.client.get_team(team_id)) is None:
                team_link = "".join(i.xpath(".//a/@href"))
                team = fs.Team(team_id, tmn, team_link)

                comp_id = url.split("/")[-2]
                team.competition = interaction.client.get_competition(comp_id)
            else:
                if team.name != tmn:
                    logger.info("Overrode team name %s -> %s", team.name, tmn)
                    team.name = tmn
                    await fs.save_team(interaction.client, team)

            player.team = team

            players.append(player)

        self.add_item(NationalityFilter(players))
        self.add_item(TeamFilter(players))

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
        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self, attachments=[])

    # Team Only
    async def squad(
        self,
        interaction: Interaction,
        tab_number: int = 0,
        sort: typing.Optional[str] = None,
        clear_index: bool = False,
    ) -> None:
        """Get the squad of the team, filter or sort, push to view"""
        if not isinstance(self, TeamView):
            raise TypeError

        # If we're changing the current sort or filter, we reset the index
        # to avoid an index error if we were on a later page and this has
        # fewer items.
        if clear_index:
            self.index = 0

        embed = await self.object.base_embed()
        embed = embed.copy()
        embed.url = f"{self.object.url}/squad"

        embed.title = "Squad1"
        embed.description = ""

        btns = {}

        await self.page.goto(embed.url, timeout=5000)
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

            embed.set_footer(
                text=f"Sorted by {sort.replace('_', ' ').title()}"
            )

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
            for count in range(await sub.count()):
                text = await sub.nth(count).text_content()

                if not text:
                    continue

                if tab_number == count:
                    embed.title += f" ({text})"
                    await sub.nth(count).click(force=True)

                btn = view_utils.Funcable(text, self.squad)
                current = "aria-current"
                dis = await sub.nth(count).get_attribute(current) is not None
                btn.disabled = dis
                btn.args = [tab_number]
                btns[row].append(btn)
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

        for k, val in btns.items():
            placeholder = f"{', '.join([i.label for i in val])}"
            self.add_function_row(val, k, placeholder)

        # Build our description & Dropdown.
        dropdown = []
        for i in players:
            if isinstance(i, str):
                embed.description += f"{i}\n"
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
            val = PlayerView(i, parent=parent).update
            btn = view_utils.Funcable(i.name, val, [interaction], emoji=flag)
            dropdown.append(btn)

        self._cached_function = self.squad

        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self, attachments=[])

    # Team only
    async def transfers(
        self,
        interaction: Interaction,
        click_number: int = 0,
        label: str = "All",
        clear_index: bool = False,
    ) -> None:
        """Get a list of the team's recent transfers."""
        if not isinstance(self, TeamView):
            raise NotImplementedError

        if clear_index:
            self.index = 0

        embed = await self.object.base_embed()
        embed = embed.copy()
        embed.description = ""
        embed.title = f"Transfers ({label})"

        embed.url = f"{self.object.url}/transfers/"
        await self.page.goto(embed.url, timeout=5000)
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
                team = interaction.client.get_team(team_id)
                if team is None:
                    team = fs.Team(team_id, team_name, tm_lnk)

                player.team = team
                teams.append(team)

                tmd = team.markdown
            else:
                tmd = "Free Agent"

            embed_rows.append(f"{pmd} {emoji} {tmd}\n{date} {tf_type}\n")

        self.pages = embed_utils.rows_to_embeds(embed, embed_rows, 5)
        row = await self.handle_tabs()

        tf_buttons = []
        filters = self.page.locator("button.filter__filter")
        for count in range(await filters.count()):
            text = await filters.nth(count).text_content()
            if count == click_number:
                await filters.nth(count).click(force=True)

            if not text:
                continue

            show_more = self.page.locator("Show more")
            max_clicks = 20
            for _ in range(max_clicks):
                if await show_more.count():
                    await show_more.click()

            atr = "filter__filter--selected"
            disable = await filters.nth(count).get_attribute(atr) is not None
            btn = view_utils.Funcable(text, self.transfers, disabled=disable)

            try:
                btn.args = {
                    0: [0, "All", True],
                    1: [1, "Arrivals", True],
                    2: [2, "Departures", True],
                }[count]
            except KeyError:
                logger.error("Transfers Extra Buttons Found: transf %s", text)
            tf_buttons.append(btn)

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
                view = TeamView(self.page, team, parent=parent)
                func = view.transfers
                btn = view_utils.Funcable(team.title, func, emoji="👕")
                btn.args = [interaction]
                btn.description = team.url
                dropdown.append(btn)
            self.add_function_row(dropdown, row, "Go to Team")

        self._cached_function = self.transfers

        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self, attachments=[])

    # Competition, Fixture, Team
    async def standings(
        self,
        interaction: Interaction,
        link: typing.Optional[str] = None,
    ) -> None:
        """Send Specified Table to view"""
        self.pages = []  # discard.

        embed = await self.object.base_embed()
        embed.title = "Standings"

        # Link is an optional passed in override fetched by the
        # buttons themselves.
        if not link:
            link = f"{self.object.url}".rstrip("/") + "/standings/"
        embed.url = link
        await self.page.goto(embed.url, timeout=5000)

        # Chaining Locators is fucking aids.
        # Thank you for coming to my ted talk.
        inner = self.page.locator(".tableWrapper, .draw__wrapper")
        outer = self.page.locator("div", has=inner)
        table_div = self.page.locator("div", has=outer).last

        try:
            await table_div.wait_for(state="visible", timeout=5000)
        except PlayWrightTimeoutError:
            # Entry point not handled on fixtures from leagues.
            logger.error("Failed to find standings on %s", embed.url)
            await self.handle_tabs()
            edit = interaction.response.edit_message
            embed.description = "❌ No Standings Available"
            await edit(embed=embed, view=self)

        row = await self.handle_tabs()
        rows = {}

        loc = self.page.locator(".subTabs")
        for i in range(await loc.count()):
            rows[row] = []

            sub = loc.nth(i).locator("a")
            for count in range(await sub.count()):
                text = await sub.nth(count).text_content()

                if not text:
                    continue

                url = await sub.nth(count).get_attribute("href")
                func = view_utils.Funcable(text, self.standings)
                current = "aria-current"
                dis = await sub.nth(count).get_attribute(current) is not None
                func.disabled = dis
                func.args = [f"{self.object.url}/standings/{url}"]
                rows[row].append(func)
            row += 1

        for k, value in rows.items():
            placeholder = f"{', '.join([i.label for i in value])}"
            self.add_function_row(value, k, placeholder)

        await self.page.eval_on_selector_all(fs.ADS, JS)
        image = await table_div.screenshot(type="png")
        file = discord.File(fp=io.BytesIO(image), filename="standings.png")

        embed.set_image(url="attachment://standings.png")

        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=[file], view=self)

    # Fixture Only
    async def stats(self, interaction: Interaction, half: int = 0) -> None:
        """Push Stats to View"""
        if not isinstance(self, FixtureView):
            raise NotImplementedError

        embed = await self.object.base_embed()

        try:
            embed.title = {
                0: "Stats",
                1: "First Half Stats",
                2: "Second Half Stats",
            }[half]
        except KeyError:
            uri = self.object.url
            logger.error("bad Half %s fixture %s", half, uri)

        lnk = self.object.url
        embed.url = f"{lnk}#/match-summary/match-statistics/{half}"
        await self.page.goto(embed.url, timeout=5000)
        await self.page.wait_for_selector(".section", timeout=5000)
        src = await self.page.inner_html(".section")

        i = await self.handle_tabs()
        rows = {}

        loc = self.page.locator(".subTabs")
        for i in range(await loc.count()):
            rows[i] = []

            sub = loc.nth(i).locator("a")
            for count in range(await sub.count()):
                text = await sub.nth(count).text_content()
                if not text:
                    continue

                btn = view_utils.Funcable(text, self.stats)

                aria = "aria-current"
                disable = await sub.nth(count).get_attribute(aria) is not None
                btn.disabled = disable
                try:
                    btn.args = {
                        "Match": [0],
                        "1st Half": [1],
                        "2nd Half": [2],
                    }[text]
                except KeyError:
                    logger.error("Found extra stats row %s", text)
                rows[i].append(btn)
            i += 1

        for k, val in rows.items():
            placeholder = f"{', '.join([i.label for i in val])}"
            self.add_function_row(val, k, placeholder)

        output = ""
        xpath = './/div[@class="stat__category"]'
        for i in html.fromstring(src).xpath(xpath):
            try:
                hom = i.xpath('.//div[@class="stat__homeValue"]/text()')[0]
                sta = i.xpath('.//div[@class="stat__categoryName"]/text()')[0]
                awa = i.xpath('.//div[@class="stat__awayValue"]/text()')[0]
                output += f"{hom.rjust(4)} [{sta.center(19)}] {awa.ljust(4)}\n"
            except IndexError:
                continue

        if output:
            embed.description = f"```ini\n{output}```"
        else:
            embed.description = "Could not find stats for this game."
        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=[], view=self)

    # Fixture Only
    async def summary(self, interaction: Interaction) -> None:
        """Fetch the summary of a Fixture as a text formatted embed"""
        if not isinstance(self, FixtureView):
            raise TypeError

        assert isinstance(self.object, fs.Fixture)

        await self.object.refresh(interaction.client)
        embed = await self.object.base_embed()

        embed.description = "\n".join(str(i) for i in self.object.events)
        if self.object.referee:
            embed.description += f"**Referee**: {self.object.referee}\n"
        if self.object.stadium:
            embed.description += f"**Venue**: {self.object.stadium}\n"
        if self.object.attendance:
            embed.description += f"**Attendance**: {self.object.attendance}\n"

        embed.url = f"{self.object.url}#/match-summary/"
        await self.page.goto(embed.url, timeout=5000)
        await self.handle_tabs()

        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=[], view=self)

    # Fixture Only
    async def video(self, interaction: Interaction) -> None:
        """Highlights and other shit."""
        if not isinstance(self, FixtureView):
            raise TypeError

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
        edit = interaction.response.edit_message
        return await edit(content=url, embed=None, attachments=[], view=self)

    async def update(self, interaction: Interaction) -> None:
        """Use this to paginate."""
        # Remove our bottom row.
        if self._cached_function is not None:
            return await self._cached_function(interaction)

        for i in self.children:
            if i.row == 0:
                self.remove_item(i)
        self.add_page_buttons()
        try:
            embed = self.pages[self.index]
        except IndexError:
            embed = self.pages[-1]

        await self.handle_tabs()

        edit = interaction.response.edit_message
        return await edit(content=None, embed=embed, attachments=[], view=self)


class CompetitionView(ItemView):
    """The view sent to a user about a Competition"""

    bot: Bot

    def __init__(
        self,
        page: Page,
        competition: fs.Competition,
        **kwargs,
    ) -> None:
        self.object: fs.Competition = competition
        super().__init__(page, **kwargs)

    async def news(self, interaction: Interaction) -> None:
        raise NotImplementedError


class FixtureView(ItemView):
    """The View sent to users about a fixture."""

    def __init__(
        self,
        page: Page,
        fixture: fs.Fixture,
        **kwargs,
    ) -> None:
        self.fixture: fs.Fixture = fixture
        super().__init__(page, **kwargs)

    # fixture.news
    async def news(self, interaction: Interaction) -> None:
        """Push News to view"""
        embed = await self.fixture.base_embed()
        embed.title = "News"
        embed.description = ""

        embed.url = f"{self.fixture.url}#/news"
        await self.page.goto(embed.url, timeout=5000)
        await self.handle_tabs()
        loc = ".container__detail"
        tree = html.fromstring(await self.page.inner_html(loc))

        row: html.HtmlEntity
        for row in tree.xpath('.//a | .//div[@class="section__title"]'):
            logging.info("Iterating row")
            if "section__title" in row.classes:
                header = row.xpath(".//text()")[0]
                logger.info("News -- Header Detected. %s", header)
                embed.description += f"\n**{header}**\n"
                continue
            link = fs.FLASHSCORE + row.xpath(".//@href")[0]
            title = row.xpath('.//div[@class="rssNews__title"]/text()')[0]

            xpath = './/div[@class="rssNews__description"]/text()'
            description: str = row.xpath(xpath)[0]
            time, source = description.split(",")

            fmt = "%d.%m.%Y %H:%M"
            time = datetime.datetime.strptime(time, fmt)
            time = timed_events.Timestamp(time).relative
            embed.description += f"> [{title}]({link})\n{source} {time}\n\n"

        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=[], view=self)


class TeamView(ItemView):
    """The View sent to a user about a Team"""

    def __init__(
        self,
        page: Page,
        team: fs.Team,
        **kwargs,
    ) -> None:
        super().__init__(page, **kwargs)
        self.team: fs.Team = team

    # Team.news
    async def news(self, interaction: Interaction) -> None:
        """Get a list of news articles related to a team in embed format"""
        await self.page.goto(f"{self.team.url}/news", timeout=5000)
        locator = self.page.locator(".matchBox").nth(0)
        await locator.wait_for()
        await self.handle_tabs()
        tree = html.fromstring(await locator.inner_html())

        items = []

        base_embed = await self.team.base_embed()

        for i in tree.xpath('.//div[@class="rssNews"]'):
            embed = base_embed.copy()

            xpath = './/div[@class="rssNews__title"]/text()'
            embed.title = "".join(i.xpath(xpath))

            xpath = ".//a/@href"
            embed.url = fs.FLASHSCORE + "".join(i.xpath(xpath))

            embed.set_image(url="".join(i.xpath(".//img/@src")))

            xpath = './/div[@class="rssNews__perex"]/text()'
            embed.description = "".join(i.xpath(xpath))

            xpath = './/div[@class="rssNews__provider"]/text()'
            provider = "".join(i.xpath(xpath)).split(",")

            time = datetime.datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
            embed.timestamp = time
            embed.set_footer(text=provider[-1].strip())
            items.append(embed)

        self.pages = items
        return await self.update(interaction)


class PlayerView(view_utils.BaseView):
    """A View reresenting a FlashSCore Player"""

    bot: Bot

    def __init__(
        self,
        player: fs.Player,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.player: fs.Player = player

    async def update(self, interaction: Interaction) -> None:
        """Send the latest version of the PlayerView to discord"""
        edit = interaction.response.edit_message
        return await edit(content="Coming ... Eventually ... Maybe")


class CompetitionSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, comps: list[fs.Competition]) -> None:
        super().__init__()

        self.comps: list[fs.Competition] = comps
        # Pagination
        pages = [self.comps[i : i + 25] for i in range(0, len(self.comps), 25)]
        self.pages: list[list[fs.Competition]] = pages

    async def update(self, interaction: Interaction) -> None:
        """Handle Pagination"""
        targets: list[fs.Competition] = self.pages[self.index]

        emo = fs.Competition.emoji
        embed = discord.Embed(title="Choose a Competition")
        embed.description = ""

        sel = view_utils.ItemSelect(placeholder="Please choose a competition")

        for comp in targets:
            if comp.id is None:
                continue

            name = comp.title
            dsc = comp.url
            sel.add_option(
                label=name, description=dsc, emoji=emo, value=comp.id
            )
            embed.description += f"`{comp.id}` {comp.markdown}\n"

        self.add_item(sel)
        self.add_page_buttons(1)
        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self)


class TeamSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, teams: list[fs.Team]) -> None:
        super().__init__()

        self.teams: list[fs.Team] = teams
        pages = [self.teams[i : i + 25] for i in range(0, len(self.teams), 25)]
        self.pages: list[list[fs.Team]] = pages

    async def update(self, interaction: Interaction) -> None:
        """Handle Pagination"""
        targets: list[fs.Team] = self.pages[self.index]
        sel = view_utils.ItemSelect(placeholder="Please choose a team")
        embed = discord.Embed(title="Choose a Team")
        embed.description = ""

        emo = fs.Team.emoji
        for team in targets:
            if team.id is None:
                continue

            name = team.name
            dsc = team.url
            val = team.id
            sel.add_option(label=name, description=dsc, value=val, emoji=emo)
            embed.description += f"`{team.id}` {team.markdown}\n"

        self.add_item(sel)
        self.add_page_buttons(1)
        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self)


class FixtureSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, fixtures: list[fs.Fixture]):
        super().__init__()

        # Pagination
        self.fixtures: list[fs.Fixture] = fixtures

        pages = [fixtures[i : i + 25] for i in range(0, len(fixtures), 25)]
        self.pages: list[list[fs.Fixture]] = pages

        # Final result
        self.value: typing.Any = None  # As Yet Unset

    async def update(self, interaction: Interaction) -> None:
        """Handle Pagination"""
        targets: list[fs.Fixture] = self.pages[self.index]
        sel = view_utils.ItemSelect(placeholder="Please choose a Fixture")
        embed = discord.Embed(title="Choose a Fixture")
        embed.description = ""

        for i in targets:
            if i.competition:
                desc = i.competition.title
            else:
                desc = None

            if i.id is not None:
                sel.add_option(label=i.score_line, description=desc)
            embed.description += f"`{i.id}` {i.bold_markdown}\n"

        self.add_item(sel)
        self.add_page_buttons(1)
        await interaction.response.edit_message(embed=embed, view=self)


class NationalityFilter(discord.ui.Button):
    """A button that when clicked generates a nationality filter dropdown"""

    view: ItemView

    def __init__(self, players: list[fs.Player]):
        super().__init__(row=4, label="Filter by Nationality", emoji="🌍")
        self.players: list[fs.Player] = players

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        nations = set(i.country[0] for i in self.players)

        opts = []
        for i in sorted(nations):
            flg = flags.get_flag(i)
            opts.append(discord.SelectOption(label=i, emoji=flg, value=i))

        view = view_utils.PagedItemSelect(opts)
        await view.update(interaction)

        await view.wait()

        link = self.view.page.url

        await self.view.top_scorers(
            interaction, link, True, nat_filter=view.values
        )


class TeamFilter(discord.ui.Button):
    """A button that spawns a Dropdown to Filter Teams"""

    view: ItemView

    def __init__(self, players: list[fs.Player]):
        super().__init__(row=4, label="Filter by Team", emoji="👕")
        self.players: list[fs.Player] = players

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        teams = set(i.team.name for i in self.players if i.team)

        opts = []
        for i in sorted(teams):
            opts.append(discord.SelectOption(label=i, emoji="👕", value=i))

        view = view_utils.PagedItemSelect(opts)
        await view.update(interaction)
        await view.wait()

        link = self.view.page.url
        logger.info("Sending Team filter of %s to view", view.values)
        return await self.view.top_scorers(
            interaction, link, True, tm_filter=view.values
        )


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
        interaction: Interaction,
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> None:
        """Set the default team for your flashscore lookups"""
        embed = await team.base_embed()
        embed.description = f"Commands will use  default team {team.markdown}"

        if interaction.guild is None:
            raise commands.NoPrivateMessage

        await interaction.response.send_message(embed=embed)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id)
                         VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, interaction.guild.id)

                sql = """INSERT INTO fixtures_defaults (guild_id, default_team)
                       VALUES ($1,$2) ON CONFLICT (guild_id)
                       DO UPDATE SET default_team = $2
                       WHERE excluded.guild_id = $1"""
                await connection.execute(sql, interaction.guild.id, team.id)

    @default.command(name="competition")
    @discord.app_commands.describe(competition=COMPETITION)
    async def d_comp(
        self,
        interaction: Interaction,
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> None:
        """Set the default competition for your flashscore lookups"""
        embed = await competition.base_embed()
        embed.description = "Default Competition set"
        await interaction.response.send_message(embed=embed)

        if interaction.guild is None:
            raise commands.NoPrivateMessage
        sql = """INSERT INTO fixtures_defaults (guild_id, default_league)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET default_league = $2
                WHERE excluded.guild_id = $1"""

        cid = competition.id
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, interaction.guild.id, cid)

    match = discord.app_commands.Group(
        name="match",
        description="Get information about a match from flashscore",
    )

    # FIXTURE commands
    @match.command(name="table")
    @discord.app_commands.describe(match=FIXTURE)
    async def fx_table(
        self,
        interaction: Interaction,
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> None:
        """Look up the table for a fixture."""
        page = await self.bot.browser.new_page()
        return await FixtureView(page, match).standings(interaction)

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def stats(
        self,
        interaction: Interaction,
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> None:
        """Look up the stats for a fixture."""
        page = await self.bot.browser.new_page()
        return await FixtureView(page, match).stats(interaction)

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def lineups(
        self,
        interaction: Interaction,
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> None:
        """Look up the lineups and/or formations for a Fixture."""
        page = await self.bot.browser.new_page()
        return await FixtureView(page, match).lineups(interaction)

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def summary(
        self,
        interaction: Interaction,
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> None:
        """Get a summary for a fixture"""
        page = await self.bot.browser.new_page()
        return await FixtureView(page, match).summary(interaction)

    @match.command(name="h2h")
    @discord.app_commands.describe(match=FIXTURE)
    async def h2h(
        self,
        interaction: Interaction,
        match: discord.app_commands.Transform[fs.Fixture, FixtureTransformer],
    ) -> None:
        """Lookup the head-to-head details for a Fixture"""
        page = await self.bot.browser.new_page()
        return await FixtureView(page, match).h2h(interaction)

    team = discord.app_commands.Group(
        name="team", description="Get information about a team "
    )

    @team.command(name="fixtures")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_fixtures(
        self,
        interaction: Interaction,
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> None:
        """Fetch upcoming fixtures for a team."""
        page = await self.bot.browser.new_page()
        return await TeamView(page, team).fixtures(interaction)

    @team.command(name="results")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_results(
        self,
        interaction: Interaction,
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> None:
        """Get recent results for a Team"""
        page = await self.bot.browser.new_page()
        return await TeamView(page, team).results(interaction)

    @team.command(name="table")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_table(
        self,
        interaction: Interaction,
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> None:
        """Get the Table of one of a Team's competitions"""
        page = await self.bot.browser.new_page()
        return await TeamView(page, team).standings(interaction)

    @team.command(name="news")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_news(
        self,
        interaction: Interaction,
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> None:
        """Get the latest news for a team"""
        page = await self.bot.browser.new_page()
        return await TeamView(page, team).news(interaction)

    @team.command(name="squad")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_squad(
        self,
        interaction: Interaction,
        team: discord.app_commands.Transform[fs.Team, TeamTransformer],
    ) -> None:
        """Lookup a team's squad members"""
        page = await self.bot.browser.new_page()
        return await TeamView(page, team).squad(interaction)

    league = discord.app_commands.Group(
        name="competition",
        description="Get information about a competition from flashscore",
    )

    @league.command(name="fixtures")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_fixtures(
        self,
        interaction: Interaction,
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> None:
        """Fetch upcoming fixtures for a competition."""
        page = await self.bot.browser.new_page()
        return await CompetitionView(page, competition).fixtures(interaction)

    @league.command(name="results")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_results(
        self,
        interaction: Interaction,
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> None:
        """Get recent results for a competition"""
        page = await self.bot.browser.new_page()
        return await CompetitionView(page, competition).results(interaction)

    @league.command(name="top_scorers")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_scorers(
        self,
        interaction: Interaction,
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> None:
        """Get top scorers from a competition."""
        page = await self.bot.browser.new_page()
        return await CompetitionView(page, competition).top_scorers(
            interaction
        )

    @league.command(name="table")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_table(
        self,
        interaction: Interaction,
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
    ) -> None:
        """Get the Table of a competition"""
        page = await self.bot.browser.new_page()
        return await CompetitionView(page, competition).standings(interaction)

    @discord.app_commands.command()
    async def scores(self, interaction: Interaction) -> None:
        """Fetch current scores for a specified competition,
        or if no competition is provided, all live games."""
        if interaction.client.games:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 No live games found"
            return await interaction.response.send_message(embed=embed)

        games = self.bot.games

        comp = None
        header = f"Scores as of: {timed_events.Timestamp().long}\n"
        base_embed = discord.Embed(color=discord.Colour.og_blurple())
        base_embed.title = "Current scores"
        base_embed.description = header
        embed = base_embed.copy()
        embed.description = ""
        embeds = []

        for i, j in [(i.competition, i.live_score_text) for i in games]:
            if i and i != comp:  # We need a new header if it's a new comp.
                comp = i
                output = f"\n**{i.title}**\n{j}\n"
            else:
                output = f"{j}\n"

            if len(embed.description + output) < 2048:
                embed.description = f"{embed.description}{output}"
            else:
                embeds.append(embed)
                embed = base_embed.copy()
                embed.description = f"\n**{i}**\n{j}\n"
        embeds.append(embed)
        return await view_utils.Paginator(embeds).handle_page(interaction)


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
