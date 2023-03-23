"""Handler Cog for dispatched Fixture events, and database handling
   for channels using it."""
# TODO: Migrate Event embed generation to the individual Events
from __future__ import annotations  # Cyclic Type hinting

import asyncio
import io
import logging
import typing

import discord
from discord.ext import commands
from playwright.async_api import TimeoutError as pw_TimeoutError

import ext.toonbot_utils.flashscore as fs
import ext.toonbot_utils.matchevents as m_evt
from ext.fixtures import CompetitionTransformer
from ext.toonbot_utils.gamestate import GameState
from ext.utils import embed_utils, view_utils

if typing.TYPE_CHECKING:
    from core import Bot

_ticker_tasks = set()

logger = logging.getLogger("ticker.py")

NOPERMS = (
    "```yaml\nThis ticker channel will not work currently"
    "I am missing the following permissions.\n"
)

table_sem = asyncio.Semaphore(2)


async def get_table(bot: Bot, link: str):

    async with table_sem:
        page = await bot.browser.new_page()
        try:
            await page.goto(link, timeout=5000)

            # Chaining Locators is fucking stupid.
            # Thank you for coming to my ted talk.
            inner = page.locator(".tableWrapper")
            outer = page.locator("div", has=inner)
            table_div = page.locator("div", has=outer).last

            try:
                await table_div.wait_for(state="visible", timeout=5000)
            except pw_TimeoutError:
                return ""

            js = "ads => ads.forEach(x => x.remove());"
            await page.eval_on_selector_all(fs.ADS, js)

            image = await table_div.screenshot(type="png")
        finally:
            await page.close()
    return await bot.dump_image(io.BytesIO(image))


class TickerEvent:
    """Handles dispatching and editing messages for a fixture event."""

    bot: typing.ClassVar[Bot]

    def __init__(
        self,
        fixture: fs.Fixture,
        event_type: m_evt.EventType,
        channels: list[TickerChannel],
        long: bool = False,
        home: typing.Optional[bool] = None,
    ) -> None:

        self.fixture: fs.Fixture = fixture
        self.event_type: m_evt.EventType = event_type
        self.channels: list[TickerChannel] = channels
        self.long: bool = long
        self.home: typing.Optional[bool] = home

        self.initial_embed: typing.Optional[discord.Embed] = None

        # For exact event.
        self.event: typing.Optional[m_evt.MatchEvent] = None

        # Begin loop on init
        task = self.bot.loop.create_task(self.event_loop())
        _ticker_tasks.add(task)
        task.add_done_callback(_ticker_tasks.discard)

    async def embed(self) -> discord.Embed:
        """The embed for the fixture event."""
        if self.initial_embed is None:
            e = await self.fixture.base_embed()

            e.title = self.fixture.score_line
            e.url = self.fixture.url
            e.colour = self.event_type.colour
            e.description = ""

            b = self.fixture.breaks
            m = self.event_type.value.replace("#PERIOD#", f"{b + 1}")

            if self.home is None:
                e.set_author(name=m)
            elif self.home is True:
                e.set_author(name=f"{m} ({self.fixture.home.name})")
            else:
                e.set_author(name=f"{m} ({self.fixture.away.name})")

            comp = self.fixture.competition
            c = f" | {comp.title}" if comp else ""

            if isinstance(self.fixture.time, GameState):
                if self.fixture.state:
                    sh = self.fixture.state.shorthand
                    e.set_footer(text=f"{sh}{c}")
            else:
                e.set_footer(text=f"{self.fixture.time}{c}")

            if self.event_type == m_evt.EventType.PENALTY_RESULTS:
                ph = self.fixture.penalties_home
                pa = self.fixture.penalties_away
                if ph is None or pa is None:
                    e.description = self.fixture.score_line
                else:
                    h, a = ("**", "") if ph > pa else ("", "**")
                    score = f"{ph} - {pa}"
                    home = f"{h}{self.fixture.home.name}{h}"
                    away = f"{a}{self.fixture.away.name}{a}"
                    e.description = f"{home} {score} {away}\n"

            self.initial_embed = e
        else:
            e = self.initial_embed

        # Fix Breaks.
        if self.event_type == m_evt.EventType.PENALTY_RESULTS:
            ph = self.fixture.penalties_home
            pa = self.fixture.penalties_away

            pens = []
            for i in self.fixture.events:
                if not isinstance(i, m_evt.Penalty):
                    continue
                if not i.shootout:
                    continue
                pens.append(i)

            # iterate through everything after penalty header
            for team in set(i.team for i in pens):
                if value := [str(i) for i in pens if i.team == team]:
                    e.add_field(name=team, value="\n".join(value))

        # Append our event
        if self.event is not None:
            e.description = f"{e.description}{str(self.event)}"
            if self.event.description:
                e.description += f"\n\n> {self.event.description}"

        # Append extra info
        if (ib := self.fixture.infobox) is not None:
            e.add_field(name="Match Info", value=f"```yaml\n{ib}```")
        return e

    async def full_embed(self) -> discord.Embed:
        """Extended Embed with all events for Extended output event_type"""
        e = await self.embed()
        e.description = str(e.description)

        if self.event is not None and len(self.fixture.events) > 1:
            e.description += "\n```yaml\n--- Previous Events ---```"

        desc = []
        for i in self.fixture.events:
            if i == self.event:
                continue

            if isinstance(i, m_evt.Substitution):
                continue  # skip subs, they're just spam.

            # Penalty Shootouts are handled in self.embed,
            # we don't need to duplicate.
            if isinstance(i, m_evt.Penalty) and i.shootout:
                continue

            if str(i) not in e.description:  # Dupes bug.
                desc.append(str(i))

        e.description += "\n".join(desc)
        return e

    async def event_loop(self) -> None:
        """The Fixture event's internal loop"""
        if not self.channels:
            return  # This should never happen.

        # Handle Match Events with no game events.
        if self.event_type == m_evt.EventType.KICK_OFF:
            e = await self.embed()
            for x in self.channels:
                await x.output(self, e)
            return  # Done.

        index: typing.Optional[int] = None
        for x in range(5):
            await self.fixture.refresh(self.bot)

            # Figure out which event we're supposed to be using
            # (Either newest event, or Stored if refresh)
            if index is None:
                if self.home is None:
                    team = None
                elif self.home is True:
                    team = self.fixture.home
                else:
                    team = self.fixture.away

                events = self.fixture.events
                if team is not None:
                    t = team.name
                    evt = filter(lambda i: i.team and i.team.name == t, events)
                    events = list(evt)

                valid: typing.Type[
                    m_evt.MatchEvent
                ] = self.event_type.valid_events
                if valid and events:
                    events.reverse()
                    try:
                        ev = [i for i in events if isinstance(i, valid)][0]
                        self.event = ev
                        index = self.fixture.events.index(self.event)
                    except IndexError:
                        ev = "\n".join(set(str(type(i)) for i in events))
                        logger.error("Can't find %s in %s", valid, ev)
                        logger.error(f"Event is {self.event_type}")

            else:
                try:
                    self.event = self.fixture.events[index]
                except IndexError:
                    self.event = None
                    break

            if self.long and index:
                evts = self.fixture.events[: index + 1]
                if all(i.player is not None for i in evts):
                    break
            else:
                if self.event and self.event.player:
                    break

            full = await self.full_embed() if self.long else None
            short = await self.embed()

            for ch in self.channels:
                await ch.output(self, short, full)

            await asyncio.sleep(x + 1 * 60)

        full = await self.full_embed() if self.long else None
        short = await self.embed()
        for ch in self.channels:
            await ch.output(self, short, full)


class TickerChannel:
    """An object representing a channel with a Match Event Ticker"""

    bot: typing.ClassVar[Bot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: set[fs.Competition] = set()
        self.dispatched: dict[TickerEvent, discord.Message] = {}

        # Settings
        self.goals: typing.Optional[bool] = None
        self.kick_offs: typing.Optional[bool] = None
        self.full_times: typing.Optional[bool] = None
        self.half_times: typing.Optional[bool] = None
        self.second_halfs: typing.Optional[bool] = None
        self.red_cards: typing.Optional[bool] = None
        self.final_results: typing.Optional[bool] = None
        self.penalties: typing.Optional[bool] = None
        self.delays: typing.Optional[bool] = None
        self.vars: typing.Optional[bool] = None
        self.extra_times: typing.Optional[bool] = None

    # Send messages
    async def output(
        self,
        event: TickerEvent,
        short_embed: discord.Embed,
        full_embed: typing.Optional[discord.Embed] = None,
    ) -> typing.Optional[discord.Message]:
        """Send the appropriate embed to this channel"""
        # Check if we need short or long embed.
        # For each stored db_field value,
        # we check against our own settings field.

        type_ = event.event_type

        e = short_embed
        if full_embed is None or type_ == m_evt.EventType.KICK_OFF:
            pass

        elif type_ == m_evt.EventType.GOAL:
            if self.goals is True:
                e = full_embed

        elif type_ == m_evt.EventType.HALF_TIME:
            if self.half_times is True:
                e = full_embed

        elif type_ == m_evt.EventType.SECOND_HALF_BEGIN:
            if self.second_halfs is True:
                e = full_embed

        elif type_ == m_evt.EventType.FULL_TIME:
            if self.full_times is True:
                e = full_embed

        elif type_ == m_evt.EventType.FINAL_RESULT_ONLY:
            if self.final_results is True:
                e = full_embed

        elif type_ == m_evt.EventType.PENALTY_RESULTS:
            if self.penalties is True:
                e = full_embed

        else:
            logger.error("unhandled embed decision for evt %s", type_)

        try:
            try:
                message = self.dispatched[event]
                # Save on ratelimiting by checking.
                if message.embeds[0] is not None:
                    if message.embeds[0].description == e.description:
                        return None
                message = await message.edit(embed=e)
            except KeyError:
                message = await self.channel.send(embed=e)
        except discord.HTTPException:
            return None

        self.dispatched[event] = message
        return message

    # Database management.
    async def configure_channel(self) -> None:
        """Retrieve the settings of the TickerChannel from the database"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM ticker_settings WHERE channel_id = $1"""
                stg = await connection.fetchrow(sql, self.channel.id)
                sql = """SELECT * FROM ticker_leagues WHERE channel_id = $1"""
                leagues = await connection.fetch(sql, self.channel.id)

        if stg is not None:
            for k, v in stg.items():
                if k == "channel_id":
                    continue
                setattr(self, k, v)

        for record in leagues:
            if comp := self.bot.get_competition(record["url"].rstrip("/")):
                self.leagues.add(comp)
            else:
                logger.error("Could not find comp %s", record)


class ToggleButton(discord.ui.Button):
    """A Button to toggle the ticker settings."""

    view: TickerConfig

    def __init__(self, db_key: str, value: bool | None, row: int = 0):
        self.value: bool | None = value
        self.db_key: str = db_key

        if value is None:
            emoji = "🔴"  # None (Off)
            style = discord.ButtonStyle.red
        elif value:
            emoji = "🔵"
            style = discord.ButtonStyle.blurple
        else:
            emoji = "🟢"
            style = discord.ButtonStyle.green

        title = db_key.replace("_", " ").title()

        if title == "Redcard":
            title = "Red Cards"
        elif title == "Var":
            title = "VAR Reviews"
        elif title == "Penalties":
            title = "Penalty Shootouts"
        super().__init__(label=title, emoji=emoji, row=row, style=style)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Set view value to button value"""

        await interaction.response.defer()

        # Rotate between the three values.
        new_value = {True: None, False: True, None: False}[self.value]

        bot = interaction.client
        sql = f"""UPDATE ticker_settings SET {self.db_key} = $1
               WHERE channel_id = $2"""
        ch = self.view.tc.channel.id
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, new_value, ch)

        setattr(self.view.tc, self.db_key, new_value)
        return await self.view.update()


class ResetLeagues(discord.ui.Button):
    """Button to reset a ticker back to the default leagues"""

    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(
            label="Reset Ticker", style=discord.ButtonStyle.primary
        )

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Click button reset leagues"""
        await interaction.response.defer()

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM ticker_leagues WHERE channel_id = $1"""
                await connection.execute(sql, self.view.tc.channel.id)

                sql = """INSERT INTO ticker_leagues (channel_id, url)
                    VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                r = [(self.view.tc.channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql, r)

        for x in fs.DEFAULT_LEAGUES:
            if (comp := interaction.client.get_competition(x)) is None:
                continue
            self.view.tc.leagues.add(comp)

        e = discord.Embed(title="Ticker: Tracked Leagues Reset")
        e.description = self.view.tc.channel.mention
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        await interaction.followup.send(embed=e)
        return await self.view.update()


class DeleteTicker(discord.ui.Button):
    """Button to delete a ticker entirely"""

    view: TickerConfig

    def __init__(self) -> None:
        super().__init__(label="Delete ticker", style=discord.ButtonStyle.red)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Click button delete ticker"""
        await interaction.response.defer()

        intr = self.view.interaction
        style = discord.ButtonStyle.red
        view = view_utils.Confirmation(intr, "Confirm", "Cancel", style)

        ch = self.view.tc.channel.mention
        e = discord.Embed(colour=discord.Colour.red())
        e.description = (
            f"Are you sure you wish to delete the ticker from {ch}?"
            "\n\nThis action cannot be undone."
        )

        await intr.edit_original_response(view=view, embed=e)

        if not view.value:
            return await self.view.update()

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.view.tc.channel.id)

        interaction.client.ticker_channels.remove(self.view.tc)

        e = discord.Embed(colour=discord.Colour.red())
        e.description = f"The Ticker for {ch} was deleted."
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        return await intr.edit_original_response(embed=e, view=None)


class RemoveLeague(discord.ui.Select):
    """Dropdown to remove leagues from a match event ticker."""

    view: TickerConfig

    def __init__(self, leagues: list[fs.Competition], row: int = 2) -> None:
        ph = "Remove tracked league(s)"
        super().__init__(placeholder=ph, row=row, max_values=len(leagues))

        for lg in leagues:
            if lg.url is None:
                continue

            opt = discord.SelectOption(label=lg.title, value=lg.url)
            opt.description = lg.url
            opt.emoji = lg.flag
            self.add_option(label=lg.title, description=lg.url, value=lg.url)

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When a league is selected, delete channel / league row from DB"""

        await interaction.response.defer()

        red = discord.ButtonStyle.red
        itr = self.view.interaction
        view = view_utils.Confirmation(itr, "Remove", "Cancel", red)

        lg_text = "```yaml\n" + "\n".join(sorted(self.values)) + "```"
        c = self.view.tc.channel.mention

        e = discord.Embed(title="Ticker", colour=discord.Colour.red())
        e.description = f"Remove these leagues from {c}?\n{lg_text}"
        await self.view.interaction.edit_original_response(embed=e, view=view)
        await view.wait()

        if not view.value:
            return await self.view.update()

        sql = """DELETE from ticker_leagues
                 WHERE (channel_id, url) = ($1, $2)"""
        rows = [(self.view.tc.channel.id, x) for x in self.values]
        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        for i in self.view.tc.leagues.copy():
            if i.url in self.values:
                self.view.tc.leagues.remove(i)

        m = self.view.tc.channel.mention
        msg = f"Removed {m} tracked leagues:\n{lg_text}"
        e = discord.Embed(description=msg, colour=discord.Colour.red())
        e.title = "Ticker"
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        await self.view.interaction.followup.send(content=msg)
        return await self.view.update()


class TickerConfig(view_utils.BaseView):
    """Match Event Ticker View"""

    interaction: discord.Interaction[Bot]
    bot: Bot

    def __init__(
        self, interaction: discord.Interaction[Bot], tc: TickerChannel
    ):
        super().__init__(interaction)
        self.tc: TickerChannel = tc

    async def update(self) -> discord.InteractionMessage:
        """Regenerate view and push to message"""
        self.clear_items()

        embed = discord.Embed(colour=discord.Colour.dark_teal())
        embed.title = "Match Event Ticker config"

        t = "Button Colour Key\nRed: Off, Green: On, Blue: Extended"
        embed.set_footer(text=t)

        missing = []

        ch = self.tc.channel
        perms = ch.permissions_for(ch.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=v)

        edit = self.interaction.edit_original_response
        if not self.tc.leagues:
            self.add_item(ResetLeagues())
            self.add_item(DeleteTicker())
            embed.description = f"{ch.mention} has no tracked leagues."
            return await edit(embed=embed, view=self)

        embed.description = f"Tracked leagues for {ch.mention}\n\n"
        leagues = sorted(self.tc.leagues, key=lambda x: x.title)

        self.pages = embed_utils.paginate(leagues)
        self.add_page_buttons()

        leagues: list[fs.Competition]
        lg_text = [f"{i.flag} {i.markdown}" for i in self.pages[self.index]]

        embed.description += "\n".join(lg_text)

        self.add_item(RemoveLeague(leagues, row=1))

        count = 0

        for k in [
            "goals",
            "kick_offs",
            "full_times",
            "half_times",
            "second_halfs",
            "red_cards",
            "final_results",
            "penalties",
            "delays",
            "vars",
            "extra_times",
        ]:
            row = 2 + count // 5
            self.add_item(
                ToggleButton(db_key=k, value=getattr(self.tc, k), row=row)
            )

            count += 1

        return await edit(embed=embed, view=self)


class Ticker(commands.Cog):
    """Get updates whenever match events occur"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        TickerEvent.bot = bot
        TickerChannel.bot = bot

        self.bot.ticker_channels.clear()

    async def cog_load(self) -> None:
        """Reset the cache on load."""
        await self.update_cache()

    async def create(
        self,
        interaction: discord.Interaction[Bot],
        channel: discord.TextChannel,
    ) -> discord.InteractionMessage:
        """Send a dialogue to create a new ticker."""
        # Ticker Verify -- NOT A SCORES CHANNEL
        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():

                q = """SELECT * FROM scores_channels WHERE channel_id = $1"""

                invalidate = await connection.fetchrow(q, channel.id)
            if invalidate:
                err = "You cannot create a ticker in a livescores channel."
                return await self.bot.error(interaction, err)

        c = channel.mention
        btn = discord.ButtonStyle.green
        view = view_utils.Confirmation(
            interaction, "Create ticker", "Cancel", btn
        )

        e = discord.Embed(title="Create a ticker")
        e.description = f"{c} has no ticker, would you like to create one?"
        await interaction.edit_original_response(embed=e, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled ticker creation for {c}"
            return await self.bot.error(interaction, txt)

        guild = channel.guild.id

        async with self.bot.db.acquire(timeout=60) as connection:
            # Verify that this is not a livescores channel.
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, guild)

                q = """INSERT INTO ticker_channels (guild_id, channel_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(q, guild, channel.id)

                qq = """INSERT INTO ticker_settings (channel_id) VALUES ($1)
                        ON CONFLICT DO NOTHING"""
                await connection.execute(qq, channel.id)

                qqq = """INSERT INTO ticker_leagues (channel_id, url)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                rows = [(channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(qqq, rows)

        tc = TickerChannel(channel)
        await tc.configure_channel()
        self.bot.ticker_channels.append(tc)
        return await TickerConfig(interaction, tc).update()

    async def update_cache(self) -> list[TickerChannel]:
        """Store a list of all Ticker Channels into the bot"""
        sql = """SELECT DISTINCT channel_id FROM ticker_channels"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        bad = set()
        for r in records:
            ch = self.bot.get_channel(r["channel_id"])
            if ch is None:
                bad.add(r["channel_id"])
                continue

            ch = typing.cast(discord.TextChannel, ch)

            tc = TickerChannel(ch)
            await tc.configure_channel()
            self.bot.ticker_channels.append(tc)

        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        if self.bot.ticker_channels:
            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    for _id in bad:
                        await connection.execute(sql, _id)
        return self.bot.ticker_channels

    @commands.Cog.listener()
    async def on_fixture_event(
        self,
        event_type: m_evt.EventType,
        fixture: fs.Fixture,
        home: typing.Optional[bool] = None,
    ) -> typing.Optional[TickerEvent]:
        """Event handler for when something occurs during a fixture."""
        # Update the competition's Table on certain events.

        if not fixture.competition:
            return

        url = fixture.competition.url

        if url is None:
            return

        channels: list[TickerChannel] = []
        for i in self.bot.ticker_channels:
            if fixture.competition in i.leagues:
                channels.append(i)

        long = False

        evt = m_evt.EventType

        if event_type == evt.KICK_OFF:
            channels = [i for i in channels if i.kick_offs is not None]

        elif event_type == evt.GOAL:
            channels = [i for i in channels if i.goals is not None]

            if channels:
                fixture.competition.table = await get_table(self.bot, url)

            long: bool = any([i.goals is True for i in channels])

        elif event_type == evt.VAR_GOAL:
            channels = [i for i in channels if None not in [i.goals, i.vars]]

            long: bool = any([all([i.goals, i.vars]) for i in channels])

        elif event_type == evt.RED_CARD:
            channels = [i for i in channels if i.red_cards is not None]

            long: bool = any([i.red_cards is True for i in channels])

        elif event_type == evt.HALF_TIME:
            channels = [i for i in channels if i.half_times is not None]

            long: bool = any([i.half_times is True for i in channels])

        elif event_type == evt.SECOND_HALF_BEGIN:
            channels = [i for i in channels if i.second_halfs is not None]

            long: bool = any([i.second_halfs is True for i in channels])

        elif event_type in [evt.FULL_TIME, evt.NORMAL_TIME_END]:
            channels = [i for i in channels if i.goals is not None]

            if channels:
                fixture.competition.table = await get_table(self.bot, url)

            long: bool = any([i.full_times is True for i in channels])

        elif event_type in [evt.EXTRA_TIME_BEGIN, evt.EXTRA_TIME_END]:
            channels = [i for i in channels if i.extra_times is not None]

            long: bool = any([i.extra_times is True for i in channels])

        elif event_type == evt.HALF_TIME_ET_BEGIN:
            channels = [i for i in channels if i.extra_times is not None]
            channels = [i for i in channels if i.half_times is not None]

            for i in channels:
                if i.extra_times is True and i.half_times is True:
                    long = True
                    break

        elif event_type == evt.HALF_TIME_ET_END:
            channels = [i for i in channels if i.extra_times is not None]
            channels = [i for i in channels if i.second_halfs is not None]

            for i in channels:
                if i.extra_times is True and i.second_halfs is True:
                    long = True
                    break

        elif event_type in [evt.PENALTIES_BEGIN, evt.PENALTY_RESULTS]:
            channels = [i for i in channels if i.penalties is not None]

            long: bool = any([i.penalties is True for i in channels])

        elif event_type == evt.FINAL_RESULT_ONLY:
            channels = [i for i in channels if i.final_results is not None]

            long: bool = any([i.final_results is True for i in channels])

        else:
            logger.info("Ticker -- Unhandled Event Type %s", event_type)

        if not channels:
            return
        return TickerEvent(fixture, event_type, channels, long, home)

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
        interaction: discord.Interaction[Bot],
        channel: typing.Optional[discord.TextChannel],
    ) -> discord.InteractionMessage:
        """View the config of this channel's Match Event Ticker"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        # Validate channel is a ticker channel.
        try:
            tkrs = self.bot.ticker_channels
            tc = next(i for i in tkrs if i.channel.id == channel.id)
        except StopIteration:
            return await self.create(interaction, channel)
        return await TickerConfig(interaction, tc).update()

    @ticker.command()
    @discord.app_commands.describe(
        competition="Search for a league by name",
        channel="Add to which channel?",
    )
    async def add_league(
        self,
        interaction: discord.Interaction[Bot],
        competition: discord.app_commands.Transform[
            fs.Competition, CompetitionTransformer
        ],
        channel: typing.Optional[discord.TextChannel],
    ) -> discord.InteractionMessage:
        """Add a league to your Match Event Ticker"""

        if competition.title == "WORLD: Club Friendly":
            err = "You can't add club friendlies as a competition, sorry."
            raise ValueError(err)

        if competition.url is None:
            raise LookupError("%s url is None", competition)

        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        chn = self.bot.ticker_channels
        try:
            tc = next(i for i in chn if i.channel.id == channel.id)
        except StopIteration:
            return await self.create(interaction, channel)

        # Find the Competition Object.
        sql = """INSERT INTO ticker_leagues (channel_id, url)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id, competition.url)

        tc.leagues.add(competition)
        e = discord.Embed(title="Ticker: Tracked League Added")
        e.description = f"{tc.channel.mention}\n\n{competition.url}"
        u = interaction.user
        e.set_footer(text=f"{u}\n{u.id}", icon_url=u.display_avatar.url)
        return await interaction.edit_original_response(embed=e)

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Handle delete channel data from database upon channel deletion."""
        sql = """DELETE FROM ticker_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        for x in self.bot.ticker_channels.copy():
            if x.channel.id == channel.id:
                self.bot.ticker_channels.remove(x)


async def setup(bot: Bot):
    """Load the goal tracker cog into the bot."""
    await bot.add_cog(Ticker(bot))
