"""SCREAMING INTENSIFIES"""
from __future__ import annotations

import typing

import discord
from discord.ext import commands

from ext.painezbot_utils.region import Region

if typing.TYPE_CHECKING:
    from painezBot import PBot


BUILDS = "http://wo.ws/builds"
HELP_ME_DISC = "https://discord.gg/c4vK9rM"
HELP_ME_BIO = f"""The [Help Me Discord]({HELP_ME_DISC}) is full of helpful play
ers from top level clans who donate their time to give advice and replay analys
is to those in need of it. \nYou can join by clicking [here]({HELP_ME_DISC}) or
 by using the button below."""


ASLAIN = """https://aslain.com/index.php?/topic/2020-download-%E2%98%85-world-o
f-warships-%E2%98%85-modpack/"""

MODSTATION = "https://worldofwarships.com/en/content/modstation/"
MOD_POLICY = "https://worldofwarships.com/en/news/general-news/mods-policy/"


DC = "https://media.discordapp.net/attachments/"
HELP_ME_LOGO = DC + "443846252019318804/992914761723433011/Logo_Discord2.png"

# Images
ARMORY = "https://wows-static-production.gcdn.co/metashop/898c4bc5/armory.png"
INVENTORY = DC + "303154190362869761/991811092437274655/unknown.png"


HOW_IT_WORKS = """https://wowsp-wows-eu.wgcdn.co/dcont/fb/image/tmb/2f4c2e32-43
15-11e8-84e0-ac162d8bc1e4_1200x.jpg"""


def do_buttons(view: discord.ui.View, attr: str) -> None:

    for region in Region:
        btn = discord.ui.Button(url=getattr(region, attr), emoji=region.emote)
        btn.style = discord.ButtonStyle.url
        btn.label = region.name
        view.add_item(btn)


class HelpMe(commands.Cog):
    """Commands Related to the HelpMe discord"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    @discord.app_commands.command()
    async def guides(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """Yurra's collection of guides"""

        await interaction.response.defer(thinking=True)

        txt = (
            "Yurra's guides contain advice on various game mechanics, play "
            "styles classes, tech tree branches, and some specific ships."
            "\n\nhttps://bit.ly/yurraguides"
        )
        e = discord.Embed(title="Yurra's guides", description=txt)
        e.url = "https://bit.ly/yurraguides"

        yurra = self.bot.get_user(192601340244000769)
        if yurra:
            e.set_author(name=f"{yurra}", icon_url=yurra.display_avatar.url)
        e.colour = discord.Colour.dark_orange()

        btn = discord.ui.Button(label="Yurra's guides")
        btn.style = discord.ButtonStyle.url
        btn.url = "https://bit.ly/yurraguides"

        v = discord.ui.View().add_item(btn)
        return await interaction.edit_original_response(embed=e, view=v)

    @discord.app_commands.command()
    async def help_me(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """Help me Discord info"""
        await interaction.response.defer(thinking=True)
        e = discord.Embed(title="Help Me Discord", colour=0xAE8A6D)
        e.description = HELP_ME_BIO
        e.set_thumbnail(url=HELP_ME_LOGO)
        btn = discord.ui.Button(url=HELP_ME_DISC, label="Help Me Discord")
        v = discord.ui.View().add_item(btn)
        return await interaction.edit_original_response(embed=e, view=v)

    @discord.app_commands.command()
    async def armory(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """Get a link to the web version of the in-game Armory"""
        await interaction.response.defer(thinking=True)

        e = discord.Embed(title="World of Warships Armory")
        e.description = "Access the armory for each region below"

        e.set_thumbnail(url=ARMORY)
        e.colour = discord.Colour.orange()

        v = discord.ui.View()
        do_buttons(v, "armory")
        return await interaction.edit_original_response(embed=e, view=v)

    @discord.app_commands.command()
    async def inventory(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """Get a link to the web version of the in-game Inventory"""
        e = discord.Embed(title="World of Warships Inventory")
        e.colour = discord.Colour.lighter_grey()
        e.description = "Manage & sell your unused modules/camos/etc below"
        e.set_thumbnail(url=INVENTORY)

        v = discord.ui.View()
        do_buttons(v, "inventory")
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def logbook(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """Get a link to the web version of the in-game Captain's Logbook"""
        e = discord.Embed(
            title="World of Warships Captain's Logbook",
            description="Access your region's logbook below.",
        )

        img = (
            HELP_ME_DISC + "303154190362869761/991811398952816790/unknown.png"
        )
        e.set_thumbnail(url=img)
        e.colour = discord.Colour.dark_orange()

        v = discord.ui.View()
        do_buttons(v, "logbook")
        return await self.bot.reply(interaction, embed=e, view=v)

    # TODO: Make this into a view.
    @discord.app_commands.command()
    async def how_it_works(
        self, interaction: discord.Interaction[PBot]
    ) -> None:
        """Links to the various How It Works videos"""
        e = discord.Embed(
            title="How it Works Video Series", colour=discord.Colour.dark_red()
        )
        e.description = (
            "The how it works video series give comprehensive overviews of "
            "some of the game's mechanics, you can find links to them all "
            "below\n\n**Latest Video**: "
            "[In-Game Mechanics](https://youtu.be/hFfBqjqQ-S8)\n\n"
            + ", ".join(
                [
                    "[AA Guns & Fighters](https://youtu.be/Dvrwz-1XhnM)",
                    "[Armour](https://youtu.be/yQcutrneBJQ)",
                    "[Ballistics](https://youtu.be/02pb8VS_mFo)",
                    "[Carrier Gameplay](https://youtu.be/qjyQVM2sGAo)",
                    "[Consumables](https://youtu.be/4XF44GsF2v4)",
                    "[Credits & XP Modifiers](https://youtu.be/KcRF3wNgzRk)",
                    "[Dispersion](https://youtu.be/AitjEbwtdUs)",
                    "[Economy](https://youtu.be/0_bXHAqLkKc)",
                    "[Expenses](https://youtu.be/v6lZE5XBMj0)",
                    "[Fire](https://youtu.be/AGEHZQsYzGE)",
                    "[Flooding](https://youtu.be/SCHNDox0BRM)",
                    "[Game Basics](https://youtu.be/Zl-lWGugzEo)",
                    "[HE Shells](https://youtu.be/B5GzyXj6oPM)",
                    "[Hit Points](https://youtu.be/Iusj8WJx5PQ)",
                    "[Modules](https://youtu.be/Z2JuRf-pnxY)",
                    "[Repair Party](https://youtu.be/mG1iSVIqmC4)",
                    "[SAP Shells](https://youtu.be/zZzlivBoP8s)",
                    "[Spotting](https://youtu.be/OgRUSmzcw2s)",
                    "[Tips & Tricks](https://youtu.be/tD9jaMrrY3I)",
                    "[Torpedoes](https://youtu.be/LPTgi20O15Q)",
                    "[Upgrades](https://youtu.be/zqwa9ZlzMA8)",
                ]
            )
        )
        e.set_thumbnail(url=HOW_IT_WORKS)
        await self.bot.reply(interaction, embed=e)

    @discord.app_commands.command()
    async def mods(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """information about where to get World of Warships modifications"""
        e = discord.Embed(colour=discord.Colour.red())
        e.set_thumbnail(url="http://i.imgur.com/2LiednG.jpg")
        e.title = "World of Warships Mods"
        e.description = (
            "There are two official sources available for in-game"
            f"modifications.\n • [Modstation]({MODSTATION})\n"
            f"• Official Forum\n\n [Aslain's Modpack]({ASLAIN}) "
            "is a popular third party compilation of mods"
            " available from the official forum\n"
        )
        e.add_field(name="Mod Policy", value=MOD_POLICY)
        v = discord.ui.View()
        v.add_item(discord.ui.Button(url=MODSTATION, label="Modstation"))
        v.add_item(discord.ui.Button(url=ASLAIN, label="Aslain's Modpack"))
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def builds(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """The Help Me Build collection"""
        await interaction.response.defer(thinking=True)
        e = discord.Embed(title="Help Me Builds", colour=0xAE8A6D)
        e.description = (
            f"The folks from the [Help Me Discord]({HELP_ME_DISC})"
            f" have compiled a list of recommended builds, you can find"
            f" them, [here]({BUILDS}) or by using the button below."
        )
        e.set_thumbnail(url=HELP_ME_LOGO)

        btn = discord.ui.Button(url=BUILDS)
        btn.label = "Help Me Builds on Google Docs"
        v = discord.ui.View().add_item(btn)
        return await self.bot.reply(interaction, embed=e, view=v)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(HelpMe(bot))