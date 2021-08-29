"""Commands for fetching information about football entities from transfermarkt"""
from copy import deepcopy
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import transfer_tools, embed_utils, view_utils


# TODO: Select / Button Pass.

class Lookups(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot):
        self.bot = bot
        reload(transfer_tools)
        self.emoji = "🔎"

    # Base lookup - No Sub-command invoked.
    @commands.group(invoke_without_command=True, usage="<Who you want to search for>")
    async def lookup(self, ctx, *, query: commands.clean_content):
        """Perform a database lookup on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify something to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query)

    @lookup.command(name="player")
    async def _player(self, ctx, *, query: commands.clean_content = None):
        """Lookup a player on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a player name to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="Players")

    @lookup.command(name="team", aliases=["club"])
    async def _team(self, ctx, *, query: commands.clean_content = None):
        """Lookup a team on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="Players")

    @lookup.command(name="staff", aliases=["manager", "trainer", "trainers", "managers"])
    async def _staff(self, ctx, *, query: commands.clean_content = None):
        """Lookup a manager/trainer/club official on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a name to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="Staff")

    @lookup.command(name="ref")
    async def _ref(self, ctx, *, query: commands.clean_content = None):
        """Lookup a referee on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a referee name to search for.',
                                        ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="Referee")

    @lookup.command(name="cup", aliases=["domestic"])
    async def _cup(self, ctx, *, query: commands.clean_content = None):
        """Lookup a domestic competition on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a competition to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="Domestic Competitions")

    @lookup.command(name="international", aliases=["int"])
    async def _int(self, ctx, *, query: commands.clean_content = None):
        """Lookup an international on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a competition to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="International Competitions")

    @lookup.command(name="agent")
    async def _agent(self, ctx, *, query: commands.clean_content = None):
        """Lookup an agent on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify an agent name to search for.', ping=True)
        await transfer_tools.TransferSearch.search(ctx, query, category="Agents")

    @commands.command(usage="<team to search for>")
    async def transfers(self, ctx, *, query: commands.clean_content = None):
        """Get this window's transfers for a team on transfermarkt"""
        if str(query).startswith("set") and ctx.message.channel_mentions:
            return await self.bot.reply(ctx, "🚫 You probably meant to use .tf, not .transfers.", ping=True)

        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for.', ping=True)

        team = await transfer_tools.TransferSearch.search(ctx, query, category="Clubs", returns_object=True)
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
            e = deepcopy(base_embed)
            e.title = f"Outbound Transfers for {e.title}"
            e.colour = discord.Colour.red()
            embeds += embed_utils.rows_to_embeds(e, [str(i) for i in outbound])

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, f"Fetching transfers for {base_embed.title}", view=view)
        await view.update()

    @commands.command(aliases=["rumors"])
    async def rumours(self, ctx, *, query: commands.clean_content = None):
        """Get the latest transfer rumours for a team"""
        if query is None:
            return self.bot.reply(ctx, "You need to specify a team name to search for rumours from.")

        res = await transfer_tools.TransferSearch.search(ctx, query, category="Clubs", returns_object=True)
        if res is None:
            return

        await res.get_rumours(ctx)

    @commands.command()
    async def contracts(self, ctx, *, query: commands.clean_content = None):
        """Get a team's expiring contracts"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for contracts from.',
                                        ping=True)

        res = await transfer_tools.TransferSearch.search(ctx, query, category="Clubs", returns_object=True)
        if res is None:
            return

        await res.get_contracts(ctx)

    @commands.command()
    async def trophies(self, ctx, *, query: commands.clean_content = None):
        """Get a list of a team's trophies"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for trophies for.',
                                        ping=True)

        res = await transfer_tools.TransferSearch.search(ctx, query, category="Clubs", returns_object=True)
        if res is None:
            return

        trophies = await res.get_trophies(ctx)
        e = await res.base_embed
        e.title = f"{res.name} Trophy Case"

        trophies = ["No trophies found for team."] if not trophies else trophies
        embeds = embed_utils.rows_to_embeds(e, trophies)

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, f"Fetching trophies for {res.name}", view=view)
        await view.update()


def setup(bot):
    """Load the lookup cog into the bot"""
    bot.add_cog(Lookups(bot))
