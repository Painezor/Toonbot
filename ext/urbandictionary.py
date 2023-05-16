"""Fetch Definitions from UrbanDictionary"""
from __future__ import annotations

import datetime
from logging import getLogger
import importlib
import re
from typing import Any, TYPE_CHECKING, TypeAlias

import discord
from discord.ext import commands

from ext.utils import view_utils

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]


logger = getLogger("urbandictionary")


DEFINE = "https://api.urbandictionary.com/v0/define?term="
THUMBNAIL = (
    "http://d2gatte9o95jao.cloudfront.net/assets/"
    "apple-touch-icon-2f29e978facd8324960a335075aa9aa3.png"
)
RANDOM = "https://api.urbandictionary.com/v0/random"
WORD_OF_THE_DAY = "https://api.urbandictionary.com/v0/words_of_the_day"


# TODO: Transformer
async def ud_ac(
    interaction: Interaction, cur: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete from list of cogs"""
    url = f"https://api.urbandictionary.com/v0/autocomplete-extra?term={cur}"
    async with interaction.client.session.get(url) as resp:
        if resp.status != 200:
            raise ConnectionError(f"{resp.status} Error accessing {url}")
        results = await resp.json()

    res = results["results"]

    choices: list[discord.app_commands.Choice[str]] = []
    for i in res:
        nom = f"{i['term']}: {i['preview']}"[:100]
        choices.append(discord.app_commands.Choice(name=nom, value=i["term"]))

        if len(choices) == 25:
            break
    return choices


def parse(results: dict[str, Any]) -> list[discord.Embed]:
    """Convert UD JSON to embeds"""
    embeds: list[discord.Embed] = []
    for i in results["list"]:
        embed = discord.Embed(color=0xFE3511)
        link = i["permalink"]
        embed.set_author(name=i["word"], url=link, icon_url=THUMBNAIL)
        defin = i["definition"]
        for item in re.finditer(r"\[(.*?)]", defin):
            rep1 = item.group(1).replace(" ", "%20")
            item = item.group()
            defin = defin.replace(item, f"{item}({DEFINE}{rep1})")

        embed.description = f"{defin[:2046]} …" if len(defin) > 2048 else defin

        targ = "https://www.urbandictionary.com/define.php?term="
        if i["example"]:
            example = i["example"]
            for item in re.finditer(r"\[(.*?)]", example):
                rep1 = item.group(1).replace(" ", "%20")
                item = item.group()
                example = example.replace(item, f"{item}({targ + rep1})")

            example = f"{example[:1023]}…" if len(example) > 1024 else example
            embed.add_field(name="Usage", value=example)

        embed.set_footer(
            text=f"👍{i['thumbs_up']} 👎{i['thumbs_down']} - {i['author']}"
        )
        embed.timestamp = datetime.datetime.fromisoformat(i["written_on"])
        embeds.append(embed)
    return embeds


class UrbanDictionary(commands.Cog):
    """UrbanDictionary Definition Fetcher"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        importlib.reload(view_utils)

    ud = discord.app_commands.Group(
        name="urban", description="Get definitions from Urban Dictionary"
    )

    @ud.command()
    @discord.app_commands.describe(term="enter a search term")
    @discord.app_commands.autocomplete(term=ud_ac)
    async def search(self, interaction: Interaction, term: str) -> None:
        """Lookup a definition from Urban Dictionary"""

        url = DEFINE + term
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                logger.error("%s: %s", resp.status, resp.url)

            data = await resp.json()

        if not (embeds := parse(data)):
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 No results for {term}"
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        view = view_utils.EmbedPaginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=embeds[0])

    @ud.command()
    async def random(self, interaction: Interaction) -> None:
        """Get some random definitions from Urban Dictionary"""
        async with self.bot.session.get(RANDOM) as resp:
            if resp.status != 200:
                logger.error("%s: %s", resp.status, resp.url)
            json = await resp.json()
            embeds = parse(json)
        view = view_utils.EmbedPaginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=embeds[0])

    @ud.command()
    async def word_of_the_day(self, interaction: Interaction) -> None:
        """Get the Word of the Day from Urban Dictionary"""
        await interaction.response.defer(thinking=True)
        async with self.bot.session.get(WORD_OF_THE_DAY) as resp:
            if resp.status != 200:
                logger.error("%s: %s", resp.status, resp.url)
            json = await resp.json()
        embeds = parse(json)
        view = view_utils.EmbedPaginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=embeds[0])


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(UrbanDictionary(bot))
