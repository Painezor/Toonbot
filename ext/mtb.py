"""r/NUFC Match Thread Bot"""
import asyncio
import datetime

import asyncpg
import asyncpraw
import discord
from discord import Embed
from discord.ext import commands
from discord.ext import tasks
from lxml import html

from ext.utils import football


# TODO: Slash attachments pass
# TODO: Permissions Pass.


class MatchThread:
    """Tool for updating a reddit post with the latest information about a match."""

    def __init__(self, bot, fixture: football.Fixture, settings, record, page):
        self.bot = bot
        self.fixture = fixture
        self.settings = settings
        self.record = record
        self.page = page

        # Fetch once
        self.tv = None

        # Caching
        self.old_markdown = ""

        # Commence loop
        self.stop = False

    @property
    def base_embed(self) -> Embed:
        """Generic Embed for MTB notifications"""
        e = discord.Embed(color=0xff4500)
        th = "http://vignette2.wikia.nocookie.net/valkyriecrusade/images/b/b5/Reddit-The-Official-App-Icon.png"
        e.set_author(icon_url=th, name="Match Thread Bot")
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        return e

    async def start(self) -> None:
        """The core loop for the match thread bot."""
        print(f"Match Thread Loop Started: {self.fixture} | {self.settings['subreddit']}")
        # Gather initial data
        await self.fixture.refresh(self.page)

        # Post Pre-Match Thread if required
        title, markdown = await self.pre_match()

        subreddit = await self.bot.reddit.subreddit(self.settings["subreddit"])

        if self.record["pre_match_url"] is None:
            os = self.settings['pre_match_offset']
            _ = datetime.timedelta(days=3) if os is None else datetime.timedelta(days=os)

            target_time = self.fixture.kickoff - _
            print(f"{self.fixture} | {self.settings['subreddit']}\nSleeping until {target_time}")

            await discord.utils.sleep_until(target_time)
            print(f'{self.fixture} | {self.settings["subreddit"]} Pre-match-sleep ended.')

            pre = await subreddit.submit(selftext=markdown, title=title)
            await pre.load()
            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    self.record = await connection.fetchrow("""UPDATE mtb_history SET pre_match_url = $1 WHERE 
                        (subreddit, fs_link) = ($2, $3)""", pre.url, self.settings['subreddit'], self.fixture.url)
            finally:
                await self.bot.db.release(connection)
        else:
            pre = await self.bot.reddit.submission(url=self.record["pre_match_url"])
            await pre.edit(markdown)

        c = self.bot.get_channel(self.settings['notify_channel'])
        if c:
            e = self.base_embed
            e.title = f"r/{self.settings['subreddit']} Pre-Match Thread: {self.fixture.bold_score}"
            e.url = pre.url
            e.description = f"[Flashscore Link]({self.fixture.url})"
            await c.send(embed=e)

        # Sleep until ready to post.
        if isinstance(self.fixture.time, datetime.datetime):
            os = self.settings["match_offset"]
            _ = 15 if os is None else os
            await discord.utils.sleep_until(self.fixture.time - datetime.timedelta(minutes=_))

        # Refresh fixture at kickoff.
        await self.fixture.refresh(self.page)
        title, markdown = await self.write_markdown()

        # Post initial thread or resume existing thread.
        if self.record['match_thread_url'] is None:
            match = await subreddit.submit(selftext=markdown, title=title)
            await match.load()
            if c:
                await c.send(f'{self.settings["subreddit"]} Match Thread Posted: {match.url} | <{self.fixture.url}>')

            connection = await self.bot.db.acquire()
            async with connection.transaction():
                self.record = await connection.fetchrow("""UPDATE mtb_history SET match_thread_url = $1 WHERE 
                (subreddit, fs_link) = ($2, $3) RETURNING *""", match.url, self.settings['subreddit'], self.fixture.url)
            await self.bot.db.release(connection)
        else:
            match = await self.bot.reddit.submission(url=self.record["match_thread_url"])
            await match.edit(markdown)

        for i in range(300):  # Maximum number of loops.
            if self.stop:
                await self.page.close()
                return

            await self.fixture.refresh(self.page)

            title, markdown = await self.write_markdown()
            # Only need to update if something has changed.
            if markdown != self.old_markdown:
                await match.edit(markdown)
                self.old_markdown = markdown

            if self.fixture.time.state == "fin":
                break

            await asyncio.sleep(60)

        # Make post-match thread
        title, markdown = await self.write_markdown(post_match=True)
        # Create post match thread, insert link into DB.
        if self.record['post_match_url'] is None:
            post = await subreddit.submit(selftext=markdown, title=title)
            await post.load()

            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    self.record = await connection.fetchrow("""UPDATE mtb_history SET post_match_url = $1 WHERE 
                            (subreddit, fs_link) = ($2, $3)""", post.url, self.settings['subreddit'], self.fixture.url)
            finally:
                await self.bot.db.release(connection)

            if c:
                await c.send(f'{self.settings["subreddit"]} Post-Match Thread: <{post.url}> | <{self.fixture.url}>')

        else:
            post = await self.bot.reddit.submission(url=self.record["post_match_url"])

        title, markdown = await self.write_markdown(post_match=True)  # Re-write post with actual link in it.
        await post.edit(markdown)

        # Edit match markdown to include the post-match link.
        _, markdown = await self.write_markdown()
        match = await self.bot.reddit.submission(url=self.record["match_thread_url"])
        await match.edit(markdown)

        # Then edit the pre-match thread with both links too.
        markdown = pre.selftext
        try:
            markdown = markdown.replace('*Pre*', f"[Pre]({self.record['pre_match_url']})")
            markdown = markdown.replace('*Match*', f"[Match]({self.record['match_thread_url']})")
            markdown = markdown.replace('*Post*', f"[Post]({self.record['post_match_url']})")
        except AttributeError:
            pass
        await pre.edit(markdown)

        if c:
            await c.send(f'{self.settings["subreddit"]} Match Thread Loop Completed: {post.url} | <{self.fixture.url}>')
        await self.page.close()

    async def pre_match(self):
        """Create a pre-match thread"""
        # Alias for easy replacing.
        home = self.fixture.home.name
        away = self.fixture.away.name

        # Grab DB data
        try:
            _ = [i for i in self.bot.reddit_teams if i['name'] == home][0]
            home_icon = _['icon']
            home_link = _['subreddit']
        except IndexError:
            print(f"MTB Loop: unable to find {home} in db")
            home_icon = ""
            home_link = ""

        try:
            _ = [i for i in self.bot.reddit_teams if i['name'] == away][0]
            away_icon = _['icon']
            away_link = _['subreddit']
        except IndexError:
            print(f"MTB Loop: unable to find {away} in db")
            away_icon = ""
            away_link = ""

        markdown = f"# {home_icon}[{home}]({home_link}) vs [{away}]({away_link}){away_icon}\n\n"
        markdown += f"#### {self.fixture.kickoff} | {self.fixture.competition} | *Pre* | *Match* | *Post*\n\n"

        title = f"Pre-Match Thread: {self.fixture.bold_score}"
        markdown += await self.fixture.get_preview(self.page)
        return title, markdown

    async def fetch_tv(self):
        """Fetch information about where the match will be televised"""
        tv = {}
        async with self.bot.session.get(f"https://www.livesoccertv.com/") as resp:
            if resp.status != 200:
                print(f"{resp.status} received when trying to fetch TV url {resp.url}")
                return None
            tree = html.fromstring(await resp.text())
            for i in tree.xpath(".//tr//a"):
                if self.fixture.home.name in ''.join(i.xpath(".//text()")):
                    lnk = ''.join(i.xpath(".//@href"))
                    tv.update({"link": f"http://www.livesoccertv.com{lnk}"})
                    break
        if not tv:
            return ""

        async with self.bot.session.get(tv["link"]) as resp:
            if resp.status != 200:
                return tv
            tree = html.fromstring(await resp.text())
            tv_table = tree.xpath('.//table[@id="wc_channels"]//tr')

            if not tv_table:
                tv.update({"uk_tv": ""})
                return tv

            for i in tv_table:
                country = i.xpath('.//td[1]/span/text()')
                if "United Kingdom" not in country:
                    continue
                uk_tv_channels = i.xpath('.//td[2]/a/text()')
                uk_tv_links = i.xpath('.//td[2]/a/@href')
                uk_tv_links = [f'http://www.livesoccertv.com/{i}' for i in uk_tv_links]
                uk_tv = list(zip(uk_tv_channels, uk_tv_links))
                tv.update({"uk_tv": [f"[{i}]({j})" for i, j in uk_tv]})
            return tv

    async def send_notification(self, channel_id, post: asyncpraw.Reddit.post):
        """Announce new posts to designated channels."""
        channel = await self.bot.get_channel(channel_id)
        if channel is None:
            return  # Rip
        await channel.send(embed=discord.Embed(colour=0xFF4500, title=post.title, url=post.url))

    async def write_markdown(self, post_match=False):
        """Write markdown for the current fixture"""
        await self.fixture.refresh(self.page)

        # Alias for easy replacing.
        home = self.fixture.home.name
        away = self.fixture.away
        score = self.fixture.score

        markdown = f"#### {self.fixture.kickoff} | {self.fixture.competition} \n\n"

        # Grab DB data
        try:
            home_team = [i for i in self.bot.reddit_teams if i['name'] == home][0]
            home_icon = home_team['icon']
            home_link = home_team['subreddit']
        except IndexError:
            print(f"MTB Loop: unable to find {home} in db")
            home_icon = ""
            home_link = None

        try:
            away_team = [i for i in self.bot.reddit_teams if i['name'] == away][0]
            away_icon = away_team['icon']
            away_link = away_team['subreddit']
        except IndexError:
            print(f"MTB Loop: unable to find {away} in db")
            away_icon = ""
            away_link = None

        # Title, title bar, & penalty shoot-out bar.
        try:
            ph, pa = self.fixture.penalties_home, self.fixture.penalties_away
            pens = f" (p. {ph} - {pa}) "
            markdown += f"# {home_icon} {home_link} {score}{pens}{away_link} {away_icon}\n\n"
        except AttributeError:
            pens = ""

        title = f"Post-Match Thread: {home} {score}{pens}{away}" if post_match else f"Match Thread: {home} vs {away}"
        print("MTB: title ===>\n", title)
        print("MTB: Markdown ===>\n", markdown)

        # Referee and Venue
        r = f"**🙈 Referee**: {self.fixture.referee}" if hasattr(self.fixture, 'referee') else ""
        s = f"**🥅 Venue**: {self.fixture.stadium}" if hasattr(self.fixture, 'stadium') else ""
        a = f"**👥 Attendance**: {self.fixture.attendance})" if self.fixture.attendance is not None else ""
        print(f"MTB: write_markdown RSA\n{r}\n{s}\n{a}")

        if any([r, s, a]):
            markdown += "####" + " | ".join([i for i in [r, s, a] if i]) + "\n\n"

        # Match Threads Bar.
        archive = f"[Archive]({self.archive_link}" if hasattr(self, "archive_link") else ""
        try:
            pre = f"[Pre]({self.record['pre_match_url']})"
        except (AttributeError, TypeError):
            pre = "*Pre*"

        try:
            match = f"[Match]({self.record['match_thread_url']})"
        except (AttributeError, TypeError):
            match = "*Match*"

        try:
            post = f"[Post]({self.record['post_match_url']})"
        except (AttributeError, TypeError):
            post = "*Post*"

        threads = [i for i in [pre, match, post, archive] if i]
        if threads:
            markdown += "---\n\n##" + " - ".join(threads) + "\n\n---\n\n"

        # Radio, TV.
        if not post_match:
            _ = self.settings['radio_link']
            markdown += f"[📻 Radio Commentary]({_})\n\n" if _ else ""
            _ = self.settings['discord_link']
            markdown += f"[](#icon-discord) [Discord]({_})\n\n" if _ else ""

            if not self.tv:
                tv = await self.fetch_tv()
                if tv is not None:
                    self.tv = f"📺🇬🇧 **TV** (UK): {tv['uk_tv']}\n\n" if tv["uk_tv"] else ""
                    self.tv += f"📺🌍 **TV** (International): [International TV Coverage]({tv['link']})\n\n"
                else:
                    self.tv = ""

            print("MTB DEBUG TV:", self.tv)
            markdown += self.tv

        markdown += f"* [Formation]({await self.fixture.get_formation(self.page)})\n"
        markdown += f"* [Stats]({await self.fixture.get_stats(self.page)})\n"
        markdown += f"* [Table]({await self.fixture.get_table(self.page)})\n"

        if self.fixture.images:
            markdown += "## Match Pictures\n"
            markdown += ", ".join(f"[Picture {count}]({item})" for count, item in enumerate(self.fixture.images))

        # Match Events
        formatted_ticker = ""
        for event in self.fixture.events:
            team = event.team

            team = home_icon if team == home else team
            team = away_icon if team == away else team

            event.team = team

            markdown += str(event)

        markdown += f"\n\n---\n\n{formatted_ticker}\n\n---\n\n^(*Beep boop, I am /u/Toon-bot, a bot coded ^badly by " \
                    f"/u/Painezor. If anything appears to be weird or off, please let him know.*)"

        print("MTB Markdown before time print", markdown)
        print("MTB Fixture time:", self.fixture.time, type(self.fixture.time))
        return title, markdown


class MatchThreadCommands(commands.Cog):
    """MatchThread Commands and Spooler."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.active_threads = []
        self.scheduler_task = self.schedule_threads.start()

    async def cog_unload(self):
        """Cancel all current match threads."""
        self.scheduler_task.cancel()
        for i in self.active_threads:
            i.stop = True
            i.task.cancel()

    @tasks.loop(hours=24)
    async def schedule_threads(self):
        """Schedule tomorrow's match threads"""
        # Number of minutes before the match to post
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM mtb_schedule""")
        await self.bot.db.release(connection)

        page = await self.bot.browser.newPage()
        for r in records:
            # Get upcoming games from flashscore.
            if r["team_flashscore_id"] in self.bot.teams:
                team = self.bot.teams[r['team_flashscore_id']]
            else:
                team = await football.Team.by_id(self.bot, r["team_flashscore_id"], page=page)
                if team is None:
                    continue

            fx = await team.get_fixtures(page, subpage="/fixtures")

            for fixture in fx:
                await self.spool_thread(fixture, r)
        await page.close()

    async def spool_thread(self, f: football.Fixture, settings: asyncpg.Record):
        """Create match threads for all scheduled games."""
        diff = f.kickoff - datetime.datetime.now()
        if diff.days > 7:
            return

        sub = settings['subreddit']
        for x in self.active_threads:
            if x.fixture == f and x.settings == settings:
                print(f'Not spooling duplicate thread: {sub} {f.url}.')
                return

        print(f'Spooling thread: {f.home.name} vs {f.away.name}')

        con = await self.bot.db.acquire()
        async with con.transaction():
            _ = """SELECT * FROM mtb_history WHERE (subreddit, fs_link) = ($1, $2)"""
            record = await con.fetchrow(_, sub, f.url)
            if not record:
                _ = """INSERT INTO mtb_history (subreddit, fs_link) VALUES ($1, $2) RETURNING *"""
                record = await con.fetchrow(_, sub, f.url)
        await self.bot.db.release(con)

        page = await self.bot.browser.newPage()
        _ = MatchThread(self.bot, f, settings, record, page)
        self.active_threads.append(_)
        print("Starting thread...")
        await _.start()


async def setup(bot):
    """Load the match thread cog into the bot"""
    await bot.add_cog(MatchThreadCommands(bot))
