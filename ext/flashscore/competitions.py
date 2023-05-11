"""Handling of Flashscore Competitions"""
from __future__ import annotations

import logging
from lxml import html
from typing import TYPE_CHECKING, Any

from ext.flashscore.cache import FlashscoreCache

from .abc import BaseCompetition
from .constants import FLASHSCORE
from .fixture import HasFixtures
from .logos import HasLogo
from .table import HasTable
from .topscorers import HasScorers


logger = logging.getLogger("flashscore.competition")

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .fixture import Fixture


class Competition(BaseCompetition, HasFixtures, HasTable, HasLogo, HasScorers):
    """An object representing a Competition on Flashscore"""

    def __str__(self) -> str:
        return self.title

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Competition):
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

    async def parse_games(
        self, page: Page, cache: FlashscoreCache | None = None
    ) -> list[Fixture]:
        fixtures = await HasFixtures.parse_games(self, page, cache)
        for i in fixtures:
            i.competition = self
        return fixtures
