"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
import asyncio
import typing
from collections import defaultdict
from importlib import reload

import discord
from asyncpg import UniqueViolationError
from discord.ext import commands

from ext.utils import football, embed_utils, view_utils

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

edict = {
    "goal": discord.Colour.dark_green(),
    "red_card": discord.Colour.red(),
    "var_goal": discord.Colour.og_blurple(),
    "var_red_card": discord.Colour.og_blurple(),
    "goal_overturned": discord.Colour.og_blurple(),
    "red_card_overturned": discord.Colour.og_blurple(),

    "kick_off": discord.Colour.green(),

    "delayed": discord.Colour.orange(),
    "interrupted": discord.Colour.dark_orange(),

    "cancelled": discord.Colour.red(),
    "postponed": discord.Colour.red(),
    "abandoned": discord.Colour.red(),

    "resumed": discord.Colour.light_gray(),
    "second_half_begin": discord.Color.light_gray(),

    "half_time": 0x00ffff,

    "end_of_normal_time": discord.Colour.greyple(),
    "extra_time_begins": discord.Colour.lighter_grey(),
    "ht_et_begin": discord.Colour.light_grey(),
    "ht_et_end": discord.Colour.dark_grey(),
    "end_of_extra_time": discord.Colour.darker_gray(),
    "penalties_begin": discord.Colour.dark_gold(),

    "full_time": discord.Colour.teal(),
    "final_result_only": discord.Colour.teal(),
    "score_after_extra_time": discord.Colour.teal(),
    "penalty_results": discord.Colour.teal()
}

# Refresh a maximum of x fixtures at a time
max_pages = asyncio.Semaphore(5)


# TODO: Select / Button Pass.


def get_event_type(mode):
    """This would've been a fucking dict but it broke so now it's a function."""
    if mode == "goal":
        return tuple([football.Goal, football.VAR])
    elif mode == "red_card":
        return football.RedCard
    elif mode in ("var_goal", "var_red_card"):
        return football.VAR
    else:
        return None


def check_mode(mode):
    """Get appropriate DB Setting for ticker event"""
    if mode == "ht_et_begin":  # Special Check - Must pass both
        return ["half_time", "extra_time"]
    elif mode == "ht_et_end":  # Special Check - Must pass both
        return ["second_half_begin", "extra_time"]

    elif mode == "resumed":
        return ["kick_off"]

    elif mode in ["var_red_card", "var_goal", "red_card_overturned", "goal_overturned"]:
        return ["var"]

    elif mode in ["interrupted", "postponed", "cancelled"]:
        return ["delayed"]

    elif mode in ["extra_time_begins", "end_of_normal_time", "end_of_extra_time"]:
        return ["extra_time"]

    elif mode in ["score_after_extra_time", "abandoned", "full_time"]:
        return ["full_time"]

    elif mode in ["penalties_begin", "penalty_results"]:
        return ["penalties"]

    elif "start_of_period" in mode:
        return ["second_half_begin"]

    elif "end_of_period" in mode:
        return ["half_time"]

    else:
        return [mode]


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(self, bot, fixture, mode, channels: typing.List[typing.Tuple[int, bool]], home=False):
        self.bot = bot
        self.fixture = fixture
        self.mode = mode
        self.channels = channels
        self.home = home

        # dynamic properties
        self.retry = 0
        self.messages = []
        self.needs_refresh = True
        self.needs_extended = True if any([i[1] for i in channels]) else False

        # For exact event.
        self.event = None
        self.event_index = None

        # Begin loop on init
        bot.loop.create_task(self.event_loop())

    @property
    async def embed(self):
        """The embed for the fixture event."""
        e = await self.fixture.base_embed
        e.title = None
        e.remove_author()

        m = self.mode.title().replace('_', ' ')
        if self.mode == "Kick off":
            e = await self.embed
            e.description = f"**Kick Off** | [{self.fixture.bold_score}]({self.fixture.url})"
            e.colour = discord.Colour.lighter_gray()

        elif "ht_et" in self.mode:
            temp_mode = "Half Time" if self.mode == "ht_et_begin" else "Second Half Begins"
            e.description = f"Extra Time: {temp_mode} | [{self.fixture.bold_score}]({self.fixture.url})"

        elif self.mode in ["goal", "var_goal", "red_card", "var_red_card"]:
            h, a = ('**', '') if self.home else ('', '**')  # Bold Home or Away Team Name.
            h, a = ('**', '**') if self.home is None else (h, a)
            home = f"{h}{self.fixture.home} {self.fixture.score_home}{h}"
            away = f"{a}{self.fixture.score_away} {self.fixture.away}{a}"
            e.description = f"**{m}** | [{home} - {away}]({self.fixture.url})\n"

        elif self.mode == "penalties_begin":
            e.description = f"**Penalties Begin** | {self.fixture.bold_score}"

        elif self.mode == "penalty_results":
            try:
                h, a = ("**", "") if self.fixture.penalties_home > self.fixture.penalties_away else ("", "**")
                home = f"{h}{self.fixture.home} {self.fixture.penalties_home}{h}"
                away = f"{a}{self.fixture.penalties_away} {self.fixture.away}{a}"

                e.description = f"**Penalty Shootout Results** | [{home} - {away}]({self.fixture.url})"
            except TypeError:  # If penalties_home / penalties_away are NoneType
                e.description = f"**Penalty Shootout Results** | [{self.fixture.bold_score}]({self.fixture.url})\n"

            events = [i for i in self.fixture.events if isinstance(i, football.Penalty) and i.shootout is True]

            # iterate through everything after penalty header
            home = [str(i) for i in events if i.team == self.fixture.home]
            away = [str(i) for i in events if i.team == self.fixture.away]

            if home:
                e.add_field(name=self.fixture.home, value="\n".join(home))
            if away:
                e.add_field(name=self.fixture.away, value="\n".join(away))

        else:
            e.description = f"**{m}** | [{self.fixture.bold_score}]({self.fixture.url})\n"

        # Fetch Embed Colour
        if "end_of_period" in self.mode:
            e.colour = discord.Colour.greyple()
        else:
            try:
                e.colour = edict[self.mode]
            except Exception as err:
                print(f"Ticker Embed Colour: edict error for mode {self.mode}", err)

        # Append our event
        if self.event is not None:
            e.description += str(self.event)
            if hasattr(self.event, "full_description"):
                e.description += f"\n\n{self.event.full_description}"

        # Append extra info
        if self.fixture.infobox is not None:
            e.description += f"```yaml\n{self.fixture.infobox}```"

        e.set_footer(text=self.fixture.event_footer)
        return e

    @property
    async def full_embed(self):
        """Extended Embed with all events for Extended output mode"""
        e = await self.embed
        if self.fixture.events:
            for i in self.fixture.events:
                if isinstance(i, (football.Substitution, football.Booking)):
                    continue
                e.description += f"{str(i)}\n"

        return e

    @property
    def valid_events(self):
        """Valid events for ticker mode"""
        if self.mode == "goal":
            return tuple([football.Goal, football.VAR])
        elif self.mode == "red_card":
            return football.RedCard
        elif self.mode in ("var_goal", "var_red_card"):
            return football.VAR
        return None

    async def retract_event(self):
        """Handle corrections for erroneous events"""
        if self.mode == "goal":
            self.mode = "goal_overturned"
            await self.bulk_edit()
        elif self.mode == "red_card":
            self.mode = "red_card_overturned"
            await self.bulk_edit()
        else:
            print(f'[WARNING] {self.fixture} Ticker: Attempted to retract event for missing mode: {self.mode}')

    async def send_messages(self):
        """Dispatch latest event embed to all applicable channels"""
        for channel_id, extended in self.channels:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue

            # True means Use Extended, False means use normal.
            try:
                _ = await self.full_embed if extended else await self.embed
            except KeyError as e:
                print('ticker - send_messages: Key Error', extended, self.mode, e)
                continue

            try:
                self.messages.append(await channel.send(embed=_))
            except discord.HTTPException as err:
                print("Ticker.py send:", channel.id, err)
                continue

    async def bulk_edit(self):
        """Edit existing messages"""
        for message in self.messages:
            r = next((i for i in self.channels if i[0] == message.channel.id), None)
            if r is None:
                continue

            # False means short embed, True means Extended Embed
            try:
                embed = await self.full_embed if r[1] else await self.embed
            except KeyError as e:
                print("Ticker, bulk edit, key error", e, self.mode, r)
                continue

            try:
                await message.edit(embed=embed)
            except discord.HTTPException:
                continue

    async def event_loop(self):
        """The Fixture event's internal loop"""
        # Handle full time only events.
        if self.mode == "kick_off":
            await self.send_messages()
            return

        while self.needs_refresh:
            # Fallback, Wait 2 minutes extra pre refresh
            _ = 120 * self.retry if self.retry in range(5) else False
            if _ is False:
                await self.bulk_edit()
                return
            else:
                await asyncio.sleep(_)

            page = await self.bot.browser.newPage()
            async with max_pages:
                try:
                    await self.fixture.refresh(page)
                finally:  # ALWAYS close the browser after refreshing to avoid Memory leak
                    await page.close()

            self.retry += 1

            # Figure out which event we're supposed to be using (Either newest event, or Stored if refresh)
            if self.event_index is not None:
                try:
                    self.event = self.fixture.events[self.event_index]
                    assert isinstance(self.event, self.valid_events)
                    # Event deleted or replaced.
                except (IndexError, AssertionError):
                    return await self.retract_event()

                if self.needs_extended:
                    if all([i.player for i in self.fixture.events[:self.event_index + 1]]):
                        self.needs_refresh = False
                else:
                    if self.event.player:
                        self.needs_refresh = False

            else:
                if self.fixture.events:
                    if self.valid_events is not None:
                        try:
                            events = [i for i in self.fixture.events if isinstance(i, self.valid_events)]
                            _ = self.fixture.home if self.home else self.fixture.away
                            event = [i for i in events if i.team == _].pop()
                            self.event_index = self.fixture.events.index(event)
                            self.event = event

                            if self.needs_extended:
                                if all([i.player for i in self.fixture.events[:self.event_index + 1]]):
                                    self.needs_refresh = False
                            else:
                                if event.player:
                                    self.needs_refresh = False
                        except IndexError:
                            self.event = None
                            self.event_index = None

            if self.messages:
                if not self.needs_refresh:
                    await self.bulk_edit()
                    return
            else:
                await self.send_messages()


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "⚽"
        self.cache = defaultdict(set)
        self.bot.loop.create_task(self.update_cache())
        self.warn_once = []
        reload(football)

    async def update_cache(self):
        """Grab and cache the most recent version of the database"""
        # Grab most recent data.
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""
            SELECT guild_id, ticker_channels.channel_id, league
            FROM ticker_channels LEFT OUTER JOIN ticker_leagues
            ON ticker_channels.channel_id = ticker_leagues.channel_id""")
        await self.bot.db.release(connection)

        # Clear out our cache.
        new_cache = defaultdict(set)

        # Repopulate.
        for r in records:
            if (r['guild_id'], r['channel_id']) in self.warn_once:
                continue

            ch = self.bot.get_channel(r['channel_id'])

            if ch is None:
                print(f"TICKER potentially deleted channel: {r['channel_id']}")
                self.warn_once.append((r["guild_id"], r["channel_id"]))
                continue

            perms = ch.permissions_for(ch.guild.me)
            if not perms.send_messages or not perms.embed_links:
                self.warn_once.append((r["guild_id"], r["channel_id"]))

            new_cache[(r["guild_id"], r["channel_id"])].add(r["league"])

        self.cache = new_cache

    @property
    async def base_embed(self):
        """Generic Discord Embed for Ticker Configuration"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Toonbot Ticker config"
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        return e

    async def send_leagues(self, ctx, channel):
        """Sends embed detailing the tracked leagues for a channel."""
        e = await self.base_embed
        # Warn if they fuck up permissions.
        if not channel.permissions_for(ctx.me).send_messages:
            v = f"```css\n[WARNING]: I do not have send_messages permissions in {channel.mention}!"
            e.add_field(name="Cannot send Messages", value=v)
        if not channel.permissions_for(ctx.me).embed_links:
            v = f"```css\n[WARNING]: I do not have embed_links permissions in {channel.mention}!"
            e.add_field(name="Cannot send Embeds", value=v)

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            leagues = await connection.fetch("""
            SELECT league FROM ticker_leagues WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)

        if not leagues:
            leagues = ["```css\n[WARNING]: Your tracked leagues is completely empty! Nothing is being output!```"]
        else:
            leagues = [r['league'] for r in leagues]

        embeds = embed_utils.rows_to_embeds(e, sorted(leagues), header=f'Tracked leagues for {channel.mention}')
        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching tracked leagues...", view=view)
        await view.update()

    async def send_settings(self, ctx, channel):
        """Send embed detailing your ticker settings for a channel."""
        e = await self.base_embed
        # Warn if they fuck up permissions.
        if not channel.permissions_for(ctx.me).send_messages:
            v = f"```css\n[WARNING]: I do not have send_messages permissions in {channel.mention}!"
            e.add_field(name="Can't Send Messages", value=v)
        if not channel.permissions_for(ctx.me).embed_links:
            v = f"```css\n[WARNING]: I do not have embed_links permissions in {channel.mention}!"
            e.add_field(name="Can't Send Embeds", value=v)

        c = await self.bot.db.acquire()
        async with c.transaction():
            cs = await c.fetchrow("""SELECT * from ticker_settings WHERE channel_id = $1""", channel.id)
            if cs is None:
                await c.fetchrow("""INSERT INTO ticker_settings (channel_id) VALUES ($1) RETURNING *""", channel.id)
        await self.bot.db.release(c)

        def fmt(value):
            """Null/True/False to English."""
            if value is None:
                return "Off"
            return "On" if value else "Extended"

        header = f"Tracked events for {channel.mention}"
        desc = "\n".join([f"{k.replace('_', ' ').title()}: {fmt(v)}" for k, v in cs.items() if k != "channel_id"])
        e.description = header + f"```yaml\n{desc}```"
        await self.bot.reply(ctx, embed=e)

    @commands.Cog.listener()
    async def on_fixture_event(self, mode, f: football.Fixture, home=True):
        """Event handler for when something occurs during a fixture."""

        _ = check_mode(mode)
        connection = await self.bot.db.acquire()

        columns = ", ".join(_)
        not_nulls = " AND ".join([f'({x} IS NOT NULL)' for x in _])
        sql = f"""SELECT {columns}, ticker_settings.channel_id FROM ticker_settings LEFT JOIN ticker_leagues 
                ON ticker_settings.channel_id = ticker_leagues.channel_id WHERE {not_nulls} AND (league = $1::text)"""

        try:
            async with connection.transaction():
                records = await connection.fetch(sql, f.full_league)
        except Exception as e:
            print(sql)
            raise e
        finally:
            await self.bot.db.release(connection)

        for _ in list(records):
            try:
                channel = self.bot.get_channel(_['channel_id'])
                assert channel is not None
                assert channel.permissions_for(channel.guild.me).send_messages
                assert channel.permissions_for(channel.guild.me).embed_links
            except AssertionError:
                records.remove(_)

        channels = [(int(r.pop(-1)), all(r)) for r in [list(x) for x in records]]

        if not channels:  # skip fetch if unwanted.
            return

        # Settings for those IDs
        TickerEvent(self.bot, channels=channels, fixture=f, mode=mode, home=home)

    async def _pick_channels(self, ctx, channels):
        # Assure guild has goal ticker channel.
        channels = [channels] if isinstance(channels, discord.TextChannel) else channels

        if ctx.guild.id not in [i[0] for i in self.cache]:
            await self.bot.reply(ctx, text=f'{ctx.guild.name} does not have any tickers.', ping=True)
            channels = []

        if channels:
            # Verify selected channels are actually in the database.
            checked = []
            for i in channels:
                if i.id not in [c[1] for c in self.cache]:
                    await self.bot.reply(ctx, text=f"{i.mention} does not have any tickers.", ping=True)
                else:
                    checked.append(i)
            channels = checked

        if not channels:
            channels = [self.bot.get_channel(i[1]) for i in self.cache if i[0] == ctx.guild.id]
            # Filter out NoneTypes caused by deleted channels.
            channels = [i for i in channels if i is not None]

        channel_links = [i.mention for i in channels]

        index = await embed_utils.page_selector(ctx, channel_links, choice_text="For which channel?")

        if index == "cancelled" or index == -1 or index is None:
            return None  # Cancelled or timed out.
        channel = channels[index]
        return channel

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def ticker(self, ctx, *, channels: commands.Greedy[discord.TextChannel] = None):
        """View the status of your Tickers."""
        channel = await self._pick_channels(ctx, channels)

        if not channel:
            return  # rip

        await self.send_leagues(ctx, channel)

    @ticker.command(usage="[#channel-Name]", aliases=["create", "make"])
    @commands.has_permissions(manage_channels=True)
    async def set(self, ctx, ch: discord.TextChannel = None):
        """Add a ticker to one of your server's channels."""
        if ch is None:
            ch = ctx.channel

        gid = ch.guild.id
        c = await self.bot.db.acquire()
        try:
            async with c.transaction():
                await c.execute("""INSERT INTO ticker_channels (guild_id, channel_id) VALUES ($1, $2)""", gid, ch.id)
                await c.execute("""INSERT INTO ticker_settings (channel_id) VALUES ($1)""", ch.id)
        except UniqueViolationError:
            return await self.bot.reply(ctx, text=f'{ch.mention} already has a ticker.')
        finally:
            await self.bot.db.release(c)

        for i in DEFAULT_LEAGUES:
            await self.add_league(ch.id, i)

        await self.bot.reply(ctx, text=f"A ticker was successfully added to {ch.mention}")
        await self.update_cache()
        await self.send_leagues(ctx, ch)

    @ticker.command(usage="<#channel-to-unset>")
    @commands.has_permissions(manage_channels=True)
    async def unset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove a channel's ticker"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.delete_ticker(channel.id)
        await self.bot.reply(ctx, text=f"✅ Removed ticker from {channel.mention}")
        await self.update_cache()

    @commands.has_permissions(manage_channels=True)
    @ticker.command(usage="[#channel #ch2...] <search query or flashscore link>")
    async def add(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *,
                  query: commands.clean_content = None):
        """Add a league to a ticker for channel(s)"""
        if query is None:
            err = '🚫 You need to specify a query or a flashscore team link'
            return await self.bot.reply(ctx, text=err, ping=True)

        if "http" not in query:
            await self.bot.reply(ctx, text=f"Searching for {query}...", delete_after=5)
            res = await football.fs_search(ctx, query)
            if res is None:
                return
        else:
            if "flashscore" not in query:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', ping=True)

            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition.by_link(query, page)
            except IndexError:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', ping=True)
            finally:
                await page.close()

            if res is None:
                return await self.bot.reply(ctx, text=f"🚫 Failed to get league data from <{query}>.")

        res = f"{res.title}"

        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        await self.add_league(channel.id, res)
        await self.bot.reply(ctx, text=f"✅ **{res}** added to the tracked leagues for {channel.mention}")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    @ticker.group(name="remove", aliases=["del", "delete"], usage="[#channel, #channel2] <Country: League Name>",
                  invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def _remove(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *,
                      target: commands.clean_content = None):
        """Remove a competition from a channel's ticker"""
        # Verify we have a valid goal ticker channel target.
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        if target is not None:
            target = str(target).strip("'\"")  # Remove quotes, idiot proofing.
            leagues = [i for i in self.cache[(ctx.guild.id, channel.id)] if target.lower() in i.lower()]
        else:
            leagues = self.cache[(ctx.guild.id, channel.id)]

        if not leagues:
            return await self.bot.reply(ctx, f"{channel.mention} has no tracked leagues to remove.")

        # Verify which league the user wishes to remove.
        index = await embed_utils.page_selector(ctx, leagues)

        if index is None or index == -1:
            return  # rip.

        target = leagues[index]

        await self.remove_league(channel.id, target)

        await self.bot.reply(ctx, text=f"✅ **{target}** deleted from {channel.mention} tracked leagues ")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    @_remove.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def all(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove ALL competitions from a ticker"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        await self.remove_all_leagues(channel.id)
        await self.bot.reply(ctx, text=f"✅ {channel.mention} leagues cleared")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    @ticker.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def reset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Reset competitions for a ticker channel to the defaults."""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        await self.remove_all_leagues(channel.id)
        for i in DEFAULT_LEAGUES:
            await self.add_league(channel.id, i)

        await self.bot.reply(ctx, text=f"✅ {channel.mention} had it's tracked leagues reset to the defaults.")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    @ticker.command(usage="[#channel]", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def addwc(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """ Temporary command: Add the qualifying tournaments for the World Cup to a channel's ticker"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return

        for league in WORLD_CUP_LEAGUES:
            await self.add_league(channel.id, league)
        await self.bot.reply(ctx, text=f"Added Regional World Cup Qualifiers to ticker for {channel.mention}")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    # Common DB methods
    async def add_league(self, channel_id: int, league):
        """Insert a tracked league for a channel;s ticker into the database."""
        sql = """INSERT INTO ticker_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(sql, channel_id, league)
        await self.bot.db.release(connection)

    async def remove_league(self, channel_id: int, league):
        """Remove a tracked league for a channel's ticker from the database."""
        c = await self.bot.db.acquire()
        async with c.transaction():
            await c.execute("""DELETE FROM ticker_leagues WHERE (league, channel_id) = ($1,$2)""", league, channel_id)
        await self.bot.db.release(c)

    async def remove_all_leagues(self, channel_id: int):
        """Remove all tracked leagues for a channel from the database."""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM ticker_leagues WHERE channel_id = $1""", channel_id)
        await self.bot.db.release(connection)

    # Purge either guild or channel from DB.
    async def delete_ticker(self, id_number: int, guild: bool = False):
        """Delete all database entries for a channel's tracked events"""
        sql = f"""DELETE FROM ticker_channels WHERE {"guild_id" if guild else "channel_id"} = $1"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(sql, id_number)
        await self.bot.db.release(connection)

    async def upsert(self, column, cid, value: bool or None):
        """Insert or update ticker_settings db entry"""
        c = await self.bot.db.acquire()
        try:
            async with c.transaction():
                await c.execute(f"""INSERT INTO ticker_settings (channel_id, {column}) VALUES ($1, $2) 
                                ON CONFLICT (channel_id)
                                DO UPDATE SET {column} = $2 WHERE EXCLUDED.channel_id = $1""", cid, value)
        finally:
            await self.bot.db.release(c)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Handle deletion of channel data from database upon channel deletion."""
        await self.delete_ticker(channel.id)
        await self.update_cache()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete all data related to a guild from the database upon guild leave."""
        await self.delete_ticker(guild.id, guild=True)
        await self.update_cache()

    @ticker.command(usage="<channel_id>", hidden=True)
    @commands.is_owner()
    async def admin(self, ctx, channel_id: int):
        """Admin force delete a goal tracker."""
        await self.delete_ticker(channel_id)
        await self.bot.reply(ctx, text=f"✅ **{channel_id}** was deleted from the ticker_channels table")
        await self.update_cache()

    # Config commands
    @ticker.group(usage="<`off`, `on`, or `extened`>", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def goals(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle the output mode for goals in tracked leagues.

        Off: Do not send anything when a goal is scored
        On: Show an embed showing the latest goalscorer
        Extended: Show an embed detailing every event in the game so far when a goal is scored."""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @goals.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def goals_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn OFF messages for goals in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("goal", channel.id, False)
        await self.bot.reply(ctx, text=f"Disabled output of messages for goal events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @goals.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def goals_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on messages for goals in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("goal", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of messages for goal events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @goals.command(name="extended", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def goals_extended(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle on extended output for goals for tracked league: all fixture event will be displayed"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("goal", channel.id, True)
        await self.bot.reply(ctx, text=f"Enabled output of extended messages for goal events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Kick off commands
    @ticker.group(usage="<`off` or `on`>", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def kickoff(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle the output mode for kickoff events in tracked leagues.

        Off: Do not send anything when a game kicks off
        On: Show an embed when a game kicks off"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @kickoff.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ko_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off messages for kick off events for tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("kick_off", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of messages for kick off events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @kickoff.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ko_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on messages for kick off events in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("kick_off", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of messages for kick off events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Half Time commands
    @ticker.group(usage="<`off`, `on`, or `extened`>", aliases=["ht"], invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def halftime(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle the output mode for half time events from tracked leagues.

        Off: Do not send anything at half time
        On: Show a short embed at half time
        Extended: Show an embed detailing every event in the game so far at Half Time"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @halftime.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ht_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of half time messages for tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("half_time", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of messages for half time events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @halftime.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ht_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of short embeds for half time events in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("half_time", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of messages for half time events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @halftime.command(name="extended", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ht_extended(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on extended messages for half time events for tracked leagues: All fixture events will be displayed"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("half_time", channel.id, True)
        await self.bot.reply(ctx, text=f"Enabled output of extended messages for half time events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Second Half commands
    @ticker.group(usage="<`off`, `on`, or `extened`>", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def sechalf(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for second half kickoff events from tracked leagues.

        Off: Do not send anything at the start of the second half
        On: Show a short embed at the start of the second half
        Extended: Show an embed detailing every event in the game so far at the start of the second half"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @sechalf.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def sec_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of second half kickoff messages for tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("second_half_begin", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of second half kickoff messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @sechalf.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def sec_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of short second half kickoff messages for tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("second_half_begin", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of second half kickoff messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @sechalf.command(name="extended", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def sec_extended(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on extended messages for second half kickoffs: All fixture events will be displayed"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("second_half_begin", channel.id, True)
        await self.bot.reply(ctx, text=f"Enabled output of extended second half kickoff messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Red Card commands
    @ticker.group(usage="<`off`, `on`, or `extened`>", invoke_without_command=True, aliases=["rc"])
    @commands.has_permissions(manage_channels=True)
    async def redcard(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle the output mode for red card events from tracked leagues.

        Off: Do not send anything when a player is given a red card
        On: Show a short embed when a player is given a red card
        Extended: Show an embed detailing every event in the game so far when a red card is given"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @redcard.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def rc_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of red card messages for tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("red_card", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of red card messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @redcard.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def rc_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of red card messages for tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("red_card", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of red_card messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @redcard.command(name="extended", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def rc_extended(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on extended messages for red cards: All fixture events will be displayed"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("red_card", channel.id, True)
        await self.bot.reply(ctx, text=f"Enabled output of extended red card messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Result Only commands
    @ticker.group(usage="<`off`, `on`, or `extened`>", invoke_without_command=True, aliases=['rx', 'fro'])
    @commands.has_permissions(manage_channels=True)
    async def results(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for final result only matches for tracked leagues.

        Sometimes data is only available at the end of a match.

        Off: Do not send anything when the final result to a match is found.
        On: Send a short embed with the final result of matches when found.
        Extended: Show an extended embed detailing every event in the game when the result is found."""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @results.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def rx_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of embeds for final result only games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("final_result_only", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of final result only match embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @results.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def rx_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of embeds for final result only games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("final_result_only", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of final result only match embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @results.command(name="extended", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def rx_extended(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on extended embeds for final result only games in tracked leagues.
        All fixture events will be displayed"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("final_result_only", channel.id, True)
        await self.bot.reply(ctx, text=f"Enabled extended output for result only match embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Full Time Commands
    @ticker.group(usage="<`off`, `on`, or `extened`>", invoke_without_command=True, aliases=['ft'])
    @commands.has_permissions(manage_channels=True)
    async def fulltime(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for full time results for matches in tracked leagues.

        Off: Do not send anything at full time.
        On: Send a short final score embed at full time.
        Extended: Show an extended embed detailing every event in the game at full time."""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @fulltime.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ft_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of embeds at full time for games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("full_time", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of full time embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @fulltime.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ft_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of embeds at full time for games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("full_time", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of full time embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @fulltime.command(name="extended", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def ft_extended(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on extended embeds at full time for games in tracked leagues. All fixture events will be displayed"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("full_time", channel.id, True)
        await self.bot.reply(ctx, text=f"Enabled extended embeds for full time results to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Delayed/cancelled/postponed/resumed
    @ticker.group(usage="<`off` or `on`>", invoke_without_command=True, aliases=['cancelled'])
    @commands.has_permissions(manage_channels=True)
    async def delays(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for delays and cancellations of matches in tracked leagues.

        Off: Do not send anything if a game is delayed, interrupted, cancelled, or resumed.
        On: Send an embed if a game is delayed, interrupted, cancelled, or resumed."""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @delays.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def delay_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of embeds for delayed, interrupted, cancelled, or resumed games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("delayed", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of delay or cancellation embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @delays.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def delay_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of embeds for delayed, interrupted, cancelled, or resumed games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("delayed", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of delay or cancellation embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # VAR Reviews
    @ticker.group(usage="<`off` or `on`>", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def var(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for VAR Reviews in tracked leagues.

        Off: Do not send anything if an event is overruled.
        On: Send an embed if a game game event is overruled"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @var.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def var_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of embeds for VAR Reviews in games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("var", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of VAR Reviews to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @var.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def var_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of embeds for VAR Reviews in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("var", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of VAR Reviews to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Extra Time
    @ticker.group(usage="<`off` or `on`>", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def et(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for Extra Time in tracked leagues.

        Off: Do not send anything if a game goes to extra time
        On: Send an embed if a game goes to extra time"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @et.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def et_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of embeds for Extra Time in games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("extra_time", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of extra time embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @et.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def et_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of embeds for Extra Time in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("extra_time", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of extra time embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Penalties
    @ticker.group(usage="<`off` or `on`>", invoke_without_command=True, aliases=["pens"])
    @commands.has_permissions(manage_channels=True)
    async def penalties(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Toggle output for penalties in tracked leagues.

        Off: Do not send anything if an event is overruled.
        On: Send an embed if a game game event is overruled"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.send_settings(ctx, channel)

    @penalties.command(name="off", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def pens_off(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn off output of embeds for penalty shootouts in games in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("penalties", channel.id, None)
        await self.bot.reply(ctx, text=f"Disabled output of penalty embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    @penalties.command(name="on", hidden=True)
    @commands.has_permissions(manage_channels=True)
    async def pens_on(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Turn on output of embeds for penalty shootouts in tracked leagues"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        await self.upsert("penalties", channel.id, False)
        await self.bot.reply(ctx, text=f"Enabled output of  penalty embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)


def setup(bot):
    """Load the goal tracker cog into the bot."""
    bot.add_cog(Ticker(bot))
