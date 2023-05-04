"""Handle the data parsed by score_task.py"""
from __future__ import annotations
import datetime

import itertools
import logging
from typing import TYPE_CHECKING, TypeAlias, cast

import discord
from discord import Message, Embed
from discord.ext import commands
from ext.fixtures import FSEmbed

import ext.flashscore as fs
from ext.utils import embed_utils, view_utils, timed_events, flags

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]
    User: TypeAlias = discord.User | discord.Member

logger = logging.getLogger("scores")

# Constants.

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


class ScoreChannel:
    """A livescore channel object, containing it's properties."""

    def __init__(self, channel: discord.TextChannel) -> None:
        self.channel: discord.TextChannel = channel
        self.messages: list[discord.Message] = []
        self._current_embeds: dict[str, Embed] = dict()
        self.leagues: set[fs.Competition] = set()

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

        def is_me(message: discord.Message) -> bool:
            return message.author.id == bot.application_id

        try:
            await self.channel.purge(reason=rsn, check=is_me, limit=20)
        except discord.HTTPException:
            return

    async def get_leagues(self, bot: Bot) -> set[fs.Competition]:
        """Fetch target leagues for the ScoreChannel from the database"""
        sql = """SELECT * FROM scores_leagues WHERE channel_id = $1"""
        records = await bot.db.fetch(sql, self.channel.id, timeout=10)

        for i in records:
            if (comp := bot.flashscore.get_competition(i["url"])) is None:
                league = i["league"].rstrip("/")
                if (comp := bot.flashscore.get_competition(league)) is None:
                    logger.error("Failed fetching comp %s", league)
                    continue

            self.leagues.add(comp)
        return self.leagues

    async def generate_embeds(
        self, bot: Bot, comps: dict[str, list[Embed]]
    ) -> list[tuple[Message | None, list[Embed] | None]]:
        """Grab Embeds for requested leagues"""
        embeds: list[Embed] = []

        titles = [i.title for i in self.leagues]
        for k, val in comps.items():
            if k in titles:
                embeds += val

        _ = self.channel
        if not self.messages and _.permissions_for(_.guild.me).manage_messages:
            await self.purge(bot)

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

    async def run_scores(
        self, bot: Bot, comps: dict[str, list[Embed]]
    ) -> None:
        """Edit a live-score channel to have the latest scores"""
        # Validatiion / Rate Limit Avoidance Logic.

        if not self.leagues:
            await self.get_leagues(bot)

        tuples = await self.generate_embeds(bot, comps)

        # We have a limit of 5 messages due to ratelimiting
        count = 1

        cog = bot.get_cog("Scores")
        assert isinstance(cog, ScoresCog)

        def should_run(
            message: Message | None, embeds: list[Embed] | None
        ) -> bool:
            if embeds is None:
                if message is None or message.flags.suppress_embeds:
                    return False
                return True

            if message is None:
                return True

            for i in embeds:
                try:
                    assert (auth := i.author.url) is not None
                    old = self._current_embeds[auth].description
                    new = i.description
                    if old != new:
                        return True  # We're good to go.
                except KeyError:
                    return True  # Old Embed does not exist, we need a new one.
            return False

        for message, m_embeds in tuples:
            if not should_run(message, m_embeds):
                continue

            try:
                await self.send_or_edit(message, m_embeds)
            except (discord.NotFound, discord.Forbidden):
                cog.score_channels.discard(self)

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

        if embeds is None:
            new_msg = await message.edit(suppress=True)
        else:
            new_msg = await message.edit(embeds=embeds, suppress=False)
        self.messages[self.messages.index(message)] = new_msg

    async def reset_leagues(self, interaction: Interaction) -> None:
        """Reset the channel's list of leagues to the defaults"""

        async with interaction.client.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """DELETE FROM scores_leagues WHERE channel_id = $1"""
                await connection.execute(sql, self.channel.id)

                sql = """INSERT INTO scores_leagues (channel_id, url)
                        VALUES ($1, $2)"""
                args = [(self.channel.id, x) for x in fs.DEFAULT_LEAGUES]
                await connection.executemany(sql, args)

        self.leagues.clear()
        for i in fs.DEFAULT_LEAGUES:
            if (
                comp := interaction.client.flashscore.get_competition(i)
            ) is None:
                logger.info("Reset: Could not add default league %s", comp)
                continue
            self.leagues.add(comp)


class ScoresConfig(view_utils.DropdownPaginator):
    """Generic Config View"""

    def __init__(self, invoker: User, channel: ScoreChannel) -> None:
        leagues = [i for i in channel.leagues if i.url is not None]
        self.channel: ScoreChannel = channel

        embed = Embed(colour=discord.Colour.dark_teal())
        embed.title = "LiveScores config"

        chan = self.channel.channel
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
        rows: list[str] = []
        for i in leagues:
            if i.url is None:
                continue

            opt = discord.SelectOption(label=i.title, value=i.url)
            opt.description = i.url

            flag = flags.get_flag(i.country)
            opt.emoji = flag
            rows.append(f"{flag} {i.markdown}")
            options.append(opt)

        super().__init__(invoker, embed, rows, options)
        self.dropdown.max_values = len(self.options)

    @discord.ui.select(placeholder="Removed Tracked leagues", row=1)
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[ScoresConfig]
    ) -> None:
        view = view_utils.Confirmation(itr.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        lg_text = "```yaml\n" + "\n".join(sorted(sel.values)) + "```"
        ment = self.channel.mention
        embed = Embed(title="LiveScores", colour=discord.Colour.red())
        embed.description = f"Remove these leagues from {ment}? {lg_text}"

        await itr.response.edit_message(embed=embed, view=view)
        await view.wait()

        if not view.value:
            embed = self.pages[self.index]
            edit = view.interaction.response.edit_message
            return await edit(view=self, embed=embed)

        sql = """DELETE from scores_leagues
                 WHERE (channel_id, url) = ($1, $2)"""

        rows: list[tuple[int, str]]
        rows = [(self.channel.id, x) for x in sel.values]

        await itr.client.db.executemany(sql, rows, timeout=60)

        for i in sel.values:
            item = next(j for j in self.channel.leagues if i == j.url)
            self.channel.leagues.remove(item)

        msg = f"Removed {self.channel.mention} tracked leagues: \n{lg_text}"
        embed = Embed(description=msg, colour=discord.Colour.red())
        embed.title = "LiveScores"
        embed_utils.user_to_footer(embed, itr.user)
        await itr.followup.send(content=msg)

        # Reinstantiate the view
        new = ScoresConfig(itr.user, self.channel)
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
            embed = self.pages[self.index]
            return await view_itr.response.edit_message(embed=embed, view=self)

        await self.channel.reset_leagues(interaction)

        embed = Embed(title="LiveScores: Tracked Leagues Reset")
        embed.description = self.channel.mention
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.followup.send(embed=embed)

        view = ScoresConfig(interaction.user, self.channel)
        await interaction.response.send_message(view=view, embed=view.pages[0])
        view.message = await interaction.original_response()


class ScoresCog(commands.Cog):
    """Live Scores channel module"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.score_channels: set[ScoreChannel] = set()

    async def cog_load(self) -> None:
        """Update the cache"""
        await self.update_cache()

    async def cog_unload(self) -> None:
        """Cancel the live scores loop when cog is unloaded."""
        self.score_channels.clear()

    @commands.Cog.listener()
    async def on_scores_ready(self, now: datetime.datetime) -> None:
        """When Livescores Fires a "scores ready" event, handle it"""
        if not self.score_channels:
            await self.update_cache()

        comps = self.bot.flashscore.live_competitions()

        sc_embeds: dict[str, list[Embed]] = {}
        for comp in comps:
            embed = await FSEmbed.create(comp)

            flt = [
                i for i in self.bot.flashscore.games if i.competition == comp
            ]
            fix = sorted(flt, key=lambda c: c.kickoff or now)

            ls_txt = [i.live_score_text for i in fix]
            table = f"\n[View Table]({comp.table})" if comp.table else ""
            embeds = embed_utils.rows_to_embeds(embed, ls_txt, 50, table)
            sc_embeds.update({comp.title: embeds})

        for i in self.score_channels.copy():
            if i.channel.is_news():
                self.score_channels.discard(i)
                return
            await i.run_scores(self.bot, sc_embeds)

    # Database load: ScoreChannels
    async def update_cache(self) -> set[ScoreChannel]:
        """Grab the most recent data for all channel configurations"""
        await self.bot.flashscore.cache_competitions()
        await self.bot.flashscore.cache_teams()

        sql = """SELECT * FROM scores_leagues"""
        records = await self.bot.db.fetch(sql, timeout=10)

        # Generate {channel_id: [league1, league2, league3, …]}
        chans = self.score_channels
        bad: list[int] = []

        for i in records:
            channel = self.bot.get_channel(i["channel_id"])

            if not isinstance(channel, discord.TextChannel):
                bad.append(i["channel_id"])
                continue

            if channel.is_news():
                bad.append(i["channel_id"])
                continue

            comp = self.bot.flashscore.get_competition(
                str(i["url"]).rstrip("/")
            )
            if not comp:
                logger.error("Could not get_competition for %s", i)
                continue

            try:
                chn = next(j for j in chans if j.channel.id == i["channel_id"])
            except StopIteration:
                chn = ScoreChannel(channel)
                chans.add(chn)

            chn.leagues.add(comp)

        # Cleanup Old.
        sql = """DELETE FROM scores_channels WHERE channel_id = $1"""
        if chans:
            await self.bot.db.executemany(sql, bad)

        self.score_channels = chans
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

        chans = self.score_channels
        try:
            chan = next(i for i in chans if i.channel.id == channel.id)
        except StopIteration:
            chan = ScoreChannel(channel)
            self.score_channels.add(chan)

        view = ScoresConfig(interaction.user, chan)
        await interaction.response.send_message(view=view, embed=view.pages[0])

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
            embed = Embed(colour=discord.Colour.red())
            err = "🚫 I need manage_channels permissions to make a channel."
            embed.description = err
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

        self.score_channels.add(chan := ScoreChannel(channel))

        await chan.reset_leagues(interaction)

        try:
            await chan.channel.send(
                f"{interaction.user.mention} Welcome to your new livescores "
                "channel.\n Use `/livescores add_league` to add new leagues,"
                " and `/livescores manage` to remove them"
            )
            msg = f"{channel.mention} created successfully."
        except discord.Forbidden:
            msg = f"{channel.mention} created, but I need send_messages perms."
        await interaction.response.send_message(msg)

    @livescores.command()
    @discord.app_commands.describe(
        competition="league name to search for",
        channel="Target Channel",
    )
    async def add_league(
        self,
        interaction: Interaction,
        competition: fs.cmp_tran,
        channel: discord.TextChannel | None,
    ) -> None:
        """Add a league to an existing live-scores channel"""

        if competition.title == "WORLD: Club Friendly":
            err = "🚫 You can't add club friendlies as a competition, sorry."
            embed = Embed(colour=discord.Colour.red(), description=err)
            return await interaction.response.send_message(embed=embed)

        if competition.url is None:
            err = "🚫 Could not fetch url from competition"
            embed = Embed(colour=discord.Colour.red(), description=err)
            return await interaction.response.send_message(embed=embed)

        if channel is None:
            channel = cast(discord.TextChannel, interaction.channel)

        score_chans = self.score_channels
        try:
            chan = next(i for i in score_chans if i.channel.id == channel.id)
        except StopIteration:
            embed = Embed(colour=discord.Colour.red())
            ment = channel.mention
            embed.description = f"🚫 {ment} is not a live-scores channel."
            return await interaction.response.send_message(embed=embed)

        embed = Embed(title="LiveScores: Tracked League Added")
        embed.description = f"{chan.channel.mention}\n\n{competition.url}"
        embed_utils.user_to_footer(embed, interaction.user)
        await interaction.response.send_message(embed=embed)

        sql = """INSERT INTO scores_leagues (channel_id, url, league)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""

        url = competition.url
        title = competition.title
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, chan.channel.id, url, title)

        chan.leagues.add(competition)

    @discord.app_commands.command()
    async def scores(
        self,
        interaction: Interaction,
        competition: fs.live_comp_transf | None,
    ) -> None:
        """Fetch current scores for a specified competition,
        or if no competition is provided, all live games."""
        if not self.bot.flashscore.games:
            embed = Embed(colour=discord.Colour.red())
            embed.description = "🚫 No live games found"
            return await interaction.response.send_message(embed=embed)

        games = self.bot.flashscore.games
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

        for i, j in [(i.competition, i.live_score_text) for i in games]:
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

        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])
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

        for i in self.score_channels.copy():
            if channel.id == i.channel.id:
                self.score_channels.remove(i)


async def setup(bot: Bot):
    """Load the cog into the bot"""
    await bot.add_cog(ScoresCog(bot))
