"""Utilities for working with transfers from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import datetime
import logging
from typing import Optional, TYPE_CHECKING
import typing

import aiohttp
import discord
from lxml import html

from ext.utils import view_utils, timed_events, flags, embed_utils

if TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
    User: typing.TypeAlias = discord.User | discord.Member
    T = typing.TypeVar("T", bound="SearchView")

FAVICON = (
    "https://upload.wikimedia.org/wikipedia/commons/f/fb/"
    "Transfermarkt_favicon.png"
)
TF = "https://www.transfermarkt.co.uk"

logger = logging.getLogger("transfermarkt")


class SearchResult:
    """A result from a transfermarkt search"""

    name: str
    link: str
    country: list[str] = []
    emoji: str = "🔎"

    def __init__(self, name: str, link: str) -> None:
        self.name = name
        self.link = link

    def __repr__(self) -> str:
        return f"SearchResult({self.__dict__})"

    def __hash__(self) -> int:
        return hash(self.link)

    @property
    def base_embed(self) -> discord.Embed:
        """A generic embed used for transfermarkt objects"""
        embed = discord.Embed(color=discord.Colour.dark_blue())
        embed.set_author(name="TransferMarkt")
        return embed

    @property
    def markdown(self) -> str:
        """Returns [Result Name](Result Link)"""
        return f"[{self.name}]({self.link})"

    @property
    def flags(self) -> typing.List[str]:
        """Return a flag for each of the object's countries"""
        # Return the 'earth' emoji if caller does not have a country
        if not self.country:
            return ["🌍"]

        return flags.get_flags(self.country)


class Competition(SearchResult):
    """An Object representing a competition from transfermarkt"""

    emoji: str = "🏆"

    def __init__(self, name: str, link: str, **kwargs: typing.Any) -> None:
        super().__init__(name, link)
        for k, val in kwargs.items():
            setattr(self, k, val)

    def __str__(self) -> str:
        flg = " ".join(self.flags)
        return f"{flg} {self.markdown}"

    def __bool__(self) -> bool:
        return bool(self.name)

    async def get_attendance(self) -> list[discord.Embed]:
        """Fetch attendances for the competition"""
        url = self.link.replace("startseite", "besucherzahlen")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
                tree = html.fromstring(await resp.text())

        xpath = (
            './/table[@class="items"]/tbody/tr[@class="odd" or @class="even"]'
        )
        rows = [StadiumAttendance(i) for i in tree.xpath(xpath)]

        embeds: list[discord.Embed] = []
        # Average
        embed = self.base_embed.copy()
        embed.title = f"Average Attendance data for {self.name}"
        embed.url = url
        rows.sort(key=lambda x: x.average, reverse=True)

        enu = [f"{i[0]}: {i[1].average_row}" for i in enumerate(rows, 1)]
        embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

        embed = self.base_embed.copy()
        embed.title = f"Total Attendance data for {self.name}"
        embed.url = url
        rows.sort(key=lambda x: x.total, reverse=True)

        enu = [f"{i[0]}: {i[1].total_row}" for i in enumerate(rows, 1)]
        embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

        embed = self.base_embed.copy()
        embed.title = f"Max Capacity data for {self.name}"
        embed.url = url
        rows.sort(key=lambda x: x.capacity, reverse=True)

        enu = [f"{i[0]}: {i[1].capacity_row}" for i in enumerate(rows, 1)]
        embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

        return embeds


class Team(SearchResult):
    """An object representing a Team from Transfermarkt"""

    emoji: str = "👕"
    league: Optional[Competition] = None

    def __init__(self, name: str, link: str, **kwargs: typing.Any) -> None:
        super().__init__(name, link)

        for k, value in kwargs.items():
            setattr(self, k, value)

    def __str__(self) -> str:
        flg = " ".join(self.flags)
        if self.league is not None:
            return f"{flg} {self.markdown} ({self.league.markdown})"
        return f"{flg} {self.markdown}"

    @property
    def badge(self) -> str:
        """Return a link to the team's badge"""
        number = self.link.split("/")[-1]
        return f"https://tmssl.akamaized.net/images/wappen/head/{number}.png"

    @property
    def base_embed(self) -> discord.Embed:
        """Return a discord embed object representing a team"""
        embed = super().base_embed
        embed.set_thumbnail(url=self.badge)
        embed.title = self.name
        embed.url = self.link
        return embed

    # TODO: Contract Class
    async def get_contracts(self) -> list[discord.Embed]:
        """Helper method for fetching contracts"""
        embed = self.base_embed
        embed.description = ""
        url = self.link.replace("startseite", "vertragsende")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
                tree = html.fromstring(await resp.text())

        embed.url = url
        embed.title = f"Expiring contracts for {self.name}"
        embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)

        rows: list[str] = []

        xpath = './/div[@class="large-8 columns"]/div[@class="box"]'
        for i in tree.xpath(xpath)[0].xpath(".//tbody/tr"):
            xpath = './/tm-tooltip[@data-type="player"]/a/@title'
            if not (name := "".join(i.xpath(xpath)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xpath = './/tm-tooltip[@data-type="player"]/a/@href'
            if not (link := "".join(i.xpath(xpath)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            if not name and not link:
                continue

            pos = "".join(i.xpath(".//td[1]//tr[2]/td/text()"))

            age = "".join(i.xpath("./td[2]/text()"))
            age = age.split("(", maxsplit=1)[-1].replace(")", "").strip()

            country = i.xpath(".//td[3]/img/@title")
            flag = flags.get_flags(country)
            date = "".join(i.xpath(".//td[4]//text()")).strip()

            time = datetime.datetime.strptime(date, "%b %d, %Y")
            expiry = timed_events.Timestamp(time).countdown

            option = "".join(i.xpath(".//td[5]//text()")).strip()
            option = f"\n∟ {option.title()}" if option != "-" else ""

            markdown = f"[{name}]({link})"
            flag = "" if not flag else flag
            rows.append(f"{flag} {markdown} {age}, {pos} ({expiry}){option}")

        if not rows:
            rows = ["No expiring contracts found."]

        return embed_utils.rows_to_embeds(embed, rows)

    # TODO: Rumour Class
    async def get_rumours(self) -> list[discord.Embed]:
        """Helper method for fetching rumours"""
        embed = self.base_embed

        url = self.link.replace("startseite", "geruechte")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
            tree = html.fromstring(await resp.text())

        embed.url = str(resp.url)
        embed.title = f"Transfer rumours for {self.name}"
        embed.set_author(name="Transfermarkt", url=resp.url, icon_url=FAVICON)

        rows: list[str] = []
        xpath = './/div[@class="large-8 columns"]/div[@class="box"]'
        for i in tree.xpath(xpath)[0].xpath(".//tbody/tr"):
            xpath = './/tm-tooltip[@data-type="player"]/a/@title'
            if not (name := "".join(i.xpath(xpath)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xpath = './/tm-tooltip[@data-type="player"]/a/@href'
            if not (link := "".join(i.xpath(xpath)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            pos = "".join(i.xpath(".//td[2]//tr[2]/td/text()"))
            country = i.xpath(".//td[3]/img/@title")
            flag = flags.get_flag(country)
            age = "".join(i.xpath("./td[4]/text()")).strip()
            team = "".join(i.xpath(".//td[5]//img/@alt"))

            team_link = "".join(i.xpath(".//td[5]//img/@href"))
            if TF not in team_link:
                team_link = TF + team_link

            source = "".join(i.xpath(".//td[8]//a/@href"))
            src = f"[Info]({source})"
            rows.append(
                f"{flag} **[{name}]({link})** ({src})\n{age},"
                f" {pos} [{team}]({team_link})\n"
            )

        if not rows:
            rows = ["No rumours about new signings found."]

        return embed_utils.rows_to_embeds(embed, rows)

    async def get_transfers(self) -> list[discord.Embed]:
        """Helper method for transfers button"""
        url = self.link.replace("startseite", "transfers")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("Status %s: %s", resp.status, url)
                tree = html.fromstring(await resp.text())

        base_embed = self.base_embed
        base_embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
        base_embed.url = url

        embeds: list[discord.Embed] = []
        xpath = (
            './/div[@class="box"][.//h2[contains(text(),"Arrivals")]]'
            '//tr[@class="even" or @class="odd"]'
        )

        inb = [Transfer.from_team(i, False, self) for i in tree.xpath(xpath)]
        if inb:
            embed = base_embed.copy()
            embed.title = f"Inbound Transfers for {embed.title}"
            embed.colour = discord.Colour.green()

            rows = [i.inbound for i in inb]
            embeds += embed_utils.rows_to_embeds(embed, rows)

        xpath = (
            './/div[@class="box"][.//h2[contains(text(),"Departures")]]'
            '//tr[@class="even" or @class="odd"]'
        )
        out = [Transfer.from_team(i, True, self) for i in tree.xpath(xpath)]
        if out:
            embed = base_embed.copy()
            embed.title = f"Outbound Transfers for {embed.title}"
            embed.colour = discord.Colour.red()
            rows = [i.outbound for i in out]
            embeds += embed_utils.rows_to_embeds(embed, rows)

        if not embeds:
            embed = base_embed
            embed.title = f"No transfers found {embed.title}"
            embed.colour = discord.Colour.orange()
            embeds = [embed]
        return embeds

    # TODO: Trophy Class
    async def get_trophies(self) -> list[discord.Embed]:
        """Get Trophies"""
        url = self.link.replace("startseite", "erfolge")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
            tree = html.fromstring(await resp.text())

        trophies: list[str] = []
        for i in tree.xpath('.//div[@class="box"][./div[@class="header"]]'):
            title = "".join(i.xpath(".//h2/text()"))

            xpath = './/div[@class="erfolg_infotext_box"]/text()'
            split = "".join(i.xpath(xpath)).split()
            dates = " ".join(split).replace(" ,", ",")
            trophies.append(f"**{title}**\n{dates}\n")

        embed = self.base_embed
        embed.title = f"{self.name} Trophy Case"

        if not trophies:
            trophies = ["No trophies found for team."]
        return embed_utils.rows_to_embeds(embed, trophies)


class PartialPlayer(SearchResult):
    """An Object representing a player from transfermarkt"""

    age: Optional[int] = None
    team: Optional[Team] = None
    position: Optional[str] = None
    picture: Optional[str] = None

    def __init__(self, name: str, link: str, **kwargs: typing.Any) -> None:
        super().__init__(name, link)

        for k, val in kwargs.items():
            setattr(self, k, val)

    def __repr__(self) -> str:
        return f"Player({self.__dict__})"

    def __str__(self) -> str:
        desc = [" ".join(self.flags), self.markdown, self.age, self.position]

        if self.team is not None:
            desc.append(self.team.markdown)
        return " ".join([str(i) for i in desc if i])


class Referee(SearchResult):
    """An object representing a referee from transfermarkt"""

    age: Optional[int] = None

    def __init__(self, name: str, link: str, **kwargs: typing.Any) -> None:
        super().__init__(name, link)

        for k, val in kwargs.items():
            setattr(self, k, val)

    def __str__(self) -> str:
        flg = " ".join(self.flags)
        output = f"{flg} {self.markdown} {self.age}"
        return output


class Staff(SearchResult):
    """An object representing a Trainer or Manager from Transfermarkt"""

    team: Optional[Team] = None
    age: Optional[int] = None
    job: Optional[str] = None
    picture: Optional[str] = None

    def __init__(self, name: str, link: str, **kwargs: typing.Any) -> None:
        super().__init__(name, link)

        for k, val in kwargs.items():
            setattr(self, k, val)

    def __str__(self) -> str:
        team = self.team.markdown if self.team is not None else ""
        markdown = self.markdown
        flg = " ".join(self.flags)
        return f"{flg} {markdown} {self.age}, {self.job} {team}".strip()


class Agent(SearchResult):
    """An object representing an Agent from transfermarkt"""


class Transfer:
    """An Object representing a transfer from transfermarkt"""

    player: PartialPlayer

    new_team: Team
    old_team: Team

    fee: str
    fee_link: str
    date: Optional[str] = None

    def __init__(self) -> None:
        pass

    @classmethod
    def from_loop(cls, data: typing.Any) -> Transfer:
        """Generated from the Transfer Ticker Loop"""
        tran = Transfer()
        name = "".join(data.xpath(".//td[1]//tr[1]/td[2]/a/text()")).strip()

        link = TF + "".join(data.xpath(".//td[1]//tr[1]/td[2]/a/@href"))

        player = PartialPlayer(name, link)

        # Box 1 - Player Info
        player.picture = "".join(data.xpath(".//img/@data-src"))
        player.position = "".join(data.xpath("./td[1]//tr[2]/td/text()"))

        # Box 2 - Age
        player.age = int("".join(data.xpath("./td[2]//text()")).strip())

        # Box 3 - Country
        player.country = data.xpath(".//td[3]/img/@title")

        tran.player = player

        # Box 4 - Old Team
        xpath = './/td[4]//img[@class="tiny_wappen"]//@title'
        o_t_name = "".join(data.xpath(xpath))

        xpath = './/td[4]//img[@class="tiny_wappen"]/parent::a/@href'
        o_t_link = TF + "".join(data.xpath(xpath))

        xpath = './/td[4]//img[@class="flaggenrahmen"]/following-sibling::a/'
        o_l_name = "".join(data.xpath(xpath + "@title"))
        if o_l_name:
            o_l_link = TF + "".join(data.xpath(xpath + "@href"))
        else:
            xpath = './/td[4]//img[@class="flaggenrahmen"]/parent::div/text()'
            o_l_name = "".join(data.xpath(xpath))
            o_l_link = ""

        o_l_link = o_l_link.replace("transfers", "startseite")
        if o_l_link:
            o_l_link = o_l_link.split("/saison_id", maxsplit=1)[0]

        xpath = './/td[4]//img[@class="flaggenrahmen"]/@alt'
        ctry = data.xpath(xpath)

        old_lg = Competition(o_l_name, o_l_link, country=ctry)
        tran.old_team = Team(o_t_name, o_t_link, league=old_lg, country=ctry)

        # Box 5 - New Team
        xpath = './/td[5]//img[@class="tiny_wappen"]//@title'
        n_t_name = "".join(data.xpath(xpath))

        xpath = './/td[5]//img[@class="tiny_wappen"]/parent::a/@href'
        n_t_link = TF + "".join(data.xpath(xpath))

        xpath = './/td[5]//img[@class="flaggenrahmen"]/following-sibling::a/'
        n_l_name = "".join(data.xpath(xpath + "@title"))
        if n_l_name:
            n_l_link = TF + "".join(data.xpath(xpath + "@href"))
        else:
            xpath = './/td[5]//img[@class="flaggenrahmen"]/parent::div/text()'
            n_l_name = "".join(data.xpath(xpath))
            n_l_link = ""

        n_l_link = n_l_link.replace("transfers", "startseite")
        if n_l_link:
            n_l_link = n_l_link.split("/saison_id", maxsplit=1)[0]

        xpath = './/td[5]//img[@class="flaggenrahmen"]/@alt'
        ctry = data.xpath(xpath)
        nw_lg = Competition(n_l_name, n_l_link, country=ctry)

        new_team = Team(n_t_name, n_t_link, league=nw_lg, country=ctry)

        tran.new_team = new_team
        player.team = new_team

        # Box 6 - Leagues & Fee
        tran.fee = "".join(data.xpath(".//td[6]//a/text()"))
        tran.fee_link = TF + "".join(data.xpath(".//td[6]//a/@href"))
        return tran

    @classmethod
    def from_team(cls, data: typing.Any, out: bool, team: Team) -> Transfer:
        """Generated from a Team Object"""
        tran = Transfer()

        # Block 1 - Discard, Position Colour Marker.
        # Block 2 - Name, Link, Picture, Position
        xpath = './/tm-tooltip[@data-type="player"]/a/@title'
        if not (name := "".join(data.xpath(xpath)).strip()):
            name = "".join(data.xpath("./td[2]//a/text()")).strip()

        xpath = './tm-tooltip[@data-type="player"]/a/@href'
        if not (link := "".join(data.xpath(xpath))):
            link = "".join(data.xpath("./td[2]//a/@href"))

        if link and TF not in link:
            link = TF + link

        player = PartialPlayer(name=name, link=link)
        xpath = './img[@class="bilderrahmen-fixed"]/@data-src'
        player.picture = "".join(data.xpath(xpath))

        xpath = "./td[2]//tr[2]/td/text()"
        player.position = "".join(data.xpath(xpath)).strip()

        # Block 3 - Age
        player.age = int("".join(data.xpath("./td[3]/text()")).strip())

        # Block 4 - Nationality
        xpath = "./td[4]//img/@title"
        player.country = [i.strip() for i in data.xpath(xpath) if i.strip()]

        tran.player = player

        # Block 5 - Other Team
        xpath = './td[5]//td[@class="hauptlink"]/a/text()'
        team_name = "".join(data.xpath(xpath)).strip()

        xpath = './td[5]//td[@class="hauptlink"]/a/@href'
        if (team_link := "".join(data.xpath(xpath))) and TF not in team_link:
            team_link = TF + team_link

        xpath = "./td[5]//tr[2]//a/text()"
        comp_name = "".join(data.xpath(xpath)).strip()

        xpath = "./td[5]//tr[2]//a/@href"
        comp_link = "".join(data.xpath(xpath)).strip()

        league = Competition(name=comp_name, link=comp_link)
        b_team = Team(name=team_name, link=team_link)
        b_team.league = league

        xpath = "./td[5]//img[@class='flaggenrahmen']/@title"
        team.country = [i.strip() for i in data.xpath(xpath) if i.strip()]

        tran.new_team = b_team if out else team
        tran.old_team = team if out else team

        # Block 6 - Fee or Loan
        tran.fee = "".join(data.xpath(".//td[6]//text()"))

        xpath = ".//td[6]//@href"
        tran.fee_link = TF + "".join(data.xpath(xpath)).strip()
        tran.date = "".join(data.xpath(".//i/text()"))
        return tran

    @property
    def loan_fee(self) -> str:
        """Returns either Loan Information or the total fee of a player's
        transfer"""
        date = "" if self.date is None else f": {self.date}"
        output = f"[{self.fee}]({self.fee_link}) {date}"
        return output

    def __str__(self) -> str:
        return f"{self.player} ({self.loan_fee})"

    @property
    def movement(self) -> str:
        """Moving from Team A to Team B"""
        old_md = self.old_team.markdown if self.old_team else "?"
        new_md = self.new_team.markdown if self.new_team else "?"
        return f"{old_md} ➡ {new_md}"

    @property
    def inbound(self) -> str:
        """Get inbound text."""
        return f"{self.player} {self.loan_fee}\nFrom: {self.old_team}\n"

    @property
    def outbound(self) -> str:
        """Get outbound text."""
        return f"{self.player} {self.loan_fee}\nTo: {self.new_team}\n"

    def embed(self) -> discord.Embed:
        """An embed representing a transfermarkt player transfer."""
        embed = discord.Embed(colour=0x1A3151)
        flg = " ".join(self.player.flags)
        embed.title = f"{flg} {self.player.name}"
        embed.url = self.player.link
        desc: list[str] = []
        desc.append(f"**Age**: {self.player.age}")
        desc.append(f"**Position**: {self.player.position}")
        desc.append(f"**From**: {self.old_team}")
        desc.append(f"**To**: {self.new_team}")
        desc.append(f"**Fee**: {self.loan_fee}")

        if self.player.picture and "http" in self.player.picture:
            embed.set_thumbnail(url=self.player.picture)

        desc.append(timed_events.Timestamp().relative)
        embed.description = "\n".join(desc)
        return embed


class TeamView(view_utils.Paginator):
    """A View representing a Team on TransferMarkt"""

    def __init__(
        self, invoker: User, team: Team, embeds: list[discord.Embed]
    ) -> None:
        super().__init__(invoker, embeds)
        self.team: Team = team

    @discord.ui.button(label="Transfers", emoji="🔄", row=1)
    async def transfers(self, interaction: Interaction, _) -> None:
        """Push transfers to View"""
        embeds = await self.team.get_transfers()
        view = TeamView(interaction.user, self.team, embeds)
        view.transfers.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Rumours", emoji="🕵", row=1)
    async def rumours(self, interaction: Interaction, _) -> None:
        """Send transfer rumours for a team to View"""
        embeds = await self.team.get_rumours()
        view = TeamView(interaction.user, self.team, embeds)
        view.rumours.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Trophies", emoji="🏆")
    async def trophies(self, interaction: Interaction, _) -> None:
        """Send trophies for a team to View"""
        embeds = await self.team.get_trophies()
        view = TeamView(interaction.user, self.team, embeds)
        view.trophies.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Contracts", emoji="📝")
    async def contracts(self, interaction: Interaction, _) -> None:
        """Push a list of a team's expiring contracts to the view"""
        embeds = await self.team.get_trophies()
        view = TeamView(interaction.user, self.team, embeds)
        view.contracts.disabled = True
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


class StadiumAttendance:
    """A Generic container representing the attendance data of a stadium"""

    name: str
    link: str
    capacity: int
    total: int
    average: int
    team: Team

    def __init__(self, data: typing.Any) -> None:
        # Two Subnodes
        node = data.xpath(".//td/table//tr[1]")[0]
        team_node = data.xpath(".//td/table//tr[2]")[0]

        # Stadium info
        self.name = "".join(node.xpath(".//a/text()"))
        self.link = TF + "".join(node.xpath(".//@href"))

        # Team info
        name = "".join(team_node.xpath(".//a/text()"))
        link = TF + "".join(data.xpath(".//a/@href"))
        self.team = Team(name, link)

        cap = "".join(data.xpath('.//td[@class="rechts"][1]/text()'))
        self.capacity = int(cap.replace(".", ""))

        tot = "".join(data.xpath('.//td[@class="rechts"][2]/text()'))
        self.total = int(tot.replace(".", ""))

        avg = "".join(data.xpath('.//td[@class="rechts"][3]/text()'))
        self.average = int(avg.replace(".", ""))

    def __str__(self) -> str:
        """Formatted markdown for Stadium Attendance"""
        markdown = self.team.markdown
        return (
            f"{self.markdown} {self.average} ({markdown})"
            f"\n*Capacity: {self.capacity} | Total: {self.total}*\n"
        )

    @property
    def markdown(self) -> str:
        """return string of [Name](Link)"""
        link = f"({self.link})" if self.link else ""
        name = f"[{self.name}]" if self.name else ""
        return f"{name}{link}"

    @property
    def capacity_row(self) -> str:
        """Formatted markdown for a stadium's max capacity"""
        markdown = self.team.markdown
        return f"[{self.name}]({self.link}) {self.capacity} ({markdown})"

    @property
    def average_row(self) -> str:
        """Formatted markdown for a stadium's average attendance"""
        markdown = self.team.markdown
        return f"[{self.name}]({self.link}) {self.average} ({markdown})"

    @property
    def total_row(self) -> str:
        """Formatted markdown for a stadium's total attendance"""
        team = self.team.markdown
        return f"[{self.name}]({self.link}) {self.total} ({team})"


class CompetitionView(view_utils.Paginator):
    """A View representing a competition on TransferMarkt"""

    def __init__(
        self, invoker: User, comp: Competition, embeds: list[discord.Embed]
    ) -> None:
        super().__init__(invoker, embeds)
        self.competition: Competition = comp

    @discord.ui.button(label="Attendance", emoji="🏟️")
    async def attendance(self, interaction: Interaction, _) -> None:
        """Fetch attendances for league's stadiums."""
        embeds = await self.competition.get_attendance()
        view = CompetitionView(interaction.user, self.competition, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])


# TODO: AsyncDropdownPaginator
class SearchView(view_utils.DropdownPaginator):
    """A TransferMarkt Search in View Form"""

    query_string: str
    match_string: str
    category: str

    def __init__(
        self,
        invoker: User,
        embed: discord.Embed,
        rows: list[str],
        options: list[discord.SelectOption],
        query: str,
    ) -> None:
        super().__init__(invoker, embed, rows, options)

        self.query: str = query

        # Afterwards.
        self.items: list[SearchResult]
        self.value: SearchResult
        self.interaction: Interaction

    @classmethod
    async def search(
        cls: typing.Type["T"], query: str, interaction: Interaction
    ) -> Optional["T"]:
        """Generate a SearchView from the query"""
        url = TF + "/schnellsuche/ergebnis/schnellsuche"
        # Header names, scrape then compare (don't follow a pattern.)
        # TransferMarkt Search indexes from 1.
        params = {"query": query, cls.query_string: 1}

        async with interaction.client.session.post(url, params=params) as resp:
            if resp.status != 200:
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, resp.url)
            tree = html.fromstring(await resp.text())

        # Get trs of table after matching header / {ms} name.
        xpath = (
            f".//div[@class='box']/h2[@class='content-box-headline']"
            f"[contains(text(),'{cls.match_string}')]"
        )

        trs = f"{xpath}/following::div[1]//tbody/tr"
        header = "".join(tree.xpath(f"{xpath}//text()"))

        try:
            matches = int("".join([i for i in header if i.isdecimal()]))
        except ValueError:
            logger.error("ValueError when parsing header, %s", header)
            matches = 0

        embed = discord.Embed(title=f"{matches} results for {query}")
        embed.url = str(resp.url)

        cat = cls.category.title()
        embed.set_author(name=f"TransferMarkt Search: {cat}", icon_url=FAVICON)

        results = cls.parse(tree.xpath(trs))

        if not results:
            err = f"🚫 No results found for {cls.category}: {query}"
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = err
            await interaction.response.send_message(embed=embed)
            return None

        embed = embed_utils.rows_to_embeds(embed, [str(i) for i in results])[0]

        options: list[discord.SelectOption] = []
        rows: list[str] = []
        for i in results:
            desc = i.country[0] if i.country else ""

            if isinstance(i, Team):
                desc += f": {i.league.name}" if i.league else ""

            option = discord.SelectOption(label=i.name, value=i.link)
            option.description = desc[:100]
            option.emoji = i.flags[0]
            options.append(option)
            rows.append(desc)

        view = cls(interaction.user, embed, rows, options, query)
        view.items = results
        await interaction.response.send_message(view=view, embed=embed)
        return view

    async def handle_page(  # type: ignore
        self, interaction: Interaction
    ) -> None:
        """Perform a search"""
        url = TF + "/schnellsuche/ergebnis/schnellsuche"
        # Header names, scrape then compare (don't follow a pattern.)
        # TransferMarkt Search indexes from 1.
        params = {"query": self.query, self.query_string: self.index + 1}

        async with interaction.client.session.post(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            tree = html.fromstring(await resp.text())

        # Get trs of table after matching header / {ms} name.
        xpath = (
            f".//div[@class='box']/h2[@class='content-box-headline']"
            f"[contains(text(),'{self.match_string}')]"
        )

        trs = f"{xpath}/following::div[1]//tbody/tr"
        header = "".join(tree.xpath(f"{xpath}//text()"))

        try:
            matches = int("".join([i for i in header if i.isdecimal()]))
        except ValueError:
            logger.error("ValueError when parsing header, %s", header)
            matches = 0

        embed = discord.Embed(title=f"{matches} results for {self.query}")
        embed.url = str(resp.url)

        cat = self.category.title()
        embed.set_author(name=f"TransferMarkt Search: {cat}", icon_url=FAVICON)

        self.items = self.parse(tree.xpath(trs))

        if not self.items:
            self.index = 0
            err = f"🚫 No results found for {self.category}: {self.query}"
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = err
            return await interaction.response.edit_message(embed=embed)

        _ = [str(i) for i in self.items]
        embed = embed_utils.rows_to_embeds(embed, _)[0]
        self.pages = [embed] * max(matches // 10, 1)
        options: list[discord.SelectOption] = []
        for i in self.items:
            desc = i.country[0] if i.country else ""

            if isinstance(i, Team):
                desc += f": {i.league.name}" if i.league else ""

            opt = discord.SelectOption(label=i.name, value=i.link)
            opt.description = desc[:100]
            opt.emoji = i.flags[0]
            options.append(opt)

        self.dropdown.options = options
        await interaction.response.edit_message(view=self, embed=embed)

    @discord.ui.select(row=4, placeholder="Select correct item")
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[SearchView]
    ) -> None:
        """Set self.value to target object"""
        self.value = next(i for i in self.items if i.link in sel.values)
        self.interaction = itr

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[typing.Any]:
        """This should always be polymorphed"""
        return rows


class AgentSearch(SearchView):
    """View when searching for an Agent"""

    category = "Agents"
    query_string = "page"
    match_string = "for agents"

    value: Agent

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[Agent]:
        """Parse a transfermarkt page into a list of Agent Objects"""
        results: list[Agent] = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()"))
            if TF not in (link := "".join(i.xpath(".//td[2]/a/@href"))):
                link = TF + link
            results.append(Agent(name=name, link=link))
        return results


class CompetitionSearch(SearchView):
    """View When Searching for a Competition"""

    category = "Competitions"
    query_string = "Wettbewerb_page"
    match_string = "competitions"

    value: Competition

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[Competition]:
        """Parse a transfermarkt page into a list of Competition Objects"""
        results: list[Competition] = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()")).strip()
            link = TF + "".join(i.xpath(".//td[2]/a/@href")).strip()

            country = [_.strip() for _ in i.xpath(".//td[3]/img/@title")]
            comp = Competition(name=name, link=link, country=country)

            results.append(comp)
        return results


class PlayerSearch(SearchView):
    """A Search View for a player"""

    category = "Players"
    query_string = "Spieler_page"
    match_string = "for players"

    value: PartialPlayer

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[PartialPlayer]:
        """Parse a transfer page to get a list of players"""
        results: list[PartialPlayer] = []
        for i in rows:
            xpath = (
                './/tm-tooltip[@data-type="player"]/a/@title |'
                './/td[@class="hauptlink"]/a/text()'
            )
            name = "".join(i.xpath(xpath))

            xpath = (
                './/tm-tooltip[@data-type="player"]/a/@href |'
                './/td[@class="hauptlink"]/a/@href'
            )
            link = "".join(i.xpath(xpath))

            if link and TF not in link:
                link = TF + link

            player = PartialPlayer(name=name, link=link)

            xpath = './/img[@class="bilderrahmen-fixed"]/@src'
            player.picture = "".join(i.xpath(xpath))

            try:
                xpath = './/tm-tooltip[@data-type="club"]/a/@title'
                team_name = i.xpath(xpath)[0]

                xpath = './/tm-tooltip[@data-type="club"]/a/@href'
                team_link = i.xpath(xpath)[0]
                if team_link and TF not in team_link:
                    team_link = TF + team_link

                team = Team(name=team_name, link=team_link)
                player.team = team
            except IndexError:
                pass

            try:
                player.age = int("".join(i.xpath(".//td[4]/text()")))
            except ValueError:
                pass

            player.position = "".join(i.xpath(".//td[2]/text()"))

            xpath = './/td/img[@class="flaggenrahmen"]/@title'
            player.country = i.xpath(xpath)

            results.append(player)
        return results


class RefereeSearch(SearchView):
    """View when searching for a Referee"""

    category = "Referees"
    query_string = "page"
    match_string = "for referees"

    value: Referee

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[Referee]:
        """Parse a transfer page to get a list of referees"""
        results: list[Referee] = []
        for i in rows:
            xpath = './/td[@class="hauptlink"]/a/@href'
            link = "".join(i.xpath(xpath)).strip()
            if TF not in link:
                link = TF + link

            xpath = './/td[@class="hauptlink"]/a/text()'
            name = "".join(i.xpath(xpath)).strip()
            country = i.xpath(".//td/img[1]/@title")
            age = "".join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
            ref = Referee(name, link, country=country, age=age)

            results.append(ref)
        return results


class StaffSearch(SearchView):
    """A Search View for a Staff member"""

    category = "Managers"
    query_string = "Trainer_page"
    match_string = "Managers"

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[Staff]:
        """Parse a list of staff"""
        results: list[Staff] = []
        for i in rows:
            xpath = './/td[@class="hauptlink"]/a/@href'
            if TF not in (link := "".join(i.xpath(xpath))):
                link = TF + link

            name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()'))

            staff = Staff(name, link)

            xpath = './/img[@class="bilderrahmen-fixed"]/@src'
            staff.picture = "".join(i.xpath(xpath))
            try:
                staff.age = int("".join(i.xpath(".//td[3]/text()")))
            except ValueError:
                pass
            staff.job = "".join(i.xpath(".//td[5]/text()"))
            staff.country = i.xpath('.//img[@class="flaggenrahmen"]/@title')

            try:
                xpath = './/tm-tooltip[@data-type="club"][1]/a/@title'
                team_name = i.xpath(xpath)[0]

                leg = i.xpath('.//tm-tooltip[@data-type="club"][1]/a/@href')[0]
                if TF not in leg:
                    leg = TF + leg
                team_link = leg

                staff.team = Team(team_name, team_link)
            except IndexError:
                pass
            results.append(staff)
        return results


class TeamSearch(SearchView):
    """A Search View for a team"""

    category = "Team"
    query_string = "Verein_page"
    match_string = "results: Clubs"

    value: Team

    @staticmethod
    def parse(rows: list[typing.Any]) -> list[Team]:
        """Fetch a list of teams from a transfermarkt page"""
        results: list[Team] = []

        for i in rows:
            xpath = './/tm-tooltip[@data-type="club"]/a/@title'
            if not (name := "".join(i.xpath(xpath)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xpath = './/tm-tooltip[@data-type="club"]/a/@href'
            if not (link := "".join(i.xpath(xpath)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            xpath = ".//tr[2]/td/a/@href"
            if TF not in (lg_lnk := "".join(i.xpath(xpath)).strip()):
                lg_lnk = TF + lg_lnk

            lg_name = "".join(i.xpath(".//tr[2]/td/a/text()")).strip()

            xpath = './/td/img[@class="flaggenrahmen" ]/@title'
            country = [c.strip() for c in i.xpath(xpath) if c]

            xpath = './/td[@class="suche-vereinswappen"]/img/@src'
            logo = "".join(i.xpath(xpath))

            league = Competition(lg_name, lg_lnk, country=country, logo=logo)

            team = Team(name, link, league=league)

            results.append(team)
        return results


DEFAULT_LEAGUES = [
    Competition(
        name="Premier League",
        country="England",
        link=TF + "premier-league/startseite/wettbewerb/GB1",
    ),
    Competition(
        name="Championship",
        country="England",
        link=TF + "/championship/startseite/wettbewerb/GB2",
    ),
    Competition(
        name="Eredivisie",
        country="Netherlands",
        link=TF + "/eredivisie/startseite/wettbewerb/NL1",
    ),
    Competition(
        name="Bundesliga",
        country="Germany",
        link=TF + "/bundesliga/startseite/wettbewerb/L1",
    ),
    Competition(
        name="Serie A",
        country="Italy",
        link=TF + "/serie-a/startseite/wettbewerb/IT1",
    ),
    Competition(
        name="LaLiga",
        country="Spain",
        link=TF + "/laliga/startseite/wettbewerb/ES1",
    ),
    Competition(
        name="Ligue 1",
        country="France",
        link=TF + "/ligue-1/startseite/wettbewerb/FR1",
    ),
    Competition(
        name="Major League Soccer",
        country="United States",
        link=TF + "/major-league-soccer/startseite/wettbewerb/MLS1",
    ),
]
