"""Fetching and parsing of World of Warships Dev Blogs."""
import logging
from lxml import html

import aiohttp

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


class DevBlog:
    """A world of Warships DevBlog"""

    def __init__(
        self,
        _id: int,
        title: str | None = None,
        text: str | None = None,
    ):
        self.id: int = _id  # pylint: disable=C0103
        self.title: str | None = title
        self.text: str | None = text

    @property
    def ac_row(self) -> str:
        """Autocomplete representation"""
        return f"{self.id} {self.title} {self.text}".casefold()

    @property
    def url(self) -> str:
        """Get the link for this blog"""
        return f"https://blog.worldofwarships.com/blog/{self.id}"

    async def fetch_text(self) -> html.HtmlElement:
        """Get the fully formatted text for the devblog"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as resp:
                tree = html.fromstring(await resp.text())

        return tree.xpath('.//div[@class="article__content"]')[0]

    def cache_title(self, title: str) -> None:
        """Cache the title of the dev blog"""
        self.title = title

    def cache_text(self, text: str) -> None:
        """Cache the text of the dev blog"""
        self.text = text
