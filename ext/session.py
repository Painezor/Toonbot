"""Bot browser Session"""
from io import BytesIO
from typing import Union

import aiohttp
import discord
import pyppeteer
from PIL import Image
from discord.commands import permissions
from discord.ext import commands
from pyppeteer.errors import TimeoutError as _TimeoutError


class Browser(commands.Cog):
    """(Re)-Initialise an aiohttp ClientSession"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.spawn_session())
        if not hasattr(bot, "browser"):
            self.bot.loop.create_task(self.make_browser())

    async def spawn_session(self):
        """Create a ClientSession object and attach to the bot."""
        try:
            await self.bot.session.close()
        except AttributeError:
            pass

        self.bot.session = aiohttp.ClientSession(loop=self.bot.loop, connector=aiohttp.TCPConnector(ssl=False))

    async def make_browser(self):
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

        self.bot.browser = await pyppeteer.launch(options=options)
        self.bot.browser.fetch = self.fetch
        self.bot.browser.bot = self.bot

    async def fetch(self, page, url, xpath, screenshot=False, max_retry=3, **kwargs) -> (Union[str, BytesIO] or None):
        """Fetch a webpage's source code or an image"""
        assert url.startswith("http"), f"BROWSER - FETCH: {url} does not appear to be a valid url."

        close = False
        if page.isClosed():
            # Replace closed pages.
            page = await self.bot.browser.newPage()
            close = True

        for _ in range(max_retry):
            try:
                await page.goto(url)
                break
            except _TimeoutError:
                print(f"Fetch Page timed out trying to access {url}")
        else:
            if close:
                await page.close()
            return None

        try:
            await page.waitForXPath(xpath, {"timeout": 5000})
        except _TimeoutError:
            pass

        for x in kwargs.get('delete', []):
            elements = await page.xpath(x)
            for element in elements:
                try:
                    await page.evaluate("""(element) => element.parentNode.removeChild(element)""", element)
                except pyppeteer.errors.ElementHandleError:  # If no exist.
                    continue

        for x in kwargs.get('clicks', []):
            try:
                await page.waitForSelector(x, {"timeout": 1000})
            except _TimeoutError:
                continue
            element = await page.querySelector(x)
            if element is not None:
                await element.click()

        if screenshot:
            await page.setViewport({"width": 1900, "height": 1100})
            elements = await page.xpath(xpath)
            if elements:
                bbox = await elements[0].boundingBox()
                bbox['height'] *= len(elements)
                screenshot = Image.open(BytesIO(await page.screenshot(clip=bbox)))
            else:
                if close:
                    await page.close()
                return None

            output = BytesIO()
            screenshot.save(output, 'PNG')
            screenshot.close()
            output.seek(0)
        else:
            output = await page.content()
        if close:
            await page.close()
        return output

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def kill_browser(self, ctx):
        """ Restart browser when you potato. """
        await self.bot.browser.close()
        await self.make_browser()
        e = self.base_embed
        e.description = ":gear: Restarting Browser."
        e.colour = discord.Colour.og_blurple()
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load into bot"""
    bot.add_cog(Browser(bot))
