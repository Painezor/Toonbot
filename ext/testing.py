"""Testing Cog for new commands."""
from importlib import reload
from typing import TYPE_CHECKING, Union

from discord.ext import commands

from ext.utils import football

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot
        reload(football)


async def setup(bot: Union['Bot', 'PBot']):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
