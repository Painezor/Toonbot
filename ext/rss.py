"""Cog for outputting various RSS based information"""
import datetime
from re import sub
from typing import TYPE_CHECKING

from discord import Embed, Interaction
from discord.app_commands import command, describe, guilds
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View
from lxml import html
from pyppeteer.errors import TimeoutError

if TYPE_CHECKING:
    from core import Bot

EU_NEWS_CHANNEL = 849418195021856768
DEV_BLOG_CHANNEL = 849412392651587614


# TODO: Dev Blog Search
# TODO: Dev Blog Browser View


class DevBlogView(View):
    """Browse Dev Blogs"""


class RSS(Cog):
    """RSS Commands"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        self.bot.eu_news = self.eu_news.start()
        self.bot.dev_blog = self.blog_loop.start()
        self.bot.blog_cache = []
        self.bot.news_cached = False
        self.bot.dev_blog_cached = False

    async def cog_load(self):
        """Do this on Cog Load"""
        await self.get_blogs()

    async def cog_unload(self):
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.eu_news.cancel()
        self.bot.dev_blog.cancel()

    async def get_blogs(self):
        """Get a list of old dev blogs stored in DB"""

    async def parse_all_blogs(self):
        """Loop through all dev blogs to fetch new data"""
        pass

    async def get_inner_text(self, blog_id=296):  # 296 debug
        """Get the inner text of a specific dev blog"""
        async with self.bot.session.get(f'https://blog.worldofwarships.com/blog/{blog_id}') as resp:
            src = await resp.text()

        tree = html.fromstring(src)

        inner = tree.xpath('.//div[@class="article__content"]')[0].inner_html
        print(inner)

    @command()
    @describe(number="Enter Dev Blog Number")
    @guilds(742372603813036082)
    async def dev_blog(self, interaction: Interaction, number: int):
        """Fetch a World of Warships dev blog, either provide ID number or leave blank to get latest."""
        if number:
            link = f"https://blog.worldofwarships.com/blog/{number}"
        else:
            async with interaction.client.session.get('https://blog.worldofwarships.com/rss-en.xml') as resp:
                tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

            articles = tree.xpath('.//item')
            for i in articles:
                link = ''.join(i.xpath('.//guid/text()'))
                if link:
                    break
            else:
                return await self.bot.error(interaction, "Couldn't find any dev blogs.")

        e = await self.parse(link)
        await self.bot.reply(interaction, embed=e)

    async def dispatch_eu_news(self, link: str, date=None, title=None, category=None, desc=None):
        """Handle dispatching of news article."""
        # Fetch Image from JS Heavy news page because it looks pretty.
        page = await self.bot.browser.newPage()

        try:
            await page.goto(link)
            await page.waitForXPath(".//div[@class='header__background']", {"timeout": 5000})
            tree = html.fromstring(await page.content())
        except TimeoutError:
            return
        finally:
            await page.close()

        e: Embed = Embed(url=link, colour=0x064273)
        e.title = tree.xpath('.//div[@class="title"]/text()')[0] if title is None else title
        category = "EU News: " + tree.xpath('.//nav/div/a/span/text()')[-1] if category is None else category
        date = datetime.datetime.now() if date is None else datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z")
        e.timestamp = date

        e.set_author(name=category, url=link)
        e.description = desc
        e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
        e.set_footer(text="World of Warships EU Portal News")

        try:
            background_image = ''.join(tree.xpath('.//div[@class="header__background"]/@style')).split('"')[1]
        except IndexError:
            pass
        else:
            e.set_image(url=background_image)

        ch = self.bot.get_channel(EU_NEWS_CHANNEL)

        await ch.send(embed=e)

    async def parse(self, url: str, store_only=False):
        """Get Embed from the Dev Blog page"""
        async with self.bot.session.get(url) as resp:
            tree = html.fromstring(await resp.text())

        article_html = tree.xpath('.//div[@class="article__content"]')[0]

        e: Embed = Embed(colour=0x00FFFF, title=''.join(tree.xpath('.//h2[@class="article__title"]/text()')), url=url)
        e.set_author(name="World of Warships Development Blog", url="https://blog.worldofwarships.com/")
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
        e.description = ""
        main_image = None
        output = ""

        def fmt(node):
            """Format the passed node"""
            if n.tag == "img" and main_image is None:
                e.set_image(url=n.attrib['src'])

            try:
                txt = node.text if node.text.strip() else ""
                txt = sub(r'\s{2,}', ' ', txt)
            except AttributeError:
                txt = ""

            if not txt:
                out = ""
            else:
                match node.tag:
                    case "p" | "div" | "ul":
                        out = txt
                    case "em":
                        out = f"*{txt}*"
                    case "strong" | "h3" | "h4":
                        out = f" **{txt}**"
                        try:
                            node.parent.text
                        except AttributeError:
                            out += "\n"
                    case "span":
                        out = txt
                        if 'class' in node.attrib:
                            if "ship" in node.attrib['class']:
                                try:
                                    out = f"`{txt}`" if node.parent.text else f"**{txt}**\n"
                                except AttributeError:
                                    out = f"**{txt}**\n"
                    case "li":
                        bullet_type = "∟○" if node.getparent().getparent().tag in ("ul", "li") else "•"
                        out = f"{bullet_type} {txt}"
                    case "a":
                        out = f"[{txt}]({node.attrib['href']})"
                    case _:
                        print(f"Unhandled node tag found: {node.tag} | {txt} | {tail}")
                        out = txt

            try:
                tl = node.tail if node.tail.strip() else ""
                tl = sub(r'\s{2,}', ' ', tl)
            except AttributeError:
                tl = ""
            out += tl

            return out

        for n in article_html.iterchildren():  # Top Level Children Only.
            try:
                text = n.text if n.text.strip() else ""
                text = sub(r'\s{2,}', ' ', text)
            except AttributeError:
                text = ""

            try:
                tail = n.tail if n.tail.strip() else ""
                tail = sub(r'\s{2,}', ' ', tail)
            except AttributeError:
                tail = ""

            if text or tail:
                output += f"{fmt(n)}"

            for child in n.iterdescendants():
                # Force Linebreak on new section.
                try:
                    child_text = child.text if child.text.strip() else ""
                    child_text = sub(r'\s{2,}', ' ', child_text)
                except AttributeError:
                    child_text = ""

                try:
                    child_tail = child.tail if child.tail.strip() else ""
                    child_tail = sub(r'\s{2,}', ' ', child_tail)
                except AttributeError:
                    child_tail = ""

                if child_text or child_tail:
                    output += "\n" if child.tag == "li" else ""
                    output += f"{fmt(child)}"
                    if child.tag == "li" and child.getnext() is None and not child.getchildren():
                        output += "\n\n"  # Extra line after lists.
                    output += "\n\n" if child.tag == "p" else ""

            if text or tail:
                if n.tag == "p":
                    output += "\n\n" if n.itertext() else ""
                output += "\n" if n.tag == "li" else ""

        if len(output) > 4000:
            trunc = f"...\n[Read Full Article]({url})"
            e.description = output.ljust(4000)[:4000 - len(trunc)] + trunc
        else:
            e.description = output
        return e

    @command()
    @describe(link="Enter the news article link to be parsed")
    @guilds(742372603813036082)
    async def news(self, interaction: Interaction, link: str) -> None:
        """Manual refresh of missed news articles."""
        if interaction.user.id != self.bot.owner_id:
            return await interaction.client.error(interaction, "You do not own this bot.")
        await self.dispatch_eu_news(link)
        await self.bot.reply(interaction, content="Sent.", delete_after=1)

    @loop(seconds=60)
    async def eu_news(self):
        """Loop to get the latest EU news articles"""
        if self.bot.session is None:
            return

        async with self.bot.session.get('https://worldofwarships.eu/en/rss/news/') as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

        articles = tree.xpath('.//item')
        for i in articles:
            link = ''.join(i.xpath('.//guid/text()'))
            if link in self.bot.blog_cache:
                continue

            self.bot.blog_cache.append(link)
            if not self.bot.news_cached:
                continue  # Skip on population

            date = ''.join(i.xpath('.//pubdate/text()'))
            category = "EU News: " + ''.join(i.xpath('.//category//text()'))
            desc = " ".join(''.join(i.xpath('.//description/text()')).split()).replace(' ]]>', '')
            title = ''.join(i.xpath('.//title/text()'))
            await self.dispatch_eu_news(link, date=date, title=title, desc=desc, category=category)

        if articles:
            self.bot.news_cached = True

    @loop(seconds=60)
    async def blog_loop(self):
        """Loop to get the latest dev blog articles"""
        if self.bot.session is None:
            return

        async with self.bot.session.get('https://blog.worldofwarships.com/rss-en.xml') as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

        articles = tree.xpath('.//item')
        for i in articles:
            link = ''.join(i.xpath('.//guid/text()'))

            try:
                if link in self.bot.blog_cache:
                    continue
            except AttributeError:
                self.bot.blog_cache = []

            self.bot.blog_cache.append(link)

            if ".ru" in link:
                continue

            if not self.bot.dev_blog_cached:
                continue  # Skip on population

            e = await self.parse(link)

            ch = self.bot.get_channel(DEV_BLOG_CHANNEL)
            await ch.send(embed=e)
        self.bot.dev_blog_cached = True


async def setup(bot: 'Bot'):
    """Load the rss Cog into the bot."""
    await bot.add_cog(RSS(bot))
