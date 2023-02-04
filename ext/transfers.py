"""Automated fetching of the latest football transfer information from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import logging
from importlib import reload
from typing import TYPE_CHECKING, ClassVar

from asyncpg import ForeignKeyViolationError
from discord import ButtonStyle, Interaction, Embed, Colour, TextChannel, Permissions, HTTPException
from discord.app_commands import Group, describe
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View, Button, Select
from lxml import html

import ext.toonbot_utils.transfermarkt as tfm
from ext.ticker import IsLiveScoreError
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.view_utils import Confirmation, Previous, Jump, Stop, Next

if TYPE_CHECKING:
    from core import Bot
    from discord import Message

TF = "https://www.transfermarkt.co.uk"
MIN_MARKET_VALUE = "200.000"
LOOP_URL = f'{TF}/transfers/neuestetransfers/statistik?minMarktwert={MIN_MARKET_VALUE}'


class TransferChannel:
    """An object representing a channel with a Transfer Ticker"""
    bot: ClassVar[Bot] = None

    def __init__(self, channel: TextChannel) -> None:

        self.channel: TextChannel = channel
        self.leagues: list[tfm.Competition] = []

    # Database management
    async def get_leagues(self) -> list[tfm.Competition]:
        """Get the leagues needed for this channel"""
        sql = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)

        self.leagues = [tfm.Competition(name=r['name'], country=r['country'], link=r['link']) for r in records]
        return self.leagues

    async def create_ticker(self) -> TransferChannel:
        """Create a ticker for the channel"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                # Create the ticker itself.
                if not await connection.fetchrow("""SELECT * FROM scores_channels WHERE channel_id = $1""",
                                                 self.channel.id):
                    await connection.execute("""INSERT INTO guild_settings (guild_id) VALUES ($1) 
                                                ON CONFLICT DO NOTHING""", self.channel.guild.id)
                    await connection.execute("""INSERT INTO transfers_channels (guild_id, channel_id) VALUES ($1, $2) 
                                                ON CONFLICT DO NOTHING""", self.channel.guild.id, self.channel.id)

        if invalidate:
            raise IsLiveScoreError

        await self.reset_leagues()
        return self

    async def delete_ticker(self) -> None:
        """Delete the ticker channel from the database and remove it from the bots loop"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", self.channel.id)

        self.bot.transfer_channels = [i for i in self.bot.transfer_channels if i is not self]

    async def add_leagues(self, leagues: list[tfm.Competition]) -> list[tfm.Competition]:
        """Add a list of leagues for the channel to the database"""
        leagues = filter(None, leagues)

        for i in leagues:
            try:
                i.country = next(iter(i.country))
            except StopIteration:
                i.country = None

        if not leagues:
            return self.leagues

        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                sql = """INSERT INTO transfers_leagues (channel_id, name, country, link) 
                         VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
                await connection.executemany(sql, [(self.channel.id, i.name, i.country, i.link) for i in leagues])

        self.leagues += [i for i in leagues if i not in self.leagues]
        return self.leagues

    async def remove_leagues(self, leagues: list[tfm.Competition]) -> list[tfm.Competition]:
        """Remove a list of leagues for the channel from the database"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                sql = """DELETE from transfers_leagues WHERE (channel_id, link) = ($1, $2)"""
                await connection.executemany(sql, [(self.channel.id, x.link) for x in leagues])

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def reset_leagues(self) -> list[tfm.Competition]:
        """Reset the Ticker Channel to the list of default leagues."""
        sql = """INSERT INTO transfers_leagues (channel_id, name, country, link) VALUES ($1, $2, $3, $4)
                 ON CONFLICT DO NOTHING"""

        fields = [(self.channel.id, x.name, x.country, x.link) for x in tfm.DEFAULT_LEAGUES]
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute('''DELETE FROM transfers_leagues WHERE channel_id = $1''', self.channel.id)
                await connection.executemany(sql, fields)

        self.leagues = tfm.DEFAULT_LEAGUES
        return self.leagues

    def view(self, interaction: Interaction) -> TransfersConfig:
        """A view representing the configuration of the TransferTicker"""
        return TransfersConfig(interaction, self)


class ResetLeagues(Button):
    """Button to reset a transfer ticker back to its default leagues"""

    def __init__(self) -> None:
        super().__init__(label="Reset Ticker", style=ButtonStyle.primary, row=1)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.reset_leagues()
        self.view.interaction = interaction


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=ButtonStyle.red, row=1)

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        await interaction.response.defer()
        await self.view.delete_ticker()
        self.view.interaction = interaction


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    def __init__(self, leagues: list[tfm.Competition], row: int = 2):
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
    bot: ClassVar[Bot] = None

    def __init__(self, interaction: Interaction, tc: TransferChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.tc: TransferChannel = tc
        self.index: int = 0
        self.pages: list[Embed] = []

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.interaction.delete_original_response()

    async def remove_leagues(self, leagues: list[tfm.Competition]) -> Message:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        lg_text = '\n'.join([f"{i.flag} {i.country}: {i.markdown}" for i in sorted(leagues, key=lambda x: x.name)])

        e = Embed(colour=Colour.red(), description=f"Remove leagues from {self.tc.channel.mention}?\n\n{lg_text}")
        await self.bot.reply(self.interaction, embed=e, view=view)
        await view.wait()

        if view.value:
            e.title = "Transfer Ticker Leagues Removed"
            e.description = f"{self.tc.channel.mention}\n\n{lg_text}"
            await self.tc.remove_leagues(leagues)
            u = self.interaction.user
            e.set_footer(text=f"{u} ({u.id})", icon_url=u.avatar.url)
        else:
            e.description = "No leagues were removed"

        await self.interaction.followup.send(embed=e)
        return await self.update()

    async def reset_leagues(self) -> Message:
        """Reset the leagues for this channel"""
        await self.tc.reset_leagues()
        e = Embed(title="Transfer Ticker Reset", description=self.tc.channel.mention, colour=Colour.blurple())
        e.set_footer(text=f"Action performed by {self.interaction.user} ({self.interaction.user.id})",
                     icon_url=self.interaction.user.avatar.url)

        await self.interaction.followup.send(embed=e)
        return await self.update()

    async def creation_dialogue(self) -> bool:
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()

        # Ticker Verify -- NOT A SCORES CHANNEL
        if self.tc.channel.id in [i.channel.id for i in self.bot.score_channels]:
            await self.bot.error(self.interaction, content='You cannot create a ticker in a livescores channel.')
            return False

        view = Confirmation(self.interaction, colour_a=ButtonStyle.green, label_a=f"Create ticker", label_b="Cancel")

        e = Embed(title="Create Transfer Ticker", description=f"{self.tc.channel.mention} does not have a ticker, "
                                                              f"would you like to create one?")
        await self.bot.reply(self.interaction, embed=e, view=view)
        await view.wait()

        if not view.value:
            await self.bot.error(self.interaction, f"Ticker creation cancelled")
            return False

        try:
            try:
                await self.tc.create_ticker()
            # We have code to handle the ForeignKeyViolation within create_ticker, so rerun it.
            except ForeignKeyViolationError:
                await self.tc.create_ticker()
        except IsLiveScoreError:
            await self.bot.error(self.interaction, content='You cannot add tickers to a livescores channel.', view=None)
            return False

        e = Embed(title="Transfer Ticker Created", colour=Colour.green(), description=f"{self.tc.channel.mention}")

        u = self.interaction.user
        e.set_footer(text=f"{u} ({u.id})", icon_url=u.avatar.url)

        await self.interaction.followup.send(embed=e)
        return await self.update()

    async def delete_ticker(self) -> Message:
        """Delete the ticker for this channel."""
        await self.tc.delete_ticker()
        view = Confirmation(self.interaction, "Confirm Deletion", "Cancel", ButtonStyle.red)
        e = Embed(colour=Colour.red(), description=f"Are you sure you wish to delete the transfer ticker from "
                                                   f"{self.tc.channel.mention}?\n\nThis action cannot be undone.")
        await self.bot.reply(self.interaction, embed=e, view=view)
        await view.wait()

        if view.value:
            e = Embed(title="Transfer Ticker Deleted", colour=Colour.red())
            e.set_footer(text=f"Action performed by: {self.interaction.user} ({self.interaction.user.id})",
                         icon_url=self.interaction.user.avatar.url)
            await self.interaction.followup.send(embed=e)
            return await self.interaction.delete_original_response()
        else:
            e = Embed(title="Transfer Ticker Deletion Cancelled")
            m = await self.interaction.followup.send(embed=e)
            await asyncio.sleep(5)
            return await m.delete()

    async def update(self) -> Message:
        """Push the latest version of the embed to view."""
        self.clear_items()

        if not self.tc.leagues:
            await self.tc.get_leagues()

        leagues = self.tc.leagues
        markdowns = [f"{i.flag} {i.country}: {i.markdown}" for i in sorted(leagues, key=lambda x: x.name)]
        e: Embed = Embed(title="Transfers Ticker config", color=Colour.dark_blue())

        missing = []
        perms = self.tc.channel.permissions_for(self.tc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = "```yaml\nThis transfers channel will not work currently, I am missing the following permissions.\n"
            e.add_field(name='Missing Permissions', value=f"{v} {missing}```")

        self.add_item(ResetLeagues())
        self.add_item(DeleteTicker())
        if not leagues:
            e.description = f"{self.tc.channel.mention} has no tracked leagues."
        else:
            header = f'Tracked leagues for {self.tc.channel.mention}\n'
            embeds = rows_to_embeds(e, markdowns, header=header, rows=25)
            self.pages = embeds

            e = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25:]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues, row=0))

        if len(self.pages) > 1:
            self.add_item(Previous(row=2, disabled=self.index == 0))
            self.add_item(Jump(row=2, label=f"Page {self.index + 1} of {len(self.pages)}", disabled=self.pages < 3))
            self.add_item(Next(row=2, disabled=self.index + 1 >= len(self.pages)))
            self.add_item(Stop(row=2))
        else:
            self.add_item(Stop(row=1))

        return await self.bot.reply(self.interaction, embed=e, view=self)


class Transfers(Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        TransferChannel.bot = bot
        TransfersConfig.bot = bot
        reload(tfm)

    async def cog_load(self) -> None:
        """Load the transfer channels on cog load."""
        self.bot.transfer_channels.clear()
        self.bot.transfers = self.transfers_loop.start()

    async def cog_unload(self) -> None:
        """Cancel transfers task on Cog Unload."""
        self.bot.transfers.cancel()

    async def update_cache(self) -> list[TransferChannel]:
        """Load Transfer Channels into the bot."""
        sql = f"""SELECT * FROM transfers_channels"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

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

            tc = TransferChannel(channel)
            await tc.get_leagues()
            self.bot.transfer_channels.append(tc)
        return self.bot.transfer_channels

    # Core Loop
    @loop(minutes=1)
    async def transfers_loop(self) -> None:
        """Core transfer ticker loop - refresh every minute and get all new transfers from transfermarkt"""
        if self.bot.db is None:
            return
        if self.bot.session is None:
            return
        if not self.bot.guilds:
            return

        if not self.bot.transfer_channels:
            logging.error("Transfer Loop - No transfer_channels found.")
            return await self.update_cache()

        async with self.bot.session.get(LOOP_URL) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    logging.error(f'Transfers: bad status: {resp.status}')
                    return

        skip_output = True if not self.bot.parsed_transfers else False

        transfers = tree.xpath('.//div[@class="responsive-table"]/div/table/tbody/tr')
        for i in transfers:
            if not (name := ''.join(i.xpath('.//td[1]//tr[1]/td[2]/a/text()')).strip()):
                continue
            if name in self.bot.parsed_transfers:
                continue  # skip when duplicate / void.
            else:
                self.bot.parsed_transfers.append(name)

            # We don't need to output when populating after a restart.
            if skip_output:
                continue

            link = TF + ''.join(i.xpath('.//td[1]//tr[1]/td[2]/a/@href'))

            player = tfm.Player(name, link)

            # Box 1 - Player Info
            player.picture = ''.join(i.xpath('.//img/@data-src'))

            player.position = ''.join(i.xpath('./td[1]//tr[2]/td/text()'))

            # Box 2 - Age
            player.age = ''.join(i.xpath('./td[2]//text()')).strip()

            # Box 3 - Country
            player.country = i.xpath('.//td[3]/img/@title')

            transfer = tfm.Transfer(player=player)

            # Box 4 - Old Team
            team = ''.join(i.xpath('.//td[4]//img[@class="tiny_wappen"]//@title'))
            team_link = TF + ''.join(i.xpath('.//td[4]//img[@class="tiny_wappen"]/parent::a/@href'))

            league = ''.join(i.xpath('.//td[4]//img[@class="flaggenrahmen"]/following-sibling::a/@title'))
            if league:
                league_link = TF + ''.join(i.xpath('.//td[4]//img[@class="flaggenrahmen"]/following-sibling::a/@href'))
            else:
                league = ''.join(i.xpath('.//td[4]//img[@class="flaggenrahmen"]/parent::div/text()'))
                league_link = ''

            country = ''.join(i.xpath('.//td[4]//img[@class="flaggenrahmen"]/@alt'))

            old_league = tfm.Competition(name=league, link=league_link, country=country)
            old_team = tfm.Team(name=team, link=team_link, league=old_league, country=country)

            transfer.old_team = old_team

            # Box 5 - New Team
            team = ''.join(i.xpath('.//td[5]//img[@class="tiny_wappen"]//@title'))
            team_link = TF + ''.join(i.xpath('.//td[5]//img[@class="tiny_wappen"]/parent::a/@href'))

            league = ''.join(i.xpath('.//td[5]//img[@class="flaggenrahmen"]/following-sibling::a/@title'))
            if league:
                league_link = TF + ''.join(i.xpath('.//td[5]//img[@class="flaggenrahmen"]/following-sibling::a/@href'))
            else:
                league = ''.join(i.xpath('.//td[5]//img[@class="flaggenrahmen"]/parent::div/text()'))
                league_link = ''

            country = ''.join(i.xpath('.//td[5]//img[@class="flaggenrahmen"]/@alt'))

            new_league = tfm.Competition(name=league, link=league_link, country=country)
            new_team = tfm.Team(name=team, link=team_link, league=new_league, country=country)

            transfer.new_team = new_team
            player.team = new_team

            # Box 6 - Leagues & Fee
            transfer.fee = ''.join(i.xpath('.//td[6]//a/text()'))
            transfer.fee_link = "https://www.transfermarkt.co.uk" + ''.join(i.xpath('.//td[6]//a/@href'))

            try:
                old_link = old_league.link.replace('transfers', 'startseite').split('/saison_id')[0]
            except IndexError:
                old_link = old_league.link.replace('transfers', 'startseite')

            try:
                new_link = new_league.link.replace('transfers', 'startseite').split('/saison_id')[0]
            except IndexError:
                new_link = new_league.link.replace('transfers', 'startseite')

            # Fetch the list of channels to output the transfer to.
            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    records = await connection.fetch("""
                                SELECT DISTINCT transfers_channels.channel_id
                                FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                                ON transfers_channels.channel_id = transfers_leagues.channel_id
                                WHERE link in ($1, $2)""", old_link, new_link)

            if records:
                e = transfer.generate_embed()
            else:
                continue

            for r in records:
                channel = self.bot.get_channel(r['channel_id'])

                if channel is None:
                    continue

                try:
                    await channel.send(embed=e)
                except HTTPException:
                    continue

    tf = Group(name="transfer_ticker",
               description="Create or manage a Transfer Ticker",
               default_permissions=Permissions(manage_channels=True))

    @tf.command(name="manage")
    @describe(channel="Manage which channel?")
    async def manage_transfers(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """View the config of this channel's transfer ticker"""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        # Validate channel is a ticker channel.
        try:
            tc = next(i for i in self.bot.transfer_channels if i.channel.id == channel.id)
            return await tc.view(interaction).update()
        except StopIteration:
            tc = TransferChannel(channel)
            if await tc.view(interaction).creation_dialogue():
                self.bot.transfer_channels.append(tc)

    @tf.command(name="add_league")
    @describe(league_name="Search for a league name")
    async def add_league_tf(self, interaction: Interaction, league_name: str, channel: TextChannel = None) -> Message:
        """Add a league to your transfer ticker channel(s)"""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        # Validate channel is a ticker channel.
        try:
            tc = next(i for i in self.bot.transfer_channels if i.channel.id == channel.id)
        except StopIteration:
            if not await (tc := TransferChannel(channel)).view(interaction).creation_dialogue():
                return

            self.bot.transfer_channels.append(tc)

        view = tfm.CompetitionSearch(interaction, league_name, fetch=True)
        await view.update()
        await view.wait()

        result = view.value

        e = Embed(title="Transfer Ticker")
        if result is None:
            e.colour = Colour.red()
            e.description = "Your channel was not modified."
        else:
            await tc.add_leagues([result])
            e.colour = Colour.green()
            e.title = "Transfer Ticker League Added"
            e.description = f"{tc.channel.mention}\n\n{result.flag} {result.country}: {result.markdown}"
            u = interaction.user
            e.set_footer(text=f"{u} ({u.id})", icon_url=u.avatar.url)

        return await interaction.edit_original_response(embed=e)

    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Delete all transfer info for a channel from database upon deletion"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                log = await connection.execute("""DELETE FROM transfers_channels WHERE channel_id = $1""", channel.id)
                logging.info(f"Transfer Channel {channel.id}: {log}")


async def setup(bot: Bot):
    """Load the transfer ticker cog into the bot"""
    await bot.add_cog(Transfers(bot))
