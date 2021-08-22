"""Create and manipulate an instance of a headerless pyppeteer browser"""
from io import BytesIO
from typing import Union

import pyppeteer
from PIL import Image


async def make_browser(bot):
    """Spawn an instance of Pyppeteer"""
    # # options = {"args": [
    # #     '--no-sandbox',
    # #     '--disable-setuid-sandbox',
    # #     '--disable-infobars',
    # #     '--single-process',
    # #     '--no-zygote',
    # #     '--no-first-run',
    # #     '--window-position=0,0',
    # #     '--ignore-certificate-errors',
    # #     '--ignore-certificate-errors-skip-list',
    # #     '--disable-dev-shm-usage',
    # #     '--disable-accelerated-2d-canvas',
    # #     '--disable-gpu',
    # #     '--hide-scrollbars',
    # #     '--disable-notifications',
    # #     '--disable-background-timer-throttling',
    # #     '--disable-backgrounding-occluded-windows',
    # #     '--disable-breakpad',
    # #     '--disable-component-extensions-with-background-pages',
    # #     '--disable-extensions',
    # #     '--disable-features=TranslateUI,BlinkGenPropertyTrees',
    # #     '--disable-ipc-flooding-protection',
    # #     '--disable-renderer-backgrounding',
    # #     '--enable-features=NetworkService,NetworkServiceInProcess',
    # #     '--force-color-profile=srgb',
    # #     '--metrics-recording-only',
    # #     '--mute-audio'
    # # ]}
    #
    # bot.browser = await pyppeteer.launch(options=options)
    bot.browser = await pyppeteer.launch()


async def fetch(page, url, xpath, clicks=None, delete=None, screenshot=False, debug=False) -> Union[str, BytesIO, None]:
    """Fetch a webpage's soruce code or an image"""
    deletes = [] if delete is None else delete
    clicks = [] if clicks is None else clicks

    assert url.startswith("http"), f"{url} does not appear to be a valid url."
    await page.goto(url)  # DEBUG, old code: (url, {'waitUntil': 'networkidle0'})

    src = await page.content()

    for x in deletes:
        elements = await page.xpath(x)
        for element in elements:
            await page.evaluate("""(element) => element.parentNode.removeChild(element)""", element)
    
    for x in clicks:
        element = await page.querySelector(x)
        if element is not None:
            await element.click()
    
    # Debug
    if debug:
        im = Image.open(BytesIO(await page.screenshot()))
        output = BytesIO()
        im.save(output, 'PNG')
        im.close()
        output.seek(0)
        return output
    
    if screenshot:
        await page.setViewport({"width": 1900, "height": 1100})
        elements = await page.xpath(xpath)
        if elements:
            bbox = await elements[0].boundingBox()
            bbox['height'] *= len(elements)
            screenshot = Image.open(BytesIO(await page.screenshot(clip=bbox)))
        else:
            return None

        output = BytesIO()
        screenshot.save(output, 'PNG')
        screenshot.close()
        output.seek(0)
        return output
    else:
        return src
