"""Miscellaneous toys built for my own personal entertainment."""
from __future__ import annotations

from random import choice
from typing import TYPE_CHECKING

import discord
from discord import Interaction, Message, File
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from core import Bot


class Memes(Cog):
    """Various Toys for you to play with."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    memes = discord.app_commands.Group(name="memes", description="annoy your friends with dead jokes")

    @memes.command()
    async def dead(self, interaction: Interaction) -> Message:
        """STOP, STOP HE'S ALREADY DEAD"""
        return await self.bot.reply(interaction, content="https://www.youtube.com/watch?v=mAUY1J8KizU")

    @memes.command(name="f")
    async def press_f(self, interaction) -> Message:
        """Press F to pay respects"""
        return await self.bot.reply(interaction, content="https://i.imgur.com/zrNE05c.gif")

    @memes.command()
    async def helmet(self, interaction: Interaction) -> Message:
        """Helmet"""
        return await self.bot.reply(interaction, file=File(fp="Images/helmet.jpg"))

    @memes.command()
    async def lenny(self, interaction: Interaction) -> Message:
        """( ͡° ͜ʖ ͡°)"""
        lennys = ['( ͡° ͜ʖ ͡°)', '(ᴗ ͜ʖ ᴗ)', '(⟃ ͜ʖ ⟄) ', '(͠≖ ͜ʖ͠≖)', 'ʕ ͡° ʖ̯ ͡°ʔ', '( ͠° ͟ʖ ͡°)', '( ͡~ ͜ʖ ͡°)',
                  '( ͡◉ ͜ʖ ͡◉)', '( ͡° ͜V ͡°)', '( ͡ᵔ ͜ʖ ͡ᵔ )',
                  '(☭ ͜ʖ ☭)', '( ° ͜ʖ °)', '( ‾ ʖ̫ ‾)', '( ͡° ʖ̯ ͡°)', '( ͡° ل͜ ͡°)', '( ͠° ͟ʖ ͠°)', '( ͡o ͜ʖ ͡o)',
                  '( ͡☉ ͜ʖ ͡☉)', 'ʕ ͡° ͜ʖ ͡°ʔ', '( ͡° ͜ʖ ͡ °)']
        return await self.bot.reply(interaction, content=choice(lennys))

    @memes.command()
    async def thatsthejoke(self, interaction: Interaction) -> Message:
        """That's the joke"""
        return await self.bot.reply(interaction, content="https://www.youtube.com/watch?v=xECUrlnXCqk")


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(Memes(bot))