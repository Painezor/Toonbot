"""Commands for fetching information about football entities from transfermarkt"""
import datetime
import typing
from copy import deepcopy
from importlib import reload

import discord
from discord.ext import commands
from lxml import html

from ext.utils import transfer_tools, embed_utils, view_utils, timed_events

TF = "https://www.transfermarkt.co.uk"
FAVICON = "https://upload.wikimedia.org/wikipedia/commons/f/fb/Transfermarkt_favicon.png"


class TeamView(discord.ui.View):
    """A View representing a Team on TransferMarkt"""

    def __init__(self, ctx, team: transfer_tools.Team):
        super().__init__()
        self.team = team

        self.message = None
        self.ctx = ctx
        self.index = 0
        self.pages = []

    async def on_timeout(self):
        """Clean up"""
        self.clear_items()
        await self.message.edit(view=self)
        self.stop()

    async def update(self):
        """Send latest version of view"""
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

        buttons = [view_utils.Button(label="Transfers", func=self.push_transfers, emoji='🔄'),
                   view_utils.Button(label="Rumours", func=self.push_rumours, emoji='🕵'),
                   view_utils.Button(label="Trophies", func=self.push_trophies, emoji='🏆'),
                   view_utils.Button(label="Contracts", func=self.push_contracts, emoji='📝'),
                   view_utils.StopButton(row=0)
                   ]

        for _ in buttons:
            self.add_item(_)

        _ = discord.AllowedMentions.none()
        await self.message.edit(content="", embed=self.pages[self.index], view=self, allowed_mentions=_)

    async def push_transfers(self):
        """Push transfers to View"""
        url = self.team.link.replace('startseite', 'transfers')

        # Winter window, Summer window.
        now = datetime.datetime.now()
        period, season_id = ("w", now.year - 1) if now.month < 7 else ("s", now.year)
        url = f"{url}/saison_id/{season_id}/pos//0/w_s/plus/plus/1"

        p = {"w_s": period}
        async with self.ctx.bot.session.get(url, params=p) as resp:
            if resp.status != 200:
                await self.ctx.bot.reply(self.ctx, text=f"Error {resp.status} connecting to {resp.url}", delete_after=5)
                return None
            tree = html.fromstring(await resp.text())

        def parse(table, out=False) -> typing.List[transfer_tools.Transfer]:
            """Read through the transfers page and extract relevant data, returning a list of transfers"""
            transfers = []
            for i in table:
                name = "".join(i.xpath('.//a[@class="spielprofil_tooltip"]/text()')).strip()
                link = TF + "".join(i.xpath('.//a[@class="spielprofil_tooltip"]/@href')).strip()
                age = "".join(i.xpath('.//td[3]/text()')).strip()
                position = "".join(i.xpath('.//td[2]//tr[2]/td/text()')).strip()
                picture = "".join(i.xpath('.//img[@class="bilderrahmen-fixed"]/@src'))
                country = [_.strip() for _ in i.xpath('.//td[5]//img/@title') if _.strip()]

                team = "".join(i.xpath('.//td[6]//td[@class="hauptlink"]/a/text()')).strip()
                _ = "".join(i.xpath('.//td[6]//td[@class="hauptlink"]/a/@href')).strip()
                team_link = TF + _
                league = "".join(i.xpath(".//td[6]//tr[2]//a/text()")).strip()

                _ = "".join(i.xpath(".//td[6]//tr[2]//a/@href")).strip()
                league_link = TF + _ if _ else ""
                team_country = [_.strip() for _ in i.xpath(".//td[6]//img/@title") if _.strip()]

                _ = self.team

                player = transfer_tools.Player(name, link, _.name, age, position, _.link, country, picture)
                old = transfer_tools.Team(team, team_link, team_country, league, league_link)
                new = transfer_tools.Team(_.name, _.link, _.country, _.league, _.league_link)
                fee = "".join(i.xpath('.//td[7]//text()')).strip()
                fee_link = TF + "".join(i.xpath('.//td[7]//@href')).strip()
                date = "".join(i.xpath('.//i/text()'))

                team_from = new if out else old
                team_to = old if out else new

                transfer = transfer_tools.Transfer(player, team_from, team_to, fee, fee_link, date=date)
                transfers.append(transfer)
            return transfers

        _ = tree.xpath('.//div[@class="box"][.//h2[contains(text(),"Arrivals")]]/div[@class="responsive-table"]')
        players_in = parse(_[0].xpath('.//tbody/tr')) if _ else []
        _ = tree.xpath('.//div[@class="box"][.//h2[contains(text(),"Departures")]]/div[@class="responsive-table"]')
        players_out = parse(_[0].xpath('.//tbody/tr'), out=True) if _ else []

        base_embed = await self.team.base_embed
        base_embed.set_author(name="Transfermarkt", url=url, icon_url=FAVICON)
        base_embed.url = url

        embeds = []

        if players_in:
            e = deepcopy(base_embed)
            e.title = f"Inbound Transfers for {e.title}"
            e.colour = discord.Colour.green()
            embeds += embed_utils.rows_to_embeds(e, [str(i) for i in players_in])

        if players_out:
            e = deepcopy(base_embed)
            e.title = f"Outbound Transfers for {e.title}"
            e.colour = discord.Colour.red()
            embeds += embed_utils.rows_to_embeds(e, [str(i) for i in players_out])

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
            name = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
            if not name:
                continue

            _ = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/@href')).strip()
            link = TF + _
            pos = "".join(i.xpath('.//td[2]//tr[2]/td/text()'))
            flag = transfer_tools.get_flag(i.xpath('.//td[3]/img/@title')[0])
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
                await self.ctx.bot.reply(self.ctx, text=f"Error {resp.status} connecting to {resp.url}", delete_after=5)
                return None
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
            name = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/text()'))
            if not name:
                continue

            _ = "".join(i.xpath('.//td[@class="hauptlink"]/a[@class="spielprofil_tooltip"]/@href'))
            link = TF + _ if _ else ""

            pos = "".join(i.xpath('.//td[1]//tr[2]/td/text()'))
            age = "".join(i.xpath('./td[2]/text()')).split('(')[-1].replace(')', '').strip()
            flag = " ".join([transfer_tools.get_flag(f) for f in i.xpath('.//td[3]/img/@title')])
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


class Lookups(commands.Cog):
    """Transfer market lookups"""

    def __init__(self, bot):
        self.bot = bot
        reload(transfer_tools)
        self.emoji = "🔎"

    async def team_view(self, ctx, query):
        """Shared function for following commands."""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for.', ping=True)

        elif str(query).startswith("set ") and ctx.message.channel_mentions:
            return await self.bot.reply(ctx, "🚫 You probably meant to use .tf, not .transfers.", ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Clubs", fetch=True)
        view.message = await self.bot.reply(ctx, f"Fetching Clubs matching {query}", view=view)
        await view.update()

        team = view.value

        if team is None:
            return

        am = discord.AllowedMentions.none()
        _ = TeamView(ctx, team)
        _.message = await view.message.edit(content=f"Fetching transfers for {team.name}", view=_, allowed_mentions=am)

        return None if team is None else _

    # Base lookup - No Sub-command invoked.
    @commands.group(invoke_without_command=True, usage="<Who you want to search for>")
    async def lookup(self, ctx, *, query: commands.clean_content = None):
        """Perform a database lookup on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify something to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query)
        view.message = await self.bot.reply(ctx, f"Fetching results for {query}", view=view)
        await view.update()

    @lookup.command(usage="<Player name to search for>")
    async def player(self, ctx, *, query: commands.clean_content = None):
        """Lookup a player on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a player name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Players")
        view.message = await self.bot.reply(ctx, f"Fetching player results for {query}", view=view)
        await view.update()

    @lookup.command(aliases=["club"], usage="<Team name to search for>")
    async def team(self, ctx, *, query: commands.clean_content = None):
        """Lookup a team on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a team name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Clubs")
        view.message = await self.bot.reply(ctx, f"Fetching club results for {query}", view=view)
        await view.update()

    @lookup.command(aliases=["manager", "trainer", "trainers", "managers"], usage="Manager to search for")
    async def staff(self, ctx, *, query: commands.clean_content = None):
        """Lookup a manager/trainer/club official on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Managers")
        view.message = await self.bot.reply(ctx, f"Fetching staff results for {query}", view=view)
        await view.update()

    @lookup.command(aliases=['referee'], usage="<Referee name to search for>")
    async def ref(self, ctx, *, query: commands.clean_content = None):
        """Lookup a referee on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a referee name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Referees")
        view.message = await self.bot.reply(ctx, f"Fetching referee results for {query}", view=view)
        await view.update()

    @lookup.command(aliases=["league", "cup"], usage="<Competition name to search for>")
    async def competition(self, ctx, *, query: commands.clean_content = None):
        """Lookup a competition on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify a competition name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Competitions")
        view.message = await self.bot.reply(ctx, f"Fetching competition results for {query}", view=view)
        await view.update()

    @lookup.command(usage="<Agency naem to search for>")
    async def agent(self, ctx, *, query: commands.clean_content = None):
        """Lookup an agent on transfermarkt"""
        if query is None:
            return await self.bot.reply(ctx, '🚫 You need to specify an agent name to search for.', ping=True)

        view = transfer_tools.SearchView(ctx, query, category="Agents")
        view.message = await self.bot.reply(ctx, f"Fetching agent results for {query}", view=view)
        await view.update()

    @commands.command(usage="<team to search for>")
    async def transfers(self, ctx, *, query: commands.clean_content = None):
        """Get this window's transfers for a team on transfermarkt"""
        _ = await self.team_view(ctx, query)
        if _ is not None:
            await _.push_transfers()

    @commands.command(aliases=["rumors"], usage="<team to search for>")
    async def rumours(self, ctx, *, query: commands.clean_content = None):
        """Get the latest transfer rumours for a team"""
        _ = await self.team_view(ctx, query)
        if _ is not None:
            await _.push_rumours()

    @commands.command(usage="<team to search for>")
    async def contracts(self, ctx, *, query: commands.clean_content = None):
        """Get a team's expiring contracts"""
        _ = await self.team_view(ctx, query)
        if _ is not None:
            await _.push_contracts()

    @commands.command(usage="<team to search for>")
    async def trophies(self, ctx, *, query: commands.clean_content = None):
        """Get a list of a team's trophies"""
        _ = await self.team_view(ctx, query)
        if _ is not None:
            await _.push_trophies()


def setup(bot):
    """Load the lookup cog into the bot"""
    bot.add_cog(Lookups(bot))
