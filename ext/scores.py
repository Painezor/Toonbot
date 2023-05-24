"""Handle the data parsed by score_task.py"""
from __future__ import annotations
import datetime

import itertools
import logging
from typing import TYPE_CHECKING, TypeAlias, cast
import discord
from discord import Message, Embed, Colour
from discord.ext import commands
from ext.fixtures import FSEmbed

import ext.flashscore as fs
from ext.flashscore.gamestate import GameState as GS
from ext.toonbot_utils.fs_transform import comp_, live_comp
from ext.utils import embed_utils, view_utils, timed_events, flags

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("scores")

# Command Mentions.
ADD_LEAGUE = "</livescores add_league:951948501355495506>"
MANAGE = "</livescores manage:951948501355495506>"

NGF = (
    "No games found for your tracked leagues today!\n\nYou can "
    "add more leagues with `/livescores add`"
)
NO_GAMES_FOUND = Embed(description=NGF)
NO_GAMES_FOUND.set_author(name="No Games Found", url=fs.FLASHSCORE)


NOPERMS = (
    "\n```yaml\nThis livescores channel will not work currently, "
    "I am missing the following permissions.\n"
)


async def get_leagues(bot: Bot, channel: int) -> list[fs.abc.BaseCompetition]:
    """Fetch target leagues for the ScoreChannel from the database"""
    sql = """SELECT * FROM scores_leagues WHERE channel_id = $1"""
    records = await bot.db.fetch(sql, channel, timeout=10)
    leagues: list[fs.abc.BaseCompetition] = []
    for i in records:
        if (comp := bot.cache.get_competition(url=i["url"])) is None:
            comp = bot.cache.get_competition(title=i["league"])
            if comp is None:
                logger.error("Failed fetching comp %s", i["league"])
                continue

        leagues.append(comp)
    return leagues


def fmt_comp(competition: fs.abc.BaseCompetition) -> str:
    flag = flags.get_flag(competition.country)
    return f"{flag} [{competition.title}]({competition.url})"


def fmt_fixture(fixture: fs.abc.BaseFixture) -> str:
    output: list[str] = []
    if fixture.state is not None:
        output.append(f"`{fixture.state.emote}")

        if isinstance(fixture.time, str):
            output.append(fixture.time)
        else:
            if fixture.state is not GS.SCHEDULED:
                output.append(fixture.state.shorthand)
        output.append("` ")

    hm_n = fixture.home.team.name
    aw_n = fixture.away.team.name

    if fixture.home.score is None or fixture.away.score is None:
        time = timed_events.Timestamp(fixture.kickoff).time_hour
        output.append(f" {time} [{hm_n} v {aw_n}]({fixture.url})")
    elif fixture.home.pens is not None:
        # Penalty Shootout
        pens = f" (p: {fixture.home.pens} - {fixture.away.pens}) "
        sco = min(fixture.home.score, fixture.away.score)
        score = f"[{sco} - {sco}]({fixture.url})"
        output.append(f"{hm_n} {score}{pens}{aw_n}")
    else:
        # Embolden Winner
        if fixture.home.score > fixture.away.score:
            hm_n = f"**{hm_n}**"
        elif fixture.away.score > fixture.home.score:
            aw_n = f"**{aw_n}**"

        def parse_cards(cards: int | None) -> str:
            """Get a number of icons matching number of cards"""
            if not cards:
                return ""
            if cards == 1:
                return f"`{fs.RED_CARD_EMOJI}` "
            return f"`{fs.RED_CARD_EMOJI} x{cards}` "

        h_s, a_s = fixture.home.score, fixture.away.score
        h_c = parse_cards(fixture.home.cards)
        a_c = parse_cards(fixture.away.cards)
        url = fixture.url
        output.append(f"{hm_n} {h_c}[{h_s} - {a_s}]({url}){a_c} {aw_n}")
    return "".join(output)


class ScoreChannel:
    """A livescore channel object, containing it's properties."""

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.messages: list[discord.Message] = []
        self._current_embeds: dict[str, Embed] = dict()
        self.leagues: list[fs.abc.BaseCompetition] = []

    @property
    def id(self) -> int:  # pylint: disable=C0103
        """Retrieve the id from the parent channel"""
        return self.channel.id

    @property
    def mention(self) -> str:
        """Retrieve the mention of the parent channel"""
        return self.channel.mention

    async def purge(self, bot: Bot) -> None:
        """Clean all old bot messages from the channel"""
        rsn = "Clearing Score Channel"

        def is_me(message: Message) -> bool:
            return message.author.id == bot.application_id

        try:
            await self.channel.purge(reason=rsn, check=is_me, limit=20)
        except discord.HTTPException:
            return

        self.messages.clear()

    def generate_embeds(
        self, comps: dict[str, list[Embed]]
    ) -> list[tuple[Message | None, list[Embed] | None]]:
        """Grab Embeds for requested leagues"""
        # Validate Channel perms.
        embeds: list[Embed] = []

        leagues = [i.title for i in self.leagues]
        for k, val in comps.items():
            if k in leagues:
                embeds += val

        if not embeds:
            embeds = [NO_GAMES_FOUND]

        # Stack embeds to max size for individual message.
        stacked = embed_utils.stack_embeds(embeds)

        # Zip the lists into tuples to simultaneously iterate Limit to 5 max
        tuples: list[tuple[Message | None, list[Embed] | None]]
        tuples = list(itertools.zip_longest(self.messages, stacked))

        def sorter(
            item: tuple[Message | None, list[Embed] | None]
        ) -> datetime.datetime:
            message, _ = item
            if message is None:
                return discord.utils.utcnow()
            if message.edited_at:
                return message.edited_at
            return message.created_at

        tuples.sort(key=sorter)
        return tuples

    def should_run(
        self, message: Message | None, embeds: list[Embed] | None
    ) -> bool:
        """Check if we need to send or update messages for each embed."""
        # If we have no Embeds to send
        if embeds is None:
            # Check if we have already suppressed the embeds
            if message is None or message.flags.suppress_embeds:
                return False

            # If they're not suppressed yet, we need to do so.
            return True

        # If there is no cached meessage, we need to send one.
        if message is None:
            return True

        for i in embeds:
            # If the message has suppressed embeds, we need to unsuppress
            if message.flags.suppress_embeds:
                return True

            try:
                # This should always be set.
                assert (auth := i.author.url) is not None
                old = self._current_embeds[auth].description
                new = i.description
                if old != new:
                    return True  # We're good to go.
            except KeyError:
                return True  # Old Embed does not exist, we need a new one.
        return False

    async def run_scores(
        self, bot: Bot, comps: dict[str, list[Embed]]
    ) -> None:
        """Edit a live-score channel to have the latest scores"""
        # Validatiion / Rate Limit Avoidance Logic.
        _ = self.channel
        perms = _.permissions_for(_.guild.me)
        if not perms.send_messages or not perms.embed_links:
            return

        if not self.messages and perms.manage_messages:
            await self.purge(bot)

        if not self.leagues:
            self.leagues = await get_leagues(bot, self.channel.id)

        tuples = self.generate_embeds(comps)

        # We have a limit of 5 messages due to ratelimiting
        count = 1

        cog = bot.get_cog(ScoresCog.__cog_name__)
        assert isinstance(cog, ScoresCog)

        for message, m_embeds in tuples:
            if not self.should_run(message, m_embeds):
                continue

            try:
                await self.send_or_edit(message, m_embeds)
            except discord.Forbidden:
                cog.channels.discard(self)
            except discord.HTTPException:
                assert m_embeds is not None
                urls = ", ".join([i.thumbnail.url or "" for i in m_embeds])
                logger.info("HTTP Exception %s", urls)

            if count > 4:
                return
            count += 1

    # If we have more than 5 messages, get the 5 oldest, and their index
    # Then map these indexes to the appropriate embeds
    async def send_or_edit(
        self,
        message: Message | None,
        embeds: list[Embed] | None,
    ) -> None:
        """Try to send this messagee to a our channel"""
        if message is None and embeds is None:
            return  # this should never happen.

        if embeds is not None:
            for i in embeds:
                assert i.author.url is not None
                self._current_embeds[i.author.url] = i

        # Suppress Message's embeds until they're needed again.
        if message is None:
            assert embeds is not None
            # No message exists in cache,
            # or we need an additional message.
            new_msg = await self.channel.send(embeds=embeds)
            self.messages.append(new_msg)
            return

        try:
            if embeds is None:
                new_msg = await message.edit(suppress=True)
            else:
                new_msg = await message.edit(embeds=embeds, suppress=False)
        except discord.NotFound:
            try:
                self.messages.remove(message)
            except ValueError:
                pass
            return

        self.messages[self.messages.index(message)] = new_msg


class ScoresConfig(view_utils.DropdownPaginator):
    """Generic Config View"""

    def __init__(
        self,
        invoker: User,
        channel: discord.TextChannel,
        leagues: list[fs.abc.BaseCompetition],
    ) -> None:
        self.channel: discord.TextChannel = channel
        self.leagues: list[fs.abc.BaseCompetition] = leagues

        embed = Embed(colour=Colour.dark_teal(), title="LiveScores config")

        chan = self.channel
        perms = chan.permissions_for(chan.guild.me)
        missing: list[str] = []
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")
        if not perms.manage_messages:
            missing.append("manage_messages")

        if missing:
            txt = f"{NOPERMS} {missing}```"
            embed.add_field(name="Missing Permissions", value=txt)

        options: list[discord.SelectOption] = []
        rows: list[str] = [fmt_comp(i) for i in leagues]
        for i in leagues:
            if i.url is None:
                continue

            flag = flags.get_flag(i.country)
            opt = discord.SelectOption(label=i.title, value=i.url, emoji=flag)
            opt.description = i.url
            options.append(opt)

        super().__init__(invoker, embed, rows, options, multi=True)

    @discord.ui.select(placeholder="Removed Tracked leagues", row=1)
    async def remove(
        self, itr: Interaction, sel: discord.ui.Select[ScoresConfig]
    ) -> None:
        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lg_text = "\n".join(
            [
                fmt_comp(next(j for j in self.leagues if i == j.url))
                for i in sorted(sel.values)
            ]
        )
        ment = self.channel.mention
        embed = Embed(title="LiveScores", colour=discord.Colour.red())
        embed.description = f"Remove these leagues from {ment}? {lg_text}"

        await itr.response.edit_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = self.embeds[self.index]
            edit = view.interaction.response.edit_message
            return await edit(view=self, embed=embed)

        sql = """DELETE from scores_leagues
                 WHERE (channel_id, url) = ($1, $2)"""

        rows: list[tuple[int, str]]
        rows = [(self.channel.id, x) for x in sel.values]

        await itr.client.db.executemany(sql, rows, timeout=60)

        for i in sel.values:
            item = next(j for j in self.leagues if i == j.url)
            self.leagues.remove(item)

        msg = f"Removed {self.channel.mention} tracked leagues: \n{lg_text}"
        embed = Embed(description=msg, colour=discord.Colour.red())
        embed.title = "LiveScores"
        embed_utils.user_to_footer(embed, itr.user)
        await itr.followup.send(content=msg)

        # Reinstantiate the view
        leagues = await get_leagues(itr.client, self.channel.id)
        new = ScoresConfig(itr.user, self.channel, leagues)
        await view.interaction.response.edit_message(embed=embed, view=new)
        view.message = await view.interaction.original_response()

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.red)
    async def reset(
        self, interaction: Interaction, _: discord.ui.Button[ScoresConfig]
    ) -> None:
        """Button to reset a live score channel back to the default leagues"""
        view = view_utils.Confirmation(interaction.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        embed = Embed(title="Ticker", colour=discord.Colour.red())
        ment = self.channel.mention
        embed.description = f"Reset leagues to default {ment}?\n"

        await interaction.response.edit_message(embed=embed, view=view)
        await view.wait()

        view_itr = view.interaction
        if not view.value:
            # Return to normal viewing
            embed = self.embeds[self.index]
            return await view_itr.response.edit_message(embed=embed, view=self)

        await self.reset_leagues(interaction)

        embed = Embed(title="LiveScores: Tracked Leagues Reset")
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)

        leagues = await get_leagues(interaction.client, self.channel.id)
        view = ScoresConfig(interaction.user, self.channel, leagues)
        await interaction.response.send_message(
            view=view, embed=view.embeds[0]
        )
        view.message = await interaction.original_response()

    async def reset_leagues(self, interaction: Interaction) -> None:
        """Reset the channel's list of leagues to the defaults"""

        sql = """DELETE FROM scores_leagues WHERE channel_id = $1"""
        await interaction.client.db.execute(sql, self.channel.id)
        _ = """INSERT INTO scores_leagues (channel_id, url) VALUES ($1, $2)"""
        args = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]
        await interaction.client.db.executemany(sql, args)

        self.leagues.clear()
        for i in fs.DEFAULT_LEAGUES:
            if (
                comp := interaction.client.cache.get_competition(url=i)
            ) is None:
                logger.info("Reset: Could not add default league %s", comp)
                continue
            self.leagues.append(comp)


class ScoresCog(commands.Cog):
    """Live Scores channel module"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.channels: set[ScoreChannel] = set()
        self._locked: bool = False
        self._table_cache: dict[str, str] = {}

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.channels.clear()

    @commands.Cog.listener()
    async def on_table_update(self, comp: fs.Competition, url: str) -> None:
        if comp.id:
            self._table_cache[comp.id] = url

    @commands.Cog.listener()
    async def on_scores_ready(self, now: datetime.datetime) -> None:
        """When Livescores Fires a "scores ready" event, handle it"""
        await self.update_cache()

        comps = self.bot.cache.live_competitions()

        sc_embeds: dict[str, list[Embed]] = {}
        for comp in comps:
            embed = await FSEmbed.create(comp)

            flt = [i for i in self.bot.cache.games if i.competition == comp]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [fmt_fixture(i) for i in fix]
            if comp.id in self._table_cache:
                footer = f"\n[View Table]({self._table_cache[comp.id]})"
            else:
                footer = None
            embeds = embed_utils.rows_to_embeds(embed, ls_txt, 50, footer)
            sc_embeds.update({comp.title: embeds})

        if self._locked:
            return

        self._locked = True
        for i in self.channels.copy():
            if i.channel.is_news():
                self.channels.discard(i)
                continue
            await i.run_scores(self.bot, sc_embeds)
        self._locked = False

    # Database load: ScoreChannels
    async def update_cache(self) -> set[ScoreChannel]:
        """Grab the most recent data for all channel configurations"""
        sql = """SELECT * FROM scores_leagues"""
        records = await self.bot.db.fetch(sql, timeout=10)

        # Generate {channel_id: [league1, league2, league3, …]}
        chans = self.channels
        bad: list[int] = []

        for i in records:
            channel = self.bot.get_channel(i["channel_id"])

            if not isinstance(channel, discord.TextChannel):
                bad.append(i["channel_id"])
                continue

            elif channel.is_news():
                bad.append(i["channel_id"])
                continue

            comp = self.bot.cache.get_competition(url=i["url"])
            if not comp:
                continue

            try:
                chn = next(j for j in chans if j.id == i["channel_id"])
            except StopIteration:
                chn = ScoreChannel(channel)
                chans.add(chn)

            chn.leagues.append(comp)

        # Cleanup Old.
        sql = """DELETE FROM scores_channels WHERE channel_id = $1"""
        if chans and bad:
            await self.bot.db.executemany(sql, [[i] for i in bad])

        self.channels = chans
        return chans

    # Core Loop
    livescores = discord.app_commands.Group(
        guild_only=True,
        name="livescores",
        description="Create & manage livescores channels",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @livescores.command()
    @discord.app_commands.describe(channel="Target Channel")
    async def manage(
        self,
        interaction: Interaction,
        channel: discord.TextChannel | None,
    ) -> None:
        """View or Delete tracked leagues from a live-scores channel."""
        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM scores_channels WHERE channel_id = $1"""
                row = await connection.fetchrow(sql, channel.id)

        if not row:
            embed = Embed(colour=discord.Colour.red())
            _ = f"🚫 {channel.mention} is not a live-scores channel."
            embed.description = _
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        chans = self.channels
        try:
            chan = next(i for i in chans if i.id == channel.id)
        except StopIteration:
            chan = ScoreChannel(channel)
            self.channels.add(chan)

        leagues = await get_leagues(self.bot, channel.id)
        view = ScoresConfig(interaction.user, channel, leagues)
        await interaction.response.send_message(
            view=view, embed=view.embeds[0]
        )

    @livescores.command()
    @discord.app_commands.describe(name="Enter a name for the channel")
    async def create(
        self, interaction: Interaction, name: str = "⚽live-scores"
    ) -> None:
        """Create a live-scores channel for your server."""
        assert interaction.guild is not None
        # command is flagged as guild_only.

        user = interaction.user
        guild = interaction.guild

        reason = f"{user} ({user.id}) created a live-scores channel."
        topic = "Live Scores from around the world"

        try:
            channel = await guild.create_text_channel(
                name, reason=reason, topic=topic
            )
        except discord.Forbidden:
            err = "🚫 I need manage_channels permissions to make a channel."
            embed = Embed(colour=Colour.red(), description=err)
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        if channel.permissions_for(channel.guild.me).manage_channels:
            dow = discord.PermissionOverwrite
            ow_ = {
                guild.default_role: dow(send_messages=False),
                guild.me: dow(send_messages=True),
            }
            channel = await channel.edit(overwrites=ow_)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                    ON CONFLICT DO NOTHING"""
                await connection.execute(sql, interaction.guild.id)
                sql = """INSERT INTO scores_channels (guild_id, channel_id)
                    VALUES ($1, $2)"""
                await connection.execute(sql, channel.guild.id, channel.id)

        self.channels.add(ScoreChannel(channel))

        view = ScoresConfig(interaction.user, channel, [])

        try:
            await channel.send(
                f"{interaction.user.mention} Welcome to your new livescores "
                f"channel.\n Use {ADD_LEAGUE} to add new leagues,"
                f" and {MANAGE} to remove them"
            )
            msg = f"{channel.mention} created successfully."
        except discord.Forbidden:
            msg = f"{channel.mention} created, but I need send_messages perms."
        await interaction.response.send_message(msg, view=view)

    @livescores.command()
    @discord.app_commands.describe(
        competition="league name to search for",
        channel="Target Channel",
    )
    async def add_league(
        self,
        interaction: Interaction,
        competition: comp_,
        channel: discord.TextChannel | None,
    ) -> None:
        """Add a league to an existing live-scores channel"""

        if competition.title == "WORLD: Club Friendly":
            err = "🚫 You can't add club friendlies as a competition, sorry."
            emb = Embed(colour=discord.Colour.red(), description=err)
            return await interaction.response.send_message(embed=emb)

        if competition.url is None:
            err = "🚫 Could not fetch url from competition"
            emb = Embed(colour=discord.Colour.red(), description=err)
            return await interaction.response.send_message(embed=emb)

        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        score_chans = self.channels
        try:
            chan = next(i for i in score_chans if i.id == channel.id)
        except StopIteration:
            emb = Embed(colour=discord.Colour.red())
            ment = channel.mention
            emb.description = f"🚫 {ment} is not a live-scores channel."
            return await interaction.response.send_message(embed=emb)

        emb = Embed(title="LiveScores: Tracked League Added")
        emb.description = f"{chan.channel.mention}\n\n{fmt_comp(competition)}"
        embed_utils.user_to_footer(emb, interaction.user)
        await interaction.response.send_message(embed=emb)

        sql = """INSERT INTO scores_leagues (channel_id, url, league)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""

        title = competition.title
        await self.bot.db.execute(sql, chan.id, competition.url, title)
        chan.leagues.append(competition)

    @discord.app_commands.command()
    async def scores(
        self,
        interaction: Interaction,
        competition: live_comp | None,
    ) -> None:
        """Fetch current scores for a specified competition,
        or if no competition is provided, all live games."""
        if not self.bot.cache.games:
            embed = Embed(colour=discord.Colour.red())
            embed.description = "🚫 No live games found"
            return await interaction.response.send_message(embed=embed)

        games = self.bot.cache.games
        if competition:
            games = [i for i in games if i.competition == competition]

        comp = None
        header = f"Scores as of: {timed_events.Timestamp().long}\n"
        base_embed = Embed(color=discord.Colour.og_blurple())
        base_embed.title = "Current scores"
        base_embed.description = header
        embed = base_embed.copy()
        embed.description = ""
        embeds: list[Embed] = []

        for i, j in [(i.competition, fmt_fixture(i)) for i in games]:
            if i and i != comp:  # We need a new header if it's a new comp.
                comp = i
                output = f"\n**{i.title}**\n{j}\n"
            else:
                output = f"{j}\n"

            if len(embed.description + output) < 2048:
                embed.description = f"{embed.description}{output}"
            else:
                embeds.append(embed)
                embed = base_embed.copy()
                embed.description = f"\n**{i}**\n{j}\n"
        embeds.append(embed)

        view = view_utils.EmbedPaginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=embeds[0])
        view.message = await interaction.original_response()

    # Event listeners for channel deletion or guild removal.
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Remove all of a channel's stored data upon deletion"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM scores_channels WHERE channel_id = $1"""
                await connection.execute(sql, channel.id)

        for i in self.channels.copy():
            if channel.id == i.id:
                self.channels.remove(i)


async def setup(bot: Bot):
    """Load the cog into the bot"""
    await bot.add_cog(ScoresCog(bot))
