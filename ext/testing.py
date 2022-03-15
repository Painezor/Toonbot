"""Testing Cog for new commands."""
from asyncio import sleep

from discord import app_commands, Interaction, Object
from discord.ext import commands


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_load(self):
        """Sync Test Guild Cogs"""
        await self.bot.tree.sync(guild=Object(id=250252535699341312))

    async def st_ac(self, interaction, current, namespace):
        print(namespace.__dict__)
        print(namespace.__repr__)
        return [app_commands.Choice(name="foo", value="foo"), app_commands.Choice(name="bar", value="bar")]

    @app_commands.command()
    @app_commands.guilds(250252535699341312)
    @app_commands.autocomplete(stuff=st_ac)
    async def test(self, interaction: Interaction, a: str, stuff: str):
        await interaction.response.defer(thinking=True)
        await sleep(10)
        await interaction.edit_original_message(content=f"Hi yes it's been 10 seconds, here is {stuff}.")


async def setup(bot):
    """Add the testing cog to the bot"""
    await bot.add_cog(Test(bot))
