"""Testing Cog for new commands."""
from discord.ext import commands


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot):
        self.bot = bot


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))
