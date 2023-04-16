"""Meta information related to Toonbot"""
from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]

INV = (
    "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&"
    "permissions=1514244730006&scope=bot%20applications.commands"
)


class MetaToonbot(commands.Cog):
    """ "Meta Information about Toonbot"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @discord.app_commands.command()
    async def invite(self, interaction: Interaction) -> None:
        """Get the bots invite link"""
        view = discord.ui.View()
        btn: discord.ui.Button[discord.ui.View]
        btn = discord.ui.Button(url=INV)
        btn.label = "Invite me to your server"
        view.add_item(btn)
        embed = discord.Embed()
        embed.description = "Use the button below to invite me to your server."
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def about(self, interaction: Interaction) -> None:
        """Tells you information about the bot itself."""
        user = self.bot.user
        assert user is not None
        embed = discord.Embed(colour=0x2ECC71, timestamp=user.created_at)

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.title = f"About {user.name}"

        # statistics
        total_members = sum(len(g.members) for g in self.bot.guilds)

        count = format(len(self.bot.guilds), ",")
        members = format(total_members, ",")

        embed.description = (
            f"I do football lookup related things.\n\n"
            f"{members} users on {count} servers,\n\n"
            "I was created by Painezor#8489 as a hobby, feel free to send a "
            "donation if you would like to help support me with this project. "
            "\n\nToonbot has no premium features and is offered "
            " completely for free at the expense of my  own time and hosting."
        )

        view = discord.ui.View()
        support = (
            "Join my Support Server",
            "http://www.discord.gg/a5NHvPx",
            "<:Toonbot:952717855474991126>",
        )
        invite = ("Invite me to your server", INV, None)
        dono = ("Donate", "https://paypal.me/Toonbot", None)
        btn: discord.ui.Button[discord.ui.View]
        for label, link, emoji in [support, invite, dono]:
            btn = discord.ui.Button(url=link, label=label, emoji=emoji)
            view.add_item(btn)
        return await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: Bot):
    """Load the meta cog into the bot"""
    await bot.add_cog(MetaToonbot(bot))
