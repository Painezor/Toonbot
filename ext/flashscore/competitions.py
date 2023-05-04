"""Handling of Flashscore Competitions"""
from __future__ import annotations

import logging
from lxml import html
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, validator

from .constants import COMPETITION_EMOJI, FLASHSCORE
from .fixture import HasFixtures
from .logos import HasLogo
from .table import HasTable
from .topscorers import HasScorers


logger = logging.getLogger("flashscore.competition")

if TYPE_CHECKING:
    from playwright.async_api import Page


class Competition(BaseModel, HasFixtures, HasTable, HasLogo, HasScorers):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji = COMPETITION_EMOJI

    # Required
    name: str

    # Optional
    id: str | None = None
    country: str | None = None
    url: str | None = None
    logo_url: str | None = None

    # Fetched
    table: str | None = None

    @validator("country")
    def fmt_country(cls, value: str | None) -> str | None:
        if value and ":" in value:
            return value.split(":")[0]
        return value

    @validator("url")
    def fmt_url(cls, value: str | None) -> str | None:
        if value:
            return value.rstrip("/")
        return value

    def __str__(self) -> str:
        return self.title

    def __eq__(self, other: Any) -> bool:
        if other is None:
            return False

        if self.title == other.title:
            return True
        if self.id is not None and self.id == other.id:
            return True
        return self.url == other.url

    @classmethod
    async def by_link(cls, page: Page, link: str) -> Competition:
        """Create a Competition Object from a flashscore url"""
        await page.goto(link, timeout=5000)
        await page.locator(".heading").wait_for()
        tree = html.fromstring(await page.content())

        try:
            xpath = './/h2[@class="breadcrumb"]//a/text()'
            country = "".join(tree.xpath(xpath)).strip()

            xpath = './/div[@class="heading__name"]//text()'
            name = tree.xpath(xpath)[0].strip()
        except IndexError:
            name = "Unidentified League"
            country = "Unidentified Country"

        # TODO: Extract the ID from the URL
        comp = cls(name=name, country=country, url=link)

        logo = tree.xpath('.//div[contains(@class,"__logo")]/@style')

        try:
            shrt = FLASHSCORE + "/res/image/data/"
            comp.logo_url = shrt + logo[0].split("(")[1].strip(")")
        except IndexError:
            if ".png" in logo:
                comp.logo_url = logo

        return comp

    @property
    def markdown(self) -> str:
        return f"[{self.title}]({self.url})"

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        return self.name

    @property
    def ac_row(self) -> str:
        return f"{self.emoji} {self.title}"
