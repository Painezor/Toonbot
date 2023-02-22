"""Meta information related to Toonbot"""
from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Embed, Interaction, Message, ButtonStyle
from discord.app_commands import command
from discord.ext.commands import Cog
from discord.ui import View, Button

if TYPE_CHECKING:
    from core import Bot

INV = ("https://discord.com/api/oauth2/authorize?client_id=250051254783311873"
       "&permissions=1514244730006&scope=bot%20applications.commands")


class MetaToonbot(Cog):
    """"Meta Information about Toonbot"""

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @command()
    async def invite(self, interaction: Interaction) -> None:
        """Get the bots invite link"""
        view = View()
        view.add_item(
            Button(
             style=ButtonStyle.url, url=INV, label="Invite me to your server"))
        e: Embed = Embed(
            description="Use the button below to invite me to your server.")
        await self.bot.reply(interaction, embed=e, view=view, ephemeral=True)

    @command()
    async def about(self, interaction: Interaction) -> Message:
        """Tells you information about the bot itself."""
        e: Embed = Embed(colour=0x2ecc71, timestamp=self.bot.user.created_at)
        e.set_footer(
            text=f"{self.bot.user.name} is coded by Painezor and was created ")

        me = self.bot.user
        e.set_thumbnail(url=me.display_avatar.url)
        e.title = f"About {self.bot.user.name}"

        # statistics
        total_members = sum(len(s.members) for s in self.bot.guilds)

        g = format(len(self.bot.guilds), ',')
        members = f"{format(total_members, ',')} users across {g} servers."

        e.description = (f"I do football lookup related things.\n I serve "
                         f"commands from {members}\n I was created by "
                         "Painezor#8489 as a hobby, feel free to send a"
                         " donation if you would like to help support me with"
                         " this project. \nToonbot has no premium features and"
                         " is offered completely for free at the expense of my"
                         " own time and hosting.")

        view = View()
        s = ("Join my Support Server", "http://www.discord.gg/a5NHvPx",
             "<:Toonbot:952717855474991126>")
        i = ("Invite me to your server", INV, None)
        d = ("Donate", "https://paypal.me/Toonbot", None)
        for label, link, emoji in [s, i, d]:
            view.add_item(Button(url=link, label=label, emoji=emoji))
        return await self.bot.reply(interaction, embed=e, view=view)


async def setup(bot: Bot):
    """Load the meta cog into the bot"""
    await bot.add_cog(MetaToonbot(bot))
