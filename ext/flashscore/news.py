"""Class handling News Articles from Flashscore"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from lxml import html


from .constants import FLASHSCORE

if TYPE_CHECKING:
    from playwright.async_api import Page


class HasNews:
    """Attached to an object that has News Available."""

    url: str | None

    async def get_news(self, page: Page) -> list[NewsArticle]:
        """Fetch a list of NewsArticles for Pagination"""
        await page.goto(f"{self.url}/news", timeout=5000)
        locator = page.locator(".rssNew")
        await locator.wait_for()

        articles: list[NewsArticle] = []
        for i in await locator.all():
            articles.append(NewsArticle(html.fromstring(await i.inner_html())))
        return articles


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
