"""Fetch Definitions from UrbanDictionary"""
# TODO: Fix Jump Button to be clickable and to show page number.
from __future__ import annotations

import datetime
import importlib
import re
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot


DEFINE = "https://www.urbandictionary.com/define.php?term="
THUMBNAIL = (
    "http://d2gatte9o95jao.cloudfront.net/assets/"
    "apple-touch-icon-2f29e978facd8324960a335075aa9aa3.png"
)


# TODO: Transformer
async def ud_ac(
    interaction: discord.Interaction[Bot], cur: str
) -> list[discord.app_commands.Choice]:
    """Autocomplete from list of cogs"""
    url = f"https://api.urbandictionary.com/v0/autocomplete-extra?term={cur}"
    async with interaction.client.session.get(url) as resp:
        if resp.status != 200:
            raise ConnectionError(f"{resp.status} Error accessing {url}")
        results = await resp.json()

    res = results["results"]

    choices = []
    for i in res:
        nom = f"{i['term']}: {i['preview']}"[:100]
        choices.append(discord.app_commands.Choice(name=nom, value=i["term"]))

        if len(choices) == 25:
            break
    return choices


class UrbanView(view_utils.BaseView):
    """Generic View to paginate through multiple definitions"""

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        embeds: list[discord.Embed],
    ) -> None:
        super().__init__(interaction)
        self.pages: list[discord.Embed] = embeds

    async def update(self) -> discord.InteractionMessage:
        """Push the latest version of the view to the user"""
        self.clear_items()

        self.add_page_buttons()
        edit = self.interaction.edit_original_response
        return await edit(embed=self.pages[self.index], view=self)


def parse(results: dict) -> list[discord.Embed]:
    """Convert UD JSON to embeds"""
    embeds = []
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
    async def search(
        self, interaction: discord.Interaction[Bot], term: str
    ) -> discord.InteractionMessage:
        """Lookup a definition from Urban Dictionary"""

        await interaction.response.defer(thinking=True)

        url = f"http://api.urbandictionary.com/v0/define?term={term}"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                return await self.bot.error(
                    interaction, f"🚫 HTTP Error, code: {resp.status}"
                )
            if not (embeds := parse(await resp.json())):
                return await self.bot.error(
                    interaction, f"🚫 No results found for {term}."
                )
            return await UrbanView(interaction, embeds).update()

    @ud.command()
    async def random(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Get some random definitions from Urban Dictionary"""
        await interaction.response.defer(thinking=True)

        url = "https://api.urbandictionary.com/v0/random"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                err = f"🚫 HTTP Error, code: {resp.status}"
                return await self.bot.error(interaction, err)
            data = parse(await resp.json())
        return await UrbanView(interaction, data).update()

    @ud.command()
    async def word_of_the_day(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Get the Word of the Day from Urban Dictionary"""
        await interaction.response.defer(thinking=True)
        url = "https://api.urbandictionary.com/v0/words_of_the_day"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                err = f"🚫 HTTP Error, code: {resp.status}"
                return await self.bot.error(interaction, err)
            data = parse(await resp.json())
        return await UrbanView(interaction, data).update()


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(UrbanDictionary(bot))
