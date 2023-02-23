"""Tracker for the World of Warships Development Blog"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from asyncpg import Record
from discord import (
    Interaction,
    Message,
    Colour,
    Embed,
    HTTPException,
    TextChannel,
)
from discord.app_commands import (
    Choice,
    command,
    autocomplete,
    describe,
    default_permissions,
)
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.utils import utcnow
from lxml import html
from lxml.html import HtmlElement

from ext.utils.flags import get_flag
from ext.utils.view_utils import add_page_buttons, BaseView

if TYPE_CHECKING:
    from painezBot import PBot

import yatg

logger = logging.getLogger("Devblog")

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


def get_emote(node: HtmlElement):
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

    bot: PBot = None

    def __init__(self, _id: int, title: str = None, text: str = None):
        self.id: int = _id
        self.title: str = title
        self.text: str = text

    @property
    def ac_row(self) -> str:
        """Autocomplete representation"""
        return f"{self.id} {self.title} {self.text}".lower()

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
        self.title = title.split(" - Development")[0]

        self.text = tree.xpath('.//div[@class="article__content"]')[
            0
        ].text_content()

        if self.text:
            logger.info(f"Storing Dev Blog #{self.id}")
        else:
            return

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO dev_blogs (id, title, text)
                       VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""
                await connection.execute(q, self.id, self.title, self.text)

    async def parse(self):
        """Get Embed from the Dev Blog page"""
        async with self.bot.session.get(self.url) as resp:
            tree = html.fromstring(await resp.text())

        article_html = tree.xpath('.//div[@class="article__content"]')[0]

        blog_number = self.id
        title = "".join(tree.xpath('.//h2[@class="article__title"]/text()'))
        e: Embed = Embed(
            colour=0x00FFFF,
            url=self.url,
            description="",
            timestamp=utcnow(),
            title=title,
        )

        e.set_author(
            name=f"World of Warships Development Blog #{blog_number}",
            url="https://blog.worldofwarships.com/",
        )
        e.set_thumbnail(
            url="https://cdn.discordapp.com/emojis/814963209978511390.png"
        )

        output = []

        def parse(node: HtmlElement):
            """Parse a single node"""

            if node.tag == "img":
                e.set_image(url="http:" + node.attrib["src"])
                return ""

            out = []

            # Nuke excessive whitespace.
            if node.text is not None:
                txt = node.text.strip()
            else:
                txt = None

            match node.tag:
                case "table" | "tr":
                    for sub_node in node.iterdescendants():
                        sub_node.text = (
                            None
                            if sub_node.text is None
                            else sub_node.text.strip()
                        )

                    string = html.tostring(node, encoding="unicode")
                    out.append(yatg.html_2_ascii_table(string))
                    for sub_node in node.iterdescendants():
                        sub_node.text = None
                case "tbody" | "tr" | "td":
                    pass
                case "i":
                    if node.attrib.get("class", None) == "superShipStar":
                        out.append(r"\⭐")
                    else:
                        logging.error(
                            "unhandled 'i' tag %s containing text %s",
                            node.attrib["class"],
                            txt,
                        )
                case "p":
                    if node.text_content():
                        if node.getprevious() is not None and node.text:
                            out.append("\n")
                        out.append(txt)
                        if (
                            node.getnext() is not None
                            and node.getnext().tag == "p"
                        ):
                            out.append("\n")
                case "div":
                    if node.attrib.get("class", None) == "article-cut":
                        out.append("\n")
                    else:
                        out.append(txt)
                case "ul" | "td" | "sup":
                    out.append(txt)
                case "em":
                    # Handle Italics
                    out.append(f"*{txt}*")
                case "strong" | "h3" | "h4":
                    # Handle Bold.
                    # Force line break if this is a standalone bold.
                    if not node.getparent().text:
                        output.append("\n")

                    if txt:
                        out.append(f"**{txt}** ")

                    if node.tail == ":":
                        out.append(":")
                        node.tail = None

                    if node.getnext() is None:
                        out.append("\n")

                case "span":
                    # Handle Ships
                    if node.attrib.get("class", None) == "ship":
                        sub_out = []

                        try:
                            if (
                                country := node.attrib.get("data-nation", None)
                            ) is not None:
                                sub_out.append(" " + get_flag(country))
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
                case "li":
                    out.append("\n")
                    if node.text:
                        match node.getparent().getparent().tag:
                            case "ul" | "ol" | "li":
                                out.append(f"∟○ {txt}")
                            case _:
                                out.append(f"• {txt}")

                    if node.getnext() is None:
                        if len(node) == 0:  # Number of children
                            out.append("\n")
                case "a":
                    out.append(f"[{txt}]({node.attrib['href']})")
                case "br":
                    out.append("\n")
                case _:
                    if node.text:
                        logging.error(
                            "Unhandled node found: %s|%s|%s",
                            node.tag,
                            txt,
                            node.tail,
                        )
                        out.append(txt)

            for sub_node in node.iterchildren():
                if node.tag != "table":
                    out.append(parse(sub_node))

            if node.tail:
                tail = node.tail.strip() + " "

                match node.getparent().tag:
                    case "span":
                        # Handle Ships
                        _cls = node.getparent().attrib.get("class", None)
                        if _cls == "ship":
                            out.append(f"**{tail}**")
                        else:
                            out.append(tail)
                    case "em":
                        out.append(f"*{tail}*")
                    case _:
                        out.append(tail)

            return "".join([i for i in out if i])

        for elem in article_html.iterchildren():
            output.append(parse(elem))

        if len(output := "".join(output)) > 4000:
            trunc = f"…\n[Read Full Article]({self.url})"
            e.description = output.ljust(4000)[: 4000 - len(trunc)] + trunc
        else:
            e.description = output
        return e


class DevBlogView(BaseView):
    """Browse Dev Blogs"""

    def __init__(self, interaction: Interaction, pages: list[Record]) -> None:
        super().__init__(interaction)
        self.pages: list[Blog] = pages
        self.index: int = 0

    async def update(self) -> Message:
        """Push the latest version of the view to discord."""
        self.clear_items()
        add_page_buttons(self)
        e = await self.pages[self.index].parse()
        return await self.interaction.client.reply(
            self.interaction, embed=e, ephemeral=True
        )


async def db_ac(interaction: Interaction, current: str) -> list[Choice]:
    """Autocomplete dev blog by text"""
    blogs = [
        i
        for i in interaction.client.dev_blog_cache
        if current.lower() in i.ac_row
    ]
    return [
        Choice(name=f"{i.id}: {i.title}"[:100], value=str(i.id)) for i in blogs
    ][
        :-25:-1
    ]  # Last 25 items reversed


class DevBlog(Cog):
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

    @loop(seconds=60)
    async def blog_loop(self) -> None:
        """Loop to get the latest dev blog articles"""
        if self.bot.session is None or not self.bot.dev_blog_cache:
            return

        async with self.bot.session.get(
            "https://blog.worldofwarships.com/rss-en.xml"
        ) as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding="utf8"))

        articles = tree.xpath(".//item")
        for i in articles:
            try:
                link = next(
                    lnk
                    for lnk in i.xpath(".//guid/text() | .//link/text()")
                    if ".ru" not in lnk
                )
            except StopIteration:
                continue

            try:
                blog_id = int(link.split("/")[-1])
            except ValueError:
                logging.error(f"Could not parse blog_id from link {link}")
                continue

            if blog_id in [r.id for r in self.bot.dev_blog_cache]:
                continue

            blog = Blog(blog_id)

            await blog.save_to_db()
            await self.get_blogs()

            e = await blog.parse()

            for x in self.bot.dev_blog_channels:
                try:
                    ch = self.bot.get_channel(x)
                    await ch.send(embed=e)
                except (AttributeError, HTTPException):
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
                q = """SELECT * FROM dev_blogs"""
                records = await connection.fetch(q)

        self.bot.dev_blog_cache = [
            Blog(r["id"], title=r["title"], text=r["text"]) for r in records
        ]

    @command()
    @default_permissions(manage_channels=True)
    async def blog_tracker(
        self, interaction: Interaction, enabled: Literal["on", "off"]
    ) -> Message:
        """Enable/Disable the World of Warships dev blog tracker
        in this channel."""

        await interaction.response.defer(thinking=True)

        if enabled:
            q = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
            args = [interaction.channel.id]
            output = "New Dev Blogs will no longer be sent to this channel."
            colour = Colour.red()
        else:
            q = """INSERT INTO dev_blog_channels (channel_id, guild_id)
                   VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            args = [interaction.channel.id, interaction.guild.id]
            output = "new Dev Blogs will now be sent to this channel."
            colour = Colour.green()

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(q, *args)

        await self.update_cache()

        e = Embed(colour=colour, title="Dev Blog Tracker", description=output)

        u = self.bot.user
        e.set_author(icon_url=u.display_avatar.url, name=u.name)
        return await self.bot.reply(interaction, embed=e)

    @command()
    @autocomplete(search=db_ac)
    @describe(search="Search for a dev blog by text content")
    async def devblog(self, interaction: Interaction, search: str) -> Message:
        """Fetch a World of Warships dev blog, either search for text or
        leave blank to get latest."""

        await interaction.response.defer(thinking=True)

        dbc = self.bot.dev_blog_cache
        try:
            blog = next(i for i in dbc if i.id == int(search))
            e = await blog.parse()
            return await self.bot.reply(interaction, embed=e, ephemeral=True)
        except StopIteration:
            # If a specific blog is not selected, send the browser view.
            s = search.lower()
            matches = [i for i in dbc if s in f"{i.title} {i.text}".lower()]
            view = DevBlogView(interaction, pages=matches)
            return await view.update()

    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)


async def setup(bot: PBot) -> None:
    """Load the Dev Blog Cog into the bot."""
    await bot.add_cog(DevBlog(bot))
