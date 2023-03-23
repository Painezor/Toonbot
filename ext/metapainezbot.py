"""Meta information related to painezBot"""
from __future__ import annotations

import typing
import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from painezBot import PBot

INV = """https://discord.com/api/oauth2/authorize?client_id=964870918738419752&
scope=bot%20applications.commands"""


class MetaPainezbot(commands.Cog):
    """ "Meta Information about painezBot"""

    def __init__(self, bot: PBot):
        self.bot: PBot = bot

    @discord.app_commands.command()
    async def invite(self, interaction: discord.Interaction[PBot]) -> None:
        """Get the bots invite link"""
        view = discord.ui.View()

        btn = discord.ui.Button(style=discord.ButtonStyle.url, url=INV)
        btn.label = "Invite me"
        view.add_item(btn)
        return await interaction.response.send_message(view=view)

    @discord.app_commands.command()
    async def about(self, interaction: discord.Interaction[PBot]) -> None:
        """Tells you information about the bot itself."""

        e = discord.Embed(colour=0x2ECC71)
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

        view = discord.ui.View()
        em = "<:painezBot:928654001279471697>"
        btn = discord.ui.Button(url=INV, emoji=em)
        btn.label = "Invite me to your server"
        view.add_item(btn)
        return await interaction.response.send_message(embed=e, view=view)


async def setup(bot: PBot):
    """Load the meta cog into the bot"""
    await bot.add_cog(MetaPainezbot(bot))
