"""Utilities for working with transfers from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import logging
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Optional, ClassVar

from discord import Interaction, Embed, Colour, Message, SelectOption
from discord.ui import View, Select
from lxml import html

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import FuncButton, add_page_buttons, Parent

if TYPE_CHECKING:
    from core import Bot

FAVICON = "https://upload.wikimedia.org/wikipedia/commons/f/fb/Transfermarkt_favicon.png"
TF = "https://www.transfermarkt.co.uk"


class SearchResult:
    """A result from a transfermarkt search"""
    emoji: str = None

    def __init__(self, name: str, link: str, **kwargs) -> None:
        self.name: str = name
        self.link: str = link
        self.country: list[str] = kwargs.pop('country', [])

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
        country = self.country
        if country is None:
            return "🌍"

        if isinstance(country, list):
            return ' '.join([x for x in [get_flag(i) for i in self.country] if x is not None])
        else:
            return get_flag(self.country)


class Competition(SearchResult):
    """An Object representing a competition from transfermarkt"""
    emoji: str = '🏆'

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)
        self.country: str = kwargs.pop('country', None)

    def __str__(self) -> str:
        return f"{self.flag} {self.markdown}"

    def view(self, interaction: Interaction) -> CompetitionView:
        """Send a view of this Competition to the user."""
        return CompetitionView(interaction, self)


class Team(SearchResult):
    """An object representing a Team from Transfermarkt"""
    emoji: str = '👕'

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name=name, link=link)

        self.league: Competition = kwargs.pop('league', None)
        self.country: str = kwargs.pop('country', None)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self) -> str:
        if self.league.markdown:
            return f"{self.flag} {self.markdown} ({self.league.markdown})"
        return f"{self.flag} {self.markdown}"

    @property
    def select_option(self) -> str:
        """A Select Option representation of this Team"""
        return SelectOption(emoji=self.flag, label=self.name, description=self.league.name)

    @property
    def badge(self) -> str:
        """Return a link to the team's badge"""
        number = self.link.split('/')[-1]
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

        self.team: Team = kwargs.pop('team', None)
        self.age: int = kwargs.pop('age', None)
        self.position: str = kwargs.pop('position', None)
        self.country: list[str] = kwargs.pop('country', [])
        self.picture: str = kwargs.pop('picture', None)

    def __repr__(self) -> str:
        return f"Player({self.__dict__})"

    def __str__(self) -> str:
        desc = [self.flag, self.markdown, self.age, self.position]

        if self.team is not None:
            desc.append(self.team.markdown)
        return ' '.join([i for i in desc if i is not None])


class Referee(SearchResult):
    """An object representing a referee from transfermarkt"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)

        self.age: int = kwargs.pop('age', None)
        self.country: list[str] = kwargs.pop('country', [])

    def __str__(self) -> str:
        output = f"{self.flag} {self.markdown}"
        if self.age is not None:
            output += f" {self.age}"
        return output


class Staff(SearchResult):
    """An object representing a Trainer or Manager from a Transfermarkt search"""

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)

        self.team: Team = kwargs.pop('team', None)
        self.age: int = kwargs.pop('age', None)
        self.job: str = kwargs.pop('job', None)
        self.country: list[str] = kwargs.pop('country', None)
        self.picture: str = kwargs.pop('picture', None)

    def __str__(self) -> str:
        team = self.team.markdown if self.team is not None else ''
        return f"{self.flag} {self.markdown} {self.age}, {self.job} {team}".strip()


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
        """Returns either Loan Information or the total fee of a player's transfer"""
        output = f"[{self.fee}]({self.fee_link})"

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
        e: Embed = Embed(description="", colour=0x1a3151)
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

        picture = self.player.picture
        if picture is not None and 'http' in picture:
            e.set_thumbnail(url=picture)

        desc.append(Timestamp().relative)
        e.description = "\n".join(desc)
        self.embed = e
        return self.embed


class TeamView(View):
    """A View representing a Team on TransferMarkt"""
    bot: ClassVar[Bot] = None

    def __init__(self, interaction: Interaction, team: Team) -> None:
        super().__init__()
        self.team: Team = team
        self.interaction: Interaction = interaction
        self.index: int = 0
        self.pages: list[Embed] = []
        self.parent: View = None

        if self.__class__.bot is None:
            self.__class__.bot = interaction.client

    async def on_timeout(self) -> Message:
        """Clean up"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = None) -> Message:
        """Send the latest version of the view"""
        self.clear_items()
        if self.parent:
            self.add_item(Parent())
            hide_row = 2
        else:
            hide_row = 3

        self.add_item(FuncButton(label="Transfers", func=self.push_transfers, emoji='🔄'))
        self.add_item(FuncButton(label="Rumours", func=self.push_rumours, emoji='🕵'))
        self.add_item(FuncButton(label="Trophies", func=self.push_trophies, emoji='🏆'))
        self.add_item(FuncButton(label="Contracts", func=self.push_contracts, emoji='📝'))
        add_page_buttons(self, row=hide_row)

        e = self.pages[self.index]
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)

    async def push_transfers(self) -> Message:
        """Push transfers to View"""
        url = self.team.link.replace('startseite', 'transfers')

        # # Winter window, Summer window.
        # now = datetime.datetime.now()
        # period, season_id = ("w", now.year - 1) if now.month < 7 else ("s", now.year)
        # url = f"{url}/saison_id/{season_id}/pos//0/w_s/plus/plus/1"
        #
        # p = {"w_s": period}
        async with self.bot.session.get(url) as resp:  # , params=p
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"Error {resp.status} connecting to {resp.url}"
                    return await self.bot.error(self.interaction, err)

        def parse(rows: list, out: bool = False) -> list[Transfer]:
            """Read through the transfers page and extract relevant data, returning a list of transfers"""

            transfers = []
            for i in rows:
                # Block 1 - Discard, Position Colour Marker.

                # Block 2 - Name, Link, Picture, Position
                name = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title')).strip()
                if not name:
                    name = ''.join(i.xpath('./td[2]//a/text()')).strip()

                link = ''.join(i.xpath('./tm-tooltip[@data-type="player"]/a/@href'))
                if not link:
                    link = ''.join(i.xpath('./td[2]//a/@href'))

                if link and TF not in link:
                    link = TF + link

                player = Player(name=name, link=link)
                player.picture = ''.join(i.xpath('./img[@class="bilderrahmen-fixed"]/@data-src'))
                player.position = ''.join(i.xpath('./td[2]//tr[2]/td/text()')).strip()

                # Block 3 - Age
                player.age = ''.join(i.xpath('./td[3]/text()')).strip()

                # Block 4 - Nationality
                player.country = [_.strip() for _ in i.xpath('./td[4]//img/@title') if _.strip()]

                transfer = Transfer(player=player)

                # Block 5 - Other Team
                team_name = ''.join(i.xpath('./td[5]//td[@class="hauptlink"]/a/text()')).strip()
                team_link = ''.join(i.xpath('./td[5]//td[@class="hauptlink"]/a/@href'))
                if team_link and TF not in team_link:
                    team_link = TF + team_link

                comp_name = ''.join(i.xpath("./td[5]//tr[2]//a/text()")).strip()
                comp_link = ''.join(i.xpath("./td[5]//tr[2]//a/@href")).strip()
                league = Competition(name=comp_name, link=comp_link)

                team = Team(name=team_name, link=team_link)
                team.league = league
                team.country = [_.strip() for _ in i.xpath("./td[5]//img[@class='flaggenrahmen']/@title") if _.strip()]

                transfer.new_team = team if out else self.team
                transfer.old_team = self.team if out else team

                # Block 6 - Fee or Loan
                transfer.fee = ''.join(i.xpath('.//td[6]//text()'))
                transfer.fee_link = TF + ''.join(i.xpath('.//td[6]//@href')).strip()
                transfer.date = ''.join(i.xpath('.//i/text()'))
                transfers.append(transfer)
            return transfers

        _ = tree.xpath('.//div[@class="box"][.//h2[contains(text(),"Arrivals")]]//tr[@class="even" or @class="odd"]')
        players_in = parse(_)
        _ = tree.xpath('.//div[@class="box"][.//h2[contains(text(),"Departures")]]//tr[@class="even" or @class="odd"]')
        players_out = parse(_, out=True)

        base_embed = self.team.base_embed
        base_embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
        base_embed.url = url

        embeds = []

        if players_in:
            e = deepcopy(base_embed)
            e.title = f"Inbound Transfers for {e.title}"
            e.colour = Colour.green()
            embeds += rows_to_embeds(e, [i.inbound for i in players_in])

        if players_out:
            e = deepcopy(base_embed)
            e.title = f"Outbound Transfers for {e.title}"
            e.colour = Colour.red()
            embeds += rows_to_embeds(e, [i.outbound for i in players_out])

        if not embeds:
            e = base_embed
            e.title = f"No transfers found {e.title}"
            e.colour = Colour.orange()
            embeds = [e]

        self.pages = embeds
        self.index = 0
        return await self.update()

    async def push_rumours(self) -> Message:
        """Send transfer rumours for a team to View"""
        e = self.team.base_embed
        url = self.team.link.replace('startseite', 'geruechte')
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return await self.bot.error(self.interaction, f"Error {resp.status} connecting to {resp.url}")

        e.url = url
        e.title = f"Transfer rumours for {self.team.name}"
        e.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)

        rows = []
        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title')).strip()
            link = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@href')).strip()

            if not name:
                name = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@title'))
            if not link:
                link = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            pos = ''.join(i.xpath('.//td[2]//tr[2]/td/text()'))
            country = i.xpath('.//td[3]/img/@title')
            flag = ' '.join([get_flag(i) for i in country])
            age = ''.join(i.xpath('./td[4]/text()')).strip()
            team = ''.join(i.xpath('.//td[5]//img/@alt'))
            team_link = ''.join(i.xpath('.//td[5]//img/@href'))
            if "transfermarkt" not in team_link:
                team_link = "http://www.transfermarkt.com" + team_link
            source = ''.join(i.xpath('.//td[8]//a/@href'))
            src = f"[Info]({source})"
            rows.append(f"{flag} **[{name}]({link})** ({src})\n{age}, {pos} [{team}]({team_link})\n")

        if not rows:
            rows = ["No rumours about new signings found."]

        self.pages = rows_to_embeds(e, rows)
        self.index = 0
        return await self.update()

    async def push_trophies(self) -> Message:
        """Send trophies for a team to View"""
        url = self.team.link.replace('startseite', 'erfolge')

        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    raise ConnectionError(f"Error {resp.status} connecting to {resp.url}")

        rows = tree.xpath('.//div[@class="box"][./div[@class="header"]]')
        trophies = []
        for i in rows:
            title = ''.join(i.xpath('.//h2/text()'))
            dates = ''.join(i.xpath('.//div[@class="erfolg_infotext_box"]/text()'))
            dates = " ".join(dates.split()).replace(' ,', ',')
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
        target = self.team.link.replace('startseite', 'vertragsende')

        async with self.bot.session.get(target) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return await self.bot.error(self.interaction, f"Error {resp.status} connecting to {resp.url}")

        e.url = target
        e.title = f"Expiring contracts for {self.team.name}"
        e.set_author(name="Transfermarkt", url=target, icon_url=FAVICON)

        rows = []

        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title')).strip()
            link = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@href')).strip()

            if not name:
                name = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@title'))
            if not link:
                link = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            if not name and not link:
                continue

            pos = ''.join(i.xpath('.//td[1]//tr[2]/td/text()'))
            age = ''.join(i.xpath('./td[2]/text()')).split('(')[-1].replace(')', '').strip()

            country = i.xpath('.//td[3]/img/@title')
            flag = " ".join([get_flag(f) for f in country])
            date = ''.join(i.xpath('.//td[4]//text()')).strip()

            _ = datetime.strptime(date, "%b %d, %Y")
            expiry = Timestamp(_).countdown

            option = ''.join(i.xpath('.//td[5]//text()')).strip()
            option = f"\n∟ {option.title()}" if option != "-" else ""

            rows.append(f"{flag} [{name}]({link}) {age}, {pos} ({expiry}){option}")

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

        self.name = kwargs.pop('name', None)
        self.link: str = kwargs.pop('link', None)

        self.capacity: int = kwargs.pop('capacity', None)
        self.total: int = kwargs.pop('total', None)
        self.average: int = kwargs.pop('average', None)
        self.team: Team = kwargs.pop('team', None)

    def __str__(self) -> str:
        """Formatted markdown for Stadium Attendance"""
        return f"[{self.name}]({self.link}) {self.average} ({self.team.markdown})" \
               f"\n*Capacity: {self.capacity} | Total: {self.total}*\n"

    @property
    def capacity_row(self) -> str:
        """Formatted markdown for a stadium's max capacity"""
        return f"[{self.name}]({self.link}) {self.capacity} ({self.team.markdown})"

    @property
    def average_row(self) -> str:
        """Formatted markdown for a stadium's average attendance"""
        return f"[{self.name}]({self.link}) {self.average} ({self.team.markdown})"

    @property
    def total_row(self) -> str:
        """Formatted markdown for a stadium's total attendance"""
        return f"[{self.name}]({self.link}) {self.total} ({self.team.markdown})"


class CompetitionView(View):
    """A View representing a competition on TransferMarkt"""
    bot: ClassVar[Bot] = None

    def __init__(self, interaction: Interaction, comp: Competition) -> None:
        super().__init__()
        self.comp: Competition = comp
        self.interaction: Interaction = interaction
        self.index: int = 0
        self.pages: list[Embed] = []
        self.parent: View = None

        if self.__class__.bot is None:
            self.__class__.bot = interaction.client

    async def on_timeout(self) -> Message:
        """Clean up"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = None) -> Message:
        """Send the latest version of the view"""
        self.clear_items()
        if self.parent is not None:
            self.add_item(Parent())
        add_page_buttons(self)

        self.add_item(FuncButton(label="Attendances", func=self.attendance, emoji='🏟️'))
        return await self.bot.reply(self.interaction, content=content, embed=self.pages[self.index], view=self)

    async def attendance(self) -> Message:
        """Fetch attendances for league's stadiums."""
        url = self.comp.link.replace('startseite', 'besucherzahlen')
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return await self.bot.error(self.interaction, f"HTTP Error {resp.status} accessing transfermarkt")

        rows = []
        for i in tree.xpath('.//table[@class="items"]/tbody/tr[@class="odd" or @class="even"]'):
            # Two sub rows.
            try:
                stadium = i.xpath('.//td/table//tr[1]')[0]
                team = i.xpath('.//td/table//tr[2]')[0]
            except IndexError:
                continue

            # Stadium info
            stad = "".join(stadium.xpath('.//a/text()'))
            stad_link = TF + "".join(stadium.xpath('.//@href'))
            # Team info
            team_name = "".join(team.xpath('.//a/text()'))
            team_link = TF + "".join(i.xpath('.//a/@href'))
            try:
                cap = int("".join(i.xpath('.//td[@class="rechts"][1]/text()')).replace('.', ''))
                tot = int("".join(i.xpath('.//td[@class="rechts"][2]/text()')).replace('.', ''))
                avg = int("".join(i.xpath('.//td[@class="rechts"][3]/text()')).replace('.', ''))
            except ValueError:
                continue

            team = Team(team_name, team_link)
            rows.append(StadiumAttendance(name=stad, link=stad_link, capacity=cap, average=avg, total=tot, team=team))

        embeds = []
        # Average
        e = self.comp.base_embed
        e.title = f"Average Attendance data for {self.comp.name}"
        e.url = url
        ranked = sorted(rows, key=lambda x: x.average, reverse=True)
        enumerated = [f"{i[0]}: {i[1].average_row}" for i in enumerate(ranked, 1)]
        embeds += rows_to_embeds(e, [i for i in enumerated], 25)

        e = self.comp.base_embed
        e.title = f"Total Attendance data for {self.comp.name}"
        e.url = url
        ranked = sorted(rows, key=lambda x: x.total, reverse=True)
        enumerated = [f"{i[0]}: {i[1].total_row}" for i in enumerate(ranked, 1)]
        embeds += rows_to_embeds(e, [i for i in enumerated], 25)

        e = self.comp.base_embed
        e.title = f"Max Capacity data for {self.comp.name}"
        e.url = url
        ranked = sorted(rows, key=lambda x: x.capacity, reverse=True)
        enumerated = [f"{i[0]}: {i[1].capacity_row}" for i in enumerate(ranked, 1)]
        embeds += rows_to_embeds(e, [i for i in enumerated], 25)

        self.pages = embeds
        await self.update()


class SearchSelect(Select):
    """Dropdown."""

    def __init__(self, objects: list[Team | Competition], row: int = 4) -> None:
        super().__init__(row=row, placeholder="Select correct option")
        self.objects: list[Team | Competition] = objects
        for n, obj in enumerate(objects):
            desc = obj.country[0] if obj.country else ""
            if isinstance(obj, Team):
                desc += f": {obj.league.name}" if obj.league else ""
            self.add_option(label=obj.name, description=desc[:100], value=str(n), emoji=obj.emoji)

    async def callback(self, interaction: Interaction) -> Competition | Team:
        """Set view value to item."""
        await interaction.response.defer()
        self.view.value = self.objects[int(self.values[0])]
        self.view.stop()
        return self.view.value


class SearchView(View):
    """A TransferMarkt Search in View Form"""
    bot: ClassVar[Bot] = None
    query_string: str = None  # Should be Polymorphed
    match_string: str = None  # Should be Polymorphed
    category: str = None  # Should be Polymorphed

    def __init__(self, interaction: Interaction, query: str, fetch: bool = False) -> None:
        super().__init__()

        self.index: int = 0
        self.value: Optional[Team | Competition] = None
        self.pages: list[Embed] = []

        self.query: str = query
        self.fetch: bool = fetch
        self.interaction: Interaction = interaction

        self._results: list = []

        if self.__class__.bot is None:
            self.__class__.bot = interaction.client

    def parse(self, rows: list) -> None:
        """This should always be polymorphed"""
        raise NotImplementedError

    async def on_error(self, error: Exception, item, interaction: Interaction) -> None:
        """Error handling & logging."""
        logging.info(f"Please typehint 'error' to {type(error)}")
        logging.info(f"Please typehint 'item' to {type(item)}")

        logging.error(f"Error in {self.__class__.__name__}\n"
                      f"Command: {self.interaction.command}, "
                      f"{item}: {item.__dict__}, {interaction}")
        raise error

    async def on_timeout(self) -> Message:
        """Cleanup."""
        self.clear_items()
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = None) -> Message:
        """Populate Initial Results"""
        url = 'https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'

        # Header names, scrape then compare (because they don't follow a pattern.)

        # TransferMarkt Search indexes from 1.
        p = {"query": self.query, self.query_string: self.index + 1}

        async with self.bot.session.post(url, params=p) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    raise ConnectionError(f"Error {resp.status} Connecting to Transfermarkt")

        # Get trs of table after matching header / {ms} name.

        header_xpath = f".//div[@class='box']/h2[@class='content-box-headline'][contains(text(),'{self.match_string}')]"

        trs = f"{header_xpath}/following::div[1]//tbody/tr"
        header = ''.join(tree.xpath(f"{header_xpath}//text()"))

        try:
            matches = int(''.join([i for i in header if i.isdecimal()]))
        except ValueError:
            logging.error(f"ValueError when parsing header, {header}")
            matches = 0

        e: Embed = Embed(title=f"{matches} results for {self.query}", url=resp.url)
        e.set_author(name=f"TransferMarkt Search: {self.category.title()}", icon_url=FAVICON)

        self.parse(tree.xpath(trs))

        if not self._results:
            self.index = 0
            return await self.bot.error(self.interaction, f"🚫 No results found for {self.category}: {self.query}")

        e = rows_to_embeds(e, [str(i) for i in self._results])[0]

        self.pages = [None] * max(matches // 10, 1)

        self.clear_items()
        add_page_buttons(self, row=1)

        if self.fetch and self._results:
            self.add_item(SearchSelect(objects=self._results))
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class AgentSearch(SearchView):
    """View when searching for an Agent"""
    category = "Agents"
    query_string = "page"
    match_string = 'for agents'

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows: list) -> list[Agent]:
        """Parse a transfermarkt page into a list of Agent Objects"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//td[2]/a/text()'))
            link = ''.join(i.xpath('.//td[2]/a/@href'))
            if "https://www.transfermarkt.co.uk" not in link:
                link = "https://www.transfermarkt.co.uk" + link
            results.append(Agent(name=name, link=link))
        self._results = results


class CompetitionSearch(SearchView):
    """View When Searching for a Competition"""
    category = "Competitions"
    query_string = "Wettbewerb_page"
    match_string = "competitions"

    def __init__(self, interaction: Interaction, query: str, fetch: bool = False) -> None:
        super().__init__(interaction, query, fetch=fetch)

    def parse(self, rows: list) -> list[Competition]:
        """Parse a transfermarkt page into a list of Competition Objects"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//td[2]/a/text()')).strip()
            link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[2]/a/@href')).strip()

            country = [_.strip() for _ in i.xpath('.//td[3]/img/@title') if _.strip()]
            comp = Competition(name=name, link=link, country=country)

            results.append(comp)
        self._results = results


class PlayerSearch(SearchView):
    """A Search View for a player"""
    category = "Players"
    query_string = "Spieler_page"
    match_string = 'for players'

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows) -> list[Player]:
        """Parse a transfer page to get a list of players"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title | .//td[@class="hauptlink"]/a/text()'))
            link = ''.join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@href | .//td[@class="hauptlink"]/a/@href'))

            if link and "transfermarkt" not in link:
                link = f"https://www.transfermarkt.co.uk{link}"

            player = Player(name=name, link=link)
            player.picture = ''.join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))

            try:
                team_name = i.xpath('.//tm-tooltip[@data-type="club"]/a/@title')[0]
                team_link = i.xpath('.//tm-tooltip[@data-type="club"]/a/@href')[0]
                if team_link and "transfermarkt" not in team_link:
                    team_link = f"https://www.transfermarkt.co.uk{team_link}"

                team = Team(name=team_name, link=team_link)
                player.team = team
            except IndexError:
                pass

            player.age = ''.join(i.xpath('.//td[4]/text()'))
            player.position = ''.join(i.xpath('.//td[2]/text()'))
            player.country = i.xpath('.//td/img[@class="flaggenrahmen"]/@title')
            results.append(player)
        self._results = results


class RefereeSearch(SearchView):
    """View when searching for a Referee"""
    category = "Agents"
    query_string = "page"
    match_string = 'for agents'

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows: list) -> list[Referee]:
        """Parse a transfer page to get a list of referees"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
            link = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
            if "https://www.transfermarkt.co.uk" not in link:
                link = f"https://www.transfermarkt.co.uk{link}"

            result = Referee(name=name, link=link)

            result.age = ''.join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
            result.country = i.xpath('.//td/img[1]/@title')
            results.append(result)
        self._results = results


class StaffSearch(SearchView):
    """A Search View for a Staff member"""
    category = "Managers"
    query_string = "Trainer_page"
    match_string = 'Managers'

    def __init__(self, interaction: Interaction, query: str) -> None:
        super().__init__(interaction, query)

    def parse(self, rows: list) -> list[Staff]:
        """Parse a list of staff"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//td[@class="hauptlink"]/a/text()'))
            link = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            staff = Staff(name, link)
            staff.picture = ''.join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))

            if link and "transfermarkt" not in link:
                link = f"https://www.transfermarkt.co.uk{link}"
            staff.link = link

            try:
                staff.team = i.xpath('.//tm-tooltip[@data-type="club"][1]/a/@title')[0]
                tl = i.xpath('.//tm-tooltip[@data-type="club"][1]/a/@href')[0]
                if tl and "transfermarkt" not in tl:
                    tl = f"https://www.transfermarkt.co.uk{tl}"
                staff.team_link = tl
            except IndexError:
                pass

            staff.age = ''.join(i.xpath('.//td[3]/text()'))
            staff.job = ''.join(i.xpath('.//td[5]/text()'))
            staff.country = i.xpath('.//img[@class="flaggenrahmen"]/@title')
            results.append(staff)
        self._results = results


class TeamSearch(SearchView):
    """A Search View for a team"""
    category = "Players"
    query_string = "Verein_page"
    match_string = 'results: Clubs'

    def __init__(self, interaction: Interaction, query: str, fetch: bool = False) -> None:
        super().__init__(interaction, query, fetch=fetch)

    def parse(self, rows: list) -> list[Team]:
        """Fetch a list of teams from a transfermarkt page"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//tm-tooltip[@data-type="club"]/a/@title')).strip()
            if not name:
                name = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            link = ''.join(i.xpath('.//tm-tooltip[@data-type="club"]/a/@href')).strip()
            if not link:
                link = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@href'))
            if link:
                link = f"{TF}{link}" if "transfermarkt" not in link else link

            team = Team(name=name, link=link)

            lg_name = ''.join(i.xpath('.//tr[2]/td/a/text()')).strip()
            lg_lnk = ''.join(i.xpath('.//tr[2]/td/a/@href')).strip()
            if lg_lnk and "transfermarkt" not in lg_lnk:
                lg_lnk = f"{TF}{lg_lnk}"
            league = Competition(name=lg_name, link=lg_lnk)

            team.league = league
            team.country = [_.strip() for _ in i.xpath('.//td/img[@class="flaggenrahmen" ]/@title') if _.strip()]
            team.logo = ''.join(i.xpath('.//td[@class="suche-vereinswappen"]/img/@src'))

            results.append(team)
        self._results = results


DEFAULT_LEAGUES = [Competition(name="Premier League", country="England",
                               link="https://www.transfermarkt.co.uk/premier-league/startseite/wettbewerb/GB1"),
                   Competition(name="Championship", country="England",
                               link="https://www.transfermarkt.co.uk/championship/startseite/wettbewerb/GB2"),
                   Competition(name="Eredivisie", country="Netherlands",
                               link="https://www.transfermarkt.co.uk/eredivisie/startseite/wettbewerb/NL1"),
                   Competition(name="Bundesliga", country="Germany",
                               link="https://www.transfermarkt.co.uk/bundesliga/startseite/wettbewerb/L1"),
                   Competition(name="Serie A", country="Italy",
                               link="https://www.transfermarkt.co.uk/serie-a/startseite/wettbewerb/IT1"),
                   Competition(name="LaLiga", country="Spain",
                               link="https://www.transfermarkt.co.uk/laliga/startseite/wettbewerb/ES1"),
                   Competition(name="Ligue 1", country="France",
                               link="https://www.transfermarkt.co.uk/ligue-1/startseite/wettbewerb/FR1"),
                   Competition(name="Major League Soccer", country="United States",
                               link="https://www.transfermarkt.co.uk/major-league-soccer/startseite/wettbewerb/MLS1")]
