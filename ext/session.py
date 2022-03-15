"""Bot browser Session"""
from typing import TYPE_CHECKING

import pyppeteer
from discord.ext import commands
from pyppeteer.browser import Browser

if TYPE_CHECKING:
    from core import Bot


async def make_browser() -> Browser:
    """Spawn an instance of Pyppeteer"""
    options = {"args": [
        '--autoplay-policy=user-gesture-required',
        '--disable-accelerated-2d-canvas',
        '--disable-backgrounding-occluded-windows',
        '--disable-background-timer-throttling',
        '--disable-breakpad',
        '--disable-client-side-phishing-detection',
        '--disable-component-extensions-with-background-pages',
        '--disable-component-update',
        '--disable-default-apps',
        '--disable-dev-shm-usage',
        '--disable-extensions',
        '--disable-features=BlinkGenPropertyTrees',
        '--disable-ipc-flooding-protection',
        '--disable-infobars',
        '--disable-notifications',
        '--disable-renderer-backgrounding',
        '--disable-setuid-sandbox',
        '--disable-sync',
        '--disable-translate',

        '--enable-features=NetworkService,NetworkServiceInProcess',
        '--force-color-profile=srgb',

        '--hide-scrollbars',

        '--ignore-certificate-errors',
        '--ignore-certificate-errors-skip-list',

        '--metrics-recording-only',
        '--mute-audio',
        '--no-default-browser-check',
        '--no-first-run',
        '--no-zygote',

        '--window-position=0,0'
    ]}

    return await pyppeteer.launch(options=options)


class BrowserCog(commands.Cog, name="Browser"):
    """(Re)-Initialise an aiohttp ClientSession"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot = bot


async def setup(bot):
    """Load into bot"""
    await bot.add_cog(BrowserCog(bot))
