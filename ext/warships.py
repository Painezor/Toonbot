"""Private world of warships related commands"""
import datetime
import os

import discord
from PIL import Image
from discord.ext import commands

targets = ["andejay", "andy_the_cupid_stunt", "chaosmachinegr", "Charede", "darknessdreams_1"
                                                                           "DobbyM8", "frostinator08", "GameProdigy",
           "Jamdearest", "KidneyCowboy", "Lord_Zath", "Masterchief1567",
           "nebelfuss", "painezor", "Pelzmorph", "pops_place", "Redberen", "SeaRaptor00", "song_mg", "spacepickshovel",
           "StatsBloke", "tcfreer", "texashula", "the_shadewe", "thegrumpybeard", "TigersDen", "wookie_legend",
           "Xairen", "Yuzral"]


# TODO: Get appropriate perms.


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

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🚢"
        self.now_live_cache = {}

    @commands.command()
    @commands.is_owner()
    async def codes(self, ctx, *, codes):
        """Strip codes for world of warships"""
        codes = codes.replace(';', '')
        codes = codes.split('|')
        codes = "\n".join([i.strip() for i in codes if i])

        await self.bot.reply(ctx, f"```\n{codes}```")

    async def on_presence_update(self, before, after):
        """Apply hoisted role to streamers when they go live."""
        # Check if this guild is tracking streaming status changes, grab row.:
        try:
            row = self.now_live_cache[before.guild.id]
        except KeyError:
            return

        # Check if member has either started, or stopped streaming.
        if not [before.activity, after.activity].count(discord.ActivityType.streaming) == 1:
            return

        # Only output notifications for those users who are being intentionally tracked on the server.
        base_role = row["base_role"]
        if base_role not in [i.id for i in after.roles]:
            return

        now_live_role = row["now_live_role"]

        # If User is no longer live, de-hoist them.
        if before.activity == discord.ActivityType.streaming:
            return await after.remove_roles([now_live_role])

        # Else If user is GOING live.
        await after.add_roles([now_live_role])
        ch = self.bot.get_channel(row['announcement_channel'])

        # Only output if channel exists.
        if ch is None:
            return

        activity = after.activity

        # Build embeds.
        e = discord.Embed()
        if activity.platform.lower() == "twitch":
            name = f"Twitch: {activity.twitch_name}"
            e.colour = 0x6441A4
        else:
            e.colour = discord.Colour.red() if activity.platform.lower() == "youtube" else discord.Colour.og_blurple()
            name = f"{activity.platform}: {after.name}"
        e.set_author(name=name, url=activity.url)
        e.title = activity.game

        e.description = f"**[{after.mention} just went live]({activity.url})**\n\n{activity.name}"
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        e.set_thumbnail(url=after.display_avatar.url)

        await ch.send(embed=e)

    @commands.command()
    @commands.is_owner()
    async def twitch(self, ctx):
        """Test command for twitch embeds"""
        e = discord.Embed()
        e.title = "World of Warships"
        e.set_author(name="Twitch: Painezor", url="http://www.twitch.tv/Painezor")
        e.colour = 0x6441A4
        tw = "http://www.twitch.tv/Painezor"
        e.description = f"[**{ctx.guild.get_member(ctx.bot.owner_id).mention} just went live!**]({tw})\n"
        e.description += "\nGold League Ranked & Regrinding Destroyers!"
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        url = ctx.guild.get_member(ctx.bot.owner_id).display_avatar.url
        e.set_thumbnail(url=url)

        await self.bot.reply(ctx, tw, embed=e)


def setup(bot):
    """Load the cog into the bot"""
    bot.add_cog(Warships(bot))
