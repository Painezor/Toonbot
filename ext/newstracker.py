"""Cog for fetching World of Warships Portal Articles from each region"""
# TODO: Add DB Table for news articles (url, image, title, text)
# TODO: Search News
from __future__ import annotations  # Cyclic Type hinting

import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Dict

from discord import Embed, Interaction, Message, Colour, TextChannel, Guild, ButtonStyle
from discord.app_commands import command, describe, guild_only, default_permissions
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View, Button
from lxml import html

if TYPE_CHECKING:
    from painezBot import PBot


class Region(Enum):
    """A Generic object representing a region"""

    def __new__(cls, *args, **kwargs):
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, db_key: str, url: str, emote: str, colour: Colour) -> None:
        self.db_key: str = db_key
        self.domain: str = url
        self.emote: str = emote
        self.colour: Colour = colour

    #     db_key  | domain                       | emote                             | colour
    EU = ('eu', 'https://worldofwarships.eu/', "<:painezBot:928654001279471697>", 0xffffff)
    NA = ('na', 'https://worldofwarships.com/', "<:Bonk:746376831296471060>", 0xff0000)
    SEA = ('sea', 'https://worldofwarships.asia/', "<:painezRaid:928653997680754739>", 0x00ff00)
    CIS = ('cis', 'https://worldofwarships.ru/', "<:Button:826154019654991882>", 0x0000ff)


class ToggleButton(Button):
    """A Button to toggle the notifications settings."""
    view: NewsConfig

    def __init__(self, bot: 'PBot', region: Region, value: bool) -> None:
        self.value: bool = value
        self.region: Region = region
        self.bot: PBot = bot

        colour = ButtonStyle.blurple if value else ButtonStyle.gray
        state: str = "On" if value else "Off"
        title: str = region.db_key.upper()
        super().__init__(label=f"{title} ({state})", emoji=region.emote, style=colour)

    async def callback(self, interaction: Interaction) -> Message:
        """Set view value to button value"""
        await interaction.response.defer()
        new_value: bool = False if self.value else True

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = f"""UPDATE news_trackers SET {self.region.db_key} = $1 WHERE channel_id = $2"""
                await connection.execute(q, new_value, self.view.channel.id)
        finally:
            await self.bot.db.release(connection)

        on = "Enabled" if new_value else "Disabled"
        return await self.view.update(f'{on} tracking of articles for {self.label} in {self.view.channel.mention}')


class Article:
    """An Object representing a World of Warships News Article"""
    __slots__ = {'date': "The original publication date of the article",
                 'category': "The Category of the article",
                 'description': "The article's written description",
                 'title': "The title of the article",
                 'image': "A link to the background image of the article",
                 'embed': "The generated embed for the article"
                 }

    bot: PBot
    link: str

    # Stored Data
    title: str
    category: str
    description: str
    image: str
    date: datetime.datetime

    # Generated
    embed: Embed
    view: View

    # A flag for each region the article has been found in.
    eu: bool = False
    na: bool = False
    cis: bool = False
    sea: bool = False

    def __init__(self, bot: 'PBot', partial: str):
        self.bot = bot
        # Partial is the trailing part of the URL.
        self.partial: str = partial

    async def generate_embed(self) -> Embed:
        """Handle dispatching of news article."""
        # Fetch Image from JS Heavy news page because it looks pretty.

        # CHeck if we need to do a full refresh on the article.
        try:
            assert hasattr(self, 'title')
            assert hasattr(self, 'category')
            assert hasattr(self, 'image')
            assert hasattr(self, 'description')
        except AssertionError:
            page = await self.bot.browser.newPage()

            try:
                await page.goto(self.link)
                await page.waitForXPath(".//div[@class='header__background']", {"timeout": 5000})
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

            try:
                self.title
            except AttributeError:
                self.title = tree.xpath('.//div[@class="title"]/text()')[0]

            try:
                self.category
            except AttributeError:
                self.category = tree.xpath('.//nav/div/a/span/text()')[-1]

            try:
                self.description
            except AttributeError:
                self.description = tree.xpath('.//span[@class="text__intro"]/text()')[-1]

            try:
                self.image = ''.join(tree.xpath('.//div[@class="header__background"]/@style')).split('"')[1]
            except IndexError:
                pass

        e: Embed = Embed(url=self.link, colour=0x064273, title=self.title, description=self.description)
        e.set_author(name=self.category, url=self.link)
        e.timestamp = self.date
        e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
        e.set_footer(text="World of Warships Portal News")
        try:
            e.set_image(url=self.image)
        except AttributeError:
            pass

        v = View()
        for region in Region:
            if getattr(self, region.db_key):
                v.add_item(Button(url=f"{region.domain}en/{self.partial})", style=ButtonStyle.url, emoji=region.emote))

        self.embed = e
        self.view = v
        return self.embed


class NewsChannel:
    """An Object representing a NewsChannel"""

    def __init__(self, bot: 'PBot', channel: TextChannel, eu=False, na=False, sea=False, cis=False) -> None:
        self.channel: TextChannel = channel
        self.bot: PBot = bot

        # A bool for the tracking of each region
        self.eu: bool = eu
        self.na: bool = na
        self.sea: bool = sea
        self.cis: bool = cis

        # A list of partial links for articles to see if this channel has already sent one.
        self.sent_articles: Dict[Article, Message] = dict()  # Article, message_id

    async def dispatch(self, region: Region, article: Article) -> Optional[Message]:
        """Check if the article has already been submitted to the channel, and is for a tracked region, then send it.

        If the article is already in our channel, edit the post with the link to the additional region.
        """
        # Check if we want this news article for this channel.
        if not getattr(self, region.db_key):
            return

        if self.channel is None:
            return

        # Check if this news article has already been posted for another region.
        message = self.sent_articles.get(article)
        if message is not None:
            await message.edit(embed=article.embed, view=article.view)
        else:
            message = await self.channel.send(embed=article.embed, view=article.view)

        self.sent_articles[article] = message

    async def send_config(self, interaction: Interaction) -> Message:
        """Send the config view to the requesting user"""
        view = NewsConfig(self.bot, interaction, self.channel)
        return await view.update()


class NewsConfig(View):
    """News Tracker Config View"""

    def __init__(self, bot: 'PBot', interaction: Interaction, channel: TextChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel
        self.bot: PBot = bot

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    @property
    def base_embed(self) -> Embed:
        """Generic Embed for Config Views"""
        return Embed(colour=Colour.dark_teal(), title="World of Warships News Tracker config")

    async def update(self, content: str = "") -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM news_trackers WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        e: Embed = Embed(colour=Colour.dark_teal())
        e.title = f"World of Warships News Tracker config"
        e.set_thumbnail(url=self.interaction.guild.me.display_avatar.url)

        for k, v in sorted(channel.items()):
            if k != 'channel_id':
                region = next(i for i in Region if k == i.db_key)
                self.add_item(ToggleButton(self.bot, region=region, value=v))

        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class NewsTracker(Cog):
    """NewsTracker Commands"""

    def __init__(self, bot: 'PBot') -> None:
        self.bot: PBot = bot
        self.bot.news = self.news_loop.start()
        self.bot.news_channels = []

    async def cog_load(self) -> None:
        """Do this on Cog Load"""
        await self.update_cache()

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.news.cancel()

    async def update_cache(self) -> None:
        """Get the list of NewsTracker channels stored in the database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM news_trackers""")
        finally:
            await self.bot.db.release(connection)

        # Remove 'dead' channels.
        new_ids = [r['channel_id'] for r in records]
        for x in self.bot.news_channels.copy():
            if x.channel.id not in new_ids:
                self.bot.news_channels.remove(x)

        # Append new ones.
        cached_ids = [x.channel.id for x in self.bot.news_channels]
        for r in records:
            if r['channel_id'] not in cached_ids:
                channel = self.bot.get_channel(r['channel_id'])
                if channel is None:
                    continue

                c = NewsChannel(self.bot, channel=channel, eu=r['eu'], na=r['na'], sea=r['sea'], cis=r['cis'])
                self.bot.news_channels.append(c)

    @loop(seconds=60)
    async def news_loop(self) -> None:
        """Loop to get the latest EU news articles"""
        if self.bot.session is None:
            return

        # If we already have parsed the articles once, flag it now.
        cached = bool(self.bot.news_cache)

        region: Region
        for region in Region:
            async with self.bot.session.get(region.domain + '/en/rss/news/') as resp:
                tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

            articles = tree.xpath('.//item')

            for i in articles:
                link = ''.join(i.xpath('.//guid/text()'))
                partial = link.split('/en/')[-1]

                article = next((i for i in self.bot.news_cache if i.partial == partial), None)

                if article is not None:
                    # If we have already dispatched this article for this region, we are no longer interested
                    if getattr(article, region.db_key):
                        continue
                else:
                    article = Article(self.bot, partial)
                    setattr(article, region.db_key, True)
                    self.bot.news_cache.append(article)

                # If we are simply populating, we are not interested.
                if not cached:
                    continue  # Skip on population

                # At this point, we either have a new article, or a new region for an existing article.
                # In which case, we check if we need to extract additional data from the RSS.

                if not hasattr(article, 'link'):
                    article.link = link  # Original Link

                    date = ''.join(i.xpath('.//pubdate/text()'))
                    if date:
                        article.date = datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z")
                    else:
                        article.date = datetime.datetime.now()

                if not hasattr(article, 'category'):
                    category = ''.join(i.xpath('.//category//text()'))
                    if category:
                        article.category = category

                if not hasattr(article, 'description'):
                    # Extract article description
                    desc = ''.join(i.xpath('.//description/text()'))
                    # Sanitise it
                    desc = " ".join(desc.split()).replace(' ]]>', '')

                    if desc:
                        article.description = desc

                if not hasattr(article, 'title'):
                    title = ''.join(i.xpath('.//title/text()'))
                    if title:
                        article.title = title

                await article.generate_embed()

                for channel in self.bot.news_channels:
                    await channel.dispatch(region, article)

    # Command for tracker management.
    @command()
    @guild_only()
    @default_permissions(manage_channels=True)
    @describe(channel="Select a channel to edit")
    async def news_tracker(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """Enable/Disable the World of Warships dev blog tracker in this channel."""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        target = next((i for i in self.bot.news_channels if i.channel.id == channel.id), None)

        if target is None:
            connection = await self.bot.db.acquire()
            sql = """INSERT INTO news_trackers (channel_id) VALUES ($1)"""

            try:
                async with connection.transaction():
                    await connection.execute(sql, channel.id)
            finally:
                await self.bot.db.release(connection)

            target = NewsChannel(self.bot, channel=channel)
        return await target.send_config(interaction)

    # Event Listeners for database cleanup.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel):
        """Remove dev blog trackers from deleted channels"""
        q = f"""DELETE FROM news_trackers WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id)
        finally:
            await self.bot.db.release(connection)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild):
        """Purge news trackers for deleted guilds"""
        q = f"""DELETE FROM news_trackers WHERE guild_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, guild.id)
        finally:
            await self.bot.db.release(connection)


async def setup(bot: 'PBot') -> None:
    """Load the NewsTracker Cog into the bot."""
    await bot.add_cog(NewsTracker(bot))
