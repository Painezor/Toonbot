"""Utility Component for fetching from footballgroundmap.com"""
from __future__ import annotations

from typing import List, NoReturn, Optional, ClassVar, TYPE_CHECKING
from urllib.parse import quote_plus

from discord import Embed
from lxml import html

from ext.utils.embed_utils import get_colour

if TYPE_CHECKING:
    from core import Bot


# TODO: Store stadiums to database to allow for autocompletes, or find autocompleter on footballgroundmap
class Stadium:
    """An object representing a football Stadium from football ground map.com"""
    __slots__ = {'url': 'A Url representing a link to this stadium on football ground map',
                 'name': 'The name of the stadium',
                 'team': 'The team that plays at this stadium',
                 'league': 'The league of the team that plays at this stadium',
                 'country': 'The country this stadium is in',
                 'team_badge': 'The badge of the team that plays at this stadium',
                 'image': 'A link to an image of this stadium',
                 'current_home': 'A list of teams this ground is the current home of',
                 'former_home': 'A list of teams that this ground is the current home of',
                 'map_link': 'A link to a map to this stadium',
                 'address': 'A link to the address of this stadium',
                 'capacity': 'The maximum capacity of this stadium',
                 'cost': 'The cost of this stadium to build',
                 'website': 'A link to the website of this stadium',
                 'attendance_record': 'The attendance record of this stadium'}

    bot: ClassVar[Bot] = None

    def __init__(self, bot: Bot, **kwargs):

        if self.__class__.bot is None:
            self.__class__.bot = bot

        self.url: Optional[str] = kwargs.pop('link', None)
        self.name: Optional[str] = kwargs.pop('name', None)
        self.team: Optional[str] = kwargs.pop('team', None)
        self.league: Optional[str] = kwargs.pop('league', None)
        self.country: Optional[str] = kwargs.pop('country', None)
        self.team_badge: Optional[str] = kwargs.pop('team_badge', None)
        self.image: Optional[str] = kwargs.pop('image', None)
        self.current_home: List[str] = kwargs.pop('current_home', [])
        self.former_home: List[str] = kwargs.pop('former_home', [])
        self.map_link: Optional[str] = kwargs.pop('map_link', None)
        self.address: Optional[str] = kwargs.pop('address', None)
        self.capacity: Optional[int] = kwargs.pop('capacity', None)
        self.cost: Optional[str] = kwargs.pop('cost', None)
        self.website: Optional[str] = kwargs.pop('website', None)
        self.attendance_record: int = kwargs.pop('attendance_record', 0)

    async def fetch_more(self) -> NoReturn:
        """Fetch more data about a target stadium"""
        async with self.bot.session.get(self.url) as resp:
            match resp.status:
                case 200:
                    src = await resp.read()
                    src = src.decode('ISO-8859-1')
                    tree = html.fromstring(src)
                case _:
                    raise ConnectionError(f'Error {resp.status} during fetch_more on {self.url}')

        self.image = ''.join(tree.xpath('.//div[@class="page-img"]/img/@src'))

        # Teams
        try:
            v = tree.xpath('.//tr/th[contains(text(), "Former home")]/following-sibling::td')[0]
            t = [f"[{x}]({y})" for x, y in list(zip(v.xpath('.//a/text()'), v.xpath('.//a/@href'))) if "/team/" in y]
            self.former_home = t
        except IndexError:
            pass

        try:
            v = tree.xpath('.//tr/th[contains(text(), "home to")]/following-sibling::td')[0]
            t = [f"[{x}]({y})" for x, y in list(zip(v.xpath('.//a/text()'), v.xpath('.//a/@href'))) if "/team/" in y]
            self.current_home = t
        except IndexError:
            pass

        self.map_link = ''.join(tree.xpath('.//figure/img/@src'))
        self.address = ''.join(tree.xpath('.//tr/th[contains(text(), "Address")]/following-sibling::td//text()'))
        self.capacity = ''.join(tree.xpath('.//tr/th[contains(text(), "Capacity")]/following-sibling::td//text()'))
        self.cost = ''.join(tree.xpath('.//tr/th[contains(text(), "Cost")]/following-sibling::td//text()'))
        self.website = ''.join(tree.xpath('.//tr/th[contains(text(), "Website")]/following-sibling::td//text()'))
        self.attendance_record = ''.join(
            tree.xpath('.//tr/th[contains(text(), "Record attendance")]/following-sibling::td//text()'))

    def __str__(self) -> str:
        return f"**{self.name}** ({self.country}: {self.team})"

    @property
    async def to_embed(self) -> Embed:
        """Create a discord Embed object representing the information about a football stadium"""
        e: Embed = Embed(title=self.name, url=self.url)
        e.set_footer(text="FootballGroundMap.com")

        await self.fetch_more()
        if self.team_badge:
            e.colour = await get_colour(self.team_badge)
            e.set_thumbnail(url=self.team_badge)

        if self.image:
            e.set_image(url=self.image.replace(' ', '%20'))

        if self.current_home:
            e.add_field(name="Home to", value=", ".join(self.current_home), inline=False)

        if self.former_home:
            e.add_field(name="Former home to", value=", ".join(self.former_home), inline=False)

        # Location
        if self.map_link:
            e.add_field(name="Location", value=f"[{self.address}]({self.map_link})", inline=False)
        elif self.address != "Link to map":
            e.add_field(name="Location", value=self.address, inline=False)

        # Misc Data.
        e.description = ""
        for x, y in [("Capacity", self.capacity), ("Record Attendance", self.attendance_record),
                     ("Cost", self.cost), ("Website", self.website)]:
            if x:
                e.description += f"{x}: {y}\n"
        return e


async def get_stadiums(bot: 'Bot', query: str) -> List[Stadium]:
    """Fetch a list of Stadium objects matching a user query"""
    async with bot.session.get(f'https://www.footballgroundmap.com/search/{quote_plus(query)}') as resp:
        tree = html.fromstring(await resp.text())

    stadiums: List[Stadium] = []

    for i in tree.xpath(".//div[@class='using-grid'][1]/div[@class='grid']/div"):
        team = ''.join(i.xpath('.//small/preceding-sibling::a//text()')).title()
        badge = i.xpath('.//img/@src')[0]
        comp_info = i.xpath('.//small/a//text()')

        if not comp_info:
            continue

        country = comp_info.pop(0)
        league = comp_info[0] if comp_info else None

        sub_nodes = i.xpath('.//small/following-sibling::a')
        for s in sub_nodes:
            stad = Stadium(bot)
            stad.name = ''.join(s.xpath('.//text()')).title()
            stad.url = ''.join(s.xpath('./@href'))

            if query.lower() not in stad.name.lower() + team.lower():
                continue  # Filtering.

            if stad not in stadiums:
                stad.team = team
                stad.team_badge = badge
                stad.country = country
                stad.league = league
                stadiums.append(stad)
    return stadiums
