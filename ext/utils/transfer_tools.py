import datetime
import pycountry
import discord
import asyncio
from lxml import html

from ext.utils import embed_utils

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
    "England": "gb",
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
    "Scotland": "gb",
    "Sint Maarten": "sx",
    "Southern Sudan": "ss",
    "South Korea": "kr",
    "St. Kitts & Nevis": "kn",
    "St. Louis": "lc",
    "St. Vincent & Grenadinen": "vc",
    "Tahiti": "fp",
    "Tanzania": "tz",
    "The Gambia": "gm",
    "Trinidad and Tobago": "tt",
    "Turks- and Caicosinseln": "tc",
    "Sao Tome and Princip": "st",
    "USA": "us",
    "Venezuela": "ve",
    "Vietnam": "vn",
    "Wales": "gb"}

unidict = {
    "a": "🇦", "b": "🇧", "c": "🇨", "d": "🇩", "e": "🇪",
    "f": "🇫", "g": "🇬", "h": "🇭", "i": "🇮", "j": "🇯",
    "k": "🇰", "l": "🇱", "m": "🇲", "n": "🇳", "o": "🇴",
    "p": "🇵", "q": "🇶", "r": "🇷", "s": "🇸", "t": "🇹",
    "u": "🇺", "v": "🇻", "w": "🇼", "x": "🇽", "y": "🇾", "z": "🇿"
}


def get_flag(country):
    # Check if pycountry has country
    if country.lower() in ["england", "scotland", "wales"]:
        country = f":{country.lower()}:"
        return country
    
    try:
        country = pycountry.countries.get(name=country.title()).alpha_2
    except (KeyError, AttributeError):
        try:
            # else revert to manual dict.
            country = country_dict[country]
        except KeyError:
            return country  # Shrug.
    country = country.lower()
    
    for key, value in unidict.items():
        country = country.replace(key, value)
    return country


class TransferResult:
    def __init__(self, name, link, **kwargs):
        self.link = link
        self.name = name
    
    def __repr__(self):
        return f"TransferResult({self.__dict__})"
    
    @property
    async def base_embed(self):
        e = discord.Embed()
        e.colour = discord.Colour.dark_blue()
        e.set_author(name="TransferMarkt")
        return e
    
    @property
    def flag(self):
        # Return earth emoji if does not have a country.
        if not hasattr(self, "country"):
            return "🌍"

        if isinstance(self.country, list):
            return "".join([get_flag(i) for i in self.country])
        else:
            return get_flag(self.country)


class Player(TransferResult):
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


class Staff(TransferResult):
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
    def __init__(self, player: Player, old_team, new_team, fee, fee_link):
        self.fee = fee
        self.fee_link = fee_link
        self.old_team = old_team
        self.new_team = new_team
        self.player = player
        super().__init__(player.name, player.link)
    
    @property
    def loan_or_fee(self):
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
        e.set_thumbnail(url=self.player.picture)
        return e


class Team(TransferResult):
    def __init__(self, name, link, country, league, league_link):
        self.league = league
        self.league_link = league_link
        self.country = country
        super().__init__(name, link)
    
    @property
    def markdown(self):
        if self.name == "Without Club":
            return self.name
        return f"[{self.name}]({self.link})"

    @property
    def league_markdown(self):
        if self.name == "Without Club":
            return ""
        return f"[{self.league}]({self.league_link})"
    
    @property
    def badge(self):
        number = self.link.split('/')[-1]
        return f"https://tmssl.akamaized.net/images/wappen/head/{number}.png"
    
    @property
    async def base_embed(self):
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
    
    async def get_transfers(self, ctx):
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
        
        def parse(table):
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


class Referee(TransferResult):
    def __init__(self, name, link, country, age):
        self.age = age
        self.country = country
        super().__init__(name, link)
        
    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link}) {self.age}"


class Competition(TransferResult):
    def __init__(self, name, link, country):
        self.country = country
        super().__init__(name, link)
    
    def __str__(self):
        return f"{self.flag} [{self.name}]({self.link})"


class Agent(TransferResult):
    def __init__(self, name, link):
        super().__init__(name, link)
    
    def __str__(self):
        return f"[{self.name}]({self.link})"


async def parse_players(trs):
    players = []
    for i in trs:
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


async def parse_staff(trs):
    staff = []
    for i in trs:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()'))
        link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href'))
        link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link

        team = "".join(i.xpath('.//td[2]/a/img/@alt'))
        tl = "".join(i.xpath('.//td[2]/a/img/@href'))
        tl = "https://www.transfermarkt.co.uk" + tl if "transfermarkt" not in tl else tl
        age = "".join(i.xpath('.//td[3]/text()'))
        job = "".join(i.xpath('.//td[5]/text()'))
        country = "".join(i.xpath('.//td/img[1]/@title'))

        staff.append(Staff(name=name, link=link, team=team, team_link=tl, age=age, job=job, country=country))
    return staff


async def parse_teams(trs):
    teams = []
    for i in trs:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
        link = "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
        link = "https://www.transfermarkt.co.uk" + link if "transfermarkt" not in link else link
        league = "".join(i.xpath('.//tr[2]/td/a/text()')).strip()
        league_link = "".join(i.xpath('.//tr[2]/td/a/@href')).strip()
        country = "".join(i.xpath('.//td/img[1]/@title')[-1]).strip()
        teams.append(Team(name=name, link=link, country=country, league=league, league_link=league_link))
    return teams


async def parse_refs(trs):
    referees = []
    for i in trs:
        name = "".join(i.xpath('.//td[@class="hauptlink"]/a/text()')).strip()
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[@class="hauptlink"]/a/@href')).strip()
        age = "".join(i.xpath('.//td[@class="zentriert"]/text()')).strip()
        country = "".join(i.xpath('.//td/img[1]/@title')).strip()

        referees.append(Referee(name=name, link=link, age=age, country=country))
    return referees


async def parse_domestic(trs):
    competitions = []
    for i in trs:
        name = "".join(i.xpath('.//td[2]/a/text()')).strip()
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href')).strip()
        country = "".join(i.xpath('.//td[3]/img/@title')).strip()
        competitions.append(Competition(name=name, link=link, country=country))
    return competitions


async def parse_int(trs):
    competitions = []
    for i in trs:
        name = "".join(i.xpath('.//td[2]/a/text()'))
 
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href'))
        country = ""
        competitions.append(Competition(name=name, link=link, country=country))
    return competitions


async def parse_agent(trs):
    agents = []
    for i in trs:
        name = "".join(i.xpath('.//td[2]/a/text()'))
        link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[2]/a/@href'))
        agents.append(Agent(name=name, link=link))
    return agents


async def fetch_page(ctx, category, query, page):
    settings = parser_settings[category]
    match = settings["match_string"]
    param = settings["querystr"]
    
    p = {"query": query, param: page}
    url = 'https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'
    async with ctx.bot.session.post(url, params=p) as resp:
        if resp.status != 200:
            await ctx.bot.reply(ctx, text=f"HTTP Error connecting to transfermarkt: {resp.status}")
            return None
        tree = html.fromstring(await resp.text())

    # Get trs of table after matching header / {categ} name.
    trs = f".//div[@class='box']/div[@class='table-header'][contains(text(),'{match}')]/following::div[1]//tbody/tr"
    
    matches = "".join(tree.xpath(f".//div[@class='table-header'][contains(text(),'{match}')]/text()"))
    matches = "".join([i for i in matches if i.isdecimal()])
    
    e = discord.Embed()
    e.colour = 0x1a3151
    e.url = str(resp.url)
    e.title = "Transfermarkt Search"
    header = f"{category.title()}: {matches} results for '{query.title()}' found"
    try:
        total_pages = int(matches) // 10 + 1
    except ValueError:
        total_pages = 0
    e.set_footer(text=f"Page {page} of {total_pages}")
    return e, tree.xpath(trs), total_pages, header


def make_embed(e, header, results, special):
    if special:
        e.description = "Please type matching ID#\n\n"
        for i, j in enumerate(results):
            e.description += f"`[{i}]`: {j}\n"
    else:
        e.description = header + "\n\n" + "\n".join([str(i) for i in results])
    return e


async def search(ctx, qry, category, special=False):
    page = 1
    e, tree, total_pages, header = await fetch_page(ctx, category, qry, page)
    if not tree:
        await ctx.bot.reply(ctx, text="No results.")
        return None

    results = await parser_settings[category]["parser"](tree)

    e = make_embed(e, header, results, special)

    # Create message and add reactions
    m = await ctx.bot.reply(ctx, embed=e)
    
    reacts = []
    if total_pages > 2:
        reacts.append("⏮")  # first
    if total_pages > 1:
        reacts.append("◀")  # prev
        reacts.append("▶")  # next
    if total_pages > 2:
        reacts.append("⏭")  # last
    reacts.append("🚫")  # eject
    
    try:
        await embed_utils.bulk_react(ctx, m, reacts)
    except AssertionError:
        await ctx.bot.reply(ctx, text='No add_reactions permission, showing first page only.', mention_author=True)

    # Only respond to user who invoked command.
    def page_check(emo, usr):
        if emo.message.id == m.id and usr.id == ctx.author.id:
            ej = str(emo.emoji)
            if ej.startswith(('⏮', '◀', '▶', '⏭', '🚫')):
                return True

    def reply_check(msg):
        if ctx.message.author.id == msg.author.id:
            try:
                return int(msg.content) < len(results)
            except ValueError:
                return False
        
    # Reaction Logic Loop.
    while True:
        received, dead = await asyncio.wait(
            [ctx.bot.wait_for('message', check=reply_check), ctx.bot.wait_for('reaction_add', check=page_check)],
            timeout=30, return_when=asyncio.FIRST_COMPLETED)
        
        if not received:
            try:
                await m.clear_reactions()
                await m.delete()
            except discord.HTTPException:
                pass
            return

        res = received.pop().result()
        for i in dead:
            i.cancel()
            
        if isinstance(res, discord.Message):
            # It's a message.
            await m.delete()
            try:
                await res.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            finally:
                return results[int(res.content)]
        else:
            # it's a reaction.
            reaction, user = res
            if reaction.emoji == "⏮":  # first
                page = 1
            elif reaction.emoji == "◀":  # prev
                page = page - 1 if page > 1 else page
            elif reaction.emoji == "▶":  # next
                page = page + 1 if page < total_pages else page
            elif reaction.emoji == "⏭":  # last
                page = total_pages
            elif reaction.emoji == "🚫":  # eject
                try:
                    await m.delete()
                except discord.NotFound:
                    pass
                return
            try:
                await m.remove_reaction(reaction.emoji, ctx.message.author)
            except discord.Forbidden:
                pass

        # Fetch the next page of results.
        e, tree, total_pages, header = await fetch_page(ctx, category, qry, page)
        results = await parser_settings[category]["parser"](tree)
        e = make_embed(e, header, results, special)  # reassign item dict.
        await m.edit(embed=e, allowed_mentions=discord.AllowedMentions().none())


async def get_rumours(ctx, e, target):
    e.description = ""
    target = target.replace('startseite', 'geruechte')
    async with ctx.bot.session.get(f"{target}") as resp:
        if resp.status != 200:
            return await ctx.bot.reply(ctx, text=f"Error {resp.status} connecting to {resp.url}")
        tree = html.fromstring(await resp.text())
        e.url = str(resp.url)
    e.set_author(name=tree.xpath('.//head/title[1]/text()')[0], url=str(resp.url))
    e.set_footer(text=discord.Embed.Empty)
    
    rumours = tree.xpath('.//div[@class="large-8 columns"]/div[@class="box"]')[0]
    rumours = rumours.xpath('.//tbody/tr')
    rumorlist = []
    for i in rumours:
        pname = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
        if not pname:
            continue
        player_link = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/@href'))
        player_link = f"https://www.transfermarkt.co.uk{player_link}"
        ppos = "".join(i.xpath('.//td[2]//tr[2]/td/text()'))
        flag = get_flag(i.xpath('.//td[3]/img/@title')[0])
        age = "".join(i.xpath('./td[4]/text()')).strip()
        team = "".join(i.xpath('.//td[5]//img/@alt'))
        team_link = "".join(i.xpath('.//td[5]//img/@href'))
        if "transfermarkt" not in team_link:
            team_link = "http://www.transfermarkt.com" + team_link
        source = "".join(i.xpath('.//td[8]//a/@href'))
        src = f"[Info]({source})"
        rumorlist.append(f"{flag} **[{pname}]({player_link})** ({src})\n{age}, {ppos} [{team}]({team_link})\n\n")
    
    output = ""
    count = 0
    if not rumorlist:
        output = "No rumours about new signings found."
    for i in rumorlist:
        if len(i) + len(output) < 1985:
            output += i
        else:
            output += f"And {len(rumorlist) - count} more..."
            break
        count += 1
    e.description = output
    
    await ctx.bot.reply(ctx, embed=e)

parser_settings = {
    "players": {"match_string": "players", "querystr": "Spieler_page", "parser": parse_players},
    "staff": {"match_string": "Managers", "querystr": "Trainer_page", "parser": parse_staff},
    "teams": {"match_string": "Clubs", "querystr": "Verein_page", "parser": parse_teams},
    "referees": {"match_string": "referees", "querystr": "Schiedsrichter_page", "parser": parse_refs},
    "domestic": {"match_string": "to competitions", "querystr": "Wettbewerb_page", "parser": parse_domestic},
    "international": {"match_string": "international comp", "querystr": "Wettbewerb_page", "parser": parse_int},
    "agent": {"match_string": "Agents", "querystr": "page", "parser": parse_agent},
    "Rumours": {"match_string": "Clubs", "querystr": "Verein_page", "parser": parse_teams}
}
