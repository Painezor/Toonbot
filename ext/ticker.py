"""Handle Dispatched Fixture events, and database for channels"""
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import logging
from playwright.async_api import TimeoutError as PWTimeout
from pydantic import BaseModel
from typing import TYPE_CHECKING, TypeAlias

import discord
from discord import Colour, Embed, Message, TextChannel
from discord.abc import GuildChannel
from discord.ext import commands
from discord.ui import Select

import ext.flashscore as fs
from ext.toonbot_utils.fs_transform import comp_
from ext.utils import embed_utils, view_utils, flags

if TYPE_CHECKING:
    from core import Bot
    from playwright.async_api import Page

    from ext.flashscore.abc import BaseCompetition, BaseFixture, BaseTeam

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("ticker.py")

NOPERMS = (
    "```yaml\nThis ticker channel will not work currently"
    "I am missing the following permissions.\n"
)

# Number of permanent instances to fetch tables.
WORKER_COUNT = 2


def fmt_comp(comp: BaseCompetition) -> str:
    return f"{flags.get_flag(comp.country)} [{comp.title}]({comp.url})"


class TickerSettings(BaseModel):
    channel_id: int
    goals: bool
    kick_offs: bool
    full_times: bool
    half_times: bool
    second_halfs: bool
    red_cards: bool
    final_results: bool
    delays: bool
    vars: bool
    extra_times: bool
    penalties: bool


class TickerEmbed(Embed):
    def __init__(self, event: TickerEvent, extended: bool = False) -> None:
        clr = event.colour

        super().__init__(colour=clr)
        self.event = event

        self.url = event.fixture.url
        self.title = event.fixture.score_line
        self.description = ""

        self.event_to_header()
        self.comp_to_footer()

        if isinstance(event, Kickoff):
            self.description += self.handle_kickoff()

        if isinstance(event, PenaltyResults):
            self.handle_pens()

        if extended:
            self.write_all()
        else:
            rev = reversed(event.fixture.incidents)
            try:
                if (ico := self.event.svg_ico) is not None:
                    evt = next(i for i in rev if i.svg_class == ico)
                    self.description = self.parse_incident(evt)
                else:
                    evt = None
            except StopIteration:
                evt = None

            if evt is not None and evt.description:
                self.description += f"\n\n> {evt.description}"

        if (info := event.fixture.infobox) is not None:
            self.add_field(name="Match Info", value=f"```yaml\n{info}```")

    def event_to_header(self) -> None:
        name = self.event.title
        if self.event.team:
            name = f"{name} ({self.event.team.name})"
            self.set_author(name=name, icon_url=self.event.team.logo_url)
        else:
            self.set_author(name=name)

    def comp_to_footer(self) -> None:
        if comp := self.event.fixture.competition:
            self.set_footer(text=comp.title, icon_url=comp.logo_url)
            self.set_thumbnail(url=comp.logo_url)

    def handle_kickoff(self) -> str:
        desc = ""
        if self.event.fixture.referee:
            desc += f"**Referee**: {self.event.fixture.referee}\n"
        if self.event.fixture.stadium:
            desc += f"**Stadium**: {self.event.fixture.stadium}\n"

        if self.event.fixture.tv:
            value = [f"[{i.name}]({i.link})" for i in self.event.fixture.tv]
            desc += "\n**TV Coverage**\n" + ", ".join(value)
        return desc

    def parse_incident(self, incident: fs.MatchIncident) -> str:
        """Get a string representation of the match incident"""

        key = incident.svg_class.rsplit(maxsplit=1)[-1].strip()
        try:
            emote = {
                "card": fs.YELLOW_CARD_EMOJI,
                "card-ico": fs.YELLOW_CARD_EMOJI,
                "footballOwnGoal-ico": f"{fs.GOAL_EMOJI}OG",
                "red-yellow-card": fs.RED_CARD_EMOJI + fs.YELLOW_CARD_EMOJI,
                "soccer": fs.GOAL_EMOJI,
                "substitution": fs.INBOUND_EMOJI,
                "var": fs.VAR_EMOJI,
                "warning": fs.WARNING_EMOJI,
                "yellowCard-ico": fs.YELLOW_CARD_EMOJI,
            }[key]
        except KeyError:
            logger.error("missing emote for %s", key)
            emote = ""

        output = f"`{incident.time}` {emote}"

        if incident.team is not None:
            name = incident.team.name
            if name is None:
                tag = "???"
            elif len(name.split()) == 1:
                tag = "".join(name[:3]).upper()
            else:
                tag = "".join([i for i in name if i.isupper()][:3])
            output += f" {tag}"

        if incident.player:
            output += f" [{incident.player.name}]({incident.player.url})"

        if incident.note:
            output += f" ({incident.note})"

        if incident.assist:
            output += f" ([{incident.assist.name}]({incident.assist.url}))"
        return output

    def handle_pens(self) -> None:
        """Add fields to the embed with the results of the penalties"""
        fix = self.event.fixture
        fxe = fix.incidents

        pens = [i for i in fxe if "Penalty" in i.type and "'" not in i.time]

        for j in [fix.home.team, fix.away.team]:
            if value := [self.parse_incident(i) for i in pens if i.team == j]:
                self.add_field(name=j.name, value="\n".join(value))

    def write_all(self) -> None:
        evts = self.event.fixture.incidents
        self.description = "\n".join(self.parse_incident(i) for i in evts)


class TickerEventView(view_utils.BaseView):
    def __init__(self, event: TickerEvent) -> None:
        super().__init__(None, timeout=None)
        self.remove_item(self._stop)  # Hide the stop button.
        self.event: TickerEvent = event
        if self.event.table_url is None:
            self.remove_item(self.standings)

    @discord.ui.button(label="Incidents", emoji="ℹ")
    async def callback(self, interaction: Interaction, _) -> None:
        """Send an emphemeral list of all events to the invoker"""
        temb = TickerEmbed(self.event)
        temb.write_all()
        try:
            await interaction.response.send_message(embed=temb, ephemeral=True)
        except Exception as err:
            logger.error("Failed to send extenderview", exc_info=True)
            raise err

    @discord.ui.button(label="Standings")
    async def standings(self, interaction: Interaction, _) -> None:
        """Send table to user"""
        url = self.event.table_url
        await interaction.response.send_message(url, ephemeral=True)


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    title = "MatchEvent"
    svg_ico = None
    colour = Colour.blurple()

    def __init__(
        self,
        bot: Bot,
        fixture: BaseFixture,
        channels: list[TextChannel],
        team: BaseTeam | None = None,
        table_url: str | None = None,
    ) -> None:
        if not channels:
            return

        self.bot: Bot = bot
        self.fixture: fs.Fixture = fs.Fixture.parse_obj(fixture)
        self.channels: list[discord.TextChannel] = channels
        self.team: BaseTeam | None = team
        self.table_url: str | None = table_url

        # Begin loop on init
        self.messages: dict[discord.TextChannel, Message] = {}
        self._cached: Embed | None = None
        name = self.__class__.__name__
        self.bot.loop.create_task(self.event_loop(), name=name)

    async def _dispatch(self) -> None:
        """Send to the appropriate channel and let them handle it."""
        embed = TickerEmbed(self)

        if self._cached is not None:
            if self._cached.description == embed.description:
                return

        self._cached = embed

        view = TickerEventView(self)

        for chan in self.channels:
            # Send messages
            if chan not in self.messages:
                try:
                    message = await chan.send(embed=embed, view=view)
                except discord.Forbidden:
                    _ = """DELETE FROM ticker_channels WHERE channel_id = $1"""
                    await self.bot.db.execute(_, chan.id)
                    self.channels.remove(chan)
                    continue
            else:
                message = self.messages[chan]
                message = await message.edit(embed=embed, view=view)
            self.messages[chan] = message

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        # Handle Match Events with no game events.
        for count in range(5):
            page = await self.bot.browser.new_page()
            try:
                await self.fixture.fetch(page)
            except Exception:
                continue
            finally:
                await page.close()

            if all(i.player is not None for i in self.fixture.incidents):
                break

            await self._dispatch()
            await asyncio.sleep(count + 1 * 60)

        await self._dispatch()


class Goal(TickerEvent):
    title = "Goal"
    svg_ico = "soccer"
    colour = Colour.green()


class VarGoal(Goal):
    colour = Colour.dark_green()


class RedCard(TickerEvent):
    title = "Red Card"
    svg_ico = "redCard-ico"
    colour = Colour.red()


class VarRedCard(RedCard):
    title = "Red Card Overturned"
    colour = Colour.dark_red()


class PeriodBegin(TickerEvent):
    title = "Period Started"
    colour = Colour.light_gray()


class Kickoff(PeriodBegin):
    title = "Kick Off"

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        await self._dispatch()


class SecondHalf(PeriodBegin):
    title = "Second Half"


class ExtraTimeSecondHalf(SecondHalf):
    title = "ET: Second Half"
    colour = Colour.dark_purple()


class ExtraTime(PeriodBegin):
    title = "Extra Time Begins"
    colour = Colour.magenta()


class PeriodEnd:
    title = "End of Period"
    colour = Colour.dark_teal()


class HalfTime(TickerEvent):
    title = "Half Time"
    colour = Colour.yellow()


class Delayed(HalfTime):
    title = "Game Delayed"
    colour = Colour.orange()


class ExtraTimeEnd(HalfTime):
    title = "End of Extra Time"
    colour = Colour.fuchsia()


class Interrupted(Delayed):
    title = "Match Interrupted"


class Postponed(Delayed):
    title = "Postponed"
    title = Colour.dark_orange()


class ExtraTimeHalfTime(HalfTime):
    title = "ET: Half Time"
    colour = Colour.dark_magenta()


class FullTime(TickerEvent):
    title = "Full Time"
    colour = Colour.teal()


class NormalTimeEnd(TickerEvent):
    title = "End of Normal Time"
    colour = Colour.dark_magenta()


class FixtureResumed(FullTime):
    title = "Match Resumed"
    colour = Colour.light_grey()


class AfterExtraTime(FullTime):
    title = "Result After Extra Time"
    colour = Colour.purple()


class FinalResult(FullTime):
    title = "Final Result"


class MatchAbandoned(FullTime):
    colour = Colour.dark_orange()
    title = "Match Abandoned"


class MatchAwarded(MatchAbandoned):
    title = "Match Abandoned"


class MatchCancelled(MatchAbandoned):
    title = "Match Cancelled"


class PenaltyResults(FullTime):
    title = "Penalty Results"
    colour = Colour.dark_gold()


class PenaltiesStart(TickerEvent):
    title = "Penalty Shootout"
    colour = Colour.gold()


class Config(view_utils.DropdownPaginator):
    """Match Event Ticker View"""

    def __init__(
        self,
        invoker: User,
        channel: discord.TextChannel,
        leagues: list[BaseCompetition],
        settings: TickerSettings,
    ):
        self.channel: discord.TextChannel = channel
        self._db_table = "ticker_settings"
        self.leagues: list[BaseCompetition] = leagues
        self.leagues.sort(key=lambda i: i.title)
        self.settings: TickerSettings = settings

        options: list[discord.SelectOption] = []
        for i in self.leagues:
            if i.url is None:
                continue

            flag = flags.get_flag(i.country)
            opt = discord.SelectOption(label=i.title, value=i.url, emoji=flag)
            opt.description = i.url
            options.append(opt)

        embed = Embed(colour=Colour.dark_teal())
        embed.set_author(name="Match Event Ticker config")
        embed.description = f"Tracked leagues for {self.channel.mention}\n"

        # Permission Checks
        missing: list[str] = []
        perms = self.channel.permissions_for(self.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        # Handle Empty
        rows: list[str] = [fmt_comp(i) for i in self.leagues]
        if not rows:
            rows += [f"{self.channel.mention} has no tracked leagues."]

        super().__init__(invoker, embed, rows, options, multi=True)

        self.stg.options = self.generate_settings()
        self.stg.max_values = len(self.stg.options)

    def generate_settings(self) -> list[discord.SelectOption]:
        """Generate Dropdown for settings configuration"""

        options: list[discord.SelectOption] = []
        for k, val in iter(self.settings):
            if k == "channel_id":
                continue

            emoji = "🟢" if val else "🔴"
            name = k.replace("_", " ").title()
            opt = discord.SelectOption(label=name, emoji=emoji, value=k)

            ena = "enabled" if val else "disabled"
            opt.description = f"{name} events are currently {ena}"
            options.append(opt)
        return options

    @discord.ui.select(placeholder="Change Settings", row=2)
    async def stg(self, itr: Interaction, sel: Select) -> None:
        """Regenerate view and push to message"""
        embed = Embed(title="Settings updated", colour=Colour.dark_teal())
        embed.description = ""
        embed_utils.user_to_footer(embed, itr.user)

        async with itr.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                for i in sel.values:  # List of DB Fields.
                    old = getattr(self.settings, i)
                    setattr(self.settings, i, not old)

                    alias = i.replace("_", " ").title()

                    if old:
                        emoji = "🟢"
                        toggle = "Enabled"
                    else:
                        emoji = "🔴"
                        toggle = "Disabled"
                    embed.description += f"{emoji} {alias}: {toggle}\n"
                    sql = f"""UPDATE {self._db_table} SET {i} = NOT {i}
                            WHERE channel_id = $1"""
                    await connection.execute(sql, self.channel.id)

        sel.options = self.generate_settings()
        await itr.response.edit_message(view=self)
        return await itr.followup.send(embed=embed)

    @discord.ui.select(placeholder="Remove Leagues", row=1)
    async def dropdown(self, itr: Interaction, sel: Select) -> None:
        """When a league is selected, delete channel / league row from DB"""

        # Ask User to confirm their selection of data destruction
        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lg_text = "\n".join(
            [
                fmt_comp(next(j for j in self.leagues if i == j.url))
                for i in sorted(sel.values)
            ]
        )

        ment = self.channel.mention
        embed = Embed(title="Ticker", colour=Colour.red())
        embed.description = f"Remove these leagues from {ment}?\n{lg_text}"

        await itr.response.edit_message(embed=embed, view=view)
        await view.wait()

        rsp = view.interaction.response

        if not view.value:
            # Return to normal viewing
            embed = self.embeds[self.index]
            return await rsp.edit_message(embed=embed, view=self)

        # Remove from the database
        _ = """DELETE from ticker_leagues WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.channel.id, x) for x in sel.values]
        await itr.client.db.executemany(_, rows, timeout=60)

        # Remove from the parent channel's tracked leagues
        for i in sel.values:
            league = next(j for j in self.leagues if j.url == i)
            self.leagues.remove(league)

        # Send Confirmation Followup
        embed = Embed(title="Ticker", colour=Colour.red())
        ment = self.channel.mention
        embed.description = f"Removed {ment} tracked leagues:\n{lg_text}"
        embed_utils.user_to_footer(embed, itr.user)
        await itr.followup.send(embed=embed)

        # Reinstantiate the view
        cfg = Config(itr.user, self.channel, self.leagues, self.settings)
        try:
            cfg.index = self.index
            embed = cfg.embeds[cfg.index]
        except IndexError:
            cfg.index = self.index - 1
            embed = cfg.embeds[cfg.index]
        await rsp.edit_message(view=cfg, embed=embed)

    @discord.ui.button(row=3, label="Reset Leagues")
    async def reset(self, interaction: Interaction, _) -> None:
        """Click button reset leagues"""
        # Ask User to confirm their selection of data destruction
        view = view_utils.Confirmation(interaction.user, "Reset", "Cancel")
        view.true.style = discord.ButtonStyle.red

        embed = Embed(title="Ticker", colour=Colour.red())
        ment = self.channel.mention
        embed.description = f"Reset leagues to default {ment}?\n"

        await interaction.response.edit_message(embed=embed, view=view)
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            # Return to normal viewing
            embed = self.embeds[self.index]
            await view_itr.response.edit_message(embed=embed, view=self)
            return

        sql = """DELETE FROM ticker_leagues WHERE channel_id = $1"""
        await interaction.client.db.execute(sql, self.channel.id)

        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        args = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]
        await interaction.client.db.executemany(sql, args)

        self.leagues.clear()
        cache = interaction.client.cache
        for i in fs.DEFAULT_LEAGUES:
            if comp := cache.get_competition(url=i):
                self.leagues.append(comp)

        embed = Embed(title="Ticker: Tracked Leagues Reset")
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)

        # Reinstantiate the view
        user = interaction.user
        cfg = Config(user, self.channel, self.leagues, self.settings)
        await view_itr.response.edit_message(view=cfg, embed=cfg.embeds[0])

    @discord.ui.button(row=3, label="Delete", style=discord.ButtonStyle.red)
    async def delete(self, interaction: Interaction, _) -> None:
        """Click button delete Match Event Ticker"""
        view = view_utils.Confirmation(interaction.user, "Confirm", "Cancel")
        view.true.style = discord.ButtonStyle.red

        ment = self.channel.mention
        embed = Embed(colour=Colour.red())
        embed.description = (
            f"Are you sure you wish to delete the ticker from {ment}?"
            "\n\nThis action cannot be undone."
        )
        await interaction.response.edit_message(view=view, embed=embed)
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            # Return to normal viewing
            embed = self.embeds[self.index]
            await view_itr.response.edit_message(embed=embed, view=self)
            return

        embed = Embed(colour=Colour.red(), title="Ticker: Ticker Deleted")
        embed.description = ment
        embed_utils.user_to_footer(embed, interaction.user)
        await view_itr.response.edit_message(embed=embed, view=None)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        await interaction.client.db.execute(sql, self.channel.id, timeout=60)


class TickerCog(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.workers: asyncio.Queue[Page] = asyncio.Queue(5)

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        for _ in range(WORKER_COUNT):
            page = await self.bot.browser.new_page()
            await self.workers.put(page)

    async def cog_unload(self) -> None:
        while not self.workers.empty():
            page = await self.workers.get()
            await page.close()

    async def get_config(
        self, interaction: Interaction, channel: discord.TextChannel | None
    ) -> Config | None:
        if channel is None:
            if isinstance(interaction.channel, discord.TextChannel):
                channel = interaction.channel
            else:
                return

        sql = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
        stg = await self.bot.db.fetchrow(sql, channel.id)
        if stg:
            sql = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
            lgs = await self.bot.db.fetch(sql, channel.id)
            objs = [self.bot.cache.get_competition(url=r["url"]) for r in lgs]
            leagues_ = [i for i in objs if i is not None]
            settings = TickerSettings.parse_obj(stg)
            return Config(interaction.user, channel, leagues_, settings)

        # else:
        # Ticker Verify -- NOT A SCORES CHANNEL
        sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""

        invalidate = await self.bot.db.fetchrow(sql, channel.id)

        if invalidate:
            err = "🚫 You cannot create a ticker in a livescores channel."
            embed = Embed(colour=Colour.red(), description=err)
            await interaction.response.edit_message(embed=embed)
            return None

        ment = channel.mention
        view = view_utils.Confirmation(interaction.user, "Create", "Cancel")
        view.true.style = discord.ButtonStyle.blurple

        embed = Embed(title="Create a ticker")
        embed.description = f"{ment} has no ticker, create one?"
        await interaction.response.send_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = Embed(colour=Colour.red())
            embed.description = f"❌ Cancelled ticker creation for {ment}"
            reply = view.interaction.response.edit_message
            await reply(embed=embed, view=None)
            return None

        guild = channel.guild.id

        dflt = fs.DEFAULT_LEAGUES
        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild)

                sql = """INSERT INTO ticker_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild, channel.id)

                sql3 = """INSERT INTO ticker_settings (channel_id) VALUES ($1)
                        ON CONFLICT DO NOTHING
                        RETURNING *"""
                settings = await connection.fetchrow(sql3, channel.id)

                sql4 = """INSERT INTO ticker_leagues (channel_id, url)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                rows = [(channel.id, x) for x in dflt]
                await connection.executemany(sql4, rows)

        cache = interaction.client.cache
        leagues = [cache.get_competition(url=i) for i in dflt]
        stg = TickerSettings.parse_obj(settings)
        return Config(
            interaction.user, channel, list(filter(None, leagues)), stg
        )

    async def refresh_table(self, comp: BaseCompetition | None) -> str | None:
        """Refresh table for object"""
        if comp is None:
            return None

        if "friendly" in comp.name.casefold():
            return None  # No.

        comp = fs.Competition.parse_obj(comp)  # Upgrade Base to actual.
        page = await self.workers.get()
        try:
            table = await comp.get_table(page, cache=self.bot.cache)
        finally:
            await self.workers.put(page)

        if table is None:
            return

        file = discord.File(fp=io.BytesIO(table.image), filename="table.png")
        channel = self.bot.get_channel(874655045633843240)
        if not isinstance(channel, discord.TextChannel):
            return None

        url = (await channel.send(file=file)).attachments[0].url
        self.bot.dispatch("table_update", comp, url)
        return url

    async def get_channels(
        self, fixture: BaseFixture, *args: str
    ) -> list[TextChannel]:
        if fixture.competition is None:
            return []

        sql = """
            SELECT ticker_settings.channel_id
            FROM ticker_settings INNER JOIN ticker_leagues
            ON ticker_settings.channel_id = ticker_leagues.channel_id WHERE
            url = $1 AND """ + " AND ".join(
            f"{i} IS TRUE" for i in args
        )
        records = await self.bot.db.fetch(sql, fixture.competition.url)

        bad: list[int] = []
        chans: list[discord.TextChannel] = []
        for i in records:
            chan = self.bot.get_channel(i["channel_id"])
            if not isinstance(chan, discord.TextChannel):
                continue

            if chan.is_news():
                bad.append(i["channel_id"])
                continue

            chans.append(chan)

        # if bad:
        #     logger.info("bad channels for ticker %s", len(bad))

        # DEBUG_CHANNEL = self.bot.get_channel(1107975381501353994)
        # if isinstance(DEBUG_CHANNEL, discord.TextChannel):
        #     chans.append(DEBUG_CHANNEL)
        return chans

    @commands.Cog.listener()
    async def on_fixture_abandoned(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "cancelled")
        MatchAbandoned(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_fixture_awarded(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "cancelled")
        MatchAwarded(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_fixture_cancelled(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "cancelled")
        Delayed(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_fixture_delayed(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "delays")
        Delayed(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_fixture_interrupted(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "delays")
        Interrupted(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_fixture_postponed(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "delays")
        Postponed(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_fixture_resumed(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "kick_offs")
        FixtureResumed(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_aet_result(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "full_times")
        AfterExtraTime(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_half_time(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "half_times")
        HalfTime(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_full_time(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "full_times")
        FullTime(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_final_result(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "final_results")
        FinalResult(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_goal(self, fix: BaseFixture, team: BaseTeam) -> None:
        chans = await self.get_channels(fix, "goals")
        try:
            table_url = await self.refresh_table(fix.competition)
        except PWTimeout:
            table_url = None
        Goal(self.bot, fix, chans, team, table_url)

    @commands.Cog.listener()
    async def on_var_goal(self, fix: BaseFixture, team: BaseTeam) -> None:
        chans = await self.get_channels(fix, "goals", "vars")
        VarGoal(self.bot, fix, chans, team)

    @commands.Cog.listener()
    async def on_kickoff(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "kick_offs")
        Kickoff(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_second_half(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "second_halfs")
        SecondHalf(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_period_begin(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "second_halfs")
        PeriodBegin(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_et_start(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "kick_offs", "extra_times")
        ExtraTime(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_et_ht_start(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "half_times", "extra_times")
        ExtraTimeHalfTime(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_et_ht_end(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "second_halfs", "extra_times")
        ExtraTimeSecondHalf(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_et_end(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "extra_times", "full_times")
        ExtraTimeEnd(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_penalty_results(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "penalties")
        PenaltyResults(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_penalties_start(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "penalties")
        PenaltiesStart(self.bot, fix, chans)

    @commands.Cog.listener()
    async def on_red_card(self, fix: BaseFixture, team: BaseTeam) -> None:
        chans = await self.get_channels(fix, "red_cards")
        RedCard(self.bot, fix, chans, team)

    @commands.Cog.listener()
    async def on_var_red_card(self, fix: BaseFixture, team: BaseTeam) -> None:
        chans = await self.get_channels(fix, "vars", "red_cards")
        VarRedCard(self.bot, fix, chans, team)

    @commands.Cog.listener()
    async def on_normal_time_end(self, fix: BaseFixture) -> None:
        chans = await self.get_channels(fix, "full_times", "extra_times")
        NormalTimeEnd(self.bot, fix, chans)

    ticker = discord.app_commands.Group(
        name="ticker",
        description="match event ticker",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @ticker.command()
    @discord.app_commands.describe(channel="Manage which channel?")
    async def manage(
        self,
        interaction: Interaction,
        channel: discord.TextChannel | None,
    ) -> None:
        """View the config of this channel's Match Event Ticker"""
        cfg = await self.get_config(interaction, channel)
        if cfg is None:
            return
        if interaction.response.is_done():
            send = interaction.edit_original_response
        else:
            send = interaction.response.send_message
        await send(view=cfg, embed=cfg.embeds[0])
        cfg.message = await interaction.original_response()

    @ticker.command(name="add_league")
    @discord.app_commands.describe(
        comp="Search for a league by name",
        channel="Add to which channel?",
    )
    async def add_tkr_league(
        self,
        interaction: Interaction,
        comp: comp_,
        channel: discord.TextChannel | None,
    ) -> None:
        """Add a league to your Match Event Ticker"""
        if comp.title == "WORLD: Club Friendly":
            err = "🚫 You can't add club friendlies as a competition, sorry."
            embed = Embed(colour=Colour.red(), description=err)
            return await interaction.response.send_message(embed=embed)

        if comp.url is None:
            err = "🚫 Invalid competition selected. Error logged."
            embed = Embed(colour=Colour.red(), description=err)
            logger.error("%s url is None", comp)
            return await interaction.response.send_message(embed=embed)

        cfg = await self.get_config(interaction, channel)
        if cfg is None:
            return

        embed = Embed(title="Ticker: Tracked League Added")
        embed.description = f"{cfg.channel.mention}\n\n{comp.url}"
        embed_utils.user_to_footer(embed, interaction.user)
        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""
        await interaction.client.db.execute(sql, cfg.channel.id, comp.url)

        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.edit_original_response(embed=embed, view=None)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: GuildChannel) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        await self.bot.db.execute(sql, channel.id, timeout=60)


async def setup(bot: Bot) -> None:
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(TickerCog(bot))
