"""Handling of Flashscore Competitions"""
from __future__ import annotations

import logging
import typing

import asyncpg
import discord
from lxml import html

from ext.utils import flags

from .abc import FlashScoreItem
from .constants import FLASHSCORE, LOGO_URL


if typing.TYPE_CHECKING:
    from core import Bot


logger = logging.getLogger("flashscore.competition")


class Competition(FlashScoreItem):
    """An object representing a Competition on Flashscore"""

    # Constant
    emoji: typing.ClassVar[str] = "🏆"

    def __init__(
        self,
        fsid: typing.Optional[str],
        name: str,
        country: typing.Optional[str],
        url: typing.Optional[str],
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

        self.logo_url: typing.Optional[str] = None
        self.country: typing.Optional[str] = country
        self.score_embeds: list[discord.Embed] = []

        # Table Imagee
        self.table: typing.Optional[str] = None

    @classmethod
    def from_record(cls, record: asyncpg.Record):
        """Generate a Competition from an asyncpg.Record"""
        i = record
        comp = Competition(i["id"], i["name"], i["country"], i["url"])
        comp.logo_url = i["logo_url"]
        return comp

    def __str__(self) -> str:
        return self.title

    def __hash__(self):
        return hash((self.title, self.id, self.url))

    def __eq__(self, other: typing.Any) -> bool:
        if other is None:
            return False

        if self.title == other.title:
            return True
        if self.id is not None and self.id == other.id:
            return True
        return self.url == other.url

    @classmethod
    async def by_link(cls, bot: Bot, link: str) -> Competition:
        """Create a Competition Object from a flashscore url"""
        page = await bot.browser.new_page()
        try:
            await page.goto(link, timeout=5000)
            await page.locator(".heading").wait_for()
            tree = html.fromstring(await page.content())
        finally:
            await page.close()

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
    def flag(self) -> str:
        """Get the flag using transfer_tools util"""
        if not self.country:
            return ""
        return flags.get_flag(self.country)

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        else:
            return self.name


async def save_comp(bot: Bot, comp: Competition) -> None:
    """Save the competition to the bot database"""
    sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
             VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
             (country, name, logo_url, url) =
             (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
             """

    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(
                sql, comp.id, comp.country, comp.name, comp.logo_url, comp.url
            )
    bot.competitions.add(comp)
    logger.info("saved competition. %s %s %s", comp.name, comp.id, comp.url)
