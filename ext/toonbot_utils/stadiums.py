"""Utility Component for fetching from footballgroundmap.com"""
from __future__ import annotations

import typing

import discord
from lxml import html

from ext.utils.embed_utils import get_colour

if typing.TYPE_CHECKING:
    from core import Bot


# TODO: Store stadiums to database to allow for autocomplete,
# or find autocomplete on footballgroundmap

# TODO: Replace with k, v in json
class Stadium:
    """An object representing a football Stadium from footballgroundmap.com"""

    __slots__ = {
        "url": "A Url representing a link to this stadium on football"
        " ground map",
        "name": "The name of the stadium",
        "team": "The team that plays at this stadium",
        "league": "The league of the team that plays at this stadium",
        "country": "The country this stadium is in",
        "team_badge": "The badge of the team that plays at this " "stadium",
        "image": "A link to an image of this stadium",
        "current_home": "A list of teams this ground is the current"
        " home of",
        "former_home": "A list of teams that this ground is the "
        "current home of",
        "map_link": "A link to a map to this stadium",
        "address": "A link to the address of this stadium",
        "capacity": "The maximum capacity of this stadium",
        "cost": "The cost of this stadium to build",
        "website": "A link to the website of this stadium",
        "attendance_record": "The attendance record of this stadium",
    }

    def __init__(self, **kwargs):
        self.url: str = kwargs.pop("url", None)
        self.name: str = kwargs.pop("name", None)
        self.team: typing.Optional[str] = kwargs.pop("team", None)
        self.league: typing.Optional[str] = kwargs.pop("league", None)
        self.country: typing.Optional[str] = kwargs.pop("country", None)
        self.team_badge: typing.Optional[str] = kwargs.pop("team_badge", None)
        self.image: typing.Optional[str] = kwargs.pop("image", None)
        self.current_home: list[str] = kwargs.pop("current_home", [])
        self.former_home: list[str] = kwargs.pop("former_home", [])
        self.map_link: typing.Optional[str] = kwargs.pop("map_link", None)
        self.address: typing.Optional[str] = kwargs.pop("address", None)
        self.capacity: typing.Optional[int] = kwargs.pop("capacity", None)
        self.cost: typing.Optional[str] = kwargs.pop("cost", None)
        self.website: typing.Optional[str] = kwargs.pop("website", None)
        self.attendance_record: int = kwargs.pop("attendance_record", 0)

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
            link = tree.xpath(xpath)[0]

            # TODO : unfuck this
            markdown = [
                f"[{x}]({y})"
                for x, y in list(
                    zip(link.xpath(".//a/text()"), link.xpath(".//a/@href"))
                )
                if "/team/" in y
            ]
            self.former_home = markdown
        except IndexError:
            pass

        try:
            xpath = (
                './/tr/th[contains(text(), "home to")]/following-sibling::td'
            )
            link = tree.xpath(xpath)[0]
            markdown = [
                f"[{x}]({y})"
                for x, y in list(
                    zip(link.xpath(".//a/text()"), link.xpath(".//a/@href"))
                )
                if "/team/" in y
            ]
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
        self.attendance_record = int("".join(tree.xpath(xpath)))

    def __str__(self) -> str:
        return f"**{self.name}** ({self.country}: {self.team})"

    async def to_embed(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.Embed:
        """Create a discord Embed object representing the information about
        a football stadium"""
        embed = discord.Embed(title=self.name, url=self.url)
        embed.set_footer(text="FootballGroundMap.com")

        await self.fetch_more(interaction)
        if self.team_badge:
            embed.colour = await get_colour(self.team_badge)
            embed.set_thumbnail(url=self.team_badge)

        if self.image:
            embed.set_image(url=self.image.replace(" ", "%20"))

        if self.current_home:
            embed.add_field(
                name="Home to",
                value=", ".join(self.current_home),
                inline=False,
            )

        if self.former_home:
            embed.add_field(
                name="Former home to",
                value=", ".join(self.former_home),
                inline=False,
            )

        # Location
        if self.map_link:
            embed.add_field(
                name="Location",
                inline=False,
                value=f"[{self.address}]({self.map_link})",
            )
        elif self.address != "Link to map":
            embed.add_field(name="Location", value=self.address, inline=False)

        # Misc Data.
        embed.description = ""
        for tup_1, tup_2 in [
            ("Capacity", self.capacity),
            ("Record Attendance", self.attendance_record),
            ("Cost", self.cost),
            ("Website", self.website),
        ]:
            if tup_1:
                embed.description += f"{tup_1}: {tup_2}\n"
        return embed
