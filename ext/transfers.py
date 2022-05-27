"""Automated fetching of the latest football transfer information from transfermarkt"""
import traceback
from typing import TYPE_CHECKING, List

from discord import ButtonStyle, Interaction, Embed, Colour, HTTPException, TextChannel, Message, Permissions
from discord.app_commands import Group, describe
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View, Button, Select
from lxml import html

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.transfer_tools import Player, Team, Competition, Transfer, SearchView
from ext.utils.view_utils import add_page_buttons, Confirmation

if TYPE_CHECKING:
    from core import Bot

LG = [(":england: Premier League", "https://www.transfermarkt.co.uk/premier-league/startseite/wettbewerb/GB1"),
      (":england: Championship", "https://www.transfermarkt.co.uk/championship/startseite/wettbewerb/GB2"),
      ("🇳🇱 Eredivisie", "https://www.transfermarkt.co.uk/eredivisie/startseite/wettbewerb/NL1"),
      ("🇩🇪 Bundesliga", "https://www.transfermarkt.co.uk/bundesliga/startseite/wettbewerb/L1"),
      ("🇮🇹 Serie A", "https://www.transfermarkt.co.uk/serie-a/startseite/wettbewerb/IT1"),
      ("🇪🇸 LaLiga", "https://www.transfermarkt.co.uk/primera-division/startseite/wettbewerb/ES1"),
      ("🇫🇷 Ligue 1", "https://www.transfermarkt.co.uk/ligue-1/startseite/wettbewerb/FR1"),
      ("🇺🇸 Major League Soccer", "https://www.transfermarkt.co.uk/major-league-soccer/startseite/wettbewerb/MLS1")]
TF = "https://www.transfermarkt.co.uk"
MIN_MARKET_VALUE = "200.000"
LOOP_URL = f'{TF}/transfers/neuestetransfers/statistik?minMarktwert={MIN_MARKET_VALUE}'


class ResetLeagues(Button):
    """Button to reset a transfer ticker back to its default leagues"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            for alias, link in LG:
                await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                            VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                                         self.view.channel.id, link, alias)
        await self.bot.db.release(connection)
        await self.view.update(content=f"The tracked transfers for {self.view.channel.mention} were reset")


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """DELETE FROM transfers_channels WHERE channel_id = $1"""
                await connection.execute(q, self.view.channel.id)
        finally:
            await self.bot.db.release(connection)
        return await self.view.update(content=f"The transfer ticker for {self.view.channel.mention} was deleted.")


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, bot: 'Bot', leagues: List[str], items, row: int = 2):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.max_values = len(leagues)
        self.bot: Bot = bot

        for league, value in sorted(list(zip(leagues, items))):
            if len(league) > 100:
                trunc = league[:99]
                print(f"TRANSFERS: Remove_league dropdown Warning: {league} > 100 characters.\nTruncated to {trunc}")
                league = trunc

            self.add_option(label=league, value=value)

    async def callback(self, interaction: Interaction):
        """When a league is selected"""
        await interaction.response.defer()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """DELETE from transfers_leagues WHERE (channel_id, item) = ($1, $2)"""
                for x in self.values:
                    await connection.execute(q, self.view.channel.id, x)
        finally:
            await self.bot.db.release(connection)
        await self.view.update()


class TransfersConfig(View):
    """View for configuring Transfer Tickers"""

    def __init__(self, bot: 'Bot', interaction: Interaction, channel: TextChannel):
        self.interaction: Interaction = interaction
        self.channel: TextChannel = channel
        self.pages: List[Embed] = []
        self.index: int = 0
        self.bot: Bot = bot
        super().__init__()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.interaction.user.id == interaction.user.id

    async def creation_dialogue(self):
        """Send a dialogue to check if the user wishes to create a new ticker."""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                invalidate = await connection.fetchrow(q, self.channel.id)
                if invalidate:
                    return await self.bot.error(self.interaction, 'You cannot add a ticker to a livescores channel.')
        finally:
            await self.bot.db.release(connection)

        self.clear_items()
        view = Confirmation(self.interaction, colour_a=ButtonStyle.green, label_a=f"Create ticker", label_b="Cancel")
        notfound = f"{self.channel.mention} does not have a ticker, would you like to create one?"
        await self.bot.reply(self.interaction, content=notfound, view=view)
        await view.wait()

        if view.value:
            connection = await self.bot.db.acquire()

            try:
                q = """INSERT INTO transfers_channels (guild_id, channel_id) VALUES ($1,$2)"""
                async with connection.transaction():
                    await connection.execute(q, self.interaction.guild.id, self.channel.id)
                q = """INSERT INTO transfers_leagues (channel_id, item, alias) VALUES ($1, $2, $3) 
                ON CONFLICT DO NOTHING"""
                leagues = [(self.channel.id,) + i for i in LG]
                await connection.executemany(q, leagues)
            except Exception:
                traceback.print_exc()
                txt = f"Error occurred creating {self.channel.mention} ticker"
                return await self.bot.error(self.interaction, txt)
            else:
                return await self.update(content=f"A ticker was created for {self.channel.mention}")
            finally:
                await self.bot.db.release(connection)
        else:
            err = f"Cancelled ticker creation for {self.channel.mention}"
            self.stop()
            return await self.bot.error(self.interaction, err)

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def update(self, content: str = "") -> Message:
        """Push the latest version of the embed to view."""
        self.clear_items()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM transfers_channels WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.channel.id)
                qq = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
                records = await connection.fetch(qq, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        links = [f"[{r['alias']}]({r['item']})" for r in records]
        leagues = [r['alias'] for r in records]
        items = [r['item'] for r in records]

        if not leagues:
            self.add_item(ResetLeagues(self.bot))
            self.add_item(DeleteTicker(self.bot))
            e: Embed = Embed(title="Transfers Ticker config", color=Colour.dark_blue())
            e.description = f"{self.channel.mention} has no tracked leagues."
        else:
            e: Embed = Embed(title=f"{self.interaction.client.user.name} Transfer Ticker config",
                             color=Colour.dark_teal())
            e.set_thumbnail(url=self.interaction.guild.me.display_avatar.url)
            header = f'Tracked leagues for {self.channel.mention}\n'
            embeds = rows_to_embeds(e, sorted(links), header=header, max_rows=25)
            self.pages = embeds

            add_page_buttons(self)

            e = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                items = items[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]
                    items = items[:25]

            self.add_item(RemoveLeague(self.bot, leagues, items, row=1))

        if channel is None:
            return await self.creation_dialogue()

        await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class TransfersCog(Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        self.bot.transfers = self.transfers_loop.start()

    async def cog_unload(self) -> None:
        """Cancel transfers task on Cog Unload."""
        self.bot.transfers.cancel()

    async def _get_team_league(self, link) -> Competition:
        """Fetch additional data for parsed player"""
        async with self.bot.session.get(link) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        name = ''.join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/text()')).strip()
        link = ''.join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/@href'))

        link = TF + link if link else ""
        return Competition(name=name, link=link)

    @loop(seconds=60)
    async def transfers_loop(self) -> None:
        """Core transfer ticker loop - refresh every x seconds and get all new transfers from transfermarkt"""
        if self.bot.session is None:
            return

        async with self.bot.session.get(LOOP_URL) as resp:
            match resp.status:
                case 200:
                    pass
                case _:
                    print(f'Transfers: bad status: {resp.status}')
                    return
            tree = html.fromstring(await resp.text())

        skip_output = True if not self.bot.parsed_transfers else False
        for i in tree.xpath('.//div[@class="responsive-table"]/div/table/tbody/tr'):
            name = ''.join(i.xpath('.//td[1]//tr[1]/td[2]/a/text()')).strip()
            link = TF + ''.join(i.xpath('.//td[1]//tr[1]/td[2]/a/@href'))

            if not name or name in self.bot.parsed_transfers:
                continue  # skip when duplicate / void.
            else:
                self.bot.parsed_transfers.append(name)
                player = Player(name, link)

            # We don't need to output when populating after a restart.
            if skip_output:
                continue

            # Player Info
            player.age = ''.join(i.xpath('./td[2]//text()')).strip()
            player.position = ''.join(i.xpath('./td[1]//tr[2]/td/text()'))
            player.country = i.xpath('.//td[3]/img/@title')
            player.picture = ''.join(i.xpath('.//td[1]//tr[1]/td[1]/img/@src'))

            # Leagues & Fee
            team = ''.join(i.xpath('.//td[5]//td[2]/a/text()')).strip()
            team_link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[5]//td[2]/a/@href')).strip()

            league = await self._get_team_league(team_link)
            new_team = Team(name=team, link=team_link, league=league)
            new_team.country = ''.join(i.xpath('.//td[5]/table//tr[2]/td//img/@alt'))

            player.team = new_team

            team = ''.join(i.xpath('.//td[4]//td[2]/a/text()')).strip()
            team_link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[4]//td[2]/a/@href')).strip()

            league = await self._get_team_league(team_link)
            old_team = Team(name=team, link=team_link, league=league)
            old_team.country = ''.join(i.xpath('.//td[4]/table//tr[2]/td//img/@alt'))

            fee = ''.join(i.xpath('.//td[6]//a/text()'))
            fee_link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[6]//a/@href'))

            transfer = Transfer(player)
            transfer.old_team = old_team
            transfer.new_team = new_team
            transfer.fee = fee
            transfer.fee_link = fee_link

            connection = await self.bot.db.acquire()

            old_link = old_team.league.link if old_team.league is not None else None
            new_link = new_team.league.link if new_team.league is not None else None

            try:
                async with connection.transaction():
                    records = await connection.fetch("""
                    SELECT DISTINCT transfers_channels.channel_id
                    FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                    ON transfers_channels.channel_id = transfers_leagues.channel_id
                    WHERE item in ($1, $2)
                    """, old_link, new_link)
            finally:
                await self.bot.db.release(connection)

            for r in records:
                ch = self.bot.get_channel(r['channel_id'])
                if ch is None:
                    continue

                try:
                    await ch.send(embed=transfer.embed)
                except HTTPException:
                    pass

    @Cog.listener()
    async def on_guild_remove(self, guild) -> None:
        """Delete all transfer info for a guild from database upon leaving"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)

    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Delete all transfer info for a channel from database upon deletion"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)

    tf = Group(name="transfer_ticker",
               description="Create or manage a Transfer Ticker",
               default_permissions=Permissions(manage_channels=True))

    @tf.command()
    async def manage(self, interaction, channel: TextChannel = None) -> Message:
        """View the config of this channel's transfer ticker"""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        return await TransfersConfig(self.bot, interaction, channel).update()

    # TODO: Creation Dialogue from within add.
    @tf.command()
    @describe(league_name="Search for a league name")
    async def add(self, interaction: Interaction, league_name: str, channel: TextChannel = None):
        """Add a league to your transfer ticker channel(s)"""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM transfers_channels WHERE channel_id = $1"""
                r = await connection.fetchrow(q, channel.id)
        finally:
            await self.bot.db.release(connection)

        if r is None or r['channel_id'] is None:
            err = f"{channel.mention} does not have a transfer ticker set. Please make one first."
            return await self.bot.error(interaction, err)

        view = SearchView(self.bot, interaction, league_name, category='competition', fetch=True)
        await view.update()
        await view.wait()

        result = view.value

        if result is None:
            return

        alias = f"{result.flag} {result.name}"

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                         VALUES ($1, $2, $3)
                                         ON CONFLICT DO NOTHING""", channel.id, result.link, alias)
        await self.bot.db.release(connection)
        await self.bot.reply(interaction, content=f"✅ {alias} added to {channel.mention} tracker", view=None)


async def setup(bot: 'Bot'):
    """Load the transfer ticker cog into the bot"""
    await bot.add_cog(TransfersCog(bot))
