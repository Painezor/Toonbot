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


class ToggleButton(discord.ui.Button):
    """A Button to toggle the notifications settings."""

    view: NewsConfig

    def __init__(self, bot: PBot, region: api.Region, value: bool) -> None:
        self.value: bool = value
        self.region: api.Region = region
        self.bot: PBot = bot

        if value:
            colour = discord.ButtonStyle.blurple
            toggle = "On"
        else:
            colour = discord.ButtonStyle.gray
            toggle = "Off"

        label = f"{toggle} ({region.db_key})"

        super().__init__(label=label, emoji=region.emote, style=colour)

    async def callback(self, interaction: Interaction) -> None:
        """Set view value to button value"""

        await interaction.response.defer()
        new_value: bool = not self.value

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = f"""UPDATE news_trackers SET {self.label} = $1
                          WHERE channel_id = $2"""
                await connection.execute(sql, new_value, self.view.channel.id)

        toggle = "Enabled" if new_value else "Disabled"
        region = self.region.name
        ment = self.view.channel.mention
        txt = f"{toggle} {region} articles in {ment}"
        return await self.view.update(interaction, txt)


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
        channel: discord.TextChannel,
        eu: bool = False,  # pylint: disable=C0103
        na: bool = False,  # pylint: disable=C0103
        sea: bool = False,
    ) -> None:
        self.channel: discord.TextChannel = channel
        self.bot: PBot = bot

        # A bool for the tracking of each region
        self.eu: bool = eu  # pylint: disable=C0103
        self.na: bool = na  # pylint: disable=C0103
        self.sea: bool = sea

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

    async def send_config(self, interaction: Interaction) -> None:
        """Send the config view to the requesting user"""
        return await NewsConfig(self.channel).update(interaction)


# TODO: Decorator Buttons
class NewsConfig(view_utils.BaseView):
    """News Tracker Config View"""

    def __init__(
        self,
        channel: discord.TextChannel,
    ) -> None:
        super().__init__()
        self.channel: discord.TextChannel = channel

    async def update(
        self, interaction: Interaction, content: typing.Optional[str] = None
    ) -> None:
        """Regenerate view and push to message"""
        self.clear_items()

        sql = """SELECT * FROM news_trackers WHERE channel_id = $1"""
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                record = await connection.fetchrow(sql, self.channel.id)

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "World of Warships News Tracker config"
        embed.description = (
            "```yaml\nClick on the buttons below to enable "
            "tracking for a region.\n\nDuplicate articles from"
            " different regions will not be output multiple times"
            ".```"
        )

        for k, value in sorted(record.items()):
            if k == "channel_id":
                continue

            if k == "cis":
                continue

            region = next(i for i in api.Region if k == i.db_key)

            reg = f"{region.emote} {region.name}"
            if value:  # Bool: True/False
                embed.description += f"\n✅ {reg} News is tracked.**"
            else:
                embed.description += f"\n❌ {reg} News is not tracked."

            self.add_item(
                ToggleButton(interaction.client, region=region, value=value)
            )

        # TODO: super.previous.callback()
        self.add_page_buttons()

        edit = interaction.response.edit_message
        await edit(content=content, embed=embed, view=self)


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
            else:
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

            # TODO: Move this to init of newschannel
            chan = NewsChannel(
                self.bot,
                channel,
                record["eu"],
                record["na"],
                record["sea"],
            )
            self.bot.news_channels.append(chan)

    @discord.app_commands.command()
    @discord.app_commands.describe(text="Search by article title")
    @discord.app_commands.autocomplete(text=news_ac)
    async def newspost(self, interaction: Interaction, text: str):
        """Search for a recent World of Warships news article"""
        try:
            article = next(i for i in self.bot.news_cache if i.link == text)
        except StopIteration:
            embed = discord.Embed()
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

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        try:
            chan = self.bot.news_channels
            target = next(i for i in chan if i.channel.id == channel.id)
        except StopIteration:
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = """INSERT INTO news_trackers (channel_id)
                             VALUES ($1)"""
                    await connection.execute(sql, channel.id)

            target = NewsChannel(self.bot, channel=channel)
            self.bot.news_channels.append(target)
        return await target.send_config(interaction)

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
