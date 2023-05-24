"""Testing Cog for new commands."""
from __future__ import annotations

import logging
import typing

import discord
from discord.ext import commands
from playwright.async_api import Request

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot  #

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]

URI = (
    "https://worldofwarships.eu/en/content/"
    "contents-and-drop-rates-of-containers/"
)
logger = logging.getLogger("test")


# TODO: Container drops
class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @staticmethod
    async def get_request(request: Request):
        """Print the request, has to be floating function because of lambda."""
        if "get_lootbox/" not in request.url:
            return

        logger.debug("REQUEST RECEIVED %s\n", request.url)
        resp = await request.response()
        if resp is not None:
            logger.debug(resp.json())

    @discord.app_commands.command()
    @discord.app_commands.guilds(250252535699341312)
    async def lootboxes(self, interaction: Interaction):
        """Get lootbox data."""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()

        page.on(
            "request", lambda r: self.bot.loop.create_task(self.get_request(r))
        )
        await page.goto(URI)
        msg = "Request complete, check console."
        return await interaction.edit_original_response(content=msg)


async def setup(bot: Bot | PBot):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
