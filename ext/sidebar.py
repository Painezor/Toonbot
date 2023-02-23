"""Background loop to update the wiki page and sidebar for
   the r/NUFC subreddit"""
from __future__ import annotations

import logging
from asyncio import sleep
from datetime import datetime
from math import ceil
from pathlib import Path
from re import sub, DOTALL
from typing import TYPE_CHECKING

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
    from ext.toonbot_utils.flashscore import Fixture, Team
NUFC_DISCORD_LINK = "nufc"  # TuuJgrA

REDDIT_THUMBNAIL = (
    "http://vignette2.wikia.nocookie.net/valkyriecrusade/"
    "images/b/b5/Reddit-The-Official-App-Icon.png"
)


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
    chunks = [
        "".join(rows[i : i + height]) for i in range(0, len(rows), height)
    ]
    chunks.reverse()
    markdown = header + header.join(chunks)

    return markdown


class NUFCSidebar(Cog):
    """Edit the r/NUFC sidebar"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.bot.sidebar = self.sidebar_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the sidebar task when Cog is unloaded."""
        self.bot.sidebar.cancel()

    @loop(hours=6)
    async def sidebar_loop(self) -> None:
        """Background task, repeat every 6 hours to update the sidebar"""
        if not self.bot.get_team("p6ahwuwJ"):
            await sleep(60)
            return await self.sidebar_loop()

        markdown = await self.make_sidebar()
        subreddit = await self.bot.reddit.subreddit("NUFC")
        page = await subreddit.wiki.get_page("config/sidebar")
        await page.edit(content=markdown)

        logging.info(f"{datetime.now()} The sidebar of r/NUFC was updated.")

    @sidebar_loop.before_loop
    async def fetch_team_data(self) -> None:
        """Grab information about teams from local database."""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                self.bot.reddit_teams = await connection.fetch(
                    """SELECT * FROM team_data"""
                )

    async def make_sidebar(
        self,
        subreddit: str = "NUFC",
        qry: str = "newcastle",
        team_id: str = "p6ahwuwJ",
    ):
        """Build the sidebar markdown"""
        # Fetch all data
        srd = await self.bot.reddit.subreddit(subreddit)
        wiki = await srd.wiki.get_page("sidebar")

        wiki_content = wiki.content_md

        fsr: Team = self.bot.get_team(team_id)

        fixtures: list[Fixture] = await fsr.fixtures()
        results: list[Fixture] = await fsr.results()

        url = "http://www.bbc.co.uk/sport/football/premier-league/table"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    return

        pad = "|:--:" * 6
        table = f"\n\n* Table\n\n Pos.|Team|P|W|D|L|GD|Pts\n--:|:--{pad}\n"

        xp = './/table[contains(@class,"gs-o-table")]//tbody/tr'
        for i in tree.xpath(xp)[:20]:
            p = i.xpath(".//td//text()")
            rank = p[0].strip()  # Ranking
            movement = p[1].strip()

            match movement:
                case "team hasn't moved":
                    table += f"{rank} | "
                case "team has moved up":
                    table += f"🔺 {rank} | "
                case "team has moved down":
                    table += f"🔻 {rank} | "
                case _:
                    logging.error("Bad movement team %s", movement)
                    table += "rank | "
            team = p[2].strip()
            # Insert subreddit link from db

            try:
                team = next(i for i in self.bot.teams if i["name"] == team)
                team = f"{team['name']}]({team['subreddit']}"
            except StopIteration:
                pass
            cols = [team] + p[3:7] + p[9:11]  # [t] [p, w, d, l] [gd, pts]

            q = qry.lower()
            t = team.lower()
            table += " | ".join([f"**{i}**" if q in t else i for i in cols])
            table += "\n"

        # Get match threads
        last_opponent = qry.split(" ")[0]
        nufc_sub = await self.bot.reddit.subreddit("NUFC")
        async for i in nufc_sub.search(
            'flair:"Pre-match thread"', sort="new", syntax="lucene"
        ):
            if last_opponent in i.title:
                pre = f"[Pre]({i.url.split('?ref=')[0]})"
                break
        else:
            pre = "Pre"
        async for i in nufc_sub.search(
            'flair:"Match thread"', sort="new", syntax="lucene"
        ):
            if not i.title.startswith("Match"):
                continue
            if last_opponent in i.title:
                match = f"[Match]({i.url.split('?ref=')[0]})"
                break
        else:
            match = "Match"

        async for i in nufc_sub.search(
            'flair:"Post-match thread"', sort="new", syntax="lucene"
        ):
            if last_opponent in i.title:
                post = f"[Post]({i.url.split('?ref=')[0]})"
                break
        else:
            post = "Post"

        # Top bar
        match_threads = f"\n\n### {pre} - {match} - {post}"
        fixture = next(i for i in results + fixtures)
        home = next(
            (
                i
                for i in self.bot.reddit_teams
                if i["name"] == fixture.home.name
            ),
            None,
        )
        away = next(
            (
                i
                for i in self.bot.reddit_teams
                if i["name"] == fixture.away.name
            ),
            None,
        )

        home_sub = home["subreddit"] if home is not None else ""
        away_sub = away["subreddit"] if away is not None else ""

        h = f"[{fixture.home.name}]({home_sub})"
        a = f"[{fixture.away.name}]({away_sub})"
        top_bar = f"> {h} [{fixture.score}]({fixture.url}) {a}"

        home_icon = "#temp" if home is None else home["icon"]
        away_icon = (
            "#temp/" if away is None else away["icon"]
        )  # / Denotes post.

        # Check if we need to upload a temporary badge.
        # Upload badge.
        if not home_icon or not away_icon:
            attr = "home" if not home_icon else "away"
            if (team_ := getattr(fixture, attr)).logo_url is not None:
                return team_.logo_url

            # Else pull up the page and grab it manually.
            page = await self.bot.browser.new_page()
            try:
                await page.goto(fixture.link, timeout=5000)
                await page.wait_for_selector(
                    f'.//div[contains(@class, "tlogo-{attr}")]//img',
                    timeout=5000,
                )
                tree = html.fromstring(await page.content())
            finally:
                await page.close()

            if badges := tree.xpath(
                f'.//div[contains(@class, "tlogo-{attr}")]//img/@src'
            ):
                im = Image.open(badges[0])
                im.save("TEMP_BADGE.png", "PNG")
                s = await self.bot.reddit.subreddit("NUFC")
                await s.stylesheet.upload("TEMP_BADGE.png", "temp")
                await s.stylesheet.update(
                    s.stylesheet().stylesheet, reason="Upload a badge"
                )

        pool = self.bot.reddit_teams
        if fixtures:
            rows = []

            for f in fixtures:
                h = f.home.name

                try:
                    home = next(i for i in pool if i["name"] == h)
                    h_ico = home["icon"]
                    h = home["short_name"]
                except StopIteration:
                    h_ico = ""

                a = f.away.name
                try:
                    away = next(i for i in pool if i["name"] == a)
                    a_ico = away["icon"]
                    a = away["short_name"]
                except StopIteration:
                    a_ico = ""

                ko = f.kickoff
                sc = f.score
                rows.append(
                    f"{ko} | {h_ico} [{h} {sc} {a}]({f.url}) {a_ico}\n"
                )
            fx_markdown = "\n* Upcoming fixtures" + rows_to_md_table(
                "\n\n Date & Time | Match\n--:|:--\n", rows
            )
        else:
            fx_markdown = ""

        # After fetching everything, begin construction.
        timestamp = f"\n#####Sidebar updated {datetime.now().ctime()}\n"
        footer = timestamp + top_bar + match_threads

        if subreddit == "NUFC":
            footer += "\n\n[](https://discord.gg/" + NUFC_DISCORD_LINK + ")"

        markdown = wiki_content + table + fx_markdown

        if results:
            header = "* Previous Results\n"
            markdown += header
            rows = []
            for r in results:
                h = r.home.name

                try:
                    home = next(i for i in pool if i["name"] == h)
                    h_ico = home["icon"]
                    h = home["short_name"]
                except StopIteration:
                    h_ico = "#temp"

                a = f.away.name
                try:
                    away = next(i for i in pool if i["name"] == a)
                    a_ico = away["icon"]
                    a = away["short_name"]
                except StopIteration:
                    # '/' Denotes away ::after img
                    a_ico = "#temp/"

                s = r.score
                ko = r.kickoff
                rows.append(f"{ko} | {h_ico} [{h} {s} {a}]({r.url}) {a_ico}\n")

            hdr = "\n Date | Result\n--:|:--\n"
            pad = 10240 - len(markdown + footer)
            markdown += rows_to_md_table(hdr, rows, 20, pad)
        markdown += footer
        return markdown

    @command()
    @guilds(332159889587699712)
    @default_permissions(manage_channels=True)
    @describe(
        image="Upload a new sidebar image", caption="Set a new Sidebar Caption"
    )
    async def sidebar(
        self,
        interaction: Interaction,
        caption: str = None,
        image: Attachment = None,
    ) -> Message:
        """Upload an image to the sidebar, or edit the caption."""

        await interaction.response.defer(thinking=True)
        # Check if message has an attachment, for the new sidebar image.
        e: Embed = Embed(color=0xFF4500, url="http://www.reddit.com/r/NUFC")
        e.set_author(icon_url=REDDIT_THUMBNAIL, name="r/NUFC Sidebar updated")

        if caption:
            page = await (
                await self.bot.reddit.subreddit("NUFC")
            ).wiki.get_page("sidebar")
            await page.edit(
                content=sub(
                    r"---.*?---",
                    f"---\n\n> {caption}\n\n---",
                    page.content_md,
                    flags=DOTALL,
                )
            )
            e.description = f"Set caption to: {caption}"

        if image:
            await image.save(Path("sidebar"))
            s: Subreddit = await self.bot.reddit.subreddit("NUFC")
            try:
                await s.stylesheet.upload("sidebar", "sidebar")
            except TooLarge:
                return await self.bot.error(
                    interaction, content="Image is too large."
                )
            style = await s.stylesheet()
            await s.stylesheet.update(
                style.stylesheet,
                reason=f"Sidebar image by {interaction.user} via discord",
            )

            e.set_image(url=image.url)
            file = await image.to_file()
        else:
            file = None

        # Build
        wiki = await (await self.bot.reddit.subreddit("NUFC")).wiki.get_page(
            "config/sidebar"
        )
        await wiki.edit(content=await self.make_sidebar())
        await self.bot.reply(interaction, embed=e, file=file)


async def setup(bot: Bot) -> None:
    """Load the Sidebar Updater Cog into the bot"""
    await bot.add_cog(NUFCSidebar(bot))
