"""World of Warships Codes handler"""
from __future__ import annotations

import typing

import discord
from discord.ext import commands

from ext.wows_api import Region

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]


CODE_IMG = "https://cdn.iconscout.com/icon/free/png-256/wargaming-1-283119.png"


class Codes(commands.Cog):
    """Handle parsing of World of Warships Promo Codes"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
    @discord.app_commands.describe(
        code="Enter the code", contents="Enter the reward the code gives"
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def code(
        self,
        interaction: Interaction,
        code: str,
        contents: str,
        eu: bool = True,  # pylint: disable=C0103
        na: bool = True,  # pylint: disable=C0103
        asia: bool = True,
    ) -> None:
        """Send a message with region specific redeem buttons"""
        regions: list[str] = []
        if eu:
            regions.append("eu")
        if na:
            regions.append("na")
        if asia:
            regions.append("sea")

        embed = discord.Embed(title=code, colour=discord.Colour.blurple())
        embed.url = f"https://eu.wargaming.net/shop/redeem/?bonus_mode={code}"
        embed.set_author(name="Bonus Code", icon_url=CODE_IMG)
        embed.set_thumbnail(
            url="https://wg-art.com/media/filer_public_thumbnails"
            "/filer_public/72/22/72227d3e-d42f-4e16-a3e9-012eb239214c/"
            "wg_wows_logo_mainversion_tm_fullcolor_ru_previewwebguide.png"
        )
        if contents:
            embed.add_field(name="Contents", value=f"```yaml\n{contents}```")
        embed.set_footer(text="Click below to redeem for each region")

        view = discord.ui.View()
        for i in regions:
            region = next(r for r in Region if i == r.db_key)

            dom = region.code_prefix
            url = f"https://{dom}.wargaming.net/shop/redeem/?bonus_mode={code}"
            btn = discord.ui.Button(url=url, label=region.name)
            btn.emoji = region.emote
            view.add_item(btn)

        return await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: PBot):
    """Load the Codes cog into the bot"""
    await bot.add_cog(Codes(bot))
