"""Lookups of Live Football Data for teams, fixtures, and competitions."""
import datetime
import typing
from copy import deepcopy
from importlib import reload

# D.py
import discord
from discord.ext import commands

# Custom Utils
from ext.utils import browser, timed_events, transfer_tools, football, embed_utils, image_utils, view_utils

# How many minutes a user has to wait between refreshes of the table within a command.
IMAGE_UPDATE_RATE_LIMIT = 1

# Long ass strings.
DF = "Use `.tb default team <team name>` to set a default team\nUse `.tb default league <league name>` to set a " \
     "default league.\n\nThis will allow you to skip the selection process to get information about your favourites."
INJURY_EMOJI = "<:injury:682714608972464187>"


class LeagueTableSelect(discord.ui.Select):
    """Push a Specific League Table"""

    def __init__(self, objects):
        self.objects = objects
        super().__init__(placeholder="Select which league to get table from...")
        for num, _ in enumerate(objects):
            self.add_option(label=_.full_league, emoji='🏆', description=_.url, value=str(num))

    async def callback(self, interaction):
        """Upon Item Selection do this"""
        await interaction.response.defer()
        await self.view.push_table(self.objects[int(self.values[0])])


class CompetitionView(discord.ui.View):
    """The view sent to a user about a Competition"""

    def __init__(self, ctx, competition: football.Competition, page):
        super().__init__()
        self.page = page
        self.ctx = ctx
        self.competition = competition
        self.message = None
        self.players = []

        # Embed and internal index.
        self.base_embed = None
        self.pages = []
        self.index = 0

        # Button Disabling
        self._current_mode = None

        # Player Filtering
        self.nationality_filter = None
        self.team_filter = None
        self.filter_mode = "goals"

        # Rate Limiting
        # TODO: Migrate Timestamping to Bot Var
        self.table_timestamp = None
        self.table_image = None

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.ctx.author.id

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            return
        finally:
            self.stop()

    async def update(self):
        """Update the view for the Competition"""
        if self.filter_mode is not None:
            await self.filter_players()

        await self.generate_buttons()
        embed = self.pages[self.index]
        try:
            await self.message.edit(content="", view=self, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            self.stop()
            return
        self.clear_items()
        await self.wait()

    async def generate_buttons(self):
        """Add our View's Buttons"""
        self.clear_items()

        if len(self.pages) > 0:
            _ = view_utils.PreviousButton()
            _.disabled = True if self.index == 0 else False
            self.add_item(_)

            _ = view_utils.PageButton()
            _.label = f"Page {self.index + 1} of {len(self.pages)}"
            _.disabled = True if len(self.pages) == 1 else False
            self.add_item(_)

            _ = view_utils.NextButton()
            _.disabled = True if self.index == len(self.pages) - 1 else False
            self.add_item(_)

        items = [view_utils.Button(label="Table", func=self.push_table, row=3),
                 view_utils.Button(label="Scorers", func=self.push_scorers, emoji='⚽', row=3),
                 view_utils.Button(label="Fixtures", func=self.push_fixtures, emoji='📆', row=3),
                 view_utils.Button(label="Results", func=self.push_results, emoji='⚽', row=3),
                 view_utils.StopButton()
                 ]

        if self.filter_mode is not None:
            all_players = [('👕', str(i.team), str(i.team_url)) for i in self.players]
            teams = set(all_players)
            teams = sorted(teams, key=lambda x: x[1])  # Sort by second Value.

            if len(teams) < 26:
                _ = view_utils.MultipleSelect(placeholder="Filter by Team...", options=teams, attribute='team_filter')
                if self.team_filter is not None:
                    _.placeholder = f"Teams: {', '.join(self.team_filter)}"
                self.add_item(_)

            flags = set([(transfer_tools.get_flag(i.country, unicode=True), i.country, "") for i in self.players])
            flags = sorted(flags, key=lambda x: x[1])  # Sort by second Value.

            if len(flags) < 26:
                ph = "Filter by Nationality..."
                _ = view_utils.MultipleSelect(placeholder=ph, options=flags, attribute='nationality_filter')
                if self.nationality_filter is not None:
                    _.placeholder = f"Countries:{', '.join(self.nationality_filter)}"
                self.add_item(_)

        for _ in items:
            self.add_item(_)
            _.disabled = True if self._current_mode == _.label else False

    async def filter_players(self):
        """Filter player list according to dropdowns."""
        embed = await self.get_embed()
        players = await self.get_players()

        if self.nationality_filter is not None:
            players = [i for i in players if i.country in self.nationality_filter]
        if self.team_filter is not None:
            players = [i for i in players if i.team in self.team_filter]

        if self.filter_mode == "goals":
            srt = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
            embed.title = f"≡ Top Scorers for {embed.title}"
            rows = [i.scorer_row for i in srt]
        elif self.filter_mode == "assists":
            srt = sorted([i for i in players if i.assists > 0], key=lambda x: x.assists, reverse=True)
            embed.title = f"≡ Top Assists for {embed.title}"
            rows = [i.assist_row for i in srt]
        else:
            rows = []

        embeds = embed_utils.rows_to_embeds(embed, rows, rows_per=None)
        self.pages = embeds

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.competition.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)

    async def get_players(self):
        """Grab the list of players"""
        self.players = await self.competition.get_scorers(page=self.page) if not self.players else self.players
        return self.players

    async def push_table(self):
        """Push Table to View"""
        dtn = datetime.datetime.now()
        ts = self.table_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.competition.get_table(page=self.page)
            self.table_image = await image_utils.dump_image(self.ctx, img)
            self.table_timestamp = datetime.datetime.now()

        embed = await self.get_embed()
        embed.clear_fields()
        embed.title = f"≡ Table for {self.competition.title}"
        if self.table_image is not None:
            embed.set_image(url=self.table_image)
            embed.description = timed_events.Timestamp().long
        else:
            embed.description = "No Table Found"

        self.pages = [embed]
        self.index = 0
        self._current_mode = "Table"
        self.filter_mode = None
        await self.update()

    async def push_scorers(self):
        """PUsh the Scorers Embed to View"""
        self.index = 0
        self.filter_mode = "goals"
        self._current_mode = "Scorers"
        self.nationality_filter = None
        self.team_filter = None
        await self.update()

    async def push_assists(self):
        """PUsh the Scorers Embed to View"""
        self.index = 0
        self.filter_mode = "assists"
        self._current_mode = "Assists"
        await self.update()

    async def push_fixtures(self):
        """Push upcoming competition fixtures to View"""
        rows = await self.competition.get_fixtures(page=self.page, subpage='/fixtures')
        rows = [str(i) for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Fixtures for {self.competition.title}"
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Fixtures"
        self.filter_mode = None
        await self.update()

    async def push_results(self):
        """Push results fixtures to View"""
        rows = await self.competition.get_fixtures(page=self.page, subpage='/results')
        rows = [str(i) for i in rows] if rows else ["No Results Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Results for {self.competition.title}"
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Results"
        self.filter_mode = None
        await self.update()


class TeamView(discord.ui.View):
    """The View sent to a user about a Team"""

    def __init__(self, ctx, team: football.Team, page):
        super().__init__()
        self.page = page  # Browser Page
        self.team = team
        self.ctx = ctx
        self.message = None

        # Pagination
        self.pages = []
        self.index = 0
        self.value = None
        self._current_mode = None

        # Specific Selection
        self._currently_selecting = []

        # Fetch Once Objects
        self.base_embed = None
        self.players = None

        # Image Rate Limiting.
        # TODO: Migrate Timestamping to Bot Var
        self.table_image = None
        self.table_timestamp = None

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except discord.NotFound:
            pass
        self.stop()

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.ctx.author.id

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.team.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)  # Do not mutate.

    async def get_players(self):
        """Grab the list of players"""
        self.players = await self.team.get_players(page=self.page) if not self.players else self.players
        return self.players

    async def update(self):
        """Update the view for the user"""
        self.generate_buttons()
        embed = self.pages[self.index] if self.pages else None
        await self.message.edit(content="", view=self, embed=embed, allowed_mentions=discord.AllowedMentions().none())
        await self.wait()

    def generate_buttons(self):
        """Add buttons to the Team embed."""
        self.clear_items()

        if len(self.pages) > 0:
            _ = view_utils.PreviousButton()
            _.disabled = True if self.index == 0 else False
            self.add_item(_)

            _ = view_utils.PageButton()
            _.label = f"Page {self.index + 1} of {len(self.pages)}"
            _.disabled = True if len(self.pages) == 1 else False
            self.add_item(_)

            _ = view_utils.NextButton()
            _.disabled = True if self.index == len(self.pages) - 1 else False
            self.add_item(_)

        if self._currently_selecting:
            self.add_item(LeagueTableSelect(objects=self._currently_selecting))
            self._currently_selecting = []

        buttons = [view_utils.Button(label="Squad", func=self.push_squad),
                   view_utils.Button(label="Injuries", func=self.push_injuries, emoji=INJURY_EMOJI),
                   view_utils.Button(label="Scorers", func=self.push_scorers, emoji='⚽'),
                   view_utils.Button(label="Table", func=self.select_table, row=3),
                   view_utils.Button(label="Fixtures", func=self.push_fixtures, row=3),
                   view_utils.Button(label="Results", func=self.push_results, row=3),
                   view_utils.StopButton(row=0)
                   ]

        for _ in buttons:
            _.disabled = True if self._current_mode == _.label else False
            self.add_item(_)

    async def push_squad(self):
        """PUsh the Squad Embed to View"""
        players = await self.get_players()
        srt = sorted(players, key=lambda x: x.number)
        p = [i.squad_row for i in srt]

        # Data must be fetched before embed url is updated.
        embed = await self.get_embed()
        embed.title = f"≡ Squad for {self.team.title}"
        embed.url = self.page.url
        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, p)
        self._current_mode = "Squad"
        await self.update()

    async def push_injuries(self):
        """PUsh the Injuries Embed to View"""
        embed = await self.get_embed()
        players = await self.get_players()
        players = [i.injury_row for i in players if i.injury]
        players = players if players else ['No injuries found']
        embed.title = f"≡ Injuries for {self.team.title}"
        embed.url = self.page.url
        embed.description = "\n".join(players)
        self.index = 0
        self.pages = [embed]
        self._current_mode = "Injuries"
        await self.update()

    async def push_scorers(self):
        """PUsh the Scorers Embed to View"""
        embed = await self.get_embed()
        players = await self.get_players()
        srt = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
        embed.title = f"≡ Top Scorers for {self.team.title}"

        rows = [i.scorer_row for i in srt]

        embed_utils.rows_to_embeds(embed, rows, rows_per=None)

        embed.url = self.page.url
        self.index = 0
        self.pages = [embed]
        self._current_mode = "Scorers"
        await self.update()

    async def select_table(self):
        """Select Which Table to push from"""
        self.pages, self.index = [await self.get_embed()], 0
        all_fixtures = await self.team.get_fixtures(self.page)
        unique_comps = []
        [unique_comps.append(x) for x in all_fixtures if x.full_league not in [y.full_league for y in unique_comps]]

        if len(unique_comps) == 1:
            return await self.push_table(unique_comps[0])

        self._currently_selecting = unique_comps
        await self.update()

    async def push_table(self, res):
        """Fetch All Comps, Confirm Result, Get Table Image, Send"""
        embed = await self.get_embed()
        ts, dtn = self.table_timestamp, datetime.datetime.now()
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await res.get_table(self.page)
            if img is not None:
                self.table_image = await image_utils.dump_image(self.ctx, img)
                self.table_timestamp = datetime.datetime.now()

        embed.title = f"≡ Table for {res.full_league}"
        if self.table_image is not None:
            embed.set_image(url=self.table_image)
            embed.description = timed_events.Timestamp().long
        else:
            embed.description = f"No Table found."
        embed.url = self.page.url
        self.pages = [embed]
        self._current_mode = "Table"
        await self.update()

    async def push_fixtures(self):
        """Push upcoming fixtures to View"""
        rows = await self.team.get_fixtures(page=self.page, subpage='/fixtures')
        rows = [str(i) for i in rows] if rows else ["No Fixtures Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Fixtures for {self.team.title}" if embed.title else "≡ Fixtures "
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Fixtures"
        await self.update()

    async def push_results(self):
        """Push results fixtures to View"""
        rows = await self.team.get_fixtures(page=self.page, subpage='/results')
        rows = [str(i) for i in rows] if rows else ["No Results Found :("]
        embed = await self.get_embed()
        embed.title = f"≡ Results for {self.team.title}" if embed.title else "≡ Results "
        embed.timestamp = discord.Embed.Empty

        self.index = 0
        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self._current_mode = "Results"
        await self.update()


class FixtureView(discord.ui.View):
    """The View sent to users about a fixture."""

    def __init__(self, ctx, fixture: football.Fixture, page):
        self.fixture = fixture
        self.ctx = ctx
        self.message = None

        self.page = page
        super().__init__()

        # Pagination
        self.pages = []
        self.index = 0
        self.base_embed = None

        # Button Disabling
        self._current_mode = None

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass
        self.stop()

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.ctx.author.id

    async def update(self):
        """Update the view for the user"""
        embed = self.pages[self.index]
        self.generate_buttons()
        await self.message.edit(content="", view=self, embed=embed, allowed_mentions=discord.AllowedMentions().none())
        await self.wait()

    def generate_buttons(self):
        """Generate our view's buttons"""
        self.clear_items()

        buttons = [view_utils.Button(label="Stats", func=self.push_stats, emoji="📊"),
                   view_utils.Button(label="Table", func=self.push_table),
                   view_utils.Button(label="Lineups", func=self.push_lineups),
                   view_utils.Button(label="Summary", func=self.push_summary),
                   view_utils.Button(label="Head To Head", func=self.push_head_to_head, emoji="⚔", row=3),
                   view_utils.StopButton()
                   ]

        for _ in buttons:
            _.disabled = True if self._current_mode == _.label else False
            self.add_item(_)

    async def get_embed(self):
        """Fetch Generic Embed for Team"""
        self.base_embed = await self.fixture.base_embed if self.base_embed is None else self.base_embed
        return deepcopy(self.base_embed)

    async def push_stats(self):
        """Push Stats to View"""
        self._current_mode = "Stats"

        dtn = datetime.datetime.now()
        ts = self.fixture.stats_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_stats(page=self.page)
            self.fixture.stats_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.stats_timestamp = datetime.datetime.now()

        image = self.fixture.stats_image
        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        embed.description += "No Stats Found" if image is None else ""
        embed.title = f"≡ Stats for {self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_lineups(self):
        """Push Lineups to View"""
        self._current_mode = "Lineups"
        self.index = 0

        dtn = datetime.datetime.now()
        ts = self.fixture.formation_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_formation(page=self.page)
            self.fixture.formation_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.formation_timestamp = datetime.datetime.now()

        image = self.fixture.formation_image

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        embed.description += "No Lineups Found" if image is None else ""
        embed.title = f"≡ Lineups for {self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_table(self):
        """Push Table to View"""
        self._current_mode = "Table"
        self.index = 0

        dtn = datetime.datetime.now()
        ts = self.fixture.table_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_table(page=self.page)
            self.fixture.table_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.table_timestamp = datetime.datetime.now()

        image = self.fixture.table_image

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        embed.description += "No Table Found" if image is None else ""
        embed.title = f"≡ Table for {self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_summary(self):
        """Push Summary to View"""
        self._current_mode = "Summary"
        self.index = 0

        dtn = datetime.datetime.now()
        ts = self.fixture.summary_timestamp
        if ts is None or ts > dtn - datetime.timedelta(minutes=IMAGE_UPDATE_RATE_LIMIT):
            img = await self.fixture.get_summary(page=self.page)
            self.fixture.summary_image = await image_utils.dump_image(self.ctx, img)
            self.fixture.summary_timestamp = datetime.datetime.now()

        image = self.fixture.summary_image

        embed = await self.get_embed()
        embed.description = f"{timed_events.Timestamp().time_relative}\n"
        embed.set_image(url=image if isinstance(image, str) else discord.Embed.Empty)
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        embed.description += "No Summary Found" if image is None else ""
        embed.title = f"≡ Summary for {self.fixture.home} {self.fixture.score} {self.fixture.away}"
        self.pages = [embed]
        await self.update()

    async def push_head_to_head(self):
        """Push Head to Head to View"""
        self._current_mode = "Head To Head"
        self.index = 0

        fixtures = await self.fixture.head_to_head(page=self.page)
        embed = await self.get_embed()
        embed.title = f"≡ Head to Head for {self.fixture.home} {self.fixture.score} {self.fixture.away}"
        if self.page.url.startswith("http"):
            embed.url = self.page.url
        for k, v in fixtures.items():
            x = "\n".join([f"{i.relative_time} [{i.bold_score}]({i.url})" for i in v])
            embed.add_field(name=k, value=x, inline=False)
        self.pages = [embed]
        await self.update()


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "⚽"

        if not hasattr(bot, "browser"):
            self.bot.loop.create_task(browser.make_browser(bot))

        for package in [transfer_tools, football, embed_utils, browser, timed_events, image_utils, view_utils]:
            reload(package)

    # Selection View/Filter/Pickers.
    async def search(self, ctx, qry, mode=None, include_live=False, include_fs=False) \
            -> typing.Union[football.Team, football.Competition, football.Fixture] or None:
        """Get Matches from Live Games & FlashScore Search Results"""
        # Handle Server Defaults
        if qry is None:
            if ctx.guild is not None:
                default = await self._fetch_default(ctx, mode)
                if default is not None:
                    page = await self.bot.browser.newPage()
                    try:
                        if mode == "team":
                            team_id = default.split('/')[-1]
                            fsr = await football.Team.by_id(team_id, page)
                        else:
                            fsr = await football.Competition.by_link(default, page)
                    except Exception as e:
                        raise e  # Re raise, this is specifically to assure page closure.
                    finally:
                        await page.close()
                    return fsr
            return None

        # Gather live games.
        query = str(qry).lower()
        if include_live:
            if mode == "team":
                live = [i for i in ctx.bot.games if query in f"{i.home.lower()} vs {i.away.lower()}"]
            else:
                live = [i for i in ctx.bot.games if query in (i.home + i.away + i.league + i.country).lower()]

            live_options = [("⚽", f"{i.home} {i.score} {i.away}", f"{i.country.upper()}: {i.league}") for i in live]
        else:
            live = live_options = []

        # Gather Other Search Results
        if include_fs:
            search_results = await football.get_fs_results(qry)
            pt = 0 if mode == "league" else 1 if mode == "team" else None  # Mode is a hard override.
            if pt is not None:
                search_results = [i for i in search_results if i.participant_type_id == pt]  # Check for specifics.

            for result in search_results:
                result.emoji = '👕' if result.participant_type_id == 1 else '🏆'

            fs_options = [(i.emoji, i.title, i.url) for i in search_results]
        else:
            fs_options = search_results = []

        markers = live_options + fs_options
        items = live + search_results

        if not markers:
            await self.bot.reply(ctx, f'🚫 {ctx.command.name.title()}: No results found for {qry}', ping=True)
            return None

        if len(markers) == 1:
            return items[0]

        view = view_utils.ObjectSelectView(owner=ctx.author, objects=markers, timeout=30)
        view.message = await self.bot.reply(ctx, '⏬ Multiple results found, choose from the dropdown.', view=view)
        await view.wait()

        if view.value is None:
            return None

        fsr = items[view.value]
        return fsr

    async def _fetch_default(self, ctx, mode=None):
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow("""SELecT * FROM fixtures_defaults WHERE (guild_id) = $1
                 AND (default_league is NOT NULL OR default_team IS NOT NULL)""", ctx.guild.id)
        await self.bot.db.release(connection)

        if not r:
            return None

        team = r["default_team"]
        league = r["default_league"]
        if team or league:
            if mode == "team":
                return team if team else league
            return league if league else team

    async def pick_recent_game(self, ctx, fsr: football.Team, page, upcoming=False):
        """Choose from recent games from team"""
        subpage = "/fixtures" if upcoming else "/results"
        items = await fsr.get_fixtures(page, subpage)

        _ = [("⚽", f"{i.home} {i.score} {i.away}", f"{i.country.upper()}: {i.league}") for i in items]
        view = view_utils.ObjectSelectView(owner=ctx.author, objects=_, timeout=30)
        _ = "an upcoming" if upcoming else "a recent"
        view.message = await self.bot.reply(ctx, f'⏬ Please choose {_} game.', view=view)
        await view.wait()

        if view.value is None:
            return None

        return items[view.value]

    # Actual Commands
    @commands.command(aliases=['fx', 'fix'], usage="<Team or league name to search for>")
    async def fixtures(self, ctx, *, qry: commands.clean_content = None):
        """Fetch upcoming fixtures for a team or league."""
        fsr = await self.search(ctx, qry, include_fs=True)
        if fsr is None:
            return

        page = await self.bot.browser.newPage()

        try:
            if isinstance(fsr, football.Competition):
                view = CompetitionView(ctx, fsr, page)
            elif isinstance(fsr, football.Team):
                view = TeamView(ctx, fsr, page)
            else:
                raise ValueError(f'Expected type football.Competition or football.Team, got {type(fsr)}')
            view.message = await self.bot.reply(ctx, text=f"Fetching fixtures data for {fsr.title}...", view=view)
            await view.push_fixtures()
        finally:
            await page.close()

    @commands.command(aliases=['rx', 'res'], usage="<Team or league name to search for>")
    async def results(self, ctx, *, qry: commands.clean_content = None):
        """Get past results for a team or league."""
        fsr = await self.search(ctx, qry, include_fs=True)
        if fsr is None:
            return

        page = await self.bot.browser.newPage()

        try:
            if isinstance(fsr, football.Competition):
                view = CompetitionView(ctx, fsr, page)
            elif isinstance(fsr, football.Team):
                view = TeamView(ctx, fsr, page)
            else:
                raise ValueError(f'Expected type football.Competition or football.Team, got {type(fsr)}')
            view.message = await self.bot.reply(ctx, text=f"Fetching results data for {fsr.title}...", view=view)
            await view.push_results()
        finally:
            await page.close()

    @commands.command(aliases=['tbl'], usage="<Team or league name to search for>")
    async def table(self, ctx, *, qry: commands.clean_content = None):
        """Get table for a league"""
        fsr = await self.search(ctx, qry, include_fs=True)
        page = await self.bot.browser.newPage()
        try:
            if fsr is None:
                return

            assert isinstance(fsr, (football.Team, football.Competition))

            if isinstance(fsr, football.Team):
                view = TeamView(ctx=ctx, page=page, team=fsr)
                text = f"Fetching Table for {fsr.title}..."
                view.message = await self.bot.reply(ctx, text, view=view)
                await view.select_table()
            else:
                view = CompetitionView(ctx=ctx, page=page, competition=fsr)
                text = f"Fetching Table for {fsr.title}..."
                view.message = await self.bot.reply(ctx, text, view=view)
                await view.push_table()

        finally:
            await page.close()

    @commands.command(aliases=['st'], usage="<team to search for>")
    async def stats(self, ctx, *, qry: commands.clean_content = None):
        """Look up the stats for a fixture."""
        fsr = await self.search(ctx, qry, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

        page = await self.bot.browser.newPage()
        try:
            if isinstance(fsr, football.Team):
                fsr = await self.pick_recent_game(ctx, fsr, page)
                if fsr is None:
                    return

            view = FixtureView(ctx, fixture=fsr, page=page)
            text = f"Fetching Stats for {fsr.home} vs {fsr.away}"
            view.message = await self.bot.reply(ctx, text, view=view)
            await view.push_stats()
        finally:
            await page.close()

    @commands.command(usage="<team to search for>", aliases=["formations", "lineup", "lineups", 'fm'])
    async def formation(self, ctx, *, qry: commands.clean_content = None):
        """Look up the formation for a Fixture."""
        fsr = await self.search(ctx, qry, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

        page = await self.bot.browser.newPage()
        try:
            if isinstance(fsr, football.Team):
                fsr = await self.pick_recent_game(ctx, fsr, page)
                if fsr is None:
                    return

            view = FixtureView(ctx, fixture=fsr, page=page)
            text = f"Fetching Formation for {fsr.home} vs {fsr.away}"
            view.message = await self.bot.reply(ctx, text, view=view)
            await view.push_lineups()
        finally:
            await page.close()

    @commands.command(aliases=["sum"])
    async def summary(self, ctx, *, qry: commands.clean_content = None):
        """Get a summary for one of today's games."""
        fsr = await self.search(ctx, qry, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

        page = await self.bot.browser.newPage()
        try:
            if isinstance(fsr, football.Team):
                fsr = await self.pick_recent_game(ctx, fsr, page)
                if fsr is None:
                    return

            view = FixtureView(ctx, fixture=fsr, page=page)
            text = f"Fetching Summary for {fsr.home} vs {fsr.away}"
            view.message = await self.bot.reply(ctx, text, view=view)
            await view.push_summary()
        finally:
            await page.close()

    @commands.command(aliases=["form", "head"], usage="<Team name to search for>")
    async def h2h(self, ctx, *, qry: commands.clean_content = None):
        """Lookup the head to head details for a Fixture"""
        fsr = await self.search(ctx, qry, include_fs=True, include_live=True, mode="team")
        if fsr is None:
            return  # Rip

        page = await self.bot.browser.newPage()
        try:
            if isinstance(fsr, football.Team):
                fsr = await self.pick_recent_game(ctx, fsr, page, upcoming=True)
                if fsr is None:
                    return

            view = FixtureView(ctx, fixture=fsr, page=page)
            text = f"Fetching Head to Head Data for {fsr.home} vs {fsr.away}"
            view.message = await self.bot.reply(ctx, text, view=view)
            await view.push_head_to_head()
        finally:
            await page.close()
    
    # Team specific.
    @commands.command(aliases=["suspensions", 'inj'], usage="<Team name to search for>")
    async def injuries(self, ctx, *, qry: commands.clean_content = None):
        """Get a team's current injuries"""
        fsr = await self.search(ctx, qry, include_fs=True, mode="team")
        if fsr is None:
            return  # Rip

        assert isinstance(fsr, football.Team)

        page = await self.bot.browser.newPage()
        try:
            view = TeamView(ctx=ctx, page=page, team=fsr)
            view.message = await self.bot.reply(ctx, f"Fetching injuries for {fsr.title}...", view=view)
            await view.push_injuries()
        finally:
            await page.close()

    @commands.command(aliases=["team", "roster", "sqd"], usage="<Team name to search for>")
    async def squad(self, ctx, *, qry: commands.clean_content = None):
        """Lookup a team's squad members"""
        fsr = await self.search(ctx, qry, include_fs=True, mode="team")
        if fsr is None:
            return

        assert isinstance(fsr, football.Team)

        page = await self.bot.browser.newPage()
        try:
            view = TeamView(ctx=ctx, page=page, team=fsr)
            view.message = await self.bot.reply(ctx, f"Fetching Squad Data for {fsr.title}", view=view)
            await view.push_squad()
        finally:
            await page.close()

    @commands.command(invoke_without_command=True, aliases=['sc', 'scr'], usage="<team or league to search for>")
    async def scorers(self, ctx, *, qry: commands.clean_content = None):
        """Get top scorers from a league, or search for a team and get their top scorers in a league."""
        fsr = await self.search(ctx, qry, include_fs=True)
        if fsr is None:
            return

        page = await self.bot.browser.newPage()
        try:
            if isinstance(fsr, football.Competition):
                view = CompetitionView(ctx=ctx, page=page, competition=fsr)
                target = fsr.title
            elif isinstance(fsr, football.Team):
                view = TeamView(ctx=ctx, page=page, team=fsr)
                target = fsr.name
            else:
                raise ValueError(f"Expected Football.Team or Football.Competition, got {type(fsr)}")

            view.message = await self.bot.reply(ctx, f"Fetching Top Scorer Data for {target}...", view=view)
            await view.push_scorers()
        finally:
            await page.close()

    @commands.command(aliases=["std"], usage="<Team or Stadium name to search for.>")
    async def stadium(self, ctx, *, query: commands.clean_content = None):
        """Lookup information about a team's stadiums"""
        if query is None:
            return await self.bot.reply(ctx, "🚫 You need to specify something to search for.", ping=True)

        stadiums = await football.get_stadiums(query)
        if not stadiums:
            return await self.bot.reply(ctx, f"🚫 No stadiums found matching search: {query}")

        markers = [("🏟️", i.name, f"{i.team} ({i.country.upper()}: {i.league})") for i in stadiums]
        view = view_utils.ObjectSelectView(owner=ctx.author, objects=markers, timeout=30)
        view.message = await self.bot.reply(ctx, '⏬ Choose a Stadium.', view=view)
        await view.wait()

        if view.value is None:
            return None

        embed = await stadiums[view.value].to_embed
        await self.bot.reply(ctx, embed=embed)

    # Server defaults
    async def send_defaults(self, ctx):
        """Base Embed for Fixtures Config Embeds"""
        e = discord.Embed()
        e.colour = 0x2ecc71
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.title = '⚙ Toonbot Config: Fixture Defaults'
        e.add_field(name="Setting defaults", value=DF)

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            record = await connection.fetchrow("""SELECT * FROM fixtures_defaults
            WHERE (guild_id) = $1 AND (default_league is NOT NULL OR default_team IS NOT NULL)""", ctx.guild.id)
        await self.bot.db.release(connection)
        if not record:
            e.description = f"{ctx.guild.name} does not currently have any defaults set."
        else:
            league = "not set." if record["default_league"] is None else record["default_league"]
            team = "not set." if record["default_team"] is None else record["default_team"]
            e.description = f"Your default league is: {league}\nYour default team is: {team}"

        await self.bot.reply(ctx, embed=e)

    @commands.group(invoke_without_command=True)
    async def default(self, ctx):
        """Check the default team and league for your server's Fixture commands"""
        return await self.send_defaults(ctx)

    @default.group()
    @commands.has_permissions(manage_guild=True)
    async def team(self, ctx, qry: commands.clean_content):
        """Set a default team for your server's Fixture commands"""
        if qry is None:
            return await self.bot.reply()

        fsr = await self.search(ctx, qry, mode="team", include_fs=True)

        if fsr is None:
            return

        assert isinstance(fsr, football.Team), f"Expected football.Team, got {type(fsr)}"

        url = fsr.url
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_team) VALUES ($1,$2)
                 ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1
           """, ctx.guild.id, url)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f'Your Fixtures commands will now use {fsr.title} as a default league')
        await self.send_defaults(ctx)

    @team.command(name="reset", aliases=["none"])
    @commands.has_permissions(manage_guild=True)
    async def reset_team(self, ctx):
        """Unsets your server's default team for your Fixtures commands"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_team)  VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text='Your Fixtures commands will no longer use a default team.')
        await self.send_defaults(ctx)

    @default.group(invoke_without_commands=True)
    @commands.has_permissions(manage_guild=True)
    async def league(self, ctx, query: commands.clean_content):
        """Set a default league for your server's Fixture commands"""
        if query is None:
            return await self.bot.reply(ctx, "🚫 You need to specify something to search for.", ping=True)

        await self.bot.reply(ctx, text=f'Searching for {query}...', delete_after=5)
        fsr = await self.search(ctx, query, mode="league", include_fs=True)

        if fsr is None:
            return

        assert isinstance(fsr, football.Competition), f"Expected football.Competition, got {type(fsr)}"

        url = fsr.url
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id, default_league) VALUES ($1,$2)
                   ON CONFLICT (guild_id) DO UPDATE SET default_league = $2 WHERE excluded.guild_id = $1
             """, ctx.guild.id, url)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f'Your Fixtures commands will now use {fsr.title} as a default league')
        await self.send_defaults(ctx)
    
    @league.command(name="reset", aliases=["none"])
    @commands.has_permissions(manage_guild=True)
    async def reset_league(self, ctx):
        """Unsets your server's default league for your Fixtures commands"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO fixtures_defaults (guild_id,default_league) VALUES ($1,$2)
                                         ON CONFLICT (guild_id) DO UPDATE SET default_league = $2
                                         WHERE excluded.guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text='Your commands will no longer use a default league.')
        await self.send_defaults(ctx)

    @commands.command(usage="<league to search for>")
    async def scores(self, ctx, *, search_query: commands.clean_content = ""):
        """Fetch current scores for a specified league"""

        embeds = []
        e = discord.Embed()
        e.colour = discord.Colour.og_blurple()
        if search_query:
            e.set_author(name=f'Live Scores matching search "{search_query}"')
        else:
            e.set_author(name="Live Scores for all known competitions")

        q = str(search_query).lower()
        matches = [i for i in self.bot.games if q in (i.home + i.away + i.league + i.country).lower()]

        if not matches:
            e.description = "No results found!"
            view = view_utils.Paginator(ctx.author, [e])
            view.message = await self.bot.reply(ctx, "Fetching Current Live Games...", view=view)
            await view.update()
            return

        header = f'Scores as of: {timed_events.Timestamp().long}\n'
        embeds = []
        matches = [(i.full_league, i.scores_row) for i in matches]
        _ = None
        e.description = header
        for x, y in matches:
            if x != _:  # We need a new header if it's a new league.
                _ = x
                output = f"\n**{x}**\n{y}\n"
            else:
                output = f"{y}\n"

            if len(e.description + output) < 2048:
                e.description += output
            else:
                embeds.append(deepcopy(e))
                e.description = header + f"\n**{x}**\n{y}\n"
        else:
            embeds.append(deepcopy(e))

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching Current Live Games...", view=view)
        await view.update()


def setup(bot):
    """Load the fixtures Cog into the bot"""
    bot.add_cog(Fixtures(bot))

# Maybe To do?: League.archive -> https://www.flashscore.com/football/england/premier-league/archive/
# Maybe to do?: League.Form table.
