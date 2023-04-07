"""Command for the "How it Works" Video Series"""
from __future__ import annotations
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]

# TODO: Fetch YouTube Playlist via API?
HIW = {
    "In-Game Mechanics": "https://youtu.be/hFfBqjqQ-S8",
    "AA Guns & Fighters": "https://youtu.be/Dvrwz-1XhnM",
    "Armour": "https://youtu.be/yQcutrneBJQ",
    "Ballistics": "https://youtu.be/02pb8VS_mFo",
    "Carrier Gameplay": "https://youtu.be/qjyQVM2sGAo",
    "Consumables": "https://youtu.be/4XF44GsF2v4",
    "Credits & XP Modifiers": "https://youtu.be/KcRF3wNgzRk",
    "Dispersion": "https://youtu.be/AitjEbwtdUs",
    "Economy": "https://youtu.be/0_bXHAqLkKc",
    "Expenses": "https://youtu.be/v6lZE5XBMj0",
    "Fire": "https://youtu.be/AGEHZQsYzGE",
    "Flooding": "https://youtu.be/SCHNDox0BRM",
    "Game Basics": "https://youtu.be/Zl-lWGugzEo",
    "HE Shells": "https://youtu.be/B5GzyXj6oPM",
    "Hit Points": "https://youtu.be/Iusj8WJx5PQ",
    "Modules": "https://youtu.be/Z2JuRf-pnxY",
    "Repair Party": "https://youtu.be/mG1iSVIqmC4",
    "SAP Shells": "https://youtu.be/zZzlivBoP8s",
    "Spotting": "https://youtu.be/OgRUSmzcw2s",
    "Tips & Tricks": "https://youtu.be/tD9jaMrrY3I",
    "Torpedoes": "https://youtu.be/LPTgi20O15Q",
    "Upgrades": "https://youtu.be/zqwa9ZlzMA8",
}

opts = [
    discord.SelectOption(label=k, value=val) for k, val in sorted(HIW.items())
]


class HowItWorksTransformer(discord.app_commands.Transformer):
    """Convert user input to video url"""

    async def autocomplete(
        self, _: Interaction, current: str
    ) -> list[discord.app_commands.Choice]:
        """Send matching choices"""
        options = []
        for k, val in sorted(HIW.items()):
            if current.lower() not in k:
                continue
            options.append(discord.app_commands.Choice(name=k, value=val))
        return options

    async def transform(self, interaction: Interaction, value: str):
        """Get Value"""
        return value


class HowItWorks(view_utils.BaseView):
    """Video Browser"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(placeholder="Change Video", options=opts)
    async def callback(self, interaction: Interaction, sel: discord.ui.Select):
        value = sel.values[0]
        return await interaction.response.edit_message(content=value)


class HowItWorksCog(commands.Cog):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @discord.app_commands.command()
    async def how_it_works(
        self,
        interaction: Interaction,
        video: discord.app_commands.Transform[str, HowItWorksTransformer],
    ) -> None:
        """Links to the various How It Works videos"""
        view = HowItWorks()
        await interaction.response.send_message(content=video, view=view)


async def setup(bot: Bot):
    await bot.add_cog(HowItWorksCog(bot))
