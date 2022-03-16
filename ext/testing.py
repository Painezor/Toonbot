"""Testing Cog for new commands."""

from discord.ext import commands


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot) -> None:
        self.bot = bot


async def setup(bot):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
