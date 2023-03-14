"""Grab XKCD Comics and output them in a view"""
from __future__ import annotations

import datetime
import random
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot


class XKCDView(view_utils.BaseView):
    """A View to browse XKCD Comics"""

    def __init__(self, interaction: discord.Interaction[Bot], index: int = 0):
        super().__init__(interaction)
        self.index: int = index

    async def update(self):
        """Get the latest version of the view."""
        url = f"https://xkcd.com/{self.index}/info.0.json"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                err = f"{resp.status} connecting to {url}"
                return await self.bot.error(self.interaction, err)
            json = await resp.json()

            if self.index == -1:
                self.index = random.randrange(1, int(json["num"]))
                return await self.update()

        def parse() -> discord.Embed:
            """Convert JSON To Embed"""
            e = discord.Embed(title=f"{json['num']}: {json['safe_title']}")

            y = int(json["year"])
            m = int(json["month"])
            ts = datetime.datetime(y, m, int(json["day"]))
            e.timestamp = ts
            e.set_footer(text=json["alt"])
            e.set_image(url=json["img"])
            return e

        self.clear_items()
        return await self.interaction.edit_original_response(embed=parse())


class XKCD(commands.Cog):
    """XKCD Grabber"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    xkcd = discord.app_commands.Group(
        name="xkcd", description="Get XKCD Comics"
    )

    @xkcd.command()
    async def latest(self, interaction: discord.Interaction[Bot]):
        """Get the latest XKCD Comic"""

        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction).update()

    @xkcd.command()
    async def random(self, interaction: discord.Interaction[Bot]):
        """Get the latest XKCD Comic"""

        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction, -1).update()

    @xkcd.command()
    async def number(self, interaction: discord.Interaction[Bot], number: int):
        """Get XKCD Comic by number..."""
        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction, number).update()


async def setup(bot: Bot) -> None:
    """Load the XKCD cog into the bot"""
    return await bot.add_cog(XKCD(bot))
