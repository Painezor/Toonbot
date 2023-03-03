from __future__ import annotations

from discord.ext import commands

import typing
import discord

if typing.TYPE_CHECKING:
    from painezBot import PBot

DC = "https://media.discordapp.net/attachments/"
OVERMATCH = DC + "303154190362869761/990588535201484800/unknown.png"

# TODO: Overmatch DD
OM_BB = {
    13: ["Tier 5 Superstructure"],
    16: [
        "Tier 5 Superstructure",
        "Tier 2-3 Bow/Stern",
        "Tier 3-7 British Battlecruiser Bow/Stern",
    ],
    19: [
        "Tier 5 Bow/Stern",
        "All Superstructure",
        "Tier 3-7 British Battlecruiser Bow/Stern",
    ],
    25: [
        "Tier 5 Bow/Stern",
        "All Superstructure",
        (
            "Florida, Mackensen, Prinz Heinrich, Borodino\n"
            "Constellation, Slava Bow/Stern"
        ),
        "All UK BattleCruiser Bow/Stern",
    ],
    26: [
        "Tier 7 Bow/Stern",
        "All Superstructure",
        "Florida/Borodino/Constellation/Slava Bow/Stern",
        "UK BattleCruiser Bow/Stern",
    ],
    27: [
        "Tier 7 Bow/Stern",
        "All Superstructure",
        "Borodino/Constellation/Slava Bow/Stern",
        "UK BattleCruiser Bow/Stern",
        "German Battlecruiser Upper Bow/Stern",
    ],
    32: [
        "All Bow/Stern except German/Kremlin/Italian Icebreaker",
        "French/British Casemates",
        "Slava Deck",
    ],
}

OM_CA = {
    6: ["Tier 3 Plating"],
    10: ["Tier 3 Plating", "Tier 5 Superstructure"],
    13: [
        "Tier 5 Plating",
        "Tier 7 Most Superstructures",
        "Tier 7 Super light (127mms) plating",
    ],
    16: [
        "Tier 5 Plating",
        "Tier 7 Superstructure",
        "Tier 7 Bow/Stern (Except Pensacola/New Orleans/Yorck)",
        r"Tier \⭐ British CL/Smolensk plating",
        "127mm and below equipped super lights",
        "",
    ],
    19: [
        "Tier 7 CL Side plating",
        "All Superstructure",
        "Tier 7 Bow/Stern (Except Pensacola/New Orleans/Yorck). ",
        r"Tier \⭐ British CL/Smolensk plating",
        "127mm super lights plating",
    ],
    25: [
        "Tier 7 everywhere",
        "Tier 10 CL side plating",
        r"Tier \⭐ bow/stern (except US & German Heavy, and icebreakers)",
        r"Tier \⭐ British CL/Smolensk plating",
    ],
    27: [
        "Tier 9 decks",
        r"Tier \⭐ bow/stern",
        r"Tier \⭐ British CL/Smolensk plating",
    ],
    30: [r"Tier \⭐ Decks", r"Tier \⭐ bow/stern", r"Tier \⭐ plating"],
    32: [
        r"Tier \⭐ Decks",
        r"Tier \⭐ bow/stern",
        r"Tier \⭐ plating",
        "Austin/Jinan Casemate",
    ],
    35: [
        r"Tier \⭐ Decks",
        r"Tier \⭐ bow/stern",
        r"Tier \⭐ plating",
        "Austin/Jinan Casemate",
        "Riga Deck",
    ],
}


class OvrMatch(commands.Cog):
    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    om = discord.app_commands.Group(
        name="overmatch",
        description="Get information about shell/armour overmatch",
    )

    @om.command()
    @discord.app_commands.describe(shell_calibre="Calibre of shell (mm)")
    async def calibre(
        self, interaction: discord.Interaction[PBot], shell_calibre: int
    ) -> discord.InteractionMessage:
        """Get information about what a shell's overmatch parameters"""

        await interaction.response.defer(thinking=True)
        value = round(shell_calibre / 14.3)

        e = discord.Embed(colour=0x0BCDFB)
        e.title = f"{shell_calibre}mm Shells overmatch {value}mm of Armour"

        ca_om = "\n".join(OM_CA[max(i for i in OM_CA if i <= value)])

        if ca_om:
            e.add_field(name="Cruisers", value=ca_om, inline=False)

        bb_om = "\n".join(OM_BB[max(i for i in OM_BB if i <= value)])
        if bb_om:
            e.add_field(name="Battleships", value=bb_om, inline=False)

        e.set_thumbnail(url=OVERMATCH)
        e.set_footer(text=f"{shell_calibre}mm / 14.3 = {value}mm")
        return await self.bot.reply(interaction, embed=e)

    @om.command()
    @discord.app_commands.describe(armour_thickness="Thickness of armour (mm)")
    async def armour(
        self, interaction: discord.Interaction[PBot], armour_thickness: int
    ) -> discord.InteractionMessage:
        """Get what gun size is required to overmatch an armour thickness"""
        r = armour_thickness
        value = round(armour_thickness * 14.3)

        e = discord.Embed(colour=0x0BCDFB)
        e.title = f"{r}mm of Armour is overmatched by {value}mm Guns"

        om_ca = "\n".join(OM_CA[max(i for i in OM_CA if i <= r)])
        if om_ca:
            e.add_field(name="Cruisers", value=om_ca, inline=False)

        om_bb = "\n".join(OM_BB[max(i for i in OM_BB if i <= r)])
        if om_bb:
            e.add_field(name="Battleships", value=om_bb, inline=False)

        e.set_thumbnail(url=OVERMATCH)
        e.set_footer(text=f"{value}mm * 14.3 = {value}mm")
        return await interaction.edit_original_response(embed=e)


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(OvrMatch(bot))