"""r/NUFC Match Thread Bot"""
from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import asyncpg
import discord
from discord.ext import commands, tasks
from lxml import html

import ext.flashscore as fs

if typing.TYPE_CHECKING:
    from core import Bot

logger = logging.getLogger("matchthread")

LSTV = "https://www.livesoccertv.com/"
# TODO: Delete MatchThread Bot or Rewrite it Entirely.


class MatchThread:
    """Tool for updating a reddit post with the latest
    information about a match."""

    def __init__(
        self,
        bot: Bot,
        fixture: fs.Fixture,
        settings: asyncpg.Record,
        record: asyncpg.Record,
    ) -> None:
        self.bot: Bot = bot
        self.fixture: fs.Fixture = fixture
        self.settings: asyncpg.Record = settings
        self.mtb_history: asyncpg.Record = record

        # Fetch once
        self.t_v = None

        # Caching
        self.old_markdown = ""

        # Commence loop
        self.stop = False

    @property
    def base_embed(self) -> discord.Embed:
        """Generic Embed for MTB notifications"""
        embed = discord.Embed(color=0xFF4500)
        thumb = (
            "http://vignette2.wikia.nocookie.net/valkyriecrusade/"
            "images/b/b5/Reddit-The-Official-App-Icon.png"
        )
        embed.set_author(icon_url=thumb, name="Match Thread Bot")
        embed.timestamp = discord.utils.utcnow()
        return embed

    async def start(self) -> None:
        """The core loop for the match thread bot."""
        # Gather initial data
        await self.fixture.refresh(self.bot)

        # Post Pre-Match Thread if required
        title, markdown = await self.pre_match()

        subreddit = await self.bot.reddit.subreddit(self.settings["subreddit"])

        k_o = self.fixture.kickoff
        if k_o is None:
            raise ValueError("Kickoff is None")

        if self.mtb_history["pre_match_url"] is None:
            if (offset := self.settings["pre_match_offset"]) is None:
                offset = 3
            offset = datetime.timedelta(days=offset)

            target_time = k_o - offset

            await discord.utils.sleep_until(target_time)

            pre = await subreddit.submit(selftext=markdown, title=title)
            await pre.load()

            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = """UPDATE mtb_history SET pre_match_url = $1 WHERE
                             (subreddit, fs_link) = ($2, $3)"""
                    self.mtb_history = await connection.fetchrow(
                        sql,
                        pre.url,
                        self.settings["subreddit"],
                        self.fixture.url,
                    )
        else:
            pre = await self.bot.reddit.submission(
                url=self.mtb_history["pre_match_url"]
            )
            await pre.edit(markdown)

        if channel := self.bot.get_channel(self.settings["notify_channel"]):
            embed = self.base_embed
            embed.title = f"Pre-Match Thread: {self.fixture.score_line}"
            embed.url = pre.url
            embed.description = f"[Flashscore Link]({self.fixture.url})"

            channel = typing.cast(discord.TextChannel, channel)
            await channel.send(embed=embed)

        # Sleep until ready to post.
        if isinstance(self.fixture.time, datetime.datetime):
            if (offset := self.settings["match_offset"]) is None:
                offset = 15
            offset = datetime.timedelta(minutes=offset)
            await discord.utils.sleep_until(k_o - offset)

        # Refresh fixture at kickoff.
        await self.fixture.refresh(self.bot)
        title, markdown = await self.write_markdown()

        # Post initial thread or resume existing thread.
        if self.mtb_history["match_thread_url"] is None:
            match = await subreddit.submit(selftext=markdown, title=title)
            await match.load()
            if channel:
                s_r = self.settings["subreddit"]
                url = self.fixture.url
                await channel.send(
                    f"{s_r} Match Thread Posted: {match.url} | <{url}>"
                )

            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = """UPDATE mtb_history SET match_thread_url = $1
                          WHERE (subreddit, fs_link) = ($2, $3) RETURNING *"""

                    self.mtb_history = await connection.fetchrow(
                        sql,
                        match.url,
                        self.settings["subreddit"],
                        self.fixture.url,
                    )
        else:
            mt_url = self.mtb_history["match_thread_url"]
            match = await self.bot.reddit.submission(url=mt_url)
            await match.edit(markdown)

        for _ in range(300):  # Maximum number of loops.
            if self.stop:
                break

            await self.fixture.refresh(self.bot)

            title, markdown = await self.write_markdown()
            # Only need to update if something has changed.
            if markdown != self.old_markdown:
                await match.edit(markdown)
                self.old_markdown = markdown

            if self.fixture.state is not None:
                if self.fixture.state.colour in [0xFFFFFF, 0xFF0000]:
                    break

            await asyncio.sleep(60)

        # Make post-match thread
        title, markdown = await self.write_markdown(post_match=True)
        # Create post match thread, insert link into DB.
        if self.mtb_history["post_match_url"] is None:
            post = await subreddit.submit(selftext=markdown, title=title)
            await post.load()

            async with self.bot.db.acquire(timeout=60) as con:
                async with con.transaction():
                    sql = """UPDATE mtb_history SET post_match_url = $1 WHERE
                            (subreddit, fs_link) = ($2, $3)"""
                    url = self.fixture.url
                    p_url = post.url
                    s_r = self.settings["subreddit"]
                    self.mtb_history = await con.fetchrow(sql, p_url, s_r, url)
            if channel:
                await channel.send(
                    f"{s_r} Post-Match Thread: <{p_url}> | <{url}>"
                )

        else:
            post_url = self.mtb_history["post_match_url"]
            post = await self.bot.reddit.submission(url=post_url)

        # Re-write post with actual link in it.
        title, markdown = await self.write_markdown(post_match=True)
        await post.edit(markdown)

        # Edit match markdown to include the post-match link.
        _, markdown = await self.write_markdown()
        mt_url = self.mtb_history["match_thread_url"]
        match = await self.bot.reddit.submission(url=mt_url)
        await match.edit(markdown)

        # Then edit the pre-match thread with both links too.
        markdown = pre.selftext
        if self.mtb_history is not None:
            markdown = markdown.replace(
                "*Pre*", f"[Pre]({self.mtb_history['pre_match_url']})"
            )
            markdown = markdown.replace(
                "*Match*", f"[Match]({self.mtb_history['match_thread_url']})"
            )
            markdown = markdown.replace(
                "*Post*", f"[Post]({self.mtb_history['post_match_url']})"
            )
        await pre.edit(markdown)

        if channel:
            url = self.fixture.url
            await channel.send(
                f"{subreddit} Match Thread Completed: {post.url} | <{url}>"
            )

    async def pre_match(self):
        """Create a pre-match thread"""
        # Alias for easy replacing.
        home = self.fixture.home.name
        away = self.fixture.away.name

        # Grab DB data
        try:
            _ = [i for i in self.bot.reddit_teams if i["name"] == home][0]
            home_icon = _["icon"]
            home_link = _["subreddit"]
        except IndexError:
            home_icon = ""
            home_link = ""

        try:
            _ = [i for i in self.bot.reddit_teams if i["name"] == away][0]
            away_icon = _["icon"]
            away_link = _["subreddit"]
        except IndexError:
            away_icon = ""
            away_link = ""

        h_str = f"{home_icon}[{home}]({home_link})"
        a_str = f"[{away}]({away_link}){away_icon}"
        markdown = f"# {h_str} vs {a_str}\n\n"

        fix = self.fixture
        markdown += (
            f"#### {fix.kickoff} | {fix.competition} |"
            " *Pre* | *Match* | *Post*\n\n"
        )

        title = f"Pre-Match Thread: {self.fixture.score_line}"
        # markdown += await self.fixture.preview()
        return title, markdown

    async def fetch_tv(self) -> dict:
        """Fetch information about where the match will be televised"""

        async with self.bot.session.get(LSTV) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
            tree = html.fromstring(await resp.text())

        tv = {}
        for i in tree.xpath(".//tr//a"):
            if self.fixture.home.name in "".join(i.xpath(".//text()")):
                lnk = i.xpath(".//@href")
                tv.update({"link": f"http://www.livesoccertv.com{lnk}"})
                break
        if not tv:
            return {}

        async with self.bot.session.get(tv["link"]) as resp:
            if resp.status != 200:
                tree = html.fromstring(await resp.text())
            else:
                text = await resp.text()
                logger.error("%s %s: %s", resp.status, text, resp.url)
                return tv

        tv_table = tree.xpath('.//table[@id="wc_channels"]//tr')

        if not tv_table:
            tv.update({"uk_tv": ""})
            return tv

        for i in tv_table:
            country = i.xpath(".//td[1]/span/text()")
            if "United Kingdom" not in country:
                continue
            uk_tv_channels = i.xpath(".//td[2]/a/text()")
            uk_tv_links = i.xpath(".//td[2]/a/@href")
            uk_tv_links = [
                f"http://www.livesoccertv.com/{i}" for i in uk_tv_links
            ]
            uk_tv = list(zip(uk_tv_channels, uk_tv_links))
            tv.update({"uk_tv": [f"[{i}]({j})" for i, j in uk_tv]})
        return tv

    async def send_notification(self, channel_id, post):
        """Announce new posts to designated channels."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return  # Rip

        channel = typing.cast(discord.TextChannel, channel)
        await channel.send(
            embed=discord.Embed(
                colour=0xFF4500, title=post.title, url=post.url
            )
        )

    async def write_markdown(self, post_match=False):
        """Write markdown for the current fixture"""
        await self.fixture.refresh(self.bot)

        # Alias for easy replacing.
        home = self.fixture.home.name
        away = self.fixture.away
        score = self.fixture.score

        if self.fixture.kickoff is not None:
            time = self.fixture.kickoff.strftime("%d/%m/%Y, %H:%M:%S")
        else:
            time = ""

        if self.fixture.competition is not None:
            comp = self.fixture.competition.title
        else:
            comp = ""
        if comp:
            markdown = f"#### {time} | {comp}\n\n"
        else:
            markdown = f"#### {time}"

        # Grab DB data
        try:
            home_team = [
                i for i in self.bot.reddit_teams if i["name"] == home
            ][0]
            home_icon = home_team["icon"]
            home_link = home_team["subreddit"]
        except IndexError:
            home_icon = ""
            home_link = None

        try:
            away_team = [
                i for i in self.bot.reddit_teams if i["name"] == away
            ][0]
            away_icon = away_team["icon"]
            away_link = away_team["subreddit"]
        except IndexError:
            away_icon = ""
            away_link = None

        # Title, title bar, & penalty shoot-out bar.
        try:
            p_h, p_a = self.fixture.penalties_home, self.fixture.penalties_away
            pens = f" (p. {p_h} - {p_a}) "

            h_md = f"{home_icon} {home_link}"
            a_md = f"{away_link} {away_icon}"
            markdown += f"# {h_md} {score}{pens} {a_md}\n\n"
        except AttributeError:
            pens = ""

        if post_match:
            title = f"Post-Match Thread: {home} {score}{pens}{away}"
        else:
            title = f"Match Thread: {home} vs {away}"

        # Referee and Venue
        ven = []
        if self.fixture.referee:
            ven.append(f"**🙈 Referee**: {self.fixture.referee}")
        if self.fixture.stadium:
            ven.append(f"**🥅 Venue**: {self.fixture.stadium}")
        if self.fixture.attendance:
            ven.append(f"**👥 Attendance**: {self.fixture.attendance})")

        if ven:
            markdown += "####" + " | ".join(ven) + "\n\n"

        # Match Threads Bar.
        archive = f"[Archive]({self.mtb_history['archive_link']}"
        try:
            pre = f"[Pre]({self.mtb_history['pre_match_url']})"
        except (AttributeError, TypeError):
            pre = "*Pre*"

        try:
            match = f"[Match]({self.mtb_history['match_thread_url']})"
        except (AttributeError, TypeError):
            match = "*Match*"

        try:
            post = f"[Post]({self.mtb_history['post_match_url']})"
        except (AttributeError, TypeError):
            post = "*Post*"

        if threads := " - ".join(
            [i for i in [pre, match, post, archive] if i]
        ):
            markdown += f"---\n\n##{threads}\n\n---\n\n"

        # Radio, TV.
        if not post_match:
            if radio := self.settings["radio_link"]:
                markdown += f"[📻 Radio Commentary]({radio})\n\n"
            if sv_discord := self.settings["discord_link"]:
                markdown += f"[](#icon-discord) [Discord]({sv_discord})\n\n"

            if not self.t_v:
                t_v = await self.fetch_tv()
                if t_v is not None:
                    self.t_v = (
                        f"📺🇬🇧 **TV** (UK): {t_v['uk_tv']}\n\n"
                        if t_v["uk_tv"]
                        else ""
                    )
                    self.t_v += (
                        "📺🌍 **TV** (International): "
                        f"[International TV Coverage]({t_v['link']})\n\n"
                    )
                else:
                    self.t_v = ""

            markdown += self.t_v

        # markdown += f"* [Formation]({await self.fixture.formation()})\n"
        # markdown += f"* [Stats]({await self.fixture.stats()})\n"
        # markdown += f"* [Table]({await self.fixture.table()})\n"

        if self.fixture.images:
            markdown += "## Match Pictures\n"
            markdown += ", ".join(
                f"[Picture {count}]({item})"
                for count, item in enumerate(self.fixture.images)
            )

        # Match Events
        formatted_ticker = ""
        for event in self.fixture.events:
            team = event.team

            team = home_icon if team == home else team
            team = away_icon if team == away else team

            markdown += str(event)

        markdown += (
            f"\n\n---\n\n{formatted_ticker}\n\n---\n\n^(*Beep boop, I"
            " am /u/Toon-bot, a bot coded ^badly by /u/Painezor. If "
            "anything appears to be weird or off, please let him know"
            ".*)"
        )

        return title, markdown


class MatchThreadCommands(commands.Cog):
    """MatchThread Commands and Spooler."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.active_threads: list[MatchThread] = []
        self.scheduler_task = self.schedule_threads.start()

    async def cog_unload(self) -> None:
        """Cancel all current match threads."""
        self.scheduler_task.cancel()
        for i in self.active_threads:
            i.stop = True
            i.task.cancel()

    @tasks.loop(hours=24)
    async def schedule_threads(self) -> None:
        """Schedule tomorrow's match threads"""
        # Number of minutes before the match to post
        async with self.bot.db.acquire(timeout=60) as connection:
            records = await connection.fetch("""SELECT * FROM mtb_schedule""")

        for i in records:
            # Get upcoming games from flashscore.
            if (team := self.bot.get_team(i["team_flashscore_id"])) is None:
                continue

            cache = self.bot.competitions
            page = await self.bot.browser.new_page()

            try:
                fixtures = await team.fixtures(page, cache)
            finally:
                await page.close()

            for fixture in fixtures:
                await self.spool_thread(fixture, i)

    async def spool_thread(
        self, fixture: fs.Fixture, settings: asyncpg.Record
    ) -> None:
        """Create match threads for all scheduled games."""

        if fixture.kickoff is None:
            raise AttributeError(f"fixture {fixture} has no kickoff")

        diff = fixture.kickoff - datetime.datetime.now(
            tz=datetime.timezone.utc
        )
        if diff.days > 7:
            return

        sub = settings["subreddit"]
        for i in self.active_threads:
            if i.fixture == fixture and i.settings == settings:
                return

        sql = """SELECT * FROM mtb_history
                 WHERE (subreddit, fs_link) = ($1, $2)"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                record = await connection.fetchrow(sql, sub, fixture.url)
                if not record:
                    sql = """INSERT INTO mtb_history (subreddit, fs_link)
                             VALUES ($1, $2) RETURNING *"""
                    record = await connection.fetchrow(sql, sub, fixture.url)

        thread = MatchThread(self.bot, fixture, settings, record)
        self.active_threads.append(thread)
        await thread.start()


async def setup(bot: Bot) -> None:
    """Load the match thread cog into the bot"""
    await bot.add_cog(MatchThreadCommands(bot))
