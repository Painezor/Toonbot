"""Bot browser Session"""
from io import BytesIO

import aiohttp
import pyppeteer
from PIL import Image
from discord import Embed, Colour, app_commands
from discord.ext import commands
from pyppeteer.browser import Browser
from pyppeteer.errors import TimeoutError as _TimeoutError


# TODO: Figure out how to overload this.
async def fetch(page, url, xpath, screenshot=False, max_retry=3, **kwargs) -> str | BytesIO | None:
    """Fetch a webpage's source code or an image"""
    assert url.startswith("http"), f"BROWSER - FETCH: {url} does not appear to be a valid url."

    close = False
    if page.isClosed():
        # Replace closed pages.
        page = await page.browser.newPage()
        close = True

    for _ in range(max_retry):
        try:
            await page.goto(url)
            break
        except _TimeoutError:
            print(f"Fetch Page timed out trying to access {url}")
            return None
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
        elements = await page.querySelectorAll(x)
        for e in elements:
            await e.click()

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


class BrowserCog(commands.Cog, name="Browser"):
    """(Re)-Initialise an aiohttp ClientSession"""

    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_load(self):
        """When the cog loads..."""
        await self.spawn_session()
        await self.make_browser()

    async def make_browser(self) -> Browser:
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
        self.bot.browser.fetch = fetch
        self.bot.browser.bot = self.bot
        return self.bot.browser

    @app_commands.command()
    @app_commands.guilds(250252535699341312)
    async def kill_browser(self, interaction):
        """ Restart browser when you potato."""
        await interaction.response.defer(thinking=True)
        if interaction.user.id != interaction.client.owner_id:
            return await interaction.client.error(interaction, "You do not own this bot.")
        if interaction.client.browser is not None:
            await interaction.client.browser.close()
        await self.make_browser()
        e = Embed(description=":gear: Restarting Browser.", colour=Colour.og_blurple())
        await interaction.client.reply(interaction, embed=e)

    async def spawn_session(self):
        """Create a ClientSession object and attach to the bot."""
        if self.bot.session is not None:
            await self.bot.session.close()

        self.bot.session = aiohttp.ClientSession(loop=self.bot.loop, connector=aiohttp.TCPConnector(ssl=False))


async def setup(bot):
    """Load into bot"""
    await bot.add_cog(BrowserCog(bot))
