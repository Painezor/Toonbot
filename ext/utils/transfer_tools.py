"""Utilties for working with transfers from transfermarkt"""
import datetime
import typing

import discord
import pycountry
from lxml import html

from ext.utils import embed_utils, view_utils, timed_events

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


def get_flag(country, unicode=False) -> str:
    """Get a flag emoji from a string representing a country"""
    try:
        country = country.strip().replace('Retired', '')
    except AttributeError:
        return country
    if not country:
        return country

    # Check if py country has country
    if country.lower() in ["england", "scotland", "wales"]:
        if unicode:
            country = country.lower()
            if country == "england":
                return '🏴󠁧󠁢󠁥󠁮󠁧󠁿'
            elif country == "scotland":
                return '🏴󠁧󠁢󠁳󠁣󠁴󠁿'
            elif country == "wales":
                return '🏴󠁧󠁢󠁷󠁬󠁳󠁿'
        else:
            country = f":{country.lower()}:"
        return country

    try:
        country = pycountry.countries.get(name=country.title()).alpha_2
    except (KeyError, AttributeError):
        try:
            # else revert to manual dict.
            country = country_dict[country]
        except KeyError:
            print(f'No flag found for country: {country}')

    country = country.lower()
    for key, value in UNI_DICT.items():
        country = country.replace(key, value)
    return country


class TransferResult:
    """The result of a transfermarket search"""
    def __init__(self, name, link, **kwargs):
        self.link = link
        self.name = name

    def __repr__(self):
        return f"TransferResult({self.__dict__})"

    @property
    async def base_embed(self) -> discord.Embed():
        """A generic embed used for transfermarkt objects"""
        e = discord.Embed()
        e.colour = discord.Colour.dark_blue()
        e.set_author(name="TransferMarkt")
        return e

    @property
    def flag(self) -> str:
        """Return a flag representing the country"""
        # Return earth emoji if does not have a country.
        if not hasattr(self, "country"):
            return "🌍"

        if isinstance(self.country, list):
            return "".join([get_flag(i) for i in self.country])
        else:
            return get_flag(self.country)


class Player(TransferResult):
    """An Object representing a player from transfermarkt"""
    def __init__(self, name, link, team, age, position, team_link, country, picture):
        super().__init__(name, link)
        self.team = team
        self.age = age
        self.position = position
        self.team_link = team_link
        self.country = country
        self.picture = picture

    def __repr__(self):
        return f"Player({self.__dict__})"

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link}) {self.age}, {self.position} [{self.team}]({self.team_link})"


def parse_players(rows) -> typing.List[Player]:
    """Parse a transfer page to get a list of players"""
    players = []
    for i in rows:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
        picture = "".join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))
        link = "".join(i.xpath('.//a[@class="spielprofil_tooltip"]/@href'))
        link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link
        team = "".join(i.xpath('.//td[3]/a/img/@alt'))
        team_link = "".join(i.xpath('.//td[3]/a/img/@href'))
        team_link = "https://www.transfermarkt.co.uk" + team_link if "transfermarkt" not in team_link else team_link
        age = "".join(i.xpath('.//td[4]/text()'))
        p = "".join(i.xpath('.//td[2]/text()'))
        c = "".join(i.xpath('.//td/img[1]/@title'))
        players.append(Player(name, link, team, age, p, team_link, c, picture))
    return players


class Staff(TransferResult):
    """An object representing a Trainer or Manager from a Transfermarkt search"""

    def __init__(self, name, link, country, team, team_link, age, job):
        super().__init__(name, link)
        self.team = team
        self.team_link = team_link
        self.age = age
        self.job = job
        self.country = country

    def __repr__(self):
        return f"Manager({self.__dict__})"

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link}) {self.age}, {self.job} [{self.team}]({self.link})"


def parse_staff(rows) -> typing.List[Staff]:
    """Parse a list of staff"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()'))
        link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))
        link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link

        team = "".join(i.xpath('.//td[2]/a/img/@alt'))
        tl = "".join(i.xpath('.//td[2]/a/img/@href'))
        tl = "https://www.transfermarkt.co.uk" + tl if "transfermarkt" not in tl else tl
        age = "".join(i.xpath('.//td[3]/text()'))
        job = "".join(i.xpath('.//td[5]/text()'))
        country = "".join(i.xpath('.//td/img[1]/@title'))

        results.append(Staff(name=name, link=link, team=team, team_link=tl, age=age, job=job, country=country))
    return results


class Transfer(TransferResult):
    """An Object representing a transfer from transfermarkt"""

    def __init__(self, player: Player, old_team, new_team, fee, fee_link, date=None):
        self.fee = fee
        self.fee_link = fee_link
        self.old_team = old_team
        self.new_team = new_team
        self.player = player
        self.date = date
        super().__init__(player.name, player.link)

    @property
    def loan_or_fee(self):
        """Returns either Loan Information or the total fee of a player's transfer"""
        if "End" in self.fee:
            fee = "End of Loan"
        elif "loan" in self.fee:
            fee = "Loan"
        else:
            fee = self.fee

        d = f": {self.date}" if self.date else ""

        return f"[{fee}]({self.fee_link}){d}"

    def __str__(self):
        return f"{self.player.flag} [{self.name}]({self.link}) {self.player.age}, " \
               f"{self.player.position} ({self.loan_or_fee})"

    @property
    def movement(self):
        """Moving from Team A to Team B"""
        return f"{self.old_team.markdown} ➡ {self.new_team.markdown}"

    @property
    def embed(self):
        """An embed representing a transfermarkt player transfer."""
        e = discord.Embed()
        e.description = ""
        e.colour = 0x1a3151
        e.title = f"{self.player.flag} {self.name} | {self.player.age}"
        e.url = self.player.link
        e.description = self.player.position
        e.description += f"\n**To**: {self.new_team.markdown}"
        if self.new_team.name != "Without Club":
            e.description += f" ({self.new_team.flag} {self.new_team.league_markdown})"
        e.description += f"\n**From**: {self.old_team.markdown}"
        if self.old_team.name != "Without Club":
            e.description += f" ({self.old_team.flag} {self.old_team.league_markdown})"
        e.add_field(name="Reported Fee", value=self.loan_or_fee, inline=False)
        if "http" in self.player.picture:
            e.set_thumbnail(url=self.player.picture)
        return e


class Team(TransferResult):
    """An object representing a Team from Transfermarkt"""
    def __init__(self, name, link, country, league, league_link):
        self.league = league
        self.league_link = league_link
        self.country = country
        super().__init__(name, link)

    @property
    def markdown(self):
        """Return markdown formatted team name and link"""
        return f"[{self.name}]({self.link})"

    @property
    def league_markdown(self):
        """Return markdown formatted league name and link"""
        if self.name == "Without Club":
            return ""
        return f"[{self.league}]({self.league_link})"

    @property
    def badge(self):
        """Return a link to the team's badge"""
        number = self.link.split('/')[-1]
        return f"https://tmssl.akamaized.net/images/wappen/head/{number}.png"

    @property
    async def base_embed(self):
        """Return a discord embed object representing a team"""
        e = await super().base_embed
        e.set_thumbnail(url=self.badge)
        e.title = self.name
        e.url = self.link
        return e

    def __str__(self):
        if self.league:
            club = f"[{self.name}]({self.link}) ([{self.league}]({self.league_link}))"
        else:
            club = f"[{self.name}]({self.link})"

        output = f"{self.flag} {club}"
        return output

    async def get_contracts(self, ctx):
        """Get a list of expiring contracts for a team."""
        e = await self.base_embed
        e.description = ""
        target = self.link
        target = target.replace('startseite', 'vertragsende')

        async with ctx.bot.session.get(f"{target}") as resp:
            if resp.status != 200:
                return await ctx.bot.reply(ctx, text=f"Error {resp.status} connecting to {resp.url}")
            tree = html.fromstring(await resp.text())
            e.url = str(resp.url)

        e.title = f"Expiring contracts for {e.title}"
        e.set_author(name="Transfermarkt", url=str(resp.url))
        e.set_footer(text=discord.Embed.Empty)

        rows = []

        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
            if not name:
                continue

            link = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/@href'))
            link = f"https://www.transfermarkt.co.uk{link}"

            pos = "".join(i.xpath('.//td[1]//tr[2]/td/text()'))
            age = "".join(i.xpath('./td[2]/text()')).split('(')[-1].replace(')', '').strip()
            flag = " ".join([get_flag(f) for f in i.xpath('.//td[3]/img/@title')])
            date = "".join(i.xpath('.//td[4]//text()')).strip()
            _ = datetime.datetime.strptime(date, "%b %d, %Y")
            expiry = timed_events.Timestamp(_).countdown

            option = "".join(i.xpath('.//td[5]//text()')).strip()
            option = f"\n∟ {option.title()}" if option != "-" else ""

            rows.append(f"{flag} [{name}]({link}) {age}, {pos} ({expiry}){option}")

        rows = ["No expiring contracts found."] if not rows else rows

        view = view_utils.Paginator(ctx.author, embed_utils.rows_to_embeds(e, rows))
        view.message = await ctx.bot.reply(ctx, f"Fetching contracts for {self.name}", view=view)
        await view.update()


def parse_teams(rows):
    """Fetch a list of teams from a transfermarkt page"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
        _ = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
        link = "https://www.transfermarkt.co.uk" + _ if "transfermarkt" not in _ else _
        league = "".join(i.xpath('.//tr[2]/td/a/text()')).strip()
        _ = "".join(i.xpath('.//tr[2]/td/a/@href')).strip()
        league_link = "https://www.transfermarkt.co.uk" + _ if "transfermarkt" not in _ else _
        country = "".join(i.xpath('.//td/img[1]/@title')[-1]).strip()
        results.append(Team(name=name, link=link, country=country, league=league, league_link=league_link))
    return results


class Referee(TransferResult):
    """An object representing a referee from transfermarkt"""

    def __init__(self, name, link, country, age):
        self.age = age
        self.country = country
        super().__init__(name, link)

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link}) {self.age}"


def parse_referees(rows) -> typing.List[Referee]:
    """Parse a transfer page to get a list of referees"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
        age = "".join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
        country = "".join(i.xpath('.//td/img[1]/@title')).strip()
        results.append(Referee(name=name, link=link, age=age, country=country))
    return results


class Competition(TransferResult):
    """An Object representing a competition from transfermarkt"""

    def __init__(self, name, link, country):
        self.country = country
        super().__init__(name, link)

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link})"


def parse_competitions(rows) -> typing.List[Competition]:
    """Parse a transfermarkt page into a list of Competition Objects"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[2]/a/text()')).strip()
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href')).strip()
        country = "".join(i.xpath('.//td[3]/img/@title')).strip()
        results.append(Competition(name=name, link=link, country=country))
    return results


class Agent(TransferResult):
    """An object representing an Agent from transfermarkt"""

    def __init__(self, name, link):
        super().__init__(name, link)

    def __str__(self):
        return f"[{self.name}]({self.link})"


def parse_agents(rows) -> typing.List[Agent]:
    """Parse a transfermarkt page into a list of Agent Objects"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[2]/a/text()'))
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href'))
        results.append(Agent(name=name, link=link))
    return results


# Transfer View.
class CategorySelect(discord.ui.Select):
    """Dropdown to specify what user is searching for."""

    def __init__(self):
        super().__init__(placeholder="What are you trying to search for...?")

    async def callback(self, interaction: discord.Interaction):
        """Edit view on select."""
        await interaction.response.defer()
        self.view.category = self.values[0]
        self.view.remove_item(self)
        await self.view.update()


class PageButton(discord.ui.Button):
    """Button to spawn a dropdown to select pages."""

    def __init__(self, row=0):
        super().__init__()
        self.label = f"Populating..."
        self.emoji = "⏬"
        self.row = row
        self.style = discord.ButtonStyle.primary

    async def callback(self, interaction: discord.Interaction):
        """The pages button."""
        await interaction.response.defer()
        if len(self.view.pages) < 25:
            sliced = self.view.pages
        else:
            if self.view.index < 13:
                sliced = list(range(1, 25))
            elif self.view.index > len(self.view.pages) - 13:
                sliced = list(range(self.view.index - 24, self.view.index))
            else:
                sliced = list(range(self.view.index - 12, self.view.index + 12))
        options = [discord.SelectOption(label=f"Page {n}", value=str(n)) for n in sliced]
        self.view.add_item(view_utils.PageSelect(placeholder="Select A Page", options=options, row=self.row + 1))
        self.disabled = True
        await self.view.message.edit(view=self.view)


class HomeButton(discord.ui.Button):
    """Reset Search view to not have a category."""

    def __init__(self):
        super().__init__(emoji="⬆", label="Back")

    async def callback(self, interaction: discord.Interaction):
        """On Click Event"""
        await interaction.response.defer()
        self.view.category = None
        self.view.index = 1
        await self.view.update()


class SearchSelect(discord.ui.Select):
    """Dropdown."""

    def __init__(self, objects: typing.List):
        super().__init__(row=3, placeholder="Select correct option")
        self.objects = objects
        for num, _ in enumerate(objects):

            if isinstance(_, Team):
                self.add_option(label=_.name, description=f"{_.country}: {_.league}", value=str(num), emoji='👕')
            elif isinstance(_, Competition):
                self.add_option(label=_.name, description=_.country, value=str(num), emoji='🏆')

    async def callback(self, interaction: discord.Interaction):
        """Set view value to item."""
        await interaction.response.defer()
        self.view.value = self.objects[int(self.values[0])]
        self.view.stop()


class SearchView(discord.ui.View):
    """A TransferMarkt Search in View Form"""

    def __init__(self, ctx, query, category=None, fetch=False):
        super().__init__()
        self.index = 1
        self.value = None
        self.pages = []

        self.query = query
        self.category = category
        self.fetch = fetch
        self.ctx = ctx
        self.message = None

        self.url = None

    @property
    def settings(self):
        """Parser Settings"""
        if self.category == "Players":
            return "Spieler_page", 'for players', parse_players
        elif self.category == "Clubs":
            return "Verein_page", 'results: Clubs', parse_teams
        elif self.category == "Referees":
            return "Schiedsrichter_page", 'for referees', parse_referees
        elif self.category == "Managers":
            return "Trainer_page", 'Managers', parse_staff
        elif self.category == "Agents":
            return "page", 'for agents', parse_agents
        elif self.category == "Competitions":
            return "Wettbewerb_page", 'competitions', parse_competitions
        else:
            print(f'WARNING NO QUERY STRING FOUND FOR {self.category}')
            return "page"

    async def on_error(self, error, item, interaction):
        """Error handling & logging."""
        print("Error in transfer_tools.SearchView")
        print(self.ctx.message.content)
        print(item)
        print(interaction)
        raise error

    async def on_timeout(self):
        """Cleanup."""
        self.clear_items()
        try:
            await self.message.edit(content="", embed=self.message.embed, view=self)
        except AttributeError:
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass

    async def update(self):
        """Populate Initial Results"""
        self.clear_items()
        url = 'https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'

        # Header names, scrape then compare (because they don't follow a pattern.)
        if self.category is None:
            p = {"query": self.query}

            async with self.ctx.bot.session.post(url, params=p) as resp:
                assert resp.status == 200, "Error Connecting to Transfermarkt"
                self.url = str(resp.url)
                tree = html.fromstring(await resp.text())

            categories = [i.lower().strip() for i in tree.xpath(".//div[@class='table-header']/text()")]

            select = CategorySelect()
            ce = discord.Embed(title="Multiple results found", description="")
            ce.set_footer(text="Use the dropdown to select a category")
            for i in categories:
                # Just give number of matches (digit characters).
                length = int("".join([n for n in i if n.isdecimal()]))
                s = "" if length == 1 else "s"
                if 'for players' in i:
                    select.add_option(emoji='🏃', label="Players", description=f"{length} Results", value="Players")
                    ce.description += f"Players: {length} Result{s}\n"
                elif 'results: clubs' in i:
                    select.add_option(emoji='👕', label="Clubs", description=f"{length} Results", value="Clubs")
                    ce.description += f"Clubs: {length} Result{s}\n"
                elif 'for agents' in i:
                    select.add_option(emoji='🏛️', label="Agents", description=f"{length} Results", value="Agents")
                    ce.description += f"Agents: {length} Result{s}\n"
                elif 'for referees' in i:
                    select.add_option(emoji='🤡', label="Referees", description=f"{length} Results", value="Referees")
                    ce.description += f"Referees: {length} Result{s}\n"
                elif 'managers' in i:
                    select.add_option(emoji='🏢', label="Managers", description=f"{length} Results", value="Managers")
                    ce.description += f"Managers: {length} Result{s}\n"
                elif 'to competitions' in i:
                    _ = "Competitions"
                    select.add_option(emoji='🏆', label=_, description=f"{length} Results", value=_)
                    ce.description += f"Competitions: {length} Result{s}\n"

            if not select.options:
                return await self.message.edit(content=f'No results found for query {self.query}')

            elif len(select.options) == 1:
                self.category = select.options[0].label

            else:
                self.clear_items()
                self.add_item(select)
                am = discord.AllowedMentions.none()
                await self.message.edit("", view=self, embed=ce, allowed_mentions=am)
                return await self.wait()

        qs, ms, parser = self.settings
        p = {"query": self.query, qs: self.index}

        async with self.ctx.bot.session.post(url, params=p) as resp:
            assert resp.status == 200, "Error Connecting to Transfermarkt"
            self.url = str(resp.url)
            tree = html.fromstring(await resp.text())

        # Get trs of table after matching header / {ms} name.
        trs = f".//div[@class='box']/div[@class='table-header'][contains(text(),'{ms}')]/following::div[1]//tbody/tr"

        _ = "".join(tree.xpath(f".//div[@class='table-header'][contains(text(),'{ms}')]//text()"))
        matches = "".join([i for i in _ if i.isdecimal()])

        e = discord.Embed(title=f"{matches} {self.category.title().rstrip('s')} results for {self.query}")
        e.set_author(name="TransferMarkt Search", url=self.url, icon_url=FAVICON)
        results = parser(tree.xpath(trs))
        rows = [f"🚫 No results found for {self.category}: {self.query}"] if not matches else [str(i) for i in results]
        e = embed_utils.rows_to_embeds(e, rows)[0]

        self.pages = [None] * max(len(rows) // 10, 1)
        self.add_item(HomeButton())

        if len(self.pages) > 1:
            _ = view_utils.PreviousButton()
            _.disabled = True if self.index == 1 else False
            self.add_item(_)

            _ = PageButton()
            _.label = f"Page {self.index} of {len(self.pages)}"
            self.add_item(_)

            _ = view_utils.NextButton()
            _.disabled = True if self.index == len(self.pages) else False
            self.add_item(_)

        self.add_item(view_utils.StopButton(row=0))

        if self.fetch and results:
            _ = SearchSelect(objects=results)
            self.add_item(_)

        await self.message.edit(content="", embed=e, view=self, allowed_mentions=discord.AllowedMentions.none())
        await self.wait()
