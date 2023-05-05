"""Working with teams retrieved from flashscore"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal

from lxml import html

from .abc import BaseTeam
from .constants import FLASHSCORE
from .fixture import HasFixtures
from .logos import HasLogo
from .news import HasNews
from .squad import parse_squad_member
from .table import HasTable
from .transfers import FSTransfer
from .topscorers import HasScorers

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .cache import FlashscoreCache
    from .squad import SquadMember

TFOpts = Literal["All", "Arrivals", "Departures"]


class Team(BaseTeam, HasFixtures, HasTable, HasNews, HasScorers, HasLogo):
    """An object representing a Team from Flashscore"""

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    async def get_squad(
        self, page: Page, btn_name: str | None = None
    ) -> list[SquadMember]:
        """Get all squad members for a tournament"""
        url = f"{self.url}/squad"

        if page.url != url:
            await page.goto(url, timeout=300)

        loc = page.locator(".lineup")
        await loc.wait_for(timeout=300)

        if btn_name is not None:
            btn = page.locator(btn_name)
            await btn.wait_for(timeout=300)
            await btn.click(force=True)

        # to_click refers to a button press.
        tree = html.fromstring(await loc.inner_html())

        # Grab All Players.
        members: list[SquadMember] = []
        for i in tree.xpath('.//div[@class="lineup__rows"]'):
            # A header row with the player's position.
            xpath = "./div[@class='lineup__title']/text()"
            position = "".join(i.xpath(xpath)).strip()
            pl_rows = i.xpath('.//div[@class="lineup__row"]')
            members += [parse_squad_member(i, position) for i in pl_rows]
        return members

    async def get_transfers(
        self, page: Page, label: TFOpts, cache: FlashscoreCache
    ) -> list[FSTransfer]:
        """Get a list of transfers for the team retrieved from flashscore"""
        from .players import FSPlayer  # pylint disable=C0415

        if page.url != (url := f"{self.url}/transfers/"):
            await page.goto(url, timeout=500)
            await page.wait_for_selector("section#transfers", timeout=500)

        filters = page.locator("button.filter__filter", has_text=label).first
        await filters.click(force=True)

        show_more = page.locator("Show more")
        for _ in range(20):
            if await show_more.count():
                await show_more.click()

        tree = html.fromstring(await page.inner_html(".transferTab"))

        output: list[FSTransfer] = []
        for i in tree.xpath('.//div[@class="transferTab__row"]'):
            xpath = './/div[contains(@class, "team--from")]/div/a'
            name = "".join(i.xpath(xpath + "/text()"))
            link = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))

            try:
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name

            plr = FSPlayer(forename=forename, surname=surname, url=link)
            plr.country = i.xpath('.//span[@class="flag"]/@title')

            xpath = './/div[@class="transferTab__season"]/text()'
            _ = "".join(i.xpath(xpath))
            date = datetime.datetime.strptime(_, "%d.%m.%Y")

            _ = "".join(i.xpath(".//svg[1]/@class"))
            out = "in" if "icon--in" in _ else "out"

            _ = i.xpath('.//div[@class="transferTab__text"]/text()')
            type = "".join(_)

            trans = FSTransfer(date=date, direction=out, player=plr, type=type)
            xpath = './/div[contains(@class, "team--to")]/div/a'
            if team_name := "".join(i.xpath(xpath + "/text()")):
                tm_lnk = FLASHSCORE + "".join(i.xpath(xpath + "/@href"))
                team_id = tm_lnk.split("/")[-2]

                if (team := cache.get_team(team_id)) is None:
                    team = Team(id=team_id, name=team_name, url=tm_lnk)
                trans.team = team
            output.append(trans)
        return output
