"""Automated fetching of the latest football transfer information from transfermarkt"""
from discord import ButtonStyle, Interaction, Embed, Colour, NotFound, HTTPException, app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, Select
from lxml import html

from ext.utils import transfer_tools, embed_utils, view_utils
from ext.utils.transfer_tools import Competition

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


# TODO: Permissions Pass.


class ResetLeagues(Button):
    """Button to reset a transfer ticker back to its default leagues"""

    def __init__(self):
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.interaction.client.db.acquire()
        async with connection.transaction():
            for alias, link in LG:
                await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                            VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                                         self.view.interaction.channel.id, link, alias)
        await self.view.interaction.client.db.release(connection)
        await self.view.update(content=f"The tracked transfers for {self.view.interaction.channel.mention} were reset")


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self):
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.interaction.client.db.acquire()
        async with connection.transaction():
            q = """DELETE FROM transfers_channels WHERE channel_id = $1"""
            await connection.execute(q, self.view.interaction.channel.id)
        await self.view.interaction.client.db.release(connection)
        await self.view.update(content=f"The transfer ticker for {self.view.interaction.channel.mention} was deleted.")


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, leagues, items, row=2):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.max_values = len(leagues)
        for league, value in sorted(list(zip(leagues, items))):

            if len(league) > 100:
                trunc = league[:99]
                print(f"TRANSFERS: Remove_league dropdown Warning: {league} > 100 characters.\nTruncated to {trunc}")
                league = trunc

            self.add_option(label=league, value=value)

    async def callback(self, interaction: Interaction):
        """When a league is selected"""
        await interaction.response.defer()

        connection = await self.view.interaction.client.db.acquire()
        async with connection.transaction():
            q = """DELETE from transfers_leagues WHERE (channel_id, item) = ($1, $2)"""
            for x in self.values:
                await connection.execute(q, self.view.interaction.channel.id, x)
        await self.view.interaction.client.db.release(connection)
        await self.view.update()


class ConfigView(View):
    """View for configuring Transfer Tickers"""

    def __init__(self, interaction):
        self.index = 0
        self.interaction = interaction
        self.message = None
        self.pages = None
        self.settings = None
        super().__init__()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.interaction.user.id == interaction.user.id

    async def creation_dialogue(self):
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()
        view = view_utils.Confirmation(self.interaction, colour_a=ButtonStyle.green,
                                       label_a=f"Create ticker", label_b="Cancel")
        _ = f"{self.interaction.channel.mention} does not have a ticker, would you like to create one?"
        if self.message is None:
            self.message = await self.interaction.client.reply(self.interaction, content=_, view=view)
        else:
            await self.message.edit(content=_, view=view)
        await view.wait()

        if view.value:
            connection = await self.interaction.client.db.acquire()
            try:
                async with connection.transaction():
                    await connection.execute("""INSERT INTO transfers_channels (guild_id, channel_id) VALUES ($1,$2)""",
                                             self.interaction.guild.id, self.interaction.channel.id)
                async with connection.transaction():
                    for alias, link in LG:
                        await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                                    VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                                                 self.interaction.channel.id, link, alias)
            except Exception as err:
                txt = f"Error occurred creating {self.interaction.channel.mention} ticker"
                await self.interaction.client.error(self.interaction, txt, message=self.message)
                raise err
            finally:
                await self.interaction.client.db.release(connection)
            await self.update(content=f"A ticker was created for {self.interaction.channel.mention}")
        else:
            err = f"Cancelled ticker creation for {self.interaction.channel.mention}"
            await self.interaction.client.error(self.interaction, err, message=self.message)
            self.stop()

    async def on_timeout(self):
        """Hide menu on timeout."""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except NotFound:
            pass
        self.stop()

    async def update(self, content=""):
        """Push the latest version of the embed to view."""
        self.clear_items()

        connection = await self.interaction.client.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM transfers_channels WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.interaction.channel.id)
                qq = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
                records = await connection.fetch(qq, self.interaction.channel.id)
        finally:
            await self.interaction.client.db.release(connection)

        links = [f"[{r['alias']}]({r['item']})" for r in records]
        leagues = [r['alias'] for r in records]
        items = [r['item'] for r in records]

        if not leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            e = Embed(title="Transfers Ticker config", color=Colour.dark_blue())
            e.description = f"{self.interaction.channel.mention} has no tracked leagues."
        else:
            e = Embed(title="Toonbot Transfer Ticker config", color=Colour.dark_teal())
            e.set_thumbnail(url=self.interaction.guild.me.display_avatar.url)
            header = f'Tracked leagues for {self.interaction.channel.mention}\n'
            embeds = embed_utils.rows_to_embeds(e, sorted(links), header=header, rows_per=25)
            self.pages = embeds

            self.add_item(view_utils.PreviousButton(disabled=True if self.index == 0 else False))
            self.add_item(view_utils.PageButton(label=f"Page {self.index + 1} of {len(self.pages)}",
                                                disabled=True if len(self.pages) == 1 else False))
            self.add_item(view_utils.NextButton(disabled=True if self.index == len(self.pages) - 1 else False))
            self.add_item(view_utils.StopButton(row=0))

            e = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                items = items[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]
                    items = items[:25]

            self.add_item(RemoveLeague(leagues, items, row=1))

        if channel is None:
            return await self.creation_dialogue()

        else:
            if self.message is None:
                i = self.interaction
                self.message = await i.client.reply(i, content=content, embed=e, view=self)
            else:
                await self.message.edit(content=content, embed=e, view=self)


class TransfersCog(commands.Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.transfers = self.transfers_loop.start()

    def cog_unload(self):
        """Cancel transfers task on Cog Unload."""
        self.bot.transfers.cancel()

    async def _get_team_league(self, link):
        """Fetch additional data for parsed player"""
        async with self.bot.session.get(link) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        name = ''.join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/text()')).strip()
        link = ''.join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/@href'))

        link = TF + link if link else ""
        return name, link

    @tasks.loop(seconds=60)
    async def transfers_loop(self):
        """Core transfer ticker loop - refresh every x seconds and get all new transfers from transfermarkt"""
        _ = f'https://www.transfermarkt.co.uk/transfers/neuestetransfers/statistik?minMarktwert={MIN_MARKET_VALUE}'
        async with self.bot.session.get(_) as resp:
            if resp.status != 200:
                print(f'Transfers: received bad status: {resp.status}')
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
                player = transfer_tools.Player(name, link)

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

            lg, lg_link = await self._get_team_league(team_link)
            league = Competition(name=lg, link=lg_link)

            new_team = transfer_tools.Team(team, team_link, league)
            team.country = ''.join(i.xpath('.//td[5]/table//tr[2]/td//img/@alt'))

            player.team = new_team

            team = ''.join(i.xpath('.//td[4]//td[2]/a/text()')).strip()
            team_link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[4]//td[2]/a/@href')).strip()

            lg, lg_link = await self._get_team_league(team_link)
            league = Competition(name=lg, link=lg_link)
            old_team = transfer_tools.Team(team, team_link, league)
            old_team.country = ''.join(i.xpath('.//td[4]/table//tr[2]/td//img/@alt'))

            fee = ''.join(i.xpath('.//td[6]//a/text()'))
            fee_link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[6]//a/@href'))

            transfer = transfer_tools.Transfer(player)
            transfer.old_team = old_team
            transfer.new_team = new_team
            transfer.fee = fee
            transfer.fee_link = fee_link

            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    records = await connection.fetch("""
                    SELECT DISTINCT transfers_channels.channel_id
                    FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                    ON transfers_channels.channel_id = transfers_leagues.channel_id
                    WHERE item in ($1, $2)
                    """, old_team.league.link, new_team.league.link)
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

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete all transfer info for a guild from database upon leaving"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE guild_id = $1""", guild.id)
        await self.bot.db.release(connection)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Delete all transfer info for a channel from database upon deletion"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)

    tf = app_commands.Group(name="transfer_ticker", description="Create or manage a Transfer Ticker")

    @tf.command()
    async def manage(self, interaction):
        """View the config of this channel's transfer ticker"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_messages:
            return await self.bot.error(interaction, "You need manage messages permissions to edit a ticker")

        await ConfigView(interaction).update()

    @tf.command()
    @app_commands.describe(league_name="Search for a league name")
    async def add(self, interaction: Interaction, league_name: str):
        """Add a league to your transfer ticker channel(s)"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.manage_messages:
            return await self.bot.error(interaction, "You need manage messages permissions to edit a ticker")

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            q = """SELECT * FROM transfers_channels WHERE channel_id = $1"""
            r = await connection.fetchrow(q, interaction.channel.id)
        await self.bot.db.release(connection)

        if r is None or r['channel_id'] is None:
            err = "This channel does not have a transfer ticker set. Please make one first."
            return await self.bot.error(interaction, err)

        view = transfer_tools.SearchView(interaction, league_name, category="Competitions", fetch=True)
        await view.update()

        result = view.value

        if result is None:
            try:
                await view.message.delete()
            except HTTPException:
                pass
            return

        alias = f"{result.flag} {result.name}"

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                         VALUES ($1, $2, $3)
                                         ON CONFLICT DO NOTHING""", interaction.channel.id, result.link, alias)
        await self.bot.db.release(connection)
        await view.message.edit(content=f"✅ {alias} added to {interaction.channel.mention} tracker", view=None)


def setup(bot):
    """Load the transfer ticker cog into the bot"""
    bot.add_cog(TransfersCog(bot))
