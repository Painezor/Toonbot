"""Meta information related to painezBot"""
from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Embed, Interaction, Message, ButtonStyle
import discord
from discord.ext.commands import Cog
from discord.ui import View, Button

if TYPE_CHECKING:
    from painezBot import PBot

INV = (
    "https://discord.com/api/oauth2/authorize?client_id=964870918738419752&"
    "scope=bot%20applications.commands"
)


class MetaPainezbot(Cog):
    """ "Meta Information about painezBot"""

    def __init__(self, bot: PBot):
        self.bot: PBot = bot

    @discord.app_commands.command()
    async def invite(self, interaction: Interaction) -> Message:
        """Get the bots invite link"""
        view = View()
        view.add_item(
            Button(style=ButtonStyle.url, url=INV, label="Invite me")
        )
        return await self.bot.reply(interaction, view=view, ephemeral=True)

    @discord.app_commands.command()
    async def about(self, interaction: Interaction) -> Message:
        """Tells you information about the bot itself."""

        e: Embed = Embed(colour=0x2ECC71)
        e.set_footer(text="painezBot is coded by Painezor | Created on")

        me = self.bot.user
        if me is not None:
            e.set_thumbnail(url=me.display_avatar.url)
            e.timestamp = me.created_at
        e.title = "About painezBot"

        # statistics
        total_members = sum(len(g.members) for g in self.bot.guilds)
        e.description = (
            f"I do World of Warships lookups, including dev blogs"
            f", news, ships, and players.\nI have {total_members}"
            "users across {len(self.bot.guilds)} servers."
        )

        view = View()
        em = "<:painezBot:928654001279471697>"
        btn = Button(url=INV, label="Invite me to your server", emoji=em)
        view.add_item(btn)
        return await self.bot.reply(interaction, embed=e, view=view)


async def setup(bot: PBot):
    """Load the meta cog into the bot"""
    await bot.add_cog(MetaPainezbot(bot))
