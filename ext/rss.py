"""Cog for outputting various RSS based information"""
import datetime

import discord
from discord.ext import commands, tasks
from lxml import html

from ext.utils import browser

EU_NEWS_CHANNEL = 849418195021856768
DEV_BLOG_CHANNEL = 849412392651587614


class RSS(commands.Cog):
    """RSS Commands"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "📣"
        self.bot.eu_news = self.eu_news.start()
        self.bot.dev_blog = self.dev_blog.start()
        self.cache = []
        self.news_cached = False
        self.dev_blog_cached = False

    def cog_unload(self):
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.eu_news.cancel()
        self.bot.dev_blog.cancel()

    @tasks.loop(seconds=60)
    async def eu_news(self):
        """Loop to get the latest EU news articles"""
        async with self.bot.session.get('https://worldofwarships.eu/en/rss/news/') as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

        articles = tree.xpath('.//item')
        for i in articles:
            link = "".join(i.xpath('.//guid/text()'))
            if link in self.cache:
                continue

            self.cache.append(link)
            if not self.news_cached:
                continue  # Skip on population

            date = "".join(i.xpath('.//pubdate/text()'))
            category = "EU News: " + "".join(i.xpath('.//category//text()'))
            desc = " ".join("".join(i.xpath('.//description/text()')).split()).replace(' ]]>', '')
            title = "".join(i.xpath('.//title/text()'))
            await self.dispatch_eu_news(link, date=date, title=title, desc=desc, category=category)
        self.news_cached = True

    async def dispatch_eu_news(self, link, date=None, title=None, category=None, desc=None):
        """Handle dispatching of news article."""
        # Fetch Image from JS Heavy news page because it looks pretty.
        page = await self.bot.browser.newPage()
        try:
            src = await browser.fetch(page, link, xpath=".//div[@class='header__background']")
            tree = html.fromstring(src)
        finally:
            await page.close()

        e = discord.Embed(url=link, colour=0x064273)
        e.title = tree.xpath('.//div[@class="title"]/text()')[0] if title is None else title
        category = "EU News: " + tree.xpath('.//nav/div/a/span/text()')[-1] if category is None else category
        date = datetime.datetime.now() if date is None else datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z")
        e.timestamp = date

        e.set_author(name=category, url=link)
        e.description = desc
        e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
        e.set_footer(text="World of Warships EU Portal News")

        try:
            background_image = "".join(tree.xpath('.//div[@class="header__background"]/@style')).split('"')[1]
        except IndexError:
            pass
        else:
            e.set_image(url=background_image)

        ch = self.bot.get_channel(EU_NEWS_CHANNEL)

        await ch.send(embed=e)

    @tasks.loop(seconds=60)
    async def dev_blog(self):
        """Loop to get the latest dev blog articles"""
        async with self.bot.session.get('https://blog.worldofwarships.com/rss-en.xml') as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

        articles = tree.xpath('.//item')
        for i in articles:
            link = "".join(i.xpath('.//guid/text()'))

            if link in self.cache:
                continue

            self.cache.append(link)

            if not self.dev_blog_cached:
                continue  # Skip on population

            e = await self.parse(link)

            ch = self.bot.get_channel(DEV_BLOG_CHANNEL)
            await ch.send(embed=e)
            return

        self.dev_blog_cached = True

    async def parse(self, url):
        """Get Embed from Devblog page"""
        async with self.bot.session.get(url) as resp:
            tree = html.fromstring(await resp.text())

        article_html = tree.xpath('.//div[@class="article__content"]')[0]

        title = "".join(tree.xpath('.//h2[@class="article__title"]/text()'))

        e = discord.Embed()
        e.colour = 0x00FFFF
        e.set_author(name="World of Warships Development Blog", url="https://blog.worldofwarships.com/")
        e.title = title
        e.url = url
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
        main_image = None

        desc = ""
        for node in article_html.iterdescendants():

            if node.tag == "img":
                if main_image is None:
                    src = str(node.attrib['src'])

                    if not src.startswith(('http:', 'https:')):
                        main_image = "http:" + node.attrib['src']
                    else:
                        main_image = node.attrib['src']
                    e.set_image(url=main_image)
                section = ""
            else:
                if node.text is None or not node.text:
                    continue

                text = node.text.strip()

                if node.tag == "p":
                    section = f"{text}\n"
                elif node.tag == "em":
                    section = f"*{text}*"
                elif node.tag == "strong":
                    section = f"**{text}**\n" if node.getparent().text is None else f"**{text}** "
                elif node.tag == "span":
                    section = f"**{text}** " if "ship" in node.attrib['class'] else text
                elif node.tag == "ul":
                    section = f"\n{text}"
                elif node.tag == "li":
                    bullet_type = "∟○" if node.getparent().getparent().tag in ("ul", "li") else "•"
                    section = f"\n{bullet_type} {text}"
                else:
                    print(f"No tag found: {text}" if not text else node.__dict__)
                    section = text

            # Append
            if len(desc) + len(section) < 2048:
                desc += section
            else:
                trunc = f"...\n[Read Full Article]({url})"
                desc = desc.ljust(2048)[:2000 - len(trunc)] + trunc
                break

        e.description = desc
        return e

    @commands.command()
    @commands.is_owner()
    async def rss(self, ctx, link=None):
        """Test dev blog output"""
        if link is None:
            async with self.bot.session.get('https://blog.worldofwarships.com/rss-en.xml') as resp:
                tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

            articles = tree.xpath('.//item')
            link = ""
            for i in articles:
                link = "".join(i.xpath('.//guid/text()'))
                if link:
                    break
        elif link.isdigit():
            link = f"https://blog.worldofwarships.com/blog/{link}"

        e = await self.parse(link)
        await self.bot.reply(ctx, embed=e)

    @commands.command()
    @commands.is_owner()
    async def news(self, ctx, link):
        """Manual refresh of missed news articles."""
        await self.dispatch_eu_news(link)
        await self.bot.reply(ctx, "Sent.", delete_after=1)


def setup(bot):
    """Load the rss Cog into the bot."""
    bot.add_cog(RSS(bot))
