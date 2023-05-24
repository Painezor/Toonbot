"""Mixin for fetching table from a flashscore item"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel

from .constants import ADS

if TYPE_CHECKING:
    from playwright.async_api import Page

    from .abc import BaseTeam


logger = logging.getLogger("flashscore.table")


class HasTable:
    """Attached to an object that can have standings"""

    url: str | None

    async def get_table(
        self, page: Page, button: str | None = None
    ) -> Table | None:
        """Get the table from a flashscore page"""
        url = self.base_url + "/standings"
        try:
            await page.goto(url, timeout=5000)
        except PWTimeout:
            logger.error("Timed out loading page %s", url)
            return

        if button:
            loc = page.locator("button")
            await loc.click(force=True)

        # Chaining Locators is fucking aids.
        # Thank you for coming to my ted talk.
        inner = page.locator(".tableWrapper, .draw__wrapper")
        outer = page.locator("div", has=inner)
        table_div = page.locator("div", has=outer).last

        try:
            await table_div.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            # Entry point not handled on fixtures from leagues.
            logger.error("Failed to find standings on %s", page.url)
            return None

        javascript = "ads => ads.forEach(x => x.remove());"
        await page.eval_on_selector_all(ADS, javascript)
        img = await table_div.screenshot(type="png")

        return Table(image=img, teams=[])

    # Overriden on Fixture
    @property
    def base_url(self) -> str:
        if self.url is None:
            raise AttributeError(f"No URL found on {self}")
        return self.url.rstrip("/")


class Table(BaseModel):
    image: bytes

    teams: list[BaseTeam] = []
