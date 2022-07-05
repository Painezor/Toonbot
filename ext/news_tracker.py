"""Cog for fetching World of Warships Portal Articles from each region"""
from __future__ import annotations  # Cyclic Type hinting

import datetime
from typing import TYPE_CHECKING, Optional, Dict, List

from asyncpg import Record
from discord import Embed, Interaction, Message, Colour, TextChannel, Guild, ButtonStyle, HTTPException
from discord.app_commands import command, describe, guild_only, default_permissions, autocomplete, Choice
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View, Button
from lxml import html

from ext.painezbot_utils.player import Region
from ext.utils.view_utils import Stop

if TYPE_CHECKING:
    from painezBot import PBot


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
        new_value: bool = not self.value

        sql = f"""UPDATE news_trackers SET {self.region.db_key} = $1 WHERE channel_id = $2"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(sql, new_value, self.view.channel.id)
        finally:
            await self.bot.db.release(connection)

        on = "Enabled" if new_value else "Disabled"
        r = self.region.name
        return await self.view.update(f'{on} tracking of articles for {r} in {self.view.channel.mention}')


class Article:
    """An Object representing a World of Warships News Article"""
    bot: PBot
    embed: Embed
    view: View

    def __init__(self, bot: 'PBot', partial: str) -> None:
        self.bot = bot
        # Partial is the trailing part of the URL.
        self.partial: str = partial
        self.link: str = None

        # Stored Data
        self.title: str = None
        self.category: str = None
        self.description: str = None
        self.image: str = None

        # A flag for each region the article has been found in.
        self.eu: bool = False
        self.na: bool = False
        self.cis: bool = False
        self.sea: bool = False

        self.date: Optional[datetime.datetime] = None

    async def save_to_db(self) -> None:
        """Store the article in the database for quicker retrieval in future"""
        sql = """INSERT INTO news_articles 
                 (title, description, partial, link, image, category, date, eu, na, cis, sea)
                 VALUES 
                 ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) 
                 ON CONFLICT (partial) DO UPDATE SET 
                 (title, description, link, image, category, date, eu, na, cis, sea) = 
                 (EXCLUDED.title, EXCLUDED.description, EXCLUDED.link, EXCLUDED.image, EXCLUDED.category, EXCLUDED.date,
                 EXCLUDED.eu, EXCLUDED.na, EXCLUDED.cis, EXCLUDED.sea)
                 """
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(sql, self.title, self.description, self.partial, self.link, self.image,
                                         self.category, self.date, self.eu, self.na, self.cis, self.sea)
        finally:
            await self.bot.db.release(connection)
        return

    async def generate_embed(self) -> Embed:
        """Handle dispatching of news article."""
        # CHeck if we need to do a full refresh on the article.
        if None in [self.title, self.category, self.image, self.description]:
            page = await self.bot.browser.newPage()

            try:
                await page.goto(self.link)
                await page.waitForXPath(".//div[@class='header__background']", {"timeout": 5000})
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

            if not self.title:
                self.title = tree.xpath('.//div[@class="title"]/text()')[0]

            if not self.category:
                self.category = tree.xpath('.//nav/div/a/span/text()')[-1]

            if not self.description:
                self.description = tree.xpath('.//span[@class="text__intro"]/text()')[-1]

            # Fetch Image from JS Heavy news page because it looks pretty.
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

        for region in Region:
            if getattr(self, region.db_key):
                e.colour = region.colour
                break

        v = View()
        for region in Region:
            if getattr(self, region.db_key):
                url = f"https://worldofwarships.{region.domain}/en/{self.partial}"
                b = Button(style=ButtonStyle.url, label=f"{region.name} article", emoji=region.emote, url=url)
                v.add_item(b)

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
        return message

    async def send_config(self, interaction: Interaction) -> Message:
        """Send the config view to the requesting user"""
        view = NewsConfig(self.bot, interaction, self.channel)
        return await view.update()


class NewsConfig(View):
    """News Tracker Config View"""

    def __init__(self, bot: 'PBot', interaction: Interaction, channel: TextChannel) -> None:
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

        sql = """SELECT * FROM news_trackers WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                record = await connection.fetchrow(sql, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        e: Embed = Embed(colour=Colour.dark_teal())
        e.title = f"World of Warships News Tracker config"
        e.description = "```yaml\nClick on the buttons below to enable tracking for a region.\n\n" \
                        "Duplicate articles from different regions will not be output multiple times.```"
        e.set_thumbnail(url=self.interaction.guild.me.display_avatar.url)

        for k, v in sorted(record.items()):
            if k != 'channel_id':
                region = next(i for i in Region if k == i.db_key)

                if v:  # Bool: True/False
                    e.description += f"\n**{region.emote} {region.name} News is currently being tracked.**"
                else:
                    e.description += f"\n{region.emote} {region.name} News is not being tracked."

                self.add_item(ToggleButton(self.bot, region=region, value=v))
        self.add_item(Stop())
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


async def news_ac(interaction: Interaction, current: str) -> List[Choice[str]]:
    """An Autocomplete that fetches from recent news articles"""
    articles: List[Article] = getattr(interaction.client, 'news_cache')
    matches = [i for i in articles if current.lower() in f"{i.title}: {i.description}".lower()]

    now = datetime.datetime.now(datetime.timezone.utc)
    matches = sorted(matches, key=lambda x: now if x.date is None else x.date, reverse=True)
    return [Choice(name=f"{i.title}: {i.description}"[:100], value=i.link) for i in matches][:25]


class NewsTracker(Cog):
    """NewsTracker Commands"""

    def __init__(self, bot: 'PBot') -> None:
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
            async with self.bot.session.get(f'https://worldofwarships.{region.domain}/en/rss/news/') as resp:
                tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

            for i in tree.xpath('.//item'):
                link = ''.join(i.xpath('.//guid/text()'))
                partial = link.split('/en/')[-1]

                try:
                    article = next(i for i in self.bot.news_cache if i.partial == partial)
                except StopIteration:
                    article = Article(self.bot, partial)
                    self.bot.news_cache.append(article)

                # If we have already dispatched this article for this region, we are no longer interested
                if getattr(article, region.db_key):
                    continue
                else:
                    setattr(article, region.db_key, True)

                # At this point, we either have a new article, or a new region for an existing article.
                # In which case, we check if we need to extract additional data from the RSS.
                if article.link is None:
                    article.link = link  # Original Link

                if article.date is None:
                    date = ''.join(i.xpath('.//pubdate/text()'))
                    if date:
                        article.date = datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z")
                    else:
                        article.date = datetime.datetime.now(datetime.timezone.utc)

                if not article.category:
                    category = ''.join(i.xpath('.//category//text()'))
                    if category:
                        article.category = category

                if not article.description:
                    # Extract article description
                    desc = ''.join(i.xpath('.//description/text()'))
                    # Sanitise it
                    desc = " ".join(desc.split()).replace(' ]]>', '')

                    if desc:
                        article.description = desc

                if article.title is None:
                    title = ''.join(i.xpath('.//title/text()'))
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

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                channels = await connection.fetch("""SELECT * FROM news_trackers""")
                articles = await connection.fetch("""SELECT * FROM news_articles""")
        finally:
            await self.bot.db.release(connection)

        partials = [i.partial for i in self.bot.news_cache]

        r: Record
        for r in articles:
            if r['partial'] in partials:
                continue
            else:
                article = Article(self.bot, partial=r['partial'])
                for k, v in r.items():
                    if k == "partial":
                        continue

                    setattr(article, k, v)
                self.bot.news_cache.append(article)

        # Append new ones.
        cached_ids = [x.channel.id for x in self.bot.news_channels]
        for r in channels:
            if r['channel_id'] not in cached_ids:
                channel = self.bot.get_channel(r['channel_id'])
                if channel is None:
                    continue

                c = NewsChannel(self.bot, channel=channel, eu=r['eu'], na=r['na'], sea=r['sea'], cis=r['cis'])
                self.bot.news_channels.append(c)

    @command()
    @describe(text="Search by article title")
    @autocomplete(text=news_ac)
    async def newspost(self, interaction: Interaction, text: str):
        """Search for a recent World of Warships news article"""
        await interaction.response.defer(thinking=True)

        try:
            article = next(i for i in self.bot.news_cache if i.link == text)
        except StopIteration:
            return await self.bot.error(interaction, content=f"Didn't find article matching {text}", ephemeral=True)

        await article.generate_embed()

        v = article.view
        await self.bot.reply(interaction, view=v, embed=article.embed)

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

        try:
            target = next(i for i in self.bot.news_channels if i.channel.id == channel.id)
        except StopIteration:
            sql = """INSERT INTO news_trackers (channel_id) VALUES ($1)"""
            connection = await self.bot.db.acquire()

            try:
                async with connection.transaction():
                    await connection.execute(sql, channel.id)
            finally:
                await self.bot.db.release(connection)

            target = NewsChannel(self.bot, channel=channel)
            self.bot.news_channels.append(target)
        return await target.send_config(interaction)

    # Event Listeners for database cleanup.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> List[NewsChannel]:
        """Remove dev blog trackers from deleted channels"""
        q = f"""DELETE FROM news_trackers WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id)
        finally:
            await self.bot.db.release(connection)

        self.bot.news_channels = [i for i in self.bot.news_channels if i.channel.id != channel.id]
        return self.bot.news_channels

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> List[NewsChannel]:
        """Purge news trackers for deleted guilds"""
        q = f"""DELETE FROM news_trackers WHERE guild_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, guild.id)
        finally:
            await self.bot.db.release(connection)

        self.bot.news_channels = [i for i in self.bot.news_channels if i.channel.guild.id != guild.id]
        return self.bot.news_channels


async def setup(bot: 'PBot') -> None:
    """Load the NewsTracker Cog into the bot."""
    await bot.add_cog(NewsTracker(bot))
