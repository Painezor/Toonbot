"""Utilities for working with transfers from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

from abc import abstractmethod
import datetime
import logging
from pydantic import BaseModel
from typing import TypeVar, Literal, Generic

import aiohttp
from lxml import html

TF = "https://www.transfermarkt.co.uk"
LOOP_URL = f"{TF}/transfers/neuestetransfers/statistik?minMarktwert="
MIN_MARKET_VALUE = 200000

logger = logging.getLogger("transfermarkt")


async def get_recent_transfers(mmv: int = MIN_MARKET_VALUE) -> list[Transfer]:
    """Get the most recent transfers"""
    url = LOOP_URL + format(mmv, ",").replace(",", ".")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s: %s", resp.status, resp.url)
                return []
            tree = html.fromstring(await resp.text())

        xpath = './/div[@class="responsive-table"]/div/table/tbody/tr'
        return [await Transfer.from_loop(i) for i in tree.xpath(xpath)]


class SearchResult(BaseModel):
    """A result from a transfermarkt search"""

    name: str
    link: str
    country: list[str] = []
    emoji: str = "🔎"
    picture: str | None = None


class TFCompetition(SearchResult):
    """An Object representing a competition from transfermarkt"""

    emoji: str = "🏆"

    async def get_attendance(self) -> list[StadiumAttendance]:  # list[StadAtt]
        """Fetch attendances for the competition"""
        url = self.link.replace("startseite", "besucherzahlen")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    rsn = await resp.text()
                    logger.error("%s %s: %s", resp.status, rsn, resp.url)
                tree = html.fromstring(await resp.text())

        xp = './/table[@class="items"]/tbody/tr[@class="odd" or @class="even"]'
        return [StadiumAttendance(i) for i in tree.xpath(xp)]


class TFTeam(SearchResult):
    """An object representing a Team from Transfermarkt"""

    emoji: str = "👕"
    league: TFCompetition | None = None

    @property
    def badge(self) -> str:
        """Return a link to the team's badge"""
        number = self.link.split("/")[-1]
        return f"https://tmssl.akamaized.net/images/wappen/head/{number}.png"

    async def get_contracts(self) -> list[Contract]:
        """Helper method for fetching contracts"""
        url = self.link.replace("startseite", "vertragsende")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("%s: %s", resp.status, resp.url)
                tree = html.fromstring(await resp.text())

        rows: list[Contract] = []

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

            age = "".join(i.xpath("./td[2]/text()")).split("(", maxsplit=1)[-1]

            country = [str(i).strip() for i in i.xpath(".//td[3]/img/@title")]

            date = "".join(i.xpath(".//td[4]//text()")).strip()
            dt = datetime.datetime.strptime(date, "%b %d, %Y")

            option = "".join(i.xpath(".//td[5]//text()")).strip()
            option = option.title() if option else None

            pos = "".join(i.xpath(".//td[1]//tr[2]/td/text()"))
            age = int(age.replace(")", "").strip())
            player = TFPlayer(
                name=name, link=link, position=pos, age=age, country=country
            )
            rows.append(Contract(player=player, expiry=dt, option=option))
        return rows

    async def get_league(self) -> TFCompetition:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.link) as resp:
                if resp.status != 200:
                    logger.error("%s: %s", resp.status, resp.url)
                tree = html.fromstring(await resp.text())

        name = tree.xpath('.//span[@class="data-header__club"]/a/text()')
        name = "".join(name).strip()
        url = tree.xpath('.//span[@class="data-header__club"]/a/@href')
        url = TF + "".join(url)
        self.league = TFCompetition(name=name, link=url)
        return self.league

    async def get_rumours(self) -> list[Rumour]:
        """Helper method for fetching rumours"""
        url = self.link.replace("startseite", "geruechte")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("%s: %s", resp.status, resp.url)
                tree = html.fromstring(await resp.text())

        rows: list[Rumour] = []
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

            country = i.xpath(".//td[3]/img/@title")
            pos = "".join(i.xpath(".//td[2]//tr[2]/td/text()"))
            plr = TFPlayer(name=name, link=link, country=country, position=pos)
            plr.age = int("".join(i.xpath("./td[4]/text()")).strip())

            team = "".join(i.xpath(".//td[5]//img/@alt"))

            team_link = "".join(i.xpath(".//td[5]//img/@href"))
            if TF not in team_link:
                team_link = TF + team_link

            team = TFTeam(name=team, link=team_link)
            source = "".join(i.xpath(".//td[8]//a/@href"))

            rows.append(Rumour(player=plr, team=team, url=source))
        return rows

    async def get_transfers(self) -> tuple[list[Transfer], list[Transfer]]:
        """
        Get recent transfers for the team

        Returns a Tuple of:
            List of Inbound Transfers
            List of Outbound Transfers
        """
        url = self.link.replace("startseite", "transfers")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("Status %s: %s", resp.status, url)
                tree = html.fromstring(await resp.text())

        xpath = (
            './/div[@class="box"][.//h2[contains(text(),"Arrivals")]]'
            '//tr[@class="even" or @class="odd"]'
        )

        inb = [Transfer.from_team(i, False, self) for i in tree.xpath(xpath)]

        xpath = (
            './/div[@class="box"][.//h2[contains(text(),"Departures")]]'
            '//tr[@class="even" or @class="odd"]'
        )
        out = [Transfer.from_team(i, True, self) for i in tree.xpath(xpath)]

        return inb, out

    async def get_trophies(self) -> list[Trophy]:
        """Get A list of Trophy Objects related to the team"""

        url = self.link.replace("startseite", "erfolge")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error("%s: %s", resp.status, resp.url)
                tree = html.fromstring(await resp.text())

        trophies: list[Trophy] = []
        for i in tree.xpath('.//div[@class="box"][./div[@class="header"]]'):
            title = "".join(i.xpath(".//h2/text()"))

            xpath = './/div[@class="erfolg_infotext_box"]/text()'
            split = "".join(i.xpath(xpath)).split()
            trophies.append(Trophy(name=title, dates=split))
        return trophies


class TFPlayer(SearchResult):
    """An Object representing a player from transfermarkt"""

    age: int | None = None
    team: TFTeam | None = None
    position: str | None = None


class Referee(SearchResult):
    """An object representing a referee from transfermarkt"""

    age: int | None = None


class Staff(SearchResult):
    """An object representing a Trainer or Manager from Transfermarkt"""

    team: TFTeam | None = None
    age: int | None = None
    job: str | None = None


class Agent(SearchResult):
    """An object representing an Agent from transfermarkt"""


class TransferFee(BaseModel):
    fee: str
    url: str


class Transfer(BaseModel):
    """An Object representing a transfer from transfermarkt"""

    player: TFPlayer

    new_team: TFTeam
    old_team: TFTeam

    fee: TransferFee
    date: str | None = None

    @staticmethod
    def get_player(node: html.HtmlElement) -> TFPlayer:
        name = "".join(node.xpath(".//td[1]//tr[1]/td[2]/a/text()")).strip()

        link = TF + "".join(node.xpath(".//td[1]//tr[1]/td[2]/a/@href"))

        player = TFPlayer(name=name, link=link)

        # Box 1 - Player Info
        player.picture = "".join(node.xpath(".//img/@data-src"))
        player.position = "".join(node.xpath("./td[1]//tr[2]/td/text()"))

        # Box 2 - Age
        player.age = int("".join(node.xpath("./td[2]//text()")).strip())

        # Box 3 - Country
        ctr = [str(i).strip() for i in node.xpath(".//td[3]/img/@title")]
        player.country = ctr
        return player

    @staticmethod
    def get_player_from_team(node: html.HtmlElement) -> TFPlayer:
        # Block 1 - Discard, Position Colour Marker.
        # Block 2 - Name, Link, Picture, Position
        xpath = './/tm-tooltip[@data-type="player"]/a/@title'
        if not (name := "".join(node.xpath(xpath)).strip()):
            name = "".join(node.xpath("./td[2]//a/text()")).strip()

        xpath = './tm-tooltip[@data-type="player"]/a/@href'
        if not (link := "".join(node.xpath(xpath))):
            link = "".join(node.xpath("./td[2]//a/@href"))

        if link and TF not in link:
            link = TF + link

        player = TFPlayer(name=name, link=link)
        xpath = './img[@class="bilderrahmen-fixed"]/@data-src'
        player.picture = "".join(node.xpath(xpath))

        xpath = "./td[2]//tr[2]/td/text()"
        player.position = "".join(node.xpath(xpath)).strip()

        # Block 3 - Age
        player.age = int("".join(node.xpath("./td[3]/text()")).strip())

        # Block 4 - Nationality
        xpath = "./td[4]//img/@title"
        player.country = [i.strip() for i in node.xpath(xpath) if i.strip()]
        return player

    @staticmethod
    async def team(node: html.HtmlElement, num: Literal["4", "5"]) -> TFTeam:
        # Box 4 - Old Team
        _ = f'.//td[{num}]//img[@class="tiny_wappen"]//@title'
        name = "".join(node.xpath(_))

        _ = f'.//td[{num}]//img[@class="tiny_wappen"]/parent::a/@href'
        link = TF + "".join(node.xpath(_))

        _ = f'.//td[{num}]//img[@class="flaggenrahmen"]/following-sibling::a/'
        lg_name = "".join(node.xpath(_ + "@title"))
        lg_link = ""

        team = TFTeam(name=name, link=link)
        if lg_name:
            lg_link = TF + "".join(node.xpath(_ + "@href"))
            lg_link = lg_link.replace("transfers", "startseite")
            if lg_link:
                lg_link = lg_link.split("/saison_id", maxsplit=1)[0]
            team.league = TFCompetition(name=lg_name, link=lg_link)
        else:
            team.league = await team.get_league()

        _ = f'.//td[{num}]//img[@class="flaggenrahmen"]/@alt'
        team.league.country = [str(i) for i in node.xpath(_)]
        team.country = team.league.country

        return team

    @staticmethod
    def get_other_team(node: html.HtmlElement) -> TFTeam:
        # Block 5 - Other Team
        xpath = './td[5]//td[@class="hauptlink"]/a/text()'
        name = "".join(node.xpath(xpath)).strip()

        xpath = './td[5]//td[@class="hauptlink"]/a/@href'
        if (link := "".join(node.xpath(xpath))) and TF not in link:
            link = TF + link

        xpath = "./td[5]//tr[2]//a/text()"
        lg_name = "".join(node.xpath(xpath)).strip()

        xpath = "./td[5]//tr[2]//a/@href"
        lg_link = "".join(node.xpath(xpath)).strip()

        xpath = "./td[5]//img[@class='flaggenrahmen']/@title"
        country = [i.strip() for i in node.xpath(xpath) if i.strip()]

        league = TFCompetition(name=lg_name, link=lg_link, country=country)
        team = TFTeam(name=name, link=link, league=league, country=country)
        return team

    @staticmethod
    def get_fee(node: html.HtmlElement) -> TransferFee:
        # Box 6 - Fee
        fee = "".join(node.xpath(".//td[6]//a/text()"))
        link = TF + "".join(node.xpath(".//td[6]//a/@href"))
        return TransferFee(fee=fee, url=link)

    @classmethod
    async def from_loop(cls, node: html.HtmlElement) -> Transfer:
        """Generated from the Transfer Ticker Loop"""
        player = cls.get_player(node)
        old = await cls.team(node, "4")
        new = await cls.team(node, "5")
        fee = cls.get_fee(node)
        player.team = new

        tran = Transfer(player=player, old_team=old, new_team=new, fee=fee)
        return tran

    @classmethod
    def from_team(
        cls, node: html.HtmlElement, out: bool, team: TFTeam
    ) -> Transfer:
        """Generated from a Team Object"""
        player = cls.get_player_from_team(node)

        other = cls.get_other_team(node)
        new = other if out else team
        old = team if out else other
        fee = cls.get_fee(node)

        tran = Transfer(player=player, new_team=new, old_team=old, fee=fee)
        tran.date = "".join(node.xpath(".//i/text()"))
        return tran

    @property
    def loan_fee(self) -> str:
        """
        Returns either Loan Information or the total fee of a player transfer
        """
        date = "" if self.date is None else f": {self.date}"
        output = f"[{self.fee.fee}]({self.fee.url}) {date}"
        return output

    def __str__(self) -> str:
        return f"{self.player} ({self.loan_fee})"


ResultT = TypeVar("ResultT", bound=SearchResult)


class TransfermarktSearch(Generic[ResultT]):
    """An object representing a connection to the transfermarket website"""

    query_string: str
    match_string: str
    category: str

    page_number: int
    current_url: str
    expected_results: int

    results: list[ResultT]
    value: ResultT

    def __init__(self, query: str) -> None:
        self.query = query

    @staticmethod
    @abstractmethod
    def parse(rows: list[html.HtmlElement]) -> list[ResultT]:
        raise NotImplementedError

    async def get_page(self, page: int = 1) -> list[ResultT]:
        """Generate a SearchView from the query"""
        url = TF + "/schnellsuche/ergebnis/schnellsuche"
        # Header names, scrape then compare (don't follow a pattern.)
        # TransferMarkt Search indexes from 1.
        params = {"query": self.query, self.query_string: page}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params) as resp:
                if resp.status != 200:
                    logger.error("%s: %s", resp.status, resp.url)
                self.current_url = str(resp.url)
                tree = html.fromstring(await resp.text())

        # Get trs of table after matching header / {ms} name.
        xpath = (
            f".//div[@class='box']/h2[@class='content-box-headline']"
            f"[contains(text(),'{self.match_string}')]"
        )

        trs = f"{xpath}/following::div[1]//tbody/tr"
        header = "".join(tree.xpath(f"{xpath}//text()"))

        try:
            count = int("".join([i for i in header if i.isdecimal()]))
        except ValueError:
            logger.error("ValueError when parsing header, %s", header)
            count = 0
        self.expected_results = count
        self.results = self.parse(tree.xpath(trs))
        return self.results


class AgentSearch(TransfermarktSearch[Agent]):
    """View when searching for an Agent"""

    category = "Agents"
    query_string = "page"
    match_string = "for agents"

    results: list[Agent]

    @staticmethod
    def parse(rows: list[html.HtmlElement]) -> list[Agent]:
        """Parse a transfermarkt page into a list of Agent Objects"""
        results: list[Agent] = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()"))
            if TF not in (link := "".join(i.xpath(".//td[2]/a/@href"))):
                link = TF + link
            results.append(Agent(name=name, link=link))
        return results


class CompetitionSearch(TransfermarktSearch[TFCompetition]):
    """View When Searching for a Competition"""

    category = "Competitions"
    query_string = "Wettbewerb_page"
    match_string = "competitions"

    value: TFCompetition

    @staticmethod
    def parse(rows: list[html.HtmlElement]) -> list[TFCompetition]:
        """Parse a transfermarkt page into a list of Competition Objects"""
        results: list[TFCompetition] = []
        for i in rows:
            name = "".join(i.xpath(".//td[2]/a/text()")).strip()
            link = TF + "".join(i.xpath(".//td[2]/a/@href")).strip()

            country = [
                _.strip()
                for _ in i.xpath(".//td[@class='flaggenrahmen']/img/@title")
            ]
            comp = TFCompetition(name=name, link=link, country=country)

            results.append(comp)
        return results


class PlayerSearch(TransfermarktSearch[TFPlayer]):
    """A Search View for a player"""

    category = "Players"
    query_string = "Spieler_page"
    match_string = "for players"

    value: TFPlayer

    @staticmethod
    def parse(rows: list[html.HtmlElement]) -> list[TFPlayer]:
        """Parse a transfer page to get a list of players"""
        results: list[TFPlayer] = []
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

            player = TFPlayer(name=name, link=link)

            xpath = './/img[@class="bilderrahmen-fixed"]/@src'
            player.picture = "".join(i.xpath(xpath))

            try:
                xpath = './/tm-tooltip[@data-type="club"]/a/@title'
                team_name = i.xpath(xpath)[0]

                xpath = './/tm-tooltip[@data-type="club"]/a/@href'
                team_link = i.xpath(xpath)[0]
                if team_link and TF not in team_link:
                    team_link = TF + team_link

                team = TFTeam(name=team_name, link=team_link)
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


class RefereeSearch(TransfermarktSearch[Referee]):
    """View when searching for a Referee"""

    category = "Referees"
    query_string = "page"
    match_string = "for referees"

    value: Referee

    @staticmethod
    def parse(rows: list[html.HtmlElement]) -> list[Referee]:
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
            ref = Referee(name=name, link=link, country=country, age=int(age))

            results.append(ref)
        return results


class StaffSearch(TransfermarktSearch[Staff]):
    """A Search View for a Staff member"""

    category = "Managers"
    query_string = "Trainer_page"
    match_string = "Managers"

    @staticmethod
    def parse(rows: list[html.HtmlElement]) -> list[Staff]:
        """Parse a list of staff"""
        results: list[Staff] = []
        for i in rows:
            xpath = './/td[@class="hauptlink"]/a/@href'
            if TF not in (link := "".join(i.xpath(xpath))):
                link = TF + link

            name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()'))

            staff = Staff(name=name, link=link)

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
                name = i.xpath(xpath)[0]

                leg = i.xpath('.//tm-tooltip[@data-type="club"][1]/a/@href')[0]
                if TF not in leg:
                    leg = TF + leg
                link = leg

                staff.team = TFTeam(name=name, link=link)
            except IndexError:
                pass
            results.append(staff)
        return results


class TeamSearch(TransfermarktSearch[TFTeam]):
    """A Search View for a team"""

    category = "Team"
    query_string = "Verein_page"
    match_string = "results: Clubs"

    value: TFTeam

    @staticmethod
    def parse(rows: list[html.HtmlElement]) -> list[TFTeam]:
        """Fetch a list of teams from a transfermarkt page"""
        output: list[TFTeam] = []
        for i in rows:
            xpath = ".//tr[2]/td/a/@href"
            if TF not in (link := "".join(i.xpath(xpath)).strip()):
                link = TF + link

            name = "".join(i.xpath(".//tr[2]/td/a/text()")).strip()
            xpath = './/td/img[@class="flaggenrahmen" ]/@title'
            country = [k.strip() for k in i.xpath(xpath) if k]

            xpath = './/td[@class="suche-vereinswappen"]/img/@src'
            logo = "".join(i.xpath(xpath))

            comp = TFCompetition(
                name=name, link=link, country=country, picture=logo
            )

            xpath = './/tm-tooltip[@data-type="club"]/a/@title'
            if not (name := "".join(i.xpath(xpath)).strip()):
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))

            xpath = './/tm-tooltip[@data-type="club"]/a/@href'
            if not (link := "".join(i.xpath(xpath)).strip()):
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link
            output.append(TFTeam(name=name, link=link, league=comp))
        return output


class StadiumAttendance:
    """A Generic container representing the attendance data of a stadium"""

    name: str
    link: str
    capacity: int
    total: int
    average: int
    team: TFTeam

    def __init__(self, data: html.HtmlElement) -> None:
        # Two Subnodes
        node = data.xpath(".//td/table//tr[1]")[0]
        team_node = data.xpath(".//td/table//tr[2]")[0]

        # Stadium info
        self.name = "".join(node.xpath(".//a/text()"))
        self.link = TF + "".join(node.xpath(".//@href"))

        # Team info
        name = "".join(team_node.xpath(".//a/text()"))
        link = TF + "".join(data.xpath(".//a/@href"))
        self.team = TFTeam(name=name, link=link)

        cap = "".join(data.xpath('.//td[@class="rechts"][1]/text()'))
        self.capacity = int(cap.replace(".", ""))

        tot = "".join(data.xpath('.//td[@class="rechts"][2]/text()'))
        self.total = int(tot.replace(".", ""))

        avg = "".join(data.xpath('.//td[@class="rechts"][3]/text()'))
        self.average = int(avg.replace(".", ""))


class Trophy(BaseModel):
    """A Trophy represented by TransferMarket"""

    name: str
    dates: list[str]


class Contract(BaseModel):
    """A Transfermarkt Contract"""

    player: TFPlayer
    expiry: datetime.datetime
    option: str | None = None


class Rumour(BaseModel):
    """A Transfermarkt Rumour"""

    player: TFPlayer
    team: TFTeam
    url: str
