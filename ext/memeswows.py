"""Memes related to world of warships"""
from __future__ import annotations

import typing

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]


RAGNAR = (
    "Ragnar is inherently underpowered. It lacks the necessary"
    "attributes to make meaningful impact on match result. No burst "
    "damage to speak of, split turrets, and yet still retains a fragile "
    "platform. I would take 1 Conqueror..Thunderer or 1 DM or even 1 of "
    "just about any CA over 2 Ragnars on my team any day of the week. "
    "Now... If WG gave it the specialized repair party of the "
    "Nestrashimy ( and 1 more base charge)... And maybe a few more "
    "thousand HP if could make up for where it is seriously lacking with"
    " longevity"
)


class MemesWows(commands.Cog):
    """World of Warships related memes"""

    def __init__(self, bot: PBot) -> None:
        self.bot = bot

    @discord.app_commands.command()
    async def ragnar(self, interaction: Interaction) -> None:
        """Ragnar is inherently underpowered"""
        await interaction.response.defer(thinking=True)
        return await interaction.response.send_message(content=RAGNAR)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(MemesWows(bot))
