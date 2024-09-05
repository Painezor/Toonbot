"""Lookups of Live Football Data for teams, fixtures, and competitions."""
from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, TypeAlias
from urllib.parse import quote_plus

import discord
from discord.ext import commands
from lxml import html

from ext.utils import embed_utils, view_utils

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("stadiums")


class Stadium:
    """An object representing a football Stadium from footballgroundmap.com"""

    address: str = ""
    attendance_record: str = ""
    capacity: int = 0
    cost: str = ""

    country: str = ""
    image: str = ""
    map_link: str = ""
    name: str = ""
    team: str = ""
    team_badge: str = ""
    website: str = ""
    url: str = ""

    current_home: list[str] = dataclasses.field(default_factory=list)
    former_home: list[str] = dataclasses.field(default_factory=list)

    league: str | None = None

    def __init__(self, data: dict[str, Any]):
        for k, val in data.items():
            setattr(self, k, val)

    async def fetch_more(self, interaction: discord.Interaction[Bot]) -> None:
        """Fetch more data about a target stadium"""
        bot = interaction.client
        async with bot.session.get(self.url) as resp:
            if resp.status != 200:
                err = f"Error {resp.status} fetch_more on {self.url}"
                raise ConnectionError(err)

            src = await resp.read()
            src = src.decode("ISO-8859-1")
            tree = html.fromstring(src)

        self.image = "".join(tree.xpath('.//div[@class="page-img"]/img/@src'))

        # Teams
        try:
            xpath = (
                './/tr/th[contains(text(), "Former home")]'
                "/following-sibling::td"
            )
            _ = tree.xpath(xpath)[0]
            names = tree.xpath(".//a/text()")
            links = tree.xpath(".//a/@href")

            markdown: list[str] = []
            for name, url in list(zip(names, links)):
                if "/team/" in url:
                    markdown.append(f"[{name}]({url})")
            self.former_home = markdown
        except IndexError:
            pass

        try:
            xpath = (
                './/tr/th[contains(text(), "home to")]/following-sibling::td'
            )
            _ = tree.xpath(xpath)[0]
            names = tree.xpath(".//a/text()")
            links = tree.xpath(".//a/@href")

            markdown: list[str] = []
            for name, url in list(zip(names, links)):
                if "/team/" in url:
                    markdown.append(f"[{name}]({url})")
            self.current_home = markdown
        except IndexError:
            pass

        self.map_link = "".join(tree.xpath(".//figure/img/@src"))

        xpath = (
            './/tr/th[contains(text(), "Address")]'
            "/following-sibling::td//text()"
        )
        self.address = "".join(tree.xpath(xpath))

        xpath = (
            './/tr/th[contains(text(), "Capacity")]'
            "/following-sibling::td//text()"
        )
        self.capacity = int("".join(tree.xpath(xpath)).replace(",", ""))

        xpath = (
            './/tr/th[contains(text(), "Cost")]/following-sibling::td//text()'
        )
        self.cost = "".join(tree.xpath(xpath))

        xpath = (
            './/tr/th[contains(text(), "Website")]'
            "/following-sibling::td//text()"
        )
        self.website = "".join(tree.xpath(xpath))

        xpath = (
            './/tr/th[contains(text(), "Record attendance")]'
            "/following-sibling::td//text()"
        )
        self.attendance_record = "".join(tree.xpath(xpath))

    def __str__(self) -> str:
        return f"**{self.name}** ({self.country}: {self.team})"

    async def to_embed(self, interaction: Interaction) -> discord.Embed:
        """Create a discord Embed object representing the information about
        a football stadium"""
        embed = discord.Embed(title=self.name, url=self.url)
        embed.set_footer(text="FootballGroundMap.com")

        await self.fetch_more(interaction)
        if self.team_badge:
            embed.colour = await embed_utils.get_colour(self.team_badge)
            embed.set_thumbnail(url=self.team_badge)

        if self.image:
            embed.set_image(url=self.image.replace(" ", "%20"))

        if self.current_home:
            value = ", ".join(self.current_home)
            embed.add_field(name="Home to", value=value, inline=False)

        if self.former_home:
            value = ", ".join(self.former_home)
            embed.add_field(name="Former home to", value=value, inline=False)

        # Location
        if self.map_link:
            value = f"[{self.address}]({self.map_link})"
            embed.add_field(name="Location", inline=False, value=value)
        elif self.address != "Link to map":
            embed.add_field(name="Location", value=self.address, inline=False)

        # Misc Data.
        embed.description = ""
        if self.capacity:
            embed.description += f"Capacity: {self.capacity}\n"
        if self.attendance_record:
            embed.description += f"Max Attendance: {self.attendance_record}\n"
        if self.cost:
            embed.description += f"Cost: {self.cost}"
        if self.website:
            embed.description += f"WEbsite: {self.website }"
        return embed


class StadiumBrowser(view_utils.DropdownPaginator):
    """View for asking user to select a specific fixture"""

    def __init__(self, invoker: User, stadiums: list[Stadium]):
        embed = discord.Embed(title="Choose a Stadium")

        options: list[discord.SelectOption] = []
        rows: list[str] = []
        for i in stadiums:
            ctr = i.country.upper() + ": " if i.country else ""
            desc = f"{i.name} ({ctr}{i.team})"
            opt = discord.SelectOption(label=i.name[:100], value=desc[:100])
            opt.description = desc
            opt.emoji = "🏟️"
            rows.append(f"[{desc}]({i.url})")
            options.append(opt)

        super().__init__(invoker, embed, rows, options, 25)

        self.stadiums = stadiums

    @discord.ui.select(placeholder="Select a Stadium")
    async def dropdown(self, itr: Interaction, sel: discord.ui.Select) -> None:
        for i in self.stadiums:
            ctr = i.country.upper() + ": " if i.country else ""
            if f"{i.name} ({ctr}{i.team})" in sel.values:
                embed = await i.to_embed(itr)
                await itr.response.edit_message(embed=embed, view=self)
                return


async def get_stadiums(interaction: Interaction, query: str) -> list[Stadium]:
    """Fetch a list of Stadium objects matching a user query"""
    uri = f"https://www.footballgroundmap.com/search/{quote_plus(query)}"

    async with interaction.client.session.get(url=uri) as resp:
        tree = html.fromstring(await resp.text())

    stadiums: list[Stadium] = []

    xpath = ".//div[@class='using-grid'][1]/div[@class='grid']/div"

    qry = query.casefold()
    for i in tree.xpath(xpath):
        xpath = ".//small/preceding-sibling::a//text()"
        team = "".join(i.xpath(xpath)).title()
        badge = i.xpath(".//img/@src")[0]

        if not (comp_info := i.xpath(".//small/a//text()")):
            continue

        country = comp_info.pop(0)
        league = comp_info[0] if comp_info else None

        for i in i.xpath(".//small/following-sibling::a"):
            name = "".join(i.xpath(".//text()")).title()
            if qry not in f"{name} {team}".casefold():
                continue  # Filtering.

            stadium = Stadium({"name": name, "team": team})
            stadium.url = "".join(i.xpath("./@href"))
            stadium.team_badge = badge
            stadium.country = country
            stadium.league = league

            stadiums.append(stadium)
    return stadiums


# TODO: Stadium Transformer
class Stadiums(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    # UNIQUE commands
    @discord.app_commands.command()
    @discord.app_commands.describe(stadium="Search for a stadium by it's name")
    async def stadium(self, interaction: Interaction, stadium: str) -> None:
        """Lookup information about a team's stadiums"""
        if not (stadiums := await get_stadiums(interaction, stadium)):
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 No matches for {stadium}"
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        view = StadiumBrowser(interaction.user, stadiums)
        await interaction.response.send_message(
            view=view, embed=view.embeds[0]
        )


async def setup(bot: Bot):
    """Load the stadiums Cog into the bot"""
    await bot.add_cog(Stadiums(bot))
