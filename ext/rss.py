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
            title = "".join(i.xpath('.//title/text()'))
            link = "".join(i.xpath('.//guid/text()'))
            date = "".join(i.xpath('.//pubdate/text()'))
            date = datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z")

            if link in self.cache:
                continue

            self.cache.append(link)

            if not self.news_cached:
                continue  # Skip on population

            e = discord.Embed()

            news_title = "EU News: " "".join(i.xpath('.//category//text()'))

            e.set_author(name=news_title, url="".join(i.xpath('.//category/@domain')))
            e.colour = 0x064273
            e.title = title
            e.url = link
            e.description = " ".join("".join(i.xpath('.//description/text()')).split()).replace(' ]]>', '')
            e.timestamp = date
            e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
            e.set_footer(text="World of Warships EU Portal News")

            # Fetch Image from JS Heavy news page because it looks pretty.
            page = await self.bot.browser.newPage()
            try:
                await browser.fetch(page, link, xpath=".//div[@class='header__background']")
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

            try:
                background_image = "".join(tree.xpath('.//div[@class="header__background"]/@style')).split('"')[1]
            except IndexError:
                pass
            else:
                e.set_image(url=background_image)

            ch = self.bot.get_channel(EU_NEWS_CHANNEL)

            await ch.send(embed=e)

        self.news_cached = True

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
            if node.tag == "p":
                if node.text is None:
                    continue

                section = node.text.strip() + "\n\n"
            elif node.tag == "div":
                continue
            elif node.tag == "em":
                section = "*" + node.text + "*"
            elif node.tag == "strong":
                if node.text is None:
                    continue
                elif node.text.strip() == ":":
                    section = "**:**\n"
                elif node.getparent().text is None:
                    section = f"**{node.text}**\n"
                else:
                    section = f"**{node.text}** "
            elif node.tag == "span":
                if "ship" in node.attrib['class']:
                    section = "**" + node.text + "** "
                else:
                    section = ""
            elif node.tag == "ul":
                if not node.text:
                    continue
                section = node.text.strip()

            elif node.tag == "li":
                if node.text is None:
                    continue
                bullet_type = "∟○" if node.getparent().getparent().tag in ("ul", "li") else "•"
                section = f"{bullet_type} {node.text.strip()}\n"

            elif node.tag == "img":
                if main_image is None:
                    src = str(node.attrib['src'])

                    if not src.startswith(('http:', 'https:')):
                        main_image = "http:" + node.attrib['src']
                    else:
                        main_image = node.attrib['src']
                    e.set_image(url=main_image)
                section = ""
            else:
                if node.text:
                    print("No tag found:", node.text)
                else:
                    print(node.__dict__)
                section = ""

            if "Announced adjustments and features" in section:
                continue

            # Append
            if len(desc) + len(section) < 2048:
                desc += section
            else:
                trunc = f"...\n[Read Full Article]({url})"
                desc = desc.ljust(2048)[:2000 - len(trunc)] + trunc
                break

        print(len(desc))

        e.description = desc
        return e

    @commands.command()
    @commands.is_owner()
    async def rss(self, ctx):
        """Test dev blog output"""
        async with self.bot.session.get('https://blog.worldofwarships.com/rss-en.xml') as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

        articles = tree.xpath('.//item')
        link = ""
        for i in articles:
            link = "".join(i.xpath('.//guid/text()'))
            if link:
                break

        e = await self.parse(link)
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the rss Cog into the bot."""
    bot.add_cog(RSS(bot))
