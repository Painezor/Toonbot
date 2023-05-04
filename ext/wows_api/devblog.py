"""Fetching and parsing of World of Warships Dev Blogs."""
import logging
from lxml import html

import aiohttp

from .emojis import SHIP_EMOTES, NATION_FLAGS

logger = logging.getLogger("api.devblog")

RSS_FEED = "https://blog.worldofwarships.com/rss-en.xml"


async def get_dev_blogs() -> list[int]:
    """Get all recent dev blogs."""
    async with aiohttp.ClientSession() as session:
        async with session.get(RSS_FEED) as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding="utf8"))

    blog_ids: list[int] = []
    for i in tree.xpath(".//item"):
        try:
            links = i.xpath(".//guid/text() | .//link/text()")
            link = next(lnk for lnk in links if ".ru" not in lnk)
        except StopIteration:
            continue

        try:
            blog_ids.append(int(link.rsplit("/", maxsplit=1)[-1]))
        except ValueError:
            logger.error("Could not parse blog_id from link %s", link)
            continue
    return blog_ids


def get_emote(node: html.HtmlElement):
    """Get the appropriate emote for ship class & rarity combination"""
    if (s_class := node.attrib.get("data-type", None)) is None:
        return ""

    if node.attrib.get("data-premium", None) == "true":
        return SHIP_EMOTES[s_class]["premium"]

    if node.attrib.get("data-special", None) == "true":
        return SHIP_EMOTES[s_class]["special"]

    return SHIP_EMOTES[s_class]["normal"]


class DevBlog:
    """A world of Warships DevBlog"""

    def __init__(
        self,
        _id: int,
        title: str | None = None,
        text: str | None = None,
    ):
        self.id: int = _id  # pylint: disable=C0103
        self._cached_title: str | None = title
        self._cached_text: str | None = text

        self.title: str
        self.text: str = ""

        self.images: list[str] = []

    @property
    def ac_row(self) -> str:
        """Autocomplete representation"""
        return f"{self.id} {self._cached_title} {self._cached_text}"

    @property
    def url(self) -> str:
        """Get the link for this blog"""
        return f"https://blog.worldofwarships.com/blog/{self.id}"

    async def fetch_text(self) -> None:
        """Get the fully formatted text for the devblog"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as resp:
                tree = html.fromstring(await resp.text())

        article_html = tree.xpath('.//div[@class="article__content"]')[0]
        self.text = ""
        self.parse(article_html)
        self.title = tree.xpath('.//h2[@class="article__title"]/text()')[0]

    def cache_title(self, title: str) -> None:
        """Cache the title of the dev blog"""
        self._cached_title = title

    def cache_text(self, text: str) -> None:
        """Cache the text of the dev blog"""
        self._cached_text = text

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
                self.text += " " + NATION_FLAGS[country.casefold()]

            if node.attrib.get("data-type", False):
                self.text += get_emote(node)

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
        if node.text_content():
            if node.getprevious() is not None and node.text:
                self.text += f"\n{node.text}"
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
        if node.text is not None and node.text.strip():
            # TODO: Delete this assertion.
            assert isinstance(node.tag, str)
            try:
                {
                    "a": self.parse_a(node),
                    "br": self.parse_br(node),
                    "div": self.parse_div_tag(node),
                    "em": self.parse_em(node),
                    "i": self.parse_info(node),
                    "h2": self.parse_header(node),
                    "h3": self.parse_header(node),
                    "h4": self.parse_header(node),
                    "img": self.parse_image(node),
                    "p": self.parse_p_tag(node),
                    "span": self.parse_span(node),
                    "strong": self.parse_header(node),
                    "sup": self.parse_p_tag(node),
                    "table": self.parse_table(node),
                    "u": self.parse_u(node),
                    "ol": self.parse_p_tag(node),
                    "ul": self.parse_p_tag(node),
                    "li": self.parse_list(node),
                }[str(node.tag)]
            except KeyError:
                tail = node.tail
                tag = node.tag
                text = node.text
                logger.error("Unhandled node: %s|%s|%s", tag, text, tail)
                return

        if is_tail:
            return

        if node.tag == "table":
            return

        for sub_node in node.iterchildren():
            self.parse(sub_node)

        if node.tail:
            node.text = node.tail
            node.tail = None
            self.parse(node, is_tail=True)
