"""Various image manipulation commands."""
import json
import random
import textwrap
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord import Option, Embed, Colour, Member, Attachment
from discord.ext import commands
from discord.ext.commands import EmojiNotFound
from discord.ui import View

from ext.utils import embed_utils

KNOB_ICON = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/86/18_icon_TV_%28Hungary%29.svg" \
            "/48px-18_icon_TV_%28Hungary%29.svg.png"


# TODO: XKCD Command. https://xkcd.com/json.html
# TODO: Select / Button Pass.
# TODO: User Commands Pass
# TODO: Modals pass
# TODO: Grouped Commands pass
# TODO: Slash attachments pass
# TODO: Permissions Pass.


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
    for coordinates in response:
        x = int(coordinates["faceRectangle"]["left"])
        y = int(coordinates["faceRectangle"]["top"])
        w = int(coordinates["faceRectangle"]["width"])
        h = int(coordinates["faceRectangle"]["height"])
        roll = int(coordinates["faceAttributes"]["headPose"]["roll"]) * -1
        top_left = int(x - (w / 4))
        bottom_left = int(y - (h / 2))
        top_right = int(x + (w * 1.25))
        bottom_right = int((y + (h * 1.25)))
        width = top_right - top_left
        height = bottom_right - bottom_left
        this = ImageOps.fit(bob, (width, height)).rotate(roll)
        im.paste(this, box=(top_left, bottom_left, top_right, bottom_right), mask=this)
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
        await ctx.reply(content="No target specified.")
        return None, None, None

    if isinstance(target, Member):
        target = target.display_avatar.with_format("png").url
    elif isinstance(target, Attachment):
        target = target.url
    elif "://" not in target:
        await ctx.error(f"{target} doesn't look like a valid url.")
        return None, None, None

    # Prepare POST
    h = {"Content-Type": "application/json", "Ocp-Apim-Subscription-Key": ctx.bot.credentials['Oxford']['OxfordKey']}
    p = {"returnFaceId": "False", "returnFaceLandmarks": "True", "returnFaceAttributes": "headPose"}
    d = json.dumps({"url": target})
    url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

    # Get Project Oxford reply
    async with ctx.bot.session.post(url, params=p, headers=h, data=d) as resp:
        if resp.status == 400:
            await ctx.error(await resp.json())
            return False, False, False
        elif resp.status != 200:
            await ctx.error(f"HTTP Error {resp.status} accessing facial recognition API.")
            return None, None, None
        response = await resp.json()

    # Get target image as file
    async with ctx.bot.session.get(target) as resp:
        if resp.status != 200:
            await ctx.error(f"{resp.status} code accessing project oxford.")
        image = await resp.content.read()
    return image, response, target


MEMBER = Option(Member, name="user", description="Use a user's profile picture", required=False, default=None)
LINK = Option(str, description="Provide a link to an image", required=False, default=None)


class ImageView(View):
    """Holder View for Image Manipulation functions."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.message = None
        super().__init__()

    async def update(self, content=""):
        if self.message is None:
            self.message = await self.ctx.replyy(content=content)


class Images(commands.Cog):
    """Image manipulation commands"""

    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command()
    async def emote(self, ctx, emoji: Option(str, description="Please enter an emote.")):
        """View a bigger version of an Emoji"""
        if emoji is None:
            return await ctx.error("You need to specify an emote to get the bigger version of.")

        try:
            emoji = await commands.EmojiConverter().convert(ctx, emoji)
        except EmojiNotFound:
            try:
                emoji = await commands.PartialEmojiConverter().convert(ctx, emoji)
            except EmojiNotFound:
                return await ctx.error("Invalid emote.")

        e = Embed()
        e.title = emoji.name
        if emoji.animated:
            e.description = "This is an animated emoji."

        try:
            e.add_field(name="From Server", value=f"{emoji.guild} (ID: {emoji.guild.id})")
        except AttributeError:  # Partial Emoji doesn't have guild.
            pass

        e.colour = await embed_utils.get_colour(emoji.url)
        e.set_image(url=emoji.url)
        e.set_footer(text=emoji.url)
        await ctx.reply(embed=e)

    @commands.slash_command()
    async def ruins(self, ctx, *, target: MEMBER):
        """Local man ruins everything"""
        message = await ctx.reply(content="Drawing...")

        if target is None:
            target = ctx.author
        av = await target.display_avatar.with_format("png").read()
        image = await self.bot.loop.run_in_executor(None, ruin, av)

        e = Embed()
        e.colour = Colour.blue()
        e.description = ctx.author.mention
        await embed_utils.embed_image(ctx, e, image, filename=f"{target}_ruins_everything.png", message=message)

    @commands.slash_command()
    async def ructions(self, ctx):
        """WEW. RUCTIONS."""
        await ctx.reply(file=embed_utils.make_file(image="Images/ructions.png"))

    @commands.slash_command()
    async def helmet(self, ctx):
        """Helmet"""
        await ctx.reply(file=embed_utils.make_file(image="Images/helmet.jpg"))

    @commands.slash_command()
    async def pressf(self, ctx):
        """Press F to pay respects"""
        await ctx.reply(content="https://i.imgur.com/zrNE05c.gif")

    @commands.slash_command()
    async def goala(self, ctx):
        """Party on Garth"""
        await ctx.reply(file=embed_utils.make_file(image='Images/goala.gif'))

    @commands.slash_command()
    async def tinder(self, ctx):
        """Try to Find your next date."""
        if ctx.guild is None:
            return await ctx.error("This command cannot be used in DMs")
        av = await ctx.author.display_avatar.with_format("png").read()

        attempts = 10
        while attempts > 0:
            match = random.choice(ctx.guild.members)
            name = match.display_name
            try:
                target = await match.display_avatar.with_format("png").read()
            except AttributeError:
                attempts -= 1
                continue
            else:
                break
        else:
            return await ctx.error("Nobody swiped right on you.")

        output = await self.bot.loop.run_in_executor(None, draw_tinder, target, av, name)
        if match == ctx.author:
            caption = f"{ctx.author.mention} matched with themself, How pathetic."
        elif match == ctx.me:
            caption = f"{ctx.author.mention} Fancy a shag?"
        else:
            caption = f"{ctx.author.mention} matched with {match.mention}"
        icon = "https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/512/tinder-512.png"
        base_embed = Embed()
        base_embed.description = caption
        base_embed.colour = 0xFD297B
        base_embed.set_author(name="Tinder", icon_url=icon)
        await embed_utils.embed_image(ctx, base_embed, output, filename="Tinder.png")

    @commands.slash_command(guild_ids=[250252535699341312])
    async def bob_ross(self, ctx, member: MEMBER, link: LINK):
        """Bob Rossify | Choose a member, provide a link, or leave both blank and upload a file."""
        message = await ctx.reply(content="Drawing...")

        if member:
            target = member
        elif link:
            target = link
        else:
            try:
                target = ctx.message.attachments[0]
            except IndexError:
                return await ctx.error('Provide an image, link, or user.')

        image, response, target = await get_faces(ctx, target)

        if response is None or response is False:
            return await ctx.error("No faces were detected in your image.", message=message)

        image = await self.bot.loop.run_in_executor(None, draw_bob, image, response)

        e = Embed()
        e.colour = 0xb4b2a7  # titanium h-white
        e.description = ctx.author.mention
        e.add_field(name="Source", value=target)
        await embed_utils.embed_image(ctx, e, image, filename="bobross.png", message=message)

    @commands.slash_command(guild_ids=[250252535699341312])
    async def eyes(self, ctx, member: MEMBER, link: LINK):
        """Draw Googly eyes on an image. Mention a user to use their avatar. Only works for human faces."""
        message = await ctx.reply(content="Drawing...")

        if member:
            target = member
        elif link:
            target = link
        else:
            try:
                target = ctx.message.attachments[0]
            except IndexError:
                return await ctx.error('Provide an image, link, or user.')

        image, response, target = await get_faces(ctx, target)

        if response is None:
            return await ctx.error("No faces were detected in your image.")
        elif response is False:
            return

        image = await self.bot.loop.run_in_executor(None, draw_eyes, image, response)

        e = Embed()
        e.colour = 0xFFFFFF
        e.description = ctx.author.mention
        e.add_field(name="Source", value=target)
        await embed_utils.embed_image(ctx, e, image, filename="eyes.png", message=message)

    # @commands.is_nsfw()
    # @commands.command(usage='<@user, link to image, or upload a file>')
    # async def knob(self, ctx, *, target: typing.Union[discord.Member, str] = None):
    #     """Draw knobs in mouth on an image. Mention a user to use their avatar. Only works for human faces."""
    #     image, response, target = await get_faces(ctx, target)
    #
    #     if response is None or response is False:
    #         return await ctx.reply(content="🚫 No faces were detected in your image.")
    #
    #     image = await self.bot.loop.run_in_executor(None, draw_knob, image, response)
    #
    #     base_embed = discord.Embed()
    #     base_embed.colour = 0xff66cc
    #     base_embed.description = ctx.author.mention
    #     base_embed.add_field(name="Source", value=target)
    #     await embed_utils.embed_image(ctx, base_embed, image, filename="Knob.png")

    @commands.slash_command()
    async def tard(self, ctx, quote: Option(str, description="Message for the image"), target: MEMBER):
        """Generate an "oh no, it's retarded" image with a user's avatar and a quote"""
        message = await ctx.reply(content="Drawing...")

        if target is None or target.id == 210582977493598208:
            target = ctx.author

        image = await target.display_avatar.with_format("png").read()
        image = await self.bot.loop.run_in_executor(None, draw_tard, image, quote)

        e = Embed()
        e.colour = Colour.blue()
        e.description = ctx.author.mention
        await embed_utils.embed_image(ctx, e, image, filename="tard.png", message=message)


def setup(bot):
    """Load the Images Cog into the bot"""
    bot.add_cog(Images(bot))
