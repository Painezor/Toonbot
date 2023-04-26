"""Grab XKCD Comics and output them in a view"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, TypeAlias, Any
import random

import discord
from discord.ext import commands

from ext.utils import view_utils

if TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[Bot | PBot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("xkcd")


class XKCDView(view_utils.AsyncPaginator):
    """A View to browse XKCD Comics"""

    def __init__(
        self,
        invoker: User,
        index: int | None,
        max_page: int,
        embed: discord.Embed,
    ):
        super().__init__(invoker, max_page)

        if index is None:
            index = random.randrange(1, max_page)
        elif index == -1:
            index = max_page
        self.index = index

        self.initial_embed = embed  # Used once.

    @classmethod
    async def create(
        cls, interaction: Interaction, *, start: int | None = -1
    ) -> XKCDView:
        """Spawn a view asynchronously"""
        url = "https://xkcd.com/info.0.json"
        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, resp.url)
            json = await resp.json()

        max_page = int(json["num"])

        if start is None:
            start = random.randrange(1, max_page)
        elif start == -1:
            start = max_page

        url = f"https://xkcd.com/{start}/info.0.json"
        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, resp.url)
            json = await resp.json()

        embed = cls.make_embed(json)

        view = XKCDView(interaction.user, start, max_page, embed)
        return view

    @staticmethod
    def make_embed(json: dict[str, Any]) -> discord.Embed:
        """Convert JSON To Embed"""
        embed = discord.Embed(title=f"{json['num']}: {json['safe_title']}")

        year = int(json["year"])
        month = int(json["month"])
        time = datetime.datetime(year, month, int(json["day"]))
        embed.timestamp = time
        embed.set_footer(text=json["alt"])
        embed.set_image(url=json["img"])
        return embed

    async def handle_page(self, interaction: Interaction):
        """Get the latest version of the view."""
        url = f"https://xkcd.com/{self.index}/info.0.json"
        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, resp.url)
            json = await resp.json()

        embed = self.make_embed(json)
        self.update_buttons()
        return await interaction.response.edit_message(embed=embed)


class XKCD(commands.Cog):
    """XKCD Grabber"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    xkcd = discord.app_commands.Group(
        name="xkcd", description="Get XKCD Comics"
    )

    @xkcd.command()
    async def latest(self, interaction: Interaction) -> None:
        """Get the latest XKCD Comic"""
        view = await XKCDView.create(interaction, start=-1)
        embed = view.initial_embed
        await interaction.response.send_message(view=view, embed=embed)

    @xkcd.command()
    async def random(self, interaction: Interaction) -> None:
        """Get the latest XKCD Comic"""
        view = await XKCDView.create(interaction)
        embed = view.initial_embed
        await interaction.response.send_message(view=view, embed=embed)

    @xkcd.command(name="number")
    async def num(self, interaction: Interaction, number: int) -> None:
        """Get XKCD Comic by number..."""
        view = await XKCDView.create(interaction, start=number)
        embed = view.initial_embed
        await interaction.response.send_message(view=view, embed=embed)


async def setup(bot: Bot) -> None:
    """Load the XKCD cog into the bot"""
    return await bot.add_cog(XKCD(bot))
