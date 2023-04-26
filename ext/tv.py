"""Fetch the televised matches from livesoccertv.com"""
from __future__ import annotations

import dataclasses
import logging
import typing
import datetime

import discord
from discord.ext import commands
from lxml import html

from ext.utils import view_utils, embed_utils, timed_events

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
User: typing.TypeAlias = discord.User | discord.Member

# aiohttp useragent.
LST = "http://www.livesoccertv.com/"
AC_URL = "https://www.livesoccertv.com/include/autocomplete.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
}

logger = logging.getLogger("tv")


# TODO: Team / League Split
# TODO: Initial Passover of fixture upon view creation
# to get all available buttons in the style of Fixtures rewrite.
# TODO: Make functions for all buttons.


#
# <div class="hints">
#   <a href="/slog.php?q=testi&url=%2Fteams%2Fromania%2Farge-pite-ti%2F" style="color:#333;text-decoration:none;">
#       <div class="flaticon crest lblue" title="Team"></div>
#       <span class="name" title="Club"></span>
#       Argeş Piteşti
#       <div class="sdesc"># Romania </div>
#   </a>
# </div>
# <div class="hints">
#   <a href="/slog.php?q=testi&url=%2Fteams%2Fromania%2Fminerul-coste-ti%2F" style="color:#333;text-decoration:none;">
#       <div class="flaticon crest lblue" title="Team"></div>
#       <span class="name" title="Club"></span>
#       Minerul Costeşti
#       <div class="sdesc"># Romania </div>
#   </a>
# </div>
# <div class="hints">
# <a href="/slog.php?q=testi&url=%2Fcompetitions%2Finternational%2Fclub-friendly%2F" style="color:#333;text-decoration:none;">
# <div class="flaticon cup lred" title="Competition"></div>
# <span class="name" title="Competition"></span>
# Club Friendly <div class="sdesc">
# International </div>
# </a>
# </div>
# <div class="hints">
# <a href="/slog.php?q=testi&url=%2Fplayer%2Fivanaldo%2F317736%2F" style="color:#333;text-decoration:none;">
# <div class="flaticon player lggrey" title="Player"></div>
# <span class="name" title="Player"></span>
# Testinha <div class="sdesc">
# Pacajus </div>
# </a>
# </div>


@dataclasses.dataclass(slots=True)
class SearchResult:
    pass


class TVTeam:
    pass


class TVCompetition:
    pass


async def tv_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Return list of live teams"""
    cur = current.casefold()

    data = {"search": cur}
    async with interaction.client.session.post(AC_URL, data=data) as resp:
        if resp.status != 200:
            rsn = await resp.text()
            logger.error("%s %s: %s", resp.status, rsn, resp.url)
        tree = html.fromstring(await resp.text())

    for _ in tree.xpath("./div"):
        pass

    logger.info("FINISH TV_AC!")
    choices: list[discord.app_commands.Choice[str]] = []

    return choices[:25]


class Tv(commands.Cog):
    """Search for live TV matches"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @discord.app_commands.command(name="tv")
    @discord.app_commands.describe(team="Search for a team")
    @discord.app_commands.autocomplete(team=tv_ac)
    async def tv_cmd(self, interaction: Interaction, team: str | None) -> None:
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
                rsn = await resp.text()
                logger.error("%s %s: %s", resp.status, rsn, resp.url)
            tree = html.fromstring(await resp.text())

        # match_column = 3 if not team else 5
        match_column = 3
        rows: list[str] = []
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
        view = view_utils.Paginator(interaction.user, embeds)
        return await view.handle_page(interaction)


async def setup(bot: Bot) -> None:
    """Load TV Lookup Module into the bot."""
    await bot.add_cog(Tv(bot))
