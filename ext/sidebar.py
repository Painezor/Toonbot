"""Background loop to update the wiki page and sidebar for the r/NUFC subreddit"""
import datetime
from asyncio import sleep
from math import ceil
from pathlib import Path
from re import sub, DOTALL
from typing import TYPE_CHECKING, List

from PIL import Image
from asyncpraw.models import Subreddit
from asyncprawcore import TooLarge
from discord import Attachment, Embed, Message, Interaction
from discord.app_commands import command, describe, guilds, default_permissions
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from lxml import html

if TYPE_CHECKING:
    from core import Bot
    from ext.utils.flashscore import Fixture, Team
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
        self.bot: Bot = bot
        self.bot.sidebar = self.sidebar_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the sidebar task when Cog is unloaded."""
        self.bot.sidebar.cancel()

    @loop(hours=6)
    async def sidebar_loop(self) -> None:
        """Background task, repeat every 6 hours to update the sidebar"""
        if not self.bot.get_team('p6ahwuwJ'):
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

    async def make_sidebar(self, subreddit: str = "NUFC", qry: str = "newcastle", team_id: str = "p6ahwuwJ"):
        """Build the sidebar markdown"""
        # Fetch all data
        srd = await self.bot.reddit.subreddit(subreddit)
        wiki = await srd.wiki.get_page('sidebar')

        wiki_content = wiki.content_md

        fsr: Team = self.bot.get_team(team_id)

        fixtures: List[Fixture] = await fsr.fixtures()
        results: List[Fixture] = await fsr.results()

        async with self.bot.session.get('http://www.bbc.co.uk/sport/football/premier-league/table') as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return

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

        # Top bar
        match_threads = f"\n\n### {pre} - {match} - {post}"
        target_game = next(i for i in results + fixtures)
        home = next((i for i in self.bot.reddit_teams if i['name'] == target_game.home.name), None)
        away = next((i for i in self.bot.reddit_teams if i['name'] == target_game.away.name), None)
        home_sub = home['subreddit']
        away_sub = away['subreddit']

        h = f"[{target_game.home.name}]({home_sub})"
        a = f"[{target_game.away.name}]({away_sub})"
        top_bar = f"> {h} [{target_game.score}]({target_game.url}) {a}"

        home_icon = "#temp" if h is None else home['icon']
        away_icon = "#temp/" if a is None else away['icon']  # / Denotes post.

        # Upload badge.
        if not home_icon or not away_icon:
            badge: str = await target_game.get_badge('home') if not home_icon else await target_game.get_badge('away')
            if badge:
                im = Image.open(badge)
                im.save("TEMP_BADGE.png", "PNG")
                s = await self.bot.reddit.subreddit("NUFC")
                await s.stylesheet.upload("TEMP_BADGE.png", "temp")
                await s.stylesheet.update(s.stylesheet().stylesheet, reason="Upload a badge")

        # Check if we need to upload a temporary badge.
        if fixtures:
            rows = []
            for f in fixtures:
                home = next((i for i in self.bot.reddit_teams if i['name'] == f.home.name), None)
                away = next((i for i in self.bot.reddit_teams if i['name'] == f.away.name), None)
                h_ico = home['icon'] if home is not None else ""
                a_ico = away['icon'] if away is not None else ""  # '/' Denotes away ::after img
                short_home = home['short_name'] if home is not None else f.home.name
                short_away = away['short_name'] if away is not None else f.away.name
                rows.append(f"{f.kickoff} | {h_ico} [{short_home} {f.score} {short_away}]({f.url}) {a_ico}\n")
            fx_markdown = "\n* Upcoming fixtures" + rows_to_md_table("\n\n Date & Time | Match\n--:|:--\n", rows)
        else:
            fx_markdown = ""

        # After fetching everything, begin construction.
        timestamp = f"\n#####Sidebar updated {datetime.datetime.now().ctime()}\n"
        footer = timestamp + top_bar + match_threads

        if subreddit == "NUFC":
            footer += "\n\n[](https://discord.gg/" + NUFC_DISCORD_LINK + ")"

        markdown = wiki_content + table + fx_markdown

        if results:
            header = "* Previous Results\n"
            markdown += header
            rows = []
            for r in results:
                home = next((i for i in self.bot.reddit_teams if i['name'] == r.home.name), None)
                away = next((i for i in self.bot.reddit_teams if i['name'] == r.away.name), None)
                short_home = home['short_name'] if home is not None else r.home.name
                short_away = away['short_name'] if away is not None else r.away.name
                h_ico = home['icon'] if home is not None else "#temp"
                a_ico = away['icon'] if away is not None else "#temp/"  # '/' Denotes away ::after img
                rows.append(f"{r.kickoff} | {h_ico} [{short_home} {r.score} {short_away}]({r.url}) {a_ico}\n")
            md = rows_to_md_table("\n Date | Result\n--:|:--\n", rows, max_length=10240 - len(markdown + footer))
            markdown += md

        markdown += footer
        return markdown

    @command()
    @guilds(332159889587699712)
    @default_permissions(manage_channels=True)
    @describe(image="Upload a new sidebar image", caption="Set a new Sidebar Caption")
    async def sidebar(self, interaction: Interaction, caption: str = None, image: Attachment = None) -> Message:
        """Upload an image to the sidebar, or edit the caption."""
        await interaction.response.defer(thinking=True)
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
            try:
                await s.stylesheet.upload("sidebar", 'sidebar')
            except TooLarge:
                return await self.bot.error(interaction, content="Image is too large.")
            style = await s.stylesheet()
            await s.stylesheet.update(style.stylesheet, reason=f"Sidebar image by {interaction.user} via discord")

            e.set_image(url=image.url)
            file = await image.to_file()

        # Build
        subreddit = await self.bot.reddit.subreddit('NUFC')
        wiki = await subreddit.wiki.get_page("config/sidebar")
        await wiki.edit(content=await self.make_sidebar())
        await self.bot.reply(interaction, embed=e, file=file)


async def setup(bot: 'Bot') -> None:
    """Load the Sidebar Updater Cog into the bot"""
    await bot.add_cog(NUFCSidebar(bot))
