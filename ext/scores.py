"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
# Misc
import datetime
from collections import defaultdict
from copy import deepcopy
from itertools import zip_longest
from typing import List, Optional, Dict, TYPE_CHECKING, Set

from asyncpg import UniqueViolationError, ForeignKeyViolationError
from discord import ButtonStyle, Interaction, Colour, Embed, NotFound, HTTPException, PermissionOverwrite, Forbidden, \
    app_commands, Message, TextChannel, Color
from discord.ext import commands, tasks
from discord.ui import Button, Select, View
# Web Scraping
from lxml import html, etree
from lxml.etree import ParserError

from ext.utils import football, embed_utils, view_utils
from ext.utils.football import Team, GameTime, Fixture, Competition

if TYPE_CHECKING:
    from core import Bot

# from pyppeteer.errors import ElementHandleError

# Constants.
NO_GAMES_FOUND = "No games found for your tracked leagues today!" \
                 "\n\nYou can add more leagues with `/livescores add`" \
                 "\nTo find out which leagues currently have games, use `/scores`"

NO_NEWS = "Could not send livescores to this channel. Do not set livescores channels as 'announcement' channels."

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

    def __init__(self) -> None:
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

    def __init__(self, interaction: Interaction, channel: TextChannel):
        super().__init__()
        self.interaction = interaction
        self.channel: TextChannel = channel

        self.index: int = 0
        self.pages: List[Embed] = []

    async def on_timeout(self) -> None:
        """Hide menu on timeout."""
        self.clear_items()
        await self.interaction.client.reply(self.interaction, view=self, followup=False)
        self.stop()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def get_leagues(self):
        """Fetch Leagues for View's Channel"""
        connection = await self.interaction.client.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM scores_leagues WHERE channel_id = $1"""
            leagues = await connection.fetch(q, self.channel.id)
        await self.interaction.client.db.release(connection)

        leagues = [r['league'] for r in leagues]
        return leagues

    async def update(self, content: str = "") -> Message:
        """Push the newest version of view to message"""
        self.clear_items()
        leagues = await self.get_leagues()

        if leagues:
            e = Embed(colour=Colour.dark_teal(), title="Toonbot Live Scores config")
            e.set_thumbnail(url=self.interaction.client.user.display_avatar.url)

            header = f'Tracked leagues for {self.channel.mention}```yaml\n'

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
            content = f"You have no tracked leagues for {self.channel.mention}, would you like to reset it?"

        return await self.interaction.client.reply(self.interaction, content=content, embed=embed, view=self)

    async def remove_leagues(self, leagues):
        """Bulk remove leagues from a live scores channel"""
        view = view_utils.Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        txt = f"Remove these leagues from {self.channel.mention}? {lg_text}"
        await self.interaction.client.reply(self.interaction, content=txt, view=view)
        await view.wait()

        if view.value:
            connection = await self.interaction.client.db.acquire()
            async with connection.transaction():
                q = """DELETE from scores_leagues WHERE (channel_id, league) = ($1, $2)"""
                for x in leagues:
                    await connection.execute(q, self.channel.id, x)
            await self.interaction.client.db.release(connection)
        await self.update(content=f"Removed {self.channel.mention} tracked leagues: {lg_text}")

    async def reset_leagues(self):
        """Reset a channel to default leagues."""
        connection = await self.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
                for x in DEFAULT_LEAGUES:
                    await connection.execute(q, self.channel.id, x)
        finally:
            await self.interaction.client.db.release(connection)
        await self.update(content=f"Tracked leagues for {self.channel.mention} reset")


class Scores(commands.Cog, name="LiveScores"):
    """Live Scores channel module"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        self.page = None

        # Score loops.
        self.bot.score_loop = self.score_loop.start()
        # Don't bother with this just yet...
        # self.bot.fs_score_loop = self.fs_score_loop.start()

    async def cog_unload(self):
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.score_loop.cancel()
        # self.bot.fs_score_loop.cancel()

    # @tasks.loop(minutes=1)
    # async def fs_score_loop(self):
    #     """Flashscore loop."""
    #     self.bot.fs_games = await self.get_games()  # FS Version

    # Core Loop
    @tasks.loop(minutes=1)
    async def score_loop(self):
        """Score Checker Loop"""
        if self.bot.db is None:
            print("[INF] Bot.db is None in scores loop.")
            return

        await self.update_cache()
        if self.bot.session is None:
            print("[INF] Bot.session is None in scores loop.")
            return

        await self.fetch_games()

        games: dict[Competition, List[Fixture]] = dict()

        for i in self.bot.games.values():
            games.setdefault(i.competition, []).append(i)

        self.bot.scores_embeds = defaultdict(set)

        for comp, fixtures in games.items():
            _ = await comp.live_score_embed
            e = deepcopy(_)
            e.description = ""

            for f in fixtures:
                if len(e) + len(f.live_score_text + "\n") < 4096:
                    e.description += f.live_score_text + "\n"
                else:
                    self.bot.scores_embeds[comp].add(e)
                    e = deepcopy(_)
                    e.description = f.live_score_text + "\n"
            if e.description:
                self.bot.scores_embeds[comp].add(e)

        for channel_id, leagues in self.bot.scores_cache.items():  # Error if dict changes sizes during iteration.
            await self.update_channel(channel_id, leagues)

    # async def get_games(self) -> List[Fixture]:
    #     """Grab current scores from flashscore using Pyppeteer"""
    #     if self.page is None or self.page.isClosed():
    #         if self.bot.browser is None:
    #             return self.bot.fs_games  # Return until browser is actually loaded.
    #         self.page = await self.bot.browser.newPage()
    #
    #     if self.page.url != "http://www.flashscore.co.uk/":
    #         await self.page.goto("http://www.flashscore.co.uk/")
    #
    #     show_more = await self.page.xpath("//div[contains(@title, 'Display all matches')]")
    #     for x in show_more:
    #         try:
    #             await x.click()
    #         except ElementHandleError:
    #             break
    #
    #     tree = html.fromstring(await self.page.content())
    #
    #     rows = tree.xpath('.//div[@class="sportName soccer"]/div')
    #     competition: Competition = Competition()
    #     for row in rows:
    #         # This is a competition Header, update competition Info.
    #         if "event__header" in row.classes:
    #             country = ''.join(row.xpath('.//span[@class="event__title--type"]/text()'))
    #             lg = ''.join(row.xpath('.//span[@class="event__title--name"]/text()'))
    #
    #             long = f"{country.upper()}: {lg}"
    #             if long in self.bot.competitions:
    #                 competition = self.bot.competitions[long]
    #             else:
    #                 competition = Competition(name=lg, country=country)
    #             continue
    #
    #         # Fetch the Basic required Info to create our Fixture object.
    #
    #         fixture_id = row.get("id").split('_')[-1]
    #         url = "http://www.flashscore.com/match/" + fixture_id
    #
    #         # Get index of existing fixture, or create new one.
    #         if url not in self.bot.fs_games:
    #             home = ''.join(row.xpath('.//div[contains(@class, "participant--home")]//text()'))
    #             away = ''.join(row.xpath('.//div[contains(@class, "participant--away")]//text()'))
    #             self.bot.fs_games[url] = Fixture(home=Team(name=home), away=Team(name=away), competition=competition)
    #
    #         # Get scores & dispatch goals.
    #         try:
    #             sh = str(row.xpath('.//div[contains(@class, "score--home")]/text()')[0])
    #             if sh != self.bot.fs_games[url].score_home:
    #                 self.bot.fs_games[url].score_home = sh
    #                 # self.bot.fs_games[url].set_score(sh)
    #         except (IndexError, ValueError):
    #             pass
    #
    #         try:
    #             sa = str(row.xpath('.//div[contains(@class, "score--away")]/text()')[0])
    #             if sa != self.bot.fs_games[url].score_away:
    #                 self.bot.fs_games[url].score_away = sa
    #                 # self.bot.fs_games[url].set_score(sa, home=False)
    #         except (IndexError, ValueError):
    #             pass
    #         a = ".//div[@class="event__stage--block"]/text()"
    #         b = ".//div[@class="event__time"]/text()"
    #         t = ''.join(row.xpath(f'{a} | {b}'))
    #
    #         if not t:
    #             t = None
    #
    #         self.bot.fs_games[url].time = GameTime(t)
    #         # Set Red Cards
    #         self.bot.fs_games[url].home_cards = len(row.xpath('.//div[contains(@class, "participant--home")]//svg'))
    #         self.bot.fs_games[url].away_cards = len(row.xpath('.//div[contains(@class, "participant--away")]//svg'))
    #     return self.bot.fs_games

    async def fetch_games(self) -> None:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                print(f'[ERR] Scores error {resp.status} ({resp.reason}) during fetch_games')
                return
            tree = html.fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))

        inner_html = tree.xpath('.//div[@id="score-data"]')[0]
        byt: bytes = etree.tostring(inner_html)
        string: str = byt.decode('utf8')
        chunks = str(string).split('<br/>')
        competition: Competition = Competition()
        for game in chunks:
            try:
                tree = html.fromstring(game)
            except ParserError:  # Document is empty because of trailing </div>
                continue

            # Check if chunk has header row:
            header = ''.join(tree.xpath('.//h4/text()'))
            if header:
                country, name = header.split(':', 1)

                # Loop over bot.competitions to see if we can find the right Competition object for base_embed.
                for c in self.bot.competitions.values():
                    if header in c.title:
                        competition = c
                        break
                else:
                    competition = Competition(country=country.strip(), name=name.strip())
                continue  # Loop after making the competition.

            lnk = ''.join(tree.xpath('.//a/@href'))

            try:
                match_id = lnk.split('/')[-2]
            except IndexError:
                continue

            # Set & forget: Competition, Teams
            if match_id not in self.bot.games:
                # These values never need to be updated.
                teams = [i.strip() for i in tree.xpath('./text()') if i.strip()]

                if teams[0].startswith('updates'):  # ???
                    teams[0] = teams[0].replace('updates', '')

                if len(teams) == 1:
                    teams = teams[0].split(' - ')  # Teams such as Al-Whatever exist.
                if len(teams) != 2:
                    for x in ["La Duchere"]:
                        if x in teams:
                            teams = [teams[0], teams[-2]] if teams[2] == x else [teams[0:2], teams[-1]]
                    for y in ["Banik Most"]:
                        if y in teams:
                            teams = [teams[0], teams[-2]] if teams[1] == y else [teams[0:2], teams[-1]]

                url = "http://www.flashscore.com" + lnk

                if len(teams) != 2:
                    print("[mobi rewrite] Found erroneous number of teams in fixture", url, teams)
                    continue

                self.bot.games[match_id] = Fixture(url=url, id=match_id)
                self.bot.games[match_id].home = Team(name=teams[0])
                self.bot.games[match_id].away = Team(name=teams[1])

            # Get the latest version of the competition because we edit it with stuff.
            self.bot.games[match_id].competition = competition

            # Game Time Logic.
            state = ''.join(tree.xpath('./a/@class')).strip()
            stage = tree.xpath('.//span/text() | .//div[@class="event__stage--block"]/text()')

            if stage:
                time = stage.pop(0)
            else:
                print(f"No stage found in {self.bot.games[match_id].url}")
                continue

            if stage:
                state = stage.pop(0)
                if state not in ['Postponed', 'Cancelled', 'Delayed', 'Interrupted']:
                    print("Unhandled state", state)
                if stage:
                    print("Unhandled", len(stage), "Length stage found", stage)
                    continue

            # Get match score, and parse additional states.
            score_line = ''.join(tree.xpath('.//a/text()')).split(':')
            try:
                h_score, a_score = score_line

                if a_score.endswith('aet'):
                    a_score = a_score.replace('aet', '')
                    state = "AET"
                elif a_score.endswith('pen'):
                    a_score = a_score.replace('pen', '')
                    state = "After Pens"

                # Replace with set_score
                sh = None if h_score == "-" else int(h_score)
                sa = None if a_score == "-" else int(a_score)
            except IndexError:
                sh = sa = None
                print(f'Could not split {score_line} into h, a')
            except ValueError:
                sh = sa = None
                print(f'Could not convert {score_line} into ints')

            cancelled = tree.xpath('./span/@class')
            if cancelled and cancelled != ['live']:
                print('Found cancelled text', cancelled)

            # State must be set before Score
            match state:
                case 'live':
                    self.bot.games[match_id].set_time(self.bot, GameTime(time))
                case 'AET' | 'After Pens' | 'Postponed' | 'Cancelled' | 'Delayed' | 'Abandoned' | 'Interrupted':
                    self.bot.games[match_id].set_time(self.bot, GameTime(state))
                case 'sched' | 'fin':
                    if state == 'sched':
                        self.bot.games[match_id].set_time(self.bot, GameTime("scheduled"))
                    else:
                        self.bot.games[match_id].set_time(self.bot, GameTime("Full Time"))

                    if self.bot.games[match_id].kickoff is None:
                        ko = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)
                        now = datetime.datetime.now()
                        ko = now.replace(hour=ko.hour, minute=ko.minute, second=0, microsecond=0)  # Discard micros

                        # If the game appears to be in the past.
                        if now.timestamp() > ko.timestamp():
                            ko += datetime.timedelta(days=1)
                        expiry = ko + datetime.timedelta(days=1)
                        self.bot.games[match_id].kickoff = ko
                        self.bot.games[match_id].expires = expiry.day
                case _:
                    print(f"State not handled {state} | {time}")

            await self.bot.games[match_id].set_score(self.bot, sh)
            await self.bot.games[match_id].set_score(self.bot, sa, home=False)

            # Get Red Card Data
            cards = [i.replace('rcard-', '') for i in tree.xpath('./img/@class')]
            if cards:
                if len(cards) == 2:
                    home_cards, away_cards = [int(card) for card in cards]
                else:
                    if len(tree.xpath('./text()')) == 2:
                        home_cards, away_cards = int(cards[0]), None
                    else:
                        home_cards, away_cards = None, int(cards[0])

                if home_cards != self.bot.games[match_id].home_cards:
                    self.bot.games[match_id].set_cards(self.bot, home_cards)
                if away_cards != self.bot.games[match_id].away_cards:
                    self.bot.games[match_id].set_cards(self.bot, away_cards, home=False)

    async def update_cache(self) -> None:
        """Grab the most recent data for all channel configurations"""
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
            self.bot.competitions[comp.id] = comp

        for t in teams:
            team = Team(id=t['id'], url=t['url'], name=t['name'], logo_url=t['logo_url'])
            self.bot.teams[team.id] = team

        # Repopulate.
        for r in records:
            self.bot.scores_cache[r["channel_id"]].add(r["league"])

        for ch in self.bot.scores_cache.copy().keys():
            channel = self.bot.get_channel(ch)
            if channel is None or channel.is_news():
                self.bot.scores_cache.pop(ch)
                continue

    async def update_channel(self, channel_id: int, leagues: Set[str]):
        """Edit a live-score channel to have the latest scores"""
        # logging = True if channel_id == 924709355872464997 else False
        logging = False
        if logging:
            print("Logging toonbot update_channel")

        channel: TextChannel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        # Does league exist in both whitelist and found games

        available: Competition

        guild_embeds: List[Embed] = []
        for comp, embeds in self.bot.scores_embeds.items():
            for tracked in leagues:
                if tracked == comp.title:
                    guild_embeds += embeds
                    break
                elif tracked + " -" in comp.title:  # For Competitions Such as EUROPE: Champions League - Playoffs
                    guild_embeds += embeds
                    break

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
        if channel.is_news():
            guild_embeds = [Embed(description=NO_NEWS, colour=Color.red())]

        if logging:
            print("Got Guild embeds", guild_embeds)

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

        if logging:
            print("Got new_embeds_paged", new_embeds_paged)

        # Copy so we don't fucking nuke it.
        try:
            messages = self.bot.scores_messages.pop(channel_id)
            msg_list, old_embeds_paged = zip(*messages.items())
        except (KeyError, ValueError):
            msg_list, old_embeds_paged = [], []

        # Unpack Lists to Variables.
        tuples = list(zip_longest(msg_list, old_embeds_paged, new_embeds_paged))
        if None in tuples[0]:
            # we need a new message
            try:
                if channel.id == 900091291331878912:
                    print("Firing purge event for channel 900091291331878912")
                if not channel.is_news():
                    await channel.purge()
            except HTTPException:
                pass

        self.bot.scores_messages[channel_id]: Dict[Message, List[Embed]] = defaultdict(list)

        for message, old_embeds, new_embeds in tuples:
            if logging:
                print(f"Got | Message: {type(message)} | old: {type(old_embeds)} | new: {type(old_embeds)}")
            if message is None:  # No message exists in cache, or we need an additional message.
                if logging:
                    print("[TOONBOT SCORES] Message is None, sending new message.")
                try:
                    if channel.id == 900091291331878912:
                        print("Sending messages to channel 900091291331878912")
                    message = await channel.send(embeds=new_embeds)
                except HTTPException:
                    message = None

            elif new_embeds is None:
                await message.delete()  # Shorter than old message list, we do not need this message any more.
                continue

            elif not set([i.description for i in new_embeds]) == set([i.description for i in old_embeds]):
                if logging:
                    print("[TOONBOT SCORES] new_embeds is None, deleting a messagee.")
                # We now have a Message, a list of old_embeds, and a list of new_embeds
                try:
                    await message.edit(embeds=new_embeds)
                except NotFound:
                    continue
            else:
                if logging:
                    print("[TOONBOT SCORES] embeds are identical.")
                    for x, y in zip(old_embeds, new_embeds):
                        print("================================")
                        print(x.description == y.description)
                        print(x.description)
                        print(y.description)
                        print("================================")
            if logging:
                print("Inserted message into channel_id", channel_id)
            self.bot.scores_messages[channel_id][message] = new_embeds
            if logging:
                print(self.bot.scores_messages[channel_id])

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
    @app_commands.describe(channel="Target Channel")
    async def manage(self, interaction: Interaction, channel: Optional[TextChannel]):
        """View or Delete tracked leagues from a live-scores channel."""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        elif not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to edit a scores channel."
            return await self.bot.error(interaction, err)

        channel = interaction.channel if channel is None else channel

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow("""SELECT * FROM scores_channels WHERE channel_id = $1""", channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            err = f"{channel.mention} is not a live-scores channel."
            return await self.bot.error(interaction, err)

        await ScoresConfig(interaction, channel).update(content=f"Fetching config for {channel.mention}...")

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
                await connection.execute(q, channel.guild.id, channel.id)

                qq = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                for i in DEFAULT_LEAGUES:
                    await connection.execute(qq, channel.id, i)
        except ForeignKeyViolationError:
            await self.bot.error(interaction, "The database entry for your server was not found... somehow.")
            raise ForeignKeyViolationError
        finally:
            await self.bot.db.release(connection)

        await self.bot.reply(interaction, content=f"The {channel.mention} channel was created")

        await self.update_cache()
        leagues = self.bot.scores_cache[channel.id]
        await self.update_channel(channel.id, leagues)

    # Autocomplete
    async def lg_ac(self, _: Interaction, current: str, __) -> List[app_commands.Choice[str]]:
        """Autocomplete from list of stored leagues"""
        lgs = self.bot.competitions.values()
        return [app_commands.Choice(name=i.title, value=i.id) for i in lgs if current.lower() in i.title.lower()][:25]

    @livescores.command()
    @app_commands.describe(league_name="league name to search for", channel="Target Channel")
    @app_commands.autocomplete(league_name=lg_ac)
    async def add(self, interaction: Interaction, league_name: str, channel: Optional[TextChannel]):
        """Add a league to an existing live-scores channel"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await self.bot.error(interaction, err)

        channel = interaction.channel if channel is None else channel

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        if league_name in self.bot.competitions:
            res = self.bot.competitions[league_name]
        elif "http" not in league_name:
            res = await football.fs_search(interaction, league_name)
            if res is None:
                return
        else:
            if "flashscore" not in league_name:
                return await self.bot.error(interaction, "Invalid link provided.")

            qry = str(league_name).strip('[]<>')  # idiots
            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition.by_link(qry, page)
            finally:
                await page.close()

            if res is None:
                err = f"Failed to get data for {qry} channel not modified."
                return await self.bot.error(interaction, err)

        q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id, res.title)
        finally:
            await self.bot.db.release(connection)

        view = ScoresConfig(interaction, channel)
        await view.update(content=f"Added tracked league for {channel.mention}```yaml\n{res}```")

    @livescores.command(name="worldcup")
    async def addwc(self, interaction: Interaction, channel: Optional[TextChannel]):
        """Add the qualifying tournaments for the World Cup to a live score channel"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to create a scores channel."
            return await self.bot.error(interaction, err)

        channel = interaction.channel if channel is None else channel

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, channel.id)
                if not row:
                    err = "This command can only be ran in a live-scores channel."
                    return await self.bot.error(interaction, err)

            q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
            try:
                async with connection.transaction():
                    for x in WORLD_CUP_LEAGUES:
                        await connection.execute(q, channel.id, x)
            except UniqueViolationError:
                pass
        finally:
            await self.bot.db.release(connection)

        res = f"{channel.mention} ```yaml\n" + "\n".join(WORLD_CUP_LEAGUES) + "```"
        await ScoresConfig(interaction, channel).update(content=f"Added to tracked leagues for {res}")

    @app_commands.command()
    @app_commands.guilds(250252535699341312)
    async def livescore_clear(self, interaction) -> Message:
        """ ADMIN: Force a cache refresh of the live scores"""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        self.bot.games = defaultdict(dict)
        e = Embed(colour=Colour.og_blurple(), description="[ADMIN] Cleared global games cache.")
        return await self.bot.reply(interaction, embed=e)

    async def on_guild_channel_update(self, before: TextChannel, after: TextChannel):
        """Warn on stupidity."""
        if not after.is_news():
            return

        if before.id in self.bot.scores_messages:
            await after.send("You have set this channel as a 'news' channel, live scores will no longer work.")


async def setup(bot: 'Bot'):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
