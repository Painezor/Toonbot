"""Testing Cog for new commands."""
from typing import TYPE_CHECKING, Union

from discord.ext import commands

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot


async def setup(bot: Union['Bot', 'PBot']):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
