"""Utilities for working with transfers from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import dataclasses
import datetime
import logging
import typing

import discord
from lxml import html

from ext.utils import view_utils, timed_events, flags, embed_utils

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]


FAVICON = (
    "https://upload.wikimedia.org/wikipedia/commons/f/fb/"
    "Transfermarkt_favicon.png"
)
TF = "https://www.transfermarkt.co.uk"

logger = logging.getLogger("transfermarkt")


# TODO: Convert functions to @buttons


class SearchResult:
    """A result from a transfermarkt search"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        self.name: str = name
        self.link: str = link
        self.emoji: str
        self.country: list[str] = kwargs.pop("country", [])

    def __repr__(self) -> str:
        return f"SearchResult({self.__dict__})"

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
    def flag(self) -> str:
        """Return a flag representing the country"""
        # Return the 'earth' emoji if caller does not have a country.
        if self.country is None:
            return "🌍"

        if isinstance(self.country, list):
            output = [flags.get_flag(i) for i in self.country]
            return " ".join([x for x in output if x is not None])
        else:
            return flags.get_flag(self.country)


class Competition(SearchResult):
    """An Object representing a competition from transfermarkt"""

    emoji: str = "🏆"

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)
        self.country: typing.Optional[str] = kwargs.pop("country", None)

    def __str__(self) -> str:
        if self:
            return f"{self.flag} {self.markdown}"
        else:
            return ""

    def __bool__(self):
        return bool(self.name)


class Team(SearchResult):
    """An object representing a Team from Transfermarkt"""

    emoji: str = "👕"

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name=name, link=link)

        self.league: Competition = kwargs.pop("league", None)
        self.country: str = kwargs.pop("country", None)
        for k, value in kwargs.items():
            setattr(self, k, value)

    def __str__(self) -> str:
        if self.league.markdown:
            return f"{self.flag} {self.markdown} ({self.league.markdown})"
        return f"{self.flag} {self.markdown}"

    @property
    def select_option(self) -> discord.SelectOption:
        """A Select Option representation of this Team"""
        flag = self.flag
        name = self.name
        desc = self.league.name
        return discord.SelectOption(emoji=flag, label=name, description=desc)

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


class Player(SearchResult):
    """An Object representing a player from transfermarkt"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)

        self.team: Team = kwargs.pop("team", None)
        self.age: int = kwargs.pop("age", None)
        self.position: str = kwargs.pop("position", None)
        self.country: list[str] = kwargs.pop("country", [])
        self.picture: str = kwargs.pop("picture", None)

    def __repr__(self) -> str:
        return f"Player({self.__dict__})"

    def __str__(self) -> str:
        desc = [self.flag, self.markdown, self.age, self.position]

        if self.team is not None:
            desc.append(self.team.markdown)
        return " ".join([str(i) for i in desc if i is not None])


class Referee(SearchResult):
    """An object representing a referee from transfermarkt"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)

        self.age: int = kwargs.pop("age", None)
        self.country: list[str] = kwargs.pop("country", [])

    def __str__(self) -> str:
        output = f"{self.flag} {self.markdown}"
        if self.age is not None:
            output += f" {self.age}"
        return output


class Staff(SearchResult):
    """An object representing a Trainer or Manager from Transfermarkt"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)

        self.team: Team = kwargs.pop("team", None)
        self.age: int = kwargs.pop("age", None)
        self.job: str = kwargs.pop("job", None)
        self.country: list[str] = kwargs.pop("country", None)
        self.picture: str = kwargs.pop("picture", None)

    def __str__(self) -> str:
        team = self.team.markdown if self.team is not None else ""
        markdown = self.markdown
        return f"{self.flag} {markdown} {self.age}, {self.job} {team}".strip()


class Agent(SearchResult):
    """An object representing an Agent from transfermarkt"""


class Transfer:
    """An Object representing a transfer from transfermarkt"""

    def __init__(self, player: Player) -> None:
        self.player: Player = player

        self.link: typing.Optional[str] = None
        self.fee: typing.Optional[str] = None
        self.fee_link: typing.Optional[str] = None
        self.old_team: typing.Optional[Team] = None
        self.new_team: typing.Optional[Team] = None
        self.date: typing.Optional[str] = None

        # Typehint
        self.embed: typing.Optional[discord.Embed] = None

    @property
    def loan_fee(self) -> str:
        """Returns either Loan Information or the total fee of a player's
        transfer"""
        output = f"[{self.fee}]({self.fee_link})"

        if self.date is not None:
            output += f": {self.date}"

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

    def generate_embed(self) -> discord.Embed:
        """An embed representing a transfermarkt player transfer."""
        embed = discord.Embed(description="", colour=0x1A3151)
        embed.title = f"{self.player.flag} {self.player.name}"
        embed.url = self.player.link
        desc = []
        if self.player.age is not None:
            desc.append(f"**Age**: {self.player.age}")
        if self.player.position is not None:
            desc.append(f"**Position**: {self.player.position}")

        desc.append(f"**From**: {self.old_team}")
        desc.append(f"**To**: {self.new_team}")
        desc.append(f"**Fee**: {self.loan_fee}")

        if self.player.picture is not None and "http" in self.player.picture:
            embed.set_thumbnail(url=self.player.picture)

        desc.append(timed_events.Timestamp().relative)
        embed.description = "\n".join(desc)
        self.embed = embed
        return self.embed


class TeamView(view_utils.BaseView):
    """A View representing a Team on TransferMarkt"""

    def __init__(self, team: Team) -> None:
        super().__init__()
        self.team: Team = team

    async def update(self, interaction: Interaction) -> None:
        """Send the latest version of the view"""
        self.clear_items()

        items = [
            view_utils.Funcable("Transfers", self.push_transfers, emoji="🔄"),
            view_utils.Funcable("Rumours", self.push_rumours, emoji="🕵"),
            view_utils.Funcable("Trophies", self.push_trophies, emoji="🏆"),
            view_utils.Funcable("Contracts", self.push_contracts, emoji="📝"),
        ]
        self.add_function_row(items, 1)
        self.add_page_buttons()

        embed = self.pages[self.index]
        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self)

    async def push_transfers(self, interaction: Interaction) -> None:
        """Push transfers to View"""
        url = self.team.link.replace("startseite", "transfers")

        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
            tree = html.fromstring(await resp.text())

        def parse(rows: list, out: bool = False) -> list[Transfer]:
            """Read through the transfers page and extract relevant data,
            returning a list of transfers"""

            transfers = []
            for i in rows:
                # Block 1 - Discard, Position Colour Marker.

                # Block 2 - Name, Link, Picture, Position
                xpath = './/tm-tooltip[@data-type="player"]/a/@title'
                if not (name := "".join(i.xpath(xpath)).strip()):
                    name = "".join(i.xpath("./td[2]//a/text()")).strip()

                xpath = './tm-tooltip[@data-type="player"]/a/@href'
                if not (link := "".join(i.xpath(xpath))):
                    link = "".join(i.xpath("./td[2]//a/@href"))

                if link and TF not in link:
                    link = TF + link

                player = Player(name=name, link=link)
                xpath = './img[@class="bilderrahmen-fixed"]/@data-src'
                player.picture = "".join(i.xpath(xpath))

                xpath = "./td[2]//tr[2]/td/text()"
                player.position = "".join(i.xpath(xpath)).strip()

                # Block 3 - Age
                player.age = int("".join(i.xpath("./td[3]/text()")).strip())

                # Block 4 - Nationality
                xpath = "./td[4]//img/@title"
                player.country = [
                    _.strip() for _ in i.xpath(xpath) if _.strip()
                ]

                transfer = Transfer(player=player)

                # Block 5 - Other Team
                xpath = './td[5]//td[@class="hauptlink"]/a/text()'
                team_name = "".join(i.xpath(xpath)).strip()

                xpath = './td[5]//td[@class="hauptlink"]/a/@href'
                if (
                    team_link := "".join(i.xpath(xpath))
                ) and TF not in team_link:
                    team_link = TF + team_link

                xpath = "./td[5]//tr[2]//a/text()"
                comp_name = "".join(i.xpath(xpath)).strip()

                xpath = "./td[5]//tr[2]//a/@href"
                comp_link = "".join(i.xpath(xpath)).strip()

                league = Competition(name=comp_name, link=comp_link)

                team = Team(name=team_name, link=team_link)
                team.league = league

                xpath = "./td[5]//img[@class='flaggenrahmen']/@title"
                team.country = "".join(
                    [_.strip() for _ in i.xpath(xpath) if _.strip()]
                )

                transfer.new_team = team if out else self.team
                transfer.old_team = self.team if out else team

                # Block 6 - Fee or Loan
                transfer.fee = "".join(i.xpath(".//td[6]//text()"))

                xpath = ".//td[6]//@href"
                transfer.fee_link = TF + "".join(i.xpath(xpath)).strip()
                transfer.date = "".join(i.xpath(".//i/text()"))
                transfers.append(transfer)
            return transfers

        base_embed = self.team.base_embed
        base_embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
        base_embed.url = url

        embeds = []
        xpath = (
            './/div[@class="box"][.//h2[contains(text(),"Arrivals")]]'
            '//tr[@class="even" or @class="odd"]'
        )

        if players_in := parse(tree.xpath(xpath)):
            embed = base_embed.copy()
            embed.title = f"Inbound Transfers for {embed.title}"
            embed.colour = discord.Colour.green()

            rows = [i.inbound for i in players_in]
            embeds += embed_utils.rows_to_embeds(embed, rows)

        xpath = (
            './/div[@class="box"][.//h2[contains(text(),"Departures")]]'
            '//tr[@class="even" or @class="odd"]'
        )
        if players_out := parse(tree.xpath(xpath), out=True):
            embed = base_embed.copy()
            embed.title = f"Outbound Transfers for {embed.title}"
            embed.colour = discord.Colour.red()
            rows = [i.outbound for i in players_out]
            embeds += embed_utils.rows_to_embeds(embed, rows)

        if not embeds:
            embed = base_embed
            embed.title = f"No transfers found {embed.title}"
            embed.colour = discord.Colour.orange()
            embeds = [embed]

        self.pages = embeds
        self.index = 0
        return await self.update(interaction)

    async def push_rumours(self, interaction: Interaction) -> None:
        """Send transfer rumours for a team to View"""
        embed = self.team.base_embed

        url = self.team.link.replace("startseite", "geruechte")
        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
            tree = html.fromstring(await resp.text())

        embed.url = str(resp.url)
        embed.title = f"Transfer rumours for {self.team.name}"
        embed.set_author(name="Transfermarkt", url=resp.url, icon_url=FAVICON)

        rows = []
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
            flag = " ".join([flags.get_flag(i) for i in country])
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

        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self.index = 0
        return await self.update(interaction)

    async def push_trophies(self, interaction: Interaction) -> None:
        """Send trophies for a team to View"""
        url = self.team.link.replace("startseite", "erfolge")

        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
        tree = html.fromstring(await resp.text())

        trophies = []
        for i in tree.xpath('.//div[@class="box"][./div[@class="header"]]'):
            title = "".join(i.xpath(".//h2/text()"))

            xpath = './/div[@class="erfolg_infotext_box"]/text()'
            split = "".join(i.xpath(xpath)).split()
            dates = " ".join(split).replace(" ,", ",")
            trophies.append(f"**{title}**\n{dates}\n")

        embed = self.team.base_embed
        embed.title = f"{self.team.name} Trophy Case"

        if not trophies:
            trophies = ["No trophies found for team."]
        self.pages = embed_utils.rows_to_embeds(embed, trophies)
        self.index = 0
        return await self.update(interaction)

    async def push_contracts(self, interaction: Interaction) -> None:
        """Push a list of a team's expiring contracts to the view"""
        embed = self.team.base_embed
        embed.description = ""
        target = self.team.link.replace("startseite", "vertragsende")

        async with interaction.client.session.get(target) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
            tree = html.fromstring(await resp.text())
        embed.url = target
        embed.title = f"Expiring contracts for {self.team.name}"
        embed.set_author(name="Transfermarkt", url=target, icon_url=FAVICON)

        rows = []

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
            flag = " ".join([flags.get_flag(f) for f in country])
            date = "".join(i.xpath(".//td[4]//text()")).strip()

            time = datetime.datetime.strptime(date, "%b %d, %Y")
            expiry = timed_events.Timestamp(time).countdown

            option = "".join(i.xpath(".//td[5]//text()")).strip()
            option = f"\n∟ {option.title()}" if option != "-" else ""

            markdown = f"[{name}]({link})"
            rows.append(f"{flag} {markdown} {age}, {pos} ({expiry}){option}")

        if not rows:
            rows = ["No expiring contracts found."]

        self.pages = embed_utils.rows_to_embeds(embed, rows)
        self.index = 0
        return await self.update(interaction)


@dataclasses.dataclass
class StadiumAttendance:
    """A Generic container representing the attendance data of a stadium"""

    name: str
    link: str
    capacity: int
    total: int
    average: int
    team: Team

    def __init__(self, **kwargs) -> None:
        for k, val in kwargs.items():
            setattr(self, k, val)

    def __str__(self) -> str:
        """Formatted markdown for Stadium Attendance"""
        markdown = self.team.markdown
        return (
            f"[{self.name}]({self.link}) {self.average} ({markdown})"
            f"\n*Capacity: {self.capacity} | Total: {self.total}*\n"
        )

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


class CompetitionView(view_utils.BaseView):
    """A View representing a competition on TransferMarkt"""

    def __init__(self, comp: Competition) -> None:
        super().__init__()
        self.comp: Competition = comp

    async def update(
        self, interaction: Interaction, content: typing.Optional[str] = None
    ) -> None:
        """Send the latest version of the view"""
        self.clear_items()
        self.add_page_buttons()

        btn = view_utils.Funcable("Attendances", self.attendance, emoji="🏟️")
        self.add_function_row([btn])

        embed = self.pages[self.index]

        edit = interaction.response.edit_message
        return await edit(content=content, embed=embed, view=self)

    async def attendance(self, interaction: Interaction) -> None:
        """Fetch attendances for league's stadiums."""
        url = self.comp.link.replace("startseite", "besucherzahlen")
        async with interaction.client.session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
            tree = html.fromstring(await resp.text())

        rows = []
        xpath = (
            './/table[@class="items"]/tbody/tr[@class="odd" or @class="even"]'
        )
        for i in tree.xpath(xpath):
            # Two sub rows.
            try:
                stadium = i.xpath(".//td/table//tr[1]")[0]
                team = i.xpath(".//td/table//tr[2]")[0]
            except IndexError:
                continue

            # Stadium info
            stad = "".join(stadium.xpath(".//a/text()"))
            stad_link = TF + "".join(stadium.xpath(".//@href"))
            # Team info
            team_name = "".join(team.xpath(".//a/text()"))
            team_link = TF + "".join(i.xpath(".//a/@href"))
            try:
                cap = "".join(i.xpath('.//td[@class="rechts"][1]/text()'))
                cap = int(cap.replace(".", ""))

                tot = "".join(i.xpath('.//td[@class="rechts"][2]/text()'))
                tot = int(tot.replace(".", ""))

                avg = "".join(i.xpath('.//td[@class="rechts"][3]/text()'))
                avg = int(avg.replace(".", ""))
            except ValueError:
                continue

            team = Team(team_name, team_link)
            rows.append(
                StadiumAttendance(
                    name=stad,
                    link=stad_link,
                    capacity=cap,
                    average=avg,
                    total=tot,
                    team=team,
                )
            )

        embeds = []
        # Average
        embed = self.comp.base_embed.copy()
        embed.title = f"Average Attendance data for {self.comp.name}"
        embed.url = url
        ranked = sorted(rows, key=lambda x: x.average, reverse=True)

        enu = [f"{i[0]}: {i[1].average_row}" for i in enumerate(ranked, 1)]
        embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

        embed = self.comp.base_embed.copy()
        embed.title = f"Total Attendance data for {self.comp.name}"
        embed.url = url
        ranked = sorted(rows, key=lambda x: x.total, reverse=True)

        enu = [f"{i[0]}: {i[1].total_row}" for i in enumerate(ranked, 1)]
        embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

        embed = self.comp.base_embed.copy()
        embed.title = f"Max Capacity data for {self.comp.name}"
        embed.url = url
        ranked = sorted(rows, key=lambda x: x.capacity, reverse=True)

        enu = [f"{i[0]}: {i[1].capacity_row}" for i in enumerate(ranked, 1)]
        embeds += embed_utils.rows_to_embeds(embed, [i for i in enu], 25)

        self.pages = embeds
        return await self.update(interaction)


class SearchSelect(discord.ui.Select):
    """Dropdown."""

    view: SearchView

    def __init__(
        self, objects: list[Team | Competition], row: int = 4
    ) -> None:

        super().__init__(row=row, placeholder="Select correct option")

        self.objects: list[Team | Competition] = objects

        for num, obj in enumerate(objects):
            desc = obj.country[0] if obj.country else ""

            if isinstance(obj, Team):
                desc += f": {obj.league.name}" if obj.league else ""

            self.add_option(
                label=obj.name,
                description=desc[:100],
                value=str(num),
                emoji=obj.emoji,
            )

    async def callback(
        self, interaction: discord.Interaction
    ) -> Competition | Team:
        """Set view value to item."""
        await interaction.response.defer()
        self.view.value = self.objects[int(self.values[0])]
        self.view.stop()
        return self.view.value


class SearchView(view_utils.BaseView):
    """A TransferMarkt Search in View Form"""

    query_string: str
    match_string: str
    category: str

    def __init__(
        self,
        query: str,
        fetch: bool = False,
    ) -> None:

        super().__init__()
        self.value: typing.Optional[Team | Competition] = None
        self.pages: list[discord.Embed] = []
        self.query: str = query
        self.fetch: bool = fetch
        self._results: list = []

    def parse(self, rows: list) -> None:
        """This should always be polymorphed"""
        raise NotImplementedError

    async def update(
        self, interaction: Interaction, content: typing.Optional[str] = None
    ) -> None:
        """Populate Initial Results"""
        url = TF + "/schnellsuche/ergebnis/schnellsuche"

        # Header names, scrape then compare (don't follow a pattern.)
        # TransferMarkt Search indexes from 1.
        params = {"query": self.query, self.query_string: self.index + 1}

        async with interaction.client.session.post(url, params=params) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
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

        self.parse(tree.xpath(trs))

        if not self._results:
            self.index = 0
            err = f"No results found for {self.category}: {self.query}"
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 " + err
            return await interaction.response.edit_message(embed=embed)

        rows = [str(i) for i in self._results]
        embed = embed_utils.rows_to_embeds(embed, rows)[0]

        self.pages = [discord.Embed()] * max(matches // 10, 1)

        self.clear_items()
        self.add_page_buttons(row=1)

        if self.fetch and self._results:
            self.add_item(SearchSelect(objects=self._results))

        edit = interaction.response.edit_message
        return await edit(content=content, embed=embed, view=self)


class AgentSearch(SearchView):
    """View when searching for an Agent"""

    category = "Agents"
    query_string = "page"
    match_string = "for agents"

    def __init__(self, query: str) -> None:
        super().__init__(query)

    def parse(self, rows: list) -> list[Agent]:
        """Parse a transfermarkt page into a list of Agent Objects"""
        results = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()"))
            if TF not in (link := "".join(i.xpath(".//td[2]/a/@href"))):
                link = TF + link
            results.append(Agent(name=name, link=link))
        self._results = results
        return results


class CompetitionSearch(SearchView):
    """View When Searching for a Competition"""

    category = "Competitions"
    query_string = "Wettbewerb_page"
    match_string = "competitions"

    def __init__(self, query: str, fetch: bool = False) -> None:
        super().__init__(query, fetch=fetch)
        self.value: typing.Optional[Competition] = None

    def parse(self, rows: list) -> list[Competition]:
        """Parse a transfermarkt page into a list of Competition Objects"""
        results = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()")).strip()
            link = TF + "".join(i.xpath(".//td[2]/a/@href")).strip()

            country = [_.strip() for _ in i.xpath(".//td[3]/img/@title")]
            country = "".join(country)
            comp = Competition(name=name, link=link, country=country)

            results.append(comp)
        self._results = results
        return results


class PlayerSearch(SearchView):
    """A Search View for a player"""

    category = "Players"
    query_string = "Spieler_page"
    match_string = "for players"

    def parse(self, rows) -> list[Player]:
        """Parse a transfer page to get a list of players"""
        results = []
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

            player = Player(name=name, link=link)

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
        self._results = results
        return results


class RefereeSearch(SearchView):
    """View when searching for a Referee"""

    category = "Referees"
    query_string = "page"
    match_string = "for referees"

    def parse(self, rows: list) -> list[Referee]:
        """Parse a transfer page to get a list of referees"""
        results = []
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

        self._results = results
        return results


class StaffSearch(SearchView):
    """A Search View for a Staff member"""

    category = "Managers"
    query_string = "Trainer_page"
    match_string = "Managers"

    def parse(self, rows: list) -> list[Staff]:
        """Parse a list of staff"""
        results = []
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
        self._results = results
        return results


class TeamSearch(SearchView):
    """A Search View for a team"""

    category = "Team"
    query_string = "Verein_page"
    match_string = "results: Clubs"
    value: Team

    def parse(self, rows: list) -> list[Team]:
        """Fetch a list of teams from a transfermarkt page"""
        results = []

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
        self._results = results
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
