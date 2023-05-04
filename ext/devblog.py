"""Tracker for the World of Warships Development Blog"""
from __future__ import annotations

import logging
import typing

import asyncio
import discord
from discord.ext import commands, tasks
from lxml import html

from ext import wows_api as api
from ext.utils import view_utils, embed_utils

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]
    User: typing.TypeAlias = discord.User | discord.Member

logger = logging.getLogger("Devblog")


class BlogEmbed(discord.Embed):
    """Convert a Dev Blog to an Embed"""

    def __init__(self, blog: api.DevBlog) -> None:
        super().__init__(url=blog.url, title=blog.title, colour=0x00FFFF)

        self.timestamp = discord.utils.utcnow()

        txt = f"World of Warships Development Blog #{blog.id}"
        self.set_author(name=txt, url="https://blog.worldofwarships.com/")

        if len(final := blog.text) > 4000:
            trunc = f"…\n[Read Full Article]({blog.url})"
            self.description = final.ljust(4000)[: 4000 - len(trunc)] + trunc
        else:
            self.description = final

        if blog.images:
            self.set_image(url=blog.images[0])

    @classmethod
    async def create(cls, blog: api.DevBlog) -> discord.Embed:
        await blog.fetch_text()
        return cls(blog)


class DevBlogView(view_utils.AsyncPaginator):
    """Browse Dev Blogs"""

    def __init__(self, invoker: User, pages: list[api.DevBlog]) -> None:
        super().__init__(invoker, len(pages))
        self.blogs: list[api.DevBlog] = pages

    async def handle_page(  # type: ignore
        self, interaction: Interaction
    ) -> None:
        """Convert to Embed"""
        embed = await BlogEmbed.create(self.blogs[self.index])
        self.update_buttons()
        return await interaction.response.edit_message(embed=embed, view=self)


async def db_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete dev blog by text"""
    cur = current.casefold()

    choices: list[discord.app_commands.Choice[str]] = []

    if isinstance((cog := interaction.client.get_cog("DevBlog")), DevBlogCog):
        cache = cog.cache
    else:
        cache = []
    blogs = sorted(cache, key=lambda i: i.id)
    for i in blogs:
        if cur not in i.ac_row:
            continue

        name = f"{i.id}: {i.title}"[:100]
        choices.append(discord.app_commands.Choice(name=name, value=str(i.id)))

        if len(choices) == 25:
            break

    choices.reverse()
    return choices


class DevBlogCog(commands.Cog):
    """DevBlog Commands"""

    def __init__(self, bot: PBot):
        self.bot: PBot = bot
        self.cache: list[api.DevBlog] = []

        self.task: asyncio.Task[None] = self.blog_loop.start()
        self.channels: list[discord.abc.Messageable] = []

    async def save_blog(self, blog: api.DevBlog) -> None:
        """Store cached inner text of a specific dev blog"""
        async with self.bot.session.get(blog.url) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        title = str(tree.xpath(".//title/text()")[0])
        title = title.split(" - Development", maxsplit=1)[0]
        blog.cache_title(title)

        xpath = './/div[@class="article__content"]'
        text = tree.xpath(xpath)[0].text_content()

        if text:
            logger.info("Storing Dev Blog #%s", blog.id)
            blog.cache_text(text)
            blog.cache_title(text)
        else:
            return
        sql = """INSERT INTO dev_blogs (id, title, text) VALUES ($1, $2, $3)
                 ON CONFLICT DO NOTHING"""
        await self.bot.db.execute(sql, blog.id, title, text, timeout=60)
        self.cache.append(blog)

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        self.task.cancel()

    @tasks.loop(seconds=60)
    async def blog_loop(self) -> None:
        """Loop to get the latest dev blog articles"""
        if not [cached := [r.id for r in self.cache]]:
            return

        for blog_id in await api.get_dev_blogs():
            if blog_id in cached:
                continue
            blog = api.DevBlog(blog_id)
            await self.save_blog(blog)

            embed = await BlogEmbed.create(blog)

            for i in self.channels:
                try:
                    await i.send(embed=embed)
                except (AttributeError, discord.HTTPException):
                    continue

    @blog_loop.before_loop
    async def update_cache(self) -> None:
        """Assure dev blog channel list is loaded."""
        self.channels.clear()

        await self.get_blogs()

        sql = """SELECT * FROM dev_blog_channels"""
        records = await self.bot.db.fetch(sql, timeout=10)

        for r in records:
            chan = self.bot.get_channel(r["channel_id"])
            if isinstance(chan, discord.abc.Messageable):
                self.channels.append(chan)

    async def get_blogs(self) -> None:
        """Get a list of old dev blogs stored in DB"""
        self.cache.clear()
        sql = """SELECT * FROM dev_blogs"""
        records = await self.bot.db.fetch(sql, timeout=10)

        self.cache = [
            api.DevBlog(r["id"], r["title"], r["text"]) for r in records
        ]

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(manage_channels=True)
    async def blog_tracker(
        self,
        interaction: Interaction,
        enabled: typing.Literal["on", "off"],
    ) -> None:
        """Enable/Disable the World of Warships dev blog tracker
        in this channel."""
        if None in (interaction.channel, interaction.guild):
            raise commands.NoPrivateMessage

        channel = typing.cast(discord.TextChannel, interaction.channel)
        guild = typing.cast(discord.Guild, interaction.guild)

        if enabled:
            sql = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
            await self.bot.db.execute(sql, channel.id, timeout=60)
            output = "New Dev Blogs will no longer be sent to this channel."
            colour = discord.Colour.red()
        else:
            sql = """INSERT INTO dev_blog_channels (channel_id, guild_id)
                   VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            await self.bot.db.execute(sql, channel.id, guild.id, timeout=60)
            output = "New Dev Blogs will now be sent to this channel."
            colour = discord.Colour.green()

        embed = discord.Embed(colour=colour, title="Dev Blog Tracker")
        embed.description = output
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.response.send_message(embed=embed)
        await self.update_cache()

    @discord.app_commands.command()
    @discord.app_commands.autocomplete(search=db_ac)
    @discord.app_commands.describe(
        search="Search for a dev blog by text content"
    )
    async def devblog(self, interaction: Interaction, search: str) -> None:
        """Fetch a World of Warships dev blog, either search for text or
        leave blank to get latest."""
        try:
            blog = next(i for i in self.cache if i.id == int(search))
            embed = await BlogEmbed.create(blog)
            return await interaction.response.send_message(embed=embed)
        except StopIteration:
            # If a specific blog is not selected, send the browser view.
            txt = search.casefold()
            yes = [i for i in self.cache if txt in i.ac_row]
            view = DevBlogView(interaction.user, pages=yes)
            return await view.handle_page(interaction)

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
        await self.bot.db.execute(sql, channel.id, timeout=10)


async def setup(bot: PBot) -> None:
    """Load the Dev Blog Cog into the bot."""
    await bot.add_cog(DevBlogCog(bot))
