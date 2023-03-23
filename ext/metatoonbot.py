"""Meta information related to Toonbot"""
from __future__ import annotations

import typing

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from core import Bot

INV = """https://discord.com/api/oauth2/authorize?client_id=250051254783311873&
permissions=1514244730006&scope=bot%20applications.commands"""


class MetaToonbot(commands.Cog):
    """ "Meta Information about Toonbot"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @discord.app_commands.command()
    async def invite(self, interaction: discord.Interaction[Bot]) -> None:
        """Get the bots invite link"""
        view = discord.ui.View()
        b = discord.ui.Button(style=discord.ButtonStyle.url, url=INV)
        b.label = "Invite me to your server"
        view.add_item(b)
        e = discord.Embed()
        e.description = "Use the button below to invite me to your server."
        return await interaction.response.send_message(embed=e, view=view)

    @discord.app_commands.command()
    async def about(self, interaction: discord.Interaction[Bot]) -> None:
        """Tells you information about the bot itself."""
        u = typing.cast(discord.Member, self.bot.user)
        e = discord.Embed(colour=0x2ECC71, timestamp=u.created_at)
        e.set_footer(text=f"{u.name} is coded by Painezor and was created ")

        e.set_thumbnail(url=u.display_avatar.url)
        e.title = f"About {u.name}"

        # statistics
        total_members = sum(len(g.members) for g in self.bot.guilds)

        g = format(len(self.bot.guilds), ",")
        members = f"{format(total_members, ',')} users across {g} servers."

        e.description = (
            f"I do football lookup related things.\n I serve commands from"
            f"{members}\n I was created by Painezor#8489 as a hobby, feel free"
            " to send a  donation if you would like to help support me with "
            "this project. \nToonbot has no premium features and is offered "
            " completely for free at the expense of my  own time and hosting."
        )

        view = discord.ui.View()
        s = (
            "Join my Support Server",
            "http://www.discord.gg/a5NHvPx",
            "<:Toonbot:952717855474991126>",
        )
        i = ("Invite me to your server", INV, None)
        d = ("Donate", "https://paypal.me/Toonbot", None)
        for label, link, emoji in [s, i, d]:
            btn = discord.ui.Button(url=link, label=label, emoji=emoji)
            view.add_item(btn)
        return await interaction.response.send_message(embed=e, view=view)


async def setup(bot: Bot):
    """Load the meta cog into the bot"""
    await bot.add_cog(MetaToonbot(bot))
