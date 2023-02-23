"""Utilities for working with transfers from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import logging
from datetime import datetime
from typing import Optional

from discord import Interaction, Embed, Colour, Message, SelectOption
from discord.ui import Select
from lxml import html

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import FuncButton, add_page_buttons, Parent, BaseView


FAVICON = (
    "https://upload.wikimedia.org/wikipedia/commons/f/fb/"
    "Transfermarkt_favicon.png"
)
TF = "https://www.transfermarkt.co.uk"


class SearchResult:
    """A result from a transfermarkt search"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        self.name: str = name
        self.link: str = link
        self.emoji: str = None
        self.country: list[str] = kwargs.pop("country", [])

    def __repr__(self) -> str:
        return f"SearchResult({self.__dict__})"

    @property
    def base_embed(self) -> Embed:
        """A generic embed used for transfermarkt objects"""
        e: Embed = Embed(color=Colour.dark_blue(), description="")
        e.set_author(name="TransferMarkt")
        return e

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
            flags = [get_flag(i) for i in self.country]
            return " ".join([x for x in flags if x is not None])
        else:
            return get_flag(self.country)


class Competition(SearchResult):
    """An Object representing a competition from transfermarkt"""

    emoji: str = "🏆"

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)
        self.country: str = kwargs.pop("country", None)

    def __str__(self) -> str:
        if self:
            return f"{self.flag} {self.markdown}"
        else:
            return ""

    def __bool__(self):
        return bool(self.name)

    def view(self, interaction: Interaction) -> CompetitionView:
        """Send a view of this Competition to the user."""
        return CompetitionView(interaction, self)


class Team(SearchResult):
    """An object representing a Team from Transfermarkt"""

    emoji: str = "👕"

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name=name, link=link)

        self.league: Competition = kwargs.pop("league", None)
        self.country: str = kwargs.pop("country", None)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self) -> str:
        if self.league.markdown:
            return f"{self.flag} {self.markdown} ({self.league.markdown})"
        return f"{self.flag} {self.markdown}"

    @property
    def select_option(self) -> str:
        """A Select Option representation of this Team"""
        return SelectOption(
            emoji=self.flag, label=self.name, description=self.league.name
        )

    @property
    def badge(self) -> str:
        """Return a link to the team's badge"""
        number = self.link.split("/")[-1]
        return f"https://tmssl.akamaized.net/images/wappen/head/{number}.png"

    @property
    def base_embed(self) -> Embed:
        """Return a discord embed object representing a team"""
        e = super().base_embed
        e.set_thumbnail(url=self.badge)
        e.title = self.name
        e.url = self.link
        return e

    def view(self, interaction: Interaction) -> TeamView:
        """Send a view of this Team to the user."""
        return TeamView(interaction, self)


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
        return " ".join([i for i in desc if i is not None])


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
        md = self.markdown
        return f"{self.flag} {md} {self.age}, {self.job} {team}".strip()


class Agent(SearchResult):
    """An object representing an Agent from transfermarkt"""

    def __init__(self, name: str, link: str):
        super().__init__(name, link)


class Transfer:
    """An Object representing a transfer from transfermarkt"""

    def __init__(self, player: Player) -> None:
        self.player: Player = player

        self.link: str = None
        self.fee: str = None
        self.fee_link: str = None
        self.old_team: Team = None
        self.new_team: Team = None
        self.date: str = None

        # Typehint
        self.embed: Optional[Embed] = None

    @property
    def loan_fee(self) -> str:
        """Returns either Loan Information or the total fee of a player's
        transfer"""
        output = f"[{self.fee.title()}]({self.fee_link})"

        if self.date is not None:
            output += f": {self.date}"

        return output

    def __str__(self) -> str:
        return f"{self.player} ({self.loan_fee})"

    @property
    def movement(self) -> str:
        """Moving from Team A to Team B"""
        return f"{self.old_team.markdown} ➡ {self.new_team.markdown}"

    @property
    def inbound(self) -> str:
        """Get inbound text."""
        return f"{self.player} {self.loan_fee}\nFrom: {self.old_team}\n"

    @property
    def outbound(self) -> str:
        """Get outbound text."""
        return f"{self.player} {self.loan_fee}\nTo: {self.new_team}\n"

    def generate_embed(self) -> Embed:
        """An embed representing a transfermarkt player transfer."""
        e: Embed = Embed(description="", colour=0x1A3151)
        e.title = f"{self.player.flag} {self.player.name}"
        e.url = self.player.link
        desc = []
        if self.player.age is not None:
            desc.append(f"**Age**: {self.player.age}")
        if self.player.position is not None:
            desc.append(f"**Position**: {self.player.position}")

        desc.append(f"**From**: {self.old_team}")
        desc.append(f"**To**: {self.new_team}")
        desc.append(f"**Fee**: {self.loan_fee}")

        if self.player.picture is not None and "http" in self.player.picture:
            e.set_thumbnail(url=self.player.picture)

        desc.append(Timestamp().relative)
        e.description = "\n".join(desc)
        self.embed = e
        return self.embed


class TeamView(BaseView):
    """A View representing a Team on TransferMarkt"""

    def __init__(self, interaction: Interaction, team: Team) -> None:
        super().__init__(interaction)
        self.team: Team = team
        self.index: int = 0
        self.pages: list[Embed] = []
        self.parent: BaseView = None

    async def update(self, content: str = None) -> None:
        """Send the latest version of the view"""
        self.clear_items()
        if self.parent:
            self.add_item(Parent())
            hide_row = 2
        else:
            hide_row = 3

        # TODO: Funcables.
        self.add_item(FuncButton("Transfers", self.push_transfers, emoji="🔄"))
        self.add_item(FuncButton("Rumours", self.push_rumours, emoji="🕵"))
        self.add_item(FuncButton("Trophies", self.push_trophies, emoji="🏆"))
        self.add_item(FuncButton("Contracts", self.push_contracts, emoji="📝"))
        add_page_buttons(self, row=hide_row)

        e = self.pages[self.index]
        await self.bot.reply(self.interaction, content, embed=e, view=self)

    async def push_transfers(self) -> Message:
        """Push transfers to View"""
        url = self.team.link.replace("startseite", "transfers")

        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"Error {resp.status} connecting to {resp.url}"
                    return await self.bot.error(self.interaction, err)

        def parse(rows: list, out: bool = False) -> list[Transfer]:
            """Read through the transfers page and extract relevant data,
            returning a list of transfers"""

            transfers = []
            for i in rows:
                # Block 1 - Discard, Position Colour Marker.

                # Block 2 - Name, Link, Picture, Position
                xp = './/tm-tooltip[@data-type="player"]/a/@title'
                if not (name := "".join(i.xpath(xp)).strip()):
                    name = "".join(i.xpath("./td[2]//a/text()")).strip()

                xp = './tm-tooltip[@data-type="player"]/a/@href'
                if not (link := "".join(i.xpath(xp))):
                    link = "".join(i.xpath("./td[2]//a/@href"))

                if link and TF not in link:
                    link = TF + link

                player = Player(name=name, link=link)
                xp = './img[@class="bilderrahmen-fixed"]/@data-src'
                player.picture = "".join(i.xpath(xp))

                xp = "./td[2]//tr[2]/td/text()"
                player.position = "".join(i.xpath(xp)).strip()

                # Block 3 - Age
                player.age = "".join(i.xpath("./td[3]/text()")).strip()

                # Block 4 - Nationality
                xp = "./td[4]//img/@title"
                player.country = [_.strip() for _ in i.xpath(xp) if _.strip()]

                transfer = Transfer(player=player)

                # Block 5 - Other Team
                xp = './td[5]//td[@class="hauptlink"]/a/text()'
                team_name = "".join(i.xpath(xp)).strip()

                xp = './td[5]//td[@class="hauptlink"]/a/@href'
                if (team_link := "".join(i.xpath(xp))) and TF not in team_link:
                    team_link = TF + team_link

                xp = "./td[5]//tr[2]//a/text()"
                comp_name = "".join(i.xpath(xp)).strip()

                xp = "./td[5]//tr[2]//a/@href"
                comp_link = "".join(i.xpath(xp)).strip()

                league = Competition(name=comp_name, link=comp_link)

                team = Team(name=team_name, link=team_link)
                team.league = league

                xp = "./td[5]//img[@class='flaggenrahmen']/@title"
                team.country = [_.strip() for _ in i.xpath(xp) if _.strip()]

                transfer.new_team = team if out else self.team
                transfer.old_team = self.team if out else team

                # Block 6 - Fee or Loan
                transfer.fee = "".join(i.xpath(".//td[6]//text()"))

                xp = ".//td[6]//@href"
                transfer.fee_link = TF + "".join(i.xpath(xp)).strip()
                transfer.date = "".join(i.xpath(".//i/text()"))
                transfers.append(transfer)
            return transfers

        base_embed = self.team.base_embed
        base_embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
        base_embed.url = url

        embeds = []
        xp = (
            './/div[@class="box"][.//h2[contains(text(),"Arrivals")]]'
            '//tr[@class="even" or @class="odd"]'
        )

        if players_in := parse(tree.xpath(xp)):
            embed = base_embed.copy()
            embed.title = f"Inbound Transfers for {embed.title}"
            embed.colour = Colour.green()
            embeds += rows_to_embeds(embed, [i.inbound for i in players_in])

        xp = (
            './/div[@class="box"][.//h2[contains(text(),"Departures")]]'
            '//tr[@class="even" or @class="odd"]'
        )
        if players_out := parse(tree.xpath(xp), out=True):
            embed = base_embed.copy()
            embed.title = f"Outbound Transfers for {embed.title}"
            embed.colour = Colour.red()
            embeds += rows_to_embeds(embed, [i.outbound for i in players_out])

        if not embeds:
            embed = base_embed
            embed.title = f"No transfers found {embed.title}"
            embed.colour = Colour.orange()
            embeds = [embed]

        self.pages = embeds
        self.index = 0
        return await self.update()

    async def push_rumours(self) -> Message:
        """Send transfer rumours for a team to View"""
        e = self.team.base_embed

        url = self.team.link.replace("startseite", "geruechte")
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"Error {resp.status} connecting to {resp.url}"
                    return await self.bot.error(self.interaction, err)

        e.url = str(resp.url)
        e.title = f"Transfer rumours for {self.team.name}"
        e.set_author(name="Transfermarkt", url=resp.url, icon_url=FAVICON)

        rows = []
        xp = './/div[@class="large-8 columns"]/div[@class="box"]'
        for i in tree.xpath(xp)[0].xpath(".//tbody/tr"):
            xp = './/tm-tooltip[@data-type="player"]/a/@title'
            if not (name := "".join(i.xpath(xp)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xp = './/tm-tooltip[@data-type="player"]/a/@href'
            if not (link := "".join(i.xpath(xp)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            pos = "".join(i.xpath(".//td[2]//tr[2]/td/text()"))
            country = i.xpath(".//td[3]/img/@title")
            flag = " ".join([get_flag(i) for i in country])
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

        self.pages = rows_to_embeds(e, rows)
        self.index = 0
        return await self.update()

    async def push_trophies(self) -> Message:
        """Send trophies for a team to View"""
        url = self.team.link.replace("startseite", "erfolge")

        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"Error {resp.status} connecting to {resp.url}"
                    return await self.bot.error(self.interaction, err)

        trophies = []
        for i in tree.xpath('.//div[@class="box"][./div[@class="header"]]'):
            title = "".join(i.xpath(".//h2/text()"))

            xp = './/div[@class="erfolg_infotext_box"]/text()'
            dates = " ".join("".join(i.xpath(xp)).split()).replace(" ,", ",")
            trophies.append(f"**{title}**\n{dates}\n")

        e = self.team.base_embed
        e.title = f"{self.team.name} Trophy Case"

        if not trophies:
            trophies = ["No trophies found for team."]
        self.pages = rows_to_embeds(e, trophies)
        self.index = 0
        return await self.update()

    async def push_contracts(self) -> Message:
        """Push a list of a team's expiring contracts to the view"""
        e = self.team.base_embed
        e.description = ""
        target = self.team.link.replace("startseite", "vertragsende")

        async with self.bot.session.get(target) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"Error {resp.status} connecting to {resp.url}"
                    return await self.bot.error(self.interaction, err)

        e.url = target
        e.title = f"Expiring contracts for {self.team.name}"
        e.set_author(name="Transfermarkt", url=target, icon_url=FAVICON)

        rows = []

        xp = './/div[@class="large-8 columns"]/div[@class="box"]'
        for i in tree.xpath(xp)[0].xpath(".//tbody/tr"):

            xp = './/tm-tooltip[@data-type="player"]/a/@title'
            if not (name := "".join(i.xpath(xp)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xp = './/tm-tooltip[@data-type="player"]/a/@href'
            if not (link := "".join(i.xpath(xp)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            if not name and not link:
                continue

            pos = "".join(i.xpath(".//td[1]//tr[2]/td/text()"))

            age = "".join(i.xpath("./td[2]/text()"))
            age = age.split("(")[-1].replace(")", "").strip()

            country = i.xpath(".//td[3]/img/@title")
            flag = " ".join([get_flag(f) for f in country])
            date = "".join(i.xpath(".//td[4]//text()")).strip()

            expiry = Timestamp(datetime.strptime(date, "%b %d, %Y")).countdown

            option = "".join(i.xpath(".//td[5]//text()")).strip()
            option = f"\n∟ {option.title()}" if option != "-" else ""

            md = f"[{name}]({link})"
            rows.append(f"{flag} {md} {age}, {pos} ({expiry}){option}")

        if not rows:
            rows = ["No expiring contracts found."]

        self.pages = rows_to_embeds(e, rows)
        self.index = 0
        return await self.update()


class StadiumAttendance:
    """A Generic container representing the attendance data of a stadium"""

    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

        self.name = kwargs.pop("name", None)
        self.link: str = kwargs.pop("link", None)

        self.capacity: int = kwargs.pop("capacity", None)
        self.total: int = kwargs.pop("total", None)
        self.average: int = kwargs.pop("average", None)
        self.team: Team = kwargs.pop("team", None)

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
        md = self.team.markdown
        return f"[{self.name}]({self.link}) {self.capacity} ({md})"

    @property
    def average_row(self) -> str:
        """Formatted markdown for a stadium's average attendance"""
        md = self.team.markdown
        return f"[{self.name}]({self.link}) {self.average} ({md})"

    @property
    def total_row(self) -> str:
        """Formatted markdown for a stadium's total attendance"""
        team = self.team.markdown
        return f"[{self.name}]({self.link}) {self.total} ({team})"


class CompetitionView(BaseView):
    """A View representing a competition on TransferMarkt"""

    def __init__(self, interaction: Interaction, comp: Competition) -> None:
        super().__init__(interaction)
        self.comp: Competition = comp
        self.index: int = 0
        self.pages: list[Embed] = []
        self.parent: BaseView = None

    async def update(self, content: str = None) -> Message:
        """Send the latest version of the view"""
        self.clear_items()
        if self.parent is not None:
            self.add_item(Parent())
        add_page_buttons(self)

        self.add_item(
            FuncButton(label="Attendances", func=self.attendance, emoji="🏟️")
        )

        e = self.pages[self.index]

        return await self.bot.reply(
            self.interaction, content, embed=e, view=self
        )

    async def attendance(self) -> Message:
        """Fetch attendances for league's stadiums."""
        url = self.comp.link.replace("startseite", "besucherzahlen")
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"HTTP Error {resp.status} accessing transfermarkt"
                    return await self.bot.error(self.interaction, err)

        rows = []
        xp = './/table[@class="items"]/tbody/tr[@class="odd" or @class="even"]'
        for i in tree.xpath(xp):
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
        e = self.comp.base_embed.copy()
        e.title = f"Average Attendance data for {self.comp.name}"
        e.url = url
        ranked = sorted(rows, key=lambda x: x.average, reverse=True)

        en = [f"{i[0]}: {i[1].average_row}" for i in enumerate(ranked, 1)]
        embeds += rows_to_embeds(e, [i for i in en], 25)

        e = self.comp.base_embed.copy()
        e.title = f"Total Attendance data for {self.comp.name}"
        e.url = url
        ranked = sorted(rows, key=lambda x: x.total, reverse=True)

        en = [f"{i[0]}: {i[1].total_row}" for i in enumerate(ranked, 1)]
        embeds += rows_to_embeds(e, [i for i in en], 25)

        e = self.comp.base_embed.copy()
        e.title = f"Max Capacity data for {self.comp.name}"
        e.url = url
        ranked = sorted(rows, key=lambda x: x.capacity, reverse=True)

        en = [f"{i[0]}: {i[1].capacity_row}" for i in enumerate(ranked, 1)]
        embeds += rows_to_embeds(e, [i for i in en], 25)

        self.pages = embeds
        await self.update()


class SearchSelect(Select):
    """Dropdown."""

    def __init__(
        self, objects: list[Team | Competition], row: int = 4
    ) -> None:

        super().__init__(row=row, placeholder="Select correct option")

        self.objects: list[Team | Competition] = objects

        for n, obj in enumerate(objects):
            desc = obj.country[0] if obj.country else ""

            if isinstance(obj, Team):
                desc += f": {obj.league.name}" if obj.league else ""

            self.add_option(
                label=obj.name,
                description=desc[:100],
                value=str(n),
                emoji=obj.emoji,
            )

    async def callback(self, interaction: Interaction) -> Competition | Team:
        """Set view value to item."""
        await interaction.response.defer()
        self.view.value = self.objects[int(self.values[0])]
        self.view.stop()
        return self.view.value


class SearchView(BaseView):
    """A TransferMarkt Search in View Form"""

    query_string: str = None  # Should be Polymorphed
    match_string: str = None  # Should be Polymorphed
    category: str = None  # Should be Polymorphed

    def __init__(
        self, interaction: Interaction, query: str, fetch: bool = False
    ) -> None:

        super().__init__(interaction)

        self.index: int = 0
        self.value: Optional[Team | Competition] = None
        self.pages: list[Embed] = []
        self.query: str = query
        self.fetch: bool = fetch
        self._results: list = []

    def parse(self, rows: list) -> None:
        """This should always be polymorphed"""
        raise NotImplementedError

    async def on_timeout(self) -> None:
        """Cleanup."""
        self.clear_items()
        await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = None) -> None:
        """Populate Initial Results"""
        url = TF + "schnellsuche/ergebnis/schnellsuche"

        # Header names, scrape then compare (don't follow a pattern.)
        # TransferMarkt Search indexes from 1.
        p = {"query": self.query, self.query_string: self.index + 1}

        async with self.bot.session.post(url, params=p) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"Error {resp.status} Connecting to Transfermarkt"
                    return await self.bot.error(err)

        # Get trs of table after matching header / {ms} name.
        xp = (
            f".//div[@class='box']/h2[@class='content-box-headline']"
            f"[contains(text(),'{self.match_string}')]"
        )

        trs = f"{xp}/following::div[1]//tbody/tr"
        header = "".join(tree.xpath(f"{xp}//text()"))

        try:
            matches = int("".join([i for i in header if i.isdecimal()]))
        except ValueError:
            logging.error(f"ValueError when parsing header, {header}")
            matches = 0

        e = Embed(title=f"{matches} results for {self.query}", url=resp.url)

        cat = self.category.title()
        e.set_author(name=f"TransferMarkt Search: {cat}", icon_url=FAVICON)

        self.parse(tree.xpath(trs))

        if not self._results:
            self.index = 0
            err = f"No results found for {self.category}: {self.query}"
            return await self.bot.error(self.interaction, err)

        e = rows_to_embeds(e, [str(i) for i in self._results])[0]

        self.pages = [None] * max(matches // 10, 1)

        self.clear_items()
        add_page_buttons(self, row=1)

        if self.fetch and self._results:
            self.add_item(SearchSelect(objects=self._results))
        await self.bot.reply(self.interaction, content, embed=e, view=self)


class AgentSearch(SearchView):
    """View when searching for an Agent"""

    category = "Agents"
    query_string = "page"
    match_string = "for agents"

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows: list) -> list[Agent]:
        """Parse a transfermarkt page into a list of Agent Objects"""
        results = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()"))
            if TF not in (link := "".join(i.xpath(".//td[2]/a/@href"))):
                link = TF + link
            results.append(Agent(name=name, link=link))
        self._results = results


class CompetitionSearch(SearchView):
    """View When Searching for a Competition"""

    category = "Competitions"
    query_string = "Wettbewerb_page"
    match_string = "competitions"

    def __init__(
        self, interaction: Interaction, query: str, fetch: bool = False
    ) -> None:

        super().__init__(interaction, query, fetch=fetch)

    def parse(self, rows: list) -> list[Competition]:
        """Parse a transfermarkt page into a list of Competition Objects"""
        results = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()")).strip()
            link = TF + "".join(i.xpath(".//td[2]/a/@href")).strip()

            country = [_.strip() for _ in i.xpath(".//td[3]/img/@title")]
            country = [i for i in country if i]
            comp = Competition(name=name, link=link, country=country)

            results.append(comp)
        self._results = results


class PlayerSearch(SearchView):
    """A Search View for a player"""

    category = "Players"
    query_string = "Spieler_page"
    match_string = "for players"

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows) -> list[Player]:
        """Parse a transfer page to get a list of players"""
        results = []
        for i in rows:

            xp = (
                './/tm-tooltip[@data-type="player"]/a/@title |'
                './/td[@class="hauptlink"]/a/text()'
            )
            name = "".join(i.xpath(xp))

            xp = (
                './/tm-tooltip[@data-type="player"]/a/@href |'
                './/td[@class="hauptlink"]/a/@href'
            )
            link = "".join(i.xpath(xp))

            if link and TF not in link:
                link = TF + link

            player = Player(name=name, link=link)

            xp = './/img[@class="bilderrahmen-fixed"]/@src'
            player.picture = "".join(i.xpath(xp))

            try:
                xp = './/tm-tooltip[@data-type="club"]/a/@title'
                team_name = i.xpath(xp)[0]

                xp = './/tm-tooltip[@data-type="club"]/a/@href'
                team_link = i.xpath(xp)[0]
                if team_link and TF not in team_link:
                    team_link = TF + team_link

                team = Team(name=team_name, link=team_link)
                player.team = team
            except IndexError:
                pass

            player.age = "".join(i.xpath(".//td[4]/text()"))
            player.position = "".join(i.xpath(".//td[2]/text()"))

            xp = './/td/img[@class="flaggenrahmen"]/@title'
            player.country = i.xpath(xp)

            results.append(player)
        self._results = results


class RefereeSearch(SearchView):
    """View when searching for a Referee"""

    category = "Referees"
    query_string = "page"
    match_string = "for referees"

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows: list) -> list[Referee]:
        """Parse a transfer page to get a list of referees"""
        results = []
        for i in rows:
            xp = './/td[@class="hauptlink"]/a/@href'
            link = "".join(i.xpath(xp)).strip()
            if TF not in link:
                link = TF + link

            xp = './/td[@class="hauptlink"]/a/text()'
            name = "".join(i.xpath(xp)).strip()
            country = i.xpath(".//td/img[1]/@title")
            age = "".join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
            ref = Referee(name, link, country=country, age=age)

            results.append(ref)

        self._results = results


class StaffSearch(SearchView):
    """A Search View for a Staff member"""

    category = "Managers"
    query_string = "Trainer_page"
    match_string = "Managers"

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows: list) -> list[Staff]:
        """Parse a list of staff"""
        results = []
        for i in rows:
            xp = './/td[@class="hauptlink"]/a/@href'
            if TF not in (link := "".join(i.xpath(xp))):
                link = TF + link

            name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()'))

            staff = Staff(name, link)

            xp = './/img[@class="bilderrahmen-fixed"]/@src'
            staff.picture = "".join(i.xpath(xp))
            staff.age = "".join(i.xpath(".//td[3]/text()"))
            staff.job = "".join(i.xpath(".//td[5]/text()"))
            staff.country = i.xpath('.//img[@class="flaggenrahmen"]/@title')

            # TODO: Staff can take an actual Team() object.
            try:
                xp = './/tm-tooltip[@data-type="club"][1]/a/@title'
                staff.team = i.xpath(xp)[0]

                tl = i.xpath('.//tm-tooltip[@data-type="club"][1]/a/@href')[0]
                if TF not in tl:
                    tl = TF + tl
                staff.team_link = tl
            except IndexError:
                pass
            results.append(staff)
        self._results = results


class TeamSearch(SearchView):
    """A Search View for a team"""

    category = "Team"
    query_string = "Verein_page"
    match_string = "results: Clubs"

    def __init__(
        self, interaction: Interaction, query: str, fetch: bool = False
    ) -> None:

        super().__init__(interaction, query, fetch=fetch)

    def parse(self, rows: list) -> list[Team]:
        """Fetch a list of teams from a transfermarkt page"""
        r = []

        for i in rows:

            xp = './/tm-tooltip[@data-type="club"]/a/@title'
            if not (name := "".join(i.xpath(xp)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xp = './/tm-tooltip[@data-type="club"]/a/@href'
            if not (link := "".join(i.xpath(xp)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            xp = ".//tr[2]/td/a/@href"
            if TF not in (lg_lnk := "".join(i.xpath(xp)).strip()):
                lg_lnk = TF + lg_lnk

            lg_name = "".join(i.xpath(".//tr[2]/td/a/text()")).strip()

            xp = './/td/img[@class="flaggenrahmen" ]/@title'
            country = [c.strip() for c in i.xpath(xp) if c]

            xp = './/td[@class="suche-vereinswappen"]/img/@src'
            logo = "".join(i.xpath(xp))

            league = Competition(lg_name, lg_lnk, country=country, logo=logo)

            team = Team(name, link, league=league)

            r.append(team)
        self._results = r


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
