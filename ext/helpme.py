"""SCREAMING INTENSIFIES"""
from __future__ import annotations

import typing

import discord
from discord.ext import commands

from ext.wows_api import Region

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]


BUILDS = "http://wo.ws/builds"
HELP_ME_DISC = "https://discord.gg/c4vK9rM"
HELP_ME_BIO = (
    f"The [Help Me Discord]({HELP_ME_DISC}) is full of helpful players from"
    "top level clans who donate their time to give advice and replay analysis"
    f"to those in need of it. \nYou can join by clicking [here]({HELP_ME_DISC}"
    ") or by using the button below."
)


ASLAIN = (
    "https://aslain.com/index.php?/topic/2020-download-%E2%98%85-world-o"
    "f-warships-%E2%98%85-modpack/"
)

MODSTATION = "https://worldofwarships.com/en/content/modstation/"
MOD_POLICY = "https://worldofwarships.com/en/news/general-news/mods-policy/"


DC = "https://media.discordapp.net/attachments/"
HELP_ME_LOGO = DC + "443846252019318804/992914761723433011/Logo_Discord2.png"

# Images
ARM_TH = "https://wows-static-production.gcdn.co/metashop/898c4bc5/armory.png"
INV_IMG = DC + "303154190362869761/991811092437274655/unknown.png"


HOW_IT_WORKS = (
    "https://wowsp-wows-eu.wgcdn.co/dcont/fb/image/tmb/2f4c2e32-43"
    "15-11e8-84e0-ac162d8bc1e4_1200x.jpg"
)

# In-Game Web Pages
ARMORY = "https://armory.worldofwarships.%%/en/"
DOCKYARD = "http://dockyard.worldofwarships.%%/en/"
INVENTORY = "https://warehouse.worldofwarships.%%"
LOGBOOK = "https://logbook.worldofwarships.%%/"
RECRUITING = "https://friends.worldofwarships.%%/en/players/"


def do_buttons(view: discord.ui.View, val: str) -> None:
    """Make region buttons"""
    btn: discord.ui.Button[discord.ui.View]
    for i in Region:
        btn = discord.ui.Button(url=val.replace("%%", i.domain), emoji=i.emote)
        btn.label = i.name
        view.add_item(btn)


class HelpMe(commands.Cog):
    """Commands Related to the HelpMe discord"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
    async def armory(self, interaction: Interaction) -> None:
        """Get a link to the web version of the in-game Armory"""
        embed = discord.Embed(title="World of Warships Armory")
        embed.description = "Access the armory for each region below"

        embed.set_thumbnail(url=ARM_TH)
        embed.colour = discord.Colour.orange()

        view = discord.ui.View()
        do_buttons(view, ARMORY)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def builds(self, interaction: Interaction) -> None:
        """The Help Me Build collection"""
        await interaction.response.defer(thinking=True)
        embed = discord.Embed(title="Help Me Builds", colour=0xAE8A6D)
        embed.description = (
            f"The folks from the [Help Me Discord]({HELP_ME_DISC})"
            f" have compiled a list of recommended builds, you can find"
            f" them [here]({BUILDS}) or by using the button below."
        )
        embed.set_thumbnail(url=HELP_ME_LOGO)
        btn: discord.ui.Button[discord.ui.View] = discord.ui.Button(url=BUILDS)
        btn.label = "Help Me Builds on Google Docs"
        view = discord.ui.View().add_item(btn)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def dockyard(self, interaction: Interaction) -> None:
        """Get a link to the web version of the in-game dockyard"""
        embed = discord.Embed(title="Dockyard")
        embed.description = "Access your region's dockyard below."
        embed.colour = discord.Colour.dark_orange()
        view = discord.ui.View()
        do_buttons(view, DOCKYARD)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def guides(self, interaction: Interaction) -> None:
        """Yurra's collection of guides"""
        txt = (
            "Yurra's guides contain advice on various game mechanics, play "
            "styles, classes, tech tree branches, and some specific ships."
            "\n\nhttps://bit.ly/yurraguides"
        )
        embed = discord.Embed(title="Yurra's guides", description=txt)
        embed.url = "https://bit.ly/yurraguides"

        yurra = self.bot.get_user(192601340244000769)
        if yurra:
            embed.set_author(
                name=f"{yurra}", icon_url=yurra.display_avatar.url
            )
        embed.colour = discord.Colour.dark_orange()
        btn: discord.ui.Button[discord.ui.View]
        btn = discord.ui.Button(url="https://bit.ly/yurraguides")
        btn.label = "Yurra's guides"
        view = discord.ui.View().add_item(btn)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def help_me(self, interaction: Interaction) -> None:
        """Help me Discord info"""
        embed = discord.Embed(title="Help Me Discord", colour=0xAE8A6D)
        embed.description = HELP_ME_BIO
        embed.set_thumbnail(url=HELP_ME_LOGO)
        btn: discord.ui.Button[discord.ui.View]
        btn = discord.ui.Button(url=HELP_ME_DISC, label="Help Me Discord")
        view = discord.ui.View().add_item(btn)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def inventory(self, interaction: Interaction) -> None:
        """Get a link to the web version of the in-game Inventory"""
        embed = discord.Embed(title="World of Warships Inventory")
        embed.colour = discord.Colour.lighter_grey()
        embed.description = "Manage & sell your unused modules/camos/etc below"
        embed.set_thumbnail(url=INV_IMG)

        view = discord.ui.View()
        do_buttons(view, INVENTORY)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def logbook(self, interaction: Interaction) -> None:
        """Get a link to the web version of the in-game Captain's Logbook"""
        embed = discord.Embed(title="Captain's Logbook")
        embed.description = "Access your region's logbook below."

        img = DC + "303154190362869761/991811398952816790/unknown.png"
        embed.set_thumbnail(url=img)
        embed.colour = discord.Colour.dark_orange()

        view = discord.ui.View()
        do_buttons(view, LOGBOOK)
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def mods(self, interaction: Interaction) -> None:
        """information about where to get World of Warships modifications"""
        embed = discord.Embed(colour=discord.Colour.red())
        embed.set_thumbnail(url="http://i.imgur.com/2LiednG.jpg")
        embed.title = "World of Warships Mods"
        embed.description = (
            "There are two official sources available for in-game"
            f" modifications.\n • [Modstation]({MODSTATION})\n"
            f"• Official Forum\n\n [Aslain's Modpack]({ASLAIN}) "
            "is a popular third party compilation of mods"
            " available from the official forum\n"
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(url=MODSTATION, label="Modstation"))
        view.add_item(discord.ui.Button(url=ASLAIN, label="Aslain's Modpack"))
        view.add_item(discord.ui.Button(url=MOD_POLICY, label="Mod Policy"))
        return await interaction.response.send_message(embed=embed, view=view)

    @discord.app_commands.command()
    async def recruiting_station(self, interaction: Interaction) -> None:
        """Get a link to the recruiting station"""
        embed = discord.Embed(title="Recruiting Station")
        embed.description = "Access your region's referrals below."
        embed.colour = discord.Colour.dark_orange()
        view = discord.ui.View()
        do_buttons(view, RECRUITING)
        return await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(HelpMe(bot))
