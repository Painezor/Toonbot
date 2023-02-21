"""Fetch the televised matches from livesoccertv.com"""
from __future__ import annotations

import logging
from datetime import datetime
from json import load
from typing import TYPE_CHECKING, Any

from discord import Embed, Interaction, Message
from discord.app_commands import command, describe, autocomplete, Choice
from discord.ext import commands
from lxml import html

from ext.utils import view_utils
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot

# aiohttp useragent.
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/75.0.3770.100 Safari/537.36'}


# TODO: Team / League Split
# TODO: Initial Passover of fixture upon view creation to get all available buttons.
# TODO: Make functions for all buttons.

# TODO: New Version of Select View
class TVSelect(view_utils.BaseView):
    """View for asking user to select a specific fixture"""

    def __init__(self, interaction: Interaction, teams: list):
        super().__init__(interaction)

        self.interaction: Interaction = interaction
        self.teams: list = teams

        # Pagination
        self.index: int = 0
        self.pages: list[list] = [self.teams[i:i + 25] for i in range(0, len(self.teams), 25)]

        # Final result
        self.value: Any = None  # As Yet Unset

    async def update(self):
        """Handle Pagination"""
        targets: list = self.pages[self.index]
        d = view_utils.ItemSelect(placeholder="Please choose a Team")
        e = Embed(title='Choose a Team', description="")

        for team in targets:
            d.add_option(emoji='📺', label=team, value=self.bot.tv[team])
            e.description += f"{team}\n"
        self.add_item(d)
        view_utils.add_page_buttons(self, 1)
        return await self.interaction.client.reply(embed=e, view=self)


async def tv_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Return list of live teams"""
    return [Choice(name=x[:100], value=x) for x in interaction.client.tv.keys() if current.lower() in x.lower()][:25]


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        with open('tv.json') as f:
            self.bot.tv = load(f)

    @command()
    @describe(team="Search for a team")
    @autocomplete(team=tv_ac)
    async def tv(self, interaction: Interaction, team: str = None) -> Message:
        """Lookup next televised games for a team"""
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(thinking=True)

        e: Embed = Embed(colour=0x034f76)
        e.set_author(name="LiveSoccerTV.com")

        # Selection View if team is passed
        if team:
            if team in self.bot.tv:
                e.url = self.bot.tv[team]
                e.title = f"Televised Fixtures for {team}"

            else:
                if not (matches := [i for i in self.bot.tv if team.lower() in i.lower()]):
                    return await self.bot.error(interaction, f"Could not find a matching team for {team}.")

                await (view := TVSelect(interaction, matches)).update()
                await view.wait()
                e.url = self.bot.tv[view.value[0]]
                e.title = f"Televised Fixtures for {view.value[0]}"
        else:
            e.url = "http://www.livesoccertv.com/schedules/"
            e.title = f"Today's Televised Matches"

        async with self.bot.session.get(e.url, headers=HEADERS) as resp:
            match resp.status:
                case 200:
                    tree = html.fromstring(await resp.text())
                case _:
                    raise ConnectionError(f"{e.url} returned a HTTP {resp.status} error.")

        # match_column = 3 if not team else 5
        match_column = 3
        rows = []
        for i in tree.xpath(".//table[@class='schedules'][1]//tr"):
            # Discard finished games.
            if ''.join(i.xpath('.//td[@class="livecell"]//span/@class')).strip() in ["narrow ft", "narrow repeat"]:
                continue

            if not (match := ''.join(i.xpath(f'.//td[{match_column}]//text()')).strip):
                continue

            try:
                link = f"http://www.livesoccertv.com/{i.xpath(f'.//td[{match_column + 1}]//a/@href')[-1]}"
            except IndexError:
                link = ""

            try:
                timestamp = int(i.xpath('.//@dv')[0])

                if match_column == 3:
                    ts = Timestamp(datetime.fromtimestamp(timestamp / 1000)).datetime
                else:
                    ts = str(Timestamp(datetime.fromtimestamp(timestamp / 1000)))

            except (ValueError, IndexError):
                date = ''.join(i.xpath('.//td[@class="datecell"]//span/text()')).strip()
                if (time := ''.join(i.xpath('.//td[@class="timecell"]//span/text()')).strip()) not in ["Postp.", "TBA"]:
                    logging.warning(f"TV.py - invalid timestamp.\nDate [{date}] Time [{time}]")
                ts = time

            rows.append(f'{ts}: [{match}]({link})')

        if not rows:
            rows = [f"No televised matches found, check online at {e.url}"]

        return await Paginator(interaction, rows_to_embeds(e, rows)).update()


async def setup(bot: Bot) -> None:
    """Load TV Lookup Module into the bot."""
    await bot.add_cog(Tv(bot))
