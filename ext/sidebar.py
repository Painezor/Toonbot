"""Background loop to update the wiki page and sidebar for the r/NUFC subreddit"""
import datetime
import math
import re
from importlib import reload
from typing import Optional

import asyncpraw
from PIL import Image
from discord import Attachment, Embed, File, app_commands, Object, Interaction
from discord.ext import commands, tasks
from lxml import html

from ext.utils import football

NUFC_DISCORD_LINK = "nufc"  # TuuJgrA


def rows_to_md_table(header, strings, per=20, max_length=10240):
    """Create sidebar pop out tables"""
    rows = []
    for num, obj in enumerate(strings):
        # Every row we buffer the length of the new result.
        max_length -= len(obj)

        # Every 20 rows we buffer the length of  another header.
        if num % 20 == 0:
            max_length -= len(header)
        if max_length < 0:
            break
        else:
            rows.append(obj)

    if not rows:
        return ""

    height = math.ceil(len(rows) / (len(rows) // per + 1))
    chunks = [''.join(rows[i:i + height]) for i in range(0, len(rows), height)]
    chunks.reverse()
    markdown = header + header.join(chunks)

    return markdown


@app_commands.command()
@app_commands.describe(image="Upload a new sidebar image", caption="Set a new Sidebar Caption")
async def sidebar(interaction: Interaction, caption: Optional[str] = None, image: Optional[Attachment] = None):
    """Upload an image to the sidebar, or edit the caption."""

    if "Subreddit Moderators" not in [i.name for i in interaction.user.roles]:
        return await interaction.client.error(interaction, "You need the 'Subreddit Moderators' role to do that")

    await interaction.response.defer()
    # Check if message has an attachment, for the new sidebar image.
    e = Embed(color=0xff4500, url="http://www.reddit.com/r/NUFC")
    th = "http://vignette2.wikia.nocookie.net/valkyriecrusade/images/b/b5/Reddit-The-Official-App-Icon.png"
    e.set_author(icon_url=th, name="r/NUFC Sidebar updated")
    file = None

    if caption:
        _ = await interaction.client.reddit.subreddit('NUFC')
        _ = await _.wiki.get_page('sidebar')
        markdown = re.sub(r'---.*?---', f"---\n\n> {caption}\n\n---", _.content_md, flags=re.DOTALL)
        await _.edit(content=markdown)
        e.description = f"Set caption to: {caption}"

    if image:
        await image.save("sidebar.png")
        s = await interaction.client.reddit.subreddit("NUFC")
        await s.stylesheet.upload("sidebar", "sidebar.png")
        style = await s.stylesheet()
        await s.stylesheet.update(style.stylesheet, reason=f"Sidebar image by {interaction.user} via discord")

        e.set_image(url=f"attachment://sidebar.png")
        file = File(fp="sidebar.png", filename="sidebar.png")

    # Build
    subreddit = await interaction.client.reddit.subreddit('NUFC')
    wiki = await subreddit.wiki.get_page("config/sidebar")
    await wiki.edit(content=await make_sidebar(interaction.client))
    await interaction.client.reply(interaction, embed=e, file=file)


async def make_sidebar(bot, subreddit="NUFC", qry="newcastle", team_id="p6ahwuwJ"):
    """Build the sidebar markdown"""
    # Fetch all data
    _ = await bot.reddit.subreddit(subreddit)
    _ = await _.wiki.get_page('sidebar')
    top = _.content_md

    page = await bot.browser.newPage()
    try:
        fsr = await football.Team.by_id(team_id, page)
        fixtures = await fsr.get_fixtures(page, "/fixtures")
        results = await fsr.get_fixtures(page, "/results")
    finally:
        await page.close()

    async def table():
        """Get the latest premier league table from the BBC website for formatting"""
        async with bot.session.get('http://www.bbc.co.uk/sport/football/premier-league/table') as resp:
            if resp.status != 200:
                return "Retry"
            tree = html.fromstring(await resp.text())

        table_data = f"\n\n* Table\n\n Pos.|Team|P|W|D|L|GD|Pts\n--:|:--{'|:--:' * 6}\n"
        for i in tree.xpath('.//table[contains(@class,"gs-o-table")]//tbody/tr')[:20]:
            p = i.xpath('.//td//text()')
            rank = p[0].strip()  # Ranking
            movement = p[1].strip()
            if "hasn't" in movement:
                movement = ''
            elif "up" in movement:
                movement = '🔺'
            elif "down" in movement:
                movement = '🔻'
            else:
                movement = "?"
            team = p[2].strip()
            try:
                # Insert subreddit link from db
                team = [i for i in bot.teams if i['name'] == team][0]
                if team:
                    team = f"[{team['name']}]({team['subreddit']})"
                else:
                    print("Sidebar, error, team is ", team)
            except IndexError:
                print(team, "Not found in", [i['name'] for i in bot.teams])
            played, won, drew, lost = p[3:7]
            goal_diff, points = p[9:11]

            if qry.lower() in team.lower():
                table_data += f"{movement} {rank} | **{team}** | **{played}** | **{won}** | **{drew}** | **{lost}** | " \
                              f"**{goal_diff}** | **{points}**\n"
            else:
                table_data += f"{movement} {rank} | {team} | {played} | {won} | {drew} | {lost} | " \
                              f"{goal_diff} | {points}\n"
        return table_data

    table = await table()

    # Get match threads
    async def get_match_threads():
        """Search the subreddit for all recent match threads for pattern matching"""
        last_opponent = qry.split(" ")[0]
        sub = await bot.reddit.subreddit("NUFC")
        async for i in sub.search('flair:"Pre-match thread"', sort="new", syntax="lucene"):
            if last_opponent in i.title:
                pre = f"[Pre]({i.url.split('?ref=')[0]})"
                break
        else:
            pre = "Pre"
        async for i in sub.search('flair:"Match thread"', sort="new", syntax="lucene"):
            if not i.title.startswith("Match"):
                continue
            if last_opponent in i.title:
                match = f"[Match]({i.url.split('?ref=')[0]})"
                break
        else:
            match = "Match"

        async for i in sub.search('flair:"Post-match thread"', sort="new", syntax="lucene"):
            if last_opponent in i.title:
                post = f"[Post]({i.url.split('?ref=')[0]})"
                break
        else:
            post = "Post"

        return f"\n\n### {pre} - {match} - {post}"

    match_threads = await get_match_threads()

    # Insert team badges
    for x in fixtures + results:
        try:
            r = [i for i in bot.teams if i['name'] == x.home][0]
            x.home_icon = r['icon']
            x.home_subreddit = r['subreddit']
            x.short_home = r['short_name']
        except IndexError:
            x.home_icon = ""
            x.home_subreddit = "#temp"
            x.short_home = x.home
        try:
            r = [i for i in bot.teams if i['name'] == x.away][0]
            x.away_icon = r['icon']
            x.away_subreddit = r['subreddit']
            x.short_away = r['short_name']
        except IndexError:
            x.away_icon = ""
            x.away_subreddit = "#temp/"
            x.short_away = x.away

    # Build data with passed icons.

    # Start with "last match" bar at the top.
    lm = results[0]

    # CHeck if we need to upload a temporary badge.
    if not lm.home_icon or not lm.away_icon:
        which_team = "home" if not lm.home_icon else "away"
        page = await bot.browser.newPage()
        try:
            badge = await lm.get_badge(page, which_team)
        finally:
            await page.close()

        if badge is not None:
            im = Image.open(badge)
            im.save("TEMP_BADGE.png", "PNG")
            s = await bot.reddit.subreddit("NUFC")
            await s.stylesheet.upload("TEMP_BADGE.png", "temp")
            await s.stylesheet.update(s.stylesheet().stylesheet, reason="Upload a badge")
            print("Uploaded new image to sidebar!")

    top_bar = f"> [{lm.home}]({lm.home_subreddit}) [{lm.score}]({lm.url}) [{lm.away}]({lm.away_subreddit})"
    if fixtures:
        header = "\n* Upcoming fixtures"
        th = "\n\n Date & Time | Match\n--:|:--\n"

        mdl = [f"{i.time.reddit_time} | [{i.short_home} {i.score} {i.short_away}]({i.url})\n" for i in fixtures]
        fx_markdown = header + rows_to_md_table(th, mdl)  # Show all fixtures.
    else:
        fx_markdown = ""

    # After fetching everything, begin construction.
    timestamp = f"\n#####Sidebar updated {datetime.datetime.now().ctime()}\n"
    footer = timestamp + top_bar + match_threads

    if subreddit == "NUFC":
        footer += "\n\n[](https://gg/" + NUFC_DISCORD_LINK + ")"

    markdown = top + table + fx_markdown
    if results:
        header = "* Previous Results\n"
        markdown += header
        th = "\n Date | Result\n--:|:--\n"

        mdl = [f"{i.time.reddit_time} | [{i.short_home} {i.score} {i.short_away}]({i.url})\n" for i in results]
        rx_markdown = rows_to_md_table(th, mdl, max_length=10240 - len(markdown + footer))
        markdown += rx_markdown

    markdown += footer
    return markdown


class NUFCSidebar(commands.Cog):
    """Edit the r/NUFC sidebar"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.reddit = asyncpraw.Reddit(**bot.credentials["Reddit"])
        self.bot.teams = None
        self.bot.sidebar = self.sidebar_loop.start()
        self.bot.tree.add_command(sidebar, guild=Object(id=332159889587699712))
        reload(football)
    
    def cog_unload(self):
        """Cancel the sidebar task when Cog is unloaded."""
        self.bot.sidebar.cancel()

    async def cog_check(self, interaction):
        """Assure commands can only be used on the r/NUFC """
        if not interaction.guild:
            return False
        return 332161994738368523 in [i.id for i in interaction.user.roles] or interaction.user.id == self.bot.owner_id

    @tasks.loop(hours=6)
    async def sidebar_loop(self):
        """Background task, repeat every 6 hours to update the sidebar"""
        markdown = await make_sidebar(self.bot)
        _ = await self.bot.reddit.subreddit('NUFC')
        _ = await _.wiki.get_page("config/sidebar")
        await _.edit(content=markdown)

    @sidebar_loop.before_loop
    async def fetch_team_data(self):
        """Grab information about teams from local database."""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            self.bot.teams = await connection.fetch("""SELECT * FROM team_data""")
        await self.bot.db.release(connection)


def setup(bot):
    """Load the Sidebar Updater Cog into the bot"""
    bot.add_cog(NUFCSidebar(bot))
