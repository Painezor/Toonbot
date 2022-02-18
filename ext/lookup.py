"""Commands for fetching information about football entities from transfermarkt"""
from importlib import reload

import discord
from discord import SlashCommandGroup
from discord.ext import commands

from ext.utils import transfer_tools

TF = "https://www.transfermarkt.co.uk"
FAVICON = "https://upload.wikimedia.org/wikipedia/commons/f/fb/Transfermarkt_favicon.png"


# TODO: User Commands Pass
# TODO: Modals pass
# TODO: Slash attachments pass
# TODO: Permissions Pass.


class Lookups(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot):
        self.bot = bot
        reload(transfer_tools)
        self.emoji = "🔎"

    async def searching(self, ctx, string):
        """Send a dummy searching embed."""
        e = discord.Embed()
        e.description = f"Searching for {string}..."
        e.set_author(name="TransferMarkt", icon_url=FAVICON)
        return await ctx.reply(embed=e)

    async def comp_view(self, ctx, query):
        """Shared function for following commands."""
        view = transfer_tools.SearchView(ctx, query, category="Competitions", fetch=True)
        view.message = await ctx.reply(content=f"Fetching Competitions matching {query}", view=view)
        await view.update()

        comp = view.value

        if comp is None:
            return

        _ = comp.view(ctx)
        __ = ctx.command.name
        _.message = await view.message.edit(content=f"Fetching {__} for {comp.name}", view=_)

        return None if comp is None else _

    lookup = SlashCommandGroup("lookup", "Look something up on TransferMarkt")

    @lookup.command()
    async def player(self, ctx, *, player_name):
        """Search for a player on transfermarkt"""
        message = await self.searching(ctx, player_name)
        view = transfer_tools.SearchView(ctx, player_name, category="Players")
        view.message = message
        await view.update()

    @lookup.command()
    async def team(self, ctx, *, team_name):
        """Lookup a team on transfermarkt"""
        message = await self.searching(ctx, team_name)
        view = transfer_tools.SearchView(ctx, team_name, category="Clubs")
        view.message = message
        await view.update()

    @lookup.command()
    async def staff(self, ctx, *, name):
        """Lookup a manager, trainer, or club official on transfermarkt"""
        message = await self.searching(ctx, name)
        view = transfer_tools.SearchView(ctx, name, category="Managers")
        view.message = message
        await view.update()

    @lookup.command()
    async def referee(self, ctx, *, name):
        """Lookup a referee on transfermarkt"""
        message = await self.searching(ctx, name)
        view = transfer_tools.SearchView(ctx, name, category="Referees")
        view.message = message
        await view.update()

    @lookup.command()
    async def competition(self, ctx, *, name):
        """Lookup a competition on transfermarkt"""
        message = await self.searching(ctx, name)
        view = transfer_tools.SearchView(ctx, name, category="Competitions")
        view.message = message
        await view.update()

    @lookup.command()
    async def agent(self, ctx, *, name):
        """Lookup an agent on transfermarkt"""
        message = await self.searching(ctx, name)
        view = transfer_tools.SearchView(ctx, name, category="Agents")
        view.message = message
        await view.update()

    @commands.slash_command()
    async def transfers(self, ctx, *, team_name):
        """Get this window's transfers for a team on transfermarkt"""
        message = await self.searching(ctx, team_name)
        view = transfer_tools.SearchView(ctx, team_name, category="Clubs", fetch=True)
        view.message = message
        await view.update()

        if view.value is None:
            return

        view = view.value.view(ctx)
        view.message = message
        await view.push_transfers()

    @commands.slash_command()
    async def rumours(self, ctx, *, team_name):
        """Get the latest transfer rumours for a team"""
        message = await self.searching(ctx, team_name)
        view = transfer_tools.SearchView(ctx, team_name, category="Clubs", fetch=True)
        view.message = message
        await view.update()

        if view.value is None:
            return

        view = view.value.view(ctx)
        view.message = message
        await view.push_rumours()

    @commands.slash_command()
    async def contracts(self, ctx, *, team_name):
        """Get a team's expiring contracts"""
        message = await self.searching(ctx, team_name)
        view = transfer_tools.SearchView(ctx, team_name, category="Clubs", fetch=True)
        view.message = message
        await view.update()

        if view.value is None:
            return

        view = view.value.view(ctx)
        view.message = message
        await view.push_contracts()

    @commands.slash_command()
    async def trophies(self, ctx, *, team_name):
        """Get a team's trophy case"""
        message = await self.searching(ctx, team_name)
        view = transfer_tools.SearchView(ctx, team_name, category="Clubs", fetch=True)
        view.message = message
        await view.update()

        if view.value is None:
            return

        view = view.value.view(ctx)
        view.message = message
        await view.push_trophies()

    @commands.command(usage="<competition to search for>")
    @commands.is_owner()
    async def attendance(self, ctx, *, query):
        """Get a list of a league's average attendances."""
        _ = await self.comp_view(ctx, query)
        if _ is not None:
            await _.push_attendance()


def setup(bot):
    """Load the lookup cog into the bot"""
    bot.add_cog(Lookups(bot))
