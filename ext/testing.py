"""Testing Cog for new commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Interaction
from discord.app_commands import command, guilds
from discord.ext import commands
from playwright.async_api import Request

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


# TODO: Container drops / https://worldofwarships.eu/en/content/contents-and-drop-rates-of-containers/

class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @staticmethod
    async def get_request(request: Request):
        """Print the request, has to be a floating function because of lambda."""
        if "get_lootbox/" not in request.url:
            return

        print(f'REQUEST RECEIVED {request.url}\n')
        resp = await request.response()
        print(resp.json())

    @command()
    @guilds(250252535699341312)
    async def lootboxes(self, interaction: Interaction):
        """Get lootbox data."""
        await interaction.response.defer(thinking=True)
        page = await self.bot.browser.new_page()
        page.on('request', lambda request: self.bot.loop.create_task(self.get_request(request)))
        await page.goto('https://worldofwarships.eu/en/content/contents-and-drop-rates-of-containers/')
        return await self.bot.reply(interaction, content='Request complete, check console.')


async def setup(bot: Bot | PBot):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
