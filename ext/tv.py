"""Fetch the televised matches from livesoccertv.com"""
import datetime
import json

from discord import Option, Embed
from discord.ext import commands
from lxml import html

from ext.utils import embed_utils, view_utils, timed_events

# aiohttp useragent.
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/75.0.3770.100 Safari/537.36'}


# Autocomplete
async def tv_list(ctx):
    """TV Autocomplete"""
    queries = ctx.value.lower().split(' ')

    matches = []
    for x in ctx.bot.tv:
        if all(q in x.lower() for q in queries):
            matches.append(x)

    return matches


TV = Option(str, "Search for Television fixtures", autocomplete=tv_list, required=False)


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot):
        self.bot = bot
        with open('tv.json') as f:
            bot.tv = json.load(f)

    @commands.slash_command()
    async def tv(self, ctx, team: TV):
        """Lookup next televised games for a team"""
        e = Embed()
        e.colour = 0x034f76
        e.set_author(name="LiveSoccerTV.com")

        # Selection View if team is passed
        if team:
            matches = [i for i in self.bot.tv if str(team).lower() in i.lower()]

            if not matches:
                return await ctx.error(f"Could not find a matching team/league for {team}.")

            _ = [('📺', i, self.bot.tv[i]) for i in matches]

            if len(_) > 1:
                view = view_utils.ObjectSelectView(ctx, objects=_, timeout=30)
                e.description = '⏬ Multiple results found, choose from the dropdown.'
                message = await ctx.reply(embed=e, view=view)
                view.message = message
                await view.update()
                await view.wait()

                if view.value is None:
                    return None

                team = matches[view.value]
            else:
                team = matches[0]
                message = await ctx.reply(content=f"Fetching televised matches for {team}")

            e.url = self.bot.tv[team]
            e.title = f"Televised Fixtures for {team}"
        else:
            e.url = "http://www.livesoccertv.com/schedules/"
            e.title = f"Today's Televised Matches"
            message = await ctx.reply(content=f"Fetching televised matches...")

        rows = []
        async with self.bot.session.get(e.url, headers=HEADERS) as resp:
            if resp.status != 200:
                return await ctx.error(f"{e.url} returned a HTTP {resp.status} error.")
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

        view = view_utils.Paginator(ctx, embed_utils.rows_to_embeds(e, rows))
        view.message = message
        await view.update()


def setup(bot):
    """Load TV Lookup Module into the bot."""
    bot.add_cog(Tv(bot))
