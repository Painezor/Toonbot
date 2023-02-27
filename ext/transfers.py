"""Automated fetching of the latest football transfer
   information from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import logging
from importlib import reload
from typing import TYPE_CHECKING, ClassVar, Optional
import typing

from discord import (
    ButtonStyle,
    Embed,
    Colour,
    TextChannel,
    Permissions,
    HTTPException,
)
import discord
from discord.app_commands import Group, describe
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import Button, Select
from lxml import html

import ext.toonbot_utils.transfermarkt as tfm
from ext.ticker import IsLiveScoreError
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.view_utils import (
    Confirmation,
    Previous,
    Jump,
    Stop,
    Next,
    BaseView,
)

if TYPE_CHECKING:
    from core import Bot
    from discord import Message, Interaction

TF = "https://www.transfermarkt.co.uk"
MIN_MARKET_VALUE = "?minMarktwert=200.000"
LOOP_URL = f"{TF}/transfers/neuestetransfers/statistik{MIN_MARKET_VALUE}"

logger = logging.getLogger("Transfers")
logger.setLevel(logging.DEBUG)


class TransferChannel:
    """An object representing a channel with a Transfer Ticker"""

    bot: ClassVar[Bot]

    def __init__(self, channel: TextChannel) -> None:
        self.channel: TextChannel = channel
        self.leagues: list[tfm.Competition] = []

    # Database management
    async def get_leagues(self) -> list[tfm.Competition]:
        """Get the leagues needed for this channel"""
        sql = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)

        self.leagues = [
            tfm.Competition(
                name=r["name"], country=r["country"], link=r["link"]
            )
            for r in records
        ]
        return self.leagues

    async def create_ticker(self) -> TransferChannel:
        """Create a ticker for the channel"""
        async with self.bot.db.acquire(timeout=60) as c:
            async with c.transaction():
                # Create the ticker itself.
                sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                if await c.fetchrow(sql, self.channel.id):
                    raise IsLiveScoreError
                else:
                    sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                             ON CONFLICT DO NOTHING"""
                    await c.execute(sql, self.channel.guild.id)
                    sql = """INSERT INTO transfers_channels
                             (guild_id, channel_id)
                             VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                    ch = self.channel
                    await c.execute(sql, ch.guild.id, ch.id)
        await self.reset_leagues()
        return self

    async def delete_ticker(self) -> None:
        """Delete the ticker channel from the database and
        remove it from the bots loop"""
        sql = """DELETE FROM transfers_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.channel.id)

        tc = self.bot.transfer_channels
        self.bot.transfer_channels = [i for i in tc if i is not self]

    async def add_leagues(self, leagues: list[tfm.Competition]) -> None:
        """Add a list of leagues for the channel to the database"""
        rows = []
        for i in leagues:
            if isinstance(i.country, list):
                ctr = i.country[0]
            else:
                ctr = i.country
            rows.append((self.channel.id, i.name, ctr, i.link))
            self.leagues.append(i)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO transfers_leagues
                         (channel_id, name, country, link)
                         VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
                await connection.executemany(sql, rows)

        self.leagues += [i for i in leagues if i not in self.leagues]

    async def remove_leagues(
        self, leagues: list[tfm.Competition]
    ) -> list[tfm.Competition]:
        """Remove a list of leagues for the channel from the database"""
        sql = """DELETE from transfers_leagues
                 WHERE (channel_id, link) = ($1, $2)"""
        rows = [(self.channel.id, x.link) for x in leagues]
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)
        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def reset_leagues(self) -> list[tfm.Competition]:
        """Reset the Ticker Channel to the list of default leagues."""
        sql_1 = """DELETE FROM transfers_leagues WHERE channel_id = $1"""
        sql_2 = """INSERT INTO transfers_leagues
                 (channel_id, name, country, link) VALUES ($1, $2, $3, $4)
                 ON CONFLICT DO NOTHING"""

        lg = tfm.DEFAULT_LEAGUES
        fields = [(self.channel.id, x.name, x.country, x.link) for x in lg]
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql_1, self.channel.id)
                await connection.executemany(sql_2, fields)

        self.leagues = lg
        return self.leagues

    def view(self, interaction: Interaction[Bot]) -> TransfersConfig:
        """A view representing the configuration of the TransferTicker"""
        return TransfersConfig(interaction, self)


class ResetLeagues(Button):
    """Button to reset a transfer ticker back to its default leagues"""

    view: TransfersConfig

    def __init__(self) -> None:
        super().__init__(
            label="Reset Ticker", style=ButtonStyle.primary, row=1
        )

    async def callback(self, interaction: Interaction[Bot]) -> None:
        """Click button reset leagues"""

        await interaction.response.defer()
        await self.view.reset_leagues()
        self.view.interaction = interaction


class DeleteTicker(Button):
    """Button to delete a ticker entirely"""

    view: TransfersConfig

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=ButtonStyle.red, row=1)

    async def callback(self, interaction: Interaction[Bot]) -> None:
        """Click button reset leagues"""

        await interaction.response.defer()
        await self.view.delete_ticker()
        self.view.interaction = interaction


class RemoveLeague(Select):
    """Dropdown to remove leagues from a match event ticker."""

    view: TransfersConfig

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

    async def callback(self, interaction: Interaction) -> None:
        """When a league is selected"""

        await interaction.response.defer()
        leagues = [i for i in self.leagues if i.link in self.values]
        await self.view.remove_leagues(leagues)


class TransfersConfig(BaseView):
    """View for configuring Transfer Tickers"""

    def __init__(self, interaction: Interaction[Bot], tc: TransferChannel):
        super().__init__(interaction)
        self.tc: TransferChannel = tc

    async def on_timeout(self) -> None:
        """Hide menu on timeout."""
        try:
            await self.interaction.delete_original_response()
        except discord.NotFound:
            pass

    async def remove_leagues(self, leagues: list[tfm.Competition]) -> None:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(
            self.interaction, "Remove", "Cancel", discord.ButtonStyle.red
        )

        lg_text = "\n".join(
            [
                f"{i.flag} {i.country}: {i.markdown}"
                for i in sorted(leagues, key=lambda x: x.name)
            ]
        )

        c = self.tc.channel.mention
        e = Embed(colour=Colour.red())
        e.description = f"Remove leagues from {c}?\n\n{lg_text}"
        await self.bot.reply(self.interaction, embed=e, view=view)
        await view.wait()

        if view.value:
            e.title = "Transfer Ticker Leagues Removed"
            e.description = f"{self.tc.channel.mention}\n\n{lg_text}"
            await self.tc.remove_leagues(leagues)
            u = self.interaction.user
            e.set_footer(text=f"{u} ({u.id})", icon_url=u.display_avatar.url)
        else:
            e.description = "No leagues were removed"

        await self.interaction.followup.send(embed=e)
        await self.update()

    async def reset_leagues(self) -> None:
        """Reset the leagues for this channel"""
        await self.tc.reset_leagues()

        e = Embed(title="Transfer Ticker Reset", colour=Colour.blurple())
        e.description = self.tc.channel.mention

        u = self.interaction.user
        e.set_footer(text=f"{u} ({u.id})", icon_url=u.display_avatar.url)

        await self.interaction.followup.send(embed=e)
        await self.update()

    async def creation_dialogue(self) -> bool:
        """Send Confirmation View for new ticker creation"""
        self.clear_items()

        # Ticker Verify -- NOT A SCORES CHANNEL
        sc = self.interaction.client.score_channels
        if self.tc.channel.id in [i.channel.id for i in sc]:
            err = "You cannot create a ticker in a livescores channel."
            await self.bot.error(self.interaction, err)
            return False

        i = self.interaction
        view = Confirmation(i, "Create ticker", "Cancel", ButtonStyle.green)

        e = Embed(
            title="Create Transfer Ticker",
            description=f"{self.tc.channel.mention} does not have a ticker, "
            "would you like to create one?",
        )
        await self.bot.reply(self.interaction, embed=e, view=view)
        await view.wait()

        if not view.value:
            await self.bot.error(self.interaction, "Ticker creation cancelled")
            return False

        try:
            await self.tc.create_ticker()
        except IsLiveScoreError:
            err = "You cannot add tickers to a livescores channel."
            await self.bot.error(self.interaction, err)
            return False

        e = Embed(title="Transfer Ticker Created", colour=Colour.green())
        e.description = self.tc.channel.mention

        u = self.interaction.user
        e.set_footer(text=f"{u} ({u.id})", icon_url=u.display_avatar.url)

        await self.interaction.followup.send(embed=e)
        return True

    async def delete_ticker(self) -> None:
        """Delete the ticker for this channel."""
        await self.tc.delete_ticker()
        int = self.interaction
        view = Confirmation(int, "Confirm", "Cancel", ButtonStyle.red)
        e = discord.Embed(colour=discord.Colour.red())
        e.description = (
            "Are you sure you wish to delete the transfer ticker"
            f"from {self.tc.channel.mention}?\n\nThis action cannot be undone."
        )
        await self.bot.reply(self.interaction, embed=e, view=view)
        await view.wait()

        if view.value:
            u = self.interaction.user
            e.title = "Transfer Ticker Deleted"
            e.set_footer(text=f"{u} ({u.id})", icon_url=u.display_avatar.url)
            await self.interaction.followup.send(embed=e)
            return await self.interaction.delete_original_response()
        else:
            e.title = "Transfer Ticker Deletion Cancelled"
            e.colour = Colour.og_blurple()
            m = await self.interaction.followup.send(embed=e)
            return

    async def update(self) -> Message:
        """Push the latest version of the embed to view."""
        self.clear_items()

        if not self.tc.leagues:
            await self.tc.get_leagues()

        leagues = self.tc.leagues
        lg_sort = sorted(leagues, key=lambda x: f"{x.country} {x.name}")
        markdowns = [f"{i.flag} {i.country}: {i.markdown}" for i in lg_sort]
        e = Embed(title="Transfers Ticker config", color=Colour.dark_blue())

        missing = []
        perms = self.tc.channel.permissions_for(self.tc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = (
                f"```yaml\nThis transfers channel will not work currently\n"
                f"I am missing the following permissions.\n{missing}```"
            )
            e.add_field(name="Missing Permissions", value=v)

        self.add_item(ResetLeagues())
        self.add_item(DeleteTicker())
        if not leagues:
            e.description = (
                f"{self.tc.channel.mention} has no tracked leagues."
            )
        else:
            header = f"Tracked leagues for {self.tc.channel.mention}\n"
            embeds = rows_to_embeds(e, markdowns, header=header, rows=25)
            self.pages = embeds

            e = self.pages[self.index]

            if len(leagues) > 25:
                leagues = leagues[self.index * 25 :]
                if len(leagues) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues, row=0))

        if len(self.pages) > 1:
            self.add_item(Previous(self, row=2))
            self.add_item(Jump(self, row=2))
            self.add_item(Next(self, row=2))
            self.add_item(Stop(row=2))
        else:
            self.add_item(Stop(row=1))

        return await self.bot.reply(self.interaction, embed=e, view=self)


class Transfers(Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        TransferChannel.bot = bot
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
        sql = """SELECT * FROM transfers_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        # Purge dead
        cached = set([r["channel_id"] for r in records])
        for tc in self.bot.transfer_channels.copy():
            if tc.channel.id not in cached:
                self.bot.transfer_channels.remove(tc)

        tcl = self.bot.transfer_channels
        missing = [i for i in cached if i not in [tc.channel.id for tc in tcl]]
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
        """Core transfer ticker loop - refresh every minute and
        get all new transfers from transfermarkt"""
        if None in [self.bot.db, self.bot.session]:
            return
        if not self.bot.guilds:
            return

        if not self.bot.transfer_channels:
            logger.error("Transfer Loop - No transfer_channels found.")
            await self.update_cache()
            return

        async with self.bot.session.get(LOOP_URL) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    logger.error("Loop returned Bad status: %s", resp.status)
                    return

        skip_output = True if not self.bot.parsed_transfers else False

        xp = './/div[@class="responsive-table"]/div/table/tbody/tr'
        transfers = tree.xpath(xp)
        for i in transfers:
            name = "".join(i.xpath(".//td[1]//tr[1]/td[2]/a/text()")).strip()
            if not name:
                continue
            if name in self.bot.parsed_transfers:
                continue  # skip when duplicate / void.
            else:
                self.bot.parsed_transfers.append(name)

            # We don't need to output when populating after a restart.
            if skip_output:
                continue

            link = TF + "".join(i.xpath(".//td[1]//tr[1]/td[2]/a/@href"))

            player = tfm.Player(name, link)

            # Box 1 - Player Info
            player.picture = "".join(i.xpath(".//img/@data-src"))
            player.position = "".join(i.xpath("./td[1]//tr[2]/td/text()"))

            # Box 2 - Age
            player.age = "".join(i.xpath("./td[2]//text()")).strip()

            # Box 3 - Country
            player.country = i.xpath(".//td[3]/img/@title")

            transfer = tfm.Transfer(player=player)

            # Box 4 - Old Team
            xp = './/td[4]//img[@class="tiny_wappen"]//@title'
            team = "".join(i.xpath(xp))

            xp = './/td[4]//img[@class="tiny_wappen"]/parent::a/@href'
            team_link = TF + "".join(i.xpath(xp))

            xp = './/td[4]//img[@class="flaggenrahmen"]/following-sibling::a/'
            league = "".join(i.xpath(xp + "@title"))
            if league:
                league_link = TF + "".join(i.xpath(xp + "@href"))
            else:
                xp = './/td[4]//img[@class="flaggenrahmen"]/parent::div/text()'
                league = "".join(i.xpath(xp))
                league_link = ""

            xp = './/td[4]//img[@class="flaggenrahmen"]/@alt'
            ctry = "".join(i.xpath(xp))

            old_lg = tfm.Competition(league, league_link, country=ctry)
            old_team = tfm.Team(team, team_link, league=old_lg, country=ctry)

            transfer.old_team = old_team

            # Box 5 - New Team
            xp = './/td[5]//img[@class="tiny_wappen"]//@title'
            team = "".join(i.xpath(xp))

            xp = './/td[5]//img[@class="tiny_wappen"]/parent::a/@href'
            team_link = TF + "".join(i.xpath(xp))

            xp = './/td[5]//img[@class="flaggenrahmen"]/following-sibling::a/'
            league = "".join(i.xpath(xp + "@title"))
            if league:
                league_link = TF + "".join(i.xpath(xp + "@href"))
            else:
                xp = './/td[5]//img[@class="flaggenrahmen"]/parent::div/text()'
                league = "".join(i.xpath(xp))
                league_link = ""

            xp = './/td[5]//img[@class="flaggenrahmen"]/@alt'
            ctry = "".join(i.xpath(xp))

            nw_lg = tfm.Competition(league, league_link, country=ctry)
            new_team = tfm.Team(team, team_link, league=nw_lg, country=ctry)

            transfer.new_team = new_team
            player.team = new_team

            # Box 6 - Leagues & Fee
            transfer.fee = "".join(i.xpath(".//td[6]//a/text()"))
            transfer.fee_link = TF + "".join(i.xpath(".//td[6]//a/@href"))

            old_link = old_lg.link.replace("transfers", "startseite")
            old_link = old_link.split("/saison_id", 1)
            new_link = nw_lg.link.replace("transfers", "startseite")
            new_link = new_link.split("/saison_id", 1)

            # Fetch the list of channels to output the transfer to.
            sql = """SELECT DISTINCT transfers_channels.channel_id
                     FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                     ON transfers_channels.channel_id
                     = transfers_leagues.channel_id WHERE link in ($1, $2)"""
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    records = await connection.fetch(sql, old_link, new_link)

            if records:
                e = transfer.generate_embed()
            else:
                continue

            for r in records:
                channel = self.bot.get_channel(r["channel_id"])

                if channel is None:
                    continue

                try:
                    await channel.send(embed=e)
                except HTTPException:
                    continue

    tf = Group(
        name="transfer_ticker",
        description="Create or manage a Transfer Ticker",
        default_permissions=Permissions(manage_channels=True),
    )

    @tf.command(name="manage")
    @discord.app_commands.describe(channel="Manage which channel?")
    async def manage_transfers(
        self, interaction: Interaction[Bot], channel: TextChannel = None
    ) -> Message:
        """View the config of this channel's transfer ticker"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        # Validate channel is a ticker channel.
        try:
            tc = next(
                i
                for i in self.bot.transfer_channels
                if i.channel.id == channel.id
            )
            return await tc.view(interaction).update()
        except StopIteration:
            tc = TransferChannel(channel)
            if await tc.view(interaction).creation_dialogue():
                self.bot.transfer_channels.append(tc)

    @tf.command(name="add_league")
    @discord.app_commands.describe(league_name="Search for a league name")
    async def add_league_tf(
        self,
        interaction: Interaction[Bot],
        league_name: str,
        channel: Optional[TextChannel] = None,
    ) -> Message:
        """Add a league to your transfer ticker channel(s)"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        try:
            tc = next(
                i
                for i in self.bot.transfer_channels
                if i.channel.id == channel.id
            )
        except StopIteration:
            if (
                not await (tc := TransferChannel(channel))
                .view(interaction)
                .creation_dialogue()
            ):
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

            r = result
            c = tc.channel.mention
            e.description = f"{c}\n\n{r.flag} {r.country}: {r.markdown}"

            u = interaction.user
            e.set_footer(text=f"{u} ({u.id})", icon_url=u.avatar.url)

        return await interaction.edit_original_response(embed=e)

    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Delete all transfer info for deleted channel from database"""
        sql = """DELETE FROM transfers_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                log = await connection.execute(sql, channel.id)
                if log != "DELETE 0":
                    logger.info("TF Channel: %s auto-deleted ", channel.id)


async def setup(bot: Bot):
    """Load the transfer ticker cog into the bot"""
    await bot.add_cog(Transfers(bot))
