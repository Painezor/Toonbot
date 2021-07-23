"""Automated fetching of latest football transfer information from transfermarkt"""
import typing
from collections import defaultdict
from importlib import reload

import discord
from asyncpg import UniqueViolationError
from discord.ext import commands, tasks
from lxml import html

from ext.utils import transfer_tools, embed_utils

LG = [(":england: Premier League", "https://www.transfermarkt.co.uk/premier-league/startseite/wettbewerb/GB1"),
      (":england: Championship", "https://www.transfermarkt.co.uk/championship/startseite/wettbewerb/GB2"),
      ("🇳🇱 Eredivisie", "https://www.transfermarkt.co.uk/eredivisie/startseite/wettbewerb/NL1"),
      ("🇩🇪 Bundesliga", "https://www.transfermarkt.co.uk/bundesliga/startseite/wettbewerb/L1"),
      ("🇮🇹 Serie A", "https://www.transfermarkt.co.uk/serie-a/startseite/wettbewerb/IT1"),
      ("🇪🇸 LaLiga", "https://www.transfermarkt.co.uk/primera-division/startseite/wettbewerb/ES1"),
      ("🇫🇷 Ligue 1", "https://www.transfermarkt.co.uk/ligue-1/startseite/wettbewerb/FR1"),
      ("🇺🇸 Major League Soccer", "https://www.transfermarkt.co.uk/major-league-soccer/startseite/wettbewerb/MLS1")]


class Transfers(commands.Cog):
    """Create and configure Transfer Ticker channels"""
    
    def __init__(self, bot):
        self.bot = bot
        self.parsed = []
        self.bot.transfers = self.transfer_ticker.start()
        self.warn_once = []
        self.cache = defaultdict(set)
        for i in [embed_utils, transfer_tools]:
            reload(i)
    
    def cog_unload(self):
        """Cancel transfers task on Cog Unload."""
        self.bot.transfers.cancel()

    async def update_cache(self):
        """Grab latest database info and load it into memory"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""
            SELECT guild_id, transfers_channels.channel_id, item, alias
            FROM transfers_channels
            LEFT OUTER JOIN transfers_leagues
            ON transfers_channels.channel_id = transfers_leagues.channel_id""")
    
        await self.bot.db.release(connection)
    
        # Clear out our cache.
        self.cache.clear()
    
        # Repopulate.
        for r in records:
            if (r["guild_id"], r["channel_id"]) in self.warn_once:
                continue

            ch = self.bot.get_channel(r['channel_id'])
            if ch is None:
                print("Transfers: Deleted Channel Detected:", r["channel_id"])
                self.warn_once.append((r["guild_id"], r["channel_id"]))
                continue

            perms = ch.guild.me.permissions_in(ch)
            if not perms.send_messages or not perms.embed_links:
                self.warn_once.append((r["guild_id"], r["channel_id"]))

            self.cache[(r["guild_id"], r["channel_id"])].add((r["item"], r["alias"]))

    @property
    async def base_embed(self):
        """Generic Discord Embed for Transfers Settings data"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_blue()
        e.title = "Toonbot Transfer Ticker config"
        e.set_thumbnail(url=self.bot.user.avatar_url)
        return e

    async def warn_missing_perms(self, ctx):
        """Aggressively tell users they've fucked up their permissions for transfers."""
        bad_guild_channels = [self.bot.get_channel(i[1]) for i in self.warn_once if ctx.guild.id == i[0]]

        if not bad_guild_channels:
            return

        deleted = len([i for i in bad_guild_channels if i is None])
        not_deleted = [i for i in bad_guild_channels if i is not None]

        if deleted > 0:
            await self.bot.reply(ctx, f"{deleted} of your transfer-ticker channel(s) appear to be deleted.")

        no_send_perms = [i.mention for i in not_deleted if not ctx.me.permissions_in(i).send_messages]
        if no_send_perms:
            await self.bot.reply(ctx, f"WARNING: I do not have send_messages permissions in {''.join(no_send_perms)}\n"
                                      f"**Transfers will not be output**")

        no_embed_perms = [i.mention for i in not_deleted if not ctx.me.permissions_in(i).embed_links]
        if no_embed_perms:
            await self.bot.reply(ctx, f"WARNING: I do not have embed_links permissions in {''.join(no_send_perms)}\n"
                                      f"**Transfers will not be output**")

    async def send_leagues(self, ctx, channel):
        """Display all currently tracked leagues for transfers."""
        e = await self.base_embed
        header = f'Tracked leagues for {channel.mention}\n'

        if not ctx.me.permissions_in(channel).send_messages:
            header += "```css\n[WARNING]: I do not have send_messages permissions in that channel!"
        if not ctx.me.permissions_in(channel).embed_links:
            header += "```css\n[WARNING]: I do not have embed_links permissions in that channel!"

        leagues = self.cache[(ctx.guild.id, channel.id)]
        e.description = header
        if leagues == {None, None}:
            e.description += "```css\n[WARNING]: Your whitelist is completely empty! Nothing is being output!```"
            embeds = [e]
        else:
            # Make whitelist readable
            leagues = [f"[{i[1]}]({i[0]})" for i in sorted(leagues)]
            embeds = embed_utils.rows_to_embeds(e, leagues, header=header)
        
        await embed_utils.paginate(ctx, embeds)
    
    async def _pick_channels(self, ctx, channels: typing.List[discord.TextChannel]):
        # Assure guild has transfer channel.
        if ctx.guild.id not in [i[0] for i in self.cache]:
            await self.bot.reply(ctx, text=f'{ctx.guild.name} does not have any transfer tickers set.',
                                 mention_author=True)
            return []
        
        if channels:
            # Verify selected channels are actually in the database.
            checked = []
            channels = [channels] if isinstance(channels, discord.TextChannel) else channels
            for i in channels:
                if i.id not in [c[1] for c in self.cache]:
                    await self.bot.reply(ctx, text=f"{i.mention} is not set as a transfer ticker.", mention_author=True)
                else:
                    checked.append(i)
            channels = checked

        if not channels:
            channels = [self.bot.get_channel(i[1]) for i in self.cache if i[0] == ctx.guild.id]
            # Filter out NoneTypes caused by deleted channels.
            channels = [i for i in channels if i is not None]

        channel_links = [i.mention for i in channels]
        index = await embed_utils.page_selector(ctx, channel_links, choice_text="For which channel?")

        if index == "cancelled" or index is None or index == -1:
            return None  # Cancelled or timed out.
        channel = channels[index]

        return channel

    async def _get_team_league(self, link):
        async with self.bot.session.get(link) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        name = "".join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/text()')).strip()
        link = "".join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/@href'))

        link = "https://www.transfermarkt.co.uk" + link if link else ""
        return name, link

    @tasks.loop(seconds=60)
    async def transfer_ticker(self):
        """Core transfer ticker loop - refresh every x seconds and get all new transfers from transfermarkt"""
        url = 'https://www.transfermarkt.co.uk/transfers/neuestetransfers/statistik?minMarktwert=200.000'
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                print(f'Transfers: recieved bad status: {resp.status}')
                return
            tree = html.fromstring(await resp.text())

        skip_output = True if not self.parsed else False

        tf_cache = self.cache.copy().items()

        for i in tree.xpath('.//div[@class="responsive-table"]/div/table/tbody/tr'):
            name = "".join(i.xpath('.//td[1]//tr[1]/td[2]/a/text()')).strip()

            if not name or name in self.parsed:
                continue  # skip when duplicate / void.
            else:
                self.parsed.append(name)

            # We don't need to output when populating after a restart.
            if skip_output:
                continue

            # Player Info
            link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[1]//tr[1]/td[2]/a/@href'))
            age = "".join(i.xpath('./td[2]//text()')).strip()
            position = "".join(i.xpath('./td[1]//tr[2]/td/text()'))
            country = i.xpath('.//td[3]/img/@title')
            picture = "".join(i.xpath('.//td[1]//tr[1]/td[1]/img/@src'))

            # Leagues & Fee
            new_team = "".join(i.xpath('.//td[5]//td[2]/a/text()')).strip()
            new_team_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[5]//td[2]/a/@href')).strip()

            old_team = "".join(i.xpath('.//td[4]//td[2]/a/text()')).strip()
            old_team_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[4]//td[2]/a/@href')).strip()

            new_league, new_league_link = await self._get_team_league(new_team_link)
            old_league, old_league_link = await self._get_team_league(old_team_link)

            new_league_country = "".join(i.xpath('.//td[5]/table//tr[2]/td//img/@alt'))
            old_league_country = "".join(i.xpath('.//td[4]/table//tr[2]/td//img/@alt'))

            fee = "".join(i.xpath('.//td[6]//a/text()'))
            fee_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[6]//a/@href'))

            player = transfer_tools.Player(name, link, new_team, age, position, new_team_link, country, picture)
            new_team = transfer_tools.Team(new_team, new_team_link, new_league_country, new_league, new_league_link)
            old_team = transfer_tools.Team(old_team, old_team_link, old_league_country, old_league, old_league_link)
            transfer = transfer_tools.Transfer(player, old_team, new_team, fee, fee_link)

            e = transfer.embed

            for (guild_id, channel_id), whitelist in tf_cache:
                ch = self.bot.get_channel(channel_id)
                if ch is None:
                    continue  # rip.

                # Iterate through every whitelist item, if there is not a match, we iterate to the next channel.
                for (link, alias) in whitelist:
                    if link is None:
                        continue

                    if link in new_league_link or link in old_league_link:
                        try:
                            await ch.send(embed=e)
                        except (discord.NotFound, discord.Forbidden):  # This is your problem, not mine.
                            pass
                        break

    @transfer_ticker.before_loop
    async def before_tf_loop(self):
        """Pre-loading of Cache before loop commencement."""
        await self.bot.wait_until_ready()
        await self.update_cache()

    @commands.group(invoke_without_command=True, usage="<#channel>")
    @commands.has_permissions(manage_channels=True)
    async def tf(self, ctx, channels: commands.Greedy[discord.TextChannel]):
        """Get info on your server's transfer tickers."""
        channel = await self._pick_channels(ctx, channels)

        if not channel:
            return  # rip

        await self.send_leagues(ctx, channel)

    @commands.has_permissions(manage_channels=True)
    @tf.command(usage="<#Channel[, #Channel2, ...]> <Search query>")
    async def add(self, ctx, channels: commands.Greedy[discord.TextChannel], *, query: commands.clean_content):
        """Add a league or team to your transfer ticker channel(s)"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return

        result = await transfer_tools.TransferSearch.search(ctx, query, category="Domestic Competitions",
                                                            returns_object=True)
        if result is None:
            return

        alias = f"{result.flag} {result.name}"

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                        VALUES ($1, $2, $3)
                                        ON CONFLICT DO NOTHING""", channel.id, result.link, alias)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ {alias} added to {channel.mention} tracker")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

        # Fuck you fix your shit.
        await self.warn_missing_perms(ctx)

    @commands.has_permissions(manage_channels=True)
    @tf.group(usage="<name of country and league to remove>", invoke_without_command=True)
    async def remove(self, ctx, channels: commands.Greedy[discord.TextChannel] = None, *, target):
        """Remove a whitelisted item from your transfer channel ticker"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        target = target.strip('\'"')
        matches = [i for i in self.cache[(ctx.guild.id, channel.id)] if target.lower() in i[1].lower()]
        
        # Verify which item the user wishes to remove.
        index = await embed_utils.page_selector(ctx, [f"{i[1]}]({i[0]})" for i in matches])
        if index is None or index == "cancelled" or index == -1:
            return  # rip.

        item = matches[index][1]

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_leagues WHERE (channel_id,alias) = ($1,$2)""",
                                     channel.id, item)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f'✅ {item} was removed from the {channel.mention} whitelist.')
        await self.update_cache()
        await self.send_leagues(ctx, channel)

        # Fuck you fix your shit.
        await self.warn_missing_perms(ctx)
    
    @remove.command()
    @commands.has_permissions(manage_channels=True)
    async def all(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove ALL competitions from a transfer ticker"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            async with connection.transaction():
                await connection.execute("""DELETE FROM transfers_leagues WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ {channel.mention} was reset to the default leagues.")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

        # Fuck you fix your shit.
        await self.warn_missing_perms(ctx)

    @tf.command()
    @commands.has_permissions(manage_channels=True)
    async def reset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Reset transfer ticker to use the default leagues"""
        channel = await self._pick_channels(ctx, channels)
        if not channel:
            return  # rip

        leagues = self.cache[(ctx.guild.id, channel.id)]
        if leagues == LG:
            return await self.bot.reply(ctx, f"⚠ {channel.mention} is already using the default leagues.")

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_leagues WHERE channel_id = $1""", channel.id)
            for alias, link in LG:
                await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                         VALUES ($1, $2, $3)""", channel.id, link, alias)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ {channel.mention} had it's tracked leagues reset to the defaults.")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

        # Fuck you fix your shit.
        await self.warn_missing_perms(ctx)

    @tf.command(aliases=["create"], usage="<#channel [, #channel2]>")
    @commands.has_permissions(manage_channels=True)
    async def set(self, ctx, channel: discord.TextChannel = None):
        """Set channel(s) as a transfer ticker for this server"""
        if channel is None:
            channel = ctx.channel

        if not ctx.me.permissions_in(channel).send_messages:
            failmsg = "� I do not have send_messages permissions in that channel."
            return await self.bot.reply(ctx, text=failmsg, mention_author=True)
        elif not ctx.me.permissions_in(channel).embed_links:
            failmsg = "� I do not have embed_links permissions in that channel."
            return await self.bot.reply(ctx, text=failmsg, mention_author=True)
        
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            try:
                await connection.execute("""INSERT INTO transfers_channels (guild_id,channel_id) VALUES ($1,$2)""",
                                         ctx.guild.id, channel.id)
            except UniqueViolationError:
                await self.bot.reply(ctx, text=f'A transfer ticker already exists for {channel.mention}')
                return
            for alias, link in LG:
                await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                         VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""", channel.id, link, alias)

        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ Created a transfer ticker in {channel.mention}.\n\n"
                                       f"Use {ctx.prefix}unset {channel.mention} to remove the transfer ticker.")
        await self.update_cache()
        await self.send_leagues(ctx, channel)

    @tf.command(usage="<#channel-to-unset>")
    @commands.has_permissions(manage_channels=True)
    async def unset(self, ctx, channels: commands.Greedy[discord.TextChannel] = None):
        """Remove a channel's transfer ticker"""
        channel = await self._pick_channels(ctx, channels)
        if channel is None:
            return

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ Removed transfer ticker from {channel.mention}")
        await self.update_cache()

    @tf.command(usage="<channel_id>", hidden=True)
    @commands.is_owner()
    async def admin(self, ctx, channel_id: int):
        """Force-delete a broken transfer ticker."""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel_id)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f"✅ **{channel_id}** was deleted from the transfers database")
        await self.update_cache()
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete all transfer info for a guild from database upon leaving"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)
        await self.update_cache()
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Delete all transfer info for a channel from database upon deletion"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)
        await self.update_cache()


def setup(bot):
    """Load the transfer ticker cog into the bot"""
    bot.add_cog(Transfers(bot))
