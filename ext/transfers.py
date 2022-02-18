"""Automated fetching of the latest football transfer information from transfermarkt"""
from discord import ButtonStyle, Interaction, Embed, Colour, NotFound, HTTPException, SlashCommandGroup
from discord.ext import commands, tasks
from discord.ui import View, Button, Select
from lxml import html

from ext.utils import transfer_tools, embed_utils, view_utils

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
        connection = await self.view.ctx.bot.db.acquire()
        async with connection.transaction():
            for alias, link in LG:
                await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                            VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                                         self.view.ctx.channel.id, link, alias)
        await self.view.ctx.bot.db.release(connection)
        await self.view.update(content=f"The tracked transfers for {self.view.ctx.channel.mention} were reset")


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self):
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction):
        """Click button reset leagues"""
        await interaction.response.defer()
        connection = await self.view.ctx.bot.db.acquire()
        async with connection.transaction():
            q = """DELETE FROM transfers_channels WHERE channel_id = $1"""
            await connection.execute(q, self.view.ctx.channel.id)
        await self.view.ctx.bot.db.release(connection)
        await self.view.update(content=f"The transfer ticker for {self.view.ctx.channel.mention} was deleted.")


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

        connection = await self.view.ctx.bot.db.acquire()
        async with connection.transaction():
            q = """DELETE from transfers_leagues WHERE (channel_id, item) = ($1, $2)"""
            for x in self.values:
                await connection.execute(q, self.view.ctx.channel.id, x)
        await self.view.ctx.bot.db.release(connection)
        await self.view.update()


class ConfigView(View):
    """View for configuring Transfer Tickers"""

    def __init__(self, ctx):
        self.index = 0
        self.ctx = ctx
        self.message = None
        self.pages = None
        self.settings = None
        super().__init__()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.ctx.author.id == interaction.user.id

    async def creation_dialogue(self):
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()
        view = view_utils.Confirmation(self.ctx, colour_a=ButtonStyle.green,
                                       label_a=f"Create ticker", label_b="Cancel")
        _ = f"{self.ctx.channel.mention} does not have a ticker, would you like to create one?"
        if self.message is None:
            self.message = await self.ctx.reply(content=_, view=view)
        else:
            await self.message.edit(content=_, view=view)
        await view.wait()

        if view.value:
            connection = await self.ctx.bot.db.acquire()
            try:
                async with connection.transaction():
                    await connection.execute("""INSERT INTO transfers_channels (guild_id, channel_id) VALUES ($1,$2)""",
                                             self.ctx.guild.id, self.ctx.channel.id)
                async with connection.transaction():
                    for alias, link in LG:
                        await connection.execute("""INSERT INTO transfers_leagues (channel_id, item, alias)
                                                    VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                                                 self.ctx.channel.id, link, alias)
            except Exception as err:
                await self.ctx.error(f"Error occurred creating {self.ctx.channel.mention} ticker", message=self.message)
                raise err
            finally:
                await self.ctx.bot.db.release(connection)
            await self.update(content=f"A ticker was created for {self.ctx.channel.mention}")
        else:
            await self.ctx.error(f"Cancelled ticker creation for {self.ctx.channel.mention}", message=self.message)
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

        connection = await self.ctx.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM transfers_channels WHERE channel_id = $1"""
                channel = await connection.fetchrow(q, self.ctx.channel.id)
                qq = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
                records = await connection.fetch(qq, self.ctx.channel.id)
        finally:
            await self.ctx.bot.db.release(connection)

        links = [f"[{r['alias']}]({r['item']})" for r in records]
        leagues = [r['alias'] for r in records]
        items = [r['item'] for r in records]

        if not leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            e = Embed(title="Transfers Ticker config", color=Colour.dark_blue())
            e.description = f"{self.ctx.channel.mention} has no tracked leagues."
        else:
            e = Embed(title="Toonbot Transfer Ticker config", color=Colour.dark_teal())
            e.set_thumbnail(url=self.ctx.me.display_avatar.url)
            header = f'Tracked leagues for {self.ctx.channel.mention}\n'
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
                self.message = await self.ctx.reply(content=content, embed=e, view=self)
            else:
                await self.message.edit(content=content, embed=e, view=self)


class Transfers(commands.Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot):
        self.bot = bot
        self.parsed = []
        self.bot.transfers = self.transfers_loop.start()
        self.warn_once = []
    
    def cog_unload(self):
        """Cancel transfers task on Cog Unload."""
        self.bot.transfers.cancel()

    async def _get_team_league(self, link):
        """Fetch additional data for parsed player"""
        async with self.bot.session.get(link) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        name = "".join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/text()')).strip()
        link = "".join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/@href'))

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

        skip_output = True if not self.parsed else False
        for i in tree.xpath('.//div[@class="responsive-table"]/div/table/tbody/tr'):
            name = "".join(i.xpath('.//td[1]//tr[1]/td[2]/a/text()')).strip()
            link = TF + "".join(i.xpath('.//td[1]//tr[1]/td[2]/a/@href'))

            if not name or name in self.parsed:
                continue  # skip when duplicate / void.
            else:
                self.parsed.append(name)
                player = transfer_tools.Player(name, link)

            # We don't need to output when populating after a restart.
            if skip_output:
                continue

            # Player Info
            player.age = "".join(i.xpath('./td[2]//text()')).strip()
            player.position = "".join(i.xpath('./td[1]//tr[2]/td/text()'))
            player.country = i.xpath('.//td[3]/img/@title')
            player.picture = "".join(i.xpath('.//td[1]//tr[1]/td[1]/img/@src'))

            # Leagues & Fee
            new_team = "".join(i.xpath('.//td[5]//td[2]/a/text()')).strip()
            new_team_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[5]//td[2]/a/@href')).strip()
            new_team = transfer_tools.Team(new_team, new_team_link)
            new_team.country = "".join(i.xpath('.//td[5]/table//tr[2]/td//img/@alt'))
            new_team.league, new_team.league_link = await self._get_team_league(new_team_link)

            player.team = new_team
            player.team_link = new_team_link

            old_team = "".join(i.xpath('.//td[4]//td[2]/a/text()')).strip()
            old_team_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[4]//td[2]/a/@href')).strip()

            old_team = transfer_tools.Team(old_team, old_team_link)
            old_team.country = "".join(i.xpath('.//td[4]/table//tr[2]/td//img/@alt'))
            old_team.league, old_team.league_link = await self._get_team_league(old_team_link)

            fee = "".join(i.xpath('.//td[6]//a/text()'))
            fee_link = "https://www.transfermarkt.co.uk" + "".join(i.xpath('.//td[6]//a/@href'))

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
                    """, old_team.league_link, new_team.league_link)
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

    transfers = SlashCommandGroup("transferticker", "Create or manage a Transfer Ticker")

    @transfers.command()
    async def manage(self, ctx):
        """View the config of this channel's transfer ticker"""
        if ctx.guild is None:
            return await ctx.error("This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            return await ctx.error("You need manage messages permissions to edit a ticker")

        await ConfigView(ctx).update()

    @transfers.command()
    async def add(self, ctx, league_name):
        """Add a league to your transfer ticker channel(s)"""
        if ctx.guild is None:
            return await ctx.error("This command cannot be ran in DMs")

        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            return await ctx.error("You need manage messages permissions to edit a ticker")

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow("""SELECT * FROM transfers_channels WHERE channel_id = $1""", ctx.channel.id)
        await self.bot.db.release(connection)

        if r is None or r['channel_id'] is None:
            return await ctx.error("This channel does not have a transfer ticker set. Please make one first.")

        view = transfer_tools.SearchView(ctx, league_name, category="Competitions", fetch=True)
        view.message = await ctx.reply(content=f"Fetching Leagues matching {league_name}", view=view)
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
                                        ON CONFLICT DO NOTHING""", ctx.channel.id, result.link, alias)
        await self.bot.db.release(connection)
        await view.message.edit(content=f"✅ {alias} added to {ctx.channel.mention} tracker", view=None)

    # @commands.Cog.listener()
    # async def on_guild_remove(self, guild):
    #     """Delete all transfer info for a guild from database upon leaving"""
    #     connection = await self.bot.db.acquire()
    #     async with connection.transaction():
    #         await connection.execute("""DELETE FROM transfers_channels WHERE guild_id = $1""", guild.id)
    #     await self.bot.db.release(connection)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Delete all transfer info for a channel from database upon deletion"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel.id)
        await self.bot.db.release(connection)


def setup(bot):
    """Load the transfer ticker cog into the bot"""
    bot.add_cog(Transfers(bot))
