"""Cog for fetching World of Warships Portal Articles from each region"""
from __future__ import annotations  # Cyclic Type hinting

import datetime
from typing import TYPE_CHECKING, Optional
import typing

import discord
from asyncpg import Record
from discord import (
    Embed,
    Interaction,
    Message,
    Colour,
    TextChannel,
    ButtonStyle,
    HTTPException,
)
from discord.app_commands import (
    guild_only,
    default_permissions,
    Choice,
)
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import Button
from discord.utils import utcnow
from lxml import html
from playwright.async_api import TimeoutError

from ext.painezbot_utils.region import Region
from ext.utils.view_utils import Stop, BaseView

if TYPE_CHECKING:
    from painezBot import PBot


class ToggleButton(Button):
    """A Button to toggle the notifications settings."""

    view: NewsConfig

    def __init__(self, bot: PBot, region: Region, value: bool) -> None:
        self.value: bool = value
        self.region: Region = region
        self.bot: PBot = bot

        if value:
            colour = discord.ButtonStyle.blurple
            toggle = "On"
        else:
            colour = discord.ButtonStyle.gray
            toggle = "Off"

        label = f"{toggle} ({region.db_key})"

        super().__init__(label=label, emoji=region.emote, style=colour)

    async def callback(self, interaction: Interaction[PBot]) -> None:
        """Set view value to button value"""

        await interaction.response.defer()
        new_value: bool = not self.value

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = f"""UPDATE news_trackers SET {self.label} = $1
                          WHERE channel_id = $2"""
                await connection.execute(sql, new_value, self.view.channel.id)

        on = "Enabled" if new_value else "Disabled"
        r = self.region.name
        c = self.view.channel.mention
        return await self.view.update(f"{on} {r} articles in {c}")


class Article:
    """An Object representing a World of Warships News Article"""

    bot: PBot
    embed: discord.Embed
    view: discord.ui.View

    def __init__(self, bot: PBot, partial: str) -> None:
        self.bot = bot
        # Partial is the trailing part of the URL.
        self.partial: str = partial
        self.link: Optional[str] = None

        # Stored Data
        self.title: Optional[str] = None
        self.category: Optional[str] = None
        self.description: Optional[str] = None
        self.image: Optional[str] = None

        # A flag for each region the article has been found in.
        self.eu: bool = False
        self.na: bool = False
        self.cis: bool = False
        self.sea: bool = False

        self.date: Optional[datetime.datetime] = None

    async def save_to_db(self) -> None:
        """Store the article in the database for quicker retrieval in future"""
        sql = """INSERT INTO news_articles (title, description, partial,
                 link, image, category, date, eu, na, cis, sea)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                 ON CONFLICT (partial) DO UPDATE SET (title, description, link,
                 image, category, date, eu, na, cis, sea) = (EXCLUDED.title,
                 EXCLUDED.description, EXCLUDED.link, EXCLUDED.image,
                 EXCLUDED.category, EXCLUDED.date, EXCLUDED.eu, EXCLUDED.na,
                 EXCLUDED.cis, EXCLUDED.sea) """
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(
                    sql,
                    self.title,
                    self.description,
                    self.partial,
                    self.link,
                    self.image,
                    self.category,
                    self.date,
                    self.eu,
                    self.na,
                    self.cis,
                    self.sea,
                )

    async def generate_embed(self) -> Embed:
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
            except TimeoutError:
                return await self.generate_embed()
            finally:
                await page.close()

            if not self.title:
                self.title = tree.xpath('.//div[@class="title"]/text()')[0]

            if not self.category:
                self.category = tree.xpath(".//nav/div/a/span/text()")[-1]

            if not self.description:
                xp = './/span[@class="text__intro"]/text()'
                self.description = tree.xpath(xp)[-1]

            xp = './/div[@class="header__background"]/@style'
            try:
                self.image = "".join(tree.xpath(xp)).split('"')[1]
            except IndexError:
                pass

        e: Embed = Embed(
            url=self.link,
            colour=0x064273,
            title=self.title,
            description=self.description,
        )
        e.set_author(name=self.category, url=self.link)
        e.timestamp = self.date
        e.set_footer(text="World of Warships Portal News")
        try:
            e.set_image(url=self.image)
        except AttributeError:
            pass

        for region in Region:
            if getattr(self, region.db_key):
                e.colour = region.colour
                break

        v = discord.ui.View()
        for region in Region:
            if getattr(self, region.db_key):
                d = region.domain
                r = region.name
                url = f"https://worldofwarships.{d}/en/{self.partial}"
                b = Button(
                    style=ButtonStyle.url,
                    label=f"{r} article",
                    emoji=region.emote,
                    url=url,
                )
                v.add_item(b)

        self.embed = e
        self.view = v
        return self.embed


class NewsChannel:
    """An Object representing a NewsChannel"""

    def __init__(
        self,
        bot: PBot,
        channel: TextChannel,
        eu=False,
        na=False,
        sea=False,
        cis=False,
    ) -> None:
        self.channel: TextChannel = channel
        self.bot: PBot = bot

        # A bool for the tracking of each region
        self.eu: bool = eu
        self.na: bool = na
        self.sea: bool = sea
        self.cis: bool = cis

        # A list of partial links for articles to see if this
        # channel has already sent one.
        # Article, message_id
        self.sent_articles: dict[Article, Message] = dict()

    async def dispatch(
        self, region: Region, article: Article
    ) -> Optional[Message]:
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

    async def send_config(self, interaction: Interaction[PBot]) -> None:
        """Send the config view to the requesting user"""
        view = NewsConfig(interaction, self.channel)
        return await view.update()


class NewsConfig(BaseView):
    """News Tracker Config View"""

    def __init__(
        self, interaction: Interaction[PBot], channel: TextChannel
    ) -> None:
        super().__init__(interaction)
        self.channel: TextChannel = channel
        self.bot: PBot = interaction.client

    async def on_timeout(self) -> None:
        """Hide menu on timeout."""
        await self.bot.reply(self.interaction, view=None, followup=False)

    @property
    def base_embed(self) -> Embed:
        """Generic Embed for Config Views"""
        return Embed(
            colour=Colour.dark_teal(), title="World of Warships News Tracker"
        )

    async def update(self, content: Optional[str] = None) -> None:
        """Regenerate view and push to message"""
        self.clear_items()

        sql = """SELECT * FROM news_trackers WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                record = await connection.fetchrow(sql, self.channel.id)

        e: Embed = Embed(colour=Colour.dark_teal())
        e.title = "World of Warships News Tracker config"
        e.description = (
            "```yaml\nClick on the buttons below to enable "
            "tracking for a region.\n\nDuplicate articles from"
            " different regions will not be output multiple times"
            ".```"
        )

        ico = self.bot.user.display_avatar.url if self.bot.user else None
        e.set_thumbnail(url=ico)

        for k, v in sorted(record.items()):
            if k == "channel_id":
                continue

            region = next(i for i in Region if k == i.db_key)

            re = f"{region.emote} {region.name}"
            if v:  # Bool: True/False
                e.description += f"\n✅ {re} News is tracked.**"
            else:
                e.description += f"\n❌ {re} News is not tracked."

            self.add_item(ToggleButton(self.bot, region=region, value=v))
        self.add_item(Stop())
        await self.bot.reply(self.interaction, content, embed=e, view=self)


async def news_ac(ctx: Interaction[PBot], cur: str) -> list[Choice[str]]:
    """An Autocomplete that fetches from recent news articles"""
    choices = []
    cache = ctx.client.news_cache
    dt = datetime.datetime.now()

    cur = cur.casefold()

    for i in sorted(cache, key=lambda x: x.date or dt, reverse=True):
        if i.link is None:
            continue

        text = f"{i.title}: {i.description}".casefold()

        if cur not in text:
            continue

        choices.append(Choice(name=text[:100], value=i.link))
    return choices[:25]


class NewsTracker(Cog):
    """NewsTracker Commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        self.bot.news = self.news_loop.start()

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.news.cancel()

    @loop(minutes=1)
    async def news_loop(self) -> None:
        """Loop to get the latest EU news articles"""

        # If we already have parsed the articles once, flag it now.

        for region in Region:

            url = f"https://worldofwarships.{region.domain}/en/rss/news/"

            async with self.bot.session.get(url) as r:

                tree = html.fromstring(bytes(await r.text(), encoding="utf8"))

            for i in tree.xpath(".//item"):
                link = "".join(i.xpath(".//guid/text()"))
                partial = link.split("/en/")[-1]

                c = self.bot.news_cache
                try:
                    article = next(i for i in c if i.partial == partial)
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
                        article.date = utcnow()

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
                await article.save_to_db()

                for channel in self.bot.news_channels:
                    try:
                        await channel.dispatch(region, article)
                    except HTTPException:
                        continue

    @news_loop.before_loop
    async def update_cache(self) -> None:
        """Get the list of NewsTracker channels stored in the database"""
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """SELECT * FROM news_trackers"""
                channels = await connection.fetch(q)
                q = """SELECT * FROM news_articles"""
                articles = await connection.fetch(q)

        partials = [i.partial for i in self.bot.news_cache]

        r: Record
        for r in articles:
            if r["partial"] in partials:
                continue
            else:
                article = Article(self.bot, partial=r["partial"])
                for k, v in r.items():
                    if k == "partial":
                        continue

                    setattr(article, k, v)
                self.bot.news_cache.append(article)

        # Append new ones.
        cached_ids = [x.channel.id for x in self.bot.news_channels]
        for r in channels:
            if r["channel_id"] in cached_ids:
                continue

            if (channel := self.bot.get_channel(r["channel_id"])) is None:
                continue

            channel = typing.cast(discord.TextChannel, channel)

            c = NewsChannel(
                self.bot, channel, r["eu"], r["na"], r["sea"], r["cis"]
            )
            self.bot.news_channels.append(c)

    @discord.app_commands.command()
    @discord.app_commands.describe(text="Search by article title")
    @discord.app_commands.autocomplete(text=news_ac)
    async def newspost(self, interaction: Interaction[PBot], text: str):
        """Search for a recent World of Warships news article"""

        await interaction.response.defer(thinking=True)

        try:
            article = next(i for i in self.bot.news_cache if i.link == text)
        except StopIteration:
            err = f"Didn't find article matching {text}"
            return await self.bot.error(interaction, err)

        await article.generate_embed()
        await self.bot.reply(
            interaction, view=article.view, embed=article.embed
        )

    # Command for tracker management.
    @discord.app_commands.command()
    @guild_only()
    @default_permissions(manage_channels=True)
    @discord.app_commands.describe(channel="Select a channel to edit")
    async def news_tracker(
        self,
        interaction: Interaction[PBot],
        channel: Optional[TextChannel] = None,
    ) -> None:
        """Enable/Disable the World of Warships dev blog tracker
        in this channel."""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        try:
            n = self.bot.news_channels
            target = next(i for i in n if i.channel.id == channel.id)
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
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove dev blog trackers from deleted channels"""
        q = """DELETE FROM news_trackers WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, channel.id)

        c = self.bot.news_channels
        self.bot.news_channels = [i for i in c if i.channel.id != channel.id]


async def setup(bot: PBot) -> None:
    """Load the NewsTracker Cog into the bot."""
    await bot.add_cog(NewsTracker(bot))
