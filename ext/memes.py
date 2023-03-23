"""Miscellaneous toys built for my own personal entertainment."""
from __future__ import annotations

import random

import typing
import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from core import Bot


class Memes(commands.Cog):
    """Various Toys for you to play with."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    mem_grp = discord.app_commands.Group(
        name="memes", description="annoy your friends with dead jokes"
    )

    @mem_grp.command()
    async def dead(self, interaction: discord.Interaction[Bot]) -> None:
        """STOP, STOP HE'S ALREADY DEAD"""
        vid = "https://www.youtube.com/watch?v=mAUY1J8KizU"
        return await interaction.response.send_message(vid)

    @mem_grp.command(name="f")
    async def press_f(self, interaction: discord.Interaction[Bot]) -> None:
        """Press F to pay respects"""
        img = "https://i.imgur.com/zrNE05c.gif"
        return await interaction.response.send_message(img)

    @mem_grp.command()
    async def helmet(self, interaction: discord.Interaction[Bot]) -> None:
        """Helmet"""
        helmet = discord.File(fp="Images/helmet.jpg")
        return await interaction.response.send_message(file=helmet)

    @mem_grp.command()
    async def lenny(self, interaction: discord.Interaction[Bot]) -> None:
        """( ͡° ͜ʖ ͡°)"""
        lennys = [
            "( ͡° ͜ʖ ͡°)",
            "(ᴗ ͜ʖ ᴗ)",
            "(⟃ ͜ʖ ⟄) ",
            "(͠≖ ͜ʖ͠≖)",
            "ʕ ͡° ʖ̯ ͡°ʔ",
            "( ͠° ͟ʖ ͡°)",
            "( ͡~ ͜ʖ ͡°)",
            "( ͡◉ ͜ʖ ͡◉)",
            "( ͡° ͜V ͡°)",
            "( ͡ᵔ ͜ʖ ͡ᵔ )",
            "(☭ ͜ʖ ☭)",
            "( ° ͜ʖ °)",
            "( ‾ ʖ̫ ‾)",
            "( ͡° ʖ̯ ͡°)",
            "( ͡° ل͜ ͡°)",
            "( ͠° ͟ʖ ͠°)",
            "( ͡o ͜ʖ ͡o)",
            "( ͡☉ ͜ʖ ͡☉)",
            "ʕ ͡° ͜ʖ ͡°ʔ",
            "( ͡° ͜ʖ ͡ °)",
        ]
        return await interaction.response.send_message(random.choice(lennys))

    @mem_grp.command()
    async def thatsthejoke(
        self, interaction: discord.Interaction[Bot]
    ) -> None:
        """That's the joke"""
        vid = "https://www.youtube.com/watch?v=xECUrlnXCqk"
        return await interaction.response.send_message(vid)


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(Memes(bot))
