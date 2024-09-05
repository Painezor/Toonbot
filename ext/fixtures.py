"""Lookups of Live Football Data for teams, fixtures, and competitions."""
# TODO: GLOBAL Nuke page.content in favour of locator.inner_html()
# TODO: Fixture => photos
# TODO: Fixture => report
# TODO: Transfers => Dropdowns for Competitions
# TODO: Squad => Enumerate when not sorting by squad number.
# TODO: Standings => Dropdown for Teams
# TODO: File=None in all r()
# TODO: Globally Nuke _ac for Transformers

from __future__ import annotations

import asyncio
import copy
import io
from importlib import reload
import logging
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, overload, cast

import asyncpg
import discord
from discord import Embed, File, Colour, SelectOption
from discord.ext import commands
from discord.ui import Button, Select
from lxml import html
from playwright.async_api import Page

import ext.flashscore as fs
from ext.toonbot_utils.fs_transform import fixture_, universal, comp_, team_
from ext.flashscore.gamestate import GameState
from ext.utils import embed_utils, flags, image_utils, timed_events
from ext.utils.view_utils import (
    BaseView,
    DropdownPaginator,
    PagedItemSelect,
    EmbedPaginator,
)

if TYPE_CHECKING:
    from core import Bot
    from flashscore.abc import BaseCompetition, BaseFixture, BaseTeam

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member


logger = logging.getLogger("Fixtures")

JS = "ads => ads.forEach(x => x.remove());"
TEAM_NAME = "Enter the name of a team to search for"
FIXTURE = "Search for a fixture by team name"
COMPETITION = "Enter the name of a competition to search for"
H2H = Literal["overall", "home", "away"]

YC = fs.YELLOW_CARD_EMOJI
TM = fs.TEAM_EMOJI

sqd_filter_opts = [
    SelectOption(label="Squad #", value="squad_number", emoji="#️⃣"),
    SelectOption(label="Goals", value="goals", emoji=fs.GOAL_EMOJI),
    SelectOption(label="Red Cards", value="reds", emoji=fs.RED_CARD_EMOJI),
    SelectOption(label="Yellow Cards", value="yellows", emoji=YC),
    SelectOption(label="Appearances", value="appearances", emoji=TM),
    SelectOption(label="Age", value="age", emoji=None),
    SelectOption(label="Injury", value="injury", emoji=fs.INJURY_EMOJI),
]


def makeselect(obj: object) -> SelectOption:
    oid = getattr(obj, "id", None)
    ttl = getattr(obj, "title", None)
    if oid is not None and ttl is not None:
        opt = discord.SelectOption(label=ttl, value=oid)
        cmp = getattr(obj, "competition", None)
        if cmp is not None:
            cmp = cast(fs.abc.BaseCompetition, cmp)
            opt.description = cmp.title

        ctry = getattr(obj, "country", None)
        if ctry:
            opt.emoji = flags.get_flag(ctry)
        else:
            opt.emoji = getattr(obj, "emoji", None)
        return opt

    opt = discord.SelectOption(label="MISSING")

    if isinstance(obj, fs.SquadMember):
        opt.label = obj.player.name
        opt.emoji = fs.PLAYER_EMOJI
    return opt


def fmt_scorer(scorer: fs.TopScorer) -> str:
    text = f"`{str(scorer.rank).rjust(3)}.` {fs.GOAL_EMOJI} {scorer.goals}"
    if scorer.assists:
        text += f" (+{scorer.assists})"

    pmd = f"[{scorer.player.name}]({scorer.player.url})"
    flag = " ".join(flags.get_flags(scorer.player.country))
    text += f" {flag} {pmd}"
    if scorer.team:
        text += f" ([{scorer.team.name}]({scorer.team.url}))"
    return text


def fmt_squad(sqd: fs.SquadMember) -> str:
    """Return a row representing the Squad Member"""
    plr = sqd.player
    pos = sqd.position
    pmd = f"[{plr.name}]({plr.url})"

    flag = ", ".join(flags.get_flags(plr.country))
    text = f"`#{sqd.squad_number}` {flag} {pmd} ({pos}): "

    if sqd.goals:
        text += f" {fs.GOAL_EMOJI} {sqd.goals}"
    if sqd.appearances:
        text += f" {fs.TEAM_EMOJI} {sqd.appearances}"
    if sqd.reds:
        text += f" {fs.RED_CARD_EMOJI} {sqd.reds}"
    if sqd.yellows:
        text += f" {fs.YELLOW_CARD_EMOJI} {sqd.yellows}"
    if sqd.injury:
        text += f" {fs.INJURY_EMOJI} {sqd.injury}"
    return text


class FSEmbed(Embed):
    _colours: dict[str, Colour | int] = {}

    def __init__(
        self,
        obj: BaseFixture | BaseTeam | BaseCompetition,
    ) -> None:
        super().__init__()

        self.obj = obj
        # Handling of logourl
        self.set_thumbnail(url=obj.logo_url)
        self.set_author(name=obj.title, url=obj.url, icon_url=obj.logo_url)

    async def set_colour(self) -> None:
        """Get and set the colour of the embed based on current logo"""
        if self.obj.id is None:
            return
        color = FSEmbed._colours.get(self.obj.id, None)

        if color is None and self.thumbnail.url:
            color = await embed_utils.get_colour(self.thumbnail.url)
            FSEmbed._colours.update({self.obj.id: color})
        self.color = color

    @overload
    @classmethod
    async def create(cls, obj: BaseFixture) -> FixtureEmbed:
        ...

    @overload
    @classmethod
    async def create(cls, obj: BaseTeam) -> TeamEmbed:
        ...

    @overload
    @classmethod
    async def create(cls, obj: BaseCompetition) -> CompetitionEmbed:
        ...

    @classmethod
    async def create(cls, obj: Any) -> Embed:
        """Create an embed based upon what type of fsobject is passed"""

        embed = cls(obj)
        await embed.set_colour()

        if isinstance(obj, fs.abc.BaseCompetition):
            return await CompetitionEmbed.extend(obj, embed)

        if isinstance(obj, fs.abc.BaseTeam):
            return await TeamEmbed.extend(obj, embed)

        if isinstance(obj, fs.abc.BaseFixture):
            return await FixtureEmbed.extend(obj, embed)

        raise ValueError("incorrect argument passed %s", type(obj))


class TeamEmbed(Embed):
    @classmethod
    async def extend(cls, team: BaseTeam, embed: Embed) -> Embed:
        return embed


class CompetitionEmbed(Embed):
    @classmethod
    async def extend(cls, competition: BaseCompetition, embed: Embed) -> Embed:
        return embed


class FixtureEmbed(Embed):
    @classmethod
    async def extend(cls, fixture: BaseFixture, embed: Embed) -> Embed:
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

        if fixture.get_time() is None:
            return embed

        elif fixture.get_time() == GameState.SCHEDULED:
            time = timed_events.Timestamp(fixture.kickoff).time_relative
            embed.description = f"Kickoff: {time}"
        elif fixture.get_time() == GameState.POSTPONED:
            embed.description = "This match has been postponed."

        if fixture.competition:
            embed.set_footer(
                text=f"{fixture.get_time()} | {fixture.competition.title}"
            )
        else:
            embed.set_footer(text=fixture.get_time())
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

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Fixture,
        parent: FSView | None = None,
    ) -> None:
        """Start a stats view and fetch by fetching the appropraite data"""
        if not interaction.response.is_done():
            await interaction.response.defer()

        stats = await obj.get_stats(page)

        if parent is None:
            parent = FSView(interaction.user, page, obj)
        await parent.handle_buttons()

        embed = await FSEmbed.create(obj)
        embed.title = "Stats"
        view = cls(interaction.user, page, obj, parent=parent)
        await view.handle_buttons()

        embed.description = cls.parse_stats(stats)
        await interaction.edit_original_response(embed=embed, view=view)
        view.message = await interaction.original_response()
        parent.message = await interaction.original_response()

    @staticmethod
    def parse_stats(stats: list[fs.fixture.MatchStat]) -> str:
        if not stats:
            return "Could not find stats for this game."

        dsc: list[str] = []
        for i in stats:
            home = i.home.rjust(4)
            label = i.label.center(19)
            away = i.away.ljust(4)
            dsc.append(f"{home} [{label}] {away}")
        return "```ini\n" + "\n".join(dsc) + "```"

    async def handle_buttons(self) -> None:
        """Add sub page buttons."""
        cur = [i.label for i in self.children if isinstance(i, Button)]

        for i in await self.page.locator(".subTabs > a").all():
            text = await i.text_content()
            # TODO: Change locator to subTabs > a or working variation.
            logger.info("DEBUG %s", text)
            if not text:
                continue

            if text not in cur:
                self.add_item(StatsButton(text))

        bt = [i for i in self.children if isinstance(i, Button)]
        btns = [f"{i.label} / {i.custom_id}" for i in bt]
        logger.info("Current buttons %s", ", ".join(btns))


class StatsButton(Button[StatsView]):
    def __init__(self, label: str) -> None:
        super().__init__(label=label)

    async def callback(self, interaction: Interaction) -> None:
        """A button that requests a subpage"""
        assert self.view is not None
        stats = await self.view.fixture.get_stats(self.view.page, self.label)
        embed = await FSEmbed.create(self.view.fixture)

        embed.description = self.view.parse_stats(stats)
        embed.title = f"Stats ({self.label})"
        view = self.view
        return await interaction.response.edit_message(view=view, embed=embed)


class StandingsView(BaseView):
    def __init__(
        self,
        invoker: User,
        page: Page,
        item: fs.Team | fs.Competition | fs.Fixture,
        teams: list[BaseTeam] = [],
        *,
        parent: BaseView | None = None,
        timeout: float | None = 180,
    ):
        super().__init__(invoker, parent=parent, timeout=timeout)
        self.page: Page = page
        self.object: fs.Team | fs.Competition | fs.Fixture = item
        self.teams: list[fs.abc.BaseTeam] = teams
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

        table = await obj.get_table(page, cache=interaction.client.cache)
        view = cls(interaction.user, page, obj, parent=parent)

        for i in await page.locator(".subTabs > a").all():
            text = await i.text_content()

            logger.info("Subtab text content %s", text)

            if not text:
                continue

            button = copy.copy(view.subtable)
            button.label = text
            view.add_item(button)

        if table is not None:
            atts = [File(fp=io.BytesIO(table.image), filename="standings.png")]
            view.dropdown.options = [makeselect(i) for i in table.teams]
            view.teams = table.teams
        else:
            view.remove_item(view.dropdown)
            atts = []

        if not view.dropdown.options:
            view.remove_item(view.dropdown)

        embed.set_image(url="attachment://standings.png")
        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        await edit(view=view, embed=embed, attachments=atts)
        view.message = await interaction.original_response()

    @discord.ui.button(label="Subtable")
    async def subtable(
        self, interaction: Interaction, btn: Button[StandingsView]
    ) -> None:
        cache = interaction.client.cache
        table = await self.object.get_table(self.page, btn.label, cache)
        embed = await FSEmbed.create(self.object)
        embed.title = f"Standings ({btn.label})"
        if table is not None:
            file = File(fp=io.BytesIO(table.image), filename="standings.png")
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

    @discord.ui.select(placeholder="Go to Team")
    async def dropdown(self, interaction: Interaction, sel: Select) -> None:
        """Go to a team's view."""
        await interaction.response.defer()
        base = next(i for i in self.teams if i.id in sel.values)
        team = fs.Team.parse_obj(base)
        await RXPaginator.start(interaction, self.page, team, parent=self)


class SquadView(DropdownPaginator):
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
        options = [makeselect(i) for i in players]
        rows = [fmt_squad(i) for i in players]

        sqd_opts = sqd_filter_opts
        super().__init__(invoker, embed, rows, options, 40, **kwargs)

    @discord.ui.select(row=1, placeholder="View Player", disabled=True)
    async def dropdown(self, itr: Interaction, sel: Select) -> None:
        """Go to specified player"""
        raise NotImplementedError
        # player = next(i for i in self.players if i.player.name in sel.values)
        # view = ItemView(itr.user, self.page, player.player)
        # await itr.response.edit_message(view=view)

    @discord.ui.select(row=2, placeholder="Sort Players")
    async def srt(self, itr: Interaction, sel: Select) -> None:
        """Change the sort mode of the view"""
        attr = sel.values[0]
        reverse = attr in ["goals", "yellows", "reds"]
        self.players.sort(key=lambda i: getattr(i, attr), reverse=reverse)
        emb = await FSEmbed.create(self.team)
        emb.set_footer(text=f"Sorted by {attr.replace('_', ' ').title()}")
        par = self.parent
        plr = self.players
        view = SquadView(itr.user, self.page, emb, self.team, plr, parent=par)
        await itr.response.edit_message(view=view, embed=view.embeds[0])

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


class FXPaginator(DropdownPaginator):
    """Paginate Fixtures, with a dropdown that goes to a specific game."""

    _title = "Fixtures"

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        fixtures: list[fs.abc.BaseFixture],
        parent: BaseView | None = None,
    ) -> None:
        self.page: Page = page

        options = [makeselect(i) for i in fixtures]
        rows: list[str] = []
        self.fixtures = fixtures
        for i in fixtures:
            if i.id is None:
                logger.error("%s fixture with no id passed", i.__dict__)
                continue

            timestamp = timed_events.Timestamp(i.kickoff).relative
            rows.append(f"{timestamp} [{i.score_line}]({i.url})")

        embed.title = self.__class__._title
        logger.info("%s fixtures, %s options", len(fixtures), len(options))
        super().__init__(invoker, embed, rows, options, 10, parent=parent)

        if not fixtures:
            self.remove_item(self.dropdown)

    @staticmethod
    async def get(
        obj: fs.Team | fs.Competition, page: Page, cache: fs.FSCache
    ) -> list[fs.abc.BaseFixture]:
        return await obj.fixtures(page, cache)

    @classmethod
    async def start(
        cls,
        interaction: Interaction,
        page: Page,
        obj: fs.Competition | fs.Team,
        parent: BaseView | None = None,
    ) -> None:
        """Generate & return a FixtureBrowser asynchronously"""
        if parent is None:
            parent = FSView(interaction.user, page, obj)
            await parent.handle_buttons()

        embed = await FSEmbed.create(obj)

        # Results or Fixtures based on whether
        games = await cls.get(obj, page, interaction.client.cache)
        view = cls(interaction.user, page, embed, games, parent)

        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        await edit(view=view, embed=view.embeds[0], attachments=[])

        view.message = await interaction.original_response()
        parent.message = view.message

    @discord.ui.select(placeholder="Go to Fixture")
    async def dropdown(self, itr: Interaction, sel: Select) -> None:
        """Go to Fixture"""
        fix = next(i for i in self.fixtures if i.id in sel.values)
        fix = fs.Fixture.parse_obj(fix)
        await FSView(itr.user, self.page, fix).stats.callback(itr)


class RXPaginator(FXPaginator):
    _title = "Results"

    @staticmethod
    async def get(
        obj: fs.Team | fs.Competition, page: Page, cache: fs.FSCache
    ) -> list[fs.abc.BaseFixture]:
        return await obj.results(page, cache)


class TopScorersView(DropdownPaginator):
    """View for handling top scorers."""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        scorers: list[fs.TopScorer],
        parent: BaseView | None,
        nt_flt: list[str] | None = None,
        tm_flt: list[fs.abc.BaseTeam] | None = None,
    ):
        self.nationality_filter = nt_flt if nt_flt is not None else []
        self.team_filter = tm_flt if tm_flt is not None else []
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

            rows.append(fmt_scorer(i))
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
        await edit(view=view, embed=view.embeds[0])

    @discord.ui.select(placeholder="Go to Player", disabled=True)
    async def dropdown(self, itr: Interaction, select: Select) -> None:
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

        view = PagedItemSelect(interaction.user, options)
        await interaction.response.edit_message(view=view)
        await view.wait()

        nt_flt = list(view.values)

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
        emb = new.embeds[0]
        await view.interaction.response.edit_message(view=new, embed=emb)

    @discord.ui.button(label="Filter: Team", emoji=fs.TEAM_EMOJI, row=4)
    async def teamfilt(self, interaction: Interaction, _) -> None:
        """Generate a team filter dropdown"""
        teams: list[fs.abc.BaseTeam] = []
        for i in self.scorers:
            if i.team in self.team_filter and i.team not in teams:
                teams.append(i.team)
        teams.sort(key=lambda i: i.title)
        opts: list[discord.SelectOption] = [makeselect(i) for i in teams]

        view = PagedItemSelect(interaction.user, opts)
        emb = view.embeds[0]
        await interaction.response.edit_message(view=view, embed=emb)
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
        emb = new.embeds[0]
        await view.interaction.response.edit_message(view=new, embed=emb)


class TransfersView(DropdownPaginator):
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
        options: list[SelectOption] = []
        for i in transfers:
            _ = fs.INBOUND_EMOJI if i.direction == "in" else fs.OUTBOUND_EMOJI
            opt = discord.SelectOption(label=i.player.name, emoji=_)
            if i.team is not None:
                opt.description = i.team.name
            options.append(opt)

            pmd = f"[{i.player.name}]({i.player.url})"
            tmd = f"[{i.team.name}]({i.team.url})" if i.team else "Free Agent"
            date = timed_events.Timestamp(i.date).date
            rows.append(f"{pmd} {_} {tmd}\n{date} {i.type}\n")

        teams: list[fs.BaseTeam] = []
        for i in transfers:
            if i.team not in teams and i.team is not None:
                teams.append(i.team)

        team_sel: list[discord.SelectOption] = []
        team_sel = [makeselect(i) for i in teams]
        self.tm_dropdown.options = team_sel

        super().__init__(invoker, embed, rows, options, 5, **kwargs)

        self.teams: list[fs.abc.BaseTeam] = teams
        self.team: fs.Team = team
        self.page: Page = page
        self.transfers: list[fs.FSTransfer] = transfers

    @discord.ui.select(placeholder="Go to Player", disabled=True)
    async def dropdown(self, itr: Interaction, sel: Select) -> None:
        """First Dropdown: Player"""
        await itr.response.defer()
        player = next(i for i in self.transfers if i.player.name in sel.values)
        logger.info(player)
        raise NotImplementedError

    @discord.ui.select(placeholder="Go to Team")
    async def tm_dropdown(self, interaction: Interaction, sel: Select) -> None:
        """Second Dropdown: Team"""
        base = next(i for i in self.teams if i.url in sel.values)
        team = fs.Team.parse_obj(base)
        await RXPaginator.start(interaction, self.page, team, self)

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
        emb = view.embeds[0]
        await interaction.response.edit_message(view=view, embed=emb)

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


class ArchiveSelect(DropdownPaginator):
    """Dropdown to Select a previous Season for a competition"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        embed: Embed,
        rows: list[str],
        options: list[discord.SelectOption],
        archives: list[BaseCompetition],
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
        seasons: list[fs.abc.BaseCompetition] = []
        rows: list[str] = []
        for i in tree.xpath('.//div[@class="archive__row"]'):
            # Get Archive as Competition
            xpath = ".//div[@class='archive__season']/a"
            name = "".join(i.xpath(xpath + "/text()")).strip()
            link = "".join(i.xpath(xpath + "/@href")).strip()

            link = fs.FLASHSCORE + "/" + link.strip("/")

            ctry = obj.country
            season = fs.abc.BaseCompetition(name=name, country=ctry, url=link)
            seasons.append(season)
            rows.append(f"[{season.name}]({season.url})")

            opt = discord.SelectOption(label=name, value=link)
            if ctry is not None:
                opt.emoji = flags.get_flag(ctry)
            # Get Winner
            xpath = ".//div[@class='archive__winner']//a"
            tm_name = "".join(i.xpath(xpath + "/text()")).strip()
            if tm_name:
                opt.description = f"🏆 Winner: {tm_name}"
            options.append(opt)
        invoker = interaction.user
        return ArchiveSelect(invoker, page, embed, rows, options, seasons)

    @discord.ui.select(placeholder="Select Previous Year")
    async def dropdown(self, itr: Interaction, sel: Select) -> None:
        """Spawn a new View for the Selected Season"""
        base = next(i for i in self.archives if i.url in sel.options)
        comp = fs.Competition.parse_obj(base)
        embed = await FSEmbed.create(comp)
        view = FSView(itr.user, self.page, comp, parent=self)
        await itr.response.edit_message(view=self, embed=embed)
        view.message = await itr.original_response()


class H2HView(BaseView):
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

    async def add_buttons(self) -> None:
        """Generate a button for each subtab found."""
        btns = [i.label for i in self.children if isinstance(i, Button)]
        for i in await self.page.locator(".subTabs > a").all():
            if not (text := await i.text_content()) or text in btns:
                continue
            self.add_item(H2HButton(text))

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

        rows = await fixture.get_h2h(page)
        embed = await FSEmbed.create(fixture)
        embed.title = "Head to Head"
        embed.description = ""

        for i in rows:
            ts = timed_events.Timestamp(i.kickoff).relative
            text = f"{ts} {i.home} {i.score} {i.away}\n"
            embed.description += text

        await edit(view=view, embed=embed)
        view.message = await interaction.original_response()
        parent.message = view.message


class H2HButton(Button[H2HView]):
    def __init__(self, label: str) -> None:
        super().__init__(label=label)

    async def callback(self, interaction: Interaction) -> None:
        """A button to go to a subpage of a HeadToHeadView"""
        assert self.view is not None
        rows = await self.view.fixture.get_h2h(self.view.page, self.label)
        embed = await FSEmbed.create(self.view.fixture)
        embed.title = f"Head to Head ({self.label})"

        embed.description = ""

        for i in rows:
            ts = timed_events.Timestamp(i.kickoff).relative
            text = f"{ts} {i.home} {i.score} {i.away}\n"
            embed.description += text

        await interaction.response.edit_message(view=self.view, embed=embed)


class FSView(BaseView):
    """A Generic for Fixture/Team/Competition Views"""

    def __init__(
        self,
        invoker: User,
        page: Page,
        obj: fs.Team | fs.Competition | fs.Fixture,
        **kwargs: Any,
    ) -> None:
        super().__init__(invoker, **kwargs)
        reload(fs)
        self.page: Page = page
        self.object: fs.Team | fs.Competition | fs.Fixture = obj

        # Remove these, we add them back later.
        self.clear_items()

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
                    "Draw": self.tbl,
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
        emb = view.embeds[0]
        await interaction.response.edit_message(view=view, embed=emb)

    # Fixture Only
    @discord.ui.button(label="Head to Head", emoji="⚔")
    async def h2h(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Get results of recent games for each team in the fixture"""
        if isinstance(self.object, fs.Competition | fs.Team):
            raise NotImplementedError
        await H2HView.start(interaction, self.page, self.object, self)

    # Competition, Team
    @discord.ui.button(label="Fixtures", emoji="🗓️")
    async def fx(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push upcoming competition fixtures to View"""
        if isinstance(self.object, fs.Fixture):
            raise NotImplementedError
        obj = self.object
        await FXPaginator.start(interaction, self.page, obj, self)

    # Fixture Only
    @discord.ui.button(label="Lineups", emoji="🧑‍🤝‍🧑")
    async def frm(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push Lineups & Formations Image to view"""
        if isinstance(self.object, fs.Competition | fs.Team):
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
        if isinstance(self.object, fs.Competition | fs.Team):
            raise NotImplementedError

        embed = await FSEmbed.create(self.object)
        embed.title = "Photos"

        photos = await self.object.get_photos(self.page)

        embeds: list[Embed] = []
        for i in photos:
            emb = embed.copy()
            emb.description = i.description
            emb.set_image(url=i.url)
            embeds.append(emb)

        view = EmbedPaginator(interaction.user, embeds, parent=self)
        await interaction.response.edit_message(view=view, embed=embeds[0])

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
            embed.set_image(url=i.image)
            embed.set_footer(text=i.provider)
            embed.title = i.title
            embeds.append(embed)

        if not embeds:
            embed = base_embed
            embed.description = "No News Articles found."
            embeds = [embed]

        await self.handle_buttons()
        view = EmbedPaginator(interaction.user, embeds, parent=self)

        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        await edit(view=view, embed=embeds[0])

    # Fixture Only
    @discord.ui.button(label="Report", emoji="📰")
    async def report(
        self, interaction: Interaction, _: Button[FSView]
    ) -> None:
        """Get the report in text format."""
        if isinstance(self.object, fs.Competition | fs.Team):
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
        embeds = embed_utils.rows_to_embeds(embed, content, 5, 2500)
        await self.handle_buttons()
        view = EmbedPaginator(interaction.user, embeds, parent=self)
        await interaction.response.edit_message(view=view, embed=embeds[0])

    # Competition, Team
    @discord.ui.button(label="Results", emoji="📋")
    async def results(
        self, interaction: Interaction, _: Button[FSView]
    ) -> None:
        """Push Previous Results Team View"""
        if isinstance(self.object, fs.Fixture):
            raise NotImplementedError

        obj = self.object
        await RXPaginator.start(interaction, self.page, obj, self)

    # Competition, Team
    @discord.ui.button(label="Top Scorers", emoji=fs.GOAL_EMOJI)
    async def top_scorers(
        self, interaction: Interaction, _: Button[FSView]
    ) -> None:
        """Push Scorers to View"""
        if isinstance(self.object, fs.Fixture):
            raise NotImplementedError
        await TopScorersView.start(interaction, self.page, self.object, self)

    # Team Only
    @discord.ui.button(label="Squad", emoji="🧑‍🤝‍🧑")
    async def squad(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Get the squad of the team, filter or sort, push to view"""
        if isinstance(self.object, fs.Fixture | fs.Competition):
            raise NotImplementedError

        view = await SquadView.create(interaction, self.page, self.object)
        emb = view.embeds[0]
        await interaction.response.edit_message(view=view, embed=emb)

    # Team only
    @discord.ui.button(label="Transfers", emoji=fs.OUTBOUND_EMOJI)
    async def trns(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Get a list of the team's recent transfers."""
        if isinstance(self.object, fs.Competition | fs.Fixture):
            raise NotImplementedError

        view = await TransfersView.start(interaction, self.page, self.object)
        edit = interaction.response.edit_message
        return await edit(embed=view.embeds[0], view=self, attachments=[])

    # Competition, Fixture, Team
    @discord.ui.button(label="Standings", emoji="🏅")
    async def tbl(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Send Specified Table to view"""
        await StandingsView.start(interaction, self.page, self.object, self)

    # Fixture Only
    @discord.ui.button(label="Stats")
    async def stats(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Push Stats to View"""
        if isinstance(self.object, fs.Competition | fs.Team):
            raise NotImplementedError
        await StatsView.start(interaction, self.page, self.object)

    # Fixture Only
    @discord.ui.button(label="Summary")
    async def smr(self, interaction: Interaction, _: Button[FSView]) -> None:
        """Fetch the summary of a Fixture as a text formatted embed"""
        if isinstance(self.object, fs.Competition | fs.Team):
            raise NotImplementedError

        await self.object.fetch(self.page)

        assert self.object.competition is not None
        if self.object.competition.url is None:
            id_ = self.object.competition.id
            cmp = interaction.client.cache.get_competition(id=id_)
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
        if isinstance(self.object, fs.Competition | fs.Team):
            raise NotImplementedError

        url = f"{self.object.url}/#/video"
        await self.page.goto(url, timeout=5000)
        await self.handle_buttons()

        url = await self.page.locator("object").get_attribute("data")
        if url is not None:
            url = url.replace("embed/", "watch?v=")

        edit = interaction.response.edit_message
        return await edit(content=url, embed=None, attachments=[], view=self)


@overload
def get_full_obj(item: BaseFixture) -> fs.Fixture:
    ...


@overload
def get_full_obj(item: BaseCompetition) -> fs.Competition:
    ...


@overload
def get_full_obj(item: BaseTeam) -> fs.Team:
    ...


def get_full_obj(item: ...) -> ...:
    if isinstance(item, fs.abc.BaseFixture):
        return fs.Fixture.parse_obj(item)
    elif isinstance(item, fs.abc.BaseTeam):
        return fs.Team.parse_obj(item)
    elif isinstance(item, fs.abc.BaseCompetition):
        return fs.Competition.parse_obj(item)


class FixturesCog(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        reload(fs)
        self.bot: Bot = bot
        self.fixture_defaults: list[asyncpg.Record] = []

    async def cog_load(self) -> None:
        """When cog loads, load up our defaults cache"""
        await self.update_cache()

    async def update_cache(self) -> None:
        """Cache our fixture defaults."""
        sql = """SELECT * FROM FIXTURES_DEFAULTS"""
        self.fixture_defaults = await self.bot.db.fetch(sql, timeout=10)

    # UNIVERAL commands.
    @discord.app_commands.command()
    @discord.app_commands.rename(obj="search")
    @discord.app_commands.describe(obj="Team, Competition, or Fixture")
    async def table(self, interaction: Interaction, obj: universal) -> None:
        """Fetch a table for a team, competition, or fixture"""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()

        obj = get_full_obj(obj)
        view = FSView(interaction.user, page, obj)
        await StandingsView.start(interaction, page, obj, view)

    # Group Commands for those with multiple available subcommands.
    default = discord.app_commands.Group(
        name="default",
        guild_only=True,
        description="Set the server's default team and competition.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @default.command(name="team")
    @discord.app_commands.describe(team=TEAM_NAME)
    async def d_team(self, interaction: Interaction, team: team_) -> None:
        """Set the default team for your flashscore lookups"""
        embed = await FSEmbed.create(team)

        md = f"[{team.name}]({team.url})"
        embed.description = f"Commands will use default team {md}"

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
        self, interaction: Interaction, competition: comp_
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

    @discord.app_commands.command(name="fixtures")
    @discord.app_commands.rename(obj="search")
    @discord.app_commands.describe(obj="Team or Competition")
    async def fx(self, interaction: Interaction, obj: universal) -> None:
        """Search for upcoming fixtures for a team or competition"""
        assert not isinstance(obj, fs.abc.BaseFixture)
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await FXPaginator.start(interaction, page, get_full_obj(obj))

    @discord.app_commands.command(name="results")
    @discord.app_commands.rename(obj="search")
    @discord.app_commands.describe(obj="Team or Competition")
    async def rx(self, interaction: Interaction, obj: universal) -> None:
        """Search for previous results from a team or competition"""
        assert not isinstance(obj, fs.abc.BaseFixture)
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await RXPaginator.start(interaction, page, get_full_obj(obj))

    @discord.app_commands.command()
    @discord.app_commands.describe(obj="Team or Fixture")
    @discord.app_commands.rename(obj="search")
    async def news(self, interaction: Interaction, obj: universal) -> None:
        """Get the latest news for a team or fixture"""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        obj = get_full_obj(obj)
        await FSView(interaction.user, page, obj).news.callback(interaction)

    # FIXTURE commands
    @discord.app_commands.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def stats(self, interaction: Interaction, match: fixture_) -> None:
        """Look up the stats for a fixture."""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        await StatsView.start(interaction, page, get_full_obj(match), None)

    @discord.app_commands.command(name="lineups")
    @discord.app_commands.describe(match=FIXTURE)
    async def frm(self, interaction: Interaction, match: fixture_) -> None:
        """Look up the lineups and/or formations for a Fixture."""
        page = await self.bot.browser.new_page()
        view = FSView(interaction.user, page, get_full_obj(match))
        await view.frm.callback(interaction)

    @discord.app_commands.command(name="tv")
    @discord.app_commands.describe(match=FIXTURE)
    async def tv(self, interaction: Interaction, match: fixture_) -> None:
        """Find the TV information for a fixture"""
        embed = FSEmbed(match)

        if match.tv:
            tv = ", ".join(f"[{i.name}]({i.link})" for i in match.tv)
            embed.description = tv
        else:
            embed.description = "Could not find TV Info for this fixture"
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="summary")
    @discord.app_commands.describe(match=FIXTURE)
    async def smry(self, interaction: Interaction, match: fixture_) -> None:
        """Get a summary for a fixture"""
        page = await self.bot.browser.new_page()
        view = FSView(interaction.user, page, get_full_obj(match))
        await view.smr.callback(interaction)
        view.message = await interaction.original_response()

    @discord.app_commands.command()
    @discord.app_commands.describe(match=FIXTURE)
    async def h2h(self, interaction: Interaction, match: fixture_) -> None:
        """Lookup the head-to-head details for a Fixture"""
        page = await self.bot.browser.new_page()
        match = get_full_obj(match)
        parent = FSView(interaction.user, page, match)
        await H2HView.start(interaction, page, match, parent)

    @discord.app_commands.command()
    @discord.app_commands.describe(team=TEAM_NAME)
    async def squad(self, interaction: Interaction, team: team_) -> None:
        """Lookup a team's squad members"""
        page = await self.bot.browser.new_page()
        team = get_full_obj(team)
        view = FSView(interaction.user, page, team)
        await view.squad.callback(interaction)

    @discord.app_commands.command(name="top_scorers")
    @discord.app_commands.rename(obj="competition")
    @discord.app_commands.describe(obj=COMPETITION)
    async def scr(self, interaction: Interaction, obj: comp_) -> None:
        """Get top scorers from a competition."""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        obj = get_full_obj(obj)
        await TopScorersView.start(interaction, page, obj)


async def setup(bot: Bot):
    """Load the fixtures Cog into the bot"""
    await bot.add_cog(FixturesCog(bot))
