"""Testing Cog for new commands."""
from importlib import reload

from discord.ext import commands

from ext.utils import transfer_tools


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🧪"
        reload(transfer_tools)

    def cog_check(self, ctx):
        """Assure all commands in this cog can only be ran on the r/NUFC discord"""
        return ctx.guild.id == 250252535699341312 if ctx.guild is not None else False

    # @commands.command()
    # @commands.is_owner()
    # async def prematch(self, ctx):
    #     """Debug for pre-match thread testing."""
    #     await ctx.send('Running...')
    #     page = await self.bot.browser.newPage()
    #     try:
    #         fix = await football.Fixture.by_id('6kBfKmCH', page)
    #         await fix.refresh(page, for_reddit=True)
    #     finally:
    #         await page.close()
    #
    #     print(fix.__dict__)

    @commands.command()
    @commands.is_owner()
    async def transfers(self, ctx, *, team_name):
        """Get this window's transfers for a team on transfermarkt"""
        message = await self.bot.reply(ctx, content=team_name)
        view = transfer_tools.SearchView(ctx, team_name, category="Clubs", fetch=True)
        view.message = message
        await view.update()

        if view.value is None:
            return

        view = view.value.view(ctx)
        view.message = message
        await view.push_transfers()


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))

# Maybe TO DO: Button to Toggle Substitutes in Extended Views
