"""Utilities for working with transfers from transfermarkt"""
import datetime
import typing
from copy import deepcopy

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
TF = "https://www.transfermarkt.co.uk"


def get_flag(country, unicode=False) -> str:
    """Get a flag emoji from a string representing a country"""
    if not country:
        return ""

    country = country.strip().replace('Retired', '').replace('Without Club', '')

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

    def try_country(ct):
        """Try to get the country."""
        try:
            ct = pycountry.countries.get(name=ct.title()).alpha_2
        except (KeyError, AttributeError):
            ct = country_dict[ct]
        return ct

    try:
        country = try_country(country)
    except KeyError:
        country = country.split(" ")[0]
        try:
            if country.strip() != "":
                country = try_country(country)
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
    def __init__(self, name, link):
        super().__init__(name, link)
        self.team = ""
        self.age = ""
        self.position = ""
        self.team_link = ""
        self.country = ""
        self.picture = ""

    def __repr__(self):
        return f"Player({self.__dict__})"

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link}) {self.age}, {self.position} [{self.team}]({self.team_link})"


def parse_players(rows) -> typing.List[Player]:
    """Parse a transfer page to get a list of players"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title'))
        if not name:
            name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()'))

        link = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@href'))
        if not link:
            link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

        if link and "transfermarkt" not in link:
            link = f"https://www.transfermarkt.co.uk{link}"

        player = Player(name, link)
        player.picture = "".join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))

        try:
            player.team = i.xpath('.//tm-tooltip[@data-type="club"]/a/@title')[0]
            tl = i.xpath('.//tm-tooltip[@data-type="club"]/a/@href')[0]
            if tl and "transfermarkt" not in tl:
                tl = f"https://www.transfermarkt.co.uk{tl}"
            player.team_link = tl
        except IndexError:
            pass

        player.age = "".join(i.xpath('.//td[4]/text()'))
        player.position = "".join(i.xpath('.//td[2]/text()'))
        player.country = i.xpath('.//td/img[1]/@title')
        results.append(player)
    return results


class Staff(TransferResult):
    """An object representing a Trainer or Manager from a Transfermarkt search"""

    def __init__(self, name, link):
        super().__init__(name, link)
        self.team = ""
        self.team_link = ""
        self.age = ""
        self.job = ""
        self.country = ""
        self.picture = ""

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

        staff = Staff(name, link)
        staff.picture = "".join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))

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

        staff.age = "".join(i.xpath('.//td[3]/text()'))
        staff.job = "".join(i.xpath('.//td[5]/text()'))
        staff.country = i.xpath('.//img[@class="flaggenrahmen"]/@title')
        results.append(staff)
    return results


class Transfer(TransferResult):
    """An Object representing a transfer from transfermarkt"""

    def __init__(self, player: Player):
        self.player = player
        self.fee = ""
        self.fee_link = ""
        self.old_team = None
        self.new_team = None
        self.date = ""
        super().__init__(player.name, player.link)

    @property
    def loan_fee(self):
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
        _ = f"{self.player.flag} [{self.name}]({self.link}) {self.player.age}, {self.player.position} ({self.loan_fee})"
        return _

    @property
    def movement(self):
        """Moving from Team A to Team B"""
        return f"{self.old_team.markdown} ➡ {self.new_team.markdown}"

    @property
    def inbound(self):
        """Get inbound text."""
        _ = f"{self.player.flag} [{self.name}]({self.link}) {self.player.age}, {self.player.position} ({self.loan_fee})"
        return f"{_}\nFrom: {self.old_team}\n"

    @property
    def outbound(self):
        """Get outbound text."""
        _ = f"{self.player.flag} [{self.name}]({self.link}) {self.player.age}, {self.player.position} ({self.loan_fee})"
        return f"{_}\nTo: {self.new_team}\n"

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
        e.add_field(name="Reported Fee", value=self.loan_fee, inline=False)
        if "http" in self.player.picture:
            e.set_thumbnail(url=self.player.picture)
        return e


class Team(TransferResult):
    """An object representing a Team from Transfermarkt"""

    def __init__(self, name, link):
        self.name = name
        self.link = link
        super().__init__(name, link)
        self.league = None
        self.country = None

    @property
    def markdown(self):
        """Return markdown formatted team name and link"""
        return f"[{self.name}]({self.link})"

    @property
    def league_markdown(self):
        """Return markdown formatted league name and link"""
        if hasattr(self, "league"):
            if self.league == "Without Club":
                return ""
            if hasattr(self, "league_link"):
                return f"[{self.league}]({self.league_link})"
            else:
                return self.league
        else:
            return ""

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
        club = f"{self.markdown} ({self.flag} {self.league_markdown})"
        return f"{club}".strip()

    async def get_contracts(self, ctx):
        """Get a list of expiring contracts for a team."""
        e = await self.base_embed
        e.description = ""
        target = self.link
        target = target.replace('startseite', 'vertragsende')

        async with ctx.bot.session.get(f"{target}") as resp:
            if resp.status != 200:
                return await ctx.reply(content=f"Error {resp.status} connecting to {resp.url}")
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

        view = view_utils.Paginator(ctx, embed_utils.rows_to_embeds(e, rows))
        view.message = await ctx.reply(content=f"Fetching contracts for {self.name}", view=view)
        await view.update()

    def view(self, ctx):
        """Send a view of this Team to the user."""
        return TeamView(ctx, self)


class TeamView(discord.ui.View):
    """A View representing a Team on TransferMarkt"""

    def __init__(self, ctx, team: Team):
        super().__init__()
        self.team = team

        self.message = None
        self.ctx = ctx
        self.index = 0
        self.pages = []

    async def on_timeout(self):
        """Clean up"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction):
        """Verify user of view is correct user."""
        return interaction.user.id == self.ctx.author.id

    async def update(self, content=""):
        """Send the latest version of the view"""
        self.clear_items()

        if len(self.pages) > 1:
            self.add_item(view_utils.PreviousButton(disabled=True if self.index == 0 else False))
            if len(self.pages) > 2:
                self.add_item(view_utils.PageButton(label=f"Page {self.index + 1} of {len(self.pages)}"))
            self.add_item(view_utils.NextButton(disabled=True if self.index + 1 == len(self.pages) else False))

        buttons = [view_utils.FuncButton(label="Transfers", func=self.push_transfers, emoji='🔄'),
                   view_utils.FuncButton(label="Rumours", func=self.push_rumours, emoji='🕵'),
                   view_utils.FuncButton(label="Trophies", func=self.push_trophies, emoji='🏆'),
                   view_utils.FuncButton(label="Contracts", func=self.push_contracts, emoji='📝'),
                   view_utils.StopButton(row=0)
                   ]

        for _ in buttons:
            self.add_item(_)

        if self.message is None:
            self.message = await self.ctx.reply(content="", embed=self.pages[self.index], view=self)
        else:
            await self.message.edit(content="", embed=self.pages[self.index], view=self)

    async def push_transfers(self):
        """Push transfers to View"""
        url = self.team.link.replace('startseite', 'transfers')

        # # Winter window, Summer window.
        # now = datetime.datetime.now()
        # period, season_id = ("w", now.year - 1) if now.month < 7 else ("s", now.year)
        # url = f"{url}/saison_id/{season_id}/pos//0/w_s/plus/plus/1"
        #
        # p = {"w_s": period}
        async with self.ctx.bot.session.get(url) as resp:  # , params=p
            if resp.status != 200:
                await self.ctx.error(f"Error {resp.status} connecting to {resp.url}", message=self.message)
                return None
            tree = html.fromstring(await resp.text())

        def parse(rows, out=False) -> typing.List[Transfer]:
            """Read through the transfers page and extract relevant data, returning a list of transfers"""

            transfers = []
            for i in rows:
                # Block 1 - Discard, Position Colour Marker.

                # Block 2 - Name, Link, Picture, Position
                name = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title')).strip()
                if not name:
                    name = "".join(i.xpath('./td[2]//a/text()')).strip()

                link = "".join(i.xpath('./tm-tooltip[@data-type="player"]/a/@href'))
                if not link:
                    link = "".join(i.xpath('./td[2]//a/@href'))

                if link and TF not in link:
                    link = TF + link
                player = Player(name, link)
                player.picture = "".join(i.xpath('./img[@class="bilderrahmen-fixed"]/@src'))
                player.position = "".join(i.xpath('./td[2]//tr[2]/td/text()')).strip()

                # Block 3 - Age
                player.age = "".join(i.xpath('./td[3]/text()')).strip()

                # Block 4 - Nationality
                player.country = [_.strip() for _ in i.xpath('./td[4]//img/@title') if _.strip()]

                # Block 5 - Other Team
                team_name = "".join(i.xpath('./td[5]//td[@class="hauptlink"]/a/text()')).strip()
                team_link = "".join(i.xpath('./td[5]//td[@class="hauptlink"]/a/@href'))
                if team_link and TF not in team_link:
                    team_link = TF + team_link

                team = Team(team_name, team_link)
                team.league = "".join(i.xpath("./td[5]//tr[2]//a/text()")).strip()
                league_link = "".join(i.xpath("./td[5]//tr[2]//a/@href")).strip()
                team.league_link = TF + league_link if league_link else ""
                team.country = [_.strip() for _ in i.xpath("./td[5]//img/@title") if _.strip()]

                new = team if out else self.team
                old = self.team if out else team

                transfer = Transfer(player=player)
                transfer.new_team = new
                transfer.old_team = old

                # Block 6 - Fee or Loan
                transfer.fee = "".join(i.xpath('.//td[6]//text()')).strip()
                transfer.fee_link = TF + "".join(i.xpath('.//td[6]//@href')).strip()
                transfer.date = "".join(i.xpath('.//i/text()'))
                transfers.append(transfer)
            return transfers

        _ = tree.xpath('.//div[@class="box"][.//h2[contains(text(),"Arrivals")]]//tr[@class="even" or @class="odd"]')
        players_in = parse(_)
        _ = tree.xpath('.//div[@class="box"][.//h2[contains(text(),"Departures")]]//tr[@class="even" or @class="odd"]')
        players_out = parse(_, out=True)

        base_embed = await self.team.base_embed
        base_embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
        base_embed.url = url

        embeds = []

        if players_in:
            e = deepcopy(base_embed)
            e.title = f"Inbound Transfers for {e.title}"
            e.colour = discord.Colour.green()
            embeds += embed_utils.rows_to_embeds(e, [i.inbound for i in players_in])

        if players_out:
            e = deepcopy(base_embed)
            e.title = f"Outbound Transfers for {e.title}"
            e.colour = discord.Colour.red()
            embeds += embed_utils.rows_to_embeds(e, [i.outbound for i in players_out])

        if not embeds:
            e = base_embed
            e.title = f"No transfers found {e.title}"
            e.colour = discord.Colour.orange()
            embeds = [e]

        self.pages = embeds
        self.index = 0
        await self.update()

    async def push_rumours(self):
        """Send transfer rumours for a team to View"""
        e = await self.team.base_embed
        e.description = ""
        target = self.team.link.replace('startseite', 'geruechte')
        async with self.ctx.bot.session.get(target) as resp:
            if resp.status != 200:
                e.description = f"Error {resp.status} connecting to {resp.url}"
                return await self.message.edit(embed=e, view=self)
            tree = html.fromstring(await resp.text())
            e.url = target

        e.title = f"Transfer rumours for {self.team.name}"
        e.set_author(name="Transfermarkt", url=target, icon_url=FAVICON)

        rows = []
        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title')).strip()
            link = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@href')).strip()

            if not name:
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))
            if not link:
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            pos = "".join(i.xpath('.//td[2]//tr[2]/td/text()'))
            flag = get_flag(i.xpath('.//td[3]/img/@title')[0])
            age = "".join(i.xpath('./td[4]/text()')).strip()
            team = "".join(i.xpath('.//td[5]//img/@alt'))
            team_link = "".join(i.xpath('.//td[5]//img/@href'))
            if "transfermarkt" not in team_link:
                team_link = "http://www.transfermarkt.com" + team_link
            source = "".join(i.xpath('.//td[8]//a/@href'))
            src = f"[Info]({source})"
            rows.append(f"{flag} **[{name}]({link})** ({src})\n{age}, {pos} [{team}]({team_link})\n")

        rows = ["No rumours about new signings found."] if not rows else rows

        self.pages = embed_utils.rows_to_embeds(e, rows)
        self.index = 0
        await self.update()

    async def push_trophies(self):
        """Send trophies for a team to View"""
        url = self.team.link.replace('startseite', 'erfolge')

        async with self.ctx.bot.session.get(url) as resp:
            if resp.status != 200:
                return await self.ctx.error(f"Error {resp.status} connecting to {resp.url}")
            tree = html.fromstring(await resp.text())

        rows = tree.xpath('.//div[@class="box"][./div[@class="header"]]')
        results = []
        for i in rows:
            title = "".join(i.xpath('.//h2/text()'))
            dates = "".join(i.xpath('.//div[@class="erfolg_infotext_box"]/text()'))
            dates = " ".join(dates.split()).replace(' ,', ',')
            results.append(f"**{title}**\n{dates}\n")

        e = await self.team.base_embed
        e.title = f"{self.team.name} Trophy Case"
        trophies = ["No trophies found for team."] if not results else results
        self.pages = embed_utils.rows_to_embeds(e, trophies)
        self.index = 0
        await self.update()

    async def push_contracts(self):
        """Push a list of a team's expiring contracts to the view"""
        e = await self.team.base_embed
        e.description = ""
        target = self.team.link.replace('startseite', 'vertragsende')

        async with self.ctx.bot.session.get(target) as resp:
            if resp.status != 200:
                e.description = f"Error {resp.status} connecting to {resp.url}"
                return await self.message.edit(embed=e, view=self)
            tree = html.fromstring(await resp.text())
            e.url = target

        e.title = f"Expiring contracts for {self.team.name}"
        e.set_author(name="Transfermarkt", url=target, icon_url=FAVICON)

        rows = []

        for i in tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0].xpath('.//tbody/tr'):
            name = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@title')).strip()
            link = "".join(i.xpath('.//tm-tooltip[@data-type="player"]/a/@href')).strip()

            if not name:
                name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))
            if not link:
                link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

            if link and TF not in link:
                link = TF + link

            if not name and not link:
                continue

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
        self.pages = embed_utils.rows_to_embeds(e, rows)
        self.index = 0
        await self.update()


def parse_teams(rows):
    """Fetch a list of teams from a transfermarkt page"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//tm-tooltip[@data-type="club"]/a/@title')).strip()
        link = "".join(i.xpath('.//tm-tooltip[@data-type="club"]/a/@href')).strip()

        # Fallbacks.
        if not name:
            name = "".join(i.xpath('.//td[@class="hauptlink"]/a/@title'))
        if not link:
            link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))

        if link:
            link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link

        team = Team(name, link)

        team.logo = "".join(i.xpath('.//td[@class="suche-vereinswappen"]/img/@src'))
        team.league = "".join(i.xpath('.//tr[2]/td/a/text()')).strip()

        lnk = "".join(i.xpath('.//tr[2]/td/a/@href')).strip()
        if lnk and "transfermarkt" not in lnk:
            lnk = f"https://www.transfermarkt.co.uk{lnk}"
        team.league_link = lnk
        team.country = [_.strip() for _ in i.xpath('.//td/img[1]/@title') if _.strip()]
        results.append(team)
    return results


class Referee(TransferResult):
    """An object representing a referee from transfermarkt"""

    def __init__(self, name, link):
        self.age = ""
        self.country = ""
        super().__init__(name, link)

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link}) {self.age}"


def parse_referees(rows) -> typing.List[Referee]:
    """Parse a transfer page to get a list of referees"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
        link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
        if "https://www.transfermarkt.co.uk" not in link:
            link = f"https://www.transfermarkt.co.uk{link}"

        result = Referee(name=name, link=link)

        result.age = "".join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
        result.country = i.xpath('.//td/img[1]/@title')
        results.append(result)
    return results


class Competition(TransferResult):
    """An Object representing a competition from transfermarkt"""

    def __init__(self, name, link, country):
        self.country = country
        super().__init__(name, link)

    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link})"


class CompetitionView(discord.ui.View):
    """A View representing a competition on TransferMarkt"""

    def __init__(self, ctx, comp: Competition):
        super().__init__()
        self.comp = comp
        self.message = None
        self.ctx = ctx
        self.index = 0
        self.pages = []

    async def on_timeout(self):
        """Clean up"""
        self.clear_items()
        await self.message.edit(view=self)
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction):
        """Verify user of view is correct user."""
        return interaction.user.id == self.ctx.author.id

    async def update(self, content=""):
        """Send the latest version of the view"""
        self.clear_items()

        if len(self.pages) > 1:
            _ = view_utils.PreviousButton()
            _.disabled = True if self.index == 0 else False
            self.add_item(_)

            if len(self.pages) > 2:
                _ = view_utils.PageButton()
                _.label = f"Page {self.index + 1} of {len(self.pages)}"
                self.add_item(_)

            _ = view_utils.NextButton()
            _.disabled = True if self.index + 1 == len(self.pages) else False
            self.add_item(_)

        buttons = [view_utils.FuncButton(label="Attendances", func=self.push_attendance, emoji='🏟️'),
                   view_utils.StopButton(row=0)
                   ]

        for _ in buttons:
            self.add_item(_)
        if self.message is None:
            self.message = self.ctx.send(content=content, embed=self.pages[self.index], view=self)
        else:
            await self.message.edit(content=content, embed=self.pages[self.index], view=self)

    async def push_attendance(self):
        """Fetch attendances for league's stadiums."""
        async with self.ctx.bot.session.get(self.comp.link + "/besucherzahlen/wettbewerb/GB1/plus/") as resp:
            if resp.status != 200:
                return await self.ctx.error(f"HTTP Error {resp.status} accessing transfermarkt")
            tree = html.fromstring(await resp.text())

        rows = []
        for i in tree.xpath('.//table[@class="items"]/tr'):
            stadium = ""
            std_lnk = ""
            team = ""
            team_lk = ""

        # TODO: League Attendance
        # https://www.transfermarkt.co.uk/premier-league/besucherzahlen/wettbewerb/GB1/plus/?saison_id=2020
        pass


def parse_competitions(rows) -> typing.List[Competition]:
    """Parse a transfermarkt page into a list of Competition Objects"""
    results = []
    for i in rows:
        name = "".join(i.xpath('.//td[2]/a/text()')).strip()
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href')).strip()
        country = [_.strip() for _ in i.xpath('.//td[3]/img/@title') if _.strip()]
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
        link = "".join(i.xpath('.//td[2]/a/@href'))
        if "https://www.transfermarkt.co.uk" not in link:
            link = "https://www.transfermarkt.co.uk" + link
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
                self.add_option(label=_.name, description=f"{_.country[0]}: {_.league}", value=str(num), emoji='👕')
            elif isinstance(_, Competition):
                self.add_option(label=_.name, description=_.country[0], value=str(num), emoji='🏆')

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
        print(item.__dict__)
        print(interaction)
        raise error

    async def on_timeout(self):
        """Cleanup."""
        self.clear_items()
        try:
            await self.message.edit(content="", embed=self.message.embed, view=self)
        except AttributeError:
            pass

    async def update(self, content=""):
        """Populate Initial Results"""
        self.clear_items()
        url = 'https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'

        # Header names, scrape then compare (because they don't follow a pattern.)
        if self.category is None:
            p = {"query": self.query}

            async with self.ctx.bot.session.post(url, params=p) as resp:
                if resp.status != 200:
                    return await self.ctx.error(f"HTTP {resp.status} Error connecting to transfermarkt.")
                self.url = str(resp.url)
                tree = html.fromstring(await resp.text())

            categories = [i.lower().strip() for i in tree.xpath(".//div[@class='table-header']/text()")]

            select = CategorySelect()
            ce = discord.Embed(title="Multiple results found", description="")
            ce.set_footer(text="Use the dropdown to select a category")

            for i in categories:
                # Just give number of matches (digit characters).
                try:
                    length = int("".join([n for n in i if n.isdecimal()]))
                except ValueError:
                    print("ValueError in transfer_tools", i)
                    length = "?"

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
                return await self.ctx.error(f'No results found for query {self.query}', message=self.message)

            elif len(select.options) == 1:
                self.category = select.options[0].label

            else:
                self.clear_items()
                self.add_item(select)
                await self.message.edit(content=content, view=self, embed=ce)
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

        try:
            matches = int("".join([i for i in _ if i.isdecimal()]))
        except ValueError:
            matches = 0
            if _:
                print("ValueError in transfer_tools", _)

        e = discord.Embed(title=f"{matches} {self.category.title().rstrip('s')} results for {self.query}")
        e.set_author(name="TransferMarkt Search", url=self.url, icon_url=FAVICON)

        results = parser(tree.xpath(trs))
        rows = [f"🚫 No results found for {self.category}: {self.query}"] if not matches else [str(i) for i in results]
        e = embed_utils.rows_to_embeds(e, rows)[0]

        self.pages = [None] * max(matches // 10, 1)
        self.add_item(HomeButton())

        if len(self.pages) > 1:
            self.add_item(view_utils.PreviousButton(disabled=True if self.index == 1 else False))
            self.add_item(view_utils.PageButton(label=f"Page {self.index} of {len(self.pages)}"))
            self.add_item(view_utils.NextButton(disabled=True if self.index == len(self.pages) else False))

        self.add_item(view_utils.StopButton(row=0))

        if self.fetch and results:
            self.add_item(SearchSelect(objects=results))

        if self.message is None:
            self.message = await self.ctx.reply(content=content, embed=e, view=self)
        else:
            await self.message.edit(content=content, embed=e, view=self)
