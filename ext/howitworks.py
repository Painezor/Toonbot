"""Command for the "How it Works" Video Series"""
from __future__ import annotations
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]
    User: typing.TypeAlias = discord.User | discord.Member

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

    async def autocomplete(  # type: ignore
        self, _: Interaction, current: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Send matching choices"""
        options: list[discord.app_commands.Choice[str]] = []
        for k, val in sorted(HIW.items()):
            if current.lower() not in k:
                continue
            options.append(discord.app_commands.Choice(name=k, value=val))
        return options

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> str:
        """Get Value"""
        return value


class HowItWorks(view_utils.BaseView):
    """Video Browser"""

    def __init__(self, invoker: User):
        super().__init__(invoker, timeout=None)

    @discord.ui.select(placeholder="Change Video", options=opts)
    async def dropdown(
        self, interaction: Interaction, sel: discord.ui.Select[HowItWorks]
    ):
        """When the dropdown is clicked edit with new content"""
        value = sel.values[0]
        return await interaction.response.edit_message(content=value)


class HowItWorksCog(commands.Cog):
    """Browse the How It Works Video Series"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
    async def how_it_works(
        self,
        interaction: Interaction,
        video: discord.app_commands.Transform[str, HowItWorksTransformer],
    ) -> None:
        """Links to the various How It Works videos"""
        view = HowItWorks(interaction.user)
        await interaction.response.send_message(content=video, view=view)


async def setup(bot: PBot):
    """Load the How it Works Cog into the bot"""
    await bot.add_cog(HowItWorksCog(bot))
