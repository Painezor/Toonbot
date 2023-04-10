"""Tracker for the World of Warships Development Blog"""
from __future__ import annotations

import logging
import typing

import asyncpg
import discord
from discord.ext import commands, tasks
from lxml import html
import yatg

from ext.utils import flags, view_utils, embed_utils

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]
    User: typing.TypeAlias = discord.User | discord.Member

logger = logging.getLogger("Devblog")

RSS = "https://blog.worldofwarships.com/rss-en.xml"

SHIP_EMOTES = {
    "aircarrier": {
        "normal": "<:aircarrier:991362771662930032>",
        "premium": "<:aircarrier_premium:991362995424862228>",
        "special": "<:aircarrier_special:991362955696406578>",
    },
    "battleship": {
        "normal": "<:battleship:991360614901493771>",
        "premium": "<:battleship_premium:991360127707914382>",
        "special": "<:battleship_special:991359103467274270>",
    },
    "cruiser": {
        "normal": "<:Cruiser:991318278611939331>",
        "premium": "<:cruiser_premium:991360312357953557>",
        "special": "<:cruiser_special:991356650701205574>",
    },
    "destroyer": {
        "normal": "<:Destroyer:991321386532491395>",
        "premium": "<:destroyer_premium:991360466322460762>",
        "special": "<:destroyer_special:991359827966173194>",
    },
    "submarine": {
        "normal": "<:submarine:991360776763879484>",
        "premium": "",
        "special": "<:submarine_special:991360980544143461>",
    },
}


def get_emote(node: html.HtmlElement):
    """Get the appropriate emote for ship class & rarity combination"""
    if (s_class := node.attrib.get("data-type", None)) is None:
        return ""

    if node.attrib.get("data-premium", None) == "true":
        return SHIP_EMOTES[s_class]["premium"]

    if node.attrib.get("data-special", None) == "true":
        return SHIP_EMOTES[s_class]["special"]

    return SHIP_EMOTES[s_class]["normal"]


class Blog:
    """A world of Warships DevBlog"""

    bot: typing.ClassVar[PBot]

    def __init__(
        self,
        _id: int,
        title: typing.Optional[str] = None,
        text: typing.Optional[str] = None,
    ):
        self.id: int = _id  # pylint: disable=C0103
        self.title: typing.Optional[str] = title
        self.text: typing.Optional[str] = text

    @property
    def ac_row(self) -> str:
        """Autocomplete representation"""
        return f"{self.id} {self.title} {self.text}".casefold()

    @property
    def url(self) -> str:
        """Get the link for this blog"""
        return f"https://blog.worldofwarships.com/blog/{self.id}"

    async def save_to_db(self) -> None:
        """Get the inner text of a specific dev blog"""
        async with self.bot.session.get(self.url) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        title = str(tree.xpath(".//title/text()")[0])
        self.title = title.split(" - Development", maxsplit=1)[0]

        self.text = tree.xpath('.//div[@class="article__content"]')[
            0
        ].text_content()

        if self.text:
            logger.info("Storing Dev Blog #%s", self.id)
        else:
            return

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO dev_blogs (id, title, text)
                       VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, self.id, self.title, self.text)

    async def make_embed(self) -> discord.Embed:
        """Get Embed from the Dev Blog page"""
        async with self.bot.session.get(self.url) as resp:
            tree = html.fromstring(await resp.text())

        article_html = tree.xpath('.//div[@class="article__content"]')[0]

        blog_number = self.id
        title = "".join(tree.xpath('.//h2[@class="article__title"]/text()'))
        embed = discord.Embed(url=self.url, title=title, colour=0x00FFFF)
        embed.timestamp = discord.utils.utcnow()

        txt = f"World of Warships Development Blog #{blog_number}"
        embed.set_author(name=txt, url="https://blog.worldofwarships.com/")
        output = []

        def parse(node: html.HtmlElement) -> str:
            """Parse a single node"""

            if node.tag == "img":
                embed.set_image(url="http:" + node.attrib["src"])
                return ""

            out: list[str] = []

            if node.text is not None:
                txt = node.text.strip()
            else:
                txt = None

            if node.tag in ["table", "tr"]:
                for sub_node in node.iterdescendants(None):
                    sub_node.text = (
                        None
                        if sub_node.text is None
                        else sub_node.text.strip()
                    )

                string = html.tostring(node, encoding="unicode")
                out.append(yatg.html_2_ascii_table(string))
                for sub_node in node.iterdescendants(None):
                    sub_node.text = None
            elif node.tag in ["tbody", "tr", "td"]:
                pass
            elif node.tag == "i":
                if node.attrib.get("class", None) == "superShipStar":
                    out.append(r"\⭐")
                else:
                    logger.error(
                        "unhandled 'i' tag %s containing text %s",
                        node.attrib["class"],
                        txt,
                    )
            elif node.tag == "p":
                if node.text_content():
                    if node.getprevious() is not None and node.text:
                        out.append("\n")
                        out.append(node.text)
                    if (nxt := node.getnext()) is not None:
                        if nxt.tag == "p":
                            out.append("\n")
            elif node.tag == "div":
                if node.attrib.get("class", None) == "article-cut":
                    out.append("\n")
                else:
                    out.append(txt)
            elif node.tag in ["ul", "td", "sup"]:
                out.append(txt)
            elif node.tag == "em":
                # Handle Italics
                out.append(f"*{txt}*")
            elif node.tag in ["strong", "h3", "h4"]:
                # Handle Bold.
                # Force line break if this is a standalone bold.
                if not node.getparent().text:
                    out.append("\n")

                if txt:
                    out.append(f"**{txt}** ")

                if node.tail == ":":
                    out.append(":")

                if node.getnext() is None:
                    out.append("\n")

            elif node.tag == "span":
                # Handle Ships
                if node.attrib.get("class", None) == "ship":
                    sub_out: list[str] = []

                    try:
                        if (
                            country := node.attrib.get("data-nation", None)
                        ) is not None:
                            sub_out.append(" " + flags.get_flag(country))
                    except AttributeError:
                        pass

                    try:
                        if node.attrib.get("data-type", False):
                            sub_out.append(get_emote(node))
                    except AttributeError:
                        pass

                    if txt is not None:
                        sub_out.append(f"**{txt}** ")
                    out.append(" ".join(sub_out))

                else:
                    out.append(txt)
            elif node.tag == "li":
                out.append("\n")
                if node.text:
                    if node.getparent().getparent().tag in ["ul", "ol", "li"]:
                        out.append(f"∟○ {txt}")
                    else:
                        out.append(f"• {txt}")

                if node.getnext() is None:
                    if len(node) == 0:  # Number of children
                        out.append("\n")
            elif node.tag == "a":
                out.append(f"[{txt}]({node.attrib['href']})")
            elif node.tag == "br":
                out.append("\n")
            else:
                if node.text:
                    tail = node.tail
                    tag = node.tag
                    logger.error("Unhandled node: %s|%s|%s", tag, txt, tail)
                    out.append(txt)

            for sub_node in node.iterchildren(None):
                if node.tag != "table":
                    out.append(parse(sub_node))

            if node.tail:
                tail = node.tail.strip() + " "

                tag = node.getparent().tag
                if tag == "em":
                    out.append(f"*{tail}*")
                elif tag == "span":
                    # Handle Ships
                    _cls = node.getparent().attrib.get("class", None)
                    if _cls == "ship":
                        out.append(f"**{tail}**")
                    else:
                        out.append(tail)
                else:
                    out.append(tail)

            return "".join([i for i in out if i])

        for elem in article_html.iterchildren():
            output.append(parse(elem))

        if len(output := "".join(output)) > 4000:
            trunc = f"…\n[Read Full Article]({self.url})"
            embed.description = output.ljust(4000)[: 4000 - len(trunc)] + trunc
        else:
            embed.description = output
        return embed


class DevBlogView(view_utils.AsyncPaginator):
    """Browse Dev Blogs"""

    def __init__(self, invoker: User, pages: list[Blog]) -> None:
        super().__init__(invoker, len(pages))
        self.blogs: list[Blog] = pages

    async def handle_page(self, interaction: Interaction) -> None:
        """Convert to Embed"""
        embed = await self.blogs[self.index].make_embed()
        await super().handle_page()
        return await interaction.response.edit_message(embed=embed, view=self)


async def db_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete dev blog by text"""
    cur = current.casefold()

    blogs: list[discord.app_commands.Choice[str]] = []
    for i in interaction.client.dev_blog_cache:
        if cur not in i.ac_row:
            continue

        name = f"{i.id}: {i.title}"[:100]
        blogs.append(discord.app_commands.Choice(name=name, value=str(i.id)))

        if len(blogs) == 25:
            break

    blogs.reverse()
    return blogs


class DevBlog(commands.Cog):
    """DevBlog Commands"""

    def __init__(self, bot: PBot):
        self.bot: PBot = bot
        self.bot.dev_blog = self.blog_loop.start()

        # Dev Blog Cache
        self.bot.dev_blog_cache.clear()
        self.bot.dev_blog_channels.clear()

        Blog.bot = bot

    async def cog_load(self) -> None:
        """Do this on Cog Load"""
        await self.get_blogs()
        await self.update_cache()

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.dev_blog.cancel()

    @tasks.loop(seconds=60)
    async def blog_loop(self) -> None:
        """Loop to get the latest dev blog articles"""
        if self.bot.session is None or not self.bot.dev_blog_cache:
            return

        async with self.bot.session.get(RSS) as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding="utf8"))

        articles = tree.xpath(".//item")
        for i in articles:
            try:
                links = i.xpath(".//guid/text() | .//link/text()")
                link = next(lnk for lnk in links if ".ru" not in lnk)
            except StopIteration:
                continue

            try:
                blog_id = int(link.rsplit("/", maxsplit=1)[-1])
            except ValueError:
                logger.error("Could not parse blog_id from link %s", link)
                continue

            if blog_id in [r.id for r in self.bot.dev_blog_cache]:
                continue

            blog = Blog(blog_id)

            await blog.save_to_db()
            await self.get_blogs()

            embed = await blog.make_embed()

            for i in self.bot.dev_blog_channels:
                try:
                    channel = self.bot.get_channel(i)
                    if channel is None:
                        continue

                    channel = typing.cast(discord.TextChannel, channel)
                    await channel.send(embed=embed)
                except (AttributeError, discord.HTTPException):
                    continue

    @blog_loop.before_loop
    async def update_cache(self) -> None:
        """Assure dev blog channel list is loaded."""
        sql = """SELECT * FROM dev_blog_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                channels = await connection.fetch(sql)
        self.bot.dev_blog_channels = [r["channel_id"] for r in channels]

    async def get_blogs(self) -> None:
        """Get a list of old dev blogs stored in DB"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM dev_blogs"""
                records = await connection.fetch(sql)

        self.bot.dev_blog_cache = [
            Blog(r["id"], title=r["title"], text=r["text"]) for r in records
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
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    await connection.execute(sql, channel.id)
            output = "New Dev Blogs will no longer be sent to this channel."
            colour = discord.Colour.red()
        else:
            sql = """INSERT INTO dev_blog_channels (channel_id, guild_id)
                   VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    await connection.execute(sql, channel.id, guild.id)
            output = "new Dev Blogs will now be sent to this channel."
            colour = discord.Colour.green()

        embed = discord.Embed(colour=colour, title="Dev Blog Tracker")
        embed.description = output
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.response.send_message(embed=embed)
        await self.update_cache()
        return

    @discord.app_commands.command()
    @discord.app_commands.autocomplete(search=db_ac)
    @discord.app_commands.describe(
        search="Search for a dev blog by text content"
    )
    async def devblog(self, interaction: Interaction, search: str) -> None:
        """Fetch a World of Warships dev blog, either search for text or
        leave blank to get latest."""
        dbc = self.bot.dev_blog_cache
        try:
            blog = next(i for i in dbc if i.id == int(search))
            embed = await blog.make_embed()
            return await interaction.response.send_message(embed=embed)
        except StopIteration:
            # If a specific blog is not selected, send the browser view.
            txt = search.casefold()
            yes = [i for i in dbc if txt in f"{i.title} {i.text}".casefold()]
            view = DevBlogView(interaction.user, pages=yes)
            return await view.handle_page(interaction)

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)


async def setup(bot: PBot) -> None:
    """Load the Dev Blog Cog into the bot."""
    await bot.add_cog(DevBlog(bot))
