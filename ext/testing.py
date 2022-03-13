"""Testing Cog for new commands."""
from asyncio import sleep

from discord import app_commands, Interaction
from discord.ext import commands


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command()
    @app_commands.guilds(250252535699341312)
    async def test(self, interaction: Interaction, stuff: str):
        await interaction.response.defer(thinking=True)
        await sleep(10)
        await interaction.edit_original_message(content=f"Hi yes it's been 10 seconds, here is {stuff}.")


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))
