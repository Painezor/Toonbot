"""Background loop to update the wiki page and sidebar for the r/NUFC subreddit"""
import datetime
from asyncio import sleep
from math import ceil
from pathlib import Path
from re import sub, DOTALL
from typing import Optional, TYPE_CHECKING

from PIL import Image
from asyncpraw.models import Subreddit
from discord import Attachment, Embed, File, Interaction
from discord.app_commands import command, describe, guilds
from discord.app_commands.checks import has_role
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from lxml import html

from ext.utils.football import Team

if TYPE_CHECKING:
    from core import Bot

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

    height = ceil(len(rows) / (len(rows) // per + 1))
    chunks = [''.join(rows[i:i + height]) for i in range(0, len(rows), height)]
    chunks.reverse()
    markdown = header + header.join(chunks)

    return markdown


class NUFCSidebar(Cog):
    """Edit the r/NUFC sidebar"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot = bot
        self.bot.sidebar = self.sidebar_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the sidebar task when Cog is unloaded."""
        self.bot.sidebar.cancel()

    @loop(hours=6)
    async def sidebar_loop(self) -> None:
        """Background task, repeat every 6 hours to update the sidebar"""
        try:
            self.bot.teams['p6ahwuwJ']
        except KeyError:
            await sleep(60)
            return await self.sidebar_loop()

        markdown = await self.make_sidebar()
        _ = await self.bot.reddit.subreddit('NUFC')
        _ = await _.wiki.get_page("config/sidebar")
        await _.edit(content=markdown)

    @sidebar_loop.before_loop
    async def fetch_team_data(self) -> None:
        """Grab information about teams from local database."""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            self.bot.reddit_teams = await connection.fetch("""SELECT * FROM team_data""")
        await self.bot.db.release(connection)

        # Session / Browser will not be initialised
        await self.bot.wait_until_ready()

    async def make_sidebar(self, subreddit: str = "NUFC", qry: str = "newcastle", team_id: str = "p6ahwuwJ"):
        """Build the sidebar markdown"""
        # Fetch all data
        srd = await self.bot.reddit.subreddit(subreddit)
        wiki = await srd.wiki.get_page('sidebar')

        top = wiki.content_md

        fsr: Team = self.bot.teams[team_id]

        page = await self.bot.browser.newPage()
        try:
            fixtures = await fsr.get_fixtures(page, "/fixtures")
            results = await fsr.get_fixtures(page, "/results")
        finally:
            await page.close()

        async with self.bot.session.get('http://www.bbc.co.uk/sport/football/premier-league/table') as resp:
            match resp.status:
                case 200:
                    pass
                case _:
                    return
            tree = html.fromstring(await resp.text())

        table = f"\n\n* Table\n\n Pos.|Team|P|W|D|L|GD|Pts\n--:|:--{'|:--:' * 6}\n"
        for i in tree.xpath('.//table[contains(@class,"gs-o-table")]//tbody/tr')[:20]:
            p = i.xpath('.//td//text()')
            rank = p[0].strip()  # Ranking
            movement = p[1].strip()

            match movement:
                case "team hasn't moved":
                    table += f'{rank} | '
                case 'team has moved up':
                    table += f'🔺 {rank} | '
                case 'team has moved down':
                    table += f'🔻 {rank} | '
                case _:
                    print("Invalid movement for team detected", movement)
                    table += f"? {rank}"
            team = p[2].strip()
            try:
                # Insert subreddit link from db
                team = [i for i in self.bot.reddit_teams if i['name'] == team][0]
                if team:
                    team = f"[{team['name']}]({team['subreddit']})"
                else:
                    print("Sidebar, error, team is ", team)
            except IndexError:
                print(team, "Not found in", [i['name'] for i in self.bot.reddit_teams])
            cols = [team] + p[3:7] + p[9:11]  # [t] [p, w, d, l] [gd, pts]
            table += " | ".join([f"**{col}**" if qry.lower() in team.lower() else col for col in cols]) + "\n"

        # Get match threads
        last_opponent = qry.split(" ")[0]
        nufc_sub = await self.bot.reddit.subreddit("NUFC")
        async for i in nufc_sub.search('flair:"Pre-match thread"', sort="new", syntax="lucene"):
            if last_opponent in i.title:
                pre = f"[Pre]({i.url.split('?ref=')[0]})"
                break
        else:
            pre = "Pre"
        async for i in nufc_sub.search('flair:"Match thread"', sort="new", syntax="lucene"):
            if not i.title.startswith("Match"):
                continue
            if last_opponent in i.title:
                match = f"[Match]({i.url.split('?ref=')[0]})"
                break
        else:
            match = "Match"

        async for i in nufc_sub.search('flair:"Post-match thread"', sort="new", syntax="lucene"):
            if last_opponent in i.title:
                post = f"[Post]({i.url.split('?ref=')[0]})"
                break
        else:
            post = "Post"

        match_threads = f"\n\n### {pre} - {match} - {post}"

        # Check if we need to upload a temporary badge.
        top_bar = ""
        count = 0
        if fixtures:
            rows = []
            for f in fixtures:
                home = next((i for i in self.bot.reddit_teams if i['name'] == f.home.name), None)
                away = next((i for i in self.bot.reddit_teams if i['name'] == f.away.name), None)
                short_home = home['short_name'] if home is not None else f.home.name
                short_away = away['short_name'] if away is not None else f.away.name
                home_sub = home['subreddit'] if home is not None else "#temp"
                away_sub = away['subreddit'] if away is not None else "#temp/"  # '/' Denotes away ::after img

                if count == 0:
                    h = f"[{f.home.name}]({home_sub})"
                    a = f"[{f.away.name}]({away_sub})"
                    top_bar = f"> {h} [{f.score}]({f.url}) {a}"

                    home_icon = home['icon'] if home is not None else ""
                    away_icon = away['icon'] if away is not None else ""

                    # Upload badge.
                    if not home_icon or not away_icon:
                        badge: str = await f.get_badge('home') if not home_icon else await f.get_badge('away')
                        if badge:
                            im = Image.open(badge)
                            im.save("TEMP_BADGE.png", "PNG")
                            s = await self.bot.reddit.subreddit("NUFC")
                            await s.stylesheet.upload("TEMP_BADGE.png", "temp")
                            await s.stylesheet.update(s.stylesheet().stylesheet, reason="Upload a badge")
                            print("Uploaded new image to sidebar!")

                count += 1

                rows.append(f"{f.kickoff} | [{short_home} {f.score} {short_away}]({f.url})\n")
            fx_markdown = "\n* Upcoming fixtures" + rows_to_md_table("\n\n Date & Time | Match\n--:|:--\n", rows)
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
            rows = []
            for r in results:
                home = next((i for i in self.bot.reddit_teams if i['name'] == r.home.name), None)
                away = next((i for i in self.bot.reddit_teams if i['name'] == r.away.name), None)
                short_home = home['short_name'] if home is not None else r.home.name
                short_away = away['short_name'] if away is not None else r.away.name
                # home_sub = home['subreddit'] if home is not None else "#temp"
                # away_sub = away['subreddit'] if away is not None else "#temp/" # '/' Denotes away ::after img
                rows.append(f"{r.kickoff} | [{short_home} {r.score} {short_away}]({r.url})\n")
            md = rows_to_md_table("\n Date | Result\n--:|:--\n", rows, max_length=10240 - len(markdown + footer))
            markdown += md

        markdown += footer
        return markdown

    @command()
    @describe(image="Upload a new sidebar image", caption="Set a new Sidebar Caption")
    @guilds(332159889587699712)
    @has_role(332161994738368523)
    async def sidebar(self, interaction: Interaction,
                      caption: Optional[str] = None,
                      image: Optional[Attachment] = None):
        """Upload an image to the sidebar, or edit the caption."""

        if "Subreddit Moderators" not in [i.name for i in interaction.user.roles]:
            return await self.bot.error(interaction, "You need the 'Subreddit Moderators' role to do that")

        await interaction.response.defer()
        # Check if message has an attachment, for the new sidebar image.
        e: Embed = Embed(color=0xff4500, url="http://www.reddit.com/r/NUFC")
        th = "http://vignette2.wikia.nocookie.net/valkyriecrusade/images/b/b5/Reddit-The-Official-App-Icon.png"
        e.set_author(icon_url=th, name="r/NUFC Sidebar updated")
        file = None

        if caption:
            _ = await self.bot.reddit.subreddit('NUFC')
            _ = await _.wiki.get_page('sidebar')
            markdown = sub(r'---.*?---', f"---\n\n> {caption}\n\n---", _.content_md, flags=DOTALL)
            await _.edit(content=markdown)
            e.description = f"Set caption to: {caption}"

        if image:
            await image.save(Path('sidebar'))
            s: Subreddit = await self.bot.reddit.subreddit("NUFC")
            await s.stylesheet.upload("sidebar", 'sidebar')
            style = await s.stylesheet()
            await s.stylesheet.update(style.stylesheet, reason=f"Sidebar image by {interaction.user} via discord")

            e.set_image(url=image.url)
            file = File(fp="sidebar.png", filename="sidebar.png")

        # Build
        subreddit = await self.bot.reddit.subreddit('NUFC')
        wiki = await subreddit.wiki.get_page("config/sidebar")
        await wiki.edit(content=await self.make_sidebar())
        await self.bot.reply(interaction, embed=e, file=file)


async def setup(bot):
    """Load the Sidebar Updater Cog into the bot"""
    await bot.add_cog(NUFCSidebar(bot))
