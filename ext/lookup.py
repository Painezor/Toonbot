"""Commands for fetching information about football entities from transfermarkt"""
from copy import deepcopy
from importlib import reload

import discord
from discord.ext import commands
from lxml import html

from ext.utils import transfer_tools, embed_utils


class Lookups(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot):
        self.bot = bot
        reload(transfer_tools)

    # Base lookup - No Sub-command invoked.
    @commands.group(invoke_without_command=True, usage="<Who you want to search for>")
    async def lookup(self, ctx, *, query: commands.clean_content):
        """Perform a database lookup on transfermarkt"""
        p = {"query": query}  # html encode.
        async with self.bot.session.post(f"http://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche",
                                         params=p) as resp:
            if resp.status != 200:
                return await self.bot.reply(ctx, text=f"HTTP Error connecting to transfermarkt: {resp.status}")
            tree = html.fromstring(await resp.text())

        # Header names, scrape then compare (because they don't follow a pattern.)
        categories = [i.lower().strip() for i in tree.xpath(".//div[@class='table-header']/text()")]

        results = []
        for i in categories:
            length = "".join([n for n in i if n.isdecimal()])  # Just give number of matches (non-digit characters).
            if 'search results for players' in i:
                results.append((f"Players ({length} Found)", self._player))
            elif 'search results: clubs' in i:
                results.append((f"Teams ({length} Found)", self._team))
            elif 'search results for agents' in i:
                results.append((f"Agents ({length} Found)", self._agent))
            elif 'search results for referees' in i:
                results.append((f"Referees ({length} Found)", self._ref))
            elif 'search results: managers & officials' in i:
                results.append((f"Staff ({length} Found)", self._staff))
            elif 'search results to competitions' in i:
                results.append((f"Domestic Competitions ({length} found)", self._cup))
            elif 'search results for international competitions' in i:
                results.append((f"International Competitions ({length} found)", self._cup))
            else:
                print('lookup - unhandled category: ', i)
                    
        if not results:
            await self.bot.reply(ctx, text=f":no_entry_sign: No results for {query}")
            return None
        
        index = await embed_utils.page_selector(ctx, item_list=[i[0] for i in results])
        if index is None:
            return  # rip
        
        await ctx.invoke(results[index][1], qry=query)

    @lookup.command(name="player")
    async def _player(self, ctx, *, qry: commands.clean_content):
        """Lookup a player on transfermarkt"""
        await transfer_tools.search(ctx, qry, "players")

    @lookup.command(name="staff", aliases=["manager", "trainer", "trainers", "managers"])
    async def _staff(self, ctx, *, qry: commands.clean_content):
        """Lookup a manager/trainer/club official on transfermarkt"""
        await transfer_tools.search(ctx, qry, "staff")

    @lookup.command(name="team", aliases=["club"])
    async def _team(self, ctx, *, qry: commands.clean_content):
        """Lookup a team on transfermarkt"""
        await transfer_tools.search(ctx, qry, "teams")

    @lookup.command(name="ref")
    async def _ref(self, ctx, *, qry: commands.clean_content):
        """Lookup a referee on transfermarkt"""
        await transfer_tools.search(ctx, qry, "referees")

    @lookup.command(name="cup", aliases=["domestic"])
    async def _cup(self, ctx, *, qry: commands.clean_content):
        """Lookup a domestic competition on transfermarkt"""
        await transfer_tools.search(ctx, qry, "domestic")

    @lookup.command(name="international", aliases=["int"])
    async def _int(self, ctx, *, qry: commands.clean_content):
        """Lookup an international on transfermarkt"""
        await transfer_tools.search(ctx, qry, "internationals")

    @lookup.command(name="agent")
    async def _agent(self, ctx, *, qry: commands.clean_content):
        """Lookup an agent on transfermarkt"""
        await transfer_tools.search(ctx, qry, "agent")

    @commands.command(usage="<team to search for>")
    async def transfers(self, ctx, *, qry: commands.clean_content):
        """Get this window's transfers for a team on transfermarkt"""
        if str(qry).startswith("set") and ctx.message.channel_mentions:
            return await self.bot.reply(ctx, "You probably meant to use .tf, not .transfers.", mention_author=True)
        
        team = await transfer_tools.search(ctx, qry, "teams", special=True)
        if team is None:
            return  # rip
        
        try:
            inbound, outbound, source_url = await team.get_transfers(ctx)
        except TypeError:
            return await self.bot.reply(ctx, 'Invalid team selected or no transfers found on page.')

        base_embed = await team.base_embed
        base_embed.url = source_url
        
        embeds = []
        
        if inbound:
            e = deepcopy(base_embed)
            e.title = f"Inbound Transfers for {e.title}"
            e.colour = discord.Colour.green()
            embeds += embed_utils.rows_to_embeds(e, [str(i) for i in inbound])

        if outbound:
            e = base_embed
            e.title = f"Outbound Transfers for {e.title}"
            e.colour = discord.Colour.red()
            embeds += embed_utils.rows_to_embeds(e, [str(i) for i in outbound])
            
        await embed_utils.paginate(ctx, embeds)
            
    @commands.command(name="rumours", aliases=["rumors"])
    async def _rumours(self, ctx, *, qry: commands.clean_content):
        """Get the latest transfer rumours for a team"""
        res = await transfer_tools.search(ctx, qry, "teams", special=True)
        if res is None:
            return
        
        await transfer_tools.get_rumours(ctx, res)

    @commands.command()
    async def contracts(self, ctx, *, qry: commands.clean_content):
        """Get a team's expiring contracts"""
        res = await transfer_tools.search(ctx, qry, "teams", special=True)
        if res is None:
            return

        await transfer_tools.get_contracts(ctx, res)


def setup(bot):
    """Load the lookup cog into the bot"""
    bot.add_cog(Lookups(bot))
