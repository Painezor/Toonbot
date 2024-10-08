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

    def __init__(self, blog: api.DevBlog) -> None:
        super().__init__(url=blog.url, colour=0x00FFFF)
        txt = f"World of Warships Development Blog #{blog.id}"
        self.set_author(name=txt, url=blog.url)
        self.text: str = ""
        self.images: list[str] = []

    def finalise(self) -> None:
        """Truncate & apply image"""
        self.timestamp = discord.utils.utcnow()

        if len(final := self.text) > 4000:
            trunc = f"…\n[Read Full Article]({self.url})"
            self.description = final.ljust(4000)[: 4000 - len(trunc)] + trunc
        else:
            self.description = final

        if self.images:
            self.set_image(url=self.images[0])  # Null coalesce

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
        """Convert <a href="bar">foo<p>hi</p></a> to [foohi](bar)"""
        self.text += " ["
        if node.text:
            self.text += node.text
        self.parse(node)
        self.text += f"]({node.attrib['href']}) "

        if node.tail:
            self.text += node.tail

    def parse_br(self, _: html.HtmlElement) -> None:
        """<br/> -> \n"""
        self.text += "\n"

    def parse_em(self, node: html.HtmlElement) -> None:
        """<em> for *emphasis*"""
        self.text += " *"
        if node.text:
            self.text += node.text
        self.parse(node)  # Iter children, these are emphasised too

        self.text += "* "  # End of emphasis

        if node.tail:
            self.text += f"{node.tail}"

    def parse_h2(self, node: html.HtmlElement) -> None:
        self.parse_header(node)  # This will soon be ##

    def parse_h3(self, node: html.HtmlElement) -> None:
        self.parse_header(node)  # This will soon be ###

    def parse_h4(self, node: html.HtmlElement) -> None:
        self.parse_header(node)  # This will soon be ####

    def parse_header(self, node: html.HtmlElement) -> None:
        """Parse Header Blocks and Embolden"""
        if node.getprevious() is None:
            self.text += "\n"

        self.text += " **"
        if node.text:
            self.text += node.text

        self.parse(node)
        self.text += "** "

        if node.tail:
            self.text += node.tail

        if node.getnext() is None:
            self.text += "\n"

    def parse_info(self, node: html.HtmlElement) -> None:
        """Handling of supership Stars"""
        cls_ = node.attrib.get("class", None)
        if cls_ == "superShipStar":
            self.text += r"\⭐"
        else:
            try:
                _cls = node.attrib["class"]
                logger.error("'i' tag %s containing text %s", _cls, node.text)
            except KeyError:
                pass

        if node.text:
            self.text += node.text

        self.parse(node)

        if node.tail:
            self.text += node.tail

    def parse_img(self, node: html.HtmlElement) -> None:
        """Get Image & save link to self.images"""
        src = "http:" + node.attrib["src"]
        self.images.append(src)
        self.text += f" [Image]({src}) "

    def parse_span(self, node: html.HtmlElement) -> None:
        """Extract ships from span blocks."""
        # Handle Ships
        if node.attrib.get("class", None) == "ship":
            if (country := node.attrib.get("data-nation", None)) is not None:
                self.text += " " + api.emojis.NATION_FLAGS[country.casefold()]

            if node.attrib.get("data-type", False):
                self.text += self.get_emote(node)

            if node.text:
                self.text += f" **{node.text}** "
        else:
            if node.text:
                self.text += node.text

        self.parse(node)

        if node.tail:
            self.text += node.tail

    def parse_div(self, node: html.HtmlElement) -> None:
        """Parse <div> tag"""
        if "article-cut" in node.classes:
            return self.parse_br(node)

        if node.text:
            self.text += node.text

        self.parse(node)

        if node.tail:
            self.text += node.tail

    def parse_li(self, node: html.HtmlElement) -> None:
        """Parse <li> tags"""
        # Get a count of total parent ol/ul/lis
        if node.text:
            depth = sum(1 for _ in node.iterancestors("ol", "ul"))
            try:
                bullet = {1: "•", 2: "∟○", 3: "└─⁍"}[depth]
            except KeyError:
                bullet = "•"
                logger.error("invalid depth %s", depth)
            self.text += f"\n{bullet} {node.text}"

        self.parse(node)

        if node.tail:
            self.text += node.tail

    def parse_ol(self, node: html.HtmlElement) -> None:
        return self.parse_p(node)

    def parse_ul(self, node: html.HtmlElement) -> None:
        return self.parse_p(node)

    def parse_p(self, node: html.HtmlElement) -> None:
        """Parse <p> tags"""
        if node.text:
            self.text += node.text

        self.parse(node)

        if node.tail:
            self.text += node.tail

        if node.text:
            self.text += "\n"

    def parse_u(self, node: html.HtmlElement) -> None:
        """__Underline__"""
        self.text += " __"
        if node.text:
            self.text += node.text

        self.parse(node)

        self.text += "__ "
        if node.tail:
            self.text += node.tail

    def parse_table(self, _: html.HtmlElement) -> None:
        """Tables are a pain in the dick."""
        self.text += "```\n<Table Omitted, please see web article>```"

    def parse_th(self, _: html.HtmlElement) -> None:
        pass

    def parse_td(self, _: html.HtmlElement) -> None:
        pass

    def parse_tr(self, _: html.HtmlElement) -> None:
        pass

    def parse(self, tree: html.HtmlElement) -> None:
        """Recursively parse a single node and it's children"""
        for node in tree.iterchildren():
            if node.text:
                node.text = node.text.strip()
            if node.tail:
                node.tail = node.tail.strip()
            try:
                {
                    "a": self.parse_a,
                    "br": self.parse_br,
                    "div": self.parse_div,
                    "em": self.parse_em,
                    "h2": self.parse_h2,
                    "h3": self.parse_h3,
                    "h4": self.parse_h4,
                    "i": self.parse_info,
                    "img": self.parse_img,
                    "li": self.parse_li,
                    "ol": self.parse_ol,
                    "p": self.parse_p,
                    "span": self.parse_span,
                    "strong": self.parse_header,
                    "sup": self.parse_p,
                    "table": self.parse_table,
                    "td": self.parse_td,
                    "th": self.parse_th,
                    "tr": self.parse_tr,
                    "u": self.parse_u,
                    "ul": self.parse_ul,
                }[node.tag.strip()](node)
            except KeyError:
                tag = node.tag
                tail = node.tail
                text = node.text
                logger.error("Unhandled tag: [%s]: %s|%s", tag, text, tail)
                continue

    @classmethod
    async def create(cls, blog: api.DevBlog) -> discord.Embed:
        html = await blog.fetch_text()
        embed = cls(blog)
        embed.title = blog.title
        embed.parse(html)
        embed.finalise()
        return embed


# TODO: Image Browser Dropdown
# TODO: Paginate text.
class DevBlogView(view_utils.Paginator):
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

    choices: list[Choice[str]] = []
    for i in dbc:
        autocomplete = f"{i.id} {i.title} {i.text}".casefold()

        if cur not in autocomplete:
            continue

        # If there's ever a description param on a choice ...
        # bf, _, af = i.text.casefold().split(cur, maxsplit=1)

        # lgth = 50 - (len(cur) / 2)
        # text = f"{bf[lgth:]}{cur}{af[:lgth]}"[:100]

        name = f"{i.id}: {i.title}"[:100]
        choices.append(Choice(name=name, value=str(i.id)))

        if len(choices) == 25:
            break

    return choices


class BlogCog(commands.Cog):
    """DevBlog Commands"""

    def __init__(self, bot: PBot):
        self.bot: PBot = bot
        self.cache: list[api.DevBlog] = []
        self.task: asyncio.Task[None] | None = None

    async def cog_load(self) -> None:
        await self.get_blogs()
        self.task = self.blog_loop.start()

    async def save_blog(self, blog: api.DevBlog) -> None:
        """Store cached inner text of a specific dev blog"""
        async with self.bot.session.get(blog.url) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        title = str(tree.xpath(".//title/text()")[0])
        title = title.split(" - Development", maxsplit=1)[0]
        blog.title = title

        xpath = './/div[@class="article__content"]'
        text = tree.xpath(xpath)[0].text_content()

        if text:
            logger.info("Storing Dev Blog #%s", blog.id)
            blog.text = text
        else:
            return
        sql = """INSERT INTO dev_blogs (id, title, text) VALUES ($1, $2, $3)
                 ON CONFLICT DO NOTHING"""
        await self.bot.db.execute(sql, blog.id, title, text, timeout=60)
        self.cache.append(blog)

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        if self.task is not None:
            self.task.cancel()

    @tasks.loop(seconds=60)
    async def blog_loop(self) -> None:
        """Loop to get the latest dev blog articles"""
        if not [cached := [int(r.id) for r in self.cache]]:
            return

        sql = """SELECT * FROM dev_blog_channels"""
        for blog_id in await api.get_dev_blogs():
            if blog_id in cached:
                continue

            logger.info("blog #%s not in cache", blog_id)

            blog = api.DevBlog(blog_id)
            await self.save_blog(blog)

            embed = await BlogEmbed.create(blog)

            for r in await self.bot.db.fetch(sql, timeout=10):
                channel = self.bot.get_channel(r["channel_id"])
                if not isinstance(channel, discord.TextChannel):
                    continue

                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    logger.error("Failed to send blog", exc_info=True)
                    continue

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
        except (StopIteration, ValueError):
            # If a specific blog is not selected, send the browser view.
            txt = search.casefold()
            yes = [i for i in self.cache if txt in i.text.casefold()]
            logger.info("devblog view has %s blogs", len(yes))
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
