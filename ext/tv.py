"""Fetch the televised matches from livesoccertv.com"""
from __future__ import annotations

import logging
from datetime import datetime
from json import load
from typing import TYPE_CHECKING, Any, Optional

import discord
from discord import Embed, Interaction, Message
from discord.ext import commands
from lxml import html

from ext.utils import view_utils
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot

# aiohttp useragent.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4)"
    " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 "
    " Safari/537.36"
}

logger = logging.getLogger("tv")

LST = "http://www.livesoccertv.com/"

# TODO: Team / League Split
# TODO: Initial Passover of fixture upon view creation
# to get all available buttons in the style of Fixtures rewrite.
# TODO: Make functions for all buttons.

# TODO: New Version of Select View


class TVSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    bot: Bot

    def __init__(self, interaction: Interaction[Bot], teams: list):
        super().__init__(interaction)

        self.teams: list = teams

        # Pagination
        self.index: int = 0
        self.pages: list[list] = [
            self.teams[i : i + 25] for i in range(0, len(self.teams), 25)
        ]

        # Final result
        self.value: Any = None  # As Yet Unset

    async def update(self):
        """Handle Pagination"""
        targets: list = self.pages[self.index]
        d = view_utils.ItemSelect(placeholder="Please choose a Team")
        e = Embed(title="Choose a Team", description="")

        e.description = ""

        for team in targets:
            d.add_option(emoji="📺", label=team, value=self.bot.tv_dict[team])
            e.description += f"{team}\n"
        self.add_item(d)
        self.add_page_buttons(1)

        edit = self.interaction.edit_original_response
        return await edit(embed=e, view=self)


async def tv_ac(
    interaction: discord.Interaction[Bot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Return list of live teams"""
    cr = current.casefold()

    choices = []
    for x in interaction.client.tv_dict.keys():
        if cr not in x.casefold():
            continue
        choices.append(discord.app_commands.Choice(name=x[:100], value=x))

    return choices[:25]


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        with open("tv.json") as f:
            self.bot.tv_dict = load(f)

    @discord.app_commands.command()
    @discord.app_commands.describe(team="Search for a team")
    @discord.app_commands.autocomplete(team=tv_ac)
    async def tv(
        self, interaction: Interaction[Bot], team: Optional[str]
    ) -> Message:
        """Lookup next televised games for a team"""

        await interaction.response.defer(thinking=True)

        e: Embed = Embed(colour=0x034F76)
        e.set_author(name="LiveSoccerTV.com")

        # Selection View if team is passed
        if team:
            if team in self.bot.tv_dict:
                e.url = self.bot.tv_dict[team]
                e.title = f"Televised Fixtures for {team}"

            else:
                dct = self.bot.tv_dict

                tm = team.casefold()
                matches = [i for i in dct if tm in i.casefold()]

                if not matches:
                    err = f"Could not find a matching team for {team}."
                    return await self.bot.error(interaction, err)

                await (view := TVSelect(interaction, matches)).update()
                await view.wait()
                e.url = self.bot.tv_dict[view.value[0]]
                e.title = f"Televised Fixtures for {view.value[0]}"
        else:
            e.url = LST + "schedules/"
            e.title = "Today's Televised Matches"

        async with self.bot.session.get(e.url, headers=HEADERS) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    err = f"{e.url} returned a HTTP {resp.status} error."
                    return await self.bot.error(interaction, err)

        # match_column = 3 if not team else 5
        match_column = 3
        rows = []
        for i in tree.xpath(".//table[@class='schedules'][1]//tr"):
            # Discard finished games.
            xp = './/td[@class="livecell"]//span/@class'
            if "".join(i.xpath(xp)).strip() in ["narrow ft", "narrow repeat"]:
                continue

            xp = f".//td[{match_column}]//text()"
            if not (match := "".join(i.xpath(xp)).strip()):
                continue

            xp = f".//td[{match_column + 1}]//a/@href"
            try:
                link = LST + f"{i.xpath(xp)[-1]}"
            except IndexError:
                link = ""

            try:
                timestamp = int(i.xpath(".//@dv")[0])
                timestamp = datetime.fromtimestamp(timestamp / 1000)
                if match_column == 3:
                    ts = Timestamp(timestamp).date
                else:
                    ts = Timestamp(timestamp).time_hour

            except (ValueError, IndexError):
                xp = './/td[@class="datecell"]//span/text()'
                date = "".join(i.xpath(xp)).strip()

                xp = './/td[@class="timecell"]//span/text()'
                time = "".join(i.xpath(xp)).strip()
                if time not in ["Postp.", "TBA"]:
                    txt = "invalid timestamp.\nDate [%s] Time [%s]"
                    logger.warning(txt, date, time)
                ts = time

            rows.append(f"{ts}: [{match}]({link})")

        if not rows:
            rows = [f"No televised matches found, check online at {e.url}"]

        v = view_utils.Paginator(interaction, rows_to_embeds(e, rows))
        return await v.update()


async def setup(bot: Bot) -> None:
    """Load TV Lookup Module into the bot."""
    await bot.add_cog(Tv(bot))
