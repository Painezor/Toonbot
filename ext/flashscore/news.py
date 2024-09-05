"""Class handling News Articles from Flashscore"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from lxml import html
from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel

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
            logger.error("Timed out loading news page %s", url)
            return []

        locator = page.locator(".rssNew").last
        try:
            await locator.wait_for()
        except PWTimeout:
            logger.error("Failed finding .rssNew on %s", page.url)

        articles: list[NewsArticle] = []
        tree = html.fromstring(await page.content())
        for i in tree.xpath('.//a[@class="rssNew"]'):
            logger.info("Parsing news article... %s", page.url)
            try:
                articles.append(self.parse_team_news(i))
                continue
            except ValueError:
                pass

            try:
                articles.append(self.parse_fixture_news(i))
            except ValueError:
                continue

        logger.info(articles)
        return articles

    def parse_fixture_news(self, node: html.HtmlElement) -> NewsArticle:
        xpath = './/p[@class="rssNew__title"]/text()'
        title = "".join(node.xpath(xpath))

        xpath = ".//a/@href"
        url = FLASHSCORE + "".join(node.xpath(xpath))

        image = "".join(node.xpath(".//img/@src"))

        xpath = './/div[@class="rssNew__descriptionInfo"]/span/text()'
        provider = "".join(node.xpath(xpath)).split(",")

        time = datetime.datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
        provider = provider[-1].strip()
        return NewsArticle(
            title=title,
            url=url,
            image=image,
            timestamp=time,
            provider=provider,
        )

    def parse_team_news(self, node: html.HtmlElement) -> NewsArticle:
        xpath = './/p[@class="rssNew__title"]/text()'
        title = "".join(node.xpath(xpath))

        xpath = ".//a/@href"
        url = FLASHSCORE + "".join(node.xpath(xpath))

        image = "".join(node.xpath(".//img/@src"))
        xpath = './/div[@class="rssNew__descriptionInfo"]//text()'
        provider = node.xpath(xpath)

        time = datetime.datetime.strptime(provider[0], "%d.%m.%Y %H:%M")
        provider = provider[-1].strip()
        return NewsArticle(
            title=title,
            url=url,
            image=image,
            timestamp=time,
            provider=provider,
        )

    @property
    def base_url(self) -> str:
        if self.url is None:
            raise AttributeError(f"No URL found on {self}")
        return self.url.rstrip("/")


class NewsArticle(BaseModel):
    """A News Article from Flashscore"""

    image: str
    provider: str
    title: str
    timestamp: datetime.datetime | None
    url: str
