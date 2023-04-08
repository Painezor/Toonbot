"""Cog for fetching World of Warships Portal Articles from each region"""
from __future__ import annotations  # Cyclic Type hinting

import datetime
import typing
import asyncpg

import discord

from discord.ext import commands, tasks

from lxml import html
from playwright.async_api import TimeoutError as pw_TimeoutError

from ext.utils import view_utils
from ext import wows_api as api

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]

RSS_NEWS = "https://worldofwarships.%%/en/rss/news/"


async def save_article(bot: PBot, article: Article) -> None:
    """Store the article in the database for quicker retrieval in future"""
    sql = """INSERT INTO news_articles
                (title, description, partial, link, image, category, date,
                eu, na, sea)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (partial)
                DO UPDATE SET
                (title, description, link, image, category, date, eu, na, sea)
                = (EXCLUDED.title, EXCLUDED.description, EXCLUDED.link,
                EXCLUDED.image, EXCLUDED.category, EXCLUDED.date,
                EXCLUDED.eu, EXCLUDED.na, EXCLUDED.sea) """
    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            await connection.execute(
                sql,
                article.title,
                article.description,
                article.partial,
                article.link,
                article.image,
                article.category,
                article.date,
                article.eu,
                article.na,
                article.sea,
            )


class Article:
    """An Object representing a World of Warships News Article"""

    bot: PBot
    embed: discord.Embed
    view: discord.ui.View

    def __init__(self, bot: PBot, partial: str) -> None:
        self.bot = bot
        # Partial is the trailing part of the URL.
        self.partial: str = partial
        self.link: typing.Optional[str] = None

        # Stored Data
        self.title: typing.Optional[str] = None
        self.category: typing.Optional[str] = None
        self.description: typing.Optional[str] = None
        self.image: typing.Optional[str] = None

        # A flag for each region the article has been found in.
        self.eu: bool = False  # pylint: disable=C0103
        self.na: bool = False  # pylint: disable=C0103
        self.sea: bool = False  # pylint: disable=C0103

        self.date: typing.Optional[datetime.datetime] = None

    async def generate_embed(self) -> discord.Embed:
        """Handle dispatching of news article."""
        # CHeck if we need to do a full refresh on the article.
        if self.link is None:
            raise ValueError

        if None in [self.title, self.category, self.image, self.description]:
            page = await self.bot.browser.new_page()

            try:
                await page.goto(self.link)
                await page.wait_for_selector(".header__background")
                tree = html.fromstring(await page.content())
            except pw_TimeoutError:
                return await self.generate_embed()
            finally:
                await page.close()

            if not self.title:
                self.title = tree.xpath('.//div[@class="title"]/text()')[0]

            if not self.category:
                self.category = tree.xpath(".//nav/div/a/span/text()")[-1]

            if not self.description:
                xpath = './/span[@class="text__intro"]/text()'
                self.description = tree.xpath(xpath)[-1]

            xpath = './/div[@class="header__background"]/@style'
            try:
                self.image = "".join(tree.xpath(xpath)).split('"')[1]
            except IndexError:
                pass

        embed = discord.Embed(url=self.link, colour=0x064273, title=self.title)
        embed.description = self.description

        embed.set_author(name=self.category, url=self.link)
        embed.timestamp = self.date
        embed.set_footer(text="World of Warships Portal News")
        try:
            embed.set_image(url=self.image)
        except AttributeError:
            pass

        for region in api.Region:
            if getattr(self, region.db_key):
                embed.colour = region.colour
                break

        view = discord.ui.View()
        for region in api.Region:
            if getattr(self, region.db_key):
                dom = region.domain
                name = region.name
                url = f"https://worldofwarships.{dom}/en/{self.partial}"
                btn = discord.ui.Button(emoji=region.emote, url=url)
                btn.label = f"{name} article"
                view.add_item(btn)

        self.embed = embed
        self.view = view
        return self.embed


class NewsChannel:
    """An Object representing a NewsChannel"""

    def __init__(
        self,
        bot: PBot,
        record: asyncpg.Record,
        channel: discord.TextChannel,
    ) -> None:
        self.channel: discord.TextChannel = channel
        self.bot: PBot = bot

        # A bool for the tracking of each region
        self.eu: bool = record["eu"]  # pylint: disable=C0103
        self.na: bool = record["na"]  # pylint: disable=C0103
        self.sea: bool = record["sea"]

        # A list of partial links for articles to see if this
        # channel has already sent one.
        # Article, message_id
        self.sent_articles: dict[Article, discord.Message] = dict()

    async def dispatch(
        self, region: api.Region, article: Article
    ) -> typing.Optional[discord.Message]:
        """

        Check if the article has already been submitted to the channel,
        and is for a tracked region, then send it. If the article is already
        in our channel, edit the post with the link to the additional region

        """
        # Check if we want this news article for this channel.
        if not getattr(self, region.db_key):
            return

        if self.channel is None:
            return

        # Check if this article has already been posted for another region.
        message = self.sent_articles.get(article)
        if message is not None:
            await message.edit(embed=article.embed, view=article.view)
        else:
            message = await self.channel.send(
                embed=article.embed, view=article.view
            )

        self.sent_articles[article] = message
        return message


class NewsConfig(view_utils.BaseView):
    """News Tracker Config View"""

    def __init__(self, channel: NewsChannel) -> None:
        super().__init__()
        self.channel: NewsChannel = channel

        style = discord.ButtonStyle

        self.eu_news.style = style.green if channel.eu else style.red
        self.na_news.style = style.green if channel.na else style.red
        self.sea_news.style = style.green if channel.sea else style.red

    @discord.ui.button(label="EU", emoji=api.Region.EU.emote)
    async def eu_news(self, interaction: Interaction, btn) -> None:
        """Button for EU News Articles"""
        self.channel.eu = not self.channel.eu

        style = discord.ButtonStyle
        btn.style = style.green if self.channel.eu else style.red

        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.update_database(interaction, "eu", self.channel.eu)

    @discord.ui.button(label="NA", emoji=api.Region.NA.emote)
    async def na_news(self, interaction: Interaction, btn):
        """Button for NA News Articles"""
        self.channel.na = not self.channel.na

        style = discord.ButtonStyle
        btn.style = style.green if self.channel.na else style.red

        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.update_database(interaction, "na", self.channel.na)

    @discord.ui.button(label="SEA", emoji=api.Region.SEA.emote)
    async def sea_news(self, interaction: Interaction, btn):
        """Button for SEA news articles"""
        self.channel.sea = not self.channel.sea

        style = discord.ButtonStyle
        btn.style = style.green if self.channel.sea else style.red

        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.update_database(interaction, "sea", self.channel.sea)

    async def update_database(
        self, interaction: Interaction, field: str, new: bool
    ) -> None:
        """Apply changes to the database."""
        ch_id = self.channel.channel.id
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = f"""UPDATE news_trackers SET {field} = $1
                          WHERE channel_id = $2"""
                await connection.execute(sql, new, ch_id)

    def embed(self) -> discord.Embed:
        """Regenerate view and push to message"""
        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "World of Warships News Tracker config"
        embed.description = (
            "```yaml\nClick on the buttons below to enable "
            "tracking for a region.\n\nDuplicate articles from "
            "different regions will not be output multiple times"
            ".```"
        )
        return embed


async def news_ac(
    interaction: Interaction, cur: str
) -> list[discord.app_commands.Choice[str]]:
    """An Autocomplete that fetches from recent news articles"""
    choices = []
    cache = interaction.client.news_cache
    now = datetime.datetime.now()

    cur = cur.casefold()

    for i in sorted(cache, key=lambda x: x.date or now, reverse=True):
        if i.link is None:
            continue

        text = f"{i.title}: {i.description}".casefold()

        if cur not in text:
            continue

        name = text[:100]
        choices.append(discord.app_commands.Choice(name=name, value=i.link))

        if len(choices) == 25:
            break

    return choices


class NewsTracker(commands.Cog):
    """NewsTracker Commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        self.bot.news = self.news_loop.start()

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.news.cancel()

    @tasks.loop(minutes=1)
    async def news_loop(self) -> None:
        """Loop to get the latest EU news articles"""

        # If we already have parsed the articles once, flag it now.

        for region in api.Region:
            url = RSS_NEWS.replace("%%", region.domain)

            async with self.bot.session.get(url) as resp:
                data = bytes(await resp.text(), encoding="utf8")
                tree = html.fromstring(data)

            for i in tree.xpath(".//item"):
                link = "".join(i.xpath(".//guid/text()"))
                partial = link.rsplit("/en/", maxsplit=1)[-1]

                cache = self.bot.news_cache
                try:
                    article = next(i for i in cache if i.partial == partial)
                except StopIteration:
                    article = Article(self.bot, partial)
                    self.bot.news_cache.append(article)

                # If we have already dispatched this article for this region
                if getattr(article, region.db_key):
                    continue
                else:
                    setattr(article, region.db_key, True)

                # At this point, we either have a new article, or a new region
                # for an existing article. In which case, we check if we need
                # to extract additional data from the RSS.
                if article.link is None:
                    article.link = link  # Original Link

                if article.date is None:
                    date = "".join(i.xpath(".//pubdate/text()"))
                    if date:
                        fmt = "%a, %d %b %Y %H:%M:%S %Z"
                        article.date = datetime.datetime.strptime(date, fmt)
                    else:
                        article.date = discord.utils.utcnow()

                if not article.category:
                    category = "".join(i.xpath(".//category//text()"))
                    if category:
                        article.category = category

                if not article.description:
                    # Extract article description
                    desc = "".join(i.xpath(".//description/text()"))
                    # Sanitise it
                    desc = " ".join(desc.split()).replace(" ]]>", "")

                    if desc:
                        article.description = desc

                if article.title is None:
                    title = "".join(i.xpath(".//title/text()"))
                    if title:
                        article.title = title

                await article.generate_embed()

                # If we are simply populating, we are not interested.
                await save_article(self.bot, article)

                for channel in self.bot.news_channels:
                    try:
                        await channel.dispatch(region, article)
                    except discord.HTTPException:
                        continue

    @news_loop.before_loop
    async def update_cache(self) -> None:
        """Get the list of NewsTracker channels stored in the database"""
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM news_trackers"""
                channels = await connection.fetch(sql)
                sql = """SELECT * FROM news_articles"""
                articles = await connection.fetch(sql)

        partials = [i.partial for i in self.bot.news_cache]

        record: asyncpg.Record
        for record in articles:
            if record["partial"] in partials:
                continue
            article = Article(self.bot, partial=record["partial"])
            for k, value in record.items():
                if k == "partial":
                    continue

                setattr(article, k, value)
            self.bot.news_cache.append(article)

        # Append new ones.
        cached_ids = [x.channel.id for x in self.bot.news_channels]
        for record in channels:
            if record["channel_id"] in cached_ids:
                continue

            if (channel := self.bot.get_channel(record["channel_id"])) is None:
                continue

            channel = typing.cast(discord.TextChannel, channel)

            chan = NewsChannel(self.bot, record, channel)
            self.bot.news_channels.append(chan)

    @discord.app_commands.command()
    @discord.app_commands.describe(text="Search by article title")
    @discord.app_commands.autocomplete(text=news_ac)
    async def newspost(self, interaction: Interaction, text: str):
        """Search for a recent World of Warships news article"""
        try:
            article = next(i for i in self.bot.news_cache if i.link == text)
        except StopIteration:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 No article matching {text}"
            return await interaction.response.send_message(embed=embed)

        await article.generate_embed()
        send = interaction.response.send_message
        return await send(view=article.view, embed=article.embed)

    # Command for tracker management.
    @discord.app_commands.command()
    @discord.app_commands.guild_only()
    @discord.app_commands.default_permissions(manage_channels=True)
    @discord.app_commands.describe(channel="Select a channel to edit")
    async def news_tracker(
        self,
        interaction: Interaction,
        channel: typing.Optional[discord.TextChannel] = None,
    ) -> None:
        """Enable/Disable the World of Warships dev blog tracker
        in this channel."""

        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        try:
            chan = self.bot.news_channels
            target = next(i for i in chan if i.channel.id == channel.id)
        except StopIteration:
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = """INSERT INTO news_trackers (channel_id)
                             VALUES ($1) returning *"""
                    record = await connection.fetchrow(sql, channel.id)

            target = NewsChannel(self.bot, channel, record)
            self.bot.news_channels.append(target)

        view = NewsConfig(target)
        await interaction.response.send_message(view=view, embed=view.embed())
        view.message = await interaction.original_response()

    # Event Listeners for database cleanup.
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM news_trackers WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        chn = self.bot.news_channels
        self.bot.news_channels = [i for i in chn if i.channel.id != channel.id]


async def setup(bot: PBot) -> None:
    """Load the NewsTracker Cog into the bot."""
    await bot.add_cog(NewsTracker(bot))
