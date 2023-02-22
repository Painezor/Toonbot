"""Grab XKCD Comics and output them in a view"""
from __future__ import annotations

import datetime
from random import randrange
from typing import TYPE_CHECKING

from discord import Embed
from discord.app_commands import Group
from discord.ext.commands import Cog

from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot
    from discord import Interaction
 

class XKCDView(BaseView):
    """A View to browse XKCD Comics"""
    def __init__(self, interaction: Interaction, index: int = 0):
        self.index: int = index
        super().__init__(interaction)

    async def update(self):
        """Get the latest version of the view."""
        async with self.bot.session.get(f"https://xkcd.com/info.{self.index}.json") as resp:
            match resp.status:
                case 200:
                    json = await resp.json()

                    if self.index == -1:
                        self.index = randrange(1, json['num'])
                        return await self.update()
                case _:
                    return await self.bot.error(self.interaction, 'Could not connect to XKCD API')

        def parse() -> Embed:
            """Convert JSON To Embed"""
            e = Embed(title=F"{json['num']}: {json['safe_title']}")
            e.timestamp = datetime.datetime(day=json['day'], month=json['month'], year=json['year'])
            e.set_footer(text=json['alt'])
            e.set_image(url=json['img'])
            return e

        self.clear_items()
        return await self.bot.reply(self.interaction, embed=parse())


class XKCD(Cog):
    """XKCD Grabber"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        XKCDView.bot = bot

    xkcd = Group(name="xkcd", description="Get XKCD Comics")

    @xkcd.command()
    async def latest(self, interaction: Interaction):
        """Get the latest XKCD Comic"""

        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction).update()

    @xkcd.command()
    async def random(self, interaction: Interaction):
        """Get the latest XKCD Comic"""

        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction, -1).update()

    @xkcd.command()
    async def number(self, interaction: Interaction, number: int):
        """Get XKCD Comic by number..."""

        await interaction.response.defer(thinking=True)
        return await XKCDView(interaction, number).update()


async def setup(bot: Bot) -> None:
    """Load the XKCD cog into the bot"""
    return await bot.add_cog(XKCD(bot))
