"""This Cog Grabs data from Flashscore and outputs the latest scores to user
-configured live score channels"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from importlib import reload
from itertools import zip_longest
from typing import TYPE_CHECKING, ClassVar, Optional
import typing

import discord
from asyncpg import Record
from discord import (
    TextChannel,
    ButtonStyle,
    Colour,
    Embed,
    PermissionOverwrite,
    Permissions,
    Message,
    Forbidden,
    NotFound,
)
from discord.app_commands import Group
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import Button, Select
from lxml.etree import ParserError, tostring
from lxml.html import fromstring
from ext.fixtures import fetch_comp
from ext.ticker import lg_ac

import ext.toonbot_utils.flashscore as fs
from ext.toonbot_utils.gamestate import GameState
from ext.toonbot_utils.matchevents import EventType
from ext.utils.embed_utils import rows_to_embeds, stack_embeds
from ext.utils.view_utils import Confirmation, BaseView

if TYPE_CHECKING:
    from discord import Interaction
    from core import Bot

logger = logging.getLogger("scores")

# Constants.
NO_GAMES_FOUND = (
    "No games found for your tracked leagues today!\n\nYou can"
    " add more leagues with `/livescores add`"
)


class ScoreChannel:
    """A livescore channel object, containing it's properties."""

    bot: ClassVar[Bot]

    def __init__(self, channel: TextChannel) -> None:
        self.channel: TextChannel = channel
        self.messages: list[Message | None] = [None, None, None, None, None]
        self.leagues: list[str] = []

    def generate_embeds(self) -> list[Embed]:
        """Have each Competition generate it's livescore embeds"""
        embeds = []
        games = self.bot.games.copy()

        for comp in set(i.competition for i in games if i.competition):
            for tracked in self.leagues:
                if tracked == comp.title:
                    embeds += comp.score_embeds
                    break

                elif f"{tracked} -" in comp.title:
                    # For Competitions Such as
                    # EUROPE: Champions League - Playoffs,
                    # where we want fixtures of a part # of a tournament,
                    # we need to do additional checks. We are not,
                    # for example, interested in U18, or
                    # women's tournaments unless explicitly tracked
                    for x in ["women", "u18"]:  # List of ignored substrings
                        if x in comp.title.casefold() and x not in tracked:
                            # Break without doing anything
                            # this sub-tournament was not requested.
                            break
                    else:
                        # If we do not break, we can fetch the score embeds
                        #  for that league.
                        embeds += comp.score_embeds
                        break

        if not embeds:
            return [Embed(title="No Games Found", description=NO_GAMES_FOUND)]
        return embeds

    async def get_leagues(self) -> list[str]:
        """Fetch target leagues for the ScoreChannel from the database"""

        sql = """SELECT league FROM scores_leagues WHERE channel_id = $1"""

        async with self.bot.db.acquire(timeout=60) as c:
            async with c.transaction():
                records: list[Record] = await c.fetch(sql, self.channel.id)

        self.leagues = [r["league"] for r in records]
        return self.leagues

    async def reset_leagues(self) -> list[str]:
        """Reset the Score Channel to the list of default leagues."""
        async with self.bot.db.acquire(timeout=60) as c:
            async with c.transaction():
                sql = """DELETE FROM scores_leagues WHERE channel_id = $1"""
                await c.execute(sql, self.channel.id)

                sql = """INSERT INTO scores_leagues (channel_id, league)
                         VALUES ($1, $2)"""

                r = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await c.executemany(sql, r)
        self.leagues = fs.DEFAULT_LEAGUES
        return self.leagues

    async def add_leagues(self, leagues: list[str]) -> list[str]:
        """Add a league to the ScoreChannel's tracked list"""

        sql = """INSERT INTO scores_leagues (channel_id, league)
                 VALUES ($1, $2) ON CONFLICT DO NOTHING"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rows = [(self.channel.id, x) for x in leagues]
                await connection.executemany(sql, rows)

        self.leagues += [i for i in leagues if i not in self.leagues]
        return self.leagues

    async def remove_leagues(self, leagues: list[str]) -> list[str]:
        """Remove a list of leagues for the channel from the database"""

        sql = """DELETE from scores_leagues
                 WHERE (channel_id, league) = ($1, $2)"""

        rows = [(self.channel.id, x) for x in leagues]

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        self.leagues = [i for i in self.leagues if i not in leagues]
        return self.leagues

    async def update(self) -> list[Message | None]:
        """Edit a live-score channel to have the latest scores"""
        if self.channel.is_news():
            return []

        if not self.leagues:
            await self.get_leagues()

        embeds = self.generate_embeds()

        # Stack embeds to max size for individual message.
        stacked = stack_embeds(embeds)

        # Zip the lists into tuples to simultaneously iterate
        # Limit to 5 max
        tuples = list(zip_longest(self.messages, stacked))[:5]

        message: Message | None

        # Zip longest will give (, None) in slot [0] // self.messages
        # if we do not have enough messages for the embeds.
        count = 0
        for message, embeds in tuples:
            try:
                # Suppress Message's embeds until they're needed again.
                if message is None and embeds is None:
                    continue

                if message is None:
                    # No message exists in cache,
                    # or we need an additional message.
                    m = await self.channel.send(embeds=embeds)
                    self.messages[count] = m
                    continue
            except discord.Forbidden:
                # If we don't have permissions to send Messages in the channel,
                # remove it and stop iterating.
                self.bot.score_channels.remove(self)
                return []
            except discord.HTTPException:
                continue

            try:
                if embeds is None:
                    if not message.flags.suppress_embeds:
                        m = await message.edit(suppress=True)
                        self.messages[count] = m
                    continue

                new = Counter([i.description for i in embeds])
                old = Counter([i.description for i in message.embeds])
                if not old == new:
                    m = await message.edit(embeds=embeds, suppress=False)
                    self.messages[count] = m
            except discord.NotFound:
                self.bot.score_channels.remove(self)
                return []
            except discord.HTTPException:
                continue
            finally:
                count += 1
        return self.messages

    def view(self, interaction: Interaction[Bot]) -> ScoresConfig:
        """Get a view representing this score channel"""
        return ScoresConfig(interaction, self)


class ScoresConfig(BaseView):
    """Generic Config View"""

    def __init__(
        self, interaction: Interaction[Bot], channel: ScoreChannel
    ) -> None:
        super().__init__(interaction)
        self.sc: ScoreChannel = channel

    async def update(self, content: Optional[str]) -> Message:
        """Push the newest version of view to message"""
        self.clear_items()

        embed: Embed = Embed(colour=Colour.dark_teal())

        usr = typing.cast(discord.Member, self.bot.user)
        embed.title = f"{usr.name} Live Scores config"
        embed.set_thumbnail(url=usr.display_avatar.url)

        missing = []
        perms = self.sc.channel.permissions_for(self.sc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")
        if not perms.manage_messages:
            missing.append("manage_messages")

        if missing:
            v = (
                "```yaml\nThis livescores channel will not work currently,"
                " I am missing the following permissions.\n"
            )
            embed.add_field(
                name="Missing Permissions", value=f"{v} {missing}```"
            )

        if leagues := await self.sc.get_leagues():
            header = f"Tracked leagues for {self.sc.channel.mention}```yaml\n"
            embeds = rows_to_embeds(embed, sorted(leagues), 25, header, "```")
            self.pages = embeds
            self.add_page_buttons(row=1)
            embed = self.pages[self.index]

            if len(leagues) > 25:
                if len(leagues := leagues[self.index * 25 :]) > 25:
                    leagues = leagues[:25]

            self.add_item(RemoveLeague(leagues, row=0))
        else:
            self.add_item(ResetLeagues())
            c = self.sc.channel.mention
            d = f"No tracked leagues for {c}, would you like to reset it?"
            embed.description = d

        return await self.bot.reply(
            self.interaction, content=content, embed=embed, view=self
        )

    async def remove_leagues(self, leagues: list[str]) -> Message:
        """Bulk remove leagues from a live scores channel"""
        # Ask user to confirm their choice.
        view = Confirmation(
            self.interaction,
            label_a="Remove",
            label_b="Cancel",
            style_a=ButtonStyle.red,
        )

        lg_txt = "\n".join(sorted(leagues))
        c = self.sc.channel.mention
        txt = f"Remove these leagues from {c}? ```yaml\n{lg_txt}```"
        await self.bot.reply(self.interaction, txt, embed=None, view=view)
        await view.wait()

        if not view.value:
            return await self.update(content="No leagues were removed")

        await self.sc.remove_leagues(leagues)
        m = self.sc.channel.mention
        msg = f"Removed {m} tracked leagues: ```yaml\n{lg_txt}```"
        return await self.update(content=msg)


class ResetLeagues(Button):
    """Button to reset a live score channel back to the default leagues"""

    def __init__(self) -> None:
        super().__init__(
            label="Reset to default leagues", style=discord.ButtonStyle.primary
        )

    async def callback(self, interaction: Interaction) -> Message:
        """Click button reset leagues"""
        v = typing.cast(ScoresConfig, self.view)

        await interaction.response.defer()
        await v.sc.reset_leagues()
        msg = f"Tracked leagues for {v.sc.channel.mention} reset"
        return await v.update(msg)


class RemoveLeague(Select):
    """Button to bring up the remove leagues dropdown."""

    def __init__(self, leagues: list[str], row: int = 4) -> None:
        ph = "Remove tracked league(s)"
        super().__init__(placeholder=ph, row=row, max_values=len(leagues))
        [self.add_option(label=lg) for lg in sorted(leagues)]

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected"""
        await interaction.response.defer()
        v = typing.cast(ScoresConfig, self.view)
        return await v.remove_leagues(self.values)


class Scores(Cog):
    """Live Scores channel module"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

        reload(fs)

        fs.FlashScoreItem.bot = bot
        ScoreChannel.bot = bot

    async def cog_load(self) -> None:
        """Load our database into the bot"""
        await self.load_database()
        self.bot.scores = self.score_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.bot.scores.cancel()
        self.bot.score_channels.clear()

    # Database load: Leagues & Teams
    async def load_database(self) -> None:
        """Load all stored leagues and competitions into the bot"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * from fs_competitions"""
                comps = await connection.fetch(sql)
                teams = await connection.fetch("""SELECT * from fs_teams""")

        for c in comps:
            if self.bot.get_competition(c["id"]) is None:
                cm = fs.Competition(c["id"], c["name"], c["country"], c["url"])
                cm.logo_url = c["logo_url"]
                self.bot.competitions.append(cm)

        for t in teams:
            if self.bot.get_team(t["id"]) is None:
                team = fs.Team(t["id"], t["name"], t["url"])
                team.logo_url = t["logo_url"]
                self.bot.teams.append(team)

    # Database load: ScoreChannels
    async def update_cache(self) -> list[ScoreChannel]:
        """Grab the most recent data for all channel configurations"""

        sql = """SELECT * FROM scores_leagues"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        # Generate {channel_id: [league1, league2, league3, …]}
        channel_leagues = defaultdict(list)
        for r in records:
            channel_leagues[r["channel_id"]].append(r["league"])

        chans = self.bot.score_channels
        for channel_id, leagues in channel_leagues.items():

            channel = self.bot.get_channel(channel_id)

            if not isinstance(channel, discord.TextChannel):
                continue

            if channel.is_news():
                continue

            try:
                sc = next(i for i in chans if i.channel.id == channel_id)
            except StopIteration:
                sc = ScoreChannel(channel)
                chans.append(sc)
            sc.leagues = sorted(leagues)
        return chans

    # Core Loop
    @loop(minutes=1)
    async def score_loop(self) -> None:
        """Score Checker Loop"""
        if not self.bot.score_channels:
            await self.update_cache()

        try:
            self.bot.games = await self.fetch_games()
        except ConnectionError:
            logger.warning("Connection Error fetching games from Flashscore")
            return

        # Used for ordinal checking,
        now = datetime.now(tz=timezone(timedelta(hours=1)))
        ordinal = now.toordinal()

        # Discard yesterday's games.
        self.bot.games = [g for g in self.bot.games if g.active(ordinal)]

        comps = set(i.competition for i in self.bot.games if i.competition)

        for comp in comps.copy():
            e = (await comp.base_embed()).copy()

            flt = [i for i in self.bot.games if i.competition == comp]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [i.live_score_text for i in fix]

            table = f"\n[View Table]({comp.table})" if comp.table else ""
            comp.score_embeds = rows_to_embeds(e, ls_txt, 50, footer=table)

        for sc in self.bot.score_channels.copy():
            await sc.update()

    @score_loop.before_loop
    async def clear_old_scores(self):
        """Purge old messages from livescore channels before starting up."""
        await self.bot.wait_until_ready()

        if not self.bot.score_channels:
            await self.update_cache()

        def is_bot_msg(m):
            return m.author.id == self.bot.application_id

        for x in self.bot.score_channels:
            try:
                await x.channel.purge(
                    reason="Clearing score-channel.",
                    check=is_bot_msg,
                    limit=20,
                )
            except (Forbidden, NotFound):
                pass

    def dispatch_states(self, fx: fs.Fixture, old: GameState) -> None:
        """Dispatch events to the ticker"""
        evt = "fixture_event"
        send_event = self.bot.dispatch

        new = fx.state

        if old == new or old is None:
            return

        match new:
            case GameState.ABANDONED:
                return send_event(evt, EventType.ABANDONED, fx)
            case GameState.AFTER_EXTRA_TIME:
                return send_event(evt, EventType.SCORE_AFTER_EXTRA_TIME, fx)
            case GameState.AFTER_PENS:
                return send_event(evt, EventType.PENALTY_RESULTS, fx)
            case GameState.BREAK_TIME:
                match old:
                    # Break Time = after regular time & before penalties
                    case GameState.EXTRA_TIME:
                        return send_event(evt, EventType.EXTRA_TIME_END, fx)
                    case _:
                        fx.breaks += 1
                        if fx.periods is not None:
                            event = EventType.PERIOD_END
                        else:
                            event = EventType.NORMAL_TIME_END
                        return send_event(evt, event, fx)
            case GameState.CANCELLED:
                return send_event(evt, EventType.CANCELLED, fx)
            case GameState.DELAYED:
                return send_event(evt, EventType.DELAYED, fx)
            case GameState.EXTRA_TIME:
                match old:
                    case GameState.HALF_TIME:
                        return send_event(evt, EventType.HALF_TIME_ET_END, fx)
                    case _:
                        return send_event(evt, EventType.EXTRA_TIME_BEGIN, fx)
            case GameState.FULL_TIME:
                match old:
                    case GameState.EXTRA_TIME:
                        return send_event(
                            evt,
                            EventType.SCORE_AFTER_EXTRA_TIME,
                            fx,
                        )
                    case GameState.SCHEDULED | GameState.HALF_TIME:
                        return send_event(evt, EventType.FINAL_RESULT_ONLY, fx)
                    case _:
                        return send_event(evt, EventType.FULL_TIME, fx)
            case GameState.HALF_TIME:
                # Half Time is fired at regular Half time & ET Half time.
                if old == GameState.EXTRA_TIME:
                    return send_event(evt, EventType.HALF_TIME_ET_BEGIN, fx)
                else:
                    return send_event(evt, EventType.HALF_TIME, fx)
            case GameState.INTERRUPTED:
                return send_event(evt, EventType.INTERRUPTED, fx)
            case GameState.LIVE:
                match old:
                    case GameState.SCHEDULED | GameState.DELAYED:
                        # Match has resumed
                        return send_event(evt, EventType.KICK_OFF, fx)
                    case GameState.INTERRUPTED:
                        return send_event(evt, EventType.RESUMED, fx)
                    case GameState.HALF_TIME:
                        return send_event(evt, EventType.SECOND_HALF_BEGIN, fx)
                    case GameState.BREAK_TIME:
                        return send_event(evt, EventType.PERIOD_BEGIN, fx)
            case GameState.PENALTIES:
                return send_event(evt, EventType.PENALTIES_BEGIN, fx)
            case GameState.POSTPONED:
                return send_event(evt, EventType.POSTPONED, fx)
            case GameState.STOPPAGE_TIME:
                return

        logger.error(f"Handle State: {old} -> {new} {fx.url} @ {fx.time}")

    # Core Loop
    async def fetch_games(self) -> list[fs.Fixture]:
        """Grab current scores from flashscore using aiohttp"""
        async with self.bot.session.get("http://www.flashscore.mobi/") as resp:
            match resp.status:
                case 200:
                    bt = bytearray(await resp.text(), encoding="utf-8")
                    tree = fromstring(bytes(bt))
                case _:
                    rs = resp.reason
                    st = resp.status
                    logger.error("%s %s during score loop", st, rs)
                    return []

        xp = './/div[@id="score-data"]'
        chunks = tostring(tree.xpath(xp)[0]).decode("utf8").split("<br/>")

        # Generic
        competition = None

        for game in chunks:
            try:
                tree = fromstring(game)
            except ParserError:  # Document is empty because of trailing </div>
                continue

            # Check if the chunk to be parsed has is a header.
            # If it is, we need to create a new competition object.
            # TODO: Handle Competition Fetching & Team Fetching from Flashscore
            if competition_name := "".join(tree.xpath(".//h4/text()")).strip():
                # Loop over bot.competitions to see if we can find the right
                # Competition object for base_embed.

                country, name = competition_name.rsplit(":", 1)

                c = self.bot.competitions

                if exact := [i for i in c if i.title == competition_name]:
                    competition = exact[0]
                else:
                    # Partial Matches
                    partial = [x for x in c if x.title in competition_name]
                    for ss in ["women", "u18"]:  # Filter…
                        if ss in competition_name.casefold():
                            partial = [
                                i for i in partial if ss in i.name.casefold()
                            ]

                    if partial:
                        partial.sort(key=lambda x: len(x.name))
                        competition = partial[0]
                    else:

                        if country:
                            country = country.strip()
                        if name:
                            name = name.strip()
                        competition = fs.Competition(None, name, country, None)
                        self.bot.competitions.append(competition)

            try:
                link = "".join(tree.xpath(".//a/@href"))
                match_id = link.split("/")[-2]
                url = fs.FLASHSCORE + link
            except IndexError:
                continue

            f = "fixture_event"  # Just a string for dispatching events.

            # Set & forget: Competition, Teams
            if (fx := self.bot.get_fixture(match_id)) is None:
                # These values never need to be updated.
                xp = "./text()"
                teams = [i.strip() for i in tree.xpath(xp) if i.strip()]

                if teams[0].startswith("updates"):  # ???
                    teams[0] = teams[0].replace("updates", "")

                if len(teams) == 1:
                    teams = teams[0].split(" - ")

                match len(teams):
                    case 2:
                        home_name, away_name = teams
                    case 3:
                        match teams:
                            case _, "La Duchere", _:
                                home_name = f"{teams[0]} {teams[1]}"
                                away_name = teams[2]
                            case _, _, "La Duchere":
                                home_name = teams[0]
                                away_name = f"{teams[1]} {teams[2]}"
                            case "Banik Most", _, _:
                                home_name = f"{teams[0]} {teams[1]}"
                                away_name = teams[2]
                            case _, "Banik Most", _:
                                home_name = teams[0]
                                away_name = f"{teams[1]} {teams[2]}"
                            case _:
                                logger.error("Fetch games found %s", teams)
                                continue
                    case _:
                        logger.error("Fetch games found %s", teams)
                        continue

                # TODO: Flesh this out to actually try and find the team's IDs.
                home = fs.Team(None, home_name, None)
                away = fs.Team(None, away_name, None)

                fx = fs.Fixture(home, away, match_id, url)

                # TODO: Spawn Browser Page Here
                # DO all set and forget shit.
                # Fetch Team Link + ID
                # Fetch Competition Link + ID
                fx.home = home
                fx.away = away
                self.bot.games.append(fx)

                old_state = None
            else:
                old_state = fx.state

            # Set the competition of the fixture
            if fx.competition is None:
                fx.competition = competition

            # Handling red cards is done relatively simply, do this first.
            cards = tree.xpath("./img/@class")
            if cards := [i.replace("rcard-", "") for i in cards]:
                try:
                    home_cards, away_cards = [int(card) for card in cards]
                except ValueError:
                    if len(tree.xpath("./text()")) == 2:
                        home_cards, away_cards = int(cards[0]), None
                    else:
                        home_cards, away_cards = None, int(cards[0])

                if home_cards is not None:
                    if home_cards != fx.home_cards:
                        if fx.home_cards is not None:
                            if home_cards > fx.home_cards:
                                t = EventType.RED_CARD
                            else:
                                t = EventType.VAR_RED_CARD
                            self.bot.dispatch(f, t, fx, home=True)
                        fx.home_cards = home_cards

                if away_cards is not None:
                    if away_cards != fx.away_cards:
                        if fx.away_cards is not None:
                            if away_cards > fx.away_cards:
                                t = EventType.RED_CARD
                            else:
                                t = EventType.VAR_RED_CARD
                            self.bot.dispatch(f, t, fx, home=False)
                        fx.away_cards = away_cards

            # The time block can be 1 element or 2 elements long.
            # Element 1 is either a time of day HH:MM (e.g. 20:45)
            # or a time of the match (e.g. 41')

            # If Element 2 exists, it is a declaration:
            # Cancelled, Postponed, Delayed, or similar.
            time = tree.xpath("./span/text()")

            state = "".join(tree.xpath("./a/@class")).strip()

            # First, we check to see if we need to,
            # and can update the fixture's kickoff

            if time and fx.kickoff is None:
                if ":" in time[0]:
                    time = time[0]
                    ko = datetime.strptime(time, "%H:%M") - timedelta(hours=1)

                    # We use the parsed data to create a 'cleaner'
                    # datetime object, with no second or microsecond
                    # And set the day to today.
                    now = datetime.now(tz=timezone.utc)
                    ko = now.replace(
                        hour=ko.hour, minute=ko.minute, second=0, microsecond=0
                    )  # Discard micros

                    # If the game appears to be in the past
                    # but has not kicked off yet, add a day.
                    if now.timestamp() > ko.timestamp() and state == "sched":
                        ko += timedelta(days=1)
                    fx.kickoff = ko
                    fx.ordinal = ko.toordinal()

            # What we now need to do, is figure out the "state" of the game.
            # Things may then get … more difficult. Often, the score of a
            # fixture contains extra data.
            # So, we update the match score, and parse additional states
            score_line = "".join(tree.xpath(".//a/text()")).split(":")

            h_score, a_score = score_line
            if a_score != "-":
                override = "".join([i for i in a_score if not i.isdigit()])
                h_score = int(h_score)
                a_score = int("".join([i for i in a_score if i.isdigit()]))

                if fx.home_score != h_score:
                    if fx.home_score is not None:
                        if h_score > fx.home_score:
                            ev = EventType.GOAL
                        else:
                            ev = EventType.VAR_GOAL
                        self.bot.dispatch(f, ev, fx, home=True)
                    fx.home_score = h_score

                if fx.away_score != a_score:
                    if fx.away_score is not None:
                        if a_score > fx.away_score:
                            ev = EventType.GOAL
                        else:
                            ev = EventType.VAR_GOAL
                        self.bot.dispatch(f, ev, fx, home=False)
                    fx.away_score = a_score
            else:
                override = None

            if override:
                try:
                    fx.time = {
                        "aet": GameState.AFTER_EXTRA_TIME,
                        "pen": GameState.AFTER_PENS,
                        "wo": GameState.WALKOVER,
                    }[override.casefold()]
                except KeyError:
                    logger.error(f"Unhandled override: {override}")
            else:
                # From the link of the score, we can gather info about the time
                # valid states are: sched, live, fin
                match len(time), state:
                    case 1, "live":
                        match time[0]:
                            case "Half Time":
                                fx.time = GameState.HALF_TIME
                            case "Break Time":
                                fx.time = GameState.BREAK_TIME
                            case "Penalties":
                                fx.time = GameState.PENALTIES
                            case "Extra Time":
                                fx.time = GameState.EXTRA_TIME
                            case "Live":
                                fx.time = GameState.FINAL_RESULT_ONLY
                            case _:
                                if "'" not in time[0]:
                                    logger.error("1 part time %1", time)
                                fx.time = time[0]
                    case 1, "sched":
                        fx.time = GameState.SCHEDULED
                    case 1, "fin":
                        fx.time = GameState.FULL_TIME
                    case 2, _:
                        # If we have a 2 part item, the second part will
                        # provide additional information
                        match time[-1]:
                            case "Cancelled":
                                fx.time = GameState.CANCELLED
                            case "Postponed":
                                fx.time = GameState.POSTPONED
                            case "Delayed":
                                fx.time = GameState.DELAYED
                            case "Interrupted":
                                fx.time = GameState.INTERRUPTED
                            case "Abandoned":
                                fx.time = GameState.ABANDONED
                            case "Extra Time":
                                fx.time = GameState.EXTRA_TIME
                            case _:
                                logger.error(f"2 part time found {time}")

            if old_state is not None:
                self.dispatch_states(fx, old_state)
        return self.bot.games

    livescores = Group(
        guild_only=True,
        name="livescores",
        description="Create & manage livescores channels",
        default_permissions=Permissions(manage_channels=True),
    )

    @livescores.command()
    @discord.app_commands.describe(channel="Target Channel")
    async def manage(
        self, interaction: Interaction[Bot], channel: Optional[TextChannel]
    ) -> Message:
        """View or Delete tracked leagues from a live-scores channel."""
        if channel is None:
            channel = typing.cast(TextChannel, interaction.channel)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                row = await connection.fetchrow(sql, channel.id)

        if not row:
            err = f"{channel.mention} is not a live-scores channel."
            return await self.bot.error(interaction, err)

        try:
            sc = next(
                i
                for i in self.bot.score_channels
                if i.channel.id == channel.id
            )
        except StopIteration:
            sc = ScoreChannel(channel)
            self.bot.score_channels.append(sc)

        txt = f"Fetching config for {sc.channel.mention}…"
        return await sc.view(interaction).update(txt)

    @livescores.command()
    @discord.app_commands.describe(name="Enter a name for the channel")
    async def create(
        self, interaction: Interaction[Bot], name: str = "⚽live-scores"
    ) -> Message:
        """Create a live-scores channel for your server."""
        await interaction.response.defer(thinking=True)

        assert interaction.guild is not None
        # command is flagged as guild_only.

        u = interaction.user
        guild = interaction.guild

        reason = f"{u} ({u.id}) created a live-scores channel."
        topic = "Live Scores from around the world"

        try:
            channel = await guild.create_text_channel(
                name, reason=reason, topic=topic
            )
        except Forbidden:
            err = "I need manage_channels permissions to make a channel."
            return await self.bot.error(interaction, err)

        ow = {
            guild.me: PermissionOverwrite(send_messages=True),
            guild.default_role: PermissionOverwrite(send_messages=False),
        }

        try:
            channel = await channel.edit(overwrites=ow)
        except Forbidden:
            pass

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                q = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                       ON CONFLICT DO NOTHING"""
                await connection.execute(q, interaction.guild.id)
                q = """INSERT INTO scores_channels (guild_id, channel_id)
                       VALUES ($1, $2)"""
                await connection.execute(q, channel.guild.id, channel.id)

        sc = ScoreChannel(channel)
        self.bot.score_channels.append(sc)
        await sc.reset_leagues()
        try:
            await sc.channel.send(
                f"{interaction.user.mention} Welcome to your new livescores "
                "channel.\n Use `/livescores add_league` to add new leagues,"
                " and `/livescores manage` to remove them"
            )
            msg = f"{channel.mention} created successfully."
        except Forbidden:
            msg = f"{channel.mention} created, but I need send_messages perms."
        return await self.bot.reply(interaction, msg)

    @livescores.command()
    @discord.app_commands.autocomplete(league=lg_ac)
    @discord.app_commands.describe(
        league="league name to search for or direct flashscore link",
        channel="Target Channel",
    )
    async def add_league(
        self,
        interaction: Interaction[Bot],
        league: str,
        channel: Optional[TextChannel],
    ) -> Message:
        """Add a league to an existing live-scores channel"""

        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = typing.cast(TextChannel, interaction.channel)

        chn = self.bot.score_channels
        try:
            sc = next(i for i in chn if i.channel.id == channel.id)
        except StopIteration:
            err = f"{channel.mention} is not a live-scores channel."
            return await self.bot.error(interaction, err)

        # Get the league object
        comp = self.bot.get_competition(league)
        if comp:
            res = comp
        elif "http" not in league:
            res = await fetch_comp(interaction, league)
        else:
            if "flashscore" not in league:
                err = "Invalid link provided."
                return await self.bot.error(interaction, err)

            qry = str(league).strip("[]<>")  # idiots
            res = await fs.Competition.by_link(self.bot, qry)

            if res is None:
                err = f"Failed to get data for {qry} channel not modified."
                return await self.bot.error(interaction, err)

        if res.title == "WORLD: Club Friendly":
            err = "You can't add club friendlies as a competition, sorry."
            return await self.bot.error(interaction, err)

        await sc.add_leagues([res.title])
        view = sc.view(interaction)
        s = sc.channel.mention
        reply = f"Added tracked league for {s}```yaml\n{res}```"
        return await view.update(content=reply)

    # Event listeners for channel deletion or guild removal.
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove all of a channel's stored data upon deletion"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM scores_channels WHERE channel_id = $1"""
                await connection.execute(sql, channel.id)

        for c in self.bot.score_channels.copy():
            if channel.id == c.channel.id:
                self.bot.score_channels.remove(c)


async def setup(bot: Bot):
    """Load the cog into the bot"""
    await bot.add_cog(Scores(bot))
