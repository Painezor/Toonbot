"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
# Misc
import datetime
from collections import defaultdict
from itertools import zip_longest
from typing import List, Tuple, Optional

from asyncpg import UniqueViolationError, ForeignKeyViolationError
from discord import ButtonStyle, Interaction, Colour, Embed, NotFound, HTTPException, PermissionOverwrite, Forbidden, \
    app_commands, Message
from discord.ext import commands, tasks
from discord.ui import Button, Select, View
# Web Scraping
from lxml import html

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


class ConfigView(View):
    """Generic Config View"""

    def __init__(self, interaction: Interaction):
        super().__init__()
        self.index = 0
        self.interaction = interaction
        self.message = None
        self.pages = None

    async def on_timeout(self):
        """Hide menu on timeout."""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except NotFound:
            pass
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
async def league(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Return list of live leagues"""
    comps = list(set([i.competition.name for i in interaction.client.games.values()]))
    return [app_commands.Choice(name=item, value=item) for item in comps if current.lower() in item.lower()]


class LiveScores(app_commands.Group):
    """Create or manage livescores channels"""

    @app_commands.command()
    async def manage(self, interaction):
        """View or Delete tracked leagues from a live-scores channel."""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be ran in DMs")
        elif not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to edit a scores channel."
            return await interaction.client.error(interaction, err)

        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                row = await connection.fetchrow(q, interaction.channel.id)
        finally:
            await interaction.client.db.release(connection)

        if not row:
            err = f"{interaction.channel.mention} is not a live-scores channel."
            return await interaction.client.error(interaction, err)

        await ConfigView(interaction).update(content=f"Fetching config for {interaction.channel.mention}...")

    @app_commands.command()
    @app_commands.describe(channel="Enter a name for the channel")
    async def create(self, interaction: Interaction, channel_name: Optional[str] = "live-scores"):
        """Create a live-scores channel for your server."""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await interaction.client.error(interaction, err)

        if not interaction.channel.permissions_for(interaction.channel.guild.me).manage_channels:
            err = "I need manage_channels permissions to create a scores channel."
            return await interaction.client.error(interaction, err)

        reason = f'{interaction.user} (ID: {interaction.user.id}) created a Toonbot live-scores channel.'
        topic = "Live Scores from around the world"

        try:
            channel = await interaction.guild.create_text_channel(name=channel_name, reason=reason, topic=topic)
        except Forbidden:
            return await interaction.client.error(interaction, 'I need manage_channels permissions to make a channel.')

        if interaction.channel.permissions_for(interaction.channel.guild.me).manage_roles:
            ow = {
                interaction.channel.guild.me: PermissionOverwrite(send_messages=True, manage_messages=True,
                                                                  read_message_history=True),
                interaction.guild.default_role: PermissionOverwrite(read_messages=True, send_messages=False)}
            try:
                channel = await channel.edit(overwrites=ow)
            except Forbidden:
                pass

        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO scores_channels (guild_id, channel_id) VALUES ($1, $2)"""
                try:
                    await connection.execute(q, channel.guild.id, channel.id)
                except ForeignKeyViolationError:
                    cog = interaction.client.get_cog("Mod")
                    await cog.create_guild(channel.guild.id)
                    await connection.execute(q, channel.guild.id, channel.id)

                qq = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                for i in DEFAULT_LEAGUES:
                    await connection.execute(qq, channel.id, i)
        finally:
            await interaction.client.db.release(connection)

        await interaction.client.reply(interaction, content=f"The {channel.mention} channel was created! "
                                                            f"Use /livescores add in there to add tracked leagues.")

        cache = await get_cache(interaction.client)
        await update_channel(interaction.client, channel.id, cache)

    @app_commands.command()
    @app_commands.describe(league_name="league name to search for")
    @app_commands.autocomplete(league_name=league)
    async def add(self, interaction: Interaction, league_name: str):
        """Add a league to an existing live-scores channel"""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await interaction.client.error(interaction, err)

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, interaction.channel.id)
        finally:
            await interaction.client.db.release(connection)

        if not row:
            return await interaction.client.error(interaction, "This command can only be ran in a live-scores channel.")

        if "http" not in league_name:
            message = await interaction.client.reply(interaction, content=f"Searching for {league_name}...")
            res = await football.fs_search(interaction, league_name)
            if res is None:
                return
        else:
            if "flashscore" not in league_name:
                return await interaction.client.error(interaction, "Invalid link provided.")

            message = await interaction.client.reply(interaction, content=f"Searching for {league_name}...")
            qry = str(league_name).strip('[]<>')  # idiots
            page = await interaction.client.browser.newPage()
            try:
                res = await football.Competition.by_link(qry, page)
            finally:
                await page.close()

            if res is None:
                err = f"Failed to get data for {qry} channel not modified."
                return await interaction.client.error(interaction, err, message=message)

        res = str(res)  # Get competition full name from competition object.
        assert res

        q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, interaction.channel.id, res)
        finally:
            await interaction.client.db.release(connection)

        view = ConfigView(interaction)
        view.message = message
        await view.update(content=f"Added tracked leagues for {interaction.channel.mention}```yaml\n{res}```")

    @app_commands.command(name="worldcup")
    async def addwc(self, interaction):
        """Add the qualifying tournaments for the World Cup to a live score channel"""
        if interaction.guild is None:
            return await interaction.client.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await interaction.client.error(interaction, err)

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
        connection = await interaction.client.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, interaction.channel.id)
                if not row:
                    err = "This command can only be ran in a live-scores channel."
                    return await interaction.client.error(interaction, err)

            q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
            try:
                async with connection.transaction():
                    for x in WORLD_CUP_LEAGUES:
                        await connection.execute(q, interaction.channel.id, x)
            except UniqueViolationError:
                pass
        finally:
            await interaction.client.db.release(connection)

        res = "```yaml\n" + "\n".join(WORLD_CUP_LEAGUES) + "```"
        await ConfigView(interaction).update(content=f"Added to tracked leagues for {interaction.channel.mention}{res}")

    @app_commands.command()
    async def scores_refresh(self, interaction):
        """ ADMIN: Force a cache refresh of the live scores"""
        if interaction.user.id != interaction.client.owner_id:
            return await interaction.client.error(interaction, "You do not own this bot.")

        interaction.client.games = defaultdict(dict)
        e = Embed(colour=Colour.og_blurple(), description="[ADMIN] Cleared global games cache.")
        await interaction.client.reply(interaction, embed=e)


async def get_cache(bot):
    """Grab the most recent data for all channel configurations"""
    cache = defaultdict(set)
    connection = await bot.db.acquire()
    try:
        async with connection.transaction():
            records = await connection.fetch("""SELECT channel_id, league FROM scores_leagues""")
    finally:
        await bot.db.release(connection)

    # Repopulate.
    for r in records:
        if bot.get_channel(r['channel_id']) is not None:
            cache[r["channel_id"]].add(r["league"])
    return cache


async def update_channel(bot, channel_id, cache):
    """Edit a live-score channel to have the latest scores"""
    if bot.get_channel(channel_id) is None:
        return

    # Does league exist in both whitelist and found games.
    guild_embeds: List[Embed] = [bot.scores_embeds[lg] for lg in bot.scores_embeds.keys() & cache[channel_id]]

    new_pages: List[List[Embed]] = []
    embeds: List[Embed] = []
    length: int = 0
    count: int = 1
    for x in guild_embeds:
        if len(x) < 6000 and count < 10:
            count += 1
            length += len(x)
            embeds.append(x)
        else:
            new_pages.append(embeds)
            embeds = [x]
            length = len(x)
            count = 1
    new_pages.append(embeds)

    if not new_pages:
        new_pages = [[Embed(description=NO_GAMES_FOUND)]]

    old: List[Tuple[Message, List[Embed]]] = bot.scores_messages[channel_id]

    replacement_list: list = []
    for old_tuple, new_embeds in zip_longest(old, new_pages):
        message, old_embeds = old_tuple[0], old_tuple[1]
        # We now have a Message, a list of old_embeds, and a list of new_embeds
        for embed_new, embed_old in zip_longest(old_embeds, new_embeds):
            try:
                assert hasattr(embed_old, "description")
                assert embed_new.description == embed_new.old.description
            except AttributeError:
                break  # Message needs to be edited.
        else:
            replacement_list.append((message, new_embeds))
            continue
        try:
            await message.edit(embeds=new_embeds)
        except HTTPException:
            pass
        replacement_list.append((message, new_embeds))
    bot.scores_messages[channel_id] = replacement_list


class Scores(commands.Cog, name="LiveScores"):
    """Live Scores channel module"""

    def __init__(self, bot):
        self.bot = bot
        self.page = None
        self.iterations = 0

        # Data
        if not hasattr(self.bot, "games"):
            self.bot.games = dict()

        if not hasattr(self.bot, "fs_games"):
            self.bot.fs_games = defaultdict(dict)

        self.bot.scores_embeds = {}  # for fast refresh
        if not hasattr(bot, "scores_messages"):
            self.bot.scores_messages = defaultdict(list)

        self.bot.tree.add_command(LiveScores())

        # Core loop.
        self.bot.score_loop = self.score_loop.start()
        self.bot.fs_score_loop = self.score_loop.start()

    def cog_unload(self):
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.score_loop.cancel()
        self.bot.fs_score_loop.cancel()

    @tasks.loop(minutes=1)
    async def fs_score_loop(self):
        """Flashscore loop."""
        self.bot.fs_games = await self.get_games()  # FS Version
        print(f"DEBUG: FS Score loop returned {len(self.bot.fs_games)} games")

    # Core Loop
    @tasks.loop(minutes=1)
    async def score_loop(self):
        """Score Checker Loop"""
        cache = await get_cache(self.bot)
        await self.fetch_games()

        embeds = dict()
        g = self.bot.games.values()
        for lg in set([str(i.competition) for i in g]):
            e = Embed(title=lg)
            e.description = "\n".join([i.live_score_text for i in g if str(i.competition) == lg])
            embeds[lg] = e

        self.bot.scores_embeds = embeds

        # Iterate: Check vs each server's individual config settings
        # Every 5 minutes
        if self.iterations % 5 == 0:
            for i in cache:  # Error if dict changes sizes during iteration.
                self.bot.loop.create_task(update_channel(self.bot, i, cache))
        self.iterations += 1

    @score_loop.before_loop
    async def before_score_loop(self):
        """Updates Cache at the start of a score loop"""
        await self.bot.wait_until_ready()

    async def get_games(self):
        """Grab current scores from flashscore using Pyppeteer"""
        print("Beginning get_games iteration")
        if self.page is None or self.page.isClosed():
            self.page = await self.bot.browser.newPage()

        if self.page.url != "http://www.flashscore.co.uk/":
            await self.page.goto("http://www.flashscore.co.uk/")

        show_more = await self.page.xpath("//div[contains(@title, 'Display all matches')]")
        print(len(show_more), "show more fields found.")
        for x in show_more:
            print("Debug, clicked on a show_more element")
            await x.click()

        tree = html.fromstring(await self.page.content())

        competition = Competition()
        for row in tree.xpath('.//div[@id="live_table"]/div[@class="sportName soccer"]/div'):
            # This is a competition Header, update competition Info.
            if "event__header" in row.classes:
                country = "".join(row.xpath('.//span[@class="event__title-type"]/text()'))
                lg = "".join(row.xpath('.//span[@class="event__title-name"]/text()'))
                print(f"[DEBUG]: scores get_games country [{country}] league [{lg}]")
                competition = Competition(name=lg, country=country)
                continue

            # Fetch the Basic required Info to create our Fixture object.

            fixture_id = row.get("id").split('_')[-1]
            url = "http://www.flashscore.com/" + fixture_id

            # Get index of existing fixture, or create new one.
            try:
                fx = self.bot.fs_games.pop([f for f in self.bot.fs_games if url == f.url][0])
            except IndexError:
                home = "".join(row.xpath('.//div[contains(@class, "participant--home")]//text()'))
                away = "".join(row.xpath('.//div[contains(@class, "participant--away")]//text()'))
                print(f"[DEBUG]: scores get_games fixture_id [{fixture_id}] [{home}] vs [{away}]")
                fx = Fixture(home=Team(name=home), away=Team(name=away))
                fx.competition = competition

            # Get scores & dispatch goals.
            try:
                sh = row.xpath('.//div[contains(@class, "score--home")]/text()')[0]
                if sh != fx.score_home:
                    event = "goal" if sh > fx.score_home else "var_goal"
                    # self.bot.dispatch("fixture_event", event_type, fx)
                    print("DEBUG: pretending to fire fixture_event", event)
                    fx.score_home = sh
            except (IndexError, ValueError):
                pass

            try:
                sa = row.xpath('.//div[contains(@class, "score--away")]/text()')[0]
                if sa != fx.score_away:
                    event = "goal" if sa > fx.score_away else "var_goal"
                    # self.bot.dispatch("fixture_event", event_type, fx, home=False)
                    print("DEBUG: pretending to fire fixture_event", event)
                    fx.score_away = sa
            except (IndexError, ValueError):
                pass

            time = "".join(row.xpath('.//div[@class="event__stage--block"]'))
            fx.time = GameTime(time, fixture=fx)

            # Set Red Cards
            fx.cards_home = len(row.xpath('.//div[contains(@class, "participant--home")]//svg'))
            fx.cards_away = len(row.xpath('.//div[contains(@class, "participant--away")]//svg'))

            self.bot.fs_games.append(fx)
            print("Ending get_games iteration")
            return self.bot.fs_games

    async def fetch_games(self):
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                print(f'{datetime.datetime.utcnow()} | Scores error {resp.status} ({resp.reason}) during fetch_games')
                return self.games
            tree = html.fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))
        elements = tree.xpath('.//div[@id="score-data"]/* | .//div[@id="score-data"]/text()')

        home_cards = 0
        away_cards = 0
        score_home = None
        score_away = None
        url = None
        time = None
        day = datetime.datetime.now().day
        state = None
        capture_group = []

        competition = Competition(country=None, name=None)

        for i in elements:
            try:
                tag = i.tag
            except AttributeError:
                # Not an element. / lxml.etree._ElementUnicodeResult
                capture_group.append(i)
                continue

            # Get Team & League Info.
            if tag == "h4":
                country, lg = i.text.split(': ')
                lg = lg.split(' - ')[0]
                competition = Competition(country=country, name=lg)

            if tag == "a":
                url = i.attrib['href']
                url = url.split('/?')[0].strip('/')  # Trim weird shit that causes duplicates.
                url = "http://www.flashscore.com/" + url
                score_home, score_away = i.text.split(':')
                if not state:
                    state = i.attrib['class'].lower()
                if score_away.endswith('aet'):
                    score_away = score_away.replace('aet', "").strip()
                    state = "after extra time"
                elif score_away.endswith('pen'):
                    score_away = score_away.replace('pen', "").strip()
                    state = "after pens"

                try:
                    score_home = int(score_home)
                    score_away = int(score_away)
                except ValueError:
                    score_home, score_away = 0, 0

            elif tag == "span":
                # Sub-span containing postponed data.
                time = i.find('span').text if i.find('span') is not None else i.text

                # Is the match finished?
                try:
                    state = i.find('span').text
                except AttributeError:
                    pass

                # Timezone Correction
                try:
                    # The time of the games we fetch is in
                    time = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)  # FS.mobi is 1 hour+
                    now = datetime.datetime.now().replace(second=0, microsecond=0)  # Discard microseconds
                    time = now.replace(hour=time.hour, minute=time.minute)
                    expires = time

                    # If the game appears to be in the past.
                    if now.timestamp() > time.timestamp():
                        time += datetime.timedelta(days=1)
                        expires += datetime.timedelta(days=2)

                except ValueError:
                    if "'" not in time:
                        state = time.lower()

            elif tag == "img":  # Red Cards
                if "rcard" in i.attrib['class']:
                    cards = int("".join([i for i in i.attrib['class'] if i.isdecimal()]))
                    if " - " in "".join(capture_group):
                        away_cards = cards
                    else:
                        home_cards = cards
                else:
                    print(f"Live scores loop / Unhandled class for {i.home} vs {i.away} {i.attrib['class']}")

            elif tag == "br":
                # End of match row.
                try:
                    home, away = "".join(capture_group).split(' - ', 1)  # Olympia HK can suck my fucking cock
                except ValueError:
                    print("fetch_games Value error", capture_group)
                    continue
                home = home.strip()
                away = away.strip()

                if time == "Half Time":
                    state = "ht"

                # If we are refreshing, create a new object and append it.
                if url not in self.bot.games[competition.link]:
                    fx = Fixture(time=time, home=home, away=away, url=url, competition=competition, expires=day)
                    fx.time = GameTime(time, fixture=fx)
                    fx.state = state
                    self.bot.games[url] = fx
                else:
                    # Otherwise, update the existing one and spool out notifications.
                    # Update all changed values.
                    self.bot.games[url].update_state(self.bot, state)
                    self.bot.games[url].set_cards(self.bot, home_cards)
                    self.bot.games[url].set_cards(self.bot, away_cards, home=False)
                    self.bot.games[url].set_score(self.bot, score_home)
                    self.bot.games[url].set_score(self.bot, score_away, home=False)
                    self.bot.games[url].time = GameTime(time, fixture=self.bot.games[url])
                    self.bot.games[url].state = state

                # Clear attributes
                home_cards = 0
                away_cards = 0
                state = None
                capture_group = []

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


def setup(bot):
    """Load the cog into the bot"""
    bot.add_cog(Scores(bot))
