"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from importlib import reload
from itertools import zip_longest
from typing import TYPE_CHECKING, ClassVar

from asyncpg import Record
from discord import TextChannel, ButtonStyle, Colour, Embed, PermissionOverwrite, Permissions, Message, \
    Forbidden, NotFound
from discord.app_commands import Group, describe, autocomplete
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import Button, Select, View
from lxml.etree import ParserError, tostring
from lxml.html import fromstring

import ext.toonbot_utils.flashscore as fs
import ext.toonbot_utils.gamestate
from ext.utils.embed_utils import rows_to_embeds, stack_embeds
from ext.utils.view_utils import add_page_buttons, Confirmation

if TYPE_CHECKING:
    from discord import Interaction
    from core import Bot

# Constants.
NO_GAMES_FOUND = "No games found for your tracked leagues today!" \
                 "\n\nYou can add more leagues with `/livescores add`" \
                 "\nTo find out which leagues currently have games, use `/scores`"

# Number of messages that can be simultaneously updated.
MAX_MESSAGES = 5


class ScoreChannel:
    """A livescore channel object, containing it's properties."""
    bot: Bot = None

    def __init__(self, channel: TextChannel) -> None:
        self.channel: TextChannel = channel
        self.messages: list[Message, None] = [None, None, None, None, None]
        self.leagues: list[str] = []

        # Iterate to avoid ratelimiting
        self.iteration: int = 0

    def generate_embeds(self) -> list[Embed]:
        """Have each Competition generate it's livescore embeds"""
        embeds = []
        games = self.bot.games.copy()

        for comp in set(i.competition for i in games):
            for tracked in self.leagues:
                if tracked == comp.title:
                    embeds += comp.score_embeds
                    break

                elif f"{tracked} -" in comp.title:
                    # For Competitions Such as EUROPE: Champions League - Playoffs, where we want fixtures of a part
                    # of a tournament, we need to do additional checks. We are not, for example, interested in U18, or
                    # women's tournaments unless explicitly tracked

                    ignored = ['women', 'u18']  # List of ignored substrings
                    for x in ignored:
                        if x in comp.title and x not in tracked.lower():
                            # Break without doing anything - this sub-tournament was not requested.
                            break
                    else:
                        # If we do not break, we can fetch the score embeds for that league.
                        embeds += comp.score_embeds
                        break

        if not embeds:
            return [Embed(title="No Games Found", description=NO_GAMES_FOUND)]
        return embeds

    async def get_leagues(self) -> list[str]:
        """Fetch target leagues for the ScoreChannel from the database"""
        sql = """SELECT league FROM scores_leagues WHERE channel_id = $1"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                records: list[Record] = await connection.fetch(sql, self.channel.id)

        self.leagues = [r['league'] for r in records]
        return self.leagues

    async def reset_leagues(self) -> list[str]:
        """Reset the Score Channel to the list of default leagues."""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute('''DELETE FROM scores_leagues WHERE channel_id = $1''', self.channel.id)

                sql = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
                await connection.executemany(sql, [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES])
        self.leagues = fs.DEFAULT_LEAGUES
        return self.leagues

    async def add_leagues(self, leagues: list[str]) -> list[str]:
        """Add a league to the ScoreChannel's tracked list"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                sql = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.executemany(sql, [(self.channel.id, x) for x in leagues])

        self.leagues += [i for i in leagues if i not in self.leagues]
        return self.leagues

    async def remove_leagues(self, leagues: list[str]) -> list[str]:
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from scores_leagues WHERE (channel_id, league) = ($1, $2)"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, x) for x in leagues])

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def update(self) -> list[Message | None]:
        """Edit a live-score channel to have the latest scores"""
        if self.channel.is_news():
            return []

        if not self.leagues:
            await self.get_leagues()

        embeds = self.generate_embeds()

        # Stack embeds to max size for individual message.
        stacked = stack_embeds(embeds)

        # Zip the lists into tuples to simultaneously iterate
        # Limit to 5 max
        tuples = list(zip_longest(self.messages, stacked))[:5]

        message: Message | None
        new_embeds: list[Embed]

        # Zip longest will give (, None) in slot [0] // self.messages if we do not have enough messages for the embeds.
        count = 0
        for message, new_embeds in tuples:
            try:
                # Suppress Message's embeds until they're needed again.
                if message is None and new_embeds is None:
                    continue

                if message is None:  # No message exists in cache, or we need an additional message.
                    self.messages[count] = await self.channel.send(embeds=new_embeds)
                    continue

                if new_embeds is None:
                    if not message.flags.suppress_embeds:
                        self.messages[count] = await message.edit(suppress=True)
                    continue

                if message.embeds is None:
                    message.embeds = [Embed()]

                if not set([i.description for i in new_embeds]) == set([i.description for i in message.embeds]):
                    self.messages[count] = await message.edit(embeds=new_embeds, suppress=False)
            except Forbidden:
                self.bot.score_channels.remove(self)
                return
            except NotFound:
                continue
            finally:
                count += 1
        return self.messages

    def view(self, interaction: Interaction) -> ScoresConfig:
        """Get a view representing this score channel"""
        return ScoresConfig(interaction, self)


# TODO: Allow re-ordering of leagues, set an "index" value in db and do a .sort?
# TODO: Figure out how to monitor page for changes rather than repeated scraping. Then Update iteration style.
class ScoresConfig(View):
    """Generic Config View"""
    bot: ClassVar[Bot] = None

    def __init__(self, interaction: Interaction, channel: ScoreChannel) -> None:
        super().__init__()
        self.sc: ScoreChannel = channel
        self.interaction: Interaction = interaction
        self.pages: list[Embed] = []
        self.index: int = 0

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = None) -> Message:
        """Push the newest version of view to message"""
        self.clear_items()
        leagues = await self.sc.get_leagues()

        embed: Embed = Embed(colour=Colour.dark_teal())
        embed.title = f"{self.bot.user.name} Live Scores config"
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        missing = []
        perms = self.sc.channel.permissions_for(self.sc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")
        if not perms.manage_messages:
            missing.append("manage_messages")

        if missing:
            v = "```yaml\nThis livescores channel will not work currently, I am missing the following permissions.\n"
            embed.add_field(name='Missing Permissions', value=f"{v} {missing}```")

        if leagues:
            header = f'Tracked leagues for {self.sc.channel.mention}```yaml\n'
            embeds = rows_to_embeds(embed, sorted(leagues), header=header, footer="```", rows=25)
            self.pages = embeds
            add_page_buttons(self, row=1)
            embed = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues, row=0))
        else:
            self.add_item(ResetLeagues())
            embed.description = f"No tracked leagues for {self.sc.channel.mention}" \
                                f", would you like to reset it?"

        return await self.bot.reply(self.interaction, content=content, embed=embed, view=self)

    async def remove_leagues(self, leagues: list[str]) -> Message:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_txt = '\n'.join(sorted(leagues))
        txt = f"Remove these leagues from {self.sc.channel.mention}? ```yaml\n{lg_txt}```"
        await self.bot.reply(self.interaction, content=txt, embed=None, view=view)
        await view.wait()

        if not view.value:
            return await self.update(content="No leagues were removed")

        await self.sc.remove_leagues(leagues)
        return await self.update(content=f"Removed {self.sc.channel.mention} tracked leagues: ```yaml\n{lg_txt}```")


class ResetLeagues(Button):
    """Button to reset a live score channel back to the default leagues"""

    def __init__(self) -> None:
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.sc.reset_leagues()
        return await self.view.update(content=f"Tracked leagues for {self.view.sc.channel.mention} reset")


class RemoveLeague(Select):
    """Button to bring up the remove leagues dropdown."""

    def __init__(self, leagues: list[str], row: int = 4) -> None:
        super().__init__(placeholder="Remove tracked league(s)", row=row, max_values=len(leagues))

        for lg in sorted(leagues):
            self.add_option(label=lg)

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected"""
        await interaction.response.defer()
        return await self.view.remove_leagues(self.values)


class Scores(Cog):
    """Live Scores channel module"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        self.iteration: int = 0

        reload(fs)

        if ScoreChannel.bot is None:
            ScoreChannel.bot = bot
            ScoresConfig.bot = bot

    async def cog_load(self) -> None:
        """Load our database into the bot"""
        await self.load_database()
        self.bot.scores = self.score_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.scores.cancel()
        self.bot.score_channels.clear()

    # Database load: Leagues & Teams
    async def load_database(self) -> None:
        """Load all stored leagues and competitions into the bot"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                comps = await connection.fetch("""SELECT * from fs_competitions""")
                teams = await connection.fetch("""SELECT * from fs_teams""")

        for c in comps:
            if self.bot.get_competition(c['id']) is None:
                comp = fs.Competition(self.bot, flashscore_id=c['id'], link=c['url'], name=c['name'])
                comp.country = c['country']
                comp.logo_url = c['logo_url']
                self.bot.competitions.append(comp)

        for t in teams:
            if self.bot.get_team(t['id']) is None:
                team = fs.Team(self.bot)
                team.id = t['id']
                team.url = t['url']
                team.name = t['name']
                team.logo_url = t['logo_url']
                self.bot.teams.append(team)

    # Database load: ScoreChannels
    async def update_cache(self) -> list[ScoreChannel]:
        """Grab the most recent data for all channel configurations"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM scores_leagues""")

        # Generate {channel_id: [league1, league2, league3, …]}
        channel_leagues = defaultdict(list)
        for r in records:
            channel_leagues[r['channel_id']].append(r['league'])

        for channel_id, leagues in channel_leagues.items():
            channel = self.bot.get_channel(channel_id)
            if channel is None or channel.is_news():
                continue

            try:
                sc = next(i for i in self.bot.score_channels if i.channel.id == channel_id)
            except StopIteration:
                sc = ScoreChannel(channel)
                self.bot.score_channels.append(sc)
            sc.leagues = sorted(leagues)
        return self.bot.score_channels

    # Core Loop
    @loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        self.iteration += 1

        if not self.bot.score_channels:
            await self.update_cache()

        try:
            self.bot.games = await self.fetch_games()
        except ConnectionError:
            logging.log(logging.WARNING, "Connection Error while fetching games from Flashscore")
            return

        # Used for ordinal checking, and then as a dummy value for getattr later.
        now = datetime.now(tz=timezone(timedelta(hours=1)))
        ordinal = now.toordinal()

        # Discard yesterday's games.
        self.bot.games = [g for g in self.bot.games if g.active(ordinal)]

        comps = set(i.competition for i in self.bot.games)

        for comp in comps.copy():
            e = deepcopy(await comp.base_embed)
            fix = sorted([i for i in self.bot.games if i.competition == comp],
                         key=lambda c: now if c.kickoff is None else c.kickoff)

            comp.score_embeds = rows_to_embeds(e, [i.live_score_text for i in fix], rows=50, footer=comp.table_link)

        # Bulk Create Tasks.
        for sc in self.bot.score_channels.copy():
            await sc.update()

    @score_loop.before_loop
    async def clear_old_scores(self):
        """Purge old messages from livescore channels before starting up."""
        await self.bot.wait_until_ready()

        if not self.bot.score_channels:
            await self.update_cache()

        for x in self.bot.score_channels:
            try:
                await x.channel.purge(reason="Clearing score-channel.",
                                      check=lambda m: m.author.id == self.bot.user.id,
                                      limit=20)
            except (Forbidden, NotFound):
                pass

    # Core Loop
    async def fetch_games(self) -> list[fs.Fixture]:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            match resp.status:
                case 200:
                    tree = fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))
                case _:
                    raise ConnectionError(f'[ERR] Scores error {resp.status} ({resp.reason}) during score loop')

        inner_html = tree.xpath('.//div[@id="score-data"]')[0]
        byt: bytes = tostring(inner_html)
        string: str = byt.decode('utf8')
        chunks = str(string).split('<br/>')
        competition: fs.Competition = fs.Competition(self.bot)  # Generic
        competition.name = "Unrecognised competition"

        for game in chunks:
            try:
                tree = fromstring(game)
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
                else:
                    partial = [x for x in self.bot.competitions if x.title in competition_name]  # Partial Matches
                    for substring in ['women', 'u18']:  # Filter…
                        if substring in competition_name.lower():
                            partial = [i for i in partial if substring in i.name.lower()]

                    if partial:
                        partial.sort(key=lambda x: len(x.name))
                        competition = partial[0]
                    else:
                        competition = fs.Competition(self.bot)
                        if country:
                            competition.country = country.strip()
                        if name:
                            competition.name = name.strip()
                        self.bot.competitions.append(competition)

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

                home = fs.Team(self.bot)
                away = fs.Team(self.bot)

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
                                logging.error(f"Fetch games team problem {len(teams)} teams found: {teams}")
                    case _:
                        logging.error(f"Fetch games team problem {len(teams)} teams found: {teams}")

                fixture = fs.Fixture(self.bot)
                fixture.url = url
                fixture.id = match_id
                fixture.home = home
                fixture.away = away
                self.bot.games.append(fixture)

            # Set the competition of the fixture
            if fixture.competition is None:
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
            if time_block and fixture.kickoff is None:
                if ":" in time_block[0]:
                    time = time_block[0]
                    ko = datetime.strptime(time, "%H:%M") - timedelta(hours=1)

                    # We use the parsed data to create a 'cleaner' datetime object, with no second or microsecond
                    # And set the day to today.
                    now = datetime.now(tz=timezone(timedelta()))
                    ko = now.replace(hour=ko.hour, minute=ko.minute, second=0, microsecond=0)  # Discard micros

                    # If the game appears to be in the past but has not kicked off yet, add a day.
                    if now.timestamp() > ko.timestamp() and state == "sched":
                        ko += timedelta(days=1)
                    fixture.kickoff = ko
                    fixture.ordinal = ko.toordinal()

            # What we now need to do, is figure out the "state" of the game.
            # Things may then get … more difficult. Often, the score of a fixture contains extra data.
            # So, we update the match score, and parse additional states

            score_line = ''.join(tree.xpath('.//a/text()')).split(':')

            h_score, a_score = score_line
            if a_score != "-":
                state_override = "".join([i for i in a_score if not i.isdigit()])
                h_score = int(h_score)
                a_score = int("".join([i for i in a_score if i.isdigit()]))

                if any([fixture.score_home != h_score, fixture.score_away != a_score]):
                    # Force a table update only if this is a new goal.
                    fixture.score_home = h_score
                    fixture.score_away = a_score

                if state_override:
                    match state_override:
                        case 'aet':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.AFTER_EXTRA_TIME)
                        case 'pen':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.AFTER_PENS)
                        case 'WO':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.WALKOVER)
                        case _:
                            logging.error(f"Unhandled state override {state_override}")
                    continue

            # Following the updating of the kickoff data, we can then
            match len(time_block), state:
                case 1, "live":
                    match time_block[0]:
                        case 'Half Time':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.HALF_TIME)
                        case 'Break Time':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.BREAK_TIME)
                        case 'Penalties':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.PENALTIES)
                        case 'Extra Time':
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.EXTRA_TIME)
                        case "Live":
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.FINAL_RESULT_ONLY)
                        case _:
                            if "'" not in time_block[0]:
                                logging.error(f"Unhandled 1 part state block {time_block[0]}")
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(time_block[0])
                case 1, "sched":
                    fixture.time = ext.toonbot_utils.gamestate.GameTime(
                        ext.toonbot_utils.gamestate.GameState.SCHEDULED)
                case 1, "fin":
                    fixture.time = ext.toonbot_utils.gamestate.GameTime(
                        ext.toonbot_utils.gamestate.GameState.FULL_TIME)
                # If we have a 2 part item, the second part will give us additional information
                case 2, _:
                    match time_block[-1]:
                        case "Cancelled":
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.CANCELLED)
                        case "Postponed":
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.POSTPONED)
                        case "Delayed":
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.DELAYED)
                        case "Interrupted":
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.INTERRUPTED)
                        case "Abandoned":
                            fixture.time = ext.toonbot_utils.gamestate.GameTime(
                                ext.toonbot_utils.gamestate.GameState.ABANDONED)
                        case 'Extra Time':
                            logging.error(f'VARIANT B Extra time 2 part time_block needs fixed. {time_block}')
                            # fixture.time = flashscore.GameTime(flashscore.GameState.EXTRA_TIME)
                        case _:
                            logging.error(f"Unhandled 2 part time block found {time_block}", time_block)
        return self.bot.games

    livescores = Group(guild_only=True, name="livescores", description="Create/manage livescores channels",
                       default_permissions=Permissions(manage_channels=True))

    @livescores.command()
    @describe(channel="Target Channel")
    async def manage(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """View or Delete tracked leagues from a live-scores channel."""
        if channel is None:
            channel = interaction.channel

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow("""SELECT * FROM scores_channels WHERE channel_id = $1""", channel.id)

        if not row:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        sc = next(i for i in self.bot.score_channels if i.channel.id == channel.id)
        return await sc.view(interaction).update(content=f"Fetching config for {sc.channel.mention}…")

    @livescores.command()
    @describe(name="Enter a name for the channel")
    async def create(self, interaction: Interaction, name: str = "⚽live-scores") -> Message:
        """Create a live-scores channel for your server."""
        reason = f'{interaction.user} (ID: {interaction.user.id}) created a live-scores channel.'
        topic = "Live Scores from around the world"

        try:
            channel = await interaction.guild.create_text_channel(name=name, reason=reason, topic=topic)
        except Forbidden:
            return await self.bot.error(interaction, content='I need manage_channels permissions to make a channel.')

        if interaction.app_permissions.manage_roles:
            ow = {interaction.guild.me: PermissionOverwrite(send_messages=True),
                  interaction.guild.default_role: PermissionOverwrite(send_messages=False)}
            try:
                channel = await channel.edit(overwrites=ow)
            except Forbidden:
                pass

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                q = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(q, interaction.guild.id)
                q = """INSERT INTO scores_channels (guild_id, channel_id) VALUES ($1, $2)"""
                await connection.execute(q, channel.guild.id, channel.id)

        sc = ScoreChannel(channel)
        self.bot.score_channels.append(sc)
        await sc.reset_leagues()
        await self.bot.reply(interaction, content=f"The {channel.mention} channel was created")
        try:
            await sc.channel.send(f'{interaction.user.mention} Welcome to your new livescores channel.'
                                  f'Use `/livescores add` to add new leagues.')
        except Forbidden:
            await self.bot.reply(interaction, content=f"Created {channel.mention}, but I need send_messages perms.")

    @livescores.command()
    @autocomplete(league_name=fs.lg_ac)
    @describe(league_name="league name to search for or direct flashscore link", channel="Target Channel")
    async def add_league(self, interaction: Interaction, league_name: str, channel: TextChannel = None) -> Message:
        """Add a league to an existing live-scores channel"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        try:
            sc = next(i for i in self.bot.score_channels if i.channel.id == channel.id)
        except StopIteration:
            return await self.bot.error(interaction, f"{channel.mention} is not a live-scores channel.")

        # Get the league object
        comp = self.bot.get_competition(league_name)
        if comp:
            res = comp
        elif "http" not in league_name:
            res = await fs.search(interaction, league_name, mode=comp)
            if isinstance(res, Message):
                return res
        else:
            if "flashscore" not in league_name:
                return await self.bot.error(interaction, content="Invalid link provided.")

            qry = str(league_name).strip('[]<>')  # idiots
            res = await fs.Competition.by_link(self.bot, qry)

            if res is None:
                err = f"Failed to get data for {qry} channel not modified."
                return await self.bot.error(interaction, err)

        if res.title == 'WORLD: Club Friendly':
            return await self.bot.error(interaction, "You can't add club friendlies as a competition, sorry.")
        await sc.add_leagues([res.title])
        view = sc.view(interaction)
        return await view.update(content=f"Added tracked league for {sc.channel.mention}```yaml\n{res}```")

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove all of a channel's stored data upon deletion"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute("""DELETE FROM scores_channels WHERE channel_id = $1""", channel.id)

        for c in self.bot.score_channels.copy():
            if channel.id == c.channel.id:
                self.bot.score_channels.remove(c)


async def setup(bot: Bot):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
