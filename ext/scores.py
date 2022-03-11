"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
# Misc
import datetime
from collections import defaultdict
from itertools import zip_longest
from typing import List, Optional, Union

from asyncpg import UniqueViolationError, ForeignKeyViolationError
from discord import ButtonStyle, Interaction, Colour, Embed, NotFound, HTTPException, PermissionOverwrite, Forbidden, \
    app_commands, Message, TextChannel
from discord.ext import commands, tasks
from discord.ui import Button, Select, View
# Web Scraping
from lxml import html, etree
from lxml.etree import ParserError
from pyppeteer.errors import ElementHandleError

from ext.utils import football, embed_utils, view_utils
from ext.utils.football import Team, GameTime, Fixture, Competition

# Constants.
NO_GAMES_FOUND = "No games found for your tracked leagues today!" \
                 "\n\nYou can add more leagues with `.tb ls add league_name`" \
                 "\nTo find out which leagues currently have games, use `.tb scores`"
DEFAULT_LEAGUES = [
    "WORLD: Friendly international",
    "EUROPE: Champions League",
    "EUROPE: Euro",
    "EUROPE: Europa League",
    "EUROPE: UEFA Nations League",
    "ENGLAND: Premier League",
    "ENGLAND: Championship",
    "ENGLAND: League One",
    "ENGLAND: FA Cup",
    "ENGLAND: EFL Cup",
    "FRANCE: Ligue 1",
    "FRANCE: Coupe de France",
    "GERMANY: Bundesliga",
    "ITALY: Serie A",
    "NETHERLANDS: Eredivisie",
    "SCOTLAND: Premiership",
    "SPAIN: Copa del Rey",
    "SPAIN: LaLiga",
    "USA: MLS"
]
WORLD_CUP_LEAGUES = [
    "EUROPE: World Cup",
    "ASIA: World Cup",
    "AFRICA: World Cup",
    "NORTH & CENTRAL AMERICA: World Cup",
    "SOUTH AMERICA: World Cup"
]


# TODO: Allow re-ordering of leagues, set an "index" value in db and do a .sort?
# TODO: Permissions Pass.


class ResetLeagues(Button):
    """Button to reset a live score channel back to it's default leagues"""

    def __init__(self):
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.reset_leagues()


class RemoveLeague(Select):
    """Button to bring up the remove leagues dropdown."""

    def __init__(self, leagues, row=4):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.max_values = len(leagues)

        for lg in sorted(leagues):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction):
        """When a league is selected"""
        await interaction.response.defer()
        await self.view.remove_leagues(self.values)


class ScoresConfig(View):
    """Generic Config View"""

    def __init__(self, interaction: Interaction):
        super().__init__()
        self.index = 0
        self.interaction = interaction
        self.message: Union[Message, None] = None
        self.pages = None

    async def on_timeout(self):
        """Hide menu on timeout."""
        self.clear_items()
        await self.message.edit(view=self)
        self.stop()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def get_leagues(self):
        """Fetch Leagues for View's Channel"""
        connection = await self.interaction.client.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM scores_leagues WHERE channel_id = $1"""
            leagues = await connection.fetch(q, self.interaction.channel.id)
        await self.interaction.client.db.release(connection)

        leagues = [r['league'] for r in leagues]
        return leagues

    async def update(self, content=""):
        """Push the newest version of view to message"""
        self.clear_items()
        leagues = await self.get_leagues()

        if leagues:
            e = Embed(colour=Colour.dark_teal(), title="Toonbot Live Scores config")
            e.set_thumbnail(url=self.interaction.client.user.display_avatar.url)

            header = f'Tracked leagues for {self.interaction.channel.mention}```yaml\n'

            if not leagues:
                leagues = ["```css\n[WARNING]: Your tracked leagues is completely empty! Nothing is being output!```"]

            embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=header, footer="```", rows_per=25)
            self.pages = embeds
            self.add_item(view_utils.PreviousButton(disabled=True if self.index == 0 else False))
            self.add_item(view_utils.PageButton(label=f"Page {self.index + 1} of {len(self.pages)}",
                                                disabled=True if len(self.pages) == 1 else False))
            self.add_item(view_utils.NextButton(disabled=True if self.index == len(self.pages) - 1 else False))
            self.add_item(view_utils.StopButton(row=0))

            embed = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues))
        else:
            self.add_item(ResetLeagues())
            embed = None
            content = f"You have no tracked leagues for {self.interaction.channel.mention}, would you like to reset it?"

        if self.message is None:
            i = self.interaction
            self.message = await i.client.reply(i, content=content, embed=embed, view=self)
        else:
            try:
                await self.message.edit(content=content, embed=embed, view=self)
            except NotFound:
                return

    async def remove_leagues(self, leagues):
        """Bulk remove leagues from a live scores channel"""
        view = view_utils.Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        await self.message.edit(content=f"Remove these leagues from {self.interaction.channel.mention}? {lg_text}",
                                view=view)
        await view.wait()

        if view.value:
            connection = await self.interaction.client.db.acquire()
            async with connection.transaction():
                q = """DELETE from scores_leagues WHERE (channel_id, league) = ($1, $2)"""
                for x in leagues:
                    await connection.execute(q, self.interaction.channel.id, x)
            await self.interaction.client.db.release(connection)
        await self.update(content=f"Removed {self.interaction.channel.mention} tracked leagues: {lg_text}")

    async def reset_leagues(self):
        """Reset a channel to default leagues."""
        connection = await self.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
                for x in DEFAULT_LEAGUES:
                    await connection.execute(q, self.interaction.channel.id, x)
        finally:
            await self.interaction.client.db.release(connection)
        await self.update(content=f"Tracked leagues for {self.interaction.channel.mention} reset")


# Autocomplete
async def lg_ac(interaction: Interaction, current: str, _) -> List[app_commands.Choice[str]]:
    """Return list of live leagues"""
    comps = list(set([i.competition.name for i in interaction.client.games.values()]))
    return [app_commands.Choice(name=item, value=item) for item in comps if current.lower() in item.lower()]


class Scores(commands.Cog, name="LiveScores"):
    """Live Scores channel module"""

    def __init__(self, bot):
        self.bot = bot
        self.page = None
        self.iterations = 0

        # Score loops.
        self.bot.score_loop = self.score_loop.start()
        self.bot.fs_score_loop = self.fs_score_loop.start()

    def cog_unload(self):
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.score_loop.cancel()
        self.bot.fs_score_loop.cancel()

    @tasks.loop(minutes=1)
    async def fs_score_loop(self):
        """Flashscore loop."""
        self.bot.fs_games = await self.get_games()  # FS Version

    # Core Loop
    @tasks.loop(minutes=1)
    async def score_loop(self):
        """Score Checker Loop"""
        cache = await self.get_cache()
        await self.fetch_games()

        embeds: dict = {}
        g: List[Fixture] = list(self.bot.games.values())
        lg: Competition

        for comp in set(i.competition for i in g):
            e = await comp.base_embed
            e.description = "\n".join([i.live_score_text for i in g if i.competition == comp])
            embeds[f"{comp.country.upper()}: {comp.name}"] = e

        self.bot.scores_embeds = embeds

        # Iterate: Check vs each server's individual config settings
        # Every 5 minutes
        if self.iterations % 5 == 0:
            for i in cache.copy():  # Error if dict changes sizes during iteration.
                await self.update_channel(i, cache)
        self.iterations += 1

    async def get_games(self) -> List[Fixture]:
        """Grab current scores from flashscore using Pyppeteer"""
        if self.page is None or self.page.isClosed():
            if self.bot.browser is None:
                return self.bot.fs_games  # Return until browser is actually loaded.
            self.page = await self.bot.browser.newPage()

        if self.page.url != "http://www.flashscore.co.uk/":
            await self.page.goto("http://www.flashscore.co.uk/")

        show_more = await self.page.xpath("//div[contains(@title, 'Display all matches')]")
        for x in show_more:
            try:
                await x.click()
            except ElementHandleError:
                break

        tree = html.fromstring(await self.page.content())

        rows = tree.xpath('.//div[@class="sportName soccer"]/div')
        competition: Competition = Competition()
        for row in rows:
            # This is a competition Header, update competition Info.
            if "event__header" in row.classes:
                country = ''.join(row.xpath('.//span[@class="event__title--type"]/text()'))
                lg = ''.join(row.xpath('.//span[@class="event__title--name"]/text()'))

                long = f"{country.upper()}: {lg}"
                if long in self.bot.competitions:
                    competition = self.bot.competitions[long]
                else:
                    competition = Competition(name=lg, country=country)
                continue

            # Fetch the Basic required Info to create our Fixture object.

            fixture_id = row.get("id").split('_')[-1]
            url = "http://www.flashscore.com/match/" + fixture_id

            # Get index of existing fixture, or create new one.
            if url not in self.bot.fs_games:
                home = ''.join(row.xpath('.//div[contains(@class, "participant--home")]//text()'))
                away = ''.join(row.xpath('.//div[contains(@class, "participant--away")]//text()'))
                self.bot.fs_games[url] = Fixture(home=Team(name=home), away=Team(name=away), competition=competition)

            # Get scores & dispatch goals.
            try:
                sh = str(row.xpath('.//div[contains(@class, "score--home")]/text()')[0])
                if sh != self.bot.fs_games[url].score_home:
                    self.bot.fs_games[url].score_home = sh
                    # self.bot.fs_games[url].set_score(sh)
            except (IndexError, ValueError):
                pass

            try:
                sa = str(row.xpath('.//div[contains(@class, "score--away")]/text()')[0])
                if sa != self.bot.fs_games[url].score_away:
                    self.bot.fs_games[url].score_away = sa
                    # self.bot.fs_games[url].set_score(sa, home=False)
            except (IndexError, ValueError):
                pass

            t = ''.join(row.xpath('.//div[@class="event__stage--block"]/text() | .//div[@class="event__time"]/text()'))

            if not t:
                t = None

            self.bot.fs_games[url].time = GameTime(t)
            # Set Red Cards
            self.bot.fs_games[url].home_cards = len(row.xpath('.//div[contains(@class, "participant--home")]//svg'))
            self.bot.fs_games[url].away_cards = len(row.xpath('.//div[contains(@class, "participant--away")]//svg'))
        return self.bot.fs_games

    async def fetch_games(self):
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                print(f'{datetime.datetime.utcnow()} | Scores error {resp.status} ({resp.reason}) during fetch_games')
                return self.bot.games
            tree = html.fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))

        inner_html = tree.xpath('.//div[@id="score-data"]')[0]
        byt: bytes = etree.tostring(inner_html)
        string: str = byt.decode('utf8')
        chunks = str(string).split('<br/>')

        # Type Hinting
        teams: List[str]
        cards: List[str]
        kickoff: str
        ko: datetime.datetime
        h_score: str
        a_score: str
        card_home: Union[int, None]
        card_away: Union[int, None]
        competition: Competition = Competition()
        for chunk in chunks:
            try:
                tree = html.fromstring(chunk)
            except ParserError:  # Document is empty because of trailing </div>
                continue

            url = "http://www.flashscore.com" + ''.join(tree.xpath('.//a/@href'))

            # Check if chunk has header row:
            header = ''.join(tree.xpath('.//h4/text()'))
            if header:
                country, name = header.split(':', 1)
                competition = Competition(country=country.strip(), name=name.strip())

            # Set & forget: Competition, Teams
            if url not in self.bot.games:
                # These values never need to be updated.
                teams = [i.strip() for i in tree.xpath('./text()') if i.strip()]
                if len(teams) == 1:
                    teams = teams[0].split(' - ')  # Teams such as Al-Whatever exist.
                if len(teams) != 2:
                    print("[mobi rewrite] Found erroneous number of teams in fixture", teams)
                    continue
                self.bot.games[url] = Fixture(url=url)

                self.bot.games[url].competition = competition
                self.bot.games[url].home = teams[0]
                self.bot.games[url].away = teams[1]

            # Get match score
            score_line = ''.join(tree.xpath('.//a/text()')).split(':')
            try:
                h_score, a_score = score_line

                if a_score.endswith('aet'):
                    a_score = a_score.replace('aet', '')
                elif a_score.endswith('pen'):
                    a_score = a_score.replace('pen', '')

                # Replace with set_score
                ns = None if h_score == "-" else int(h_score)
                self.bot.games[url].set_score(self.bot, ns)
                ns = None if a_score == "-" else int(a_score)
                self.bot.games[url].set_score(self.bot, ns, home=False)
            except IndexError:
                print(f'Could not split {score_line} into h, a')
            except ValueError:
                print(f'Could not convert {score_line} into ints')

            # Game Time Logic.
            state = ''.join(tree.xpath('./a/@class')).strip()
            time = tree.xpath('.//span/text()')

            if len(time) == 1:
                time = time[0]
            else:
                state = time[1]

            cancelled = tree.xpath('./span/@class')
            if cancelled and cancelled != ['live']:
                print('Found cancelled text', cancelled)

            if state in ['sched', 'fin']:
                # FS.mobi is 1 hour+
                if state == 'fin':
                    if score_line[-1].endswith("pen"):
                        self.bot.games[url].set_time(GameTime("After Pens"))
                    elif score_line[-1].endswith("aet"):
                        self.bot.games[url].set_time(GameTime("AET"))
                    else:
                        self.bot.games[url].set_time(GameTime("Full Time"))
                else:
                    self.bot.games[url].set_time(GameTime("scheduled"))

                if self.bot.games[url].kickoff is None:
                    ko = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)
                    now = datetime.datetime.now()
                    ko = now.replace(hour=ko.hour, minute=ko.minute, second=0, microsecond=0)  # Discard microseconds

                    # If the game appears to be in the past.
                    if now.timestamp() > ko.timestamp():
                        ko += datetime.timedelta(days=1)
                    expiry = ko + datetime.timedelta(days=1)
                    self.bot.games[url].kickoff = ko
                    self.bot.games[url].expires = expiry.day
            elif state == 'live':
                self.bot.games[url].set_time(GameTime(time))
            elif state in ['Postponed', 'Cancelled']:
                self.bot.games[url].set_time(GameTime(state))
            else:
                raise NotImplementedError(f"State not handled {state} | {time}")

            cards = [i.replace('rcard-', '') for i in tree.xpath('./img/@class')]
            if cards:
                teams = [i.strip() for i in tree.xpath('./text()') if i.strip()]
                if len(cards) == 2:
                    card_home, card_away = [int(card) for card in cards]
                else:
                    if len(teams) == 2:
                        card_home, card_away = int(cards[0]), None
                    else:
                        card_home, card_away = None, int(cards[0])

                self.bot.games[url].set_cards(self.bot, card_home)
                self.bot.games[url].set_cards(self.bot, card_away, home=False)

    async def get_cache(self):
        """Grab the most recent data for all channel configurations"""
        cache = defaultdict(set)

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                comps = await connection.fetch("""SELECT * from fs_competitions""")
            async with connection.transaction():
                teams = await connection.fetch("""SELECT * from fs_teams""")
            async with connection.transaction():
                records = await connection.fetch("""SELECT channel_id, league FROM scores_leagues""")
        finally:
            await self.bot.db.release(connection)

        for c in comps:
            comp = Competition(id=c['id'], url=c['url'], name=c['name'], country=c['country'], logo_url=c['logo_url'])
            self.bot.competitions[comp.name] = comp

        for t in teams:
            team = Team(id=t['id'], url=t['url'], name=t['name'], logo_url=t['logo_url'])
            self.bot.teams[team.name] = team

        # Repopulate.
        for r in records:
            if self.bot.get_channel(r['channel_id']) is not None:
                cache[r["channel_id"]].add(r["league"])
        return cache

    async def update_channel(self, channel_id: int, cache: dict):
        """Edit a live-score channel to have the latest scores"""
        channel: TextChannel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        # Does league exist in both whitelist and found games.
        intersection = set()
        for available in self.bot.scores_embeds.keys():
            for tracked in cache[channel_id]:
                if tracked == available:
                    intersection.add(available)
                elif tracked + " -" in available:  # For Competitions Such as EUROPE: Champions League - Playoffs
                    intersection.add(available)

        guild_embeds: List[Embed] = [self.bot.scores_embeds[lg] for lg in intersection]

        # Type Hinting for loop
        messages: dict[Message, List[Embed]]
        new_embeds_paged: List[List[Embed]] = []
        old_embeds: List[Embed]
        new_embeds: List[Embed] = []
        embed_new: Embed
        embed_old: Embed
        length: int = 0
        count: int = 1

        if not guild_embeds:
            guild_embeds = [Embed(description=NO_GAMES_FOUND)]

        # Paginate into maxsize 6000 / max number 10 chunks.
        for x in guild_embeds:
            if length + len(x) < 6000 and count < 10:
                length += len(x)
                count += 1
                new_embeds.append(x)
            else:
                new_embeds_paged.append(new_embeds)
                new_embeds = [x]
                length = len(x)
                count = 1
        new_embeds_paged.append(new_embeds)

        # Unpack Lists to Variables.
        messages = self.bot.scores_messages[channel_id]

        for old, new_embeds in zip_longest(messages.items(), new_embeds_paged):
            try:
                old: dict
                message, old_embeds = old
            except TypeError:
                message, old_embeds = None, []

            if message is None:  # No message exists in cache, or we need an additional message.
                try:
                    await channel.purge()
                except Forbidden:
                    pass
                try:
                    message = await channel.send(embeds=new_embeds)
                except HTTPException:
                    message = None
            elif not new_embeds:
                # Shorter than old message list.
                await message.delete()
                continue
            elif not set(new_embeds) == set(old_embeds):
                # We now have a Message, a list of old_embeds, and a list of new_embeds
                try:
                    await message.edit(embeds=new_embeds)
                except NotFound:
                    self.bot.scores_messages.pop(message)
                    continue
            self.bot.scores_messages[channel_id][message] = new_embeds

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Remove all of a channel's stored data upon deletion"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM scores_channels WHERE channel_id = $1""", channel.id)
        finally:
            await self.bot.db.release(connection)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Remove all data for tracked channels for a guild upon guild leave"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)

    livescores = app_commands.Group(name="livescores", description="Create or manage livescores channels")

    @livescores.command()
    async def manage(self, interaction):
        """View or Delete tracked leagues from a live-scores channel."""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        elif not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to edit a scores channel."
            return await self.bot.error(interaction, err)

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                row = await connection.fetchrow(q, interaction.channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            err = f"{interaction.channel.mention} is not a live-scores channel."
            return await self.bot.error(interaction, err)

        await ScoresConfig(interaction).update(content=f"Fetching config for {interaction.channel.mention}...")

    @livescores.command()
    @app_commands.describe(name="Enter a name for the channel")
    async def create(self, interaction: Interaction, name: Optional[str]):
        """Create a live-scores channel for your server."""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await self.bot.error(interaction, err)

        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            err = "I need manage_channels permissions to create a scores channel."
            return await self.bot.error(interaction, err)

        reason = f'{interaction.user} (ID: {interaction.user.id}) created a Toonbot live-scores channel.'
        topic = "Live Scores from around the world"

        try:
            name = "live-scores" if name is None else name
            channel = await interaction.guild.create_text_channel(name=name, reason=reason, topic=topic)
        except Forbidden:
            return await self.bot.error(interaction, 'I need manage_channels permissions to make a channel.')

        if interaction.channel.permissions_for(interaction.guild.me).manage_roles:
            ow = {
                interaction.guild.me: PermissionOverwrite(send_messages=True, manage_messages=True,
                                                          read_message_history=True),
                interaction.guild.default_role: PermissionOverwrite(read_messages=True, send_messages=False)}
            try:
                channel = await channel.edit(overwrites=ow)
            except Forbidden:
                pass

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO scores_channels (guild_id, channel_id) VALUES ($1, $2)"""
                try:
                    await connection.execute(q, channel.guild.id, channel.id)
                except ForeignKeyViolationError:
                    cog = self.bot.get_cog("Mod")
                    await cog.create_guild(channel.guild.id)
                    await connection.execute(q, channel.guild.id, channel.id)

                qq = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                for i in DEFAULT_LEAGUES:
                    await connection.execute(qq, channel.id, i)
        finally:
            await self.bot.db.release(connection)

        await self.bot.reply(interaction, content=f"The {channel.mention} channel was created! "
                                                  f"Use /livescores add in there to add tracked leagues.")

        cache = await self.get_cache()
        await self.update_channel(channel.id, cache)

    @livescores.command()
    @app_commands.describe(league_name="league name to search for")
    @app_commands.autocomplete(league_name=lg_ac)
    async def add(self, interaction: Interaction, league_name: str):
        """Add a league to an existing live-scores channel"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await self.bot.error(interaction, err)

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, interaction.channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            return await self.bot.error(interaction, "This command can only be ran in a live-scores channel.")

        if "http" not in league_name:
            message = await self.bot.reply(interaction, content=f"Searching for {league_name}...")
            res = await football.fs_search(interaction, league_name)
            if res is None:
                return
        else:
            if "flashscore" not in league_name:
                return await self.bot.error(interaction, "Invalid link provided.")

            message = await self.bot.reply(interaction, content=f"Searching for {league_name}...")
            qry = str(league_name).strip('[]<>')  # idiots
            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition.by_link(qry, page)
            finally:
                await page.close()

            if res is None:
                err = f"Failed to get data for {qry} channel not modified."
                return await self.bot.error(interaction, err, message=message)

        res = str(res)  # Get competition full name from competition object.
        assert res

        q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, interaction.channel.id, res)
        finally:
            await self.bot.db.release(connection)

        view = ScoresConfig(interaction)
        view.message = message
        await view.update(content=f"Added tracked leagues for {interaction.channel.mention}```yaml\n{res}```")

    @livescores.command(name="worldcup")
    async def addwc(self, interaction):
        """Add the qualifying tournaments for the World Cup to a live score channel"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await self.bot.error(interaction, err)

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, interaction.channel.id)
                if not row:
                    err = "This command can only be ran in a live-scores channel."
                    return await self.bot.error(interaction, err)

            q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
            try:
                async with connection.transaction():
                    for x in WORLD_CUP_LEAGUES:
                        await connection.execute(q, interaction.channel.id, x)
            except UniqueViolationError:
                pass
        finally:
            await self.bot.db.release(connection)

        res = f"{interaction.channel.mention} ```yaml\n" + "\n".join(WORLD_CUP_LEAGUES) + "```"
        await ScoresConfig(interaction).update(content=f"Added to tracked leagues for {res}")

    @livescores.command()
    async def scores_refresh(self, interaction):
        """ ADMIN: Force a cache refresh of the live scores"""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        self.bot.games = defaultdict(dict)
        e = Embed(colour=Colour.og_blurple(), description="[ADMIN] Cleared global games cache.")
        await self.bot.reply(interaction, embed=e)


def setup(bot):
    """Load the cog into the bot"""
    bot.add_cog(Scores(bot))
