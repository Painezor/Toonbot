"""Fetch the televised matches from livesoccertv.com"""
from __future__ import annotations

import logging
import json
import typing
import datetime

import discord
from discord.ext import commands
from lxml import html

from ext.utils import view_utils, embed_utils, timed_events

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]

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

    def __init__(self, teams: list):
        super().__init__()

        self.teams: list = teams

        # Pagination
        self.index: int = 0
        self.pages: list[list] = [
            self.teams[i : i + 25] for i in range(0, len(self.teams), 25)
        ]

        # Final result
        self.value: typing.Any = None  # As Yet Unset

    async def update(self, interaction: Interaction) -> None:
        """Handle Pagination"""
        targets: list = self.pages[self.index]
        sel = view_utils.ItemSelect(placeholder="Please choose a Team")
        embed = discord.Embed(title="Choose a Team")
        embed.description = ""

        for team in targets:
            value = self.bot.tv_dict[team]
            sel.add_option(emoji="📺", label=team, value=value)
            embed.description += f"{team}\n"
        self.add_item(sel)
        self.add_page_buttons(1)

        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self)


async def tv_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Return list of live teams"""
    cur = current.casefold()

    choices = []
    for key in interaction.client.tv_dict.keys():
        if cur not in key.casefold():
            continue
        choices.append(discord.app_commands.Choice(name=key[:100], value=key))

    return choices[:25]


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        with open("tv.json", encoding="utf-8") as data:
            self.bot.tv_dict = json.load(data)

    @discord.app_commands.command(name="tv")
    @discord.app_commands.describe(team="Search for a team")
    @discord.app_commands.autocomplete(team=tv_ac)
    async def tv_cmd(
        self, interaction: Interaction, team: typing.Optional[str]
    ) -> None:
        """Lookup next televised games for a team"""
        embed = discord.Embed(colour=0x034F76)
        embed.set_author(name="LiveSoccerTV.com")

        # Selection View if team is passed
        if team:
            if team in self.bot.tv_dict:
                embed.url = self.bot.tv_dict[team]
                embed.title = f"Televised Fixtures for {team}"

            else:
                dct = self.bot.tv_dict

                name = team.casefold()
                matches = [i for i in dct if name in i.casefold()]

                if not matches:
                    err = f"Could not find a matching team for {team}."
                    embed = discord.Embed()
                    embed.description = "🚫 " + err
                    reply = interaction.response.send_message
                    return await reply(embed=embed, ephemeral=True)

                await (view := TVSelect(matches)).update(interaction)
                await view.wait()
                embed.url = self.bot.tv_dict[view.value[0]]
                embed.title = f"Televised Fixtures for {view.value[0]}"
        else:
            embed.url = LST + "schedules/"
            embed.title = "Today's Televised Matches"

        async with self.bot.session.get(embed.url, headers=HEADERS) as resp:
            if resp.status != 200:
                logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
            tree = html.fromstring(await resp.text())

        # match_column = 3 if not team else 5
        match_column = 3
        rows = []
        for i in tree.xpath(".//table[@class='schedules'][1]//tr"):
            # Discard finished games.
            xpath = './/td[@class="livecell"]//span/@class'
            text = "".join(i.xpath(xpath)).strip()
            if text in ["narrow ft", "narrow repeat"]:
                continue

            xpath = f".//td[{match_column}]//text()"
            if not (match := "".join(i.xpath(xpath)).strip()):
                continue

            xpath = f".//td[{match_column + 1}]//a/@href"
            try:
                link = LST + f"{i.xpath(xpath)[-1]}"
            except IndexError:
                link = ""

            try:
                timestamp = int(i.xpath(".//@dv")[0])
                timestamp = datetime.datetime.fromtimestamp(timestamp / 1000)
                if match_column == 3:
                    t_s = timed_events.Timestamp(timestamp).date
                else:
                    t_s = timed_events.Timestamp(timestamp).time_hour

            except (ValueError, IndexError):
                xpath = './/td[@class="datecell"]//span/text()'
                date = "".join(i.xpath(xpath)).strip()

                xpath = './/td[@class="timecell"]//span/text()'
                time = "".join(i.xpath(xpath)).strip()
                if time not in ["Postp.", "TBA"]:
                    txt = "invalid timestamp.\nDate [%s] Time [%s]"
                    logger.warning(txt, date, time)
                t_s = time

            rows.append(f"{t_s}: [{match}]({link})")

        if not rows:
            rows = [f"No televised matches found, check online at {embed.url}"]

        embeds = embed_utils.rows_to_embeds(embed, rows)
        view = view_utils.Paginator(embeds)
        return await view.update(interaction)


async def setup(bot: Bot) -> None:
    """Load TV Lookup Module into the bot."""
    await bot.add_cog(Tv(bot))
