"""Background loop to update the wiki page and sidebar for
   the r/NUFC subreddit"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import pathlib
import re
from typing import TYPE_CHECKING, Any

from asyncpraw import Reddit  # type: ignore
from asyncprawcore import TooLarge
import discord
from discord.ext import commands, tasks
from lxml import html
from PIL import Image

import ext.flashscore as fs

if TYPE_CHECKING:
    from core import Bot
    from asyncpg import Record


NUFC_DISCORD_LINK = "newcastleutd"  # TuuJgrA

REDDIT = "http://www.reddit.com/r/NUFC"
REDDIT_THUMBNAIL = (
    "http://vignette2.wikia.nocookie.net/valkyriecrusade/"
    "images/b/b5/Reddit-The-Official-App-Icon.png"
)

logger = logging.getLogger("sidebar")


with open("credentials.json", mode="r", encoding="utf-8") as fun:
    _credentials = json.load(fun)


# TODO: Ask Asyncpraw guy to make his shit unfucked.


def rows_to_md_table(
    header: str, strings: list[str], per: int = 20, max_length: int = 10240
):
    """Create sidebar pop out tables"""
    rows: list[str] = []
    for num, obj in enumerate(strings):
        # Every row we buffer the length of the new result.
        max_length -= len(obj)

        # Every 20 rows we buffer the length of another header.
        if num % 20 == 0:
            max_length -= len(header)
        if max_length < 0:
            break
        rows.append(obj)

    if not rows:
        return ""

    height = math.ceil(len(rows) / (len(rows) // per + 1))
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

        self.reddit_teams: list[Record] = []

        self.reddit = Reddit(**_credentials["Reddit"])
        self.task: asyncio.Task[None] = self.sidebar_task.start()

    async def cog_load(self) -> None:
        sql = """SELECT * FROM team_data"""
        self.reddit_teams = await self.bot.db.fetch(sql)

    async def cog_unload(self) -> None:
        """Cancel the sidebar task when Cog is unloaded."""
        self.task.cancel()

    @tasks.loop(hours=6)
    async def sidebar_task(self) -> None:
        """Background task, repeat every 6 hours to update the sidebar"""
        if not self.bot.browser or not self.bot.cache.teams:
            await asyncio.sleep(60)
            self.sidebar_task.change_interval(seconds=60)
            return
        self.sidebar_task.change_interval(hours=6)

        markdown = await self.make_sidebar()
        subreddit = await self.reddit.subreddit("NUFC")  # type: ignore
        page = await subreddit.wiki.get_page("config/sidebar")  # type: ignore
        await page.edit(content=markdown)  # type: ignore

        time = datetime.datetime.now()
        logger.info("%s The sidebar of r/NUFC was updated.", time)

    def get_team(self, name: str | None) -> tuple[str, str]:
        if name is None:
            return "", "?"

        try:
            team = next(i for i in self.reddit_teams if i["name"] == name)
            icon = team["icon"]
            short = team["short_name"]
        except StopIteration:
            icon = ""
            short = name
        return icon, short

    def parse_fixtures(self, fixtures: list[fs.abc.BaseFixture]) -> list[str]:
        rows: list[str] = []
        for fix in fixtures:
            h_sh, h_ico = self.get_team(fix.home.team.name)
            a_sh, a_ico = self.get_team(fix.away.team.name)

            if fix.kickoff:
                k_o = fix.kickoff.strftime("%d/%m/%Y %H:%M")
            else:
                k_o = ""

            sco = fix.score
            sco = f"{k_o} | {h_ico} [{h_sh} {sco} {a_sh}]({fix.url}) {a_ico}\n"
            rows.append(sco)
        return rows

    async def make_sidebar(
        self,
        subreddit: str = "NUFC",
        qry: str = "newcastle",
        team_id: str = "p6ahwuwJ",
    ) -> str:
        """Build the sidebar markdown"""
        # Fetch all data
        srd: Any = await self.reddit.subreddit(subreddit)
        wiki: Any = await srd.wiki.get_page("sidebar")

        wiki_content = wiki.content_md

        fsr = self.bot.cache.get_team(team_id)
        if fsr is None:
            raise ValueError(f"Team with ID {team_id} not found in db")
        fsr = fs.Team.parse_obj(fsr)

        page = await self.bot.browser.new_page()
        try:
            fixtures = await fsr.fixtures(page, self.bot.cache)
            results = await fsr.results(page, self.bot.cache)
        finally:
            await page.close()

        url = "http://www.bbc.co.uk/sport/football/premier-league/table"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                raise ConnectionError()
            tree = html.fromstring(await resp.text())

        pad = "|:--:" * 6
        table = f"\n\n* Table\n\n Pos.|Team|P|W|D|L|GD|Pts\n--:|:--{pad}\n"

        xpath = ".//tbody/tr"

        name = qry.casefold()
        for i in tree.xpath(xpath):
            items = i.xpath(".//td//text()")

            team = items[1].strip()
            # Insert subreddit link from db

            try:
                team = next(i for i in self.reddit_teams if i["name"] == team)
                team = f"[{team['name']}]({team['subreddit']})"
            except StopIteration:
                pass

            # [rank] [t] [p, w, d, l] [gd, pts]
            cols = [items[0], team] + items[2:6] + items[8:10]
            tem = team.casefold()
            rows: list[str] = [f"**{i}**" if name in tem else i for i in cols]
            table += " | ".join(rows) + "\n"

        # Get match threads
        last_opponent = qry.split(" ")[0]

        nufc_sub: Any = await self.reddit.subreddit("NUFC")

        pre = "Pre"
        match = "Match"
        post = "Post"

        src = last_opponent
        async for i in nufc_sub.search(src, sort="new", time_filter="month"):
            if i.title.strip("[").startswith("Pre"):
                if last_opponent in i.title:
                    pre = f"[Pre]({i.url.split('?ref=')[0]})"
                    logger.info("Got prematch %s", i.title)

            if i.title.strip("[").startswith("Match"):
                if last_opponent in i.title:
                    match = f"[Match]({i.url.split('?ref=')[0]})"
                    logger.info("Got match %s", i.title)

            if i.title.strip("[").startswith("[Post"):
                if last_opponent in i.title:
                    post = f"[Post]({i.url.split('?ref=')[0]})"
                    logger.info("Got postmatch %s", i.title)
        # Top bar
        match_threads = f"\n\n### {pre} - {match} - {post}"
        fixture = next(i for i in results + fixtures)
        home = next(
            (
                i
                for i in self.reddit_teams
                if i["name"] == fixture.home.team.name
            ),
            None,
        )
        away = next(
            (
                i
                for i in self.reddit_teams
                if i["name"] == fixture.away.team.name
            ),
            None,
        )

        home_sub = home["subreddit"] if home is not None else ""
        away_sub = away["subreddit"] if away is not None else ""

        h_sh = f"[{fixture.home.team.name}]({home_sub})"
        a_sh = f"[{fixture.away.team.name}]({away_sub})"
        top_bar = f"> {h_sh} [{fixture.score}]({fixture.url}) {a_sh}"

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
                image = Image.open(badges[0])
                image.save("TEMP_BADGE.png", "PNG")
                sco: Any = await self.reddit.subreddit("NUFC")
                await sco.stylesheet.upload("TEMP_BADGE.png", "temp")
                await sco.stylesheet.update(
                    sco.stylesheet().stylesheet, reason="Upload a badge"
                )
                image.close()

        rows = self.parse_fixtures(fixtures)
        hdr = "\n\n Date & Time | Match\n--:|:--\n"
        fx_markdown = "\n* Upcoming fixtures" + rows_to_md_table(hdr, rows)

        # After fetching everything, begin construction.
        now = datetime.datetime.now().ctime()
        timestamp = f"\n#####Sidebar updated {now}\n"
        footer = timestamp + top_bar + match_threads

        if subreddit == "NUFC":
            footer += "\n\n[](https://discord.gg/" + NUFC_DISCORD_LINK + ")"

        markdown: str = wiki_content + table + fx_markdown

        results = self.parse_fixtures(results)
        if results:
            header = "* Previous Results\n"
            markdown += header

            hdr = "\n Date | Result\n--:|:--\n"
            used: int = 10240 - len(markdown + footer)
            markdown += rows_to_md_table(hdr, results, 20, used)
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
        interaction: discord.Interaction[Bot],
        caption: str | None,
        image: discord.Attachment | None,
    ) -> None:
        """Upload an image to the sidebar, or edit the caption."""
        await interaction.response.defer(thinking=True)

        reply = interaction.edit_original_response
        if not caption and not image:
            embed = discord.Embed()
            embed.description = "🚫 Provide a caption or image"
            await reply(embed=embed)
            return

        # Check if message has an attachment, for the new sidebar image.
        embed = discord.Embed(color=0xFF4500, url=REDDIT)
        embed.set_author(icon_url=REDDIT_THUMBNAIL, name="Sidebar updated")

        subreddit: Any = await self.reddit.subreddit("NUFC")
        if caption:
            page = await subreddit.wiki.get_page("sidebar")

            new_txt = f"---\n\n> {caption}\n\n---"
            content = page.content_md
            txt = re.sub(r"---.*?---", new_txt, content, flags=re.DOTALL)

            await page.edit(txt)
            embed.description = f"Set caption to: {caption}"

        if image:
            await image.save(pathlib.Path(image.filename))
            sub: Any = await self.reddit.subreddit("NUFC")
            try:
                await sub.stylesheet.upload("sidebar", "sidebar")
            except TooLarge:
                embed = discord.Embed()
                embed.description = "🚫 Image file size too large"
                await reply(embed=embed)
                return

            style = await sub.stylesheet()

            stylesheet = style.stylesheet
            reason = f"Sidebar image by {interaction.user} via discord"
            await sub.stylesheet.update(stylesheet, reason=reason)

            embed.set_image(url=image.url)
            file = [await image.to_file()]
        else:
            file = []

        # Build
        wiki = await subreddit.wiki.get_page("config/sidebar")
        await wiki.edit(content=await self.make_sidebar())
        await interaction.edit_original_response(embed=embed, attachments=file)


async def setup(bot: Bot) -> None:
    """Load the Sidebar Updater Cog into the bot"""
    await bot.add_cog(NUFCSidebar(bot))
