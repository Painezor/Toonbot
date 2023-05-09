"""Tracker for the World of Warships Development Blog"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast, TypeAlias, Literal

import asyncio
import discord
from discord.abc import GuildChannel
from discord.ext import commands, tasks
from discord.app_commands import Choice
from lxml import html

from ext import wows_api as api
from ext.utils import view_utils, embed_utils

if TYPE_CHECKING:
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[PBot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("Devblog")


class BlogEmbed(discord.Embed):
    """Convert a Dev Blog to an Embed"""

    text: str = ""
    images: list[str] = []

    def __init__(self, blog: api.DevBlog) -> None:
        super().__init__(url=blog.url, colour=0x00FFFF)
        txt = f"World of Warships Development Blog #{blog.id}"
        self.set_author(name=txt, url=blog.url)

    def finalise(self) -> None:
        """Truncate & apply image"""
        self.timestamp = discord.utils.utcnow()

        if len(final := self.text) > 4000:
            trunc = f"…\n[Read Full Article]({self.url})"
            self.description = final.ljust(4000)[: 4000 - len(trunc)] + trunc
        else:
            self.description = final

        if self.images:
            self.set_image(url=self.images[0])

    @staticmethod
    def get_emote(node: html.HtmlElement) -> str:
        """Get the appropriate emote for ship class & rarity combination"""
        if (s_class := node.attrib.get("data-type", None)) is None:
            return ""

        if node.attrib.get("data-premium", None) == "true":
            return api.SHIP_EMOTES[s_class]["premium"]

        if node.attrib.get("data-special", None) == "true":
            return api.SHIP_EMOTES[s_class]["special"]

        return api.SHIP_EMOTES[s_class]["normal"]

    def parse_a(self, node: html.HtmlElement) -> None:
        """Convert <a href="bar">foo</a> to [foo](bar)"""
        self.text += f"[{node.text}]({node.attrib['href']})"

    def parse_br(self, _: html.HtmlElement) -> None:
        """<br/> -> \n"""
        self.text += "\n"

    def parse_em(self, node: html.HtmlElement) -> None:
        """<em> for *emphasis*"""
        self.text += f"*{node.text}*"

    def parse_header(self, node: html.HtmlElement) -> None:
        """Parse Header Blocks and Embolden"""
        if node.text:
            self.text += f"**{node.text}**"

        if node.getnext() is None:
            self.text += "\n"

    def parse_info(self, node: html.HtmlElement) -> None:
        """Handling of supership Stars"""
        if node.attrib.get("class", None) == "superShipStar":
            self.text += r"\⭐"
        else:
            _cls = node.attrib["class"]
            logger.error("'i' tag %s containing text %s", _cls, node.text)

    def parse_image(self, node: html.HtmlElement) -> None:
        """Get Image & save link to self.images"""
        src = "http:" + node.attrib["src"]
        self.images.append(src)
        self.text += f"[Image]({src})"

    def parse_span(self, node: html.HtmlElement) -> None:
        """Extract ships from span blocks."""
        # Handle Ships
        if node.attrib.get("class", None) == "ship":
            if (country := node.attrib.get("data-nation", None)) is not None:
                self.text += " " + api.emojis.NATION_FLAGS[country.casefold()]

            if node.attrib.get("data-type", False):
                self.text += self.get_emote(node)

            if node.text is not None:
                self.text += f"**{node.text}** "
            return

        if node.text:
            self.text += node.text

    def parse_div_tag(self, node: html.HtmlElement) -> None:
        """Parse <div> tag"""
        if "article-cut" in node.classes:
            self.parse_br(node)
            return

        elif "spoiler" in node.classes:
            for i in node.iterchildren():
                node.remove(i)

            self.text += "```\nSee article for full statistics```"

        elif node.text is not None:
            self.text += node.text

    def parse_list(self, node: html.HtmlElement) -> None:
        """Parse <li> tags"""
        bullet = "•"
        if node.text:
            if (par := node.getparent()) is not None:
                if (par := par.getparent()) is not None:
                    if par.tag in ["ul", "ol", "li"]:
                        bullet = "∟○"
            self.text += f"\n{bullet} {node.text}"

        if node.getnext() is None:
            if len(node) == 0:  # Number of children
                self.text += "\n"

    def parse_p_tag(self, node: html.HtmlElement) -> None:
        """Parse <p> tags"""
        if node.text:
            if node.getprevious() is not None and node.text:
                self.text += "\n"
            self.text += node.text
            if (nxt := node.getnext()) is not None and nxt.tag == "p":
                self.text += "\n"

    def parse_u(self, node: html.HtmlElement) -> None:
        """__Underline__"""
        self.text += f"__{node.text}__"

    def parse_table(self, _: html.HtmlElement) -> None:
        """Tables are a pain in the dick."""
        self.text += "```\n<Table Omitted, please see web article>```"

    def parse(self, node: html.HtmlElement, is_tail: bool = False) -> None:
        """Recursively parse a single node and it's children"""
        tag = node.tag
        tail = node.tail
        text = node.text

        if text is not None and text.strip():
            try:
                {
                    "a": self.parse_a,
                    "br": self.parse_br,
                    "div": self.parse_div_tag,
                    "em": self.parse_em,
                    "i": self.parse_info,
                    "h2": self.parse_header,
                    "h3": self.parse_header,
                    "h4": self.parse_header,
                    "img": self.parse_image,
                    "p": self.parse_p_tag,
                    "span": self.parse_span,
                    "strong": self.parse_header,
                    "sup": self.parse_p_tag,
                    "table": self.parse_table,
                    "u": self.parse_u,
                    "ol": self.parse_p_tag,
                    "ul": self.parse_p_tag,
                    "li": self.parse_list,
                }[tag](node)
            except KeyError:
                logger.error("Unhandled tag: [%s]: %s|%s", tag, text, tail)
                return

        if is_tail:
            return

        if tag == "table":
            return

        for sub_node in node.iterchildren():
            self.parse(sub_node)

        if tail:
            par = node.getparent()
            if par:
                node.tag = par.tag
            node.text = node.tail
            node.tail = None
            self.parse(node, is_tail=True)

    @classmethod
    async def create(cls, blog: api.DevBlog) -> discord.Embed:
        html = await blog.fetch_text()
        embed = cls(blog)
        embed.title = html.xpath('.//h2[@class="article__title"]/text()')[0]
        embed.parse(html)
        embed.finalise()
        return embed


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


async def db_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete dev blog by text"""

    cur = current.casefold()
    dbc = cast(BlogCog, interaction.client.get_cog(BlogCog.__cog_name__)).cache
    dbc.sort(key=lambda i: i.id, reverse=True)
    logger.info("%s Blogs Sorted.", len(dbc))

    choices: list[Choice[str]] = []
    for i in dbc:
        if cur not in i.ac_row:
            continue

        name = f"{i.id}: {i.title}"[:100]
        choices.append(Choice(name=name, value=str(i.id)))

        if len(choices) == 25:
            break
    logger.info("generateed %s blog options", len(choices))

    return choices


class BlogCog(commands.Cog):
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
        enabled: Literal["on", "off"],
    ) -> None:
        """Enable/Disable the World of Warships dev blog tracker
        in this channel."""
        if None in (interaction.channel, interaction.guild):
            raise commands.NoPrivateMessage

        channel = cast(discord.TextChannel, interaction.channel)
        guild = cast(discord.Guild, interaction.guild)

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
    async def on_guild_channel_delete(self, channel: GuildChannel) -> None:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
        await self.bot.db.execute(sql, channel.id, timeout=10)


async def setup(bot: PBot) -> None:
    """Load the Dev Blog Cog into the bot."""
    await bot.add_cog(BlogCog(bot))
