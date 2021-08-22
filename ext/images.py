import json
import random
import textwrap
import typing
from io import BytesIO

import discord
from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from ext.utils import embed_utils

KNOB_ICON = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/86/18_icon_TV_%28Hungary%29.svg" \
            "/48px-18_icon_TV_%28Hungary%29.svg.png"

# TODO: Select / Button Pass.

def draw_tinder(image, av, name):
    """Draw Images for the tinder command"""
    # Base Image
    im = Image.open("Images/tinder.png").convert(mode="RGBA")
    # Prepare mask
    msk = Image.open("Images/circlemask.png").convert('L')
    msk = ImageOps.fit(msk, (185, 185))
    
    # User Avatar
    avt = Image.open(BytesIO(av)).convert(mode="RGBA")
    avo = ImageOps.fit(avt, (185, 185))
    avo.putalpha(msk)
    im.paste(avo, box=(100, 223, 285, 408), mask=msk)
    
    # Player
    user_av = Image.open(BytesIO(image)).convert(mode="RGBA")
    plo = ImageOps.fit(user_av, (185, 185), centering=(0.5, 0.0))
    plo.putalpha(msk)
    im.paste(plo, box=(313, 223, 498, 408), mask=msk)
    # Write "it's a mutual match"
    txt = f"You and {name} have liked each other."
    f = ImageFont.truetype('Whitney-Medium.ttf', 24)
    w, h = f.getsize(txt)
    d = ImageDraw.Draw(im)
    d.text((300 - w / 2, 180), txt, font=f, fill="#ffffff")

    output = BytesIO()
    im.save(output, "PNG")
    output.seek(0)
    return output


def draw_bob(image, response):
    """Pillow Bob Rossifying"""
    im = Image.open(BytesIO(image)).convert(mode="RGBA")
    bob = Image.open("Images/rossface.png")
    for coords in response:
        x = int(coords["faceRectangle"]["left"])
        y = int(coords["faceRectangle"]["top"])
        w = int(coords["faceRectangle"]["width"])
        h = int(coords["faceRectangle"]["height"])
        roll = int(coords["faceAttributes"]["headPose"]["roll"]) * -1
        vara = int(x - (w / 4))
        varb = int(y - (h / 2))
        varc = int(x + (w * 1.25))
        vard = int((y + (h * 1.25)))
        xsize = varc - vara
        ysize = vard - varb
        thisbob = ImageOps.fit(bob, (xsize, ysize)).rotate(roll)
        im.paste(thisbob, box=(vara, varb, varc, vard), mask=thisbob)
    output = BytesIO()
    im.save(output, "PNG")
    output.seek(0)
    return output


def draw_knob(image, response):
    """Draw a knob in someone's mouth for the knob command"""
    im = Image.open(BytesIO(image)).convert(mode="RGBA")
    knob = Image.open("Images/knob.png")
    
    for coords in response:
        mlx = int(coords["faceLandmarks"]["mouthLeft"]["x"])
        mrx = int(coords["faceLandmarks"]["mouthRight"]["x"])
        lipy = int(coords["faceLandmarks"]["upperLipBottom"]["y"])
        lipx = int(coords["faceLandmarks"]["upperLipBottom"]["x"])
        
        angle = int(coords["faceAttributes"]["headPose"]["roll"] * -1)
        w = int((mrx - mlx)) * 2
        h = w
        tk = ImageOps.fit(knob, (w, h)).rotate(angle)
        im.paste(tk, box=(int(lipx - w / 2), int(lipy)), mask=tk)
    output = BytesIO()
    im.save(output, "PNG")
    output.seek(0)
    return output


def draw_eyes(image, response):
    """Draws the eyes"""
    im = Image.open(BytesIO(image))
    for i in response:
        # Get eye bounds
        lix = int(i["faceLandmarks"]["eyeLeftInner"]["x"])
        lox = int(i["faceLandmarks"]["eyeLeftOuter"]["x"])
        lty = int(i["faceLandmarks"]["eyeLeftTop"]["y"])
        # lby = int(i["faceLandmarks"]["eyeLeftBottom"]["y"])
        rox = int(i["faceLandmarks"]["eyeRightOuter"]["x"])
        rix = int(i["faceLandmarks"]["eyeRightInner"]["x"])
        rty = int(i["faceLandmarks"]["eyeRightTop"]["y"])
        # rby = int(i["faceLandmarks"]["eyeRightBottom"]["y"])

        lw = lix - lox
        rw = rox - rix

        # Inflate
        lix += lw
        lox -= lw
        lty -= lw
        # lby = lby + lw
        rox += rw
        rix -= rw
        rty -= rw
        # rby = rby + rw

        # Recalculate with new sizes.
        lw = lix - lox
        rw = rox - rix

        # Open Eye Image, resize, paste twice
        eye = Image.open("Images/eye.png")
        left = ImageOps.fit(eye, (lw, lw))
        right = ImageOps.fit(eye, (rw, rw))
        im.paste(left, box=(lox, lty), mask=left)
        im.paste(right, box=(rix, rty), mask=right)
    
    # Prepare for sending and return
    output = BytesIO()
    im.save(output, "PNG")
    output.seek(0)
    return output


def draw_tard(image, quote):
    """Draws the "it's retarded" image"""
    # Open Files
    im = Image.open(BytesIO(image))
    base = Image.open("Images/retardedbase.png")
    msk = Image.open("Images/circlemask.png").convert('L')
    
    # Resize avatar, make circle, paste
    ops = ImageOps.fit(im, (250, 250))
    ops.putalpha(msk)
    smallmsk = msk.resize((35, 40))
    small = ops.resize((35, 40))
    largemsk = msk.resize((100, 100))
    large = ops.resize((100, 100)).rotate(-20)
    base.paste(small, box=(175, 160, 210, 200), mask=smallmsk)
    base.paste(large, box=(325, 90, 425, 190), mask=largemsk)
    
    # Drawing tex
    d = ImageDraw.Draw(base)
    
    # Get best size for text
    def get_first_size(quote_text):
        """Measure font and shrink it to appropriate size."""
        font_size = 72
        ttf = 'Whitney-Medium.ttf'
        ftsz = ImageFont.truetype(ttf, font_size)
        width = 300
        quote_text = textwrap.fill(quote_text, width=width)
        while font_size > 0:
            # Make lines thinner if too wide.
            while width > 1:
                if ftsz.getsize(quote_text)[0] < 237 and ftsz.getsize(quote)[1] < 89:
                    return width, ftsz
                width -= 1
                quote_text = textwrap.fill(quote, width=width)
                ftsz = ImageFont.truetype(ttf, font_size)
            font_size -= 1
            ftsz = ImageFont.truetype(ttf, font_size)
            width = 40

    wid, font = get_first_size(quote)
    quote = textwrap.fill(quote, width=wid)
    # Write lines.
    moveup = font.getsize(quote)[1]
    d.text((245, (80 - moveup)), quote, font=font, fill="#000000")
    
    # Prepare for sending
    output = BytesIO()
    base.save(output, "PNG")
    output.seek(0)
    return output


def ruin(image):
    """Generates the Image"""
    im = Image.open(BytesIO(image))
    base = Image.open("Images/localman.png")
    ops = ImageOps.fit(im, (256, 256))
    base.paste(ops, box=(175, 284, 431, 540))
    output = BytesIO()
    base.save(output, "PNG")
    output.seek(0)
    return output


async def get_faces(ctx, target):
    """Retrieve face features from Project Oxford"""
    if target is None:
        await ctx.bot.reply(ctx, text="No target specified.")
        return None, None, None

    if isinstance(target, discord.Member):
        target = target.avatar.with_format("png").url
    elif isinstance(target, discord.Attachment):
        target = target.url
    elif "://" not in target:
        await ctx.bot.reply(ctx, text=f"{target} doesn't look like a valid url.")
        return None, None, None

    # Prepare POST
    h = {"Content-Type": "application/json", "Ocp-Apim-Subscription-Key": ctx.bot.credentials['Oxford']['OxfordKey']}
    p = {"returnFaceId": "False", "returnFaceLandmarks": "True", "returnFaceAttributes": "headPose"}
    d = json.dumps({"url": target})
    url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

    # Get Project Oxford reply
    async with ctx.bot.session.post(url, params=p, headers=h, data=d) as resp:
        if resp.status == 400:
            await ctx.bot.reply(ctx, text=await resp.json())
            return False, False, False
        elif resp.status != 200:
            await ctx.bot.reply(ctx, text=f"HTTP Error {resp.status} accessing facial recognition API.")
            return None, None, None
        response = await resp.json()
    
    # Get target image as file
    async with ctx.bot.session.get(target) as resp:
        if resp.status != 200:
            await ctx.bot.reply(ctx, text=f"{resp.status} code accessing project oxford.")
        image = await resp.content.read()
    return image, response, target


# TODO: XKCD Command. https://xkcd.com/json.html


class Images(commands.Cog):
    """Image manipulation commands"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🖼️"

    @commands.command(hidden=True)
    @commands.cooldown(2, 90, BucketType.user)
    async def tinder(self, ctx):
        """Try to Find your next date."""
        with ctx.typing():
            if ctx.author.id == 272722118192529409:
                return await self.bot.reply(ctx, text="Nobody will ever swipe right on you, Kegs.", ping=True)
            match = random.choice([True, False, False])
            if not match:
                return await self.bot.reply(ctx, text="Nobody swiped right on you.")

            av = await ctx.author.avatar.with_format("png").read()
            match = random.choice(ctx.guild.members)
            # TODO: Get presence intents.
            # match = random.choice([i for i in ctx.guild.members if str(i.status) != "offline"])
            name = match.display_name

            target = await match.avatar.with_format("png").read()
            output = await self.bot.loop.run_in_executor(None, draw_tinder, target, av, name)
            if match == ctx.author:
                caption = f"{ctx.author.mention} matched with themself, How pathetic."
            elif match == ctx.me:
                caption = f"{ctx.author.mention} Fancy a shag?"
            else:
                caption = f"{ctx.author.mention} matched with {match.mention}"
            icon = "https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/512/tinder-512.png"
            base_embed = discord.Embed()
            base_embed.description = caption
            base_embed.colour = 0xFD297B
            base_embed.set_author(name=ctx.invoked_with, icon_url=icon)
            base_embed.description = caption
            await embed_utils.embed_image(ctx, base_embed, output, filename="Tinder.png")

    @commands.command(aliases=["bob", "ross"], usage='<@user, link to image, or upload a file>')
    async def bobross(self, ctx, *, target: typing.Union[discord.Member, str] = None):
        """Bob Rossify"""
        if target is None:
            try:
                target = ctx.message.attachments[0]
            except IndexError:
                return await self.bot.reply(ctx, '🚫 Provide an image, link, or user.')
        
        image, response, target = await get_faces(ctx, target)
        
        if response is None or response is False:
            return await self.bot.reply(ctx, text="🚫 No faces were detected in your image.", ping=True)

        image = await self.bot.loop.run_in_executor(None, draw_bob, image, response)
        icon = "https://cdn4.vectorstock.com/i/thumb-large/79/33/painting-icon-image-vector-14647933.jpg"

        base_embed = discord.Embed()
        base_embed.colour = 0xb4b2a7  # titanium h-white
        base_embed.set_author(name=ctx.invoked_with, icon_url=icon)
        base_embed.description = ctx.author.mention
        base_embed.add_field(name="Source", value=target)
        await embed_utils.embed_image(ctx, base_embed, image, filename="bobross.png")

    # @commands.is_nsfw()
    # @commands.command(usage='<@user, link to image, or upload a file>')
    # async def knob(self, ctx, *, target: typing.Union[discord.Member, str] = None):
    #     """Draw knobs in mouth on an image. Mention a user to use their avatar. Only works for human faces."""
    #     image, response, target = await get_faces(ctx, target)
    #
    #     if response is None or response is False:
    #         return await self.bot.reply(ctx, text="🚫 No faces were detected in your image.", ping=True)
    #
    #     image = await self.bot.loop.run_in_executor(None, draw_knob, image, response)
    #
    #     base_embed = discord.Embed()
    #     base_embed.colour = 0xff66cc
    #     base_embed.set_author(name=ctx.invoked_with, icon_url=KNOB_ICON)
    #     base_embed.description = ctx.author.mention
    #     base_embed.add_field(name="Source", value=target)
    #     await embed_utils.embed_image(ctx, base_embed, image, filename="Knob.png")

    @commands.command(usage='<@user, link to image, or upload a file>')
    async def eyes(self, ctx, *, target: typing.Union[discord.Member, str] = None):
        """Draw Googly eyes on an image. Mention a user to use their avatar. Only works for human faces."""
        image, response, target = await get_faces(ctx, target)

        if response is None:
            return await self.bot.reply(ctx, text="🚫 No faces were detected in your image.", ping=True)
        elif response is False:
            return
        
        image = await self.bot.loop.run_in_executor(None, draw_eyes, image, response)
        icon = "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/120/microsoft/209/eyes_1f440.png"
        
        base_embed = discord.Embed()
        base_embed.colour = 0xFFFFFF
        base_embed.set_author(name=ctx.invoked_with, icon_url=icon)
        base_embed.description = ctx.author.mention
        base_embed.add_field(name="Source", value=target)
        await embed_utils.embed_image(ctx, base_embed, image, filename="eyes.png")

    @commands.command(usage='<@user> <quote>', hidden=True)
    async def tard(self, ctx, target: discord.Member, *, quote):
        """Generate an "oh no, it's retarded" image with a user's avatar and a quote"""
        if target.id == 210582977493598208:
            target = ctx.author

        image = target.avatar.with_format("png").read()
        image = await self.bot.loop.run_in_executor(None, draw_tard, image, quote)

        base_embed = discord.Embed()
        base_embed.colour = discord.Colour.blue()
        base_embed.set_author(name=ctx.invoked_with)
        base_embed.description = ctx.author.mention
        await embed_utils.embed_image(ctx, base_embed, image, filename="tard.png")
        await self.bot.reply(ctx, "no u")
            
    @tard.error
    async def tard_error(self, ctx, exc):
        """Handle errors for the tard command"""
        if isinstance(exc, commands.BadArgument):
            return await self.bot.reply(ctx, text="🚫 Bad argument provided: Pinging a user or use their ID",
                                        ping=True)

    @commands.command(aliases=["localman", "local", "ruin"], usage="[@member or leave blank to use yourself.]")
    async def ruins(self, ctx, *, target: discord.Member = None):
        """Local man ruins everything"""
        with ctx.typing():
            if target is None:
                target = ctx.author
            av = await target.avatar.with_format("png").read()
            image = await self.bot.loop.run_in_executor(None, ruin, av)

            base_embed = discord.Embed()
            base_embed.colour = discord.Colour.blue()
            base_embed.set_author(name=ctx.invoked_with)
            base_embed.description = ctx.author.mention
            await embed_utils.embed_image(ctx, base_embed, image, filename=f"{target}_ruins_everything.png")

    @commands.command(hidden=True)
    async def butter(self, ctx):
        """What is my purpose?"""
        await self.bot.reply(ctx, image="Images/butter.png")
    
    @commands.command(hidden=True)
    async def fixed(self, ctx):
        """Fixed!"""
        await self.bot.reply(ctx, image="Images/fixed.png")

    @commands.command(hidden=True)
    async def ructions(self, ctx):
        """WEW. RUCTIONS."""
        await self.bot.reply(ctx, image="Images/ructions.png")

    @commands.command(hidden=True)
    async def helmet(self, ctx):
        """Helmet"""
        await self.bot.reply(ctx, image="Images/helmet.jpg")

    @commands.command(aliases=["f"], hidden=True)
    async def pressf(self, ctx):
        """Press F to pay respects"""
        await self.bot.reply(ctx, text="https://i.imgur.com/zrNE05c.gif")

    @commands.command(hidden=True)
    async def goala(self, ctx):
        """Party on Garth"""
        await self.bot.reply(ctx, image='Images/goala.gif')

    @commands.command(usage="<an emoji>", aliases=['emoji'])
    async def emote(self, ctx, emoji: typing.Union[discord.Emoji, discord.PartialEmoji]):
        """View a bigger version of an Emoji"""
        e = discord.Embed()
        e.title = emoji.name
        if emoji.animated:
            e.description = "This is an animated emoji."

        try:
            e.add_field(name="Emoji Source", value=f"{emoji.guild} (ID: {emoji.guild.id})")
        except AttributeError:  # Partial Emoji doesn't have guild.
            pass

        e.colour = await embed_utils.get_colour(emoji.url)
        e.set_image(url=emoji.url)
        e.set_footer(text=emoji.url)
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load t he Images Cog into the bot"""
    bot.add_cog(Images(bot))
