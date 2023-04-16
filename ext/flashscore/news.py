"""Class handling News Articles from Flashscore"""
import datetime
from lxml.html import HtmlElement

from .constants import FLASHSCORE


class NewsArticle:
    """A News Article from Flashscore"""

    description: str
    image: str
    provider: str
    title: str
    timestamp: datetime.datetime
    url: str

    def __init__(self, data: HtmlElement) -> None:
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
