"""Bot browser Session"""
from io import BytesIO
from typing import List, NoReturn

from pyppeteer import launch
from pyppeteer.browser import Browser
from pyppeteer.errors import TimeoutError


async def click(page, xpath: List[str]) -> NoReturn:
    """Click on all designated items"""
    for selector in xpath:
        try:
            await page.waitForSelector(selector, {"timeout": 1000})
        except TimeoutError:  # Nested exception.
            continue

        elements = await page.querySelectorAll(selector)
        for e in elements:
            await e.click()


async def screenshot(page, xpath: str) -> BytesIO | None:
    """Take a screenshot of the specified element"""
    await page.setViewport({"width": 1900, "height": 1100})
    elements = await page.xpath(xpath)

    if elements:
        bbox = await elements[0].boundingBox()
        bbox['height'] *= len(elements)
        return BytesIO(await page.screenshot(clip=bbox))
    else:
        return None


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

    return await launch(options=options)
