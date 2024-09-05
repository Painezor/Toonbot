"""Mixin for fetching table from a flashscore item"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lxml import html
from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel

from ext.flashscore.cache import FSCache

from .abc import BaseTeam
from .constants import ADS

if TYPE_CHECKING:
    from playwright.async_api import Page


logger = logging.getLogger("flashscore.table")


class Table(BaseModel):
    image: bytes

    teams: list[BaseTeam] = []


class HasTable:
    """Attached to an object that can have standings"""

    url: str | None

    async def get_table(
        self,
        page: Page,
        button: str | None = None,
        cache: FSCache | None = None,
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
        loc = "div > div > .tableWrapper, div > div > .draw__wrapper"
        table_div = page.locator(loc).last

        try:
            await table_div.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            # Entry point not handled on fixtures from leagues.
            return await self.get_draw(page)

        tree = html.fromstring(await table_div.inner_html())

        teams: list[BaseTeam] = []
        for i in tree.xpath('.//div[@class="tableCellParticipant__block"]'):
            _ = i.xpath('.//a[@class="tableCellParticipant__name"]/text()')[0]
            url = i.xpath('.//a[@class="tableCellParticipant__name"]/@href')[0]
            id_ = url.split("/")[-2]

            if cache:
                team = cache.get_team(id_)
            else:
                team = None
            if team is None:
                team = BaseTeam(name=_, url=url, id=id_)
            teams.append(team)

        if cache:
            await cache.save_teams(teams)

        javascript = "ads => ads.forEach(x => x.remove());"
        await page.eval_on_selector_all(ADS, javascript)
        img = await table_div.screenshot(type="png")

        return Table(image=img, teams=teams)

    async def get_draw(self, page: Page) -> Table | None:
        url = self.base_url + "/draw"
        try:
            await page.goto(url, timeout=5000)
        except PWTimeout:
            logger.error("Timed out loading page %s", url)
            return  #

        loc = "div > div > .draw__wrapper"
        draw_div = page.locator(loc).last

        try:
            await draw_div.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            logger.error("Failed to find standings or draw on %s", page.url)

        javascript = "ads => ads.forEach(x => x.remove());"
        await page.eval_on_selector_all(ADS, javascript)
        img = await draw_div.screenshot(type="png")

        return Table(image=img, teams=[])

    # Overriden on Fixture
    @property
    def base_url(self) -> str:
        if self.url is None:
            raise AttributeError(f"No URL found on {self}")
        return self.url.rstrip("/")
