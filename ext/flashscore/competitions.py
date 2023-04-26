"""Handling of Flashscore Competitions"""
from __future__ import annotations

import logging
from lxml import html
from typing import TYPE_CHECKING, Any

from . import abc
from .constants import COMPETITION_EMOJI, LOGO_URL, FLASHSCORE

logger = logging.getLogger("flashscore.competition")

if TYPE_CHECKING:
    import asyncpg
    from playwright.async_api import Page


class Competition(abc.FSObject):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji = COMPETITION_EMOJI

    def __init__(
        self,
        fsid: str | None,
        name: str,
        country: str | None,
        url: str | None,
    ) -> None:
        # Sanitise inputs.
        if country is not None and ":" in country:
            country = country.split(":")[0]

        if url is not None:
            url = url.rstrip("/")

        if name and country and not url:
            nom = name.casefold().replace(" ", "-").replace(".", "")
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = FLASHSCORE + f"/football/{ctr}/{nom}"
        elif url and country and FLASHSCORE not in url:
            ctr = country.casefold().replace(" ", "-").replace(".", "")
            url = f"{FLASHSCORE}/football/{ctr}/{url}"
        elif fsid and not url:
            # https://www.flashscore.com/?r=1:jLsL0hAF ??
            url = f"https://www.flashscore.com/?r=2:{url}"

        super().__init__(fsid, name, url)

        self.logo_url: str | None = None
        self.country: str | None = country

        # Table Imagee
        self.table: str | None = None

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Competition:
        """Generate a Competition from an asyncpg.Record"""
        i = record
        comp = Competition(i["id"], i["name"], i["country"], i["url"])
        comp.logo_url = i["logo_url"]
        return comp

    def __str__(self) -> str:
        return self.title

    def __hash__(self) -> int:
        return hash((self.title, self.id, self.url))

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
        comp = cls(None, name, country, link)

        logo = tree.xpath('.//div[contains(@class,"__logo")]/@style')

        try:
            comp.logo_url = LOGO_URL + logo[0].split("(")[1].strip(")")
        except IndexError:
            if ".png" in logo:
                comp.logo_url = logo

        return comp

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        return self.name

    @property
    def ac_row(self) -> str:
        return f"{self.emoji} {self.title}"
