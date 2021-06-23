"""Private world of warships related commands"""
import os

from PIL import Image
from discord.ext import commands

targets = ["andejay", "andy_the_cupid_stunt", "chaosmachinegr", "Charede", "darknessdreams_1"
                                                                           "DobbyM8", "frostinator08", "GameProdigy",
           "Jamdearest", "KidneyCowboy", "Lord_Zath", "Masterchief1567",
           "nebelfuss", "painezor", "Pelzmorph", "pops_place", "Redberen", "SeaRaptor00", "song_mg", "spacepickshovel",
           "StatsBloke", "tcfreer", "texashula", "the_shadewe", "thegrumpybeard", "TigersDen", "wookie_legend",
           "Xairen", "Yuzral"]


def make_bauble(img):
    """Make a single bauble"""
    # Open Avatar file.
    avatar = Image.open(r"F:/Logos/" + img).convert(mode="RGBA")

    # Create Canvas & Paste Avatar
    canvas = Image.new("RGBA", (300, 350), (0, 0, 0, 255))
    canvas.paste(avatar, (0, 50))

    # Apply Bauble mask.
    msk = Image.open("images/Bauble_MASK.png").convert('L')
    canvas.putalpha(msk)

    # Apply bauble top overlay
    bauble_top = Image.open("images/BaubleTop.png").convert(mode="RGBA")
    canvas.paste(bauble_top, mask=bauble_top)

    output_loc = r"F:/Logo-Output/" + img.split('.')[0]
    canvas.save(output_loc + ".png")


def bulk_image():
    """Batch Export Baubles"""
    directory = r'F:\Logos'
    for img in os.listdir(directory):
        make_bauble(img)


class Warships(commands.Cog):
    """World of Warships related commands"""

    def __init(self, bot):
        self.bot = bot

    @commands.command()
    @commands.is_owner()
    async def codes(self, ctx, *, input_string):
        """Strip codes for world of warships"""
        out = input_string.replace(';', '').replace('|', ',').strip(' ;,')
        await self.bot.reply(ctx, f"```{out}```")


def setup(bot):
    """Load the cog into the bot"""
    bot.add_cog(bot)
