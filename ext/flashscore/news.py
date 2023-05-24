"""Class handling News Articles from Flashscore"""
from __future__ import annotations

import datetime
import logging
from lxml import html
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PWTimeout

from .constants import FLASHSCORE

if TYPE_CHECKING:
    from playwright.async_api import Page


logger = logging.getLogger("flashscore.news")


class HasNews:
    """Attached to an object that has News Available."""

    url: str | None

    async def get_news(self, page: Page) -> list[NewsArticle]:
        """Fetch a list of NewsArticles for Pagination"""

        url = self.base_url + "/news"
        try:
            await page.goto(url, timeout=5000)
        except PWTimeout:
            logger.error("Timed out loading page %s", url)
            return []

        locator = page.locator(".rssNew")
        try:
            await locator.wait_for()
        except PWTimeout:
            logger.error("Failed finding .rssNew on %s", page.url)

        articles: list[NewsArticle] = []
        for i in await locator.all():
            articles.append(NewsArticle(html.fromstring(await i.inner_html())))
        return articles

    @property
    def base_url(self) -> str:
        if self.url is None:
            raise AttributeError(f"No URL found on {self}")
        return self.url.rstrip("/")


class NewsArticle:
    """A News Article from Flashscore"""

    description: str
    image: str
    provider: str
    title: str
    timestamp: datetime.datetime
    url: str

    def __init__(self, data: html.HtmlElement) -> None:
        xpath = './/div[@class="rssNews__title"]/text()'
        self.title = "".join(data.xpath(xpath))

        xpath = ".//a/@href"
        self.url = FLASHSCORE + "".join(data.xpath(xpath))

        self.image = "".join(data.xpath(".//img/@src"))

        xpath = './/div[@class="rssNews__perex"]/text()'
        self.description = "".join(data.xpath(xpath))

        xpath = './/div[@class="rssNews__provider"]/text()'
        provider = "".join(data.xpath(xpath)).split(",")

        time = datetime.datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
        self.timestamp = time
        self.provider = provider[-1].strip()
