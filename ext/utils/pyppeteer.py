from io import BytesIO

from PIL import Image


async def fetch(page, url, xpath, clicks=None, deletes=None, screenshot=False, debug=False):
    deletes = [] if deletes is None else deletes
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
        element = await page.xpath(xpath)
        try:
            element = element[0]
        except IndexError:
            raw_screenshot = await page.screenshot()
        else:
            raw_screenshot = await element.screenshot()
        
        im = Image.open(BytesIO(raw_screenshot))
        output = BytesIO()
        im.save(output, 'PNG')
        im.close()
        output.seek(0)
        
        return output
    else:
        return src
