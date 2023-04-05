"""Automated fetching of the latest football transfer
   information from transfermarkt"""
from __future__ import annotations  # Cyclic Type hinting

from importlib import reload
import typing
import logging

import discord
from discord.ext import commands, tasks
from lxml import html

import ext.toonbot_utils.transfermarkt as tfm
from ext.utils import view_utils, embed_utils

logger = logging.getLogger("transfers.py")

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]

TF = "https://www.transfermarkt.co.uk"
MIN_MARKET_VALUE = "?minMarktwert=200.000"
LOOP_URL = f"{TF}/transfers/neuestetransfers/statistik{MIN_MARKET_VALUE}"

NOPERMS = "```yaml\nI need the following permissions.\n"


class CompetitionTransformer(discord.app_commands.Transformer):
    """Get a Competition from user Input"""

    async def autocomplete(
        self, _: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from list of stored competitions"""
        search = f"🔎 Search for '{current}'"
        return [discord.app_commands.Choice(name=search, value=current)]

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> typing.Optional[tfm.Competition]:
        await interaction.response.defer(thinking=True)

        view = tfm.CompetitionSearch(value, fetch=True)
        await view.update(interaction)
        await view.wait()

        return view.value


class TransferChannel:
    """An object representing a channel with a Transfer Ticker"""

    bot: typing.ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: set[tfm.Competition] = set()

    # Database management
    async def get_leagues(self) -> set[tfm.Competition]:
        """Get the leagues needed for this channel"""
        sql = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)

        self.leagues = set(
            tfm.Competition(
                name=r["name"], country=r["country"], link=r["link"]
            )
            for r in records
        )
        return self.leagues


class ResetLeagues(discord.ui.Button):
    """Button to reset a transfer ticker back to its default leagues"""

    view: TransfersConfig

    def __init__(self) -> None:
        super().__init__(
            label="Reset Ticker", style=discord.ButtonStyle.primary, row=1
        )

    async def callback(self, interaction: Interaction) -> None:
        """Click button reset leagues"""
        await interaction.response.defer()

        sql_1 = """DELETE FROM transfers_leagues WHERE channel_id = $1"""
        sql_2 = """INSERT INTO transfers_leagues
                 (channel_id, name, country, link) VALUES ($1, $2, $3, $4)
                 ON CONFLICT DO NOTHING"""

        defaults = tfm.DEFAULT_LEAGUES

        id_ = self.view.chan.channel.id
        fields = [(id_, x.name, x.country, x.link) for x in defaults]
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql_1, id_)
                await connection.executemany(sql_2, fields)

        for league in defaults:
            self.view.chan.leagues.add(league)

        embed = discord.Embed(title="Transfers: Tracked Leagues Reset")
        embed.description = self.view.chan.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)
        await self.view.update(interaction)


class DeleteTicker(discord.ui.Button):
    """Button to delete a ticker entirely"""

    view: TransfersConfig

    def __init__(self) -> None:
        super().__init__(
            label="Delete ticker", style=discord.ButtonStyle.red, row=1
        )

    async def callback(self, interaction: Interaction) -> None:
        """Click button reset leagues"""
        style = discord.ButtonStyle.red
        view = view_utils.Confirmation("Confirm", "Cancel", style)
        embed = discord.Embed(colour=discord.Colour.red())

        chan = self.view.chan.channel.mention
        embed.description = (
            f"Are you sure you wish to delete the transfer ticker from {chan}?"
            "\n\nThis action cannot be undone."
        )

        await interaction.response.edit_message(view=view, embed=embed)

        if not view.value:
            return await self.view.update(interaction)

        sql = """DELETE FROM transfers_channels WHERE channel_id = $1"""
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.view.chan.channel.id)

        interaction.client.transfer_channels.remove(self.view.chan)

        embed = discord.Embed(colour=discord.Colour.red())
        embed.description = f"The Transfer Ticker for {chan} was deleted."
        embed_utils.user_to_footer(embed, interaction.user)
        return await interaction.response.edit_message(embed=embed, view=None)


class RemoveLeague(discord.ui.Select):
    """Dropdown to remove leagues from a match event ticker."""

    view: TransfersConfig

    def __init__(self, leagues: list[tfm.Competition], row: int = 2) -> None:
        place = "Remove tracked league(s)"
        super().__init__(placeholder=place, row=row, max_values=len(leagues))

        for league in leagues:
            if league.link is None:
                continue

            lbl = league.name[:100]
            self.add_option(label=lbl, value=league.link, emoji=league.flag)

    async def callback(self, interaction: Interaction) -> None:
        """When a league is selected"""
        red = discord.ButtonStyle.red
        view = view_utils.Confirmation("Remove", "Cancel", red)

        lg_text = "```yaml\n" + "\n".join(sorted(self.values)) + "```"
        chan = self.view.chan.channel.mention

        embed = discord.Embed(title="Transfers", colour=discord.Colour.red())
        embed.description = f"Remove these leagues from {chan}? {lg_text}"
        await interaction.response.edit_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            return await self.view.update(interaction)

        sql = """DELETE from transfers_leagues
                 WHERE (channel_id, link) = ($1, $2)"""
        rows = [(self.view.chan.channel.id, x) for x in self.values]

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        for i in self.view.chan.leagues.copy():
            if i.link in self.values:
                self.view.chan.leagues.remove(i)

        ment = self.view.chan.channel.mention
        msg = f"Removed {ment} tracked leagues:\n{lg_text}"
        embed = discord.Embed(description=msg, colour=discord.Colour.red())
        embed.title = "Transfers"
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(content=msg)
        return await self.view.update(interaction)


class TransfersConfig(view_utils.BaseView):
    """View for configuring Transfer Tickers"""

    bot: Bot
    interaction: Interaction

    def __init__(self, chan: TransferChannel):
        super().__init__()
        self.chan: TransferChannel = chan

    async def update(self, interaction: Interaction) -> None:
        """Push the latest version of the embed to view."""
        self.clear_items()

        if not self.chan.leagues:
            await self.chan.get_leagues()

        embed = discord.Embed(colour=discord.Colour.dark_blue())
        embed.title = "Transfers Ticker config"

        missing = []

        chan = self.chan.channel
        perms = chan.permissions_for(chan.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        leagues = self.chan.leagues
        lg_sort = sorted(leagues, key=lambda x: f"{x.country} {x.name}")

        self.pages = embed_utils.paginate(lg_sort)

        this_page = self.pages[self.index]
        markdowns = [f"{i.flag} {i.country}: {i.markdown}" for i in this_page]

        embed.description = f"Tracked leagues for {chan.mention}```yaml\n"
        embed.description += "\n".join(markdowns)
        self.add_item(ResetLeagues())
        self.add_item(DeleteTicker())

        if not leagues:
            mention = self.chan.channel.mention
            embed.description = f"{mention} has no tracked leagues."
        else:
            self.add_item(RemoveLeague(this_page, row=0))

        self.add_page_buttons(2)
        return await interaction.response.edit_message(embed=embed, view=self)


class Transfers(commands.Cog):
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

    async def create(
        self,
        interaction: Interaction,
        channel: discord.TextChannel,
    ) -> None:
        """Create a ticker for the channel"""

        chan = channel.mention
        btn = discord.ButtonStyle.green
        view = view_utils.Confirmation("Create ticker", "Cancel", btn)

        embed = discord.Embed(title="Create a ticker")
        embed.description = f"{chan} has no transfer ticker, create one?"
        await interaction.edit_original_response(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"❌ Cancelled transfer ticker for {chan}"
            return await interaction.response.edit_message(embed=embed)

        leg = tfm.DEFAULT_LEAGUES

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                # Create the ticker itself.
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, channel.guild.id)
                sql = """INSERT INTO transfers_channels
                         (guild_id, channel_id)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, channel.guild.id, channel.id)
                sql = """DELETE FROM transfers_leagues WHERE channel_id = $1"""
                await connection.execute(sql, channel.id)
                sql = """INSERT INTO transfers_leagues
                         (channel_id, name, country, link)
                         VALUES ($1, $2, $3, $4)
                         ON CONFLICT DO NOTHING"""
                fields = [(channel.id, x.name, x.country, x.link) for x in leg]
                await connection.executemany(sql, fields)

        chan = TransferChannel(channel)
        self.bot.transfer_channels.append(chan)
        for i in leg:
            chan.leagues.add(i)
        return await TransfersConfig(chan).update(interaction)

    async def update_cache(self) -> list[TransferChannel]:
        """Load Transfer Channels into the bot."""
        sql = """SELECT * FROM transfers_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        # Purge dead
        cached = set([r["channel_id"] for r in records])
        for chan in self.bot.transfer_channels.copy():
            if chan.channel.id not in cached:
                self.bot.transfer_channels.remove(chan)

        tcl = self.bot.transfer_channels
        missing = [i for i in cached if i not in [tc.channel.id for tc in tcl]]
        for cid in missing:
            channel = self.bot.get_channel(cid)
            if channel is None:
                continue

            channel = typing.cast(discord.TextChannel, channel)

            chan = TransferChannel(channel)
            await chan.get_leagues()
            self.bot.transfer_channels.append(chan)
        return self.bot.transfer_channels

    # Core Loop
    @tasks.loop(minutes=1)
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

        xpath = './/div[@class="responsive-table"]/div/table/tbody/tr'
        transfers = tree.xpath(xpath)
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
            player.age = int("".join(i.xpath("./td[2]//text()")).strip())

            # Box 3 - Country
            player.country = i.xpath(".//td[3]/img/@title")

            transfer = tfm.Transfer(player=player)

            # Box 4 - Old Team
            xpath = './/td[4]//img[@class="tiny_wappen"]//@title'
            team = "".join(i.xpath(xpath))

            xpath = './/td[4]//img[@class="tiny_wappen"]/parent::a/@href'
            team_link = TF + "".join(i.xpath(xpath))

            xpath = (
                './/td[4]//img[@class="flaggenrahmen"]/following-sibling::a/'
            )
            league = "".join(i.xpath(xpath + "@title"))
            if league:
                league_link = TF + "".join(i.xpath(xpath + "@href"))
            else:
                xpath = (
                    './/td[4]//img[@class="flaggenrahmen"]/parent::div/text()'
                )
                league = "".join(i.xpath(xpath))
                league_link = ""

            xpath = './/td[4]//img[@class="flaggenrahmen"]/@alt'
            ctry = "".join(i.xpath(xpath))

            old_lg = tfm.Competition(league, league_link, country=ctry)
            old_team = tfm.Team(team, team_link, league=old_lg, country=ctry)

            transfer.old_team = old_team

            # Box 5 - New Team
            xpath = './/td[5]//img[@class="tiny_wappen"]//@title'
            team = "".join(i.xpath(xpath))

            xpath = './/td[5]//img[@class="tiny_wappen"]/parent::a/@href'
            team_link = TF + "".join(i.xpath(xpath))

            xpath = (
                './/td[5]//img[@class="flaggenrahmen"]/following-sibling::a/'
            )
            league = "".join(i.xpath(xpath + "@title"))
            if league:
                league_link = TF + "".join(i.xpath(xpath + "@href"))
            else:
                xpath = (
                    './/td[5]//img[@class="flaggenrahmen"]/parent::div/text()'
                )
                league = "".join(i.xpath(xpath))
                league_link = ""

            xpath = './/td[5]//img[@class="flaggenrahmen"]/@alt'
            ctry = "".join(i.xpath(xpath))

            nw_lg = tfm.Competition(league, league_link, country=ctry)
            new_team = tfm.Team(team, team_link, league=nw_lg, country=ctry)

            transfer.new_team = new_team
            player.team = new_team

            # Box 6 - Leagues & Fee
            transfer.fee = "".join(i.xpath(".//td[6]//a/text()"))
            transfer.fee_link = TF + "".join(i.xpath(".//td[6]//a/@href"))

            old_link = old_lg.link.replace("transfers", "startseite")
            if old_link:
                old_link = old_link.split("/saison_id", 1)[0]

            new_link = nw_lg.link.replace("transfers", "startseite")
            if new_link:
                new_link = new_link.split("/saison_id", 1)[0]

            # Fetch the list of channels to output the transfer to.
            sql = """SELECT DISTINCT transfers_channels.channel_id
                     FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                     ON transfers_channels.channel_id
                     = transfers_leagues.channel_id WHERE link in ($1, $2)"""
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    records = await connection.fetch(sql, old_link, new_link)

            if not records:
                continue

            embed = transfer.generate_embed()

            for record in records:
                channel = self.bot.get_channel(record["channel_id"])

                if channel is None:
                    continue

                channel = typing.cast(discord.TextChannel, channel)

                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    continue

    tf = discord.app_commands.Group(
        name="transfer_ticker",
        description="Create or manage a Transfer Ticker",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @tf.command()
    @discord.app_commands.describe(channel="Manage which channel?")
    async def manage(
        self,
        interaction: Interaction,
        channel: typing.Optional[discord.TextChannel],
    ) -> None:
        """View the config of this channel's transfer ticker"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        try:
            tkrs = self.bot.transfer_channels
            chan = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            return await self.create(interaction, channel)
        return await TransfersConfig(chan).update(interaction)

    @tf.command()
    @discord.app_commands.describe(competition="Search for a competition name")
    async def add_league(
        self,
        interaction: Interaction,
        competition: discord.app_commands.Transform[
            tfm.Competition, CompetitionTransformer
        ],
        channel: typing.Optional[discord.TextChannel],
    ) -> None:
        """Add a league to your transfer ticker channel(s)"""
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        try:
            tkrs = self.bot.transfer_channels
            chan = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            return await self.create(interaction, channel)

        if isinstance(competition.country, list):
            ctr = competition.country[0]
        else:
            ctr = competition.country
        chan.leagues.add(competition)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO transfers_leagues
                        (channel_id, name, country, link)
                        VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
                await connection.execute(
                    sql, channel.id, competition.name, ctr, competition.link
                )

        embed = discord.Embed(title="Transfers: Tracked League Added")
        embed.description = f"{chan.channel.mention}\n\n{competition.link}"
        embed_utils.user_to_footer(embed, interaction.user)
        return await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, chan: discord.TextChannel) -> None:
        """Delete all transfer info for deleted channel from database"""
        sql = """DELETE FROM transfers_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                log = await connection.execute(sql, chan.id)
                if log != "DELETE 0":
                    logger.info("TF Channel: %s auto-deleted ", chan.id)


async def setup(bot: Bot):
    """Load the transfer ticker cog into the bot"""
    await bot.add_cog(Transfers(bot))
