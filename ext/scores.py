"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
import datetime
# Misc
from copy import deepcopy
from itertools import zip_longest
# Type Hinting
from typing import List, Optional, TYPE_CHECKING

# Error Handling
from asyncpg import UniqueViolationError, ForeignKeyViolationError, Record
# Discord
from discord import ButtonStyle, Interaction, Colour, Embed, PermissionOverwrite, Message, TextChannel, Color, \
    Permissions, Guild
from discord import HTTPException, Forbidden
from discord.app_commands import Group, describe, Choice, autocomplete
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import Button, Select, View
from lxml import html, etree
from lxml.etree import ParserError

# Utils
from ext.utils import football
from ext.utils.embed_utils import rows_to_embeds, stack_embeds
from ext.utils.view_utils import add_page_buttons, Confirmation

if TYPE_CHECKING:
    from core import Bot

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

    def __init__(self, bot: 'Bot', channel_id: int):
        self.bot: Bot = bot
        self.channel_id: int = channel_id

    embeds: List[List[Embed]] = []
    _cached_embeds: List[List[Embed]] = []
    messages: List[Message | None] = []

    @property
    def mention(self):
        """mention the channel"""
        return self.bot.get_channel(self.channel_id).mention

    def generate_embeds(self, leagues: List[str]) -> List[Embed]:
        """Have each Competition generate it's livescore embeds"""
        embeds = []
        for comp in set(i.competition for i in self.bot.games):
            for tracked in leagues:
                if tracked == comp.title:
                    embeds += getattr(comp, "score_embeds", [])
                    break
                elif tracked + " -" in comp.title:  # For Competitions Such as EUROPE: Champions League - Playoffs

                    ignored = ['women', 'u18']
                    for x in ignored:
                        # If any of these things happen, invalidate with a break.
                        if x not in tracked.lower() and x in comp.title:
                            break
                    else:
                        # If we do not break, we can fetch the score embeds for that league.
                        embeds += getattr(comp, "score_embeds", [])
                        break

        if not embeds:
            return [Embed(description=NO_GAMES_FOUND)]
        return embeds

    async def get_leagues(self) -> List[str]:
        """Fetch target leagues for the ScoreChannel from the database"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """SELECT league FROM scores_leagues WHERE channel_id = $1"""
            records: List[Record] = await connection.fetch(q, self.channel_id)
        return [r['league'] for r in records]

    async def reset_leagues(self) -> None:
        """Reset the channel to the list of default leagues."""
        sql = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel_id, x) for x in DEFAULT_LEAGUES])
        finally:
            await self.bot.db.release(connection)

    async def add_league(self, res: football.Competition):
        """Add a league to the ScoreChannel's tracked list"""
        q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, self.channel_id, res.title)
        finally:
            await self.bot.db.release(connection)

    async def add_world_cup(self) -> None:
        """Add the World Cup Competitions to the ScoreChannel"""
        sql = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel_id, x) for x in WORLD_CUP_LEAGUES])
        except UniqueViolationError:
            pass
        finally:
            await self.bot.db.release(connection)

    async def remove_leagues(self, leagues: List[str]):
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from scores_leagues WHERE (channel_id, league) = ($1, $2)"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel_id, x) for x in leagues])
        finally:
            await self.bot.db.release(connection)

    async def update(self) -> None:
        """Edit a live-score channel to have the latest scores"""
        channel: TextChannel = self.bot.get_channel(self.channel_id)

        match channel:
            case channel if channel is None:  # Could not find channel object.
                return
            case channel if channel.is_news():  # News channels have high ratelimiting so we warn people.
                embeds = [Embed(description=NO_NEWS, colour=Color.red())]
            case _:
                leagues = await self.get_leagues()
                embeds = self.generate_embeds(leagues)

        # Stack embeds to max size for individual message.
        embeds = stack_embeds(embeds)

        # Zip our lists for comparative iteration.
        tuples = list(zip_longest(self.messages, self._cached_embeds, embeds))

        # If we do not have old messages: purge the channel, so we can send in our new set.
        if not self.messages:
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
        new_messages: List[Message] = []

        # Zip longest will give (, None) in slot [0] // self.messages if we do not have enough messages for the embeds.
        for message, old_embeds, new_embeds in tuples:
            try:
                if message is None:  # No message exists in cache, or we need an additional message.
                    message = await channel.send(embeds=new_embeds)
                elif new_embeds is None:
                    if not message.flags.suppress_embeds:
                        # Suppress Message's embeds until they're needed again.
                        await message.edit(suppress=True)
                elif old_embeds is None:
                    # Remove embed suppression
                    await message.edit(embeds=new_embeds, suppress=False)
                elif not set([i.description for i in new_embeds]) == set([i.description for i in old_embeds]):
                    await message.edit(embeds=new_embeds, suppress=False)
            except HTTPException:
                message = None

            new_messages.append(message)
        self._cached_embeds = embeds
        self.messages = new_messages


# TODO: Allow re-ordering of leagues, set an "index" value in db and do a .sort?
# TODO: Figure out how to monitor page for changes rather than repeated scraping. Then Update iteration style.
class ScoresConfig(View):
    """Generic Config View"""

    def __init__(self, bot: 'Bot', interaction: Interaction, channel: ScoreChannel) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: ScoreChannel = channel
        self.pages: List[Embed] = []
        self.index: int = 0
        self.bot: Bot = bot

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = "") -> Message:
        """Push the newest version of view to message"""
        self.clear_items()
        leagues = await self.channel.get_leagues()

        embed: Embed = Embed(colour=Colour.dark_teal())
        embed.title = f"{self.interaction.client.user.name} Live Scores config"
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        if leagues:
            header = f'Tracked leagues for {self.channel.mention}```yaml\n'
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

    async def remove_leagues(self, leagues: List[str]) -> Message:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        txt = f"Remove these leagues from {self.channel.mention}? {lg_text}"
        await self.bot.reply(self.interaction, content=txt, view=view)
        await view.wait()

        if not view.value:
            return await self.update(content="No leagues were removed")

        await self.channel.remove_leagues(leagues)
        return await self.update(content=f"Removed {self.channel.mention} tracked leagues: {lg_text}")


class ResetLeagues(Button):
    """Button to reset a live score channel back to it's default leagues"""
    view: ScoresConfig

    def __init__(self) -> None:
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.channel.reset_leagues()
        return await self.view.update(content=f"Tracked leagues for {self.view.channel.mention} reset")


class RemoveLeague(Select):
    """Button to bring up the remove leagues dropdown."""
    view: ScoresConfig

    def __init__(self, leagues: List[str], row: int = 4) -> None:
        super().__init__(placeholder="Remove tracked league(s)", row=row, max_values=len(leagues))

        for lg in sorted(leagues):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected"""
        await interaction.response.defer()
        return await self.view.remove_leagues(self.values)


async def lg_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """Autocomplete from list of stored leagues"""
    lgs = getattr(interaction.client, "competitions")
    lgs = [i for i in lgs if getattr(i, 'id', None) is not None]

    return [Choice(name=i.title[:100], value=i.id) for i in lgs if current.lower() in i.title.lower()][:25]


class Scores(Cog, name="LiveScores"):
    """Live Scores channel module"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

        # Score loops.
        self.bot.scores = self.score_loop.start()

    async def cog_load(self) -> None:
        """Load our database into the bot"""
        await self.update_cache()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.scores.cancel()

    # Core Loop
    @loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        try:
            assert self.bot.db is not None
            assert self.bot.session is not None
        except (AssertionError, AttributeError):
            return

        await self.fetch_games()

        # Copy to avoid size change in iteration.
        now = datetime.datetime.now().toordinal()
        games: List[football.Fixture] = []
        for x in self.bot.games.copy():
            try:
                assert x.kickoff.toordinal() != now
            except (AssertionError, AttributeError):
                games.append(x)

        comps = set(i.competition for i in games)
        for comp in comps:
            _ = await comp.live_score_embed
            e = deepcopy(_)
            e.description = ""

            now = datetime.datetime.now()

            fixtures = sorted([i for i in games if i.competition == comp], key=lambda c: getattr(c, 'kickoff', now))
            comp.score_embeds = rows_to_embeds(e, [i.live_score_text for i in fixtures], max_rows=50)

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
        competition: football.Competition = football.Competition(self.bot)  # Generic
        competition.name = "Unrecognised competition"

        for game in chunks:
            try:
                tree = html.fromstring(game)
            except ParserError:  # Document is empty because of trailing </div>
                continue

            # Check if the chunk to be parsed has is a header.
            # If it is, we need to create a new competition object.
            competition_name = ''.join(tree.xpath('.//h4/text()')).strip()
            if competition_name:
                # Loop over bot.competitions to see if we can find the right Competition object for base_embed.
                exact = [i for i in self.bot.competitions if i.title == competition_name]

                country, name = competition_name.split(':', 1)

                if exact:
                    competition = exact[0]
                    continue

                partial = [x for x in self.bot.competitions if x.title in competition_name]  # Partial Matches
                for substring in ['women', 'u18']:  # Filter...
                    if substring in competition_name.lower():
                        partial = [i for i in partial if substring in i.name.lower()]

                if partial:
                    partial.sort(key=lambda x: len(x.name))
                    competition = partial[0]
                    if len(partial) > 2:
                        print(f"[SCORES] found multiple partial matches for {competition_name}\n",
                              "\n".join([p.title for p in partial]))
                else:
                    print("Did not find stored competition for", competition_name)
                    competition = football.Competition(self.bot)
                    if country:
                        competition.country = country.strip()
                    if name:
                        competition.name = name.strip()
                    self.bot.competitions.append(competition)
                continue

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

                home = football.Team(self.bot)
                away = football.Team(self.bot)

                if len(teams) == 1:
                    teams = teams[0].split(' - ')

                match len(teams):
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

                fixture = football.Fixture(self.bot)
                fixture.url = url
                fixture.id = match_id
                fixture.home = home
                fixture.away = away
                self.bot.games.append(fixture)

            # Set the competition of the fixture
            if getattr(fixture, 'Competition', None) is None:
                fixture.competition = competition

            # Handling red cards is done relatively simply, so we do this first.
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

            # From the link of the score, we can gather info about the time valid states are:
            # sched, live, fin
            state = ''.join(tree.xpath('./a/@class')).strip()

            # The time block can be 1 element or 2 elements long.
            # Element 1 is either a time of day HH:MM (e.g. 20:45) or a time of the match (e.g. 41')
            # If Element 2 exists, it is a declaration of Cancelled, Postponed, Delayed, or similar.
            time_block = tree.xpath('./span/text()')

            # First, we check to see if we need to, and can update the fixture's kickoff
            if not hasattr(fixture, 'kickoff'):
                if ":" in time_block[0]:
                    time = time_block[0]
                    ko = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)

                    # We use the parsed data to create a 'cleaner' datetime object, with no second or microsecond
                    # And set the day to today.
                    now = datetime.datetime.now()
                    ko = now.replace(hour=ko.hour, minute=ko.minute, second=0, microsecond=0)  # Discard micros

                    # If the game appears to be in the past but has not kicked off yet, add a day.
                    if now.timestamp() > ko.timestamp() and state == "sched":
                        ko += datetime.timedelta(days=1)
                    fixture.kickoff = ko

            # What we now need to do, is figure out the "state" of the game.
            # Things may then get ... more difficult. Often, the score of a fixture contains extra data.
            # So, we update the match score, and parse additional states

            score_line = ''.join(tree.xpath('.//a/text()')).split(':')

            h_score, a_score = score_line

            if a_score != "-":
                state_override = "".join([i for i in a_score if not i.isdigit()])
                h_score = int(h_score)
                a_score = int("".join([i for i in a_score if i.isdigit()]))

                if any([fixture.score_home != h_score, fixture.score_away != a_score]):
                    # Force a table update only if this is a new goal.
                    if fixture.score_home is not None and fixture.score_away is not None:
                        await fixture.competition.table()

                    fixture.score_home = h_score
                    fixture.score_away = a_score

                if state_override:
                    match state_override:
                        case 'aet':
                            fixture.time = football.GameTime(football.GameState.AFTER_EXTRA_TIME)
                        case 'pen':
                            fixture.time = football.GameTime(football.GameState.AFTER_PENS)
                        case 'WO':
                            fixture.time = football.GameTime(football.GameState.WALKOVER)
                        case _:
                            print("Unhandled state override", state_override)
                    continue

            # Following the updating of the kickoff data, we can then
            match len(time_block):
                case 1:
                    match state:
                        case "live":
                            fixture.time = football.GameTime(time_block[0])
                        case "sched":
                            fixture.time = football.GameTime(football.GameState.SCHEDULED)
                        case "fin":
                            fixture.time = football.GameTime(football.GameState.FULL_TIME)
                    continue

                # If we have a 2 part item, the second part will give us additional information
                case 2:
                    match time_block[-1]:
                        case "Cancelled":
                            fixture.time = football.GameTime(football.GameState.CANCELLED)
                        case "Postponed":
                            fixture.time = football.GameTime(football.GameState.POSTPONED)
                        case "Delayed":
                            fixture.time = football.GameTime(football.GameState.DELAYED)
                        case "Interrupted":
                            fixture.time = football.GameTime(football.GameState.INTERRUPTED)
                        case "Abandoned":
                            fixture.time = football.GameTime(football.GameState.ABANDONED)
                        case 'Extra Time':
                            fixture.time = football.GameTime(football.GameState.EXTRA_TIME)
                        case 'Break Time':
                            fixture.time = football.GameTime(football.GameState.BREAK_TIME)
                        case 'Penalties':
                            fixture.time = football.GameTime(football.GameState.PENALTIES)
                        case 'Half Time':
                            fixture.time = football.GameTime(football.GameState.HALF_TIME)
                        case _:
                            print("Unhandled 2 part time block found", time_block)
                    continue

    async def update_cache(self) -> None:
        """Grab the most recent data for all channel configurations"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                comps = await connection.fetch("""SELECT * from fs_competitions""")
                teams = await connection.fetch("""SELECT * from fs_teams""")
                records = await connection.fetch("""SELECT DISTINCT channel_id FROM scores_leagues""")
        finally:
            await self.bot.db.release(connection)

        for c in comps:
            if self.bot.get_competition(c['id']) is None:
                comp = football.Competition(self.bot)
                comp.id = c['id']
                comp.url = c['url']
                comp.name = c['name']
                comp.country = c['country']
                comp.logo_url = c['logo_url']
                self.bot.competitions.append(comp)

        for t in teams:
            if self.bot.get_team(t['id']) is None:
                team = football.Team(self.bot)
                team.id = t['id']
                team.url = t['url']
                team.name = t['name']
                team.logo_url = t['logo_url']
                self.bot.teams.append(team)

        # Repopulate.
        for r in records:
            channel = next((i for i in self.bot.score_channels if i.channel_id == r['channel_id']), None)
            if channel is None:
                channel = self.bot.get_channel(r['channel_id'])
                if channel is None:
                    continue

                channel = ScoreChannel(self.bot, r['channel_id'])
                await channel.get_leagues()

        for ch in self.bot.score_channels.copy():
            channel = self.bot.get_channel(ch.channel_id)
            if channel is None or channel.is_news():
                self.bot.score_channels.remove(ch)

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

        channel = next(i for i in self.bot.score_channels if i.channel_id == channel.id)
        v = ScoresConfig(self.bot, interaction, channel)
        return await v.update(content=f"Fetching config for {channel.mention}...")

    @livescores.command()
    @describe(name="Enter a name for the channel")
    async def create(self, interaction: Interaction, name: str = "live-scores") -> Message:
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
        except ForeignKeyViolationError as e:
            await self.bot.error(interaction, "The database entry for your server was not found... somehow.")
            raise e
        finally:
            await self.bot.db.release(connection)

        channel = ScoreChannel(self.bot, channel.id)
        self.bot.score_channels.append(channel)
        await channel.reset_leagues()

        await self.bot.reply(interaction, content=f"The {channel.mention} channel was created")
        await channel.update()

    @livescores.command()
    @autocomplete(league_name=lg_ac)
    @describe(league_name="league name to search for or direct flashscore link", channel="Target Channel")
    async def add(self, interaction: Interaction, league_name: str, channel: TextChannel = None) -> Message:
        """Add a league to an existing live-scores channel"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        target = next((i for i in self.bot.score_channels if i.channel_id == channel.id), None)

        if target is None:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        # Get the league object
        comp = self.bot.get_competition(league_name)
        if comp:
            res = comp
        elif "http" not in league_name:
            res = await football.fs_search(self.bot, interaction, league_name, competitions=True)
            if isinstance(res, Message):
                return res
        else:
            if "flashscore" not in league_name:
                return await self.bot.error(interaction, "Invalid link provided.")

            qry = str(league_name).strip('[]<>')  # idiots
            res = await football.Competition.by_link(self.bot, qry)

            if res is None:
                err = f"Failed to get data for {qry} channel not modified."
                return await self.bot.error(interaction, err)

        await target.add_league(res)
        view = ScoresConfig(self.bot, interaction, target)
        await view.update(content=f"Added tracked league for {target.mention}```yaml\n{res}```")
        await target.update()

    @livescores.command(name="worldcup")
    @bot_has_permissions(manage_channels=True)
    @describe(channel="which channel are you editing")
    async def addwc(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """Add the qualifying tournaments for the World Cup to a live score channel"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        target = next((i for i in self.bot.score_channels if i.channel_id == channel.id), None)

        if target is None:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        await target.add_world_cup()

        res = f"{target.mention} ```yaml\n" + "\n".join(WORLD_CUP_LEAGUES) + "```"
        await ScoresConfig(self.bot, interaction, target).update(content=f"Added to tracked leagues for {res}")

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove all of a channel's stored data upon deletion"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM scores_channels WHERE channel_id = $1""", channel.id)
        finally:
            await self.bot.db.release(connection)

        for c in self.bot.score_channels.copy():
            if channel.id == c.channel_id:
                self.bot.score_channels.remove(c)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        """Remove all data for tracked channels for a guild upon guild leave"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)

        for x in self.bot.score_channels.copy():
            if self.bot.get_channel(x.channel_id).guild is None:
                self.bot.score_channels.remove(x)

    @Cog.listener()
    async def on_guild_channel_update(self, _: TextChannel, after: TextChannel) -> Optional[Message]:
        """Warn on stupidity."""
        try:
            assert not after.is_news()
            assert after.id in [i.channel_id for i in self.bot.score_channels]
        except (AttributeError, AssertionError):
            return

        await self.update_cache()
        return await after.send("You have set this channel as a 'news' channel, live scores will no longer work.")


async def setup(bot: 'Bot'):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
