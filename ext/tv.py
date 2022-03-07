"""Fetch the televised matches from livesoccertv.com"""
import datetime
import json
from typing import Optional, List

from discord import Embed, app_commands, Interaction
from discord.ext import commands
from lxml import html

from ext.utils import embed_utils, view_utils, timed_events

# aiohttp useragent.
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/75.0.3770.100 Safari/537.36'}


async def team(interaction: Interaction, current: str, namespace) -> List[app_commands.Choice[str]]:
    """Return list of live leagues"""
    matches = [x for x in interaction.client.tv if current.lower() in x.lower()]
    return [app_commands.Choice(name=item, value=item) for item in matches if current.lower() in item.lower()]


@app_commands.command()
@app_commands.describe(name="Search for a team")
@app_commands.autocomplete(name=team)
async def tv(self, interaction: Interaction, name: Optional[str] = None):
    """Lookup next televised games for a team"""
    await interaction.response.defer(thinking=True)
    e = Embed(colour=0x034f76)
    e.set_author(name="LiveSoccerTV.com")

    # Selection View if team is passed
    if name:
        matches = [i for i in self.bot.tv if str(name).lower() in i.lower()]

        if not matches:
            return await interaction.client.error(interaction, f"Could not find a matching team/league for {name}.")

        _ = [('📺', i, self.bot.tv[i]) for i in matches]

        if len(_) > 1:
            view = view_utils.ObjectSelectView(interaction, objects=_, timeout=30)
            e.description = '⏬ Multiple results found, choose from the dropdown.'
            message = await interaction.client.reply(interaction, embed=e, view=view)
            view.message = message
            await view.update()
            await view.wait()

            if view.value is None:
                return None

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
        if resp.status != 200:
            return await interaction.client.error(interaction, f"{e.url} returned a HTTP {resp.status} error.")
        tree = html.fromstring(await resp.text())

    match_column = 3 if not team else 5
    for i in tree.xpath(".//table[@class='schedules'][1]//tr"):
        # Discard finished games.
        complete = "".join(i.xpath('.//td[@class="livecell"]//span/@class')).strip()
        if complete in ["narrow ft", "narrow repeat"]:
            continue

        match = "".join(i.xpath(f'.//td[{match_column}]//text()')).strip()
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
                ts = timed_events.Timestamp(_).datetime
            else:
                ts = str(timed_events.Timestamp(_))

        except (ValueError, IndexError):
            date = "".join(i.xpath('.//td[@class="datecell"]//span/text()')).strip()
            time = "".join(i.xpath('.//td[@class="timecell"]//span/text()')).strip()
            if time not in ["Postp.", "TBA"]:
                print(f"TV.py - invalid timestamp.\nDate [{date}] Time [{time}]")
            ts = time

        rows.append(f'{ts}: [{match}]({link})')

    if not rows:
        rows = [f"No televised matches found, check online at {e.url}"]

    view = view_utils.Paginator(interaction, embed_utils.rows_to_embeds(e, rows))
    await view.update()


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot):
        self.bot = bot
        with open('tv.json') as f:
            bot.tv = json.load(f)
        self.bot.tree.add_command(tv)


def setup(bot):
    """Load TV Lookup Module into the bot."""
    bot.add_cog(Tv(bot))
