"""Grab XKCD Comics and output them in a view"""
from __future__ import annotations

import datetime
import logging
import random
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
    User: typing.TypeAlias = discord.User | discord.Member

logger = logging.getLogger("xkcd")


class XKCDView(view_utils.BaseView):
    """A View to browse XKCD Comics"""

    def __init__(self, invoker: User, index: int = 0):
        super().__init__(invoker)
        self.index: int = index

    async def update(self, interaction: Interaction):
        """Get the latest version of the view."""
        url = f"https://xkcd.com/{self.index}/info.0.json"
        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
            json = await resp.json()

            if self.index == -1:
                self.index = random.randrange(1, int(json["num"]))
                return await self.update(interaction)

        def parse() -> discord.Embed:
            """Convert JSON To Embed"""
            embed = discord.Embed(title=f"{json['num']}: {json['safe_title']}")

            year = int(json["year"])
            month = int(json["month"])
            time = datetime.datetime(year, month, int(json["day"]))
            embed.timestamp = time
            embed.set_footer(text=json["alt"])
            embed.set_image(url=json["img"])
            return embed

        self.clear_items()
        return await interaction.response.edit_message(embed=parse())


class XKCD(commands.Cog):
    """XKCD Grabber"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    xkcd = discord.app_commands.Group(
        name="xkcd", description="Get XKCD Comics"
    )

    @xkcd.command()
    async def latest(self, interaction: Interaction):
        """Get the latest XKCD Comic"""
        return await XKCDView(interaction.user).update(interaction)

    @xkcd.command()
    async def random(self, interaction: Interaction):
        """Get the latest XKCD Comic"""
        return await XKCDView(interaction.user, -1).update(interaction)

    @xkcd.command()
    async def number(self, interaction: Interaction, number: int):
        """Get XKCD Comic by number..."""
        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction.user, number).update(interaction)


async def setup(bot: Bot) -> None:
    """Load the XKCD cog into the bot"""
    return await bot.add_cog(XKCD(bot))
