"""Fetch the televised matches from livesoccertv.com"""
import datetime
import json
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from core import Bot

from discord import Embed, app_commands, Interaction, Message
from discord.app_commands import command, describe, autocomplete
from discord.ext import commands
from lxml import html

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import ObjectSelectView, Paginator

# aiohttp useragent.
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/75.0.3770.100 Safari/537.36'}


# TODO: Team / League Split


async def tv_ac(interaction: Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Return list of live teams"""
    tv = getattr(interaction.client, "tv", {})
    m = []
    for x in tv.keys():
        if current.lower() in x.lower():
            m.append(app_commands.Choice(name=x[:100], value=x))

    return m[:25]


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        with open('tv.json') as f:
            self.bot.tv = json.load(f)

    @command()
    @describe(name="Search for a team")
    @autocomplete(name=tv_ac)
    async def tv(self, interaction: Interaction, name: str = None) -> Message:
        """Lookup next televised games for a team"""
        await interaction.response.defer(thinking=True)

        e: Embed = Embed(colour=0x034f76)
        e.set_author(name="LiveSoccerTV.com")

        # Selection View if team is passed
        if name in self.bot.tv:
            e.url = self.bot.tv[name]
            e.title = f"Televised Fixtures for {name}"
        else:
            if name:
                matches = [i for i in self.bot.tv if name.lower() in i.lower()]

                if not matches:
                    return await self.bot.error(interaction, f"Could not find a matching team/league for {name}.")

                _ = [('📺', i, self.bot.tv[i]) for i in matches]

                if len(_) > 1:
                    view = ObjectSelectView(self.bot, interaction, objects=_, timeout=30)
                    e.description = '⏬ Multiple results found, choose from the dropdown.'
                    await self.bot.reply(interaction, embed=e, view=view)
                    await view.update()
                    await view.wait()

                    if view.value is None:
                        return await self.bot.error(interaction, "Timed out waiting for you to select an option")

                    result = matches[view.value]
                else:
                    result = matches[0]

                e.url = self.bot.tv[result]
                e.title = f"Televised Fixtures for {result}"
            else:
                e.url = "http://www.livesoccertv.com/schedules/"
                e.title = f"Today's Televised Matches"

        rows = []
        async with self.bot.session.get(e.url, headers=HEADERS) as resp:
            match resp.status:
                case 200:
                    pass
                case _:
                    return await self.bot.error(interaction, f"{e.url} returned a HTTP {resp.status} error.")
            tree = html.fromstring(await resp.text())

        # match_column = 3 if not team else 5
        match_column = 3
        for i in tree.xpath(".//table[@class='schedules'][1]//tr"):
            # Discard finished games.
            complete = ''.join(i.xpath('.//td[@class="livecell"]//span/@class')).strip()
            if complete in ["narrow ft", "narrow repeat"]:
                continue

            match = ''.join(i.xpath(f'.//td[{match_column}]//text()')).strip()
            if not match:
                continue

            try:
                link = i.xpath(f'.//td[{match_column + 1}]//a/@href')[-1]
                link = f"http://www.livesoccertv.com/{link}"
            except IndexError:
                link = ""

            try:
                timestamp = i.xpath('.//@dv')[0]
                timestamp = int(timestamp)
                _ = datetime.datetime.fromtimestamp(timestamp / 1000)
                if match_column == 3:
                    ts = Timestamp(_).datetime
                else:
                    ts = str(Timestamp(_))

            except (ValueError, IndexError):
                date = ''.join(i.xpath('.//td[@class="datecell"]//span/text()')).strip()
                time = ''.join(i.xpath('.//td[@class="timecell"]//span/text()')).strip()
                if time not in ["Postp.", "TBA"]:
                    print(f"TV.py - invalid timestamp.\nDate [{date}] Time [{time}]")
                ts = time

            rows.append(f'{ts}: [{match}]({link})')

        if not rows:
            rows = [f"No televised matches found, check online at {e.url}"]

        view = Paginator(self.bot, interaction, rows_to_embeds(e, rows))
        return await view.update()


async def setup(bot: 'Bot') -> None:
    """Load TV Lookup Module into the bot."""
    await bot.add_cog(Tv(bot))
