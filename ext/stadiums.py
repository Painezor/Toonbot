"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from __future__ import annotations

import logging
import importlib
import typing
from urllib.parse import quote_plus

# D.py
import discord
from discord.ext import commands

# Custom Utils
from lxml import html

from ext.utils import view_utils, image_utils
from ext.toonbot_utils import flashscore as fs, stadiums as stads

if typing.TYPE_CHECKING:
    from core import Bot

logger = logging.getLogger("stadiums")


class StadiumSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        stadiums: list[stads.Stadium],
    ):
        super().__init__(interaction)

        self.stadiums: list[stads.Stadium] = stadiums

        # Pagination
        s = [stadiums[i : i + 25] for i in range(0, len(stadiums), 25)]
        self.pages: list[list[stads.Stadium]] = s

        # Final result
        self.value: typing.Any = None

    async def update(self):
        """Handle Pagination"""
        stadiums: list[stads.Stadium] = self.pages[self.index]

        d = view_utils.ItemSelect(placeholder="Please choose a Stadium")
        e = discord.Embed(title="Choose a Stadium")
        e.description = ""

        for i in stadiums:
            ctr = i.country.upper() + ": " if i.country else ""
            desc = f"{i.team} ({ctr}{i.name})"
            d.add_option(label=i.name, description=desc, value=i.url)
            e.description += f"[{desc}]({i.url})\n"
        self.add_item(d)
        self.add_page_buttons(1)
        await self.interaction.edit_original_response(embed=e, view=self)


async def get_stadiums(
    interaction: discord.Interaction[Bot], query: str
) -> list[stads.Stadium]:
    """Fetch a list of Stadium objects matching a user query"""
    uri = f"https://www.footballgroundmap.com/search/{quote_plus(query)}"

    async with interaction.client.session.get(url=uri) as resp:
        tree = html.fromstring(await resp.text())

    stadiums: list[stads.Stadium] = []

    xp = ".//div[@class='using-grid'][1]/div[@class='grid']/div"

    qry = query.casefold()
    for i in tree.xpath(xp):

        xp = ".//small/preceding-sibling::a//text()"
        team = "".join(i.xpath(xp)).title()
        badge = i.xpath(".//img/@src")[0]

        if not (comp_info := i.xpath(".//small/a//text()")):
            continue

        country = comp_info.pop(0)
        league = comp_info[0] if comp_info else None

        for s in i.xpath(".//small/following-sibling::a"):
            name = "".join(s.xpath(".//text()")).title()
            if qry not in f"{name} {team}".casefold():
                continue  # Filtering.

            stadium = stads.Stadium()
            stadium.name = name
            stadium.url = "".join(s.xpath("./@href"))
            stadium.team = team
            stadium.team_badge = badge
            stadium.country = country
            stadium.league = league

            stadiums.append(stadium)
    return stadiums


class Stadiums(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        importlib.reload(fs)
        importlib.reload(view_utils)
        importlib.reload(image_utils)

    # UNIQUE commands
    @discord.app_commands.command()
    @discord.app_commands.describe(stadium="Search for a stadium by it's name")
    async def stadium(
        self, interaction: discord.Interaction[Bot], stadium: str
    ) -> discord.InteractionMessage:
        """Lookup information about a team's stadiums"""

        await interaction.response.defer(thinking=True)

        if not (std := await get_stadiums(interaction, stadium)):
            err = f"No stadiums found matching `{stadium}`"
            return await self.bot.error(interaction, err)

        await (view := StadiumSelect(interaction, std)).update()
        await view.wait()

        if view.value is None:
            err = "Timed out waiting for you to reply"
            return await self.bot.error(interaction, err, followup=False)

        target = next(i for i in std if i.url == view.value[0])

        embed = await target.to_embed(interaction)
        return await interaction.edit_original_response(embed=embed)


async def setup(bot: Bot):
    """Load the stadiums Cog into the bot"""
    await bot.add_cog(Stadiums(bot))
