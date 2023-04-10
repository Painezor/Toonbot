"""Lookups of Live Football Data for teams, fixtures, and competitions."""
# TODO: GLOBAL Nuke page.content in favour of locator.inner_html()
# TODO: Standings => Team Dropdown
# TODO: Fixture => photos
# TODO: Fixture => report
# TODO: Transfers => Dropdowns for Teams & Competitions
# TODO: TeamView.squad => Enumerate when not sorting by squad number.
# TODO: Hybridise .news
# TODO: File=None in all r()
# TODO: Globally Nuke _ac for Transformers

from __future__ import annotations

import asyncio
import datetime
import io
import logging
import typing

import discord
from discord.ext import commands
from lxml import html
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeout

import ext.flashscore as fs
from ext.utils import embed_utils, flags, image_utils, timed_events, view_utils

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
    User: typing.TypeAlias = discord.User | discord.Member


logger = logging.getLogger("Fixtures")

JS = "ads => ads.forEach(x => x.remove());"
TEAM_NAME = "Enter the name of a team to search for"
FIXTURE = "Search for a fixture by team name"
COMPETITION = "Enter the name of a competition to search for"
H2H = typing.Literal["overall", "home", "away"]


sqd_filter_opts = [
    ("Sort by Squad Number", "squad_number", "#️⃣"),
    ("Sort by Goals", "goals", fs.GOAL_EMOJI),
    ("Sort by Red Cards", "reds", fs.RED_CARD_EMOJI),
    ("Sort by Yellow Cards", "yellows", fs.YELLOW_CARD_EMOJI),
    ("Sort by Appearances", "appearances", fs.TEAM_EMOJI),
    ("Sort by Age", "age", None),
    ("Show only injured", "injury", fs.INJURY_EMOJI),
]


class SquadView(view_utils.DropdownPaginator):
    """View & Sort a Team's Squad for various competitions"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: discord.Embed,
        team: fs.Team,
        players: list[fs.SquadMember],
        **kwargs,
    ) -> None:
        self.page: Page = page
        self.team: fs.Team = team
        self.players: list[fs.SquadMember]

        rows = []
        options = []
        for i in players:
            rows.append(i.output)
            opt = discord.SelectOption(label=i.player.name)
            opt.emoji = fs.PLAYER_EMOJI

        sqd_opts: list[discord.SelectOption] = []
        for i in sqd_filter_opts:
            opt = discord.SelectOption(label=i[0], value=i[1], emoji=i[2])
            sqd_opts.append(opt)
        self.srt.options = sqd_opts

        super().__init__(invoker, embed, rows, options, 40, **kwargs)

    @discord.ui.select(row=1, placeholder="View Player", disabled=True)
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[SquadView]
    ) -> None:
        """Go to specified player"""
        player = next(i for i in self.players if i.player.name in sel.values)
        view = PlayerView(itr.user, player.player)
        await itr.response.edit_message(view=view)

    @discord.ui.select(row=2, placeholder="Sort Players")
    async def srt(
        self, itr: Interaction, sel: discord.ui.Select[SquadView]
    ) -> None:
        """Change the sort mode of the view"""
        attr = sel.values[0]
        reverse = attr in ["goals", "yellows", "reds"]
        self.players.sort(key=lambda i: getattr(i, attr), reverse=reverse)
        emb = await self.team.base_embed()
        emb.set_footer(text=f"Sorted by {attr.replace('_', ' ').title()}")
        par = self.parent
        plr = self.players
        view = SquadView(itr.user, self.page, emb, self.team, plr, parent=par)
        await itr.response.edit_message(view=view, embed=view.pages[0])

    @classmethod
    async def create(
        cls,
        interaction: Interaction,
        page: Page,
        team: fs.Team,
        btn_name: typing.Optional[str] = None,
    ) -> SquadView:
        """Generate & Return a squad view"""
        embed = await team.base_embed()
        embed.title = "Squad"
        players = await team.get_squad(page, btn_name)

        # Handle Buttons
        invoker = interaction.user
        view = SquadView(invoker, page, embed, team, players)

        buttons = await view.get_buttons(interaction)
        view.add_function_row(buttons, row=3)
        return view

    async def get_buttons(
        self, interaction: Interaction
    ) -> list[view_utils.Funcable]:
        tabs = self.page.locator("role=tablist")

        btns = []
        for i in range(await tabs.count()):
            sub = tabs.nth(i).locator("button")
            for count in range(await sub.count()):
                inner_txt = await sub.nth(count).text_content()

                if not inner_txt:
                    continue

                btn = view_utils.Funcable(inner_txt, self.create)
                current = "aria-current"
                dis = await sub.nth(count).get_attribute(current) is not None
                btn.disabled = dis
                btn.args = [interaction, self.page, self.team, inner_txt]
                btns.append(btn)
        return btns


class FixturesPaginator(view_utils.DropdownPaginator):
    """Paginate Fixtures, with a dropdown that goes to a specific game."""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: discord.Embed,
        fixtures: list[fs.Fixture],
        is_fixtures: bool,
        parent: typing.Optional[ItemView] = None,
    ) -> None:
        self.page: Page = page

        options = []
        rows = []
        self.fixtures = fixtures
        for i in fixtures:
            if i.id is None:
                logger.error("%s fixture with no id passed", i.__dict__)
                continue

            # Toggle -- Are we doing fixtures or results
            rows.append(i.upcoming if is_fixtures else i.finished)
            opt = discord.SelectOption(label=i.score_line, value=i.id)
            opt.description = i.competition.title if i.competition else None
            opt.emoji = fs.GOAL_EMOJI
            options.append(opt)

        embed.title = "Fixtures"
        super().__init__(invoker, embed, rows, options, 10, parent=parent)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Competition | fs.Team,
        parent: ItemView,
        is_fixtures: bool,
    ) -> FixturesPaginator:
        """Generate & return a FixtureBrowser asynchronously"""
        cache = interaction.client.competitions
        if is_fixtures:
            games = await obj.fixtures(page, cache)
        else:
            games = await obj.results(page, cache)

        embed = await obj.base_embed()

        user = interaction.user
        view = FixturesPaginator(user, page, embed, games, is_fixtures, parent)
        return view

    @discord.ui.select()
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[FixturesPaginator]
    ) -> None:
        """Go to Fixture"""
        fix = next(i for i in self.fixtures if i.url in sel.values)
        view = FixtureView(itr.user, self.page, fix, parent=self)
        await view.news(itr)

    async def on_timeout(self) -> None:
        """Close Page, then do regular handling."""
        await self.page.close()
        return await super().on_timeout()


class TopScorersView(view_utils.DropdownPaginator):
    """View for handling top scorers."""

    nationality_filter: typing.Optional[set[str]]
    team_filter: typing.Optional[set[fs.Team]]

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: discord.Embed,
        scorers: list[fs.TopScorer],
        parent: typing.Optional[view_utils.BaseView],
        nt_flt: typing.Optional[set[str]] = None,
        tm_flt: typing.Optional[set[fs.Team]] = None,
    ):
        self.nationality_filter = nt_flt if nt_flt is not None else set()
        self.team_filter = tm_flt if tm_flt is not None else set()
        self.scorers: list[fs.TopScorer] = scorers

        flt = self.scorers.copy()

        if _ := self.nationality_filter:
            flt = [i for i in flt if i.player.country[0] in _]

        if self.team_filter:
            flt = [i for i in flt if i.team in self.team_filter]

        rows: list[str] = []
        options: list[discord.SelectOption] = []
        for i in flt:
            if i.player.url is None:
                continue

            rows.append(i.output)
            opt = discord.SelectOption(label=i.player.name)
            opt.value = i.player.url
            opt.emoji = i.player.flag

            team = f" ({i.team.name})" if i.team else ""
            opt.description = f"⚽ {i.goals} {team}"
            options.append(opt)

        self.page: Page = page
        super().__init__(invoker, embed, rows, options, 20, parent=parent)

    @discord.ui.select(placeholder="Go to Player", disabled=True)
    async def dropdown(
        self, itr: Interaction, select: discord.ui.Select[TopScorersView]
    ) -> None:
        await itr.response.defer()
        logger.info(select.values)
        raise NotImplementedError

    @discord.ui.button(label="Filter: Nationality", emoji="🌍", row=4)
    async def natfilt(self, interaction: Interaction, _) -> None:
        """Generate a nationality filter dropdown"""
        nations = [i.player.country[0] for i in self.scorers]
        nations.sort()

        options = []
        for i in set(nations):
            flg = flags.get_flag(i)
            opt = discord.SelectOption(label=i, emoji=flg, value=i)

            if i in self.nationality_filter:
                opt.default = True
            options.append(opt)

        view = view_utils.PagedItemSelect(interaction.user, options)
        await interaction.response.edit_message(view=view)
        await view.wait()

        nt_flt = view.values

        assert interaction.message is not None
        embed = interaction.message.embeds[0]

        tm_flt = self.team_filter
        invoker = interaction.user
        par = self.parent
        new = TopScorersView(
            invoker, self.page, embed, self.scorers, par, nt_flt, tm_flt
        )
        if nt_flt:
            self.natfilt.style = discord.ButtonStyle.blurple
        if tm_flt:
            self.teamfilt.style = discord.ButtonStyle.blurple
        emb = new.pages[0]
        await view.interaction.response.edit_message(view=new, embed=emb)

    @discord.ui.button(label="Filter: Team", emoji=fs.TEAM_EMOJI, row=4)
    async def teamfilt(self, interaction: Interaction, _) -> None:
        """Generate a team filter dropdown"""
        teams = set(i.team.name for i in self.scorers if i.team)

        opts: list[discord.SelectOption] = []
        for i in sorted(teams):
            emoji = fs.TEAM_EMOJI
            opts.append(discord.SelectOption(label=i, emoji=emoji, value=i))

        view = view_utils.PagedItemSelect(interaction.user, opts)
        await interaction.response.edit_message(view=view, embed=view.pages[0])
        await view.wait()

        tm_flt = view.values

        assert interaction.message is not None
        embed = interaction.message.embeds[0]

        nt_flt = self.nationality_filter
        invoker = interaction.user

        par = self.parent
        new = TopScorersView(
            invoker, self.page, embed, self.scorers, par, nt_flt, tm_flt
        )

        if nt_flt:
            self.natfilt.style = discord.ButtonStyle.blurple
        if tm_flt:
            self.teamfilt.style = discord.ButtonStyle.blurple
        emb = new.pages[0]
        await view.interaction.response.edit_message(view=new, embed=emb)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Fixture | fs.Competition | fs.Team,
        parent: view_utils.BaseView,
    ) -> TopScorersView:
        """Inttialise the Top Scorers view by fetching data"""
        embed = await obj.base_embed()
        players = await obj.get_scorers(page, interaction)

        embed.url = page.url
        embed.title = "Top Scorers"

        view = TopScorersView(interaction.user, page, embed, players, parent)
        return view


class TransfersView(view_utils.DropdownPaginator):
    """Paginator for a FlashScore Team's Transfers.

    Attatched Dropdown Allows user to go to one of the Players
    Secondary Dropdown allows user to go to one of the Teams
    Three Buttons exist to change the filter mode.
    """

    def __init__(
        self,
        invoker: User,
        page: Page,
        team: fs.Team,
        embed: discord.Embed,
        transfers: list[fs.FSTransfer],
        **kwargs,
    ) -> None:
        rows: list[str] = []
        options: list[discord.SelectOption] = []
        for i in transfers:
            opt = discord.SelectOption(label=i.player.name, emoji=i.emoji)
            if i.team is not None:
                opt.description = i.team.name
            options.append(opt)
            rows.append(i.output)

        teams = set(i.team for i in transfers if i.team is not None)
        team_sel = []
        for j in teams:
            assert j.url is not None
            emo = fs.TEAM_EMOJI
            opt = discord.SelectOption(label=j.name, value=j.url, emoji=emo)
            team_sel.append(opt)
        self.tm_dropdown.options = team_sel

        super().__init__(invoker, embed, rows, options, 5, **kwargs)

        self.teams: set[fs.Team] = teams
        self.team: fs.Team = team
        self.page: Page = page
        self.transfers: list[fs.FSTransfer] = transfers

    @discord.ui.select(placeholder="Go to Player", disabled=True)
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[TransfersView]
    ) -> None:
        """First Dropdown: Player"""
        await itr.response.defer()
        player = next(i for i in self.transfers if i.player.name in sel.values)
        logger.info(player)
        raise NotImplementedError

    @discord.ui.select(placeholder="Go to Team")
    async def tm_dropdown(
        self, interaction: Interaction, sel: discord.ui.Select[TransferView]
    ) -> None:
        """Second Dropdown: Team"""
        team = next(i for i in self.teams if i.url in sel.values)
        view = TeamView(interaction.user, self.page, team)
        await view.results(interaction)

    @discord.ui.button(label="All", row=3)
    async def _all(self, interaction: Interaction, _) -> None:
        """Get all transfers for the team."""
        cache = interaction.client.teams
        transfers = await self.team.get_transfers(self.page, "All", cache)
        embed = await self.team.base_embed()
        embed.title = "Transfers (All)"
        embed.url = self.page.url

        invoker = interaction.user
        par = self.parent
        view = TransfersView(
            invoker, self.page, self.team, embed, transfers, parent=par
        )
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    @classmethod
    async def start(
        cls, interaction: Interaction, page: Page, team: fs.Team
    ) -> TransfersView:
        """Generate a TransfersView"""
        embed: discord.Embed = await team.base_embed()
        cache = interaction.client.teams
        transfers = await team.get_transfers(page, "All", cache)
        view = TransfersView(interaction.user, page, team, embed, transfers)
        return view


class ArchiveSelect(view_utils.DropdownPaginator):
    """Dropdown to Select a previous Season for a competition"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: discord.Embed,
        rows: list[str],
        options: list[discord.SelectOption],
        archives: list[fs.Competition],
        **kwargs,
    ) -> None:
        self.page: Page = page
        super().__init__(invoker, embed, rows, options, **kwargs)
        self.archives = archives

    @classmethod
    async def start(
        cls, interaction: Interaction, page: Page, obj: fs.Competition
    ) -> ArchiveSelect:
        """Generate an ArchiveSelect asynchronously"""
        await page.goto(f"{obj.url}/archive/")
        embed = await obj.base_embed()
        embed.url = page.url
        sel = page.locator("#tournament-page-archiv")
        await sel.wait_for(timeout=5000)
        tree = html.fromstring(await sel.inner_html())

        options: list[discord.SelectOption] = []
        seasons: list[fs.Competition] = []
        rows: list[str] = []
        for i in tree.xpath('.//div[@class="archive__row"]'):
            # Get Archive as Competition
            xpath = ".//div[@class='archive__season']/a"
            c_name = "".join(i.xpath(xpath + "/text()")).strip()
            c_link = "".join(i.xpath(xpath + "/@href")).strip()

            c_link = fs.FLASHSCORE + "/" + c_link.strip("/")

            country = obj.country
            season = fs.Competition(None, c_name, country, c_link)
            seasons.append(season)
            rows.append(season.markdown)

            opt = discord.SelectOption(label=c_name, value=c_link)
            if country is not None:
                opt.emoji = flags.get_flag(country)
            # Get Winner
            xpath = ".//div[@class='archive__winner']//a"
            tm_name = "".join(i.xpath(xpath + "/text()")).strip()
            if tm_name:
                opt.description = f"🏆 Winner: {tm_name}"
            options.append(opt)
        invoker = interaction.user
        return ArchiveSelect(invoker, page, embed, rows, options, seasons)

    @discord.ui.select(placeholder="Select Previous Year")
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[ArchiveSelect]
    ) -> None:
        """Spawn a CompetitionView for the Selected Season"""
        comp = next(i for i in self.archives if i.url == sel.options[0])
        embed = await comp.base_embed()
        view = CompetitionView(itr.user, self.page, comp, parent=self)
        await itr.response.edit_message(view=self, embed=embed)
        view.message = await itr.original_response()


class ItemView(view_utils.BaseView):
    """A Generic for Fixture/Team/Competition Views"""

    def __init__(
        self, invoker: User, page: Page, **kwargs: typing.Any
    ) -> None:
        super().__init__(invoker, **kwargs)

        self.page: Page = page

    @property
    def object(self) -> fs.Team | fs.Competition | fs.Fixture:
        """Return the underlying object of the parent class"""
        if isinstance(self, TeamView):
            return self.team
        elif isinstance(self, FixtureView):
            return self.fixture
        elif isinstance(self, CompetitionView):
            return self.object
        raise TypeError

    async def on_timeout(self) -> None:
        if not self.page.is_closed():
            await self.page.close()
        await super().on_timeout()

    # TODO: create classes for each button.
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
                    btn.emoji = fs.GOAL_EMOJI
                    btn.args = [f"{self.object.url}/standings/{link}"]
                    btn.style = discord.ButtonStyle.red

                elif text == "Transfers":
                    btn = view_utils.Funcable(text, self.transfers)
                    btn.description = "Recent Transfers"
                    btn.emoji = fs.INBOUND_EMOJI

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
        view = await ArchiveSelect.start(interaction, self.page, self.object)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

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

        locator = self.page.locator(".subTabs")

        rows: dict[int, list[view_utils.Funcable]] = {}
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
        assert isinstance(self.object, (fs.Team, fs.Competition))
        await FixturesPaginator.start(
            interaction, self.page, self.object, self, True
        )

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
        screenshots: list[io.BytesIO] = []

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

        pages: list[discord.Embed] = []
        for i in images:
            embed = embed.copy()
            image = "".join(i.xpath(".//img/@src"))
            embed.set_image(url=image)
            xpath = './/div[@class="liveComment"]/text()'
            embed.description = "".join(i.xpath(xpath))
            pages.append(embed)

        view = view_utils.Paginator(interaction.user, pages, parent=self)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

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

        embed.description = f"**{title}**\n\n"
        embeds = embed_utils.rows_to_embeds(embed, content, 5, "", 2500)
        await self.handle_tabs()

        view = view_utils.Paginator(interaction.user, embeds, parent=self)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    # Competition, Team
    async def results(self, interaction: Interaction) -> None:
        """Push Previous Results Team View"""
        assert isinstance(self.object, (fs.Team, fs.Competition))
        await FixturesPaginator.start(
            interaction, self.page, self.object, self, False
        )

    # Competition, Fixture, Team
    async def top_scorers(self, interaction: Interaction) -> None:
        """Push Scorers to View"""
        obj = self.object
        view = await TopScorersView.start(interaction, self.page, obj, self)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    # Team Only
    async def squad(self, interaction: Interaction) -> None:
        """Get the squad of the team, filter or sort, push to view"""
        assert isinstance(self.object, fs.Team)
        view = await SquadView.create(interaction, self.page, self.object)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    # Team only
    async def transfers(self, interaction: Interaction) -> None:
        """Get a list of the team's recent transfers."""
        assert isinstance(self.object, fs.Team)
        view = await TransfersView.start(interaction, self.page, self.object)
        edit = interaction.response.edit_message
        return await edit(embed=view.pages[0], view=self, attachments=[])

    # Competition, Fixture, Team
    async def standings(
        self,
        interaction: Interaction,
        link: typing.Optional[str] = None,
    ) -> None:
        """Send Specified Table to view"""
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
        except PWTimeout:
            # Entry point not handled on fixtures from leagues.
            logger.error("Failed to find standings on %s", embed.url)
            await self.handle_tabs()
            edit = interaction.response.edit_message
            embed.description = "❌ No Standings Available"
            await edit(embed=embed, view=self)

        row = await self.handle_tabs()
        rows: dict[int, list[view_utils.Funcable]] = {}

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
        rows: dict[int, list[view_utils.Funcable]] = {}

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

        logger.info("Video button was pressed on page %s", self.object.url)

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


class CompetitionView(ItemView):
    """The view sent to a user about a Competition"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        competition: fs.Competition,
        **kwargs,
    ) -> None:
        self.object: fs.Competition = competition

        super().__init__(invoker, page, **kwargs)

    async def news(self, interaction: Interaction) -> None:
        raise NotImplementedError


class FixtureView(ItemView):
    """The View sent to users about a fixture."""

    def __init__(
        self,
        invoker: User,
        page: Page,
        fixture: fs.Fixture,
        **kwargs: typing.Any,
    ) -> None:
        self.fixture: fs.Fixture = fixture
        super().__init__(invoker, page, **kwargs)

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
        invoker: User,
        page: Page,
        team: fs.Team,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(invoker, page, **kwargs)
        self.team: fs.Team = team

    # Team.news
    async def news(self, interaction: Interaction) -> None:
        """Get a list of news articles related to a team in embed format"""
        await self.page.goto(f"{self.team.url}/news", timeout=5000)
        locator = self.page.locator(".matchBox").nth(0)
        await locator.wait_for()
        await self.handle_tabs()
        tree = html.fromstring(await locator.inner_html())

        embeds = []

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
            embeds.append(embed)

        view = view_utils.Paginator(interaction.user, embeds, parent=self)
        await interaction.response.edit_message(view=view, embed=view.pages[0])


class PlayerView(view_utils.BaseView):
    """A View reresenting a FlashSCore Player"""

    def __init__(
        self,
        invoker: User,
        player: fs.Player,
        **kwargs: typing.Any,
    ):
        super().__init__(invoker, **kwargs)
        self.player: fs.Player = player

    async def update(self, interaction: Interaction) -> None:
        """Send the latest version of the PlayerView to discord"""
        edit = interaction.response.edit_message
        return await edit(content="Coming ... Eventually ... Maybe")


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

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
        team: fs.team_trnsf,
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
        self, interaction: Interaction, competition: fs.comp_trnsf
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
        self, interaction: Interaction, match: fs.fix_trnsf
    ) -> None:
        """Look up the table for a fixture."""
        page = await self.bot.browser.new_page()
        await FixtureView(interaction.user, page, match).standings(interaction)

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def stats(
        self, interaction: Interaction, match: fs.fix_trnsf
    ) -> None:
        """Look up the stats for a fixture."""
        page = await self.bot.browser.new_page()
        await FixtureView(interaction.user, page, match).stats(interaction)

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def lineups(
        self, interaction: Interaction, match: fs.fix_trnsf
    ) -> None:
        """Look up the lineups and/or formations for a Fixture."""
        page = await self.bot.browser.new_page()
        await FixtureView(interaction.user, page, match).lineups(interaction)

    @match.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def summary(
        self, interaction: Interaction, match: fs.fix_trnsf
    ) -> None:
        """Get a summary for a fixture"""
        page = await self.bot.browser.new_page()
        await FixtureView(interaction.user, page, match).summary(interaction)

    @match.command(name="h2h")
    @discord.app_commands.describe(match=FIXTURE)
    async def h2h(
        self, interaction: Interaction, match: fs.team_trnsf
    ) -> None:
        """Lookup the head-to-head details for a Fixture"""
        page = await self.bot.browser.new_page()
        await FixtureView(interaction.user, page, match).h2h(interaction)

    team = discord.app_commands.Group(
        name="team", description="Get information about a team "
    )

    @team.command(name="fixtures")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_fixtures(
        self, interaction: Interaction, team: fs.team_trnsf
    ) -> None:
        """Fetch upcoming fixtures for a team."""
        page = await self.bot.browser.new_page()
        await TeamView(interaction.user, page, team).fixtures(interaction)

    @team.command(name="results")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_results(
        self, interaction: Interaction, team: fs.team_trnsf
    ) -> None:
        """Get recent results for a Team"""
        page = await self.bot.browser.new_page()
        await TeamView(interaction.user, page, team).results(interaction)

    @team.command(name="table")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_table(
        self, interaction: Interaction, team: fs.team_trnsf
    ) -> None:
        """Get the Table of one of a Team's competitions"""
        page = await self.bot.browser.new_page()
        await TeamView(interaction.user, page, team).standings(interaction)

    @team.command(name="news")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_news(
        self, interaction: Interaction, team: fs.team_trnsf
    ) -> None:
        """Get the latest news for a team"""
        page = await self.bot.browser.new_page()
        await TeamView(interaction.user, page, team).news(interaction)

    @team.command(name="squad")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def team_squad(
        self, interaction: Interaction, team: fs.team_trnsf
    ) -> None:
        """Lookup a team's squad members"""
        page = await self.bot.browser.new_page()
        await TeamView(interaction.user, page, team).squad(interaction)

    league = discord.app_commands.Group(
        name="competition",
        description="Get information about a competition from flashscore",
    )

    @league.command(name="fixtures")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_fixtures(
        self, interaction: Interaction, competition: fs.comp_trnsf
    ) -> None:
        """Fetch upcoming fixtures for a competition."""
        page = await self.bot.browser.new_page()
        view = CompetitionView(interaction.user, page, competition)
        await view.fixtures(interaction)

    @league.command(name="results")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_results(
        self, interaction: Interaction, competition: fs.comp_trnsf
    ) -> None:
        """Get recent results for a competition"""
        page = await self.bot.browser.new_page()
        view = CompetitionView(interaction.user, page, competition)
        await view.results(interaction)

    @league.command(name="top_scorers")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_scorers(
        self, interaction: Interaction, competition: fs.comp_trnsf
    ) -> None:
        """Get top scorers from a competition."""
        page = await self.bot.browser.new_page()
        view = CompetitionView(interaction.user, page, competition)
        await view.top_scorers(interaction)

    @league.command(name="table")
    @discord.app_commands.describe(competition=COMPETITION)
    async def comp_table(
        self, interaction: Interaction, competition: fs.comp_trnsf
    ) -> None:
        """Get the Table of a competition"""
        page = await self.bot.browser.new_page()
        view = CompetitionView(interaction.user, page, competition)
        await view.standings(interaction)

    # TODO: Scores Transformer with Autocomplete
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
        embeds: list[discord.Embed] = []

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

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(Fixtures(bot))
