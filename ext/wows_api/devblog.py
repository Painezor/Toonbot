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

    def __init__(self, _id: int, title: str = "", text: str = ""):
        self.id: int = _id  # pylint: disable=C0103
        self.title: str = title
        self.text: str = text

    @property
    def url(self) -> str:
        """Get the link for this blog"""
        return f"https://blog.worldofwarships.com/blog/{self.id}"

    async def fetch_text(self) -> html.HtmlElement:
        """Get the HTML content for a devblog"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as resp:
                tree = html.fromstring(await resp.text())

        self.title = tree.xpath('.//h2[@class="article__title"]/text()')[0]
        return tree.xpath('.//div[@class="article__content"]')[0]
