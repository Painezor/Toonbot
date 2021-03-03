from io import BytesIO
from PIL import Image


async def fetch(page, url, xpath, clicks=None, deletes=None, screenshot=False):
    deletes = [] if deletes is None else deletes
    clicks = [] if clicks is None else clicks
    
    assert url.startswith("http"), f"{url} does not appear to be a valid url."
    
    await page.goto(url, {'waitUntil': 'networkidle0'})
    
    for x in deletes:
        elements = await page.xpath(x)
        for element in elements:
            await page.evaluate("""(element) => element.parentNode.removeChild(element)""", element)
    
    for x in clicks:
        elements = await page.xpath(x)
        for target in elements:
            await page.click(target)
    
    if screenshot:
        element = await page.xpath(xpath)
        try:
            element = element[0]
        except IndexError:
            print(f"Pypeteer - screenshot - Did not find '{xpath} on {url}, using fallback.")
            raw_screenshot = await page.screenshot()
        else:
            raw_screenshot = await element.screenshot()
        
        im = Image.open(BytesIO(raw_screenshot))
        output = BytesIO()
        im.save(output, 'PNG')
        im.close()
        output.seek(0)
        
        return output
