"""Fetch Definitions from UrbanDictionary"""
# TODO: Fix Jump Button to be clickable and to show page number.

from __future__ import annotations

from importlib import reload
from re import finditer
from typing import TYPE_CHECKING

import datetime
import discord
from discord import Embed
from discord.app_commands import autocomplete, Group, Choice
from discord.ext.commands import Cog

from ext.utils import view_utils
from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot
    from discord import Interaction, Message

THUMBNAIL = (
    "http://d2gatte9o95jao.cloudfront.net/assets/"
    "apple-touch-icon-2f29e978facd8324960a335075aa9aa3.png"
)


async def ud_ac(interaction: Interaction[Bot], current: str) -> list[Choice]:
    """Autocomplete from list of cogs"""
    url = (
        "https://api.urbandictionary.com/v0/"
        f"autocomplete-extra?term={current}"
    )
    async with interaction.client.session.get(url) as resp:
        match resp.status:
            case 200:
                results = await resp.json()
            case _:
                raise ConnectionError(f"{resp.status} Error accessing {url}")

    res = results["results"]
    return [
        Choice(name=f"{r['term']}: {r['preview']}"[:100], value=r["term"])
        for r in res
    ]


class UrbanView(BaseView):
    """Generic View to paginate through multiple definitions"""

    def __init__(
        self, interaction: Interaction[Bot], embeds: list[Embed]
    ) -> None:
        super().__init__(interaction)
        self.pages: list[Embed] = embeds

    async def update(self) -> Message:
        """Push the latest version of the view to the user"""
        self.clear_items()

        self.add_item(view_utils.Previous(self))
        if len(self.pages) > 3:
            self.add_item(view_utils.Jump(view=self))
        self.add_item(view_utils.Next(self))
        self.add_item(view_utils.Stop(row=0))
        return await self.interaction.edit_original_response(
            embed=self.pages[self.index], view=self
        )


def parse(results: dict) -> list[Embed]:
    """Convert UD JSON to embeds"""
    embeds = []
    for i in results["list"]:
        e = Embed(color=0xFE3511)
        e.set_author(name=i["word"], url=i["permalink"], icon_url=THUMBNAIL)
        de = i["definition"]
        for z in finditer(r"\[(.*?)]", de):
            z1 = z.group(1).replace(" ", "%20")
            z = z.group()
            de = de.replace(
                z, f"{z}(https://www.urbandictionary.com/define.php?term={z1})"
            )

        e.description = f"{de[:2046]} …" if len(de) > 2048 else de

        targ = "https://www.urbandictionary.com/define.php?term="
        if i["example"]:
            ex = i["example"]
            for z in finditer(r"\[(.*?)]", ex):
                z1 = z.group(1).replace(" ", "%20")
                z = z.group()
                ex = ex.replace(z, f"{z}({targ + z1})")

            ex = f"{ex[:1023]}…" if len(ex) > 1024 else ex
            e.add_field(name="Usage", value=ex)

        e.set_footer(
            text=f"👍{i['thumbs_up']} 👎{i['thumbs_down']} - {i['author']}"
        )
        e.timestamp = datetime.datetime.fromisoformat(i["written_on"])
        embeds.append(e)
    return embeds


class UrbanDictionary(Cog):
    """UrbanDictionary Definition Fetcher"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        reload(view_utils)

    ud = Group(
        name="urban", description="Get definitions from Urban Dictionary"
    )

    @ud.command()
    @discord.app_commands.describe(term="enter a search term")
    @discord.app_commands.autocomplete(term=ud_ac)
    async def search(
        self, interaction: Interaction[Bot], term: str
    ) -> UrbanView | Message:
        """Lookup a definition from Urban Dictionary"""

        await interaction.response.defer(thinking=True)
        async with self.bot.session.get(
            f"http://api.urbandictionary.com/v0/define?term={term}"
        ) as resp:
            match resp.status:
                case 200:
                    if not (embeds := parse(await resp.json())):
                        return await self.bot.error(
                            interaction, f"🚫 No results found for {term}."
                        )
                    return await UrbanView(interaction, embeds).update()
                case _:
                    return await self.bot.error(
                        interaction, f"🚫 HTTP Error, code: {resp.status}"
                    )

    @ud.command()
    async def random(self, ctx: Interaction[Bot]) -> Message:
        """Get some random definitions from Urban Dictionary"""
        await ctx.response.defer(thinking=True)

        url = "https://api.urbandictionary.com/v0/random"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    js = parse(await resp.json())
                    return await UrbanView(ctx, js).update()
                case _:
                    err = f"🚫 HTTP Error, code: {resp.status}"
                    return await self.bot.error(ctx, err)

    @ud.command()
    async def word_of_the_day(self, interaction: Interaction[Bot]) -> Message:
        """Get the Word of the Day from Urban Dictionary"""
        await interaction.response.defer(thinking=True)
        url = "https://api.urbandictionary.com/v0/words_of_the_day"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    js = parse(await resp.json())
                case _:
                    err = f"🚫 HTTP Error, code: {resp.status}"
                    return await self.bot.error(interaction, err)
        return await UrbanView(interaction, js).update()


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(UrbanDictionary(bot))
