"""Create and manipulate an instance of a headerless pyppeteer browser"""
from io import BytesIO
from typing import Union

import pyppeteer
from PIL import Image
from pyppeteer import page as pg
from pyppeteer.errors import TimeoutError as _TimeoutError


async def make_browser(bot):
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

    bot.browser = await pyppeteer.launch(options=options)


async def fetch(page, url, xpath, clicks=None, delete=None, screenshot=False, max_retry=3, close=False) \
        -> (Union[str, BytesIO, None], pg.Page):
    """Fetch a webpage's soruce code or an image"""
    deletes = [] if delete is None else delete
    clicks = [] if clicks is None else clicks

    assert url.startswith("http"), f"BROWSER - FETCH: {url} does not appear to be a valid url."

    if page.isClosed():
        # Replace closed pages.
        page = await page.browser.newPage()
        close = True

    for _ in range(max_retry):
        try:
            await page.goto(url)
        except _TimeoutError:
            print(f"Fetch Page timed out trying to access {url}")
        else:
            break
    else:
        if close:
            await page.close()
        return None

    try:
        await page.waitForXPath(xpath, {"timeout": 5000})
    except _TimeoutError:
        pass

    for x in deletes:
        elements = await page.xpath(x)
        for element in elements:
            try:
                await page.evaluate("""(element) => element.parentNode.removeChild(element)""", element)
            except pyppeteer.errors.ElementHandleError:  # If no exist.
                continue

    for x in clicks:
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
        if close:
            await page.close()

        return output
    else:
        if close:
            await page.close()
        return await page.content()
