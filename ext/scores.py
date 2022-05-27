"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
import datetime
# Misc
from collections import defaultdict
from copy import deepcopy
from itertools import zip_longest
# Type Hinting
from typing import List, Optional, TYPE_CHECKING

# Error Handling
from asyncpg import UniqueViolationError, ForeignKeyViolationError
# Discord
from discord import ButtonStyle, Interaction, Colour, Embed, PermissionOverwrite, Message, TextChannel, Color, \
    Permissions
from discord import HTTPException, Forbidden
from discord.app_commands import command, Group, describe, Choice, guilds, autocomplete
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import Button, Select, View
from lxml import html, etree
from lxml.etree import ParserError

from ext.utils.embed_utils import rows_to_embeds
# Utils
from ext.utils.football import Team, GameTime, Fixture, Competition, fs_search, GameState
from ext.utils.view_utils import add_page_buttons, Confirmation

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


class ScoreChannel:
    """A livescore channel object, containing it's properties."""
    __slots__ = {'bot': "a Bot instance",
                 'leagues': "A list of leagues the score channel is requesting",
                 'channel_id': "The target channel's ID number",
                 'embeds': "Paginated list of Embeds for the current iteration.",
                 '_cached_embeds': "The previous Paginated list of Embeds of the channels embeds",
                 'messages': "A list of message objects for the channel"}

    def __init__(self, bot: 'Bot', channel_id: int):
        self.bot: Bot = bot
        self.channel_id = channel_id

    channel_id: int

    leagues: List[str] = []
    embeds: List[List[Embed]]
    _cached_embeds: List[List[Embed]]
    messages: List[Message | None]

    async def update(self) -> None:
        """Edit a live-score channel to have the latest scores"""
        channel: TextChannel = self.bot.get_channel(self.channel_id)
        if channel is None:
            return

        # Does league exist in both whitelist and found games
        embeds = []
        for comp in set(i.competition for i in self.bot.games):
            for tracked in self.leagues:
                if tracked == comp.title:
                    embeds += getattr(comp, "score_embeds", [])
                    break
                elif tracked + " -" in comp.title:  # For Competitions Such as EUROPE: Champions League - Playoffs
                    embeds += getattr(comp, "score_embeds", [])
                    break

        # Type Hinting for loop
        messages: List[Message]
        old_embeds: List[Embed]

        embed_new: Embed
        embed_old: Embed
        length: int = 0
        count: int = 1

        if not embeds:
            embeds = [Embed(description=NO_GAMES_FOUND)]
        if channel.is_news():
            embeds = [Embed(description=NO_NEWS, colour=Color.red())]

        # Paginate into maxsize 6000 / max number 10 chunks.
        stacked_embeds: List[Embed] = []
        for x in embeds:
            if length + len(x) < 6000 and count < 10:
                length += len(x)
                count += 1
                stacked_embeds.append(x)
            else:
                self.embeds.append(stacked_embeds)
                stacked_embeds = [x]
                length = len(x)
                count = 1

        self.embeds.append(stacked_embeds)

        # Unpack Lists to Variables.
        tuples = list(zip_longest(self.messages, self._cached_embeds, self.embeds))

        # Zip longest will give (, None) in slot [0] // self.messages if we do not have enough messages for the embeds.
        # Check for None in tuples[0] to see if we need a new message.
        if None in tuples[0]:
            # we need a new message
            try:
                if not channel.is_news():
                    # Purge up to 10 messages from last 7 days because fuck you ratelimiting.
                    ts = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=7)
                    await channel.purge(after=ts, limit=10, reason="Clean livescores channel")
            except HTTPException:
                pass

        message: Optional[Message]
        old_embeds: List[Embed]
        new_embeds: List[Embed]
        for message, old_embeds, new_embeds in tuples:
            if message is None:  # No message exists in cache, or we need an additional message.
                try:
                    self.messages.remove(message)
                    message = await channel.send(embeds=new_embeds)
                except HTTPException:
                    message = None
                self.messages.append(message)

            elif new_embeds is None:
                if not message.flags.suppress_embeds:
                    try:
                        await message.edit(suppress=True)  # Suppress Message embeds until they're needed again.
                    except HTTPException:
                        self.messages.remove(message)

            elif old_embeds is None:
                try:
                    if message.flags.suppress_embeds:
                        await message.edit(embeds=new_embeds, suppress=False)
                    else:
                        await message.edit(embeds=new_embeds)
                except HTTPException:  # Forbidden, NotFound
                    continue

            elif not set([i.description for i in new_embeds]) == set([i.description for i in old_embeds]):
                # We now have a Message, a list of old_embeds, and a list of new_embeds
                try:
                    if message.flags.suppress_embeds:
                        await message.edit(embeds=new_embeds, suppress=False)
                    else:
                        await message.edit(embeds=new_embeds)
                except HTTPException:  # Forbidden, NotFound
                    continue
            self._cached_embeds = self.embeds


# TODO: Allow re-ordering of leagues, set an "index" value in db and do a .sort?
# TODO: Figure out how to monitor page for changes rather than repeated scraping. Then Update iteration style.

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

    def __init__(self, leagues: List[str], row: int = 4) -> None:
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.max_values = len(leagues)

        for lg in sorted(leagues):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction) -> None:
        """When a league is selected"""
        await interaction.response.defer()
        await self.view.remove_leagues(self.values)


class ScoresConfig(View):
    """Generic Config View"""

    def __init__(self, bot: 'Bot', interaction: Interaction, channel: TextChannel) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel
        self.pages: List[Embed] = []
        self.index: int = 0
        self.bot: Bot = bot

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def get_leagues(self) -> List[str]:
        """Fetch Leagues for View's Channel"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM scores_leagues WHERE channel_id = $1"""
            leagues = await connection.fetch(q, self.channel.id)
        await self.bot.db.release(connection)
        return [r['league'] for r in leagues]

    async def update(self, content: str = "") -> Message:
        """Push the newest version of view to message"""
        self.clear_items()
        leagues = await self.get_leagues()

        embed: Embed = Embed(colour=Colour.dark_teal())
        embed.title = f"{self.interaction.client.user.name} Live Scores config"

        if leagues:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            header = f'Tracked leagues for {self.channel.mention}```yaml\n'

            if not leagues:
                leagues = ["```css\n[WARNING]: Your tracked leagues is completely empty! Nothing is being output!```"]

            embeds = rows_to_embeds(embed, sorted(leagues), header=header, footer="```", max_rows=25)
            self.pages = embeds
            add_page_buttons(self)
            embed = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues))
        else:
            self.add_item(ResetLeagues())
            embed.description = f"No tracked leagues for {self.channel.mention}, would you like to reset it?"

        return await self.bot.reply(self.interaction, content=content, embed=embed, view=self)

    async def remove_leagues(self, leagues) -> Message:
        """Bulk remove leagues from a live scores channel"""
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        txt = f"Remove these leagues from {self.channel.mention}? {lg_text}"
        await self.bot.reply(self.interaction, content=txt, view=view)
        await view.wait()

        if view.value:
            connection = await self.bot.db.acquire()
            async with connection.transaction():
                q = """DELETE from scores_leagues WHERE (channel_id, league) = ($1, $2)"""
                for x in leagues:
                    await connection.execute(q, self.channel.id, x)
            await self.bot.db.release(connection)
            return await self.update(content=f"Removed {self.channel.mention} tracked leagues: {lg_text}")
        else:
            return await self.update()

    async def reset_leagues(self) -> Message:
        """Reset a channel to default leagues."""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
                for x in DEFAULT_LEAGUES:
                    await connection.execute(q, self.channel.id, x)
        finally:
            await self.bot.db.release(connection)
        return await self.update(content=f"Tracked leagues for {self.channel.mention} reset")


async def lg_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Autocomplete from list of stored leagues"""
    lgs = getattr(interaction.client, "competitions")
    return [Choice(name=i.title[:100], value=i.id) for i in lgs if current.lower() in i.title.lower()][:25]


class Scores(Cog, name="LiveScores"):
    """Live Scores channel module"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

        # Score loops.
        self.bot.score_loop = self.score_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.score_loop.cancel()

    # Core Loop
    @loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        if self.bot.db is None:
            return

        await self.update_cache()
        if self.bot.session is None:
            return

        await self.fetch_games()

        games: List[Fixture]

        # Copy to avoid size change in iteration.
        games = [i for i in self.bot.games if getattr(i, 'expires') != datetime.datetime.now().toordinal()]

        comps = set(i.competition for i in games)
        for comp in comps:
            _ = await comp.live_score_embed
            e = deepcopy(_)
            e.description = ""

            fixtures = [i for i in games if i.competition == comp]
            comp.score_embeds = []
            for f in fixtures:
                if len(e) + len(f.live_score_text + "\n") < 4096:
                    e.description += f.live_score_text + "\n"
                else:
                    comp.score_embeds.append(e)
                    e = deepcopy(_)
                    e.description = f.live_score_text + "\n"

            if e.description:
                comp.score_embeds.append(e)

        for channel in self.bot.score_channels:
            await channel.update()

    async def fetch_games(self) -> None:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            match resp.status:
                case 200:
                    pass
                case _:
                    print(f'[ERR] Scores error {resp.status} ({resp.reason}) during fetch_games')
                    return
            tree = html.fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))

        inner_html = tree.xpath('.//div[@id="score-data"]')[0]
        byt: bytes = etree.tostring(inner_html)
        string: str = byt.decode('utf8')
        chunks = str(string).split('<br/>')
        competition: Competition = Competition(self.bot)

        for game in chunks:
            try:
                tree = html.fromstring(game)
            except ParserError:  # Document is empty because of trailing </div>
                continue

            # Check if chunk has header row:
            competition_name = ''.join(tree.xpath('.//h4/text()')).strip()
            if competition_name:
                # Loop over bot.competitions to see if we can find the right Competition object for base_embed.

                exact = [i for i in self.bot.competitions if i.title == competition_name]

                if exact:
                    competition = exact[0]
                else:
                    print("Did not find exact stored competition for", competition_name)
                    partial = [x for x in self.bot.competitions if x.title in competition_name]  # Partial Matches
                    print("Found partial matches", partial)
                    for substring in ['women', 'u18']:  # Filter...
                        if substring in competition_name.lower():
                            partial = [i for i in partial if "women" in i.name.lower()]

                    if partial:
                        competition = partial[0]
                        if len(partial) > 2:
                            print(f"[SCORES] found multiple partial matches for {competition_name}"
                                  f" {[c.title for c in partial]}")
                    else:
                        country, name = competition_name.split(':', 1)
                        competition = Competition(self.bot)
                        competition.country = country.strip()
                        competition.name = name.strip()

            lnk = ''.join(tree.xpath('.//a/@href'))

            try:
                match_id = lnk.split('/')[-2]
                url = "http://www.flashscore.com" + lnk
            except IndexError:
                continue

            # Set & forget: Competition, Teams
            fixture = self.bot.get_fixture(match_id)
            if fixture is None:
                # These values never need to be updated.
                teams = [i.strip() for i in tree.xpath('./text()') if i.strip()]

                if teams[0].startswith('updates'):  # ???
                    teams[0] = teams[0].replace('updates', '')

                home = Team(self.bot)
                away = Team(self.bot)
                match len(teams):
                    case 1:
                        home.name, away.name = "".join(teams).split(' - ')
                    case 2:
                        home.name = teams[0]
                        away.name = teams[1]
                    case 3:
                        match teams:
                            case _, "La Duchere", _:
                                home.name, away.name = f"{teams[0]} {teams[1]}", teams[2]
                            case _, _, "La Duchere":
                                home.name, away.name = teams[0], f"{teams[1]} {teams[2]}"
                            case "Banik Most", _, _:
                                home.name, away.name = f"{teams[0]} {teams[1]}", teams[2]
                            case _, "Banik Most", _:
                                home.name, away.name = teams[0], f"{teams[1]} {teams[2]}"
                            case _:
                                print("Fetch games team problem", len(teams), "teams found:", teams)
                                continue
                    case _:
                        print("Fetch games team problem", len(teams), "teams found:", teams)
                        continue

                fixture = Fixture(self.bot)
                fixture.url = url
                fixture.id = match_id
                fixture.home = home
                fixture.away = away

            # Get the latest version of the competition because we edit it with stuff.
            fixture.competition = competition

            # Game Time Logic.
            state = ''.join(tree.xpath('./a/@class')).strip()
            stage = tree.xpath('.//span/text() | .//div[@class="event__stage--block"]/text()')

            if stage:
                time = str(stage.pop(0))
            else:
                # "Awaiting <br/> Updates" line split breaks this
                continue

            # If there is still remaining stage data.
            if stage:
                state = str(stage.pop(0))

            # Get match score, and parse additional states.
            score_line = ''.join(tree.xpath('.//a/text()')).split(':')
            try:
                h_score, a_score = score_line

                if a_score.endswith('aet'):
                    a_score = a_score.replace('aet', '')
                    state = GameState.AFTER_EXTRA_TIME
                elif a_score.endswith('pen'):
                    a_score = a_score.replace('pen', '')
                    state = GameState.AFTER_PENS
                elif a_score.endswith('WO'):
                    a_score = a_score.replace('WO', '')
                    state = GameState.WALKOVER

                try:
                    fixture.score_home = int(h_score)
                except ValueError:
                    pass
                try:
                    fixture.score_away = int(a_score)
                except ValueError:
                    pass
            except (IndexError, ValueError):
                pass

            match state:
                case GameState():
                    pass
                case "Postponed":
                    state = GameState.POSTPONED
                case "Cancelled":
                    state = GameState.CANCELLED
                case "Delayed":
                    state = GameState.DELAYED
                case "Interrupted":
                    state = GameState.INTERRUPTED
                case "Abandoned":
                    state = GameState.ABANDONED
                case "sched" | "scheduled":
                    state = GameState.SCHEDULED
                case "fin":
                    if hasattr(fixture, "penalties_home"):
                        state = GameState.AFTER_PENS
                    else:
                        state = GameState.FULL_TIME
                case "live":
                    pass
                case _:
                    print("scores.py: Unhandled state", state)

            # Get Red Card Data
            cards = [i.replace('rcard-', '') for i in tree.xpath('./img/@class')]
            if cards:
                try:
                    home_cards, away_cards = [int(card) for card in cards]
                except ValueError:
                    if len(tree.xpath('./text()')) == 2:
                        home_cards, away_cards = int(cards[0]), None
                    else:
                        home_cards, away_cards = None, int(cards[0])

                if home_cards:
                    fixture.cards_home = home_cards

                if away_cards:
                    fixture.cards_away = away_cards

            match time:
                case 'Extra Time':
                    state = GameState.EXTRA_TIME
                case 'Break Time':
                    state = GameState.BREAK_TIME
                case 'Penalties':
                    state = GameState.PENALTIES
                case 'Half Time':
                    state = GameState.HALF_TIME
                case time if time.isdigit() or "'" in time:
                    state = GameState.LIVE
                case time if "+" in time:
                    state = GameState.STOPPAGE_TIME
                case time if ":" in time:  # This is a kickoff.
                    # self.bot.games[match_id].time = GameTime(state)
                    if not hasattr(fixture, "kickoff"):
                        ko = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)
                        now = datetime.datetime.now()
                        ko = now.replace(hour=ko.hour, minute=ko.minute, second=0, microsecond=0)  # Discard micros

                        # If the game appears to be in the past.
                        if now.timestamp() > ko.timestamp():
                            ko += datetime.timedelta(days=1)
                        expiry = ko + datetime.timedelta(days=1)
                        fixture.kickoff = ko
                        fixture.expires = expiry.toordinal()

            # State must be set before Score
            match state:
                # If it is already an instance of GameState
                case GameState():
                    fixture.time = GameTime(state)
                case _:
                    print(f"Scores.py - GameState not handled {state} | {time}")

    async def update_cache(self) -> None:
        """Grab the most recent data for all channel configurations"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                comps = await connection.fetch("""SELECT * from fs_competitions""")
                teams = await connection.fetch("""SELECT * from fs_teams""")
                records = await connection.fetch("""SELECT channel_id, league FROM scores_leagues""")
        finally:
            await self.bot.db.release(connection)

        for c in comps:
            comp = Competition(self.bot)
            comp.id = c['id']
            comp.url = c['url']
            comp.name = c['name']
            comp.country = c['country']
            comp.logo_url = c['logo_url']
            self.bot.competitions.append(comp)

        for t in teams:
            team = Team(self.bot)
            team.id = t['id']
            team.url = t['url']
            team.name = t['name']
            team.logo_url = t['logo_url']
            self.bot.teams.append(team)

        self.bot.score_channels.clear()

        # Repopulate.
        for r in records:
            channel = next((i for i in self.bot.score_channels if i.channel_id == r['channel_id']), None)
            if channel is None:
                channel = ScoreChannel(self.bot, r['channel_id'])
                self.bot.score_channels.append(channel)
            channel.leagues.append(r["league"])

        for ch in self.bot.score_channels.copy():
            channel = self.bot.get_channel(ch.channel_id)
            if channel is None or channel.is_news():
                self.bot.score_channels.remove(ch)

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel) -> None:
        """Remove all of a channel's stored data upon deletion"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM scores_channels WHERE channel_id = $1""", channel.id)
        finally:
            await self.bot.db.release(connection)

    @Cog.listener()
    async def on_guild_remove(self, guild) -> None:
        """Remove all data for tracked channels for a guild upon guild leave"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)

    livescores = Group(
        guild_only=True,
        name="livescores",
        description="Create/manage livescores channels",
        default_permissions=Permissions(manage_channels=True)
    )

    @livescores.command()
    @describe(channel="Target Channel")
    async def manage(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """View or Delete tracked leagues from a live-scores channel."""
        if channel is None:
            channel = interaction.channel

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow("""SELECT * FROM scores_channels WHERE channel_id = $1""", channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        v = ScoresConfig(self.bot, interaction, channel)
        return await v.update(content=f"Fetching config for {channel.mention}...")

    @livescores.command()
    @describe(name="Enter a name for the channel")
    async def create(self, interaction: Interaction, name: str = "live-scores"):
        """Create a live-scores channel for your server."""
        reason = f'{interaction.user} (ID: {interaction.user.id}) created a live-scores channel.'
        topic = "Live Scores from around the world"

        try:
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

        for channel in self.bot.score_channels:
            await channel.update()

    @livescores.command()
    @autocomplete(league_name=lg_ac)
    @describe(league_name="league name to search for", channel="Target Channel")
    async def add(self, interaction: Interaction, league_name: str, channel: TextChannel = None):
        """Add a league to an existing live-scores channel"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        comp = self.bot.get_competition(league_name)
        if comp:
            res = comp
        elif "http" not in league_name:
            res = await fs_search(self.bot, interaction, league_name, competitions=True)
            if isinstance(res, Message):
                return
        else:
            if "flashscore" not in league_name:
                return await self.bot.error(interaction, "Invalid link provided.")

            qry = str(league_name).strip('[]<>')  # idiots
            res = await Competition.by_link(self.bot, qry)

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

        view = ScoresConfig(self.bot, interaction, channel)
        await view.update(content=f"Added tracked league for {channel.mention}```yaml\n{res}```")

    @livescores.command(name="worldcup")
    @bot_has_permissions(manage_channels=True)
    @describe(channel="which channel are you editing")
    async def addwc(self, interaction: Interaction, channel: TextChannel = None):
        """Add the qualifying tournaments for the World Cup to a live score channel"""
        if channel is None:
            channel = interaction.channel

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, channel.id)
                if not row:
                    return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

            q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
            async with connection.transaction():
                for x in WORLD_CUP_LEAGUES:
                    await connection.execute(q, channel.id, x)
        except UniqueViolationError:
            pass
        finally:
            await self.bot.db.release(connection)

        res = f"{channel.mention} ```yaml\n" + "\n".join(WORLD_CUP_LEAGUES) + "```"
        await ScoresConfig(self.bot, interaction, channel).update(content=f"Added to tracked leagues for {res}")

    @command()
    @guilds(250252535699341312)
    async def livescore_clear(self, interaction) -> Message:
        """ ADMIN: Force a cache refresh of the live scores"""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        self.bot.games = defaultdict(dict)
        e: Embed = Embed(colour=Colour.og_blurple(), description="[ADMIN] Cleared global games cache.")
        return await self.bot.reply(interaction, embed=e)

    async def on_guild_channel_update(self, before: TextChannel, after: TextChannel) -> Optional[Message]:
        """Warn on stupidity."""
        if not after.is_news():
            return

        if before.id in [i.channel_id for i in self.bot.score_channels]:
            return await after.send("You have set this channel as a 'news' channel, live scores will no longer work.")


async def setup(bot: 'Bot'):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
