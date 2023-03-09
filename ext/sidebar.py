"""Background loop to update the wiki page and sidebar for
   the r/NUFC subreddit"""
from __future__ import annotations

import logging
from asyncio import sleep
from datetime import datetime
from math import ceil
from pathlib import Path
from re import sub, DOTALL
from typing import TYPE_CHECKING, Optional

from PIL import Image
from asyncpraw.models import Subreddit
from asyncprawcore import TooLarge
from discord import Attachment, Embed, Message, Interaction

import discord
from discord.ext import commands, tasks
from lxml import html

import ext.toonbot_utils.flashscore as fs

if TYPE_CHECKING:
    from core import Bot


NUFC_DISCORD_LINK = "newcastleutd"  # TuuJgrA

REDDIT_THUMBNAIL = (
    "http://vignette2.wikia.nocookie.net/valkyriecrusade/"
    "images/b/b5/Reddit-The-Official-App-Icon.png"
)

logger = logging.getLogger("sidebar")


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


class NUFCSidebar(commands.Cog):
    """Edit the r/NUFC sidebar"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.bot.sidebar = self.sidebar_loop.start()

    async def cog_unload(self) -> None:
        """Cancel the sidebar task when Cog is unloaded."""
        self.bot.sidebar.cancel()

    @tasks.loop(hours=6)
    async def sidebar_loop(self) -> None:
        """Background task, repeat every 6 hours to update the sidebar"""
        if not self.bot.browser or not self.bot.teams:
            await sleep(60)
            return await self.sidebar_loop()

        markdown = await self.make_sidebar()
        subreddit = await self.bot.reddit.subreddit("NUFC")
        page = await subreddit.wiki.get_page("config/sidebar")
        await page.edit(content=markdown)

        logger.info(f"{datetime.now()} The sidebar of r/NUFC was updated.")

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

        fsr = self.bot.get_team(team_id)
        if fsr is None:
            raise ValueError(f"Team with ID {team_id} not found in db")

        fx = await fs.parse_games(self.bot, fsr, "/fixtures/")
        fixtures: list[fs.Fixture] = fx
        rx = await fs.parse_games(self.bot, fsr, "/results/")
        results: list[fs.Fixture] = rx

        url = "http://www.bbc.co.uk/sport/football/premier-league/table"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                raise ConnectionError()
            tree = html.fromstring(await resp.text())

        sql = """SELECT * FROM team_data"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rt = await connection.fetch(sql)

        pad = "|:--:" * 6
        table = f"\n\n* Table\n\n Pos.|Team|P|W|D|L|GD|Pts\n--:|:--{pad}\n"

        xp = ".//tbody/tr"
        for i in tree.xpath(xp):
            p = i.xpath(".//td//text()")

            team = p[1].strip()
            # Insert subreddit link from db

            try:
                team = next(i for i in rt if i["name"] == team)
                team = f"[{team['name']}]({team['subreddit']})"
            except StopIteration:
                pass

            # [rank] [t] [p, w, d, l] [gd, pts]
            cols = [p[0], team] + p[2:6] + p[8:10]

            q = qry.casefold()
            t = team.casefold()
            table += " | ".join([f"**{i}**" if q in t else i for i in cols])
            table += "\n"

        # Get match threads
        last_opponent = qry.split(" ")[0]
        nufc_sub = await self.bot.reddit.subreddit("NUFC")

        pre = "Pre"
        match = "Match"
        post = "Post"

        src = last_opponent
        async for i in nufc_sub.search(src, sort="new", time_filter="month"):
            logger.info("Sidebar: Searching for match threads %s", i)
            if i.title.startswith("Pre"):
                if last_opponent in i.title:
                    pre = f"[Pre]({i.url.split('?ref=')[0]})"

            if i.title.startswith("Match"):
                if last_opponent in i.title:
                    match = f"[Match]({i.url.split('?ref=')[0]})"

            if i.title.startswith("Post"):
                if last_opponent in i.title:
                    post = f"[Post]({i.url.split('?ref=')[0]})"
        # Top bar
        match_threads = f"\n\n### {pre} - {match} - {post}"
        fixture = next(i for i in results + fixtures)
        home = next(
            (i for i in rt if i["name"] == fixture.home.name),
            None,
        )
        away = next(
            (i for i in rt if i["name"] == fixture.away.name),
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
            if fixture.url is None:
                raise ValueError("Cannot fetch None Sidebar URL")

            page = await self.bot.browser.new_page()
            try:
                await page.goto(fixture.url, timeout=5000)
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

        pool = rt
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

                if f.kickoff:
                    ko = f.kickoff.strftime("%d/%m/%Y %H:%M")
                else:
                    ko = ""
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
                    h_ico = ""

                a = r.away.name
                try:
                    away = next(i for i in pool if i["name"] == a)
                    a_ico = away["icon"]
                    a = away["short_name"]
                except StopIteration:
                    # '/' Denotes away ::after img
                    a_ico = ""

                s = r.score
                if r.kickoff:
                    ko = r.kickoff.strftime("%d/%m/%Y %H:%M")
                else:
                    ko = "?"
                rows.append(f"{ko} | {h_ico} [{h} {s} {a}]({r.url}) {a_ico}\n")

            hdr = "\n Date | Result\n--:|:--\n"
            pad = 10240 - len(markdown + footer)
            markdown += rows_to_md_table(hdr, rows, 20, pad)
        markdown += footer
        return markdown

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    @discord.app_commands.default_permissions(manage_channels=True)
    @discord.app_commands.describe(
        image="Upload a new sidebar image", caption="Set a new Sidebar Caption"
    )
    async def sidebar(
        self,
        interaction: Interaction[Bot],
        caption: Optional[str],
        image: Optional[Attachment],
    ) -> Message:
        """Upload an image to the sidebar, or edit the caption."""
        if not caption and not image:
            return await self.bot.error(
                interaction, "No caption / image provided."
            )
        await interaction.response.defer(thinking=True)
        # Check if message has an attachment, for the new sidebar image.
        e: Embed = Embed(color=0xFF4500, url="http://www.reddit.com/r/NUFC")
        e.set_author(icon_url=REDDIT_THUMBNAIL, name="r/NUFC Sidebar updated")

        subreddit = await self.bot.reddit.subreddit("NUFC")
        if caption:

            page = await subreddit.wiki.get_page("sidebar")

            new_txt = f"---\n\n> {caption}\n\n---"
            txt = sub(r"---.*?---", new_txt, page.content_md, flags=DOTALL)

            await page.edit(txt)
            e.description = f"Set caption to: {caption}"

        if image:
            await image.save(Path("sidebar"))
            s: Subreddit = await self.bot.reddit.subreddit("NUFC")
            try:
                await s.stylesheet.upload("sidebar", "sidebar")
            except TooLarge:
                return await self.bot.error(interaction, "Image is too large.")

            style = await s.stylesheet()

            pg = style.stylesheet
            u = interaction.user
            await s.stylesheet.update(
                pg, reason=f"Sidebar image by {u} via discord"
            )

            e.set_image(url=image.url)
            file = [await image.to_file()]
        else:
            file = []

        # Build
        wiki = await subreddit.wiki.get_page("config/sidebar")
        await wiki.edit(content=await self.make_sidebar())
        edit = interaction.edit_original_response
        return await edit(embed=e, attachments=file)


async def setup(bot: Bot) -> None:
    """Load the Sidebar Updater Cog into the bot"""
    await bot.add_cog(NUFCSidebar(bot))
