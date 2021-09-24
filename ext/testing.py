"""Testing Cog for new commands."""
from importlib import reload

from discord.ext import commands

from ext.utils import view_utils, football, transfer_tools


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🧪"
        reload(view_utils)
        reload(football)

    def cog_check(self, ctx):
        """Assure all commands in this cog can only be ran on the r/NUFC discord"""
        if ctx.guild:
            return ctx.channel.id == 873620981497876590 or ctx.author.id == 210582977493598208

    @commands.group(invoke_without_command=True)
    async def test(self, ctx, *, query: commands.clean_content = None):
        """Current testing for New Transfer Lookups System"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify something to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query)
        view.message = await self.bot.reply(ctx, f"Fetching results for {query}", view=view)
        await view.update()

    @test.command(name="player")
    async def _player(self, ctx, *, query: commands.clean_content = None):
        """Lookup a player on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a player name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Players")
        view.message = await self.bot.reply(ctx, f"Fetching player results for {query}", view=view)
        await view.update()

    @test.command(name="team", aliases=["club"])
    async def _team(self, ctx, *, query: commands.clean_content = None):
        """Lookup a team on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Clubs")
        view.message = await self.bot.reply(ctx, f"Fetching club results for {query}", view=view)
        await view.update()

    @test.command(name="staff", aliases=["manager", "trainer", "trainers", "managers"])
    async def _staff(self, ctx, *, query: commands.clean_content = None):
        """Lookup a manager/trainer/club official on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Staff")
        view.message = await self.bot.reply(ctx, f"Fetching staff results for {query}", view=view)
        await view.update()


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))

# Maybe TO DO: Button to Toggle Substitutes in Extended Views
