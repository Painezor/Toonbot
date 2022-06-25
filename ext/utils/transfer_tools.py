"""Utilities for working with transfers from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import datetime
from copy import deepcopy
from typing import List, TYPE_CHECKING, Optional

from discord import Interaction, Embed, Colour, Message
from discord.ui import View, Select, Button
from lxml import html
from pycountry import countries

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator, FuncButton, add_page_buttons

if TYPE_CHECKING:
    from core import Bot

# Manual Country Code Flag Dict
country_dict = {
    "American Virgin Islands": "vi",
    "Antigua and Barbuda": "ag",
    "Bolivia": "bo",
    "Bosnia-Herzegovina": "ba",
    "Bosnia and Herzegovina": "ba",
    "Botsuana": "bw",
    "British Virgin Islands": "vg",
    "Cape Verde": "cv",
    "Cayman-Inseln": "ky",
    "Chinese Taipei (Taiwan)": "tw",
    "Congo DR": "cd",
    "Curacao": "cw",
    "DR Congo": "cd",
    "Cote d'Ivoire": "ci",
    "CSSR": "cz",
    "Czech Republic": "cz",
    "East Timor": "tl",
    "Faroe Island": "fo",
    "Federated States of Micronesia": "fm",
    "Hongkong": "hk",
    "Iran": "ir",
    "Ivory Coast": "ci",
    "Korea, North": "kp",
    "Korea, South": "kr",
    "Kosovo": "xk",
    "Laos": "la",
    "Macedonia": "mk",
    "Mariana Islands": "mp",
    "Moldova": "md",
    "N/A": "x",
    "Netherlands Antilles": "nl",
    "Neukaledonien": "nc",
    "Northern Ireland": "gb",
    "Osttimor": "tl",
    "Palästina": "ps",
    "Palestine": "pa",
    "Republic of the Congo": "cd",
    "Rumänien": "ro",
    "Russia": "ru",
    "Sao Tome and Principe": "st",
    "Sao Tome and Princip": "st",
    "Sint Maarten": "sx",
    "Southern Sudan": "ss",
    "South Korea": "kr",
    "St. Kitts & Nevis": "kn",
    "St. Lucia": "lc",
    "St. Vincent & Grenadinen": "vc",
    "Syria": "sy",
    "Tahiti": "fp",
    "Tanzania": "tz",
    "The Gambia": "gm",
    "Trinidad and Tobago": "tt",
    "Turks- and Caicosinseln": "tc",
    "USA": "us",
    "Venezuela": "ve",
    "Vietnam": "vn"}

UNI_DICT = {
    "a": "🇦", "b": "🇧", "c": "🇨", "d": "🇩", "e": "🇪",
    "f": "🇫", "g": "🇬", "h": "🇭", "i": "🇮", "j": "🇯",
    "k": "🇰", "l": "🇱", "m": "🇲", "n": "🇳", "o": "🇴",
    "p": "🇵", "q": "🇶", "r": "🇷", "s": "🇸", "t": "🇹",
    "u": "🇺", "v": "🇻", "w": "🇼", "x": "🇽", "y": "🇾", "z": "🇿"
}

FAVICON = "https://upload.wikimedia.org/wikipedia/commons/f/fb/Transfermarkt_favicon.png"
TF = "https://www.transfermarkt.co.uk"


def get_flag(country: str) -> Optional[str]:
    """Get a flag emoji from a string representing a country"""
    if not country:
        return None

    for x in ['Retired', 'Without Club']:
        country = country.strip().replace(x, '')

    match country.lower():
        case "england" | 'en':
            return '🏴󠁧󠁢󠁥󠁮󠁧󠁿'
        case "scotland":
            return '🏴󠁧󠁢󠁳󠁣󠁴󠁿'
        case "wales":
            return '🏴󠁧󠁢󠁷󠁬󠁳󠁿'
        case "world":
            return '🌍'
        case 'cs':
            return '🇨🇿'
        case 'ko':
            return '🇰🇷'
        case 'zh':
            return '🇨🇳'
        case 'ja':
            return '🇯🇵'

    if len(country) == 2:
        country = country.lower()

        for key, value in UNI_DICT.items():
            country = country.replace(key, value)
        return country

    # Check if py country has country

    try:
        return countries.get(name=country.title()).alpha_2
    except (KeyError, AttributeError):
        pass
    if country in country_dict:
        return country_dict.get(country)

    print(f'No flag found for country: {country}')
    country = country.lower()
    for key, value in UNI_DICT.items():
        country = country.replace(key, value)
    return country


class TransferResult:
    """A result from a transfermarkt search"""
    bot: Bot

    def __init__(self, name: str, link: str) -> None:
        self.name: str = name
        self.link: str = link

    def __repr__(self) -> str:
        return f"TransferResult({self.__dict__})"

    @property
    def base_embed(self) -> Embed:
        """A generic embed used for transfermarkt objects"""
        e: Embed = Embed(color=Colour.dark_blue(), description="")
        e.set_author(name="TransferMarkt")
        return e

    @property
    def markdown(self) -> str:
        """Return markdown formatted link"""
        return f"[{self.name}]({self.link})"

    @property
    def flag(self) -> str:
        """Return a flag representing the country"""
        # Return the 'earth' emoji if caller does not have a country.
        country = getattr(self, 'country', None)
        if country is None:
            return "🌍"

        if isinstance(country, list):
            return ''.join([get_flag(i) for i in self.country])
        else:
            return get_flag(self.country)


class Competition(TransferResult):
    """An Object representing a competition from transfermarkt"""
    __slots__ = {'country': 'The country this competition is from'}

    emoji: str = '🏆'

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name, link)

        for k, v in kwargs.items():
            setattr(self, k, v)

        self.country: Optional[List[str]] = None

    def __str__(self) -> str:
        return f"{self.flag} {self.markdown}"

    def view(self, interaction: Interaction) -> CompetitionView:
        """Send a view of this Competition to the user."""
        return CompetitionView(interaction, self)


class Team(TransferResult):
    """An object representing a Team from Transfermarkt"""
    __slots__ = {'league': 'The competition this team takes part in.',
                 'country': 'A list of countries this Team is in'}
    emoji: str = '👕'

    def __init__(self, name: str, link: str, **kwargs) -> None:
        super().__init__(name=name, link=link)
        for k, v in kwargs.items():
            setattr(self, k, v)

        # Type Hint
        self.league: Competition
        self.country: str

    def __str__(self) -> str:
        out = f"{self.flag} {self.markdown}"
        self.league: Optional[Competition] = None

        if getattr(self, 'league', None) is not None:
            return out + f" ({self.league.markdown})"
        return out

    @property
    def dropdown(self) -> str:
        """Text to be sent to the dropdown Option"""
        return f"{self.flag} {self.name} ({self.league.name})"

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

    async def get_contracts(self, bot: 'Bot', interaction: Interaction) -> List[Embed] | Message:
        """Get a list of expiring contracts for a team."""
        e = self.base_embed
        e.description = ""
        target = self.link
        target = target.replace('startseite', 'vertragsende')

        async with bot.session.get(target) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return await bot.error(interaction, f"Error {resp.status} connecting to {resp.url}")

        e.url = target
        e.title = f"Expiring contracts for {e.title}"
        e.set_author(name="Transfermarkt", url=str(resp.url))

        rows = []

        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = ''.join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
            if not name:
                continue

            link = ''.join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/@href'))
            link = f"https://www.transfermarkt.co.uk{link}"

            pos = ''.join(i.xpath('.//td[1]//tr[2]/td/text()'))
            age = ''.join(i.xpath('./td[2]/text()')).split('(')[-1].replace(')', '').strip()
            flag = " ".join([get_flag(f) for f in i.xpath('.//td[3]/img/@title')])
            date = ''.join(i.xpath('.//td[4]//text()')).strip()
            _ = datetime.datetime.strptime(date, "%b %d, %Y")
            expiry = Timestamp(_).countdown

            option = ''.join(i.xpath('.//td[5]//text()')).strip()
            option = f"\n∟ {option.title()}" if option != "-" else ""

            rows.append(f"{flag} [{name}]({link}) {age}, {pos} ({expiry}){option}")

        rows = ["No expiring contracts found."] if not rows else rows

        view = Paginator(bot, interaction, rows_to_embeds(e, rows))
        await view.update()

    def view(self, interaction: Interaction) -> TeamView:
        """Send a view of this Team to the user."""
        return TeamView(interaction, self)


class Player(TransferResult):
    """An Object representing a player from transfermarkt"""
    __slots__ = {'team': 'The team this player plays for',
                 'age': 'The age of the player',
                 'position': 'The position this player plays for the team',
                 'country': 'A list of countries this player plays for',
                 'picture': 'A link to a picture of this player'}

    def __init__(self, name: str, link: str) -> None:
        super().__init__(name, link)
        team: Team
        age: int
        position: str
        country: List[str]
        picture: str

    def __repr__(self) -> str:
        return f"Player({self.__dict__})"

    def __str__(self) -> str:
        out = f"{self.flag} {self.markdown}"

        if hasattr(self, 'age'):
            out += f" {self.age}"

        if hasattr(self, 'position'):
            out += f" {self.position}"

        if hasattr(self, 'team'):
            try:
                out += f" {self.team.markdown}"
            except AttributeError:
                pass
        return out


class Referee(TransferResult):
    """An object representing a referee from transfermarkt"""
    __slots__ = {'age': 'The age of the referee'}
    age: int
    country: List[str] = None

    def __init__(self, name: str, link: str) -> None:
        super().__init__(name, link)

    def __str__(self) -> str:
        output = f"{self.flag} {self.markdown}"
        if getattr(self, 'age', None) is not None:
            output += f" {self.age}"
        return output


class Staff(TransferResult):
    """An object representing a Trainer or Manager from a Transfermarkt search"""
    __slots__ = {'team': 'The team this person works for',
                 'age': "The age of this person",
                 "job": "The job of this person",
                 "country": "A list of countries representing this person's nationality",
                 "picture": "A link to a picture of this person"}
    team: Team
    age: int
    job: str
    country: List[str]
    picture: str

    def __init__(self, name: str, link: str) -> None:
        super().__init__(name, link)

    def __repr__(self) -> str:
        return f"Manager({self.__dict__})"

    def __str__(self) -> str:
        return f"{self.flag} {self.markdown} {self.age}, {self.job} {self.team.markdown})"


class Transfer:
    """An Object representing a transfer from transfermarkt"""
    __slots__ = {'link': 'A string representing a link to the transfer',
                 'player': 'A player Object representing The player in the transfer',
                 'fee': 'A string The transfer fee',
                 'fee_link': 'A string representing link to info about the fee',
                 'old_team': 'A team object representing the old team',
                 'new_team': 'A team object representing the new team',
                 'date': 'A datetime object representing the date of the transfer',
                 'embed': 'An embed representing the transfer'}

    def __init__(self,
                 player: Player = None,
                 link: str = None,
                 fee: str = None,
                 fee_link: str = None,
                 old_team: Team = None,
                 new_team: Team = None,
                 date: str = None,
                 ) -> None:

        if player is not None:
            self.player: Player = player

        if link is not None:
            self.link: str = link

        if fee is not None:
            self.fee: str = fee

        if fee_link is not None:
            self.fee_link: str = fee_link

        if old_team is not None:
            self.old_team: Team = old_team

        if new_team is not None:
            self.new_team: Team = new_team

        if date is not None:
            self.date: str = date

        # Typehint
        self.embed: Optional[Embed] = None

    @property
    def loan_fee(self) -> str:
        """Returns either Loan Information or the total fee of a player's transfer"""
        if "End" in self.fee:
            output = f"[End of Loan]({self.fee_link})"
        elif "loan" in self.fee:
            output = f"[Loan]({self.fee_link})"
        else:
            output = f"[{self.fee}]({self.fee_link})"

        if hasattr(self, 'date'):
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
        return f"{self.player} ({self.loan_fee})\nFrom: {self.old_team.markdown}\n"

    @property
    def outbound(self) -> str:
        """Get outbound text."""
        return f"{self.player} ({self.loan_fee})\nTo: {self.new_team.markdown}\n"

    def generate_embed(self) -> Embed:
        """An embed representing a transfermarkt player transfer."""
        e: Embed = Embed(description="", colour=0x1a3151)
        e.title = f"{self.player.flag} {self.player.name}"
        e.url = self.player.link

        if hasattr(self.player, 'age'):
            e.description += f"Age: {self.player.age}\n"
        if hasattr(self.player, 'position'):
            e.description += f"Position: {self.player.position}\n"

        try:
            old = self.old_team.markdown
            try:
                old += f"\n{self.old_team.flag} {self.old_team.league.markdown}"
            except AttributeError:
                pass
            e.add_field(name="From", value=old)
        except AttributeError:
            pass

        try:
            new = self.new_team.markdown
            try:
                new += f"\n{self.new_team.flag} {self.new_team.league.markdown}"
            except AttributeError:
                pass
            e.add_field(name="To", value=new)
        except AttributeError:
            pass

        e.add_field(name="Reported Fee", value=self.loan_fee, inline=False)

        picture = getattr(self.player, 'picture', None)
        if picture is not None and 'http' in picture:
            e.set_thumbnail(url=picture)

        self.embed = e
        return self.embed


class TeamView(View):
    """A View representing a Team on TransferMarkt"""
    bot: Bot

    def __init__(self, interaction: Interaction, team: Team) -> None:
        super().__init__()
        self.team: Team = team
        self.interaction: Interaction = interaction
        self.index: int = 0
        self.pages: List[Embed] = []

        if not hasattr(self.__class__, 'bot'):
            self.__class__.bot = interaction.client

    async def on_timeout(self) -> Message:
        """Clean up"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = "") -> Message:
        """Send the latest version of the view"""
        self.clear_items()
        add_page_buttons(self)

        for label, func, emoji in [("Transfers", self.push_transfers, '🔄'), ("Rumours", self.push_rumours, '🕵'),
                                   ("Trophies", self.push_trophies, '🏆'), ("Contracts", self.push_contracts, '📝')]:
            self.add_item(FuncButton(label=label, func=func, emoji=emoji))

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

        def parse(rows: List, out: bool = False) -> List[Transfer]:
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
                # player.picture = ''.join(i.xpath('./img[@class="bilderrahmen-fixed"]/@data-src'))
                player.position = ''.join(i.xpath('./td[2]//tr[2]/td/text()')).strip()

                # Block 3 - Age
                player.age = ''.join(i.xpath('./td[3]/text()')).strip()

                # Block 4 - Nationality
                player.country = [_.strip() for _ in i.xpath('./td[4]//img/@title') if _.strip()]

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
                team.country = [_.strip() for _ in i.xpath("./td[5]//img/@title") if _.strip()]

                new = team if out else self.team
                old = self.team if out else team

                # Block 6 - Fee or Loan
                fee = ''.join(i.xpath('.//td[6]//text()')).strip()
                fee_link = TF + ''.join(i.xpath('.//td[6]//@href')).strip()
                date = ''.join(i.xpath('.//i/text()'))

                transfer = Transfer(player=player, new_team=new, old_team=old, date=date, fee=fee, fee_link=fee_link)
                transfer.generate_embed()

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
        target = self.team.link.replace('startseite', 'geruechte')
        async with self.bot.session.get(target) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return await self.bot.error(self.interaction, f"Error {resp.status} connecting to {resp.url}")

        e.url = target
        e.title = f"Transfer rumours for {self.team.name}"
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

            pos = ''.join(i.xpath('.//td[2]//tr[2]/td/text()'))
            flag = get_flag(i.xpath('.//td[3]/img/@title')[0])
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
                    return await self.bot.error(self.interaction, f"Error {resp.status} connecting to {resp.url}")

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
            flag = " ".join([get_flag(f) for f in i.xpath('.//td[3]/img/@title')])
            date = ''.join(i.xpath('.//td[4]//text()')).strip()

            _ = datetime.datetime.strptime(date, "%b %d, %Y")
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
    name: str
    link: str

    capacity: int
    total: int
    average: int
    team: Team

    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

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
    bot: Bot

    def __init__(self, interaction: Interaction, comp: Competition) -> None:
        super().__init__()
        self.comp: Competition = comp
        self.interaction: Interaction = interaction
        self.index: int = 0
        self.pages: List[Embed] = []

        if not hasattr(self.__class__, 'bot'):
            self.__class__.bot = interaction.client

    async def on_timeout(self) -> Message:
        """Clean up"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify user of view is correct user."""
        return interaction.user.id == self.interaction.user.id

    async def update(self, content: str = "") -> Message:
        """Send the latest version of the view"""
        self.clear_items()
        add_page_buttons(self)

        for _ in [FuncButton(label="Attendances", func=self.attendance, emoji='🏟️')]:
            self.add_item(_)
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


class Agent(TransferResult):
    """An object representing an Agent from transfermarkt"""

    def __init__(self, name: str, link: str):
        super().__init__(name, link)


# Transfer View.
class CategorySelect(Select):
    """Dropdown to specify what user is searching for."""

    def __init__(self) -> None:
        super().__init__(placeholder="What are you trying to search for…?")

    async def callback(self, interaction: Interaction) -> Message:
        """Edit view on select."""
        await interaction.response.defer()
        self.view.category = self.values[0]
        self.view.remove_item(self)
        return await self.view.update()


class Home(Button):
    """Reset Search view to not have a category."""

    def __init__(self, row: int = 1) -> None:
        super().__init__(emoji="⬆", label="Back", row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """On Click Event"""
        await interaction.response.defer()
        self.view.category = None
        self.view.index = 1
        return await self.view.update()


class SearchSelect(Select):
    """Dropdown."""

    def __init__(self, objects: List) -> None:
        super().__init__(row=3, placeholder="Select correct option")
        self.objects: List[Team | Competition] = objects
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
    bot: Bot

    def __init__(self, interaction: Interaction, query: str, category: str = None, fetch: bool = False) -> None:
        super().__init__()

        self.index: int = 1
        self.value: Optional[Team | Competition] = None
        self.pages: List[Embed] = []

        self.query: str = query
        self.category: str = category
        self.fetch: bool = fetch
        self.interaction: Interaction = interaction

        if not hasattr(self.__class__, 'bot'):
            self.__class__.bot = interaction.client

    @staticmethod
    def parse_competitions(rows: List) -> List[Competition]:
        """Parse a transfermarkt page into a list of Competition Objects"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//td[2]/a/text()')).strip()
            link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[2]/a/@href')).strip()
            country = [_.strip() for _ in i.xpath('.//td[3]/img/@title') if _.strip()]

            comp = Competition(name=name, link=link, country=country)

            results.append(comp)
        return results

    @staticmethod
    def parse_players(rows: List) -> List[Player]:
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
        return results

    @staticmethod
    def parse_agents(rows: List) -> List[Agent]:
        """Parse a transfermarkt page into a list of Agent Objects"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//td[2]/a/text()'))
            link = ''.join(i.xpath('.//td[2]/a/@href'))
            if "https://www.transfermarkt.co.uk" not in link:
                link = "https://www.transfermarkt.co.uk" + link
            results.append(Agent(name=name, link=link))
        return results

    @staticmethod
    def parse_staff(rows: List) -> List[Staff]:
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
        return results

    @staticmethod
    def parse_teams(rows: List) -> List[Team]:
        """Fetch a list of teams from a transfermarkt page"""
        results = []
        for i in rows:
            name = ''.join(i.xpath('.//tm-tooltip[@data-type="club"]/a/@title')).strip()
            link = ''.join(i.xpath('.//tm-tooltip[@data-type="club"]/a/@href')).strip()

            # Fallbacks.
            if not name:
                name = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@title'))
            if not link:
                link = ''.join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link:
                link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link

            lg_name = ''.join(i.xpath('.//tr[2]/td/a/text()')).strip()
            lg_lnk = ''.join(i.xpath('.//tr[2]/td/a/@href')).strip()
            if lg_lnk and "transfermarkt" not in lg_lnk:
                lg_lnk = f"https://www.transfermarkt.co.uk{lg_lnk}"
            league = Competition(name=lg_name, link=lg_lnk)

            team = Team(name=name, link=link, league=league)
            team.country = [_.strip() for _ in i.xpath('.//td/img[1]/@title') if _.strip()]
            team.logo = ''.join(i.xpath('.//td[@class="suche-vereinswappen"]/img/@src'))

            results.append(team)
        return results

    @staticmethod
    def parse_referees(rows: List) -> List[Referee]:
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
        return results

    async def on_error(self, error, item, interaction) -> None:
        """Error handling & logging."""
        print("Error in SearchView\n", self.interaction.message.content, item, item.__dict__, interaction)
        raise error

    async def on_timeout(self) -> Message:
        """Cleanup."""
        self.clear_items()
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = "") -> Message:
        """Populate Initial Results"""
        self.clear_items()
        url = 'https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'

        # Header names, scrape then compare (because they don't follow a pattern.)
        if self.category is None:
            p = {"query": self.query}

            async with self.bot.session.post(url, params=p) as resp:
                match resp.status:
                    case 200:
                        tree = html.fromstring(await resp.text())
                    case _:
                        i = self.interaction
                        return await self.bot.error(i, f"HTTP {resp.status} Error connecting to transfermarkt.")

            categories = [i.lower().strip() for i in tree.xpath(".//div[@class='table-header']/text()")]

            sel = CategorySelect()
            ce: Embed = Embed(title="Multiple results found")
            ce.set_footer(text="Use the dropdown to select a category")
            desc = []
            for i in categories:
                # Just give number of matches (digit characters).
                try:
                    ln = int(''.join([n for n in i if n.isdecimal()]))
                except ValueError:
                    print("ValueError in transfer_tools", i)
                    ln = "?"

                s = "" if ln == 1 else "s"

                match i:
                    case i if 'for players' in i:
                        sel.add_option(emoji='🏃', label="Players", description=f"{ln} Results", value='player')
                        desc.append(f"Players: {ln} Result{s}\n")
                    case i if 'results: clubs' in i:
                        sel.add_option(emoji='👕', label="Clubs", description=f"{ln} Results", value='team')
                        desc.append(f"Clubs: {ln} Result{s}\n")
                    case i if 'for agents' in i:
                        sel.add_option(emoji='🏛️', label="Agents", description=f"{ln} Results", value='agent')
                        desc.append(f"Agents: {ln} Result{s}\n")
                    case i if 'for referees' in i:
                        sel.add_option(emoji='🤡', label="Referees", description=f"{ln} Results", value='referee')
                        desc.append(f"Referees: {ln} Result{s}\n")
                    case i if 'managers' in i:
                        sel.add_option(emoji='🏢', label="Managers", description=f"{ln} Results", value='staff')
                        desc.append(f"Managers: {ln} Result{s}\n")
                    case i if 'to competitions' in i:
                        val = 'competition'
                        sel.add_option(emoji='🏆', label='Competitions', description=f"{ln} Results", value=val)
                        desc.append(f"Competitions: {ln} Result{s}\n")

            ce.description = ''.join(desc)

            if not sel.options:
                return await self.bot.error(self.interaction, f'No results found for query {self.query}')

            elif len(sel.options) == 1:
                self.category = sel.options[0].value

            else:
                self.clear_items()
                self.add_item(sel)
                return await self.bot.reply(self.interaction, content=content, view=self, embed=ce)

        match self.category:
            case 'player':
                qs, ms, parser = "Spieler_page", 'for players', self.parse_players
            case 'team':
                qs, ms, parser = "Verein_page", 'results: Clubs', self.parse_teams
            case 'referee':
                qs, ms, parser = "Schiedsrichter_page", 'for referees', self.parse_referees
            case 'staff':
                qs, ms, parser = "Trainer_page", 'Managers', self.parse_staff
            case 'agent':
                qs, ms, parser = "page", 'for agents', self.parse_agents
            case 'competition':
                qs, ms, parser = "Wettbewerb_page", 'competitions', self.parse_competitions
            case _:
                print(f'WARNING NO QUERY STRING FOUND FOR {self.category}')
                qs, ms, parser = "page", "", None

        p = {"query": self.query, qs: self.index}

        async with self.bot.session.post(url, params=p) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return await self.bot.error(self.interaction, content="Error Connecting to Transfermarkt")

        # Get trs of table after matching header / {ms} name.
        trs = f".//div[@class='box']/div[@class='table-header'][contains(text(),'{ms}')]/following::div[1]//tbody/tr"
        _ = ''.join(tree.xpath(f".//div[@class='table-header'][contains(text(),'{ms}')]//text()"))

        try:
            matches = int(''.join([i for i in _ if i.isdecimal()]))
        except ValueError:
            matches = 0
            if _:
                print("ValueError in transfer_tools", _)

        e: Embed = Embed(title=f"{matches} {self.category.title().rstrip('s')} results for {self.query}")
        e.set_author(name="TransferMarkt Search", url=url, icon_url=FAVICON)

        results: List[TransferResult] = parser(tree.xpath(trs))
        if not results:
            self.index = 0
            return await self.bot.error(self.interaction, f"🚫 No results found for {self.category}: {self.query}")

        e = rows_to_embeds(e, [str(i) for i in results])[0]

        self.pages = [None] * max(matches // 10, 1)
        self.add_item(Home())
        add_page_buttons(self)

        if self.fetch and results:
            self.add_item(SearchSelect(objects=results))
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)
