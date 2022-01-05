from importlib import reload

import aiohttp
from discord.ext import commands

from ext.utils import browser


class Browser(commands.Cog):
    """(Re)-Intialise an aiohttp ClientSession"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.spawn_session())
        reload(browser)

    async def spawn_session(self):
        """Create a ClientSession object and attach to the bot."""
        try:
            await self.bot.session.close()
        except AttributeError:
            pass

        self.bot.session = aiohttp.ClientSession(loop=self.bot.loop, connector=aiohttp.TCPConnector(ssl=False))


def setup(bot):
    """Load into bot"""
    bot.add_cog(Browser(bot))
