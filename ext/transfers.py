"""Automated fetching of the latest football transfer information from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

from typing import TYPE_CHECKING, List, Dict, Optional, ClassVar

from asyncpg import ForeignKeyViolationError
from discord import ButtonStyle, Interaction, Embed, Colour, TextChannel, Permissions
from discord.app_commands import Group, describe
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View, Button, Select
from lxml import html
from typing_extensions import Self

from ext.ticker import IsLiveScoreError
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.transfer_tools import Player, Team, Competition, Transfer, SearchView, TransferResult, DEFAULT_LEAGUES
from ext.utils.view_utils import add_page_buttons, Confirmation

if TYPE_CHECKING:
    from core import Bot
    from discord import Guild, Message

TF = "https://www.transfermarkt.co.uk"
MIN_MARKET_VALUE = "200.000"
LOOP_URL = f'{TF}/transfers/neuestetransfers/statistik?minMarktwert={MIN_MARKET_VALUE}'


class TransferChannel:
    """An object representing a channel with a Transfer Ticker"""
    bot: ClassVar[Bot] = None

    def __init__(self, bot: 'Bot', channel: TextChannel) -> None:

        self.channel: TextChannel = channel
        self.leagues: List[Competition] = []  # Alias, Link
        self.dispatched: Dict[Transfer, Message] = {}

        if self.__class__.bot is None:
            self.__class__.bot = bot

    # Message dispatching
    async def dispatch(self, transfer: Transfer) -> Optional[Message]:
        """Dispatch a transfer to this channel"""
        # Do not send duplicate events.
        if transfer in self.dispatched:
            message = await self.dispatched[transfer].edit(embed=transfer.embed)
            return message

        leagues = [i.link for i in self.leagues]
        if transfer.old_team.league.link not in leagues:
            if transfer.new_team.league.link not in leagues:
                return None

        message = await self.channel.send(embed=transfer.embed)
        self.dispatched[transfer] = message
        return message

    # Database management
    async def get_leagues(self) -> List[Competition]:
        """Get the leagues needed for this channel"""
        sql = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        _ = [Competition(name=r['name'], country=r['country'], link=r['link']) for r in records]
        self.leagues = _
        return self.leagues

    async def create_ticker(self) -> Self:
        """Create a ticker for the channel"""
        connection = await self.bot.db.acquire()

        try:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                invalidate = await connection.fetchrow(sql, self.channel.id)
                if invalidate:
                    raise IsLiveScoreError

            # Create the ticker itself.
            sql = """INSERT INTO transfers_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            async with connection.transaction():
                await connection.execute(sql, self.channel.guild.id, self.channel.id)

        except ForeignKeyViolationError as e:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)"""
                await connection.execute(sql, self.channel.guild.id)
                raise e
        finally:
            await self.bot.db.release(connection)

        await self.reset_leagues()
        return self

    async def delete_ticker(self) -> None:
        """Delete the ticker channel from the database and remove it from the bots loop"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", self.channel.id)
        finally:
            await self.bot.db.release(connection)
        self.bot.transfer_channels.remove(self)

    async def add_leagues(self, leagues: List[Competition]) -> List[Competition]:
        """Add a list of leagues for the channel to the database"""
        sql = """INSERT INTO transfers_leagues (channel_id, name, country, link) 
        VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
        leagues = [i for i in leagues if i is not None]  # sanitise.

        if not leagues:
            return self.leagues

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, i.name, i.country, i.link) for i in leagues])
        finally:
            await self.bot.db.release(connection)

        self.leagues += [i for i in leagues if i not in self.leagues]
        return self.leagues

    async def remove_leagues(self, leagues: List[Competition]) -> List[Competition]:
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from transfers_leagues WHERE (channel_id, link) = ($1, $2)"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, x.link) for x in leagues])
        finally:
            await self.bot.db.release(connection)

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def reset_leagues(self) -> List[Competition]:
        """Reset the Ticker Channel to the list of default leagues."""
        sql = """INSERT INTO transfers_leagues (channel_id, name, country, link) VALUES ($1, $2, $3, $4)
                 ON CONFLICT DO NOTHING"""
        self.leagues = DEFAULT_LEAGUES
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute('''DELETE FROM transfers_leagues WHERE channel_id = $1''', self.channel.id)
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, x.name, x.country, x.link) for x in self.leagues])
        finally:
            await self.bot.db.release(connection)

        return self.leagues

    def view(self, interaction: Interaction) -> TransfersConfig:
        """A view representing the configuration of the TransferTicker"""
        return TransfersConfig(self.bot, interaction, self)


class ResetLeagues(Button):
    """Button to reset a transfer ticker back to its default leagues"""

    def __init__(self) -> None:
        super().__init__(label="Reset to default leagues", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        return await self.view.reset_leagues()


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=ButtonStyle.red)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        return await self.view.delete_ticker()


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, leagues: List[Competition], row: int = 2):
        super().__init__(placeholder="Remove tracked league(s)", row=row)
        self.leagues = leagues

        seen = set()
        unique = []
        for obj in leagues:
            if obj.link not in seen:
                unique.append(obj)
                seen.add(obj.link)

        self.max_values = len(unique)

        for i in unique:
            self.add_option(label=i.name[:100], value=i.link, emoji=i.flag)

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected"""
        await interaction.response.defer()
        return await self.view.remove_leagues([i for i in self.leagues if i.link in self.values])


class TransfersConfig(View):
    """View for configuring Transfer Tickers"""
    bot: Bot = None

    def __init__(self, bot: 'Bot', interaction: Interaction, tc: TransferChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.tc: TransferChannel = tc
        self.index: int = 0
        self.pages: List[Embed] = []

        if self.__class__.bot is None:
            self.__class__.bot = bot

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def remove_leagues(self, leagues: List[Competition]) -> Message:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = '\n'.join([f"{i.flag} {i.name}" for i in sorted(leagues, key=lambda x: x.name)])
        txt = f"Remove these leagues from {self.tc.channel.mention}? {lg_text}"
        await self.bot.reply(self.interaction, content=txt, embed=None, view=view)
        await view.wait()

        if not view.value:
            return await self.update(content="No leagues were removed")

        await self.tc.remove_leagues(leagues)
        return await self.update(content=f"Removed {self.tc.channel.mention} tracked leagues: {lg_text}")

    async def reset_leagues(self) -> Message:
        """Reset the leagues for this channel"""
        await self.tc.reset_leagues()
        return await self.update(content=f"The Tracked leagues for {self.tc.channel.mention} reset")

    async def creation_dialogue(self) -> bool:
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()

        # Ticker Verify -- NOT A SCORES CHANNEL
        if self.tc.channel.id in [i.channel.id for i in self.bot.score_channels]:
            await self.bot.error(self.interaction, content='You cannot create a ticker in a livescores channel.')
            return False

        view = Confirmation(self.interaction, colour_a=ButtonStyle.green, label_a=f"Create ticker", label_b="Cancel")
        notfound = f"{self.tc.channel.mention} does not have a ticker, would you like to create one?"
        await self.bot.reply(self.interaction, content=notfound, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {self.tc.channel.mention}"
            view.clear_items()
            view.clear_items()
            await self.bot.error(self.interaction, txt, view=view)
            return False

        try:
            try:
                await self.tc.create_ticker()
            # We have code to handle the ForeignKeyViolation within create_ticker, so rerun it.
            except ForeignKeyViolationError:
                await self.tc.create_ticker()
        except IsLiveScoreError:
            await self.bot.error(self.interaction, content='You cannot add tickers to a livescores channel.',
                                 view=None)
            return False

        await self.update(content=f"A ticker was created for {self.tc.channel.mention}")
        return True

    async def delete_ticker(self) -> Message:
        """Delete the ticker for this channel."""
        await self.tc.delete_ticker()
        return await self.bot.reply(self.interaction, view=None,
                                    content=f"The transfer ticker for {self.tc.channel.mention} was deleted.")

    async def update(self, content: str = "") -> Message:
        """Push the latest version of the embed to view."""
        self.clear_items()

        if not self.tc.leagues:
            await self.tc.get_leagues()

        leagues = self.tc.leagues
        markdowns = [f"{i.flag} {i.country}: {i.markdown}" for i in sorted(leagues, key=lambda x: x.name)]
        e: Embed = Embed(title="Toonbot Transfers Ticker config", color=Colour.dark_blue())
        e.set_thumbnail(url=self.bot.user.display_avatar.url)

        missing = []
        perms = self.tc.channel.permissions_for(self.tc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = "```yaml\nThis transfers channel will not work currently, I am missing the following permissions.\n"
            e.add_field(name='Missing Permissions', value=f"{v} {missing}```")

        if not leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            e.description = f"{self.tc.channel.mention} has no tracked leagues."
        else:
            header = f'Tracked leagues for {self.tc.channel.mention}\n'
            embeds = rows_to_embeds(e, markdowns, header=header, max_rows=25)
            self.pages = embeds

            add_page_buttons(self, row=4)

            e = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues, row=0))
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class TransfersCog(Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

        if TransferResult.bot is None:
            TransferResult.bot = bot
        if SearchView.bot is None:
            SearchView.bot = bot

    async def cog_load(self) -> None:
        """Load the transfer channels on cog load."""
        self.bot.transferrs = self.transfers_loop.start()

    async def cog_unload(self) -> None:
        """Cancel transfers task on Cog Unload."""
        self.bot.transfers.cancel()

    async def update_cache(self) -> List[TransferChannel]:
        """Load Transfer Channels into the bot."""
        sql = f"""SELECT * FROM transfers_channels"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch(sql)
        finally:
            await self.bot.db.release(connection)

        # Purge dead
        cached = set([r['channel_id'] for r in records])
        for tc in self.bot.transfer_channels.copy():
            if tc.channel.id not in cached:
                self.bot.transfer_channels.remove(tc)

        # Bring in new
        missing = [i for i in cached if i not in [tc.channel.id for tc in self.bot.transfer_channels]]
        for cid in missing:
            channel = self.bot.get_channel(cid)
            if channel is None:
                continue

            tc = TransferChannel(self.bot, channel)
            await tc.get_leagues()
            self.bot.transfer_channels.append(tc)
        return self.bot.transfer_channels

    async def _get_team_league(self, link) -> Competition:
        """Fetch additional data for parsed player"""
        async with self.bot.session.get(link) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        name = ''.join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/text()')).strip()
        link = ''.join(tree.xpath('.//div[@class="dataZusatzbox"]//span[@class="hauptpunkt"]/a/@href'))

        link = TF + link if link else ""
        return Competition(name=name, link=link)

    # Core Loop
    @loop(minutes=1)
    async def transfers_loop(self) -> None:
        """Core transfer ticker loop - refresh every x seconds and get all new transfers from transfermarkt"""
        if self.bot.db is None:
            return
        if self.bot.session is None:
            return
        if not self.bot.guilds:
            return

        if not self.bot.transfer_channels:
            return await self.update_cache()

        async with self.bot.session.get(LOOP_URL) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    raise ValueError(f'Transfers: bad status: {resp.status}')

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
            player.picture = ''.join(i.xpath('.//img/@data-src'))

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

            transfer = Transfer(player=player, fee=fee, old_team=old_team, new_team=new_team, fee_link=fee_link)
            transfer.generate_embed()
            old_link = old_team.league.link if old_team.league is not None else None
            new_link = new_team.league.link if new_team.league is not None else None

            # Fetch the list of channels to output the transfer to.
            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    records = await connection.fetch("""
                    SELECT DISTINCT transfers_channels.channel_id
                    FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                    ON transfers_channels.channel_id = transfers_leagues.channel_id
                    WHERE link in ($1, $2)
                    """, old_link, new_link)
            finally:
                await self.bot.db.release(connection)

            for r in records:
                try:
                    tc = next(i for i in self.bot.transfer_channels if r['channel_id'] == i.channel.id)
                except StopIteration:
                    channel = self.bot.get_channel(r['channel_id'])
                    if channel is None:
                        continue
                    tc = TransferChannel(self.bot, channel)
                    self.bot.transfer_channels.append(tc)
                await tc.dispatch(transfer)

    tf = Group(name="transfer_ticker",
               description="Create or manage a Transfer Ticker",
               default_permissions=Permissions(manage_channels=True))

    @tf.command()
    @describe(channel="Manage which channel?")
    async def manage(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """View the config of this channel's transfer ticker"""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        # Validate channel is a ticker channel.
        try:
            tc = next(i for i in self.bot.transfer_channels if i.channel.id == channel.id)
            return await tc.view(interaction).update()
        except StopIteration:
            tc = TransferChannel(self.bot, channel)
            success = await tc.view(interaction).creation_dialogue()
            if success:
                self.bot.transfer_channels.append(tc)

    @tf.command()
    @describe(league_name="Search for a league name")
    async def add(self, interaction: Interaction, league_name: str, channel: TextChannel = None) -> Message:
        """Add a league to your transfer ticker channel(s)"""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        # Validate channel is a ticker channel.
        try:
            tc = next(i for i in self.bot.transfer_channels if i.channel.id == channel.id)
        except StopIteration:
            tc = TransferChannel(self.bot, channel)
            success = await tc.view(interaction).creation_dialogue()
            if not success:
                return

            self.bot.transfer_channels.append(tc)

        view = SearchView(interaction, league_name, category='competition', fetch=True)
        await view.update()
        await view.wait()

        result = view.value

        if result is None:
            return await self.bot.reply(interaction, content="Your channel was not modified.")

        await tc.add_leagues([result])
        return await tc.view(interaction).update(f"{result.flag} {result.name} added to {tc.channel.mention} tracker")

    # Database Cleanup
    @Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
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


async def setup(bot: 'Bot'):
    """Load the transfer ticker cog into the bot"""
    await bot.add_cog(TransfersCog(bot))
