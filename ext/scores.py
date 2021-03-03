# discord
import discord
from discord.ext import commands, tasks

# Misc
import datetime
from collections import defaultdict

# Web Scraping
from lxml import html

# Utils
from importlib import reload
from ext.utils import football, embed_utils

# Constants.
NO_GAMES_FOUND = "No games found for your tracked leagues today!" \
                 "\n\nYou can add more leagues with `.tb ls add league_name`" \
                 "\nYou can reset your leagues to the list of default leagues with `.tb ls reset`" \
                 "\nTo find out which leagues currently have games, use `.tb scores`"
NO_CLEAR_CHANNEL_PERM = "Unable to clean previous messages, please make sure I have manage_messages permissions," \
                        " or delete this channel."
NO_MANAGE_CHANNELS = "Unable to create live-scores channel. Please make sure I have the manage_channels permission."

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

# TODO: Allow re-ordering of leagues, set an "index" value in db and do a .sort?


class Scores(commands.Cog, name="LiveScores"):
    """Live Scores channel module"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Reload utils
        reload(football)
        reload(embed_utils)
        
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
        self.bot.scores.cancel()
    
    @property
    async def base_embed(self):
        e = discord.Embed()
        e.colour = discord.Colour.dark_orange()
        e.title = "Toonbot Live Scores config"
        e.set_thumbnail(url=self.bot.user.avatar_url)
        return e

    async def send_leagues(self, ctx, channel):
        e = await self.base_embed
        header = f'Tracked leagues for {channel.mention}'
        # Warn if they fuck up permissions.
        if not ctx.me.permissions_in(channel).send_messages:
            header += "```css\n[WARNING]: I do not have send_messages permissions in that channel!"
        leagues = self.cache[(ctx.guild.id, channel.id)]
        
        if leagues == {None}:
            e.description = header
            e.description += "```css\n[WARNING]: Your tracked leagues is completely empty! Nothing is being output!```"
            embeds = [e]
        else:
            header += "```yaml\n"
            footer = "```"
            embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=header, footer=footer)
        
        await embed_utils.paginate(ctx, embeds)
    
    async def update_cache(self):
        # Grab most recent data.
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""
            SELECT guild_id, scores_channels.channel_id, league
            FROM scores_channels
            LEFT OUTER JOIN scores_leagues
            ON scores_channels.channel_id = scores_leagues.channel_id""")
        await self.bot.db.release(connection)
        
        # Clear out our cache.
        self.cache.clear()
        warn_once = []
        
        # Repopulate.
        for r in records:
            if r['channel_id'] in warn_once:
                continue
            
            if self.bot.get_channel(r['channel_id']) is None:
                print(f"SCORES probably deleted channel: {r['channel_id']}")
                warn_once.append(r['channel_id'])
                continue
            
            self.cache[(r["guild_id"], r["channel_id"])].add(r["league"])

    async def _pick_channels(self, ctx, channels):
        # Assure guild has score channel.
        if ctx.guild.id not in [i[0] for i in self.cache]:
            await self.bot.reply(ctx, text=f'{ctx.guild.name} does not have any live scores channels set.',
                                 mention_author=True)
            return []
    
        if channels:
            # Verify selected channels are actually in the database.
            checked = []
            channels = [channels] if isinstance(channels, discord.TextChannel) else channels
            for i in channels:
                if i.id not in [c[1] for c in self.cache]:
                    await self.bot.reply(ctx, text=f"{i.mention} is not set as a live scores channel.",
                                         mention_author=True)
                else:
                    checked.append(i)
            channels = checked
    
        if not channels:
            channels = [self.bot.get_channel(i[1]) for i in self.cache if i[0] == ctx.guild.id]
            # Filter out NoneTypes caused by deleted channels.
            channels = [i for i in channels if i is not None]
    
        channel_links = [i.mention for i in channels]
        index = await embed_utils.page_selector(ctx, channel_links, choice_text="For which channel?")
    
        if index == "cancelled" or index is None:
            return None  # Cancelled or timed out.
        channel = channels[index]
    
        return channel
    
    async def update_channel(self, guild_id, channel_id):
        whitelist = self.cache[(guild_id, channel_id)]
        # Does league exist in both whitelist and found games.
        channel_leagues_required = self.game_cache.keys() & whitelist
        
        chunks = []
        this_chunk = datetime.datetime.now().strftime("Live Scores for **%a %d %b %Y** (Time Now: **%H:%M** (UTC))\n")
        if channel_leagues_required:
            # Build messages.
            for league in channel_leagues_required:
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
                    except discord.NotFound:  # reset on corruption.
                        return await self.reset_channel(channel_id, chunks)
                    except discord.HTTPException:
                        pass  # can't help.
        
        # Otherwise we build a new message list.
        else:
            await self.reset_channel(channel_id, chunks)
    
    async def reset_channel(self, channel_id, chunks):
        channel = self.bot.get_channel(channel_id)
        try:
            self.msg_dict[channel_id] = []
            await channel.purge()
        except discord.HTTPException:
            pass
        except AttributeError:  # Channel not found.
            return
        
        for x in chunks:
            # Append message ID to our list
            try:
                message = await channel.send(x)
            except discord.HTTPException:
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
        games = await self.fetch_games(self.bot.games)
        
        # Purging of "expired" games.
        target_day = datetime.datetime.now() + datetime.timedelta(hours=1)
        target_day = target_day.date()
        
        games = [i for i in games if i.date >= target_day]
        
        # If we have an item with new data, force a full cache clear. This is expected behaviour at midnight.
        if not {i.url for i in self.bot.games} & {x.url for x in games}:
            self.bot.games = []
            
        # If we only have a partial match returned, for whatever reason
        self.bot.games = [i for i in self.bot.games if i.url not in [x.url for x in games]] + [x for x in games]
        
        # Key games by league for intersections.
        game_dict = defaultdict(set)
        for i in self.bot.games:
            game_dict[i.full_league].add(i.live_score_text)
        self.game_cache = game_dict
        
        # Iterate: Check vs each server's individual config settings
        for i in self.cache.copy():  # Error if dict changes sizes during iteration.
            await self.update_channel(i[0], i[1])
    
    @score_loop.before_loop
    async def before_score_loop(self):
        await self.bot.wait_until_ready()
        await self.update_cache()
    
    async def fetch_games(self, games):
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            if resp.status != 200:
                print(f'{datetime.datetime.utcnow()} | Scores error {resp.status} ({resp.reason}) during fetch_games')
            tree = html.fromstring(bytes(bytearray(await resp.text(), encoding='utf-8')))
        elements = tree.xpath('.//div[@id="score-data"]/* | .//div[@id="score-data"]/text()')
        
        date = datetime.datetime.today().date()
        country = None
        league = None
        home_cards = ""
        away_cards = ""
        score_home = None
        score_away = None
        url = None
        time = None
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
                
                # Timezone Correction
                try:
                    time = datetime.datetime.strptime(time, "%H:%M") - datetime.timedelta(hours=1)
                    time = datetime.datetime.strftime(time, "%H:%M")
                    hour, minute = time.split(':')
                    now = datetime.datetime.now()
                    date = now.replace(hour=int(hour), minute=int(minute))
                    date = date - datetime.timedelta(hours=1)
                    date = date.date()
                except ValueError:
                    # Handle live games, cancelled, postponed, properly.
                    pass
                
                # Is the match finished?
                try:
                    state = i.find('span').text
                except AttributeError:
                    pass
            
            elif tag == "a":
                url = i.attrib['href']
                url = url.split('/?')[0].strip('/')  # Trim weird shit that causes duplicates.
                url = "http://www.flashscore.com/" + url
                score_home, score_away = i.text.split(':')
                if not state:
                    state = i.attrib['class']
                if score_away.endswith('aet'):
                    score_away = score_away.replace('aet', "").strip()
                    time = "AET"
                elif score_away.endswith('pen'):
                    score_away = score_away.replace('pen', "").strip()
                    time = "After Pens"
                
                try:
                    score_home = int(score_home)
                    score_away = int(score_away)
                except ValueError:
                    score_home, score_away = 0, 0
            
            elif tag == "img":  # Red Cards
                if "rcard" in i.attrib['class']:
                    cards = "`" + "🟥" * int("".join([i for i in i.attrib['class'] if i.isdecimal()])) + "`"
                    if " - " in "".join(capture_group):
                        away_cards = cards
                    else:
                        home_cards = cards
                else:
                    print("Live scores loop / Unhandled class for ", i.home, "vs", i.away, i.attrib['class'])
            
            elif tag == "br":
                # End of match row.
                try:
                    home, away = "".join(capture_group).split(' - ', 1)  # Olympia HK can suck my fucking cock
                except ValueError:
                    print("fetch_games Value error", capture_group)
                    continue
                home = home.strip()
                away = away.strip()

                # DEBUG
                if time == "Half Time":
                    state = "ht"
                
                # If we are refreshing, create a new object and append it.
                if url not in [fx.url for fx in games]:
                    fixture = football.Fixture(time=time, home=home, away=away, url=url, country=country,
                                               league=league,
                                               score_home=score_home, score_away=score_away, away_cards=away_cards,
                                               home_cards=home_cards, state=state, date=date)
                    new_games.append(fixture)
                
                # Otherwise, update the existing one and spool out notifications.
                else:
                    fx = [f for f in games if url == f.url][0]
                    old_score_home = fx.score_home
                    old_score_away = fx.score_away
                    old_cards_home = fx.home_cards
                    old_cards_away = fx.away_cards
                    
                    fx.time = time
                    fx.state = state
                    fx.score_home = score_home
                    fx.score_away = score_away
                    fx.home_cards = home_cards
                    fx.away_cards = away_cards
                    
                    if score_home > 0 and score_away > 0:
                        if old_score_home < score_home and old_score_away < fx.score_away:
                            if "FT" in fx.time:
                                self.bot.disaptch("fixture_event", "FULL TIME", fx)
                        else:
                            if old_score_home < fx.score_home:
                                self.bot.dispatch("fixture_event", "GOAL", fx)
                            elif old_score_home > fx.score_home:
                                self.bot.dispatch("fixture_event", "VAR", fx)
                            if old_score_away < fx.score_away:
                                self.bot.dispatch("fixture_event", "GOAL", fx, home=False)
                            elif old_score_home > fx.score_home:
                                self.bot.dispatch("fixture_event", "VAR", fx, home=False)
                    if old_cards_home != fx.home_cards:
                        self.bot.dispatch("fixture_event", "RED CARD", fx)
                    if old_cards_away != fx.away_cards:
                        self.bot.dispatch("fixture_event", "RED CARD", fx, home=False)
                
                    new_games.append(fx)
                
                # Clear attributes
                home_cards = ""
                away_cards = ""
                state = None
                capture_group = []
        return new_games
    
    @commands.group(invoke_without_command=True, aliases=['livescores'])
    @commands.has_permissions(manage_channels=True)
    async def ls(self, ctx, *, channels: commands.Greedy[discord.TextChannel] = None):
        """View the status of your live scores channels."""
        channel = await self._pick_channels(ctx, channels)
        
        if not channel:
            return  # rip

        await self.send_leagues(ctx, channel)

    @ls.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def create(self, ctx, *, name=None):
        """Create a live-scores channel for your server."""
        if not ctx.guild.me.guild_permissions.manage_channels:
            return await self.bot.reply(ctx, text='⛔ I need manage_channels permissions to make a channel, sorry.')
        
        ow = {ctx.me: discord.PermissionOverwrite(read_messages=True, send_messages=True,
                                                  manage_messages=True, read_message_history=True),
              ctx.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False,
                                                                  read_message_history=True)}
        reason = f'{ctx.author} (ID: {ctx.author.id}) created a Toonbot live-scores channel.'
        if name is None:
            name = "live-scores"
        
        
        try:
            ch = await ctx.guild.create_text_channel(name=name, overwrites=ow, reason=reason)
        except discord.Forbidden:
            return await self.bot.reply('🚫 I need manage_channels permissions to do that.')
        
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(
               """INSERT INTO scores_channels (guild_id, channel_id) VALUES ($1, $2)""", ctx.guild.id, ch.id)
            for i in DEFAULT_LEAGUES:
                await connection.execute(
                   """INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)""", ch.id, i)
    
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"The {ch.mention} channel was created successfully.")
        await self.update_cache()
        await self.update_channel(ch.guild.id, ch.id)
        await self.send_leagues(ctx, ch)
    
    @commands.has_permissions(manage_channels=True)
    @ls.command(usage="[#channel] <search query or flashscore link>")
    async def add(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *, query: commands.clean_content):
        """Add a league to an existing live-scores channel"""
        if "http" not in query:
            await self.bot.reply(ctx, text=f"Searching for {query}...", delete_after=5)
            res = await football.fs_search(ctx, query)
            if res is None:
                return
        else:
            if "flashscore" not in query:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', mention_author=True)
            
            qry = query.strip('[]<>')  # idiots
            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition().by_link(qry, page)
            except AssertionError:
                return
            finally:
                await page.close()
    
            if res is None:
                return await self.bot.reply(ctx, text=f"🚫 Failed to get data from <{qry}> channel not modified.")
        
        res = res.title  # Get competition full name from competition object.
        
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip
        
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""
                INSERT INTO scores_leagues (league,channel_id)
                VALUES ($1,$2)
                ON CONFLICT DO NOTHING
               """, res, channel.id)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ **{res}** added to the tracked leagues for {channel.mention}")
        await self.update_cache()
        await self.update_channel(channel.guild.id, channel.id)
        await self.send_leagues(ctx, channel)

    @ls.group(usage="[#channel] <Country: League Name>", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def remove(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *,
                     target: commands.clean_content):
        """Remove a competition from an existing live-scores channel"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip
        
        target = target.strip("'\"")  # Remove quotes, idiot proofing.
        leagues = [i for i in self.cache[(ctx.guild.id, channel.id)] if target.lower() in i.lower()]
        
        # Verify which league the user wishes to remove.
        index = await embed_utils.page_selector(ctx, leagues)
        if index is None or index == "cancelled":
            return  # rip.
        
        target = leagues[index]

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_leagues WHERE (league,channel_id) = ($1,$2)""",
                                     target, channel.id)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ **{target}** deleted from the tracked leagues for {channel.mention}")
        await self.update_cache()
        await self.update_channel(channel.guild.id, channel.id)
        await self.send_leagues(ctx, channel)
    
    @remove.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def all(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove ALL competitions from a live-scores channel"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip
        
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            async with connection.transaction():
                await connection.execute("""DELETE FROM scores_leagues WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)

        await self.bot.reply(ctx, text=f"✅ {channel.mention} leagues cleared.")
        await self.update_cache()
        await self.update_channel(channel.guild.id, channel.id)
        await self.send_leagues(ctx, channel)
    
    @ls.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def reset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Reset competitions for a live-scores channel to the defaults."""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip
        
        whitelist = self.cache[(ctx.guild.id, channel.id)]
        if whitelist == DEFAULT_LEAGUES:
            return await self.bot.reply(ctx, text=f"⚠ {channel.mention} is already using the default leagues.")
        
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_leagues WHERE channel_id = $1""", channel.id)
            for i in DEFAULT_LEAGUES:
                await connection.execute("""INSERT INTO scores_leagues (channel_id, league) VALUES ($1, $2)""",
                                         channel.id, i)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ {channel.mention} had it's tracked leagues reset to the defaults.")
        await self.update_cache()
        await self.update_channel(channel.guild.id, channel.id)
        await self.send_leagues(ctx, channel)
    
    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_channels WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)
        await self.update_cache()

    @ls.command(usage="<channel_id>", hidden=True)
    @commands.is_owner()
    async def admin(self, ctx, channel_id: int):
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM scores_channels WHERE channel_id = $1""", channel_id)
        await self.bot.db.release(connection)
        await self.update_cache()
        await self.bot.reply(ctx, text=f"✅ **{channel_id}** was deleted from the scores_channels table")


def setup(bot):
    bot.add_cog(Scores(bot))
