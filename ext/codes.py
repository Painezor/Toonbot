"""World of Warships Codes handler"""
from __future__ import annotations

import discord
import typing
from discord.ext import commands

from ext.utils.wows_api import Region

if typing.TYPE_CHECKING:
    from painezBot import PBot


CODE_IMG = "https://cdn.iconscout.com/icon/free/png-256/wargaming-1-283119.png"


class Codes(commands.Cog):
    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
    @discord.app_commands.describe(
        code="Enter the code", contents="Enter the reward the code gives"
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def code(
        self,
        interaction: discord.Interaction[PBot],
        code: str,
        contents: str,
        eu: bool = True,
        na: bool = True,
        asia: bool = True,
    ) -> discord.InteractionMessage:
        """Send a message with region specific redeem buttons"""

        await interaction.response.defer(thinking=True)

        regions = []
        if eu:
            regions.append("eu")
        if na:
            regions.append("na")
        if asia:
            regions.append("sea")

        e = discord.Embed(title=code, colour=discord.Colour.blurple())
        e.url = f"https://eu.wargaming.net/shop/redeem/?bonus_mode={code}"
        e.set_author(name="Bonus Code", icon_url=CODE_IMG)
        e.set_thumbnail(
            url="https://wg-art.com/media/filer_public_thumbnails"
            "/filer_public/72/22/72227d3e-d42f-4e16-a3e9-012eb239214c/"
            "wg_wows_logo_mainversion_tm_fullcolor_ru_previewwebguide.png"
        )
        if contents:
            e.add_field(name="Contents", value=f"```yaml\n{contents}```")
        e.set_footer(text="Click on a button below to redeem for your region")

        view = discord.ui.View()
        for i in regions:
            region = next(r for r in Region if i == r.db_key)

            dom = region.code_prefix
            url = f"https://{dom}.wargaming.net/shop/redeem/?bonus_mode={code}"
            btn = discord.ui.Button(url=url, label=region.name)
            btn.emoji = region.emote
            btn.style = discord.ButtonStyle.url
            view.add_item(btn)

        return await interaction.edit_original_response(embed=e, view=view)


async def setup(bot: PBot):
    await bot.add_cog(Codes(bot))
