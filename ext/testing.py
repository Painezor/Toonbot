"""Testing Cog for new commands."""
from importlib import reload

from discord.ext import commands

from ext.utils import view_utils, football


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


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))

# Maybe TO DO: Button to Toggle Substitutes in Extended Views
