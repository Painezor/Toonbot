"""This Cog Grabs data from Flashscore and outputs the latest scores to user-configured live score channels"""
# Misc
import datetime
from collections import defaultdict

from asyncpg import UniqueViolationError, ForeignKeyViolationError
from discord import Option, ButtonStyle, Interaction, Colour, Embed, NotFound, HTTPException, PermissionOverwrite, \
    Forbidden, SlashCommandGroup
from discord.commands import permissions
from discord.ext import commands, tasks
from discord.ui import Button, Select, View
# Web Scraping
from lxml import html

from ext.utils import football, embed_utils, view_utils, timed_events

# discord

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


# Autocomplete
async def live_leagues(ctx):
    """Return list of live leagues"""
    leagues = set([i.league for i in ctx.bot.games if ctx.value.lower() in i.league.lower()])
    return sorted(list(leagues))


LEAGUES = Option(str, "Search for a competition", autocomplete=live_leagues)


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

        for league in sorted(leagues):
            self.add_option(label=league)

    async def callback(self, interaction: Interaction):
        """When a league is selected"""
        await interaction.response.defer()
        await self.view.remove_leagues(self.values)


class ConfigView(View):
    """Generic Config View"""

    def __init__(self, ctx):
        super().__init__()
        self.index = 0
        self.ctx = ctx
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

    async def interaction_check(self, interaction: Interaction):
        """Verify user of view is correct user."""
        return interaction.user.id == self.ctx.author.id

    async def get_leagues(self):
        """Fetch Leagues for View's Channel"""
        connection = await self.ctx.bot.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM scores_leagues WHERE channel_id = $1"""
            leagues = await connection.fetch(q, self.ctx.channel.id)
        await self.ctx.bot.db.release(connection)

        leagues = [r['league'] for r in leagues]
        return leagues

    async def update(self, content=""):
        """Push the newest version of view to message"""
        self.clear_items()
        leagues = await self.get_leagues()

        if leagues:
            e = Embed(colour=Colour.dark_teal(), title="Toonbot Live Scores config")
            e.set_thumbnail(url=self.ctx.channel.guild.me.display_avatar.url)

            header = f'Tracked leagues for {self.ctx.channel.mention}```yaml\n'

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
            content = f"You have no tracked leagues for {self.ctx.channel.mention}, would you like to reset it?"

        if self.message is None:
            self.message = await self.ctx.reply(content=content, embed=embed, view=self)
        else:
            await self.message.edit(content=content, embed=embed, view=self)

    async def remove_leagues(self, leagues):
        """Bulk remove leagues from a live scores channel"""
        view = view_utils.Confirmation(self.ctx, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = "```yaml\n" + '\n'.join(sorted(leagues)) + "```"
        await self.message.edit(content=f"Remove these leagues from {self.ctx.channel.mention}? {lg_text}", view=view)
        await view.wait()

        if view.value:
            connection = await self.ctx.bot.db.acquire()
            async with connection.transaction():
                q = """DELETE from scores_leagues WHERE (channel_id, league) = ($1, $2)"""
                for x in leagues:
                    await connection.execute(q, self.ctx.channel.id, x)
            await self.ctx.bot.db.release(connection)
        await self.update(content=f"Removed {self.ctx.channel.mention} tracked leagues: {lg_text}")

    async def reset_leagues(self):
        """Reset a channel to default leagues."""
        connection = await self.ctx.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
                for x in DEFAULT_LEAGUES:
                    await connection.execute(q, self.ctx.channel.id, x)
        finally:
            await self.ctx.bot.db.release(connection)
        await self.update(content=f"Tracked leagues for {self.ctx.channel.mention} reset")


class Scores(commands.Cog, name="LiveScores"):
    """Live Scores channel module"""

    def __init__(self, bot):
        self.bot = bot
        
        # Data
        if not hasattr(self.bot, "games"):
            self.bot.games = []
        self.game_cache = {}  # for fast refresh
        self.msg_dict = {}
        self.cache = defaultdict(set)
        self.bot.loop.create_task(self.update_cache())
        
        # Core loop.
        self.bot.scores = self.score_loop.start()
    
    def cog_unload(self):
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.scores.cancel()

    async def update_cache(self):
        """Grab the most recent data for all channel configurations"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT channel_id, league FROM scores_leagues""")
        finally:
            await self.bot.db.release(connection)

        # Clear out our cache.
        self.cache.clear()

        # Repopulate.
        for r in records:
            if self.bot.get_channel(r['channel_id']) is not None:
                self.cache[r["channel_id"]].add(r["league"])

    async def update_channel(self, channel_id):
        """Edit a live-score channel to have the latest scores"""
        # Does league exist in both whitelist and found games.
        _ = self.game_cache.keys() & self.cache[channel_id]

        chunks = []
        this_chunk = f"Live scores at {timed_events.Timestamp(datetime.datetime.now()).day_time}\n"
        if _:
            # Build messages.
            for league in _:
                # Chunk-ify to max message length
                hdr = f"\n**{league}**"
                if len(this_chunk + hdr) > 1999:
                    chunks += [this_chunk]
                    this_chunk = ""
                this_chunk += hdr + "\n"

                for game in sorted(self.game_cache[league]):
                    if len(this_chunk + game) > 1999:
                        chunks += [this_chunk]
                        this_chunk = ""
                    this_chunk += game + "\n"
        else:
            this_chunk += NO_GAMES_FOUND
        
        # Dump final_chunk.
        chunks += [this_chunk]
        
        # Check if we have some previous messages for this channel
        if channel_id not in self.msg_dict:
            self.msg_dict[channel_id] = {}
        
        # Expected behaviour: Edit pre-existing message with new data.
        if len(self.msg_dict[channel_id]) == len(chunks):
            for message, chunk in list(zip(self.msg_dict[channel_id], chunks)):
                # Save API calls by only editing when a change occurs.
                if message.content != chunk:
                    try:
                        await message.edit(content=chunk)
                    except NotFound:  # reset on corruption.
                        return await self.purge_chanel(channel_id, chunks)
                    except HTTPException:
                        pass  # can't help.

        # Otherwise, we build a new message list.
        else:
            await self.purge_chanel(channel_id, chunks)

    async def purge_chanel(self, channel_id, chunks):
        """Remove all live score messages from a channel"""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        try:
            self.msg_dict[channel_id] = []
            await channel.purge(limit=10, check=lambda m: m.author.id == self.bot.user.id)
        except HTTPException:
            pass

        for x in chunks:
            # Append message ID to our list
            try:
                message = await channel.send(x)
            except HTTPException:
                continue  # These are user-problems, not mine.
            except Exception as e:
                # These however need to be logged.
                print("-- error sending message to scores channel --", channel.id, e)
            else:
                self.msg_dict[channel_id].append(message)
    
    # Core Loop
    @tasks.loop(minutes=1)
    async def score_loop(self):
        """Score Checker Loop"""
        games = await self.fetch_games()
        # Purging of "expired" games.
        games = [i for i in games if i.day == datetime.datetime.now().day]
        
        # If we have an item with new data, force a full cache clear. This is expected behaviour at midnight.
        if not {i.url for i in self.bot.games} & {x.url for x in games}:
            self.bot.games = []
            
        # If we only have a partial match returned, for whatever reason
        self.bot.games = [i for i in self.bot.games if i.url not in [x.url for x in games]] + games

        # Key games by league for intersections.
        game_dict = defaultdict(set)
        for i in self.bot.games:
            game_dict[i.full_league].add(i.live_score_text)
        self.game_cache = game_dict

        # Iterate: Check vs each server's individual config settings
        for i in self.cache.copy():  # Error if dict changes sizes during iteration.
            await self.update_channel(i)

    @score_loop.before_loop
    async def before_score_loop(self):
        """Updates Cache at the start of a score loop"""
        await self.update_cache()

    async def fetch_games(self):
        """Grab current scores from flashscore"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                print(f'{datetime.datetime.utcnow()} | Scores error {resp.status} ({resp.reason}) during fetch_games')
            tree = html.fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))
        elements = tree.xpath('.//div[@id="score-data"]/* | .//div[@id="score-data"]/text()')

        country = None
        league = None
        home_cards = 0
        away_cards = 0
        score_home = None
        score_away = None
        url = None
        time = None
        day = datetime.datetime.now().day
        state = None
        capture_group = []
        new_games = []
        
        for i in elements:
            try:
                tag = i.tag
            except AttributeError:
                # Not an element. / lxml.etree._ElementUnicodeResult
                capture_group.append(i)
                continue
            
            if tag == "h4":
                country, league = i.text.split(': ')
                league = league.split(' - ')[0]
            
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
                    time = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)
                    now = datetime.datetime.now()
                    time = now.replace(hour=time.hour, minute=time.minute)

                    if now.timestamp() > time.timestamp():
                        time += datetime.timedelta(days=1)

                except ValueError:
                    if "'" not in time:
                        state = time.lower()
            
            elif tag == "a":
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

                try:
                    fx = [f for f in self.bot.games if url == f.url][0]
                except IndexError:
                    fx = football.Fixture(time=time, home=home, away=away, url=url, country=country, league=league,
                                          score_home=score_home, score_away=score_away, state=state, day=day,
                                          home_cards=home_cards, away_cards=away_cards)
                    new_games.append(fx)
                # Otherwise, update the existing one and spool out notifications.
                else:
                    state = fx.state if state == "awaiting" else state  # Ignore "awaiting" events,

                    if state == fx.state:
                        pass

                    elif state == "live":
                        if fx.state in ["sched", "delayed"]:
                            self.bot.dispatch("fixture_event", "kick_off", fx)
                        elif fx.state == "ht":
                            self.bot.dispatch("fixture_event", "second_half_begin", fx)

                        # Delays & Cancellations
                        elif fx.state == "interrupted":
                            self.bot.dispatch("fixture_event", "resumed", fx)
                        elif fx.state == "break time":
                            self.bot.dispatch("fixture_event", f"start_of_period_{fx.breaks + 1}", fx)
                        else:
                            print(f'DEBUG: Unhandled state change: {fx.state} -> {state} | {fx.url}')

                    elif state in ["interrupted", "abandoned", "postponed", "cancelled", "delayed"]:
                        self.bot.dispatch("fixture_event", state, fx)

                    elif state == "sched":
                        if fx.state == "delayed":
                            self.bot.dispatch("fixture_event", "postponed", fx)
                        elif fx.state == "postponed":
                            pass  # Don't bother sending New Date Announcement.
                        else:
                            print(f'DEBUG: Unhandled state change: {fx.state} -> {state} | {fx.url}')

                    # End Of Game
                    elif state == "fin":
                        if fx.state in ["sched", "ht"]:
                            self.bot.dispatch("fixture_event", "final_result_only", fx)
                        elif fx.state in ["live", "fin"]:
                            self.bot.dispatch("fixture_event", "full_time", fx)
                        elif fx.state == "extra_time":
                            self.bot.dispatch("fixture_event", "score_after_extra_time", fx)
                        else:
                            print(f'DEBUG: Unhandled state change: {fx.state} -> {state} | {fx.url}')

                    elif state == "after extra time":
                        self.bot.dispatch("fixture_event", "score_after_extra_time", fx)
                    elif state == "after pens":
                        self.bot.dispatch("fixture_event", "penalty_results", fx)

                    # Half Time
                    elif state == "ht":
                        mode = "half_time" if fx.state != "extra time" else "ht_et_begin"
                        self.bot.dispatch("fixture_event", mode, fx)

                    # Other Breaks.
                    elif state == "break time":
                        fx.breaks += 1
                        if fx.state == "live":
                            if not hasattr(fx, "periods"):  # A Standard Game.
                                if fx.breaks == 1:
                                    self.bot.dispatch("fixture_event", "end_of_normal_time", fx)
                                elif fx.breaks == 2:
                                    self.bot.dispatch("fixture_event", "end_of_extra_time", fx)
                                else:
                                    print(f'Scores No Mode found for break number {fx.breaks} - {fx.url}')
                            else:
                                self.bot.dispatch("fixture_event", f"end_of_period_{fx.breaks}", fx)
                        elif fx.state == "extra time":
                            if fx.breaks == 2 and not hasattr(fx, 'periods'):
                                self.bot.dispatch("fixture_event", "end_of_extra_time", fx)
                            else:
                                self.bot.dispatch("fixture_event", f"end_of_period_{fx.breaks}", fx)
                        else:
                            print(f'DEBUG: Unhandled state change: {fx.state} -> {state} | {fx.url}')

                    elif state == "extra time":
                        if fx.state == "break time":
                            if fx.breaks == 1 and not hasattr(fx, "periods"):
                                self.bot.dispatch("fixture_event", "extra_time_begins", fx)
                            elif fx.breaks == 2 and not hasattr(fx, "periods"):
                                self.bot.dispatch("fixture_event", "ht_et_end", fx)
                            else:
                                self.bot.dispatch("fixture_event", f"start_of_period_{fx.breaks + 1}", fx)
                        elif fx.state == "ht":
                            self.bot.dispatch("fixture_event", "ht_et_end", fx)
                        elif fx.state == "live":
                            self.bot.dispatch("fixture_event", "extra_time_begins", fx)
                        else:
                            print(f'DEBUG: Unhandled state change: {fx.state} -> {state} | {fx.url}')

                    elif state == "penalties":
                        self.bot.dispatch("fixture_event", "penalties_begin", fx)

                    else:
                        print(f'Unhandled State change: {fx.url} | {fx.state} -> {state}')

                    # Dispatch Events for Goals
                    if score_home > fx.score_home and score_away > fx.score_away:
                        try:
                            assert score_home > 0 and score_away > 0
                        except AssertionError:
                            print('Scores: Assertion error when sending double team goals')
                            print(f'{time}: {home} {score_home} - {score_away} {away} | {url}')
                        else:
                            self.bot.dispatch("fixture_event", "goal", fx, home=None)
                    elif score_home > fx.score_home:
                        self.bot.dispatch("fixture_event", "goal", fx)
                    elif score_away > fx.score_away:
                        self.bot.dispatch("fixture_event", "goal", fx, home=False)
                    elif score_home < fx.score_home:
                        self.bot.dispatch("fixture_event", "var_goal", fx)
                    elif score_away < fx.score_away:
                        self.bot.dispatch("fixture_event", "var_goal", fx, home=False)

                    # Dispatch cards.
                    if home_cards > fx.home_cards:
                        self.bot.dispatch("fixture_event", "red_card", fx)
                    elif home_cards < fx.home_cards:
                        self.bot.dispatch("fixture_event", "var_red_card", fx)

                    if away_cards > fx.away_cards:
                        self.bot.dispatch("fixture_event", "red_card", fx, home=False)
                    elif away_cards < fx.away_cards:
                        self.bot.dispatch("fixture_event", "var_red_card", fx, home=False)

                    # Update all changed values.
                    fx.time = time
                    fx.state = state
                    fx.score_home = score_home
                    fx.score_away = score_away
                    fx.home_cards = home_cards
                    fx.away_cards = away_cards

                    new_games.append(fx)

                # Clear attributes
                home_cards = 0
                away_cards = 0
                state = None
                capture_group = []
        return new_games

    livescores = SlashCommandGroup("livescores", "Create or manage livescores channels")

    @livescores.command()
    async def manage(self, ctx):
        """View or Delete tracked leagues from a live-scores channel."""
        if ctx.guild is None:
            return await ctx.error("This command cannot be ran in DMs")
        elif not ctx.channel.permissions_for(ctx.author).manage_channels:
            return await ctx.error("You need manage_channels permissions to edit a scores channel.")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                row = await connection.fetchrow(q, ctx.channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            return await ctx.error(f"{ctx.channel.mention} is not a live-scores channel.")

        await ConfigView(ctx).update(content=f"Fetching config for {ctx.channel.mention}...")

    @livescores.command()
    async def create(self, ctx, channel_name: Option(str, "Enter name for the the new channel", default="live-scores")):
        """Create a live-scores channel for your server."""
        if ctx.guild is None:
            return await ctx.error("This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_channels:
            return await ctx.error("You need manage_channels permissions to create a scores channel.")

        if not ctx.channel.permissions_for(ctx.me).manage_channels:
            return await ctx.error("I need manage_channels permissions to create a scores channel.")

        reason = f'{ctx.author} (ID: {ctx.author.id}) created a Toonbot live-scores channel.'
        topic = "Live Scores from around the world"

        try:
            channel = await ctx.guild.create_text_channel(name=channel_name, reason=reason, topic=topic)
        except Forbidden:
            return await ctx.error('I need manage_channels permissions to make a channel.')

        if ctx.channel.permissions_for(ctx.me).manage_roles:
            ow = {
                ctx.me: PermissionOverwrite(send_messages=True, manage_messages=True, read_message_history=True),
                ctx.guild.default_role: PermissionOverwrite(read_messages=True, send_messages=False)}
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

        await ctx.reply(content=f"The {channel.mention} channel was created! Use /livescores add in there "
                                f"to add tracked leagues.")

        await self.update_cache()
        await self.update_channel(channel.id)

    @livescores.command()
    async def add(self, ctx, league_name: LEAGUES):
        """Add a league to an existing live-scores channel"""
        if ctx.guild is None:
            return await ctx.error("This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_channels:
            return await ctx.error("You need manage_channels permissions to create a scores channel.")

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, ctx.channel.id)
        finally:
            await self.bot.db.release(connection)

        if not row:
            return await ctx.error("This command can only be ran in a live-scores channel.")

        if league_name is None:
            return await ctx.error("You need to specify a query or a flashscore team link.")

        if "http" not in league_name:
            message = await ctx.reply(content=f"Searching for {league_name}...")
            res = await football.fs_search(ctx, message, league_name)
            if res is None:
                return
        else:
            if "flashscore" not in league_name:
                return await ctx.error("Invalid link provided.")

            message = await ctx.reply(content=f"Searching for {league_name}...")
            qry = str(league_name).strip('[]<>')  # idiots
            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition.by_link(qry, page)
            finally:
                await page.close()

            if res is None:
                return await ctx.error(f"Failed to get data for {qry} channel not modified.", message=message)

        res = res.title  # Get competition full name from competition object.

        q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, ctx.channel.id, res)
        finally:
            await self.bot.db.release(connection)

        await self.update_cache()
        view = ConfigView(ctx)
        view.message = message
        await view.update(content=f"Added tracked leagues for {ctx.channel.mention}```yaml\n{res}```")

    @livescores.command(name="worldcup")
    async def addwc(self, ctx):
        """Add the qualifying tournaments for the World Cup to a live score channel"""
        if ctx.guild is None:
            return await ctx.error("This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_channels:
            return await ctx.error("You need manage_channels permissions to create a scores channel.")

        q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                row = await connection.fetchrow(q, ctx.channel.id)
                if not row:
                    return await ctx.error("This command can only be ran in a live-scores channel.")
        finally:
            await self.bot.db.release(connection)

        q = """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                for x in WORLD_CUP_LEAGUES:
                    await connection.execute(q, ctx.channel.id, x)
        except UniqueViolationError:
            pass
        finally:
            await self.bot.db.release(connection)

        res = "```yaml\n" + "\n".join(WORLD_CUP_LEAGUES) + "```"

        await self.update_cache()
        await ConfigView(ctx).update(content=f"Added to tracked leagues for {ctx.channel.mention}{res}")

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
        await self.update_cache()

    # @commands.Cog.listener()
    # async def on_guild_remove(self, guild):
    #     """Remove all data for tracked channels for a guild upon guild leave"""
    #     connection = await self.bot.db.acquire()
    #     async with connection.transaction():
    #         await connection.execute("""DELETE FROM scores_channels WHERE guild_id = $1""", guild.id)
    #     await self.bot.db.release(connection)
    #     await self.update_cache()

    @livescores.command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def scores_refresh(self, ctx):
        """ ADMIN: Force a cache refresh of the live scores"""
        self.bot.games = []
        await ctx.reply(embed=Embed(colour=Colour.og_blurple(), description="[ADMIN] Cleared global games cache."))


def setup(bot):
    """Load the cog into the bot"""
    bot.add_cog(Scores(bot))
