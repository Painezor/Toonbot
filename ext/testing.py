"""Testing Cog for new commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot


async def setup(bot: Bot | PBot):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
