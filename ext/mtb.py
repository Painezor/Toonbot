"""r/NUFC Match Thread Bot"""
import asyncio
import datetime
from importlib import reload

import asyncpg
import discord
import praw
from discord.ext import commands
from discord.ext import tasks
from lxml import html

from ext.utils import football


async def imgurify(bot, img_url):
    """Upload an image to imgur"""
    d = {"image": img_url}
    h = {'Authorization': f'Client-ID {bot.credentials["Imgur"]["Authorization"]}'}
    async with bot.session.post("https://api.imgur.com/3/image", data=d, headers=h) as resp:
        res = await resp.json()
    try:
        return res['data']['link']
    except KeyError:
        return None


async def get_ref_link(bot, name):
    """Fetch referee info and return markdown link"""
    name = name.strip()  # clean up nbsp.
    surname = name.split(' ')[0]
    url = 'http://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche'
    p = {"query": surname, "Schiedsrichter_page": "0"}
    async with bot.session.get(url, params=p) as ref_resp:
        if ref_resp.status != 200:
            return name
        tree = html.fromstring(await ref_resp.text())
    matches = f".//div[@class='box']/div[@class='table-header'][contains(text(),'referees')]" \
              f"/following::div[1]//tbody/tr"
    trs = tree.xpath(matches)
    if trs:
        link = trs[0].xpath('.//td[@class="hauptlink"]/a/@href')[0]
        name = trs[0].xpath('.//td[@class="hauptlink"]/a/text()')[0]
        link = f"http://www.transfermarkt.co.uk/{link}"
        return f"[{name}]({link})"

    p = {"query": name, "Schiedsrichter_page": "0"}
    async with bot.session.get(url, params=p) as ref_resp:
        if ref_resp.status != 200:
            return name
        tree = html.fromstring(await ref_resp.text())
        matches = f".//div[@class='box']/div[@class='table-header'][contains(text(),'referees')]" \
                  f"/following::div[1]//tbody/tr"
        trs = tree.xpath(matches)
        if trs:
            link = trs[0].xpath('.//td[@class="hauptlink"]/a/@href')[0]
            name = trs[0].xpath('.//td[@class="hauptlink"]/a/text()')[0]
            link = f"http://www.transfermarkt.co.uk/{link}"
            return f"[{name}]({link})"
        else:
            return name

   
class MatchThread:
    """Tool for updating a reddit post with the latest information about a match."""
    def __init__(self, bot, subreddit, fixture):
        self.bot = bot
        self.active = True
        self.subreddit = subreddit
        self.fixture = fixture
        
        # Fetch once
        self.tv = None
        
        # Reddit stuff.
        self.subreddit = subreddit
        self.pre_match_url = None
        self.match_thread_url = None
        self.post_match_url = None
        self.archive = None
        
        # Caching
        self.cached_formations = None
        self.cached_statistics = None
        self.cached_table = None
        self.old_markdown = ""
        
        # Commence loop
        self.task = self.bot.loop.create_task(self.match_thread_loop())

    async def match_thread_loop(self):
        """The core loop for the match thread bot."""
        # Dupe check.
        connection = await self.bot.db.acquire()
        print("Searching db for values:", self.subreddit, self.fixture.url)

        r = await connection.fetchrow("""SELECT FROM mtb_history WHERE subreddit = $1 AND fs_link = $2""",
                                      self.subreddit, self.fixture.url)

        if r is not None:
            self.post_match_url = r['post_match_url']
            self.match_thread_url = r['match_thread_url']
            self.pre_match_url = r['pre_match_url']
            self.archive = r['archive_link']
        else:
            async with connection.transaction():
                await connection.execute("""INSERT INTO mtb_history (fs_link, subreddit)
                                           VALUES ($1, $2)""", self.fixture.url, self.subreddit)

        if hasattr(self, "pre_match_offset"):
            print('Pre-match-offset check.')
            target_time = self.fixture.time - datetime.timedelta(minutes=self.pre_match_offset)
            print("Sleeping until", target_time)
            await discord.utils.sleep_until(target_time)
            print('pre-match-sleep ended.')
            if self.pre_match_url is None:
                # TODO: Pre-match posting.
                title, markdown = await self.make_pre_match()
                pre_match_instance = await self.bot.loop.run_in_executor(None, self.make_post, title, markdown)
                self.pre_match_url = pre_match_instance.url
                connection = await self.bot.db.acquire()
                async with connection.transaction():
                    await connection.execute("""UPDATE mtb_history
                                                SET pre_match_url = $1
                                                WHERE (subreddit, fs_link) = ($2, $3)""",
                                             self.pre_match_url, self.subreddit, self.fixture.url)
                await self.bot.db.release(connection)
            else:
                pre_match_instance = await self.bot.loop.run_in_executor(None, self.fetch_post, self.pre_match_url)
                self.pre_match_url = pre_match_instance.url
        else:
            pre_match_instance = None
        
        # Gather initial data
        page = await self.bot.browser.newPage()
        try:
            await self.fixture.refresh(page)
        except Exception as e:
            print("Error when refreshing match thread fixture")
            raise e
        finally:
            await page.close()
        
        title, markdown = await self.write_markdown()
        
        # Sleep until ready to post.
        if isinstance(self.fixture.time, datetime.datetime):
            if hasattr(self, "match_offset"):
                await discord.utils.sleep_until(self.fixture.time - datetime.timedelta(minutes=self.match_offset))
    
        # Post initial thread or resume existing thread.
        if self.match_thread_url is None:
            post = await self.bot.loop.run_in_executor(None, self.make_post, title, markdown)
            connection = await self.bot.db.acquire()
            await connection.execute("""UPDATE mtb_history
                                        SET match_thread_url = $1
                                        WHERE (subreddit, fs_link) = ($2, $3)""",
                                     post.url, self.subreddit, self.fixture.url)
            await self.bot.db.release(connection)
        else:
            post = await self.bot.loop.run_in_executor(None, self.fetch_post, self.match_thread_url)
    
        self.match_thread_url = post.url
    
        for i in range(300):  # Maximum number of loops.
            page = await self.bot.browser.newPage()
            await self.fixture.refresh(page)
            await page.close()
            
            title, markdown = await self.write_markdown()
            # Only need to update if something has changed.
            if markdown != self.old_markdown:
                await self.bot.loop.run_in_executor(None, post.edit, markdown)
                self.old_markdown = markdown
        
            if not self.active:  # Set in self.scrape.
                break
        
            await asyncio.sleep(60)
    
        # Grab final data
        title, markdown = self.write_markdown()
        # Create post match thread, get link.
        if self.post_match_url is None:
            post_match_instance = await self.bot.loop.run_in_executor(None, self.make_post, title, markdown)
            post = await self.bot.loop.run_in_executor(None, self.make_post, title, markdown)
            connection = await self.bot.db.acquire()
            await connection.execute("""UPDATE mtb_history
                                        SET post_match_url = $1
                                        WHERE (subreddit, fs_link) = ($2, $3)""",
                                     self.post_match_url, self.subreddit, self.fixture.url)
            await self.bot.db.release(connection)
        else:
            post_match_instance = await self.bot.loop.run_in_executor(self.fetch_post(self.post_match_url))
        self.post_match_url = post_match_instance.url
    
        # Edit it's markdown to include the link.
        title, markdown = await self.write_markdown(is_post_match=True)
        await self.bot.loop.run_in_executor(None, post_match_instance.edit, markdown)
    
        # Then edit the match thread with the link too.
        title, markdown = await self.write_markdown()
        await self.bot.loop.run_in_executor(None, post.edit, markdown)
    
        # and finally, edit pre_match to include links
        title, markdown = self.make_pre_match()
        if hasattr(self, "pre_match_offset"):
            if pre_match_instance is not None:
                self.bot.loop.run_in_executor(None, pre_match_instance.edit, markdown)
        
    # Reddit posting shit.
    def make_post(self, title, markdown):
        """Upload a post to reddit"""
        post = self.bot.reddit.subreddit(self.subreddit).submit(title, selftext=markdown)
        if hasattr(self, "announcement_channel_id"):
            self.bot.loop.create_task(self.send_notification(self.announcement_channel_id, post))
        return post

    def fetch_post(self, resume):
        """Fetch an existing reddit post."""
        try:
            if "://" in resume:
                post = self.bot.reddit.submission(url=resume)
            else:
                post = self.bot.reddit.submission(id=resume)
        except Exception as e:
            print("Error during fetch post..", e)
            post = None
        return post
    
    async def make_pre_match(self):
        """Create a prematch-thread"""
        # TODO: Actually write the code.
        self.pre_match_url = None
        title = "blah"
        markdown = "blah"
        return title, markdown
    
    async def fetch_tv(self):
        """Fetch information about where the match will be televised"""
        tv = {}
        async with self.bot.session.get(f"https://www.livesoccertv.com/") as resp:
            if resp.status != 200:
                print(f"{resp.status} recieved when trying to fetch TV url {resp.url}")
                return None
            tree = html.fromstring(await resp.text())
            for i in tree.xpath(".//tr//a"):
                if self.fixture.home in "".join(i.xpath(".//text()")):
                    lnk = "".join(i.xpath(".//@href"))
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
    
    async def send_notification(self, channel_id, post: praw.Reddit.post):
        """Announce new posts to designated channels."""
        channel = await self.bot.get_channel(channel_id)
        if channel is None:
            return  # Rip
        
        e = discord.Embed()
        e.colour = 0xFF4500
        e.title = post.title
        e.url = post.url
        await channel.send(embed=e)
    
    async def write_markdown(self, is_post_match=False):
        """Write markdown for the current fixture"""
        page = await self.bot.browser.newPage()
        await self.fixture.refresh(page)
        
        # Alias for easy replacing.
        home = self.fixture.home
        away = self.fixture.away
        score = self.fixture.score
        # Date and Competition bar
        if self.fixture.kickoff is None:
            kickoff = await self.fixture.fetch_kickoff(page)
        else:
            kickoff = self.fixture.kickoff

        markdown = f"#### {kickoff} | {self.fixture.full_league} \n\n"
       
        # Grab DB data
        try:
            home_team = [i for i in self.bot.teams if i['name'] == home][0]
            home_icon = home_team['icon']
            home_link = home_team['subreddit']
        except IndexError:
            print(f"MTB Loop: unable to find {home} in db")
            home_icon = ""
            home_link = None
        
        try:
            away_team = [i for i in self.bot.teams if i['name'] == away][0]
            away_icon = away_team['icon']
            away_link = away_team['subreddit']
        except IndexError:
            print(f"MTB Loop: unable to find {away} in db")
            away_icon = ""
            away_link = None
        
        # Title, title bar, & penalty shoot-out bar.
        ph = self.fixture.penalties_home
        pa = self.fixture.penalties_away
        if ph:
            markdown += f"# {home_icon} {home_link} {score} (p. {ph} - {pa}) {away_link} {away_icon}\n\n"
        else:
            markdown += f"# {home_icon} {home_link} {score} {away_link} {away_icon}\n\n"
        
        print('Markdown breakpoint 5')
        
        if is_post_match:
            if self.fixture.penalties_home is not None:
                title = f"Post-Match Thread: {home} {score} (p. {ph} - {pa}) {away}"
            else:
                title = f"Post-Match Thread: {home} {score} {away}"
        else:
            title = f"Match Thread: {home} vs {away}"
        
        print("markdown", markdown)
        print("title", title)
        
        # Referee and Venue
        if self.fixture.referee is not None:
            referee = "**🙈 Referee**: " + await get_ref_link(self.bot, self.fixture.referee)
        else:
            referee = ""
        
        # TODO: Get venue link.
        stadium = f"**🥅 Venue**: {self.fixture.stadium}" if self.fixture.stadium is not None else ""
        attendance = f" (👥 Attendance: {self.fixture.attendance})" if self.fixture.attendance is not None else ""
        print("Stadium Referee Attendance", self.fixture.stadium, referee, self.fixture.attendance)
        
        if any([referee, stadium, attendance]):
            markdown += "####" + " | ".join([i for i in [referee, stadium, attendance] if i]) + "\n\n"
        
        # Match Threads Bar.
        archive = f"[Match Thread Archive]({self.archive_link}" if hasattr(self, "archive_link") else ""
        pre = f"[Pre-Match Thread]({self.pre_match_url})" if self.pre_match_url else ""
        match = f"[Match Thread]({self.match_thread_url})" if self.match_thread_url else ""
        post = f"[Post-Match Thread]({self.post_match_url})" if self.post_match_url else ""
        
        threads = [i for i in [pre, match, post, archive] if i]
        if threads:
            markdown += "---\n\n##" + " | ".join(threads) + "\n\n---\n\n"
        
        print("Match threads bar:", threads)
        
        # Radio, TV.
        if not is_post_match:
            if hasattr(self, "radio_link"):
                markdown += f"[📻 Radio Commentary]({self.radio_link})\n\n"
            if hasattr(self, "invite_link"):
                markdown += f"[](#icon-discord) [Join us on Discord]({self.invite_link})\n\n"
                
            if not hasattr(self.fixture, "tv"):
                self.fixture.tv = ""
                tv = await self.fetch_tv()
                self.fixture.tv = f"📺🇬🇧 **TV** (UK): {tv['uk_tv']}\n\n" if tv["uk_tv"] else ""
                self.fixture.tv += f"📺🌍 **TV** (Intl): [International TV Coverage]({tv['link']})\n\n"

            print("DEBUG TV:", self.fixture.tv)
            markdown += self.fixture.tv

        if not self.cached_formations == self.fixture.formation:
            await imgurify(self.bot, self.fixture.formation)
            self.cached_formations = self.fixture.formation

        markdown += f"* [Formation]({self.cached_formations})\n"

        stats_image = await self.fixture.get_stats(page)
        if not self.cached_statistics == stats_image:
            stats_image = await imgurify(self.bot, stats_image)
            self.cached_statistics = stats_image

        markdown += f"* [Stats]({self.cached_statistics})\n"

        table_image = await self.fixture.get_table(page)
        if not self.cached_table == table_image:
            table_image = await imgurify(self.bot, table_image)
            self.cached_table = table_image

        markdown += f"* [Table]({self.cached_table})\n"

        if self.fixture.images:
            markdown += "## Match Pictures\n"
            markdown += ", ".join(f"[Picture {count}]({item})" for count, item in enumerate(self.fixture.images))

        # Match Events
        formatted_ticker = ""
        penalty_mode = False
        for event in self.fixture.events:
            team = event.team

            team = home_icon if team == home else team
            team = away_icon if team == away else team

            event.team = team

            markdown += str(event)
        
        markdown += "\n\n---\n\n" + formatted_ticker + "\n\n"
        markdown += "\n\n---\n\n^(*Beep boop, I am /u/Toon-bot, a bot coded ^badly by /u/Painezor. " \
                    "If anything appears to be weird or off, please let him know.*)"
        
        print("Markdown before time print", markdown)
        
        print("debug, time:", self.fixture.time, type(self.fixture.time))
        await page.close()
        return title, markdown


class MatchThreadCommands(commands.Cog):
    """MatchThread Commands and Spooler."""

    def __init__(self, bot):
        self.bot = bot
        self.active_threads = []
        self.scheduler_task = self.schedule_threads.start()
        reload(football)

    def cog_unload(self):
        """Cancel all current match threads."""
        self.scheduler_task.cancel()
        for i in self.active_threads:
            i.task.cancel()

    def cog_check(self, ctx):
        """Assure commands can only be ran from the r/NUFC discord"""
        if ctx.guild:
            return ctx.guild.id in [332159889587699712, 250252535699341312]

    async def spool_thread(self, f: football.Fixture, r: asyncpg.Record):
        """Create match threads for all scheduled games."""
        subreddit = r['subreddit']

        for i in self.active_threads:
            if (subreddit, i.url) in self.active_threads:
                print(f'Not spooling duplicate thread: {subreddit} {i.score}.')
                return

            print(f"Spooling match thread: {subreddit} {i.score}")
            MatchThread(self.bot, subreddit, f)
            self.active_threads.append((subreddit, i.url))
    
    @tasks.loop(hours=24)
    async def schedule_threads(self):
        """Schedule tomorrow's match threads"""
        # Number of minutes before the match to post
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM mtb_schedule""")
        await self.bot.db.release(connection)
        
        for r in records:
            # Get upcoming games from flashscore.
            page = await self.bot.browser.newPage()
            team = await football.Team.by_id(r["team_flashscore_id"], page=page)
            fx = await team.get_fixtures(page=page)
            for i in fx:
                if i.time - datetime.datetime.now() > datetime.timedelta(days=3):
                    self.bot.loop.create_task(self.spool_thread(i, r))
            await page.close()


def setup(bot):
    """Load the match thread cog into the bot"""
    bot.add_cog(MatchThreadCommands(bot))
