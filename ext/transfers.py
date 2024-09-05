"""Automated fetching of the latest football transfer
   information from transfermarkt"""
from __future__ import annotations

# Cyclic Type hintingd

import logging
from importlib import reload
from typing import TYPE_CHECKING, TypeAlias

import discord
from discord import Embed
from discord.app_commands import Choice, Group, Transformer
from discord.ext import commands, tasks

import ext.lookup as lookup
import ext.toonbot_utils.transfermarkt as tfm
from ext.utils import embed_utils, flags, timed_events, view_utils

logger = logging.getLogger("transfers.py")

if TYPE_CHECKING:
    from asyncio import Task

    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member


NOPERMS = "```yaml\nI need the following permissions.\n"
NO_EMBED_PERMS = "A transfer was found, but toonbot needs embed_links perms."
TFM_COLOUR = 0x1A3151

DEFAULT_LEAGUES = [
    tfm.TFCompetition(
        name="Premier League",
        country=["England"],
        link=tfm.TF + "premier-league/startseite/wettbewerb/GB1",
    ),
    tfm.TFCompetition(
        name="Championship",
        country=["England"],
        link=tfm.TF + "/championship/startseite/wettbewerb/GB2",
    ),
    tfm.TFCompetition(
        name="Eredivisie",
        country=["Netherlands"],
        link=tfm.TF + "/eredivisie/startseite/wettbewerb/NL1",
    ),
    tfm.TFCompetition(
        name="Bundesliga",
        country=["Germany"],
        link=tfm.TF + "/bundesliga/startseite/wettbewerb/L1",
    ),
    tfm.TFCompetition(
        name="Serie A",
        country=["Italy"],
        link=tfm.TF + "/serie-a/startseite/wettbewerb/IT1",
    ),
    tfm.TFCompetition(
        name="LaLiga",
        country=["Spain"],
        link=tfm.TF + "/laliga/startseite/wettbewerb/ES1",
    ),
    tfm.TFCompetition(
        name="Ligue 1",
        country=["France"],
        link=tfm.TF + "/ligue-1/startseite/wettbewerb/FR1",
    ),
    tfm.TFCompetition(
        name="Major League Soccer",
        country=["United States"],
        link=tfm.TF + "/major-league-soccer/startseite/wettbewerb/MLS1",
    ),
]


def fmt_league(league: tfm.TFCompetition) -> str:
    """Markdown format a competition"""
    emoji = flags.get_flags(league.country)[0]
    ctr = league.country[0]
    md = f"[{league.name}]({league.link})"
    return f"{emoji} {ctr}: {md}"


class TransferEmbed(Embed):
    """An embed representing a transfermarkt player transfer."""

    def __init__(self, transfer: tfm.Transfer):
        super().__init__(colour=TFM_COLOUR, url=transfer.player.link)

        flg = " ".join(flags.get_flags(transfer.player.country))
        self.title = f"{flg} {transfer.player.name}"

        self.description = ""
        if transfer.player.age is not None:
            self.description += f"**Age**: {transfer.player.age}\n"

        self.description += (
            f"**Position**: {transfer.player.position}\n"
            f"**From**: {self.parse_team(transfer.old_team)}\n"
            f"**To**: {self.parse_team(transfer.new_team)}\n"
            f"**Fee**: {self.parse_fee(transfer)}\n"
            f"{timed_events.Timestamp().relative}"
        )
        if transfer.player.picture and "http" in transfer.player.picture:
            self.set_thumbnail(url=transfer.player.picture)

    @staticmethod
    def parse_fee(tf: tfm.Transfer) -> str:
        date = "" if tf.date is None else f": {tf.date}"
        return f"[{tf.fee.fee.title()}]({tf.fee.url}) {date}"

    @staticmethod
    def parse_team(team: tfm.TFTeam) -> str:
        flg = " ".join(flags.get_flags(team.country))
        markdown = f"{flg} [{team.name}]({team.link})"
        olg = team.league
        if olg and olg.name:
            markdown += f" ([{olg.name}]({olg.link}))"
        return markdown


class TFCompetitionTransformer(Transformer):
    """Get a Competition from user Input"""

    async def autocomplete(  # type: ignore
        self, _: Interaction, current: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from list of stored competitions"""
        search = f"🔎 Search for '{current}'"
        return [Choice(name=search, value=current)]

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> tfm.CompetitionSearch | None:
        return tfm.CompetitionSearch(value)


class Config(view_utils.DropdownPaginator):
    """View for configuring Transfer Tickers"""

    def __init__(
        self,
        invoker: User,
        channel: discord.TextChannel,
        leagues: list[tfm.TFCompetition],
    ):
        self.channel: discord.TextChannel = channel
        self.leagues: list[tfm.TFCompetition] = leagues

        embed = discord.Embed(colour=TFM_COLOUR)
        embed.title = "Transfers Ticker config"
        embed.description = f"Tracked leagues for {channel.mention}\n"

        missing: list[str] = []

        chan = self.channel
        perms = chan.permissions_for(chan.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        options: list[discord.SelectOption] = []
        rows: list[str] = []

        for league in sorted(leagues, key=lambda x: f"{x.country} {x.name}"):
            if not league.link:
                continue

            lbl = league.name[:100]
            opt = discord.SelectOption(label=lbl, value=league.link)
            opt.emoji = flags.get_flags(league.country)[0]
            rows.append(fmt_league(league))
            options.append(opt)

        super().__init__(invoker, embed, rows, options, multi=True)

        if not rows:
            mention = channel.mention
            embed.description = f"{mention} has no tracked leagues."
            self.remove_item(self.dropdown)

    @discord.ui.select(placeholder="Removed Tracked leagues", row=2)
    async def dropdown(self, itr: Interaction, sel: discord.ui.Select) -> None:
        """When a league is selected"""

        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lgtxt = ""
        for url in sel.values:
            lg = next(i for i in self.leagues if url == i.link)
            lgtxt += fmt_league(lg) + "\n"

        chan = self.channel.mention

        embed = discord.Embed(title="Transfers", colour=discord.Colour.red())
        embed.description = f"Remove these leagues from {chan}?\n{lgtxt}"
        await itr.response.edit_message(embed=embed, view=view)
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            embed = self.embeds[self.index]
            return await view_itr.response.edit_message(view=self, embed=embed)

        sql = """DELETE from transfers_leagues
                 WHERE (channel_id, link) = ($1, $2)"""
        rows = [(self.channel.id, x) for x in sel.values]

        await itr.client.db.executemany(sql, rows)

        for i in sel.values:
            league = next(j for j in self.leagues if j.link == i)
            self.leagues.remove(league)

        msg = f"{self.channel.mention}: {lgtxt}"
        embed = discord.Embed(description=msg, colour=discord.Colour.red())
        embed.title = "Transfers: Tracked Leageus Removed"
        embed_utils.user_to_footer(embed, itr.user)
        await itr.followup.send(embed=embed)

        new = Config(itr.user, self.channel, self.leagues)
        await view_itr.response.edit_message(view=new, embed=new.embeds[0])
        new.message = await view_itr.original_response()

    @discord.ui.button(row=3, style=discord.ButtonStyle.primary, label="Reset")
    async def reset(self, interaction: Interaction, _) -> None:
        """Button to reset a transfer ticker back to its default leagues"""
        view = view_utils.Confirmation(interaction.user, "Reset", "Cancel")
        view.true.style = discord.ButtonStyle.red

        embed = discord.Embed(title="Transfers:", colour=discord.Colour.red())
        ment = self.channel.mention
        embed.description = f"Reset {ment} leagues to default?\n"
        await interaction.response.edit_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            # Return to normal viewing
            embed = self.embeds[self.index]
            return await view_itr.response.edit_message(embed=embed, view=self)

        sql = """DELETE FROM transfers_leagues WHERE channel_id = $1"""
        sq2 = """INSERT INTO transfers_leagues
                 (channel_id, name, country, link) VALUES ($1, $2, $3, $4)
                 ON CONFLICT DO NOTHING"""

        defaults = DEFAULT_LEAGUES

        id_ = self.channel.id
        fields = [(id_, x.name, x.country[0], x.link) for x in defaults]
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, id_)
                await connection.executemany(sq2, fields)

        self.leagues = DEFAULT_LEAGUES

        embed = discord.Embed(title="Transfers: Tracked Leagues Reset")
        embed.colour = TFM_COLOUR
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)

        new = Config(interaction.user, self.channel, self.leagues)
        await view_itr.response.send_message(view=new, embed=new.embeds[0])
        view.message = await interaction.original_response()

    @discord.ui.button(label="Delete", row=3, style=discord.ButtonStyle.red)
    async def delete(self, interaction: Interaction, _) -> None:
        """Button to delete a ticker entirely"""
        view = view_utils.Confirmation(interaction.user, "Confirm", "Cancel")
        view.true.style = discord.ButtonStyle.red
        embed = discord.Embed(colour=discord.Colour.red())

        ment = self.channel.mention
        embed.description = (
            f"Are you sure you wish to delete the transfer ticker from {ment}?"
            "\n\nThis action cannot be undone."
        )

        await interaction.response.edit_message(view=view, embed=embed)
        view.message = await interaction.original_response()
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            embed = self.embeds[self.index]
            await view_itr.response.edit_message(view=self, embed=embed)
            return

        embed = discord.Embed(colour=discord.Colour.red())
        embed.title = "Transfers: Tracker Deleted"
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await view_itr.response.edit_message(embed=embed, view=None)
        sql = """DELETE FROM transfers_channels WHERE channel_id = $1"""
        await interaction.client.db.execute(sql, self.channel.id)


class Transfers(commands.Cog):
    """Create and configure Transfer Ticker channels"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.parsed: list[str] = []
        self.task: Task[None]
        reload(lookup)
        reload(tfm)

        self._override_once: bool = False

    async def cog_load(self) -> None:
        """Load the transfer channels on cog load."""
        self.task = self.transfers_loop.start()  # pylint: disable=E1101

    async def cog_unload(self) -> None:
        """Cancel transfers task on Cog Unload."""
        self.task.cancel()

    async def get_config(
        self, interaction: Interaction, channel: discord.TextChannel | None
    ) -> Config | None:
        if channel is None:
            if isinstance(interaction.channel, discord.TextChannel):
                channel = interaction.channel
            else:
                return

        # Validate channel is a ticker channel.
        sql = """SELECT * from transfers_channels WHERE channel_id = $1"""
        if await self.bot.db.fetchrow(sql, channel.id):
            sql = """SELECT * FROM transfers_leagues WHERE channel_id = $1"""
            records = await self.bot.db.fetch(sql, channel.id)
            leagues = list(tfm.TFCompetition.parse_obj(r) for r in records)
            return Config(interaction.user, channel, leagues)

        # Or create one.
        chan = channel.mention
        view = view_utils.Confirmation(interaction.user, "Create", "Cancel")
        view.true.style = discord.ButtonStyle.green

        embed = discord.Embed(title="Create a ticker")
        embed.description = f"{chan} has no transfer ticker, create one?"

        if interaction.response.is_done():
            send = interaction.edit_original_response
        else:
            send = interaction.response.send_message

        await send(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"❌ Cancelled transfer ticker for {chan}"
            edit = view.interaction.response.edit_message
            await edit(embed=embed, view=None)
            return None

        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, channel.guild.id)

                sql = """INSERT INTO transfers_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, channel.guild.id, channel.id)

                sq2 = """
                INSERT INTO transfers_leagues (channel_id, name, country, link)
                VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING
                """

                lgs = DEFAULT_LEAGUES
                rows = [
                    (channel.id, x.name, x.country[0], x.link) for x in lgs
                ]
                await connection.executemany(sq2, rows)
        return Config(interaction.user, channel, lgs)

    # Core Loop
    @tasks.loop(minutes=1)
    async def transfers_loop(self) -> None:
        """
        Core transfer ticker loop

        Refresh every minute and get all new transfers from transfermarkt
        """
        skip_output = not bool(self.parsed)

        if self._override_once:
            skip_output = False
            self._override_once = False

        bad: list[int] = []
        for i in await tfm.recent_transfers():
            if i.player.link in self.parsed:
                continue  # skip when duplicate / void.

            self.parsed.append(i.player.link)

            # We don't need to output when populating after a restart.
            if skip_output:
                continue

            old = i.old_team.league.link if i.old_team.league else None
            new = i.new_team.league.link if i.new_team.league else None

            if old is new is None:
                continue

            # Fetch the list of channels to output the transfer to.
            sql = """SELECT DISTINCT transfers_channels.channel_id
                     FROM transfers_channels LEFT OUTER JOIN transfers_leagues
                     ON transfers_channels.channel_id
                     = transfers_leagues.channel_id WHERE link in ($1, $2)"""
            records = await self.bot.db.fetch(sql, old, new)

            embed = TransferEmbed(i)

            for record in records:
                channel = self.bot.get_channel(record["channel_id"])

                if not isinstance(channel, discord.TextChannel):
                    continue

                if channel.is_news():
                    bad.append(channel.id)
                    continue

                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    try:
                        await channel.send(NO_EMBED_PERMS)
                    except discord.Forbidden:
                        bad.append(channel.id)

            DEBUG_CHANNEL = self.bot.get_channel(1108036536710209546)
            if isinstance(DEBUG_CHANNEL, discord.TextChannel):
                await DEBUG_CHANNEL.send(embed=embed)

        if bad:
            logger.info("Found %s bad transfer channels", bad)

    tf = Group(
        name="transfer_ticker",
        description="Create or manage a Transfer Ticker",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @tf.command()
    @discord.app_commands.describe(channel="Manage which channel?")
    async def manage(
        self,
        interaction: Interaction,
        channel: discord.TextChannel | None,
    ) -> None:
        """View the config of this channel's transfer ticker"""
        await interaction.response.defer(thinking=True)

        cfg = await self.get_config(interaction, channel)
        if cfg is None:
            return

        emb = cfg.embeds[0]
        await interaction.edit_original_response(view=cfg, embed=emb)
        cfg.message = await interaction.original_response()

    @tf.command(name="add_league")
    @discord.app_commands.describe(competition="Search for a competition name")
    async def add_tf_league(
        self,
        interaction: Interaction,
        competition: str,
        channel: discord.TextChannel | None,
    ) -> None:
        """Add a league to your transfer ticker channel(s)"""
        await interaction.response.defer(thinking=True)

        cfg = await self.get_config(interaction, channel)
        if cfg is None:
            return

        view = await lookup.SearchView.fetch(
            interaction, tfm.CompetitionSearch(competition)
        )

        await view.wait()

        if not view.value:
            return

        tfr = view.value

        sql = """
        INSERT INTO transfers_leagues (channel_id, name, country, link)
        VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
        await interaction.client.db.execute(
            sql,
            cfg.channel.id,
            tfr.name,
            tfr.country[0],
            tfr.link,
            timeout=60,
        )

        embed = discord.Embed(title="Transfers: Tracked League Added")
        embed.description = f"{cfg.channel.mention}: {fmt_league(tfr)}"
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.edit_original_response(embed=embed, view=None)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, chan: discord.TextChannel) -> None:
        """Delete all transfer info for deleted channel from database"""
        sql = """DELETE FROM transfers_channels WHERE channel_id = $1"""
        if await self.bot.db.execute(sql, chan.id) != "DELETE 0":
            logger.info("%s TF Channel auto-deleted", chan.id)


async def setup(bot: Bot):
    """Load the transfer ticker cog into the bot"""
    await bot.add_cog(Transfers(bot))
