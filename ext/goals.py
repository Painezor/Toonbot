from collections import defaultdict
from importlib import reload

import discord
from asyncpg import UniqueViolationError
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


class Goals(commands.Cog):
    """Get updates whenever goals are scored"""

    def __init__(self, bot):
        self.bot = bot
        self.cache = defaultdict(set)
        self.bot.loop.create_task(self.update_cache())
        reload(football)

    async def update_cache(self):
        # Grab most recent data.
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""
            SELECT guild_id, goals_channels.channel_id, league
            FROM goals_channels LEFT OUTER JOIN goals_leagues
            ON goals_channels.channel_id = goals_leagues.channel_id""")
        await self.bot.db.release(connection)
    
        # Clear out our cache.
        self.cache.clear()
        warn_once = []
    
        # Repopulate.
        for r in records:
            if r['channel_id'] in warn_once:
                continue
        
            if self.bot.get_channel(r['channel_id']) is None:
                print(f"GOALS potentially deleted channel: {r['channel_id']}")
                warn_once.append(r['channel_id'])
                continue
        
            self.cache[(r["guild_id"], r["channel_id"])].add(r["league"])

    @property
    async def base_embed(self):
        e = discord.Embed()
        e.colour = discord.Colour.dark_teal()
        e.title = "Toonbot Goal Ticker config"
        e.set_thumbnail(url=self.bot.user.avatar_url)
        return e

    async def send_leagues(self, ctx, channel):
        e = await self.base_embed
        header = f'Tracked leagues for {channel.mention}'
        # Warn if they fuck up permissions.
        if not ctx.me.permissions_in(channel).send_messages:
            header += "```css\n[WARNING]: I do not have send_messages permissions in that channel!"
        if not ctx.me.permissions_in(channel).embed_links:
            header += "```css\n[WARNING]: I do not have embed_links permissions in that channel!"
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

    async def update_channels(self, fixture, embed):
        cache_cache = self.cache.copy()
        for (guild_id, channel_id) in cache_cache:
            if fixture.full_league in cache_cache[(guild_id, channel_id)]:
                channel = self.bot.get_channel(channel_id)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    continue
                
    @commands.Cog.listener()
    async def on_fixture_event(self, mode, f: football.Fixture, home=True):
        page = await self.bot.browser.newPage()
        try:
            await f.refresh(page)
        except Exception as err:
            raise err
        finally:  # ALWAYS close the browser after refreshing to avoid Memory leak
            await page.close()

        e = await f.base_embed
        e.title = None
        e.remove_author()
        e.set_footer(text=f"{f.country}: {f.league} | {f.time}")
 
        link = f.url if hasattr(f, "url") else ""
        
        # Handle Penalty Shootout Results:
        if f.penalties_home is not None:
            events = [i for i in f.events if hasattr(i, "type") and i.type in ['PSO: Scored', 'PSO: Missed']]
            
            hb, ab = ("**", "") if f.penalties_home > f.penalties_away else ("", "**")
            d = f"**PSO**: [{hb}{f.home} {f.penalties_home}{hb} - {ab}{f.penalties_away} {f.away}{ab}]({link})"
            
            e.description = d
            
            # iterate through everything after penalty header
            h_val = [f"`{'⚽' if i.type == 'PSO: Scored' else '⛔'}` {i.player}" for i in events if i.team == f.home]
            a_val = [f"`{'⚽' if i.type == 'PSO: Scored' else '⛔'}` {i.player}" for i in events if i.team == f.away]

            if h_val:
                e.add_field(name=f.home, value="\n".join(h_val))
            if a_val:
                e.add_field(name=f.away, value="\n".join(a_val))
            
            dev_channel = self.bot.get_channel(250252535699341312)
            await dev_channel.send("DEBUG: Penalty shootout result embed", embed=e)
            
            return await self.update_channels(f, e)
        
        # Handle full time only events.
        if mode == "FULL TIME":
            if f.score_home == f.score_away:
                hb, ab = "", ""
            else:
                hb, ab = ('**', '') if f.score_home > f.score_away else ('', '**')
            
            e.description = f"**FT**: [{hb}{f.home} {f.score_home}{hb} - {ab}{f.score_away} {f.away}{ab}]({link})"
            return await self.update_channels(f, e)
    
        if home is None:
            hb, ab = ('**', '**')
        else:
            hb, ab = ('**', '') if home else ('', '**')  # Bold Home or Away Team Name.
        
        edict = {
            "GOAL": {"colour":discord.Colour.dark_green(), "icon": '⚽', "events": ["Goal", "Own Goal"]},
            "RED CARD": {"colour": discord.Colour.red(), "icon": "🟥", "events": ['Dismissal, "Second Yellow']},
            "VAR": {"colour": discord.Colour.blurple(), "icon": "📹", "events": ["VAR"]}
        }
        
        # Embed header row.
        e.description = f"**{mode}**: [{hb}{f.home} {f.score_home}{hb} - {ab}{f.score_away} {f.away}{ab}]({f.url})\n"

        try:
            event = [i for i in f.events if hasattr(i, "type") and i.type in edict[mode]["events"]][-1]
            player = event.player if hasattr(event, "player") else ""
            e.description += f"`{edict[mode]['icon']} {event.time}:` {player}"
            e.colour = edict[mode]["colour"]
            e.description += event.note.replace("Penalty", "(pen.)") if hasattr (event, "note") else ""
            e.description += f"\n\n{event.full_description}" if hasattr(event, "full_description") else ""
        except IndexError:
            pass
        
        await self.update_channels(f, e)

    async def _pick_channels(self, ctx, channels):
        # Assure guild has goal ticker channel.
        channels = [channels] if isinstance(channels, discord.TextChannel) else channels
        
        if ctx.guild.id not in [i[0] for i in self.cache]:
            await self.bot.reply(ctx, text=f'{ctx.guild.name} does not have any goal tickers.', mention_author=True)
            channels = []
        
        if channels:
            # Verify selected channels are actually in the database.
            checked = []
            for i in channels:
                if i.id not in [c[1] for c in self.cache]:
                    await self.bot.reply(ctx, text=f"{i.mention} does not have any goal tickers.", mention_author=True)
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
    
    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def goals(self, ctx, *,  channels: commands.Greedy[discord.TextChannel] = None):
        """View the status of your goal tickers."""
        channel = await self._pick_channels(ctx, channels)

        if not channel:
            return  # rip

        await self.send_leagues(ctx, channel)

    @goals.command(usage="[#channel-Name]", aliases=["create"])
    @commands.has_permissions(manage_channels=True)
    async def set(self, ctx, ch: discord.TextChannel = None):
        """Add a goal ticker to one of your server's channels."""
        if ch is None:
            ch = ctx.channel
        
        try:
            await self.create_channel(ch)
        except UniqueViolationError:
            return await self.bot.reply(ctx, text='That channel already has a goal ticker!')
        
        for i in DEFAULT_LEAGUES:
            await self.add_league(ch.id, i)
        
        await self.bot.reply(ctx, text=f"A goal ticker was successfully added to {ch.mention}")
        await self.update_cache()
        await self.send_leagues(ctx, ch)

    @goals.command(usage="<#channel-to-unset>")
    @commands.has_permissions(manage_channels=True)
    async def unset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove a channel's goal ticker"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return
    
        await self.delete_channel(channel.id)
        await self.bot.reply(ctx, text=f"✅ Removed goal ticker from {channel.mention}")
        await self.update_cache()
    
    @commands.has_permissions(manage_channels=True)
    @goals.command(usage="[#channel #channel2] <search query or flashscore link>")
    async def add(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *, query: commands.clean_content):
        """Add a league to a goal ticker for a channel"""
        if "http" not in query:
            await self.bot.reply(ctx, text=f"Searching for {query}...", delete_after=5)
            res = await football.fs_search(ctx, query)
            if res is None:
                return
        else:
            if "flashscore" not in query:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', mention_author=True)
            
            page = await self.bot.browser.newPage()
            try:
                res = await football.Competition().by_link(query, page)
            except IndexError:
                return await self.bot.reply(ctx, text='🚫 Invalid link provided', mention_author=True)
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
    
    @goals.group(name="remove", aliases=["del", "delete"], usage="[#channel, #channel2] <Country: League Name>",
                 invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def _remove(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *,
                      target: commands.clean_content):
        """Remove a competition from a channel's goal ticker"""
        # Verify we have a valid goal ticker channel target.
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        target = target.strip("'\"")  # Remove quotes, idiot proofing.
        leagues = [i for i in self.cache[(ctx.guild.id, channel.id)] if target.lower() in i.lower()]

        # Verify which league the user wishes to remove.
        index = await embed_utils.page_selector(ctx, leagues)
        if index is None:
            return  # rip.

        target = leagues[index]

        await self.remove_league(channel.id, target)
        
        await self.bot.reply(ctx, text=f"✅ **{target}** deleted from {channel.mention} tracked leagues ")
        await self.update_cache()
        await self.send_leagues(ctx, channel)
    
    @_remove.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def all(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove ALL competitions from a goal ticker"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        await self.remove_all_leagues(channel.id)

        await self.bot.reply(ctx, text=f"✅ {channel.mention} leagues cleared")
        await self.update_cache()
        await self.send_leagues(ctx, channel)
    
    @goals.command(usage="[#channel-name]")
    @commands.has_permissions(manage_channels=True)
    async def reset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Reset competitions for a goal ticker channel to the defaults."""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip
        
        await self.remove_all_leagues(channel.id)
        for i in DEFAULT_LEAGUES:
            await self.add_league(channel.id, i)
            
        await self.bot.reply(ctx, text=f"✅ {channel.mention} had it's tracked leagues reset to the defaults.")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    @goals.command(usage="[#channel]")
    @commands.has_permissions(manage_channels=True)
    async def addwc(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """ Temporary command: Add the qualifying tournaments for the World Cup to a livescore channel  """
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return
    
        for league in WORLD_CUP_LEAGUES:
            await self.add_league(channel.id, league)
        await self.bot.reply(ctx, text=f"Added Regional World Cup Qualifiers to tracker for {channel.mention}")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    # Common DB methods
    async def add_league(self, channel_id: int, league):
        sql = """INSERT INTO goals_leagues (channel_id, league) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(sql, channel_id, league)
        await self.bot.db.release(connection)

    async def remove_league(self, channel_id: int, league):
        c = await self.bot.db.acquire()
        async with c.transaction():
            await c.execute("""DELETE FROM goals_leagues WHERE (league,channel_id) = ($1,$2)""", league, channel_id)
        await self.bot.db.release(c)

    async def remove_all_leagues(self, channel_id: int):
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM goals_leagues WHERE channel_id = $1""", channel_id)
        await self.bot.db.release(connection)
    
    async def create_channel(self, ch: discord.TextChannel):
        gid = ch.guild.id
        c = await self.bot.db.acquire()
        try:
            async with c.transaction():
                await c.execute("""INSERT INTO goals_channels (guild_id, channel_id) VALUES ($1, $2)""", gid, ch.id)
        except UniqueViolationError:
            raise UniqueViolationError
        finally:
            await self.bot.db.release(c)

    # Purge either guild or channel from DB.
    async def delete_channel(self, id_number: int, guild: bool = False):
        if guild:
            sql = """DELETE FROM goals_channels WHERE guild_id = $1"""
        else:
            sql = """DELETE FROM goals_channels WHERE channel_id = $1"""
    
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(sql, id_number)
        await self.bot.db.release(connection)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.delete_channel(channel.id)
        await self.update_cache()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.delete_channel(guild.id, guild=True)
        await self.update_cache()

    @goals.command(usage="<channel_id>")
    @commands.is_owner()
    async def admin(self, ctx, channel_id: int):
        """Admin force delete a goal tracker."""
        await self.delete_channel(channel_id)
        await self.bot.reply(ctx, text=f"✅ **{channel_id}** was deleted from the goals_channels table")
        await self.update_cache()


def setup(bot):
    bot.add_cog(Goals(bot))
