"""Testing Cog for new commands."""
from datetime import datetime
from typing import TYPE_CHECKING, Union

from discord import Embed
from discord.app_commands import command, guilds
from discord.ext import commands
from lxml import html

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.football import NewsItem
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot

    @command()
    @guilds(250252535699341312)
    async def get_news(self, interaction):
        """Get a list of news articles related to a team"""
        if interaction.author.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")
        page = await self.bot.browser.newPage()
        try:
            await page.goto("https://www.flashscore.com/team/arsenal/hA1Zm19f" + "/news")
            await page.waitForXPath('.//div[@class="matchBox"]', {"timeout": 5000})
            tree = html.fromstring(await page.content())
        except TimeoutError:
            return []

        rows = tree.xpath('.//div[@id="tab-match-newsfeed"]')
        items = []
        for i in rows:
            title = "".join(i.xpath('.//div[@class="rssNews__title"]/text()'))
            print("Title", title)
            image = "".join(i.xpath('.//img/@src'))
            print("Image", image)
            link = "http://www.flashscore.com" + "".join(i.xpath('.//a[@class="rssNews__titleAndPerex"]/@href'))
            print("Link", link)
            blurb = "".join(i.xpath('.//div[@class="rssNews__perex"]/text()'))
            print("Blurb", blurb)
            provider = "".join(i.xpath('.//div[@class="rssNews__provider"]/text()')).split(',')
            print("Provider", provider)
            if provider:
                time = datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
                print(time)
                source = provider[-1].strip()
                print(source)
                items.append(NewsItem(title, link, blurb, source, time, image_url=image))
            else:
                items.append(NewsItem(title, link, blurb, "", datetime.now(), image_url=image))
        e = Embed()
        embeds = rows_to_embeds(e, [i.fmt for i in items])
        v = Paginator(self.bot, interaction, embeds)
        await v.update()


async def setup(bot: Union['Bot', 'PBot']):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
