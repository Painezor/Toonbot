"""Handler Cog for dispatched Fixture events, and database handling for channels using it."""
import asyncio
import typing
from collections import defaultdict
from importlib import reload

import discord
from asyncpg import UniqueViolationError, Record
from discord.ext import commands

from ext.utils import football, embed_utils

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


def fallback(retry):
    """Handle fallback for automatic retrying of refreshing if data is not present"""
    return 60 * retry if retry in range(5) else False


def check_mode(mode):
    """Get appropriate DB Setting for ticker event"""
    if mode in ["var_red_card", "var_goal"]:
        mode = "var"

    elif mode in ["resumed", "interrupted", "postponed", "abandoned", "cancelled"]:
        mode = "delayed"

    elif mode in ["extra_time_begins", "end_of_normal_time", "end_of_extra_time", "ht_et_begin", "ht_et_end"]:
        mode = "extra_time"

    elif mode == "score_after_extra_time":
        mode = "full_time"

    elif mode in ["penalties_begin", "penalty_results"]:
        mode = "penalties"

    return mode


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    def __init__(self, bot, fixture, mode, channels: typing.List[Record], home=False):
        self.bot = bot
        self.fixture = fixture
        self.mode = mode
        self.channels = channels
        self.home = home

        # dynamic properties
        self.retry = 0
        self.messages = []
        self.needs_refresh = True

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
        if "ht_et" in self.mode:
            temp_mode = "Half Time" if self.mode == "ht_et_begin" else "Second Half Begins"
            m = f"Extra Time: {temp_mode}"

        if self.mode in ["goal", "var_goal", "red_card", "var_red_card"]:
            h, a = ('**', '') if self.home else ('', '**')  # Bold Home or Away Team Name.
            h, a = ('**', '**') if self.home is None else h, a
            home = f"{h}{self.fixture.home} {self.fixture.score_home}{h}"
            away = f"{a}{self.fixture.score_away} {self.fixture.away}{a}"
            e.description = f"**{m}** | [{home} - {away}]({self.fixture.url})\n"
        elif self.mode in ["penalties_begin", "penalty_results"]:
            try:
                h, a = ("**", "") if self.fixture.penalties_home > self.fixture.penalties_away else ("", "**")
                home = f"{h}{self.fixture.home} {self.fixture.penalties_home}{h}"
                away = f"{a}{self.fixture.penalties_away} {self.fixture.away}{a}"

                e.description = f"**Penalties** | [{home} - {away}]({self.fixture.url})"
            except TypeError:  # If penalties_home / penalties_away are Nonetype
                e.description = f"**Penalties** | [{self.fixture.bold_score}]({self.fixture.url})\n"

            events = [i for i in self.fixture.events if isinstance(i, football.Penalty) and i.shootout is True]

            # iterate through everything after penalty header
            home = [str(i) for i in events if i.team == self.fixture.home]
            away = [str(i) for i in events if i.team == self.fixture.away]

            self.retry = 1 if self.fixture.state != "fin" else self.retry

            if home:
                e.add_field(name=self.fixture.home, value="\n".join(home))
            if away:
                e.add_field(name=self.fixture.away, value="\n".join(away))

        else:
            e.description = f"**{m}** | [{self.fixture.bold_score}]({self.fixture.url})\n"

        footer = self.fixture.event_footer

        if "end_of_period" in self.mode:
            e.colour = discord.Colour.greyple()

        else:
            try:
                e.colour = edict[self.mode]
            except Exception as err:
                print(f"Ticker: Edict error for mode {self.mode}", err)

        if self.event is not None:
            e.description += str(self.event)
            if hasattr(self.event, "full_description"):
                e.description += f"\n\n{self.event.full_description}"

        if self.fixture.infobox is not None:
            if "leg." in self.fixture.infobox:
                footer += f" ({self.fixture.infobox}) "
                e.set_footer(text=footer)

            else:
                e.description += f"```{self.fixture.infobox}```"

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
    def fallback(self):
        """Handle fallback for automatic retrying of refreshing if data is not present"""
        return 60 * self.retry if self.retry in range(5) else False

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

    @property
    def db_mode(self):
        """Get appropriate DB Setting for ticker event"""
        if self.mode in ["var_red_card", "var_goal", "red_card_overturned", "goal_overturned"]:
            return "var"
        elif self.mode in ["resumed", "interrupted", "postponed", "abandoned", "cancelled"]:
            return "delayed"
        elif self.mode in ["extra_time_begins", "end_of_normal_time", "ht_et_begin", "ht_et_end", "end_of_extra_time"]:
            return "extra_time"
        elif self.mode in ["score_after_extra_time", "full_time"]:
            return "full_time"
        elif self.mode in ["penalties_begin", "penalty_results"]:
            return "penalties"
        elif "start_of_period" in self.mode:
            return "Half_time"
        else:
            return self.mode

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
        full_embed = await self.full_embed
        short_embed = await self.embed

        for r in self.channels:
            channel = self.bot.get_channel(r['channel_id'])

            if r[self.db_mode] is None:  # Default Off Options.
                if self.mode in ("kick_off", "half_time", "second_half_begin", "delayed"):
                    continue

            elif self.mode == "ht_et_begin":  # Special Check - Must pass both
                if r["half_time"] == "off" or r["half_time"] is None:
                    continue

            elif self.mode == "ht_et_end":  # Special Check - Must pass both
                if r["second_half_begin"] == "off" or r["second_half_begin"] is None:
                    continue

            elif r[self.db_mode] == "off":
                continue  # If output is disabled for this channel skip output entirely.

            if self.db_mode == "extended":
                embed = full_embed

            else:
                embed = short_embed

            try:
                self.messages.append(await channel.send(embed=embed))
            except discord.HTTPException as err:
                print(err)
                continue

    async def bulk_edit(self):
        """Edit existing messages"""
        for message in self.messages:
            settings = [i for i in self.channels if i['channel_id'] == message.channel.id][-1]

            if settings[self.db_mode] in [None, "off"]:  # Default Off Options.
                if self.mode in ("kick_off", "half_time", "second_half_begin", "delayed"):
                    continue

            elif self.mode == "ht_et_begin":  # Special Check - Must pass both
                if settings["half_time"] == "off" or settings["half_time"] is None:
                    continue

            elif self.mode == "ht_et_end":  # Special Check - Must pass both
                if settings["second_half_begin"] == "off" or settings["second_half_begin"] is None:
                    continue

            if self.db_mode == "extended":
                embed = await self.full_embed

            else:
                embed = await self.embed

            try:
                await message.edit(embed=embed)
            except discord.HTTPException:
                continue

    async def event_loop(self):
        """The Fixture event's internal loop"""
        # Handle full time only events.
        if self.mode == "kick_off":
            e = await self.embed
            e.description = f"**Kick Off** [{self.fixture.bold_score}]({self.fixture.url})"
            e.colour = discord.Colour.lighter_gray()
            await self.send_messages()
            return

        while self.needs_refresh:
            timer = self.fallback
            if timer is False:
                return

            await asyncio.sleep(timer)

            page = await self.bot.browser.newPage()
            async with max_pages:
                try:
                    await self.fixture.refresh(page)
                finally:  # ALWAYS close the browser after refreshing to avoid Memory leak
                    await page.close()

            self.retry += 1

            # Figure out which event we're supposed to be using (Either newest event, or Stored if refresh)
            if self.event_index is None:
                if not self.fixture.events:
                    self.event = None
                else:
                    ve = self.valid_events
                    if ve is not None:
                        try:
                            events = [i for i in self.fixture.events if isinstance(i, ve)]
                            target_team = self.fixture.home if self.home else self.fixture.away
                            event = [i for i in events if i.team == target_team][-1]
                            self.event_index = self.fixture.events.index(event)
                            self.event = event
                            self.needs_refresh = False if all([i.player for i in self.fixture.events]) else True
                        except IndexError:
                            self.event = None
                            self.event_index = None

            else:
                try:
                    self.event = self.fixture.events[self.event_index]
                    assert isinstance(self.event, self.valid_events)
                    self.needs_refresh = False if all([i.player for i in self.fixture.events]) else True
                except (AssertionError, IndexError):
                    return await self.retract_event()

            if not self.messages:
                await self.send_messages()
            else:
                await self.bulk_edit()


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "⚽"
        self.cache = defaultdict(set)
        self.settings = defaultdict(set)
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
        self.cache.clear()

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

            self.cache[(r["guild_id"], r["channel_id"])].add(r["league"])

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""
            SELECT guild_id, ticker_channels.channel_id, goal, red_card,  kick_off, half_time, second_half_begin,
            full_time, final_result_only, delayed, var, extra_time, penalties
            FROM ticker_channels LEFT OUTER JOIN ticker_settings
            ON ticker_channels.channel_id = ticker_settings.channel_id""")
        await self.bot.db.release(connection)

        self.settings = records

    async def warn_missing_perms(self, ctx):
        """Aggressively tell users they've fucked up their permissions for their tickers."""
        bad_guild_channels = [self.bot.get_channel(i[1]) for i in self.warn_once if ctx.guild.id == i[0]]
        deleted = len([i for i in bad_guild_channels if i is None])
        not_deleted = [i for i in bad_guild_channels if i is not None]

        if deleted > 0:
            await self.bot.reply(ctx, f"{deleted} of your ticker channel(s) appear to be deleted.")

        no_send_perms = [i.mention for i in not_deleted if not i.permissions_for(ctx.me).send_messages]
        if no_send_perms:
            await self.bot.reply(ctx, f"WARNING: I do not have send_messages permissions in {''.join(no_send_perms)}\n"
                                      f"**Ticker Events will not be output**")

        no_embed_perms = [i.mention for i in not_deleted if not i.permissions_for(ctx.me).embed_links]
        if no_embed_perms:
            await self.bot.reply(ctx, f"WARNING: I do not have embed_links permissions in {''.join(no_send_perms)}\n"
                                      f"**Ticker Events will not be output**")

    @property
    async def base_embed(self):
        """Generic Discord Embed for Ticker Configuration"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Toonbot Ticker config"
        e.set_thumbnail(url=self.bot.user.avatar.url)
        return e

    async def send_leagues(self, ctx, channel):
        """Sends embed detailing the tracked leagues for a channel."""
        e = await self.base_embed
        header = f'Tracked leagues for {channel.mention}'
        # Warn if they fuck up permissions.
        if not channel.permissions_for(ctx.me).send_messages:
            header += f"```css\n[WARNING]: I do not have send_messages permissions in {channel.mention}!"
        if not channel.permissions_for(ctx.me).embed_links:
            header += f"```css\n[WARNING]: I do not have embed_links permissions in {channel.mention}!"
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
        await self.warn_missing_perms(ctx)

    async def send_settings(self, ctx, channel):
        """Send embed detailing your ticker settings for a channel."""
        e = await self.base_embed
        header = f"Tracked events for {channel.mention}"
        # Warn if they fuck up permissions.
        if not channel.permissions_for(ctx.me).send_messages:
            header += f"```css\n[WARNING]: I do not have send_messages permissions in {channel.mention}!"
        if not channel.permissions_for(ctx.me).embed_links:
            header += f"```css\n[WARNING]: I do not have embed_links permissions in {channel.mention}!"

        channel_settings = [i for i in self.settings if i['channel_id'] == channel.id][0]

        pos = "default (on)"
        neg = "default (off)"

        goal = channel_settings['goal'] if channel_settings['goal'] is not None else pos
        red_card = channel_settings['red_card'] if channel_settings['red_card'] is not None else pos
        kick_off = channel_settings['kick_off'] if channel_settings['kick_off'] is not None else neg
        half_time = channel_settings['half_time'] if channel_settings['half_time'] is not None else neg
        sec = channel_settings['second_half_begin'] if channel_settings['second_half_begin'] is not None else neg
        full_time = channel_settings['full_time'] if channel_settings['full_time'] is not None else pos
        fro = channel_settings['final_result_only'] if channel_settings['final_result_only'] is not None else pos
        delayed = channel_settings['delayed'] if channel_settings['delayed'] is not None else neg
        var = channel_settings['var'] if channel_settings['var'] is not None else neg
        extra_time = channel_settings['extra_time'] if channel_settings['extra_time'] is not None else pos
        penalties = channel_settings['penalties'] if channel_settings['penalties'] is not None else pos

        settings = f"Goal: {goal}\n"
        settings += f"Red Card: {red_card}\n"
        settings += f"Kick Off: {kick_off}\n"
        settings += f"Half Time: {half_time}\n"
        settings += f"Second Half Start: {sec}\n"
        settings += f"Full Time: {full_time}\n"
        settings += f"Final Result Only: {fro}\n"
        settings += f"Delayed Games: {delayed}\n"
        settings += f"VAR: {var}\n"
        settings += f"Extra Time: {extra_time}\n"
        settings += f"Penalties: {penalties}\n"

        e.description = header + f"```yaml\n{settings}```"
        await self.bot.reply(ctx, embed=e)

    @commands.Cog.listener()
    async def on_fixture_event(self, mode, f: football.Fixture, home=True):
        """Event handler for when something occurs during a fixture."""
        # Perform an initial Refresh of the fixture
        channels = [i[1] for i in self.cache if f.full_league in self.cache[i]]  # List oF IDs we want settings for
        channels = [i for i in self.settings if i['channel_id'] in channels]  # Settings for those IDs
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
        await self.warn_missing_perms(ctx)

    @ticker.command(usage="[#channel-Name]", aliases=["create", "make"])
    @commands.has_permissions(manage_channels=True)
    async def set(self, ctx, ch: discord.TextChannel = None):
        """Add a ticker to one of your server's channels."""
        if ch is None:
            ch = ctx.channel

        try:
            await self.create_channel(ch)
        except UniqueViolationError:
            return await self.bot.reply(ctx, text='That channel already has a ticker!')

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

        await self.delete_channel(channel.id)
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

        target = str(target).strip("'\"")  # Remove quotes, idiot proofing.
        if target is not None:
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

    async def create_channel(self, ch: discord.TextChannel):
        """Create a database entry for a channel to track match events"""
        gid = ch.guild.id
        c = await self.bot.db.acquire()
        try:
            async with c.transaction():
                await c.execute("""INSERT INTO ticker_channels (guild_id, channel_id) VALUES ($1, $2)""", gid, ch.id)
        except UniqueViolationError:
            raise UniqueViolationError
        finally:
            await self.bot.db.release(c)

    # Purge either guild or channel from DB.
    async def delete_channel(self, id_number: int, guild: bool = False):
        """Delete all database entries for a channel's tracked events"""
        if guild:
            sql = """DELETE FROM ticker_channels WHERE guild_id = $1"""
        else:
            sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(sql, id_number)
        await self.bot.db.release(connection)

    async def settings_upsert(self, column, cid, value):
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
        await self.delete_channel(channel.id)
        await self.update_cache()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete all data related to a guild from the database upon guild leave."""
        await self.delete_channel(guild.id, guild=True)
        await self.update_cache()

    @ticker.command(usage="<channel_id>", hidden=True)
    @commands.is_owner()
    async def admin(self, ctx, channel_id: int):
        """Admin force delete a goal tracker."""
        await self.delete_channel(channel_id)
        await self.bot.reply(ctx, text=f"✅ **{channel_id}** was deleted from the ticker_channels table")
        await self.update_cache()

    # Config commands
    @ticker.group(usage="<'off', 'on', or 'extended'>", invoke_without_command=True)
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

        await self.settings_upsert("goal", channel.id, "off")
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

        await self.settings_upsert("goal", channel.id, "on")
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

        await self.settings_upsert("goal", channel.id, "extended")
        await self.bot.reply(ctx, text=f"Enabled output of extended messages for goal events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Kick off commands
    @ticker.group(usage="<'off' or 'on'>", invoke_without_command=True)
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

        await self.settings_upsert("kick_off", channel.id, "off")
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

        await self.settings_upsert("kick_off", channel.id, "on")
        await self.bot.reply(ctx, text=f"Enabled output of messages for kick off events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Half Time commands
    @ticker.group(usage="<'off', 'on', or 'extended'>", aliases=["ht"], invoke_without_command=True)
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

        await self.settings_upsert("half_time", channel.id, "off")
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

        await self.settings_upsert("half_time", channel.id, "on")
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

        await self.settings_upsert("half_time", channel.id, "extended")
        await self.bot.reply(ctx, text=f"Enabled output of extended messages for half time events to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Second Half commands
    @ticker.group(usage="<'off', 'on', or 'extended'>", invoke_without_command=True)
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

        await self.settings_upsert("second_half_begin", channel.id, "off")
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

        await self.settings_upsert("second_half_begin", channel.id, "on")
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

        await self.settings_upsert("second_half_begin", channel.id, "extended")
        await self.bot.reply(ctx, text=f"Enabled output of extended second half kickoff messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Red Card commands
    @ticker.group(usage="<'off', 'on', or 'extended'>", invoke_without_command=True, aliases=["rc"])
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

        await self.settings_upsert("red_card", channel.id, "off")
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

        await self.settings_upsert("red_card", channel.id, "on")
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

        await self.settings_upsert("red_card", channel.id, "extended")
        await self.bot.reply(ctx, text=f"Enabled output of extended red card messages to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Result Only commands
    @ticker.group(usage="<'off', 'on', or 'extended'>", invoke_without_command=True, aliases=['rx', 'fro'])
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

        await self.settings_upsert("final_result_only", channel.id, "off")
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

        await self.settings_upsert("final_result_only", channel.id, "on")
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

        await self.settings_upsert("final_result_only", channel.id, "extended")
        await self.bot.reply(ctx, text=f"Enabled extended output for result only match embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Full Time Commands
    @ticker.group(usage="<'off', 'on', or 'extended'>", invoke_without_command=True, aliases=['ft'])
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

        await self.settings_upsert("full_time", channel.id, "off")
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

        await self.settings_upsert("full_time", channel.id, "on")
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

        await self.settings_upsert("full_time", channel.id, "extended")
        await self.bot.reply(ctx, text=f"Enabled extended embeds for full time results to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Delayed/cancelled/postponed/resumed
    @ticker.group(usage="<'off' or 'on'>", invoke_without_command=True, aliases=['cancelled'])
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

        await self.settings_upsert("delayed", channel.id, "off")
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

        await self.settings_upsert("delayed", channel.id, "on")
        await self.bot.reply(ctx, text=f"Enabled output of delay or cancellation embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # VAR Reviews
    @ticker.group(usage="<'off' or 'on'>", invoke_without_command=True)
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

        await self.settings_upsert("var", channel.id, "off")
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

        await self.settings_upsert("var", channel.id, "on")
        await self.bot.reply(ctx, text=f"Enabled output of VAR Reviews to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Extra Time
    @ticker.group(usage="<'off' or 'on'>", invoke_without_command=True)
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

        await self.settings_upsert("extra_time", channel.id, "off")
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

        await self.settings_upsert("extra_time", channel.id, "on")
        await self.bot.reply(ctx, text=f"Enabled output of extra time embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)

    # Penalties
    @ticker.group(usage="<'off' or 'on'>", invoke_without_command=True, aliases=["pens"])
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

        await self.settings_upsert("penalties", channel.id, "off")
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

        await self.settings_upsert("penalties", channel.id, "on")
        await self.bot.reply(ctx, text=f"Enabled output of  penalty embeds to {channel.mention}")
        await self.update_cache()
        await self.send_settings(ctx, channel)


def setup(bot):
    """Load the goal tracker cog into the bot."""
    bot.add_cog(Ticker(bot))
