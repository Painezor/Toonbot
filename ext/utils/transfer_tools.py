"""Utiltiies for working with transfers from transfermarkt"""
import asyncio
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
    "Russia": "ru",
    "Sao Tome and Principe": "st",
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
    "Sao Tome and Princip": "st",
    "USA": "us",
    "Venezuela": "ve",
    "Vietnam": "vn"}

unidict = {
    "a": "🇦", "b": "🇧", "c": "🇨", "d": "🇩", "e": "🇪",
    "f": "🇫", "g": "🇬", "h": "🇭", "i": "🇮", "j": "🇯",
    "k": "🇰", "l": "🇱", "m": "🇲", "n": "🇳", "o": "🇴",
    "p": "🇵", "q": "🇶", "r": "🇷", "s": "🇸", "t": "🇹",
    "u": "🇺", "v": "🇻", "w": "🇼", "x": "🇽", "y": "🇾", "z": "🇿"
}


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
    for key, value in unidict.items():
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


class Transfer(TransferResult):
    """An Object representing a transfer from transfermarkt"""
    def __init__(self, player: Player, old_team, new_team, fee, fee_link):
        self.fee = fee
        self.fee_link = fee_link
        self.old_team = old_team
        self.new_team = new_team
        self.player = player
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
        return f"[{fee}]({self.fee_link})"

    def __str__(self):
        return f"{self.player.flag} [{self.name}]({self.link}) {self.player.age}, " \
               f"{self.player.position} ({self.loan_or_fee})"

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
        if self.name == "Without Club":
            return self.name
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

    async def get_trophies(self, ctx):
        """Fetch a list of a team's trophies"""
        url = self.link.replace('startseite', 'erfolge')

        async with ctx.bot.session.get(url) as resp:
            if resp.status != 200:
                await ctx.bot.reply(ctx, text=f"Error {resp.status} connecting to {resp.url}")
                return None
            tree = html.fromstring(await resp.text())

        rows = tree.xpath('.//div[@class="box"][./div[@class="header"]]')
        results = []
        for i in rows:
            title = "".join(i.xpath('.//h2/text()'))
            dates = "".join(i.xpath('.//div[@class="erfolg_infotext_box"]/text()'))
            dates = " ".join(dates.split()).replace(' ,', ',')
            results.append(f"**{title}**\n{dates}\n")

        self.link = url
        return results

    async def get_transfers(self, ctx):
        """Fetch the latest transfers for a team"""
        url = self.link.replace('startseite', 'transfers')

        # Winter window, Summer window.
        now = datetime.datetime.now()
        period, season_id = ("w", now.year - 1) if now.month < 7 else ("s", now.year)
        url = f"{url}/saison_id/{season_id}/pos//detailpos/0/w_s/plus/1"

        p = {"w_s": period}
        async with ctx.bot.session.get(url, params=p) as resp:
            if resp.status != 200:
                await ctx.bot.reply(ctx, text=f"Error {resp.status} connecting to {resp.url}")
                return None
            tree = html.fromstring(await resp.text())

        p_in = tree.xpath('.//div[@class="box"][.//h2/a[text() = "Arrivals"]]/div[@class="responsive-table"]')
        p_out = tree.xpath('.//div[@class="box"][.//h2/a[text() = "Departures"]]/div[@class="responsive-table"]')

        players_in = p_in[0].xpath('.//tbody/tr') if p_in else []
        players_out = p_out[0].xpath('.//tbody/tr') if p_out else []

        def parse(table) -> typing.List[Transfer]:
            """Read through the transfers page and extract relevant data, returning a list of transfers"""
            transfers = []
            for i in table:
                name = "".join(i.xpath('.//a[@class="spielprofil_tooltip"]/text()')).strip()
                link = f"https://www.transfermarkt.co.uk" + "".join(i.xpath('.//a[@class="spielprofil_tooltip"]/@href'))

                link = link.strip()
                age = "".join(i.xpath('.//td[3]/text()')).strip()
                position = "".join(i.xpath('.//td[2]//tr[2]/td/text()')).strip()
                picture = "".join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))

                team = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="vereinprofil_tooltip"]/text()')).strip()

                team_link = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="vereinprofil_tooltip"]/@href')).strip()
                team_country = "".join(i.xpath(".//td[5]//img/@title")).strip()
                league = "".join(i.xpath(".//td[5]//tr[2]//a/text()")).strip()
                league_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath(".//td[5]//tr[2]//a/@href")).strip()
                country = "".join(i.xpath('.//td[4]/img[1]/@title')).strip()

                player = Player(name, link, self.name, age, position, self.link, country, picture)
                other_team = Team(team, team_link, team_country, league, league_link)
                this_team = Team(self.name, self.link, self.country, self.league, self.league_link)
                fee = "".join(i.xpath('.//td[7]//text()')).strip()
                fee_link = f"https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[7]//@href')).strip()

                transfer = Transfer(player, other_team, this_team, fee, fee_link)
                transfers.append(transfer)
            return transfers

        players_in = parse(players_in)
        players_out = parse(players_out)

        return players_in, players_out, url

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

    async def get_rumours(self, ctx):
        """Fetch a list of transfer rumours for a team."""
        e = await self.base_embed
        e.description = ""
        target = self.link
        target = target.replace('startseite', 'geruechte')
        async with ctx.bot.session.get(f"{target}") as resp:
            if resp.status != 200:
                return await ctx.bot.reply(ctx, text=f"Error {resp.status} connecting to {resp.url}")
            tree = html.fromstring(await resp.text())
            e.url = str(resp.url)

        e.title = f"Transfer rumours for {e.title}"
        e.set_author(name="Transfermarkt", url=str(resp.url))
        e.set_footer(text=discord.Embed.Empty)

        rows = []
        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
            if not name:
                continue

            link = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/@href'))
            link = f"https://www.transfermarkt.co.uk{link}"
            ppos = "".join(i.xpath('.//td[2]//tr[2]/td/text()'))
            flag = get_flag(i.xpath('.//td[3]/img/@title')[0])
            age = "".join(i.xpath('./td[4]/text()')).strip()
            team = "".join(i.xpath('.//td[5]//img/@alt'))
            team_link = "".join(i.xpath('.//td[5]//img/@href'))
            if "transfermarkt" not in team_link:
                team_link = "http://www.transfermarkt.com" + team_link
            source = "".join(i.xpath('.//td[8]//a/@href'))
            src = f"[Info]({source})"
            rows.append(f"{flag} **[{name}]({link})** ({src})\n{age}, {ppos} [{team}]({team_link})\n")

        rows = ["No rumours about new signings found."] if not rows else rows

        view = view_utils.Paginator(ctx.author, embed_utils.rows_to_embeds(e, rows))
        view.message = await ctx.bot.reply(ctx, f"Fetching rumours for {self.name}", view=view)
        await view.update()


def parse_teams(rows):
    """Fetch a list of teams from a transfermarkt page"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
        link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
        link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link
        league = "".join(i.xpath('.//tr[2]/td/a/text()')).strip()
        league_link = "".join(i.xpath('.//tr[2]/td/a/@href')).strip()
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


class Competition(TransferResult):
    """An Object representing a competition from transfermarkt"""
    def __init__(self, name, link, country):
        self.country = country
        super().__init__(name, link)

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link})"


class Agent(TransferResult):
    """An object representing an Agent from transfermarkt"""
    def __init__(self, name, link):
        super().__init__(name, link)

    def __str__(self):
        return f"[{self.name}]({self.link})"


class TransferSearch:
    """An instance of a Transfermarkt Search"""

    def __init__(self, returns_object=False):
        # Input or calculated
        self.category = None
        self.query = None

        # Calculated
        self.results = None
        self.page = 1
        self.url = None
        self.total_pages = None

        # Embed
        self.message = None
        self.header = None

        self.returns_object = returns_object

    @classmethod
    async def search(cls, ctx, query, returns_object=False, category=None):
        """Factory Method for Async creation"""
        self = TransferSearch(returns_object=returns_object)
        self.category = category
        self.query = query
        item = await self.perform_search(ctx)
        return item

    @property
    def react_list(self):
        """A list of reactions to add to the paginator"""
        reacts = []
        if self.total_pages > 2:
            reacts.append("⏮")  # first
        if self.total_pages > 1:
            reacts.append("◀")  # prev
            reacts.append("▶")  # next
        if self.total_pages > 2:
            reacts.append("⏭")  # last
        reacts.append("🚫")  # eject

        return reacts

    @property
    def query_string(self):
        """Get the German url thingy."""
        if self.category == "Players":
            return "Spieler_page"
        elif self.category == "Clubs":
            return "Verein_page"
        elif self.category == "Referees":
            return "Schiedsrichter_page"
        elif self.category == "Staff":
            return "Trainer_page"
        elif self.category == "Agents":
            return "page"
        elif self.category == "Domestic Competitions":
            return "Wettbewerb_page"
        elif self.category == "International Competitions":
            return "Wettbewerb_page"
        else:
            print(f'WARNING NO QUERY STRING FOUND FOR {self.category}')
            return "page"

    @property
    def match_string(self):
        """Get the header text to look for search results under."""
        if self.category == "Players":
            return 'for players'
        elif self.category == "Clubs":
            return 'results: Clubs'
        elif self.category == "Referees":
            return 'for referees'
        elif self.category == "Staff":
            return 'managers & officials'
        elif self.category == "Agents":
            return 'for agents'
        elif self.category == "Domestic Competitions":
            return 'to competitions'
        elif self.category == "International Competitions":
            return 'for international competitions'
        else:
            print(f'WARNING NO MATCH STRING FOUND FOR {self.category}')
            return "page"

    async def perform_search(self, ctx):
        """Perform the initial Search and populate values"""
        p = {"query": self.query}  # html encode.
        url = "http://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche"
        async with ctx.bot.session.post(url, params=p) as resp:
            if resp.status != 200:
                await ctx.bot.reply(ctx, text=f"HTTP Error connecting to transfermarkt: {resp.status}")
                return None
            tree = html.fromstring(await resp.text())

        # Header names, scrape then compare (because they don't follow a pattern.)
        if self.category is None:
            categories = [i.lower().strip() for i in tree.xpath(".//div[@class='table-header']/text()")]

            selectors = []
            mode = ""

            for i in categories:
                length = "".join([n for n in i if n.isdecimal()])  # Just give number of matches (non-digit characters).

                mode = "Players" if 'for players' in i else mode
                mode = "Clubs" if 'results: clubs' in i else mode
                mode = "Agents" if 'for agents' in i else mode
                mode = "Referees" if 'for referees' in i else mode
                mode = "Staff" if 'managers & officials' in i else mode
                mode = "Domestic Competitions" if 'to competitions' in i else mode
                mode = "International Competitions" if 'for international competitions' in i else mode

                selectors.append((mode, int(length)))

            picker_rows = [f"{x}: {y} Results" for x, y in selectors]
            index = await embed_utils.page_selector(ctx, picker_rows)

            if index is None:
                return

            if index == -1:
                await ctx.bot.reply(ctx, text=f'🚫 No results found for your search "{self.query}" in any category.')
                return

            self.category = selectors[index][0]

        await self.fetch_page(ctx)

        if not self.results:
            return
        if self.page == 1 and len(self.results) == 1:  # Return single results.
            if self.returns_object:
                return self.results[0]

        self.message = await ctx.bot.reply(ctx, embed=self.embed)

        try:
            await embed_utils.bulk_react(ctx, self.message, self.react_list)
        except discord.Forbidden:
            await ctx.bot.reply(ctx, text='No add_reactions permission, showing first page only.', ping=True)

        def page_check(emo, usr):
            """Verify reactions are from user who invoked the command."""
            if emo.message.id == self.message.id and usr.id == ctx.author.id:
                ej = str(emo.emoji)
                if ej.startswith(tuple(self.react_list)):
                    return True

        def reply_check(msg):
            """Verify message responses are from user who invoked the command."""
            if ctx.message.author.id == msg.author.id:
                try:
                    return int(msg.content) < len(self.results)
                except ValueError:
                    return False

        while True:
            received, dead = await asyncio.wait(
                [ctx.bot.wait_for('message', check=reply_check), ctx.bot.wait_for('reaction_add', check=page_check)],
                timeout=30, return_when=asyncio.FIRST_COMPLETED)

            if not received:
                try:
                    await self.message.clear_reactions()
                    await self.message.delete()
                except discord.HTTPException:
                    pass
                return

            res = received.pop().result()
            for i in dead:
                i.cancel()

            if isinstance(res, discord.Message):
                # It's a message.
                try:
                    await self.message.delete()
                    await res.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
                finally:
                    return self.results[int(res.content)]
            else:
                # it's a reaction.
                reaction, user = res
                if reaction.emoji == "⏮":  # first
                    self.page = 1
                elif reaction.emoji == "◀":  # prev
                    self.page -= 1 if self.page > 1 else self.page
                elif reaction.emoji == "▶":  # next
                    self.page += 1 if self.page < self.total_pages else self.page
                elif reaction.emoji == "⏭":  # last
                    self.page = self.total_pages
                elif reaction.emoji == "🚫":  # eject
                    try:
                        await self.message.delete()
                    except discord.NotFound:
                        pass
                    return None

                await self.fetch_page(ctx)
            await self.message.edit(embed=self.embed, allowed_mentions=discord.AllowedMentions().none())

    @property
    def embed(self):
        """Create an embed for asking users to choose between TransferMarkt results."""
        e = discord.Embed()
        e.colour = 0x1a3151
        e.url = self.url
        e.title = "Transfermarkt Search"
        e.set_footer(text=f"Page {self.page} of {self.total_pages}")

        if self.returns_object:
            e.description = "Please type matching ID#\n\n"
            if not self.results:
                return None

            for i, j in enumerate(self.results):
                e.description += f"`[{i}]`: {j}\n"
        else:
            e.description = self.header + "\n\n" + "\n".join([str(i) for i in self.results])
        return e

    async def fetch_page(self, ctx):
        """Fetch and parse a page from transfermarkt"""
        p = {"query": self.query, self.query_string: self.page}
        url = 'https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'
        async with ctx.bot.session.post(url, params=p) as resp:
            assert resp.status == 200, "Error Connecting to Transfermarkt"
            self.url = str(resp.url)
            tree = html.fromstring(await resp.text())

        # Get trs of table after matching header / {categ} name.
        match = self.match_string
        trs = f".//div[@class='box']/div[@class='table-header'][contains(text(),'{match}')]/following::div[1]//tbody/tr"
        matches = "".join(tree.xpath(f".//div[@class='table-header'][contains(text(),'{match}')]/text()"))
        matches = "".join([i for i in matches if i.isdecimal()])

        if not matches:
            await ctx.bot.reply(ctx,
                                f'🚫 No results found for your search "{self.query}" in category "{self.category}"')
            return None

        self.header = f"{self.category.title()}: {matches} results for '{self.query.title()}' found"

        try:
            self.total_pages = int(matches) // 10 + 1
        except ValueError:
            self.total_pages = 0

        rows = tree.xpath(trs)

        results = []

        if self.category == "Players":
            results = parse_players(rows)
        elif self.category == "Clubs":
            results = parse_teams(rows)
        elif self.category == "Referees":
            for i in rows:
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
                link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
                age = "".join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
                country = "".join(i.xpath('.//td/img[1]/@title')).strip()
                results.append(Referee(name=name, link=link, age=age, country=country))
        elif self.category == "Staff":
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
        elif self.category == "Domestic Competitions":
            for i in rows:
                name = "".join(i.xpath('.//td[2]/a/text()')).strip()
                link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href')).strip()
                country = "".join(i.xpath('.//td[3]/img/@title')).strip()
                results.append(Competition(name=name, link=link, country=country))
        elif self.category == "International Competitions":
            for i in rows:
                name = "".join(i.xpath('.//td[2]/a/text()'))
                link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href'))
                country = ""
                results.append(Competition(name=name, link=link, country=country))
        elif self.category == "Agents":
            for i in rows:
                name = "".join(i.xpath('.//td[2]/a/text()'))
                link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href'))
                results.append(Agent(name=name, link=link))
        else:
            print(f"Transfer Tools WARNING! NO VALID PARSER FOUND FOR CATEGORY: {self.category}")

        self.results = results
