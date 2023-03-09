import aiohttp
import asyncio
from lxml import html


URL = "https://www.flashscore.com/match/KxPM2Gzt/#/match-summary"


async def fetch():
    print("Hello World!")
    session = aiohttp.ClientSession()
    await asyncio.sleep(5)
    async with session.get(URL) as resp:
        tree = html.fromstring(await resp.text())

    print(tree.xpath(".//div[@class=duelParticipant]"))

    await asyncio.sleep(60)


# Handle Teams
loop = asyncio.run(fetch())
