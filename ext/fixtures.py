"""Lookups of Live Football Data for teams, fixtures, and competitions."""
# TODO: GLOBAL Nuke page.content in favour of locator.inner_html()
# TODO: Fixture => photos
# TODO: Fixture => report
# TODO: Transfers => Dropdowns for Competitions
# TODO: Squad => Enumerate when not sorting by squad number.
# TODO: File=None in all r()
# TODO: Globally Nuke _ac for Transformers

from __future__ import annotations

import asyncio
import copy
import io
import logging
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, overload
import asyncpg

import discord
from discord import Embed, File, Colour
from discord.ext import commands
from discord.ui import Button, Select
from lxml import html
from playwright.async_api import Page

import ext.flashscore as fs
from ext.utils import embed_utils, flags, image_utils, view_utils, timed_events
from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member


logger = logging.getLogger("Fixtures")

JS = "ads => ads.forEach(x => x.remove());"
TEAM_NAME = "Enter the name of a team to search for"
FIXTURE = "Search for a fixture by team name"
COMPETITION = "Enter the name of a competition to search for"
H2H = Literal["overall", "home", "away"]


sqd_filter_opts = [
    ("Sort by Squad Number", "squad_number", "#️⃣"),
    ("Sort by Goals", "goals", fs.GOAL_EMOJI),
    ("Sort by Red Cards", "reds", fs.RED_CARD_EMOJI),
    ("Sort by Yellow Cards", "yellows", fs.YELLOW_CARD_EMOJI),
    ("Sort by Appearances", "appearances", fs.TEAM_EMOJI),
    ("Sort by Age", "age", None),
    ("Show only injured", "injury", fs.INJURY_EMOJI),
]

_colours: dict[str, Colour | int] = {}


class FSEmbed(Embed):
    def __init__(self, obj: fs.Fixture | fs.Team | fs.Competition) -> None:
        super().__init__()

        self.obj = obj
        # Handling of logourl
        self.set_thumbnail(url=obj.logo_url)
        self.set_author(name=obj.title, url=obj.url, icon_url=obj.logo_url)

    async def set_colour(self) -> None:
        """Get and set the colour of the embed based on current logo"""
        if self.obj.id is None:
            return
        color = _colours.get(self.obj.id, None)

        if color is None and self.thumbnail.url:
            color = await embed_utils.get_colour(self.thumbnail.url)
            _colours.update({self.obj.id: color})
        self.color = color

    @overload
    @classmethod
    async def create(cls, obj: fs.Fixture) -> FixtureEmbed:
        ...

    @overload
    @classmethod
    async def create(cls, obj: fs.Team) -> TeamEmbed:
        ...

    @overload
    @classmethod
    async def create(cls, obj: fs.Competition) -> CompetitionEmbed:
        ...

    @classmethod
    async def create(cls, obj: ...) -> Embed:
        """Create an embed based upon what type of fsobject is passed"""

        embed = cls(obj)
        await embed.set_colour()

        _class = {
            fs.Fixture: FixtureEmbed,
            fs.Team: TeamEmbed,
            fs.Competition: CompetitionEmbed,
        }[type(obj)]
        return await _class.extend(obj, embed)


class TeamEmbed(Embed):
    @classmethod
    async def extend(cls, team: fs.Team, embed: Embed) -> Embed:
        return embed


class CompetitionEmbed(Embed):
    @classmethod
    async def extend(cls, competition: fs.Competition, embed: Embed) -> Embed:
        return embed


class FixtureEmbed(Embed):
    @classmethod
    async def extend(cls, fixture: fs.Fixture, embed: Embed) -> Embed:
        """Return a discord embed for a generic Fixture"""
        if fixture.competition:
            embed = FSEmbed(fixture.competition)

        embed.url = fixture.url
        if fixture.state:
            embed.colour = fixture.state.colour
        embed.set_author(name=fixture.score_line)
        embed.timestamp = fixture.kickoff
        embed.description = ""

        if fixture.infobox is not None:
            embed.add_field(name="Match Info", value=fixture.infobox)

        if fixture.time is None:
            return embed

        elif fixture.time == fs.GameState.SCHEDULED:
            time = timed_events.Timestamp(fixture.kickoff).time_relative
            embed.description = f"Kickoff: {time}"
        elif fixture.time == fs.GameState.POSTPONED:
            embed.description = "This match has been postponed."

        if fixture.competition:
            embed.set_footer(
                text=f"{fixture.time} | {fixture.competition.title}"
            )
        else:
            embed.set_footer(text=fixture.time)
        return embed


class StatsView(BaseView):
    def __init__(
        self,
        invoker: User,
        page: Page,
        fixture: fs.Fixture,
        *,
        parent: BaseView | None = None,
        timeout: float | None = 180,
    ):
        super().__init__(invoker, parent=parent, timeout=timeout)
        self.fixture: fs.Fixture = fixture
        self.page: Page = page
        self.remove_item(self.sub_page)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Fixture,
        parent: FSView | None = None,
    ) -> None:
        """Start a stats view and fetch by fetching the appropraite data"""
        if parent is None:
            parent = FSView(interaction.user, page, obj)
            await parent.handle_buttons()

        stats = await obj.get_stats(page)
        embed = await FSEmbed.create(obj)
        embed.title = "Stats"
        view = cls(interaction.user, page, obj, parent=parent)
        await view.handle_buttons()

        if output := "\n".join(str(i) for i in stats):
            embed.description = f"```ini\n{output}```"
        else:
            embed.description = "Could not find stats for this game."

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(row=1, label="Stats")
    async def sub_page(
        self, interaction: Interaction, btn: Button[StatsView]
    ) -> None:
        """A button that requests a subpage"""
        stats = await self.fixture.get_stats(self.page, btn.label)
        embed = await FSEmbed.create(self.fixture)
        if output := "\n".join(str(i) for i in stats):
            embed.description = f"```ini\n{output}```"
        else:
            embed.description = "Could not find stats for this game."
        embed.title = f"Stats ({btn.label})"
        return await interaction.response.edit_message(view=self, embed=embed)

    async def handle_buttons(self) -> None:
        """Add sub page buttons."""
        cur = [i.label for i in self.children if isinstance(i, Button)]

        # TODO: Change locator to subTabs > a or working variaation.
        for i in await self.page.locator(".subTabs").all():
            for j in await i.locator("a").all():
                text = await j.text_content()
                if not text:
                    continue

                if text not in cur:
                    btn = copy.copy(self.sub_page)
                    btn.label = text
                    self.add_item(btn)


# TODO: Finish Standings View -> Team Dropdown
class StandingsView(BaseView):
    def __init__(
        self,
        invoker: User,
        page: Page,
        item: fs.Team | fs.Competition | fs.Fixture,
        teams: list[fs.Team] = [],
        *,
        parent: BaseView | None = None,
        timeout: float | None = 180,
    ):
        super().__init__(invoker, parent=parent, timeout=timeout)
        self.page: Page = page
        self.object: fs.Team | fs.Competition | fs.Fixture = item
        self.teams: list[fs.Team] = teams
        self.remove_item(self.subtable)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Team | fs.Competition | fs.Fixture,
        parent: BaseView | None = None,
    ) -> None:
        """Start a Standings View"""
        embed = await FSEmbed.create(obj)
        embed.title = "Standings"

        image = await obj.get_table(page)
        view = cls(interaction.user, page, obj, parent=parent)

        loc = page.locator(".subTabs")
        for i in range(await loc.count()):
            sub = loc.nth(i).locator("a")
            for count in range(await sub.count()):
                text = await sub.nth(count).text_content()

                if not text:
                    continue

                button = copy.copy(view.subtable)
                button.label = text
                view.add_item(button)

        if image is not None:
            atts = [File(fp=io.BytesIO(image), filename="standings.png")]
        else:
            atts = []

        embed.set_image(url="attachment://standings.png")
        edit = interaction.response.edit_message
        await edit(view=view, embed=embed, attachments=atts)

    @discord.ui.button(label="Subtable")
    async def subtable(
        self, interaction: Interaction, btn: Button[StandingsView]
    ) -> None:
        image = await self.object.get_table(self.page, btn.label)
        embed = await FSEmbed.create(self.object)
        embed.title = f"Standings ({btn.label})"
        if image is not None:
            file = File(fp=io.BytesIO(image), filename="standings.png")
            atts = [file]
        else:
            atts = []

        embed.set_image(url="attachment://standings.png")
        if interaction.response.is_done():
            edit = interaction.edit_original_response
            await edit(embed=embed, attachments=atts, view=self)
        else:
            edit = interaction.response.edit_message
            await edit(embed=embed, attachments=atts, view=self)

    # TODO: Standings => Team Dropdown
    @discord.ui.select(placeholder="Go to Team", disabled=True)
    async def dropdown(
        self, interaction: Interaction, sel: Select[StandingsView]
    ) -> None:
        """Go to a team's view."""
        team: fs.Team = next(i for i in self.teams if i.id in sel.values)
        view = FSView(interaction.user, self.page, team, parent=self)
        embed = await FSEmbed.create(team)
        return await interaction.response.edit_message(view=view, embed=embed)


class SquadView(view_utils.DropdownPaginator):
    """View & Sort a Team's Squad for various competitions"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        team: fs.Team,
        players: list[fs.SquadMember],
        **kwargs: Any,
    ) -> None:
        self.page: Page = page
        self.team: fs.Team = team
        self.players: list[fs.SquadMember]

        rows: list[str] = []
        options: list[discord.SelectOption] = []
        for i in players:
            rows.append(i.output)
            opt = discord.SelectOption(label=i.player.name)
            opt.emoji = fs.PLAYER_EMOJI

        sqd_opts: list[discord.SelectOption] = []
        for i in sqd_filter_opts:
            opt = discord.SelectOption(label=i[0], value=i[1], emoji=i[2])
            sqd_opts.append(opt)

        super().__init__(invoker, embed, rows, options, 40, **kwargs)

    @discord.ui.select(row=1, placeholder="View Player", disabled=True)
    async def dropdown(self, itr: Interaction, sel: Select[SquadView]) -> None:
        """Go to specified player"""
        raise NotImplementedError
        # player = next(i for i in self.players if i.player.name in sel.values)
        # view = ItemView(itr.user, self.page, player.player)
        # await itr.response.edit_message(view=view)

    @discord.ui.select(row=2, placeholder="Sort Players")
    async def srt(self, itr: Interaction, sel: Select[SquadView]) -> None:
        """Change the sort mode of the view"""
        attr = sel.values[0]
        reverse = attr in ["goals", "yellows", "reds"]
        self.players.sort(key=lambda i: getattr(i, attr), reverse=reverse)
        emb = await FSEmbed.create(self.team)
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
        btn_name: str | None = None,
    ) -> SquadView:
        """Generate & Return a squad view"""
        embed = await FSEmbed.create(team)
        embed.title = "Squad"
        players = await team.get_squad(page, btn_name)

        # Handle Buttons
        invoker = interaction.user
        view = SquadView(invoker, page, embed, team, players)
        await view.get_buttons()
        return view

    @discord.ui.button(label="SubPage")
    async def subpage(
        self, interaction: Interaction, _: Button[SquadView]
    ) -> None:
        """Get Squads for other leagues"""
        # TODO

    async def get_buttons(self) -> None:
        """Create Buttons for filter modes"""
        btns = [i.label for i in self.children if isinstance(i, Button)]
        for i in await self.page.locator("role=tablist > button").all():
            text = await i.text_content()

            if not text or text in btns:
                continue

            button = copy.copy(self.subpage)
            button.label = text
            self.add_item(button)


class FXPaginator(view_utils.DropdownPaginator):
    """Paginate Fixtures, with a dropdown that goes to a specific game."""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        fixtures: list[fs.Fixture],
        parent: BaseView | None = None,
    ) -> None:
        self.page: Page = page

        options: list[discord.SelectOption] = []
        rows: list[str] = []
        self.fixtures = fixtures
        for i in fixtures:
            if i.id is None:
                logger.error("%s fixture with no id passed", i.__dict__)
                continue

            # Toggle -- Are we doing fixtures or results
            rows.append(str(i))
            opt = discord.SelectOption(label=i.score_line, value=i.id)
            opt.description = i.competition.title if i.competition else None
            opt.emoji = fs.GOAL_EMOJI
            options.append(opt)

        embed.title = "Fixtures"
        logger.info("%s fixtures, %s options", len(fixtures), len(options))
        super().__init__(invoker, embed, rows, options, 10, parent=parent)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Competition | fs.Team,
        is_fixtures: bool,
        parent: BaseView | None = None,
    ) -> None:
        """Generate & return a FixtureBrowser asynchronously"""
        if parent is None:
            parent = FSView(interaction.user, page, obj)
            await parent.handle_buttons()

        if is_fixtures:
            games = await obj.fixtures(page, interaction.client.cache)
        else:
            games = await obj.results(page, interaction.client.cache)

        embed = await FSEmbed.create(obj)
        view = FXPaginator(interaction.user, page, embed, games, parent)
        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        await edit(view=view, embed=view.pages[0])

        view.message = await interaction.original_response()
        parent.message = view.message

    @discord.ui.select()
    async def dropdown(
        self, itr: Interaction, sel: Select[FXPaginator]
    ) -> None:
        """Go to Fixture"""
        fix = next(i for i in self.fixtures if i.id in sel.values)
        parent = FSView(itr.user, self.page, fix)
        await parent.news.callback(itr)

    async def on_timeout(self) -> None:
        """Close Page, then do regular handling."""
        if not self.page.is_closed():
            await self.page.close()
        return await super().on_timeout()


class TopScorersView(view_utils.DropdownPaginator):
    """View for handling top scorers."""

    nationality_filter: set[str]
    team_filter: set[fs.Team]

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        scorers: list[fs.TopScorer],
        parent: view_utils.BaseView | None,
        nt_flt: set[str] | None = None,
        tm_flt: set[fs.Team] | None = None,
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
            opt.emoji = flags.get_flags(i.player.country)[0]

            team = f" ({i.team.name})" if i.team else ""
            opt.description = f"⚽ {i.goals} {team}"
            options.append(opt)

        self.base_embed: Embed = embed
        self.page: Page = page
        super().__init__(invoker, embed, rows, options, 20, parent=parent)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Competition | fs.Team,
        parent: BaseView | None = None,
    ) -> None:
        """Inttialise the Top Scorers view by fetching data"""
        if parent is None:
            parent = FSView(interaction.user, page, obj)
            await parent.handle_buttons()

        embed = await FSEmbed.create(obj)
        players = await obj.get_scorers(page)

        embed.url = page.url
        embed.title = "Top Scorers"

        view = TopScorersView(interaction.user, page, embed, players, parent)
        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        await edit(view=view, embed=view.pages[0])

    @discord.ui.select(placeholder="Go to Player", disabled=True)
    async def dropdown(
        self, itr: Interaction, select: Select[TopScorersView]
    ) -> None:
        await itr.response.defer()
        logger.info(select.values)
        raise NotImplementedError

    @discord.ui.button(label="Filter: Nationality", emoji="🌍", row=4)
    async def natfilt(self, interaction: Interaction, _) -> None:
        """Generate a nationality filter dropdown"""
        nations = [i.player.country[0] for i in self.scorers]
        nations.sort()

        options: list[discord.SelectOption] = []
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

        embed = self.base_embed

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
        teams = set(i.team for i in self.scorers if i.team in self.team_filter)

        opts: list[discord.SelectOption] = []
        for i in sorted(teams, key=lambda i: i.title):
            if i.url is None:
                continue

            opt = discord.SelectOption(label=i.title, value=i.url)
            opt.emoji = fs.TEAM_EMOJI
            opts.append(opt)

        view = view_utils.PagedItemSelect(interaction.user, opts)
        await interaction.response.edit_message(view=view, embed=view.pages[0])
        await view.wait()

        tm_flt = teams
        embed = self.base_embed
        nt_flt = self.nationality_filter
        invoker = interaction.user

        par = self.parent
        new = TopScorersView(
            invoker, self.page, embed, self.scorers, par, nt_flt, tm_flt
        )

        if nt_flt:
            new.natfilt.style = discord.ButtonStyle.blurple
        if tm_flt:
            new.teamfilt.style = discord.ButtonStyle.blurple
        emb = new.pages[0]
        await view.interaction.response.edit_message(view=new, embed=emb)


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
        embed: Embed,
        transfers: list[fs.FSTransfer],
        **kwargs: Any,
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
        team_sel: list[discord.SelectOption] = []
        for j in teams:
            assert j.url is not None
            emo = fs.TEAM_EMOJI
            opt = discord.SelectOption(label=j.title, value=j.url, emoji=emo)
            team_sel.append(opt)
        self.tm_dropdown.options = team_sel

        super().__init__(invoker, embed, rows, options, 5, **kwargs)

        self.teams: set[fs.Team] = teams
        self.team: fs.Team = team
        self.page: Page = page
        self.transfers: list[fs.FSTransfer] = transfers

    @discord.ui.select(placeholder="Go to Player", disabled=True)
    async def dropdown(
        self, itr: Interaction, sel: Select[TransfersView]
    ) -> None:
        """First Dropdown: Player"""
        await itr.response.defer()
        player = next(i for i in self.transfers if i.player.name in sel.values)
        logger.info(player)
        raise NotImplementedError

    @discord.ui.select(placeholder="Go to Team")
    async def tm_dropdown(
        self, interaction: Interaction, sel: Select[TransfersView]
    ) -> None:
        """Second Dropdown: Team"""
        team = next(i for i in self.teams if i.url in sel.values)
        await FXPaginator.start(interaction, self.page, team, False, self)

    @discord.ui.button(label="All", row=3)
    async def _all(self, interaction: Interaction, _) -> None:
        """Get all transfers for the team."""
        cache = interaction.client.cache
        transfers = await self.team.get_transfers(self.page, "All", cache)
        embed = await FSEmbed.create(self.team)
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
        embed: Embed = await FSEmbed.create(team)
        cache = interaction.client.cache
        transfers = await team.get_transfers(page, "All", cache)
        view = TransfersView(interaction.user, page, team, embed, transfers)
        return view


class ArchiveSelect(view_utils.DropdownPaginator):
    """Dropdown to Select a previous Season for a competition"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        rows: list[str],
        options: list[discord.SelectOption],
        archives: list[fs.Competition],
        **kwargs: Any,
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
        embed = await FSEmbed.create(obj)
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
            season = fs.Competition(name=c_name, country=country, url=c_link)
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
        self, itr: Interaction, sel: Select[ArchiveSelect]
    ) -> None:
        """Spawn a new View for the Selected Season"""
        comp = next(i for i in self.archives if i.url == sel.options[0])
        embed = await FSEmbed.create(comp)
        view = FSView(itr.user, self.page, comp, parent=self)
        await itr.response.edit_message(view=self, embed=embed)
        view.message = await itr.original_response()


class H2HView(view_utils.BaseView):
    def __init__(
        self,
        invoker: User,
        page: Page,
        fixture: fs.Fixture,
        *,
        parent: BaseView | None = None,
        timeout: float | None = 180,
    ):
        super().__init__(invoker, parent=parent, timeout=timeout)
        self.page = page
        self.fixture = fixture

    @discord.ui.button(label="subpage")
    async def btn(self, interaction: Interaction, _: Button[H2HView]) -> None:
        """A button to go to a subpage of a HeadToHeadView"""
        rows = await self.fixture.get_head_to_head(self.page, _.label)
        embed = await FSEmbed.create(self.fixture)
        embed.title = f"Head to Head ({_.label})"
        embed.description = "\n".join(rows)
        await interaction.response.edit_message(view=self, embed=embed)

    async def add_buttons(self) -> None:
        """Generate a button for each subtab found."""
        btns = [i.label for i in self.children if isinstance(i, Button)]
        for i in await self.page.locator(".subTabs > a").all():
            if not (text := await i.text_content()) or text in btns:
                continue

            button = copy.copy(self.btn)
            button.label = text
            self.add_item(button)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        fixture: fs.Fixture,
        parent: FSView | None = None,
    ) -> None:
        """Start a Head to Head View"""
        if parent is None:
            parent = FSView(interaction.user, page, fixture)
            await parent.handle_buttons()

        view = H2HView(interaction.user, page, fixture, parent=parent)
        await view.add_buttons()

        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message

        rows = await fixture.get_head_to_head(page)
        embed = await FSEmbed.create(fixture)
        embed.title = "Head to Head"
        embed.description = "\n".join(rows)
        await edit(view=view, embed=embed)
        view.message = await interaction.original_response()
        parent.message = view.message


class FSView(view_utils.BaseView):
    """A Generic for Fixture/Team/Competition Views"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        obj: fs.Team | fs.Competition | fs.Fixture,
        **kwargs: Any,
    ) -> None:
        super().__init__(invoker, **kwargs)
        self.page: Page = page
        self.object: fs.Team | fs.Competition | fs.Fixture = obj

        # Remove these, we add them back later.
        self.clear_items()

    async def on_timeout(self) -> None:
        """Close the page on this & use BaseView's cleanup."""
        if not self.page.is_closed():
            await self.page.close()
        await super().on_timeout()

    async def handle_buttons(self) -> None:
        """Generate our buttons. Returns the next free row number"""
        self.clear_items()
        self.embed = await FSEmbed.create(self.object)

        # While we're here, let's also grab the logo url.
        if isinstance(self.object, (fs.Team, fs.Competition)):
            await self.object.get_logo(self.page)

        for i in await self.page.locator("div.tabs__group > a").all():
            if not (text := await i.text_content()):
                continue

            try:
                btn = {
                    "Archive": self.ach,
                    "Fixtures": self.fx,
                    "H2H": self.h2h,
                    "Lineups": self.frm,
                    "News": self.news,
                    "Match": self.smr,
                    "Photos": self.photo,
                    "Report": self.report,
                    "Results": self.results,
                    "Standings": self.tbl,
                    "Stats": self.stats,
                    "Squad": self.squad,
                    "Summary": self.smr,
                    "Top Scorers": self.top_scorers,
                    "Transfers": self.trns,
                    "Video": self.video,
                }[text]

                if text in ["Summary", "Match"]:
                    if not isinstance(self.object, fs.Fixture):
                        continue  # Summary is garbage on everything else.

                if btn not in self.children:
                    self.add_item(btn)
                continue
            except KeyError:
                if text != "Odds":
                    logger.info("Missing button for %s", text)
        return

    @discord.ui.button(label="Archive", emoji="🗄️")
    async def ach(self, interaction: Interaction, btn: Button[FSView]) -> None:
        """Get a list of Archives for a competition"""
        if not isinstance(self.object, fs.Competition):
            raise NotImplementedError

        view = await ArchiveSelect.start(interaction, self.page, self.object)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    # Fixture Only
    @discord.ui.button(label="Head to Head", emoji="⚔")
    async def h2h(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Get results of recent games for each team in the fixture"""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError
        await H2HView.start(interaction, self.page, self.object, self)

    # Competition, Team
    @discord.ui.button(label="Fixtures", emoji="🗓️")
    async def fx(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push upcoming competition fixtures to View"""
        if not isinstance(self.object, (fs.Competition, fs.Team)):
            raise NotImplementedError
        obj = self.object
        await FXPaginator.start(interaction, self.page, obj, True, self)

    # Fixture Only
    @discord.ui.button(label="Lineups", emoji="🧑‍🤝‍🧑")
    async def frm(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push Lineups & Formations Image to view"""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        embed = await FSEmbed.create(self.object)
        embed.title = "Lineups and Formations"

        embed.url = f"{self.object.url}/#/match-summary/lineups"
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
            file = [File(fp=data, filename="lineups.png")]
        else:
            embed.description = "Lineups and Formations unavailable."
            file = []
        embed.set_image(url="attachment://lineups.png")

        await self.handle_buttons()
        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=file, view=self)

    # Fixture Only
    @discord.ui.button(label="Photos", emoji="📷")
    async def photo(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push Photos to view"""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        embed = await FSEmbed.create(self.object)
        embed.title = "Photos"

        photos = await self.object.get_photos(self.page)

        pht: list[Embed] = []
        for i in photos:
            emb = embed.copy()
            emb.description = i.description
            emb.set_image(url=i.url)
            pht.append(emb)

        view = view_utils.Paginator(interaction.user, pht, parent=self)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    @discord.ui.button(label="News", emoji="📰")
    async def news(self, interaction: Interaction, _: Button[FSView]) -> None:
        """The News Button"""
        if not isinstance(self.object, (fs.Team, fs.Fixture)):
            raise NotImplementedError

        articles = await self.object.get_news(self.page)
        base_embed = await FSEmbed.create(self.object)

        embeds: list[Embed] = []
        for i in articles:
            embed = base_embed.copy()
            embed.timestamp = i.timestamp
            embed.description = i.description
            embed.set_image(url=i.image)
            embed.set_footer(text=i.provider)
            embed.title = i.title
            embeds.append(embed)

        await self.handle_buttons()
        view = view_utils.Paginator(interaction.user, embeds, parent=self)

        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        await edit(view=view, embed=view.pages[0])

    # Fixture Only
    @discord.ui.button(label="Report", emoji="📰")
    async def report(
        self, interaction: Interaction, _: Button[FSView]
    ) -> None:
        """Get the report in text format."""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        embed = await FSEmbed.create(self.object)

        embed.url = f"{self.object.url}/#/report/"
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
        await self.handle_buttons()
        view = view_utils.Paginator(interaction.user, embeds, parent=self)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    # Competition, Team
    @discord.ui.button(label="Results", emoji="📋")
    async def results(
        self, interaction: Interaction, btn: Button[FSView]
    ) -> None:
        """Push Previous Results Team View"""
        if not isinstance(self.object, (fs.Team, fs.Competition)):
            raise NotImplementedError

        obj = self.object
        await FXPaginator.start(interaction, self.page, obj, False, self)

    # Competition, Team
    @discord.ui.button(label="Top Scorers", emoji=fs.GOAL_EMOJI)
    async def top_scorers(
        self, interaction: Interaction, _: Button[FSView]
    ) -> None:
        """Push Scorers to View"""
        if isinstance(self.object, (fs.FSPlayer, fs.Fixture)):
            raise NotImplementedError
        await TopScorersView.start(interaction, self.page, self.object, self)

    # Team Only
    @discord.ui.button(label="Squad", emoji="🧑‍🤝‍🧑")
    async def squad(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Get the squad of the team, filter or sort, push to view"""
        if not isinstance(self.object, fs.Team):
            raise NotImplementedError

        view = await SquadView.create(interaction, self.page, self.object)
        await interaction.response.edit_message(view=view, embed=view.pages[0])

    # Team only
    @discord.ui.button(label="Transfers", emoji=fs.OUTBOUND_EMOJI)
    async def trns(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Get a list of the team's recent transfers."""
        if not isinstance(self.object, fs.Team):
            raise NotImplementedError

        view = await TransfersView.start(interaction, self.page, self.object)
        edit = interaction.response.edit_message
        return await edit(embed=view.pages[0], view=self, attachments=[])

    # Competition, Fixture, Team
    @discord.ui.button(label="Standings", emoji="🏅")
    async def tbl(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Send Specified Table to view"""
        await StandingsView.start(interaction, self.page, self.object, self)

    # Fixture Only
    @discord.ui.button(label="Stats")
    async def stats(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push Stats to View"""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError
        return await StatsView.start(interaction, self.page, self.object)

    # Fixture Only
    @discord.ui.button(label="Summary")
    async def smr(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Fetch the summary of a Fixture as a text formatted embed"""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        await self.object.refresh(self.page)

        assert self.object.competition is not None
        if self.object.competition.url is None:
            id_ = self.object.competition.id
            comps = interaction.client.cache.competitions
            cmp = next(i for i in comps if i.id == id_)
            self.object.competition = cmp

        embed = await FSEmbed.create(self.object)

        embed.description = "\n".join(str(i) for i in self.object.incidents)
        if self.object.referee:
            embed.description += f"**Referee**: {self.object.referee}\n"
        if self.object.stadium:
            embed.description += f"**Venue**: {self.object.stadium}\n"
        if self.object.attendance:
            embed.description += f"**Attendance**: {self.object.attendance}\n"

        embed.url = f"{self.object.url}/#/match-summary/"
        await self.page.goto(embed.url, timeout=5000)
        await self.handle_buttons()
        edit = interaction.response.edit_message
        return await edit(embed=embed, attachments=[], view=self)

    # Fixture Only
    @discord.ui.button(label="Video", emoji="📹")
    async def video(
        self, interaction: Interaction, btn: Button[FSView]
    ) -> None:
        """Highlights and other shit."""
        if not isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        logger.info("Video button was pressed on page %s", self.object.url)

        # e.url = f"{self.fixture.link}#/video"
        url = f"{self.object.url}/#/video"
        await self.page.goto(url, timeout=5000)
        await self.handle_buttons()

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


class FixturesCog(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.fixture_defaults: list[asyncpg.Record] = []

    async def cog_load(self) -> None:
        """When cog loads, load up our defaults cache"""
        await self.update_cache()

    async def update_cache(self) -> None:
        """Cache our fixture defaults."""
        sql = """SELECT * FROM FIXTURES_DEFAULTS"""
        self.fixture_defaults = await self.bot.db.fetch(sql, timeout=10)

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
        team: fs.tm_tran,
    ) -> None:
        """Set the default team for your flashscore lookups"""
        embed = await FSEmbed.create(team)
        embed.description = f"Commands will use  default team {team.markdown}"

        if interaction.guild is None:
            raise commands.NoPrivateMessage

        await interaction.response.send_message(embed=embed)

        sql = """INSERT INTO guild_settings (guild_id)
                 VALUES ($1) ON CONFLICT DO NOTHING"""
        await self.bot.db.execute(sql, interaction.guild.id, timeout=10)
        sql = """INSERT INTO fixtures_defaults (guild_id, default_team)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1"""
        await self.bot.db.execute(sql, interaction.guild.id, team.id)

    @default.command(name="competition")
    @discord.app_commands.describe(competition=COMPETITION)
    async def d_comp(
        self, interaction: Interaction, competition: fs.cmp_tran
    ) -> None:
        """Set the default competition for your flashscore lookups"""

        embed = await FSEmbed.create(competition)
        embed.description = "Default Competition set"
        await interaction.edit_original_response(embed=embed)

        if interaction.guild is None:
            raise commands.NoPrivateMessage

        gid = interaction.guild.id
        sql = """INSERT INTO guild_settings (guild_id)
                 VALUES ($1) ON CONFLICT DO NOTHING"""
        await self.bot.db.execute(sql, gid, timeout=10)

        sql = """INSERT INTO fixtures_defaults (guild_id, default_league)
                VALUES ($1,$2) ON CONFLICT (guild_id) DO UPDATE SET
                default_league = $2 WHERE excluded.guild_id = $1"""
        await self.bot.db.execute(sql, gid, competition.id, timeout=60)

    # UNIVERAL commands.
    @discord.app_commands.command()
    @discord.app_commands.rename(obj="search")
    @discord.app_commands.describe(obj="Team, Competition, or Fixture")
    async def table(self, interaction: Interaction, obj: fs.universal) -> None:
        """Fetch a table for a team, competition, or fixture"""
        page = await self.bot.browser.new_page()
        view = FSView(interaction.user, page, obj)
        await StandingsView.start(interaction, page, obj, view)

    @discord.app_commands.command(name="fixtures")
    @discord.app_commands.rename(obj="search")
    @discord.app_commands.describe(obj="Team or Competition")
    async def fx(self, interaction: Interaction, obj: fs.universal) -> None:
        """Search for upcoming fixtures for a team or competition"""
        assert isinstance(obj, fs.Competition | fs.Team)
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await FXPaginator.start(interaction, page, obj, True)

    @discord.app_commands.command(name="results")
    @discord.app_commands.rename(obj="search")
    @discord.app_commands.describe(obj="Team or Competition")
    async def rx(self, interaction: Interaction, obj: fs.universal) -> None:
        """Search for previous results from a team or competition"""
        assert isinstance(obj, fs.Competition | fs.Team)
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await FXPaginator.start(interaction, page, obj, False)

    @discord.app_commands.command()
    @discord.app_commands.describe(obj="Team or Fixture")
    @discord.app_commands.rename(obj="search")
    async def news(self, interaction: Interaction, obj: fs.universal) -> None:
        """Get the latest news for a team or fixture"""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await FSView(interaction.user, page, obj).news.callback(interaction)

    # FIXTURE commands
    @discord.app_commands.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def stats(self, interaction: Interaction, match: fs.fx_tran) -> None:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await StatsView.start(interaction, page, match, None)

    @discord.app_commands.command(name="lineups")
    @discord.app_commands.describe(match=FIXTURE)
    async def frm(self, interaction: Interaction, match: fs.fx_tran) -> None:
        """Look up the lineups and/or formations for a Fixture."""
        page = await self.bot.browser.new_page()
        view = FSView(interaction.user, page, match)
        await view.frm.callback(interaction)

    @discord.app_commands.command(name="summary")
    @discord.app_commands.describe(match=FIXTURE)
    async def smry(self, interaction: Interaction, match: fs.fx_tran) -> None:
        """Get a summary for a fixture"""
        page = await self.bot.browser.new_page()
        view = FSView(interaction.user, page, match)
        await view.smr.callback(interaction)
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def h2h(self, interaction: Interaction, match: fs.fx_tran) -> None:
        """Lookup the head-to-head details for a Fixture"""
        page = await self.bot.browser.new_page()
        parent = FSView(interaction.user, page, match)
        await H2HView.start(interaction, page, match, parent)

    @discord.app_commands.command()
    @discord.app_commands.describe(team=TEAM_NAME)
    async def squad(self, interaction: Interaction, team: fs.tm_tran) -> None:
        """Lookup a team's squad members"""
        page = await self.bot.browser.new_page()
        view = FSView(interaction.user, page, team)
        await view.squad.callback(interaction)

    @discord.app_commands.command(name="top_scorers")
    @discord.app_commands.rename(obj="competition")
    @discord.app_commands.describe(obj=COMPETITION)
    async def scr(self, interaction: Interaction, obj: fs.cmp_tran) -> None:
        """Get top scorers from a competition."""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await TopScorersView.start(interaction, page, obj)


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(FixturesCog(bot))
