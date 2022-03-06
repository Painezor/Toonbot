"""Various image manipulation commands."""
import json
import random
import textwrap
from io import BytesIO
from typing import Optional, Union

from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord import Embed, Colour, Member, Attachment, Interaction, app_commands, User
from discord.ext import commands
from discord.ui import View

from ext.utils import embed_utils

KNOB_ICON = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/86/18_icon_TV_%28Hungary%29.svg" \
            "/48px-18_icon_TV_%28Hungary%29.svg.png"


# TODO: XKCD Command. https://xkcd.com/json.html
# TODO: Select / Button Pass: Dropdown for ImageView
# TODO: User Commands Pass


class ImageView(View):
    """Holder View for Image Manipulation functions."""

    def __init__(self, interaction, target: str):
        self.interaction = interaction
        self.message = None
        self.coordinates = None
        self.image = None
        self.target_url = target
        super().__init__()

    async def get_faces(self):
        """Retrieve face features from Project Oxford"""

        # Prepare POST
        h = {"Content-Type": "application/json",
             "Ocp-Apim-Subscription-Key": self.interaction.client.credentials['Oxford']['OxfordKey']}
        p = {"returnFaceId": "False", "returnFaceLandmarks": "True", "returnFaceAttributes": "headPose"}
        d = json.dumps({"url": self.target_url})
        url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

        # Get Project Oxford reply
        async with self.interaction.client.session.post(url, params=p, headers=h, data=d) as resp:
            if resp.status == 400:
                return await self.error(await resp.json())
            elif resp.status != 200:
                return await self.error(f"HTTP Error {resp.status} accessing facial recognition API.")
            self.coordinates = await resp.json()

        # Get target image as file
        async with self.interaction.client.session.get(self.target_url) as resp:
            if resp.status != 200:
                return await self.error(f"HTTP Error {resp.status} opening {self.target_url}.")
            self.image = await resp.content.read()

    async def push_eyes(self):
        """Draw the googly eyes"""
        if self.image is None:
            await self.get_faces()

        def draw_eyes():
            """Draws the eyes"""
            im = Image.open(BytesIO(self.image))
            for i in self.coordinates:
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

        image = await self.interaction.client.loop.run_in_executor(None, draw_eyes)

        e = Embed(colour=0xFFFFFF, description=self.interaction.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        await embed_utils.embed_image(self.interaction, e, image, filename="eyes.png", message=self.message)

    async def push_knob(self):
        """Push the bob ross image to View"""
        if self.image is None:
            await self.get_faces()

        def draw_knob():
            """Draw a knob in someone's mouth for the knob command"""
            im = Image.open(BytesIO(self.image)).convert(mode="RGBA")
            knob = Image.open("Images/knob.png")

            for coords in self.coordinates:
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

        image = await self.interaction.client.loop.run_in_executor(None, draw_knob)

        e = Embed(colour=0xFFFFFF, description=self.interaction.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        await embed_utils.embed_image(self.interaction, e, image, filename="knob.png", message=self.message)

    async def push_bob(self):
        """Push the bob ross image to View"""
        if self.image is None:
            await self.get_faces()

        def draw_bob():
            """Pillow Bob Rossifying"""
            im = Image.open(BytesIO(self.image)).convert(mode="RGBA")
            bob = Image.open("Images/rossface.png")
            for coordinates in self.coordinates:
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

        image = await self.interaction.client.loop.run_in_executor(None, draw_bob)

        e = Embed(colour=0xFFFFFF, description=self.interaction.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        await embed_utils.embed_image(self.interaction, e, image, filename="bob.png", message=self.message)

    async def error(self, err):
        """Handle Image Errors"""
        if self.message is None:
            self.message = await self.interaction.response.error(self.interaction, error_message=err)

    async def update(self, content=""):
        """Push latest version to view"""
        if self.message is None:
            self.message = await self.interaction.response.reply(self.interaction, content=content)


@app_commands.command()
@app_commands.describe(user="pick a user", link="provide a link", file="upload a file")
async def eyes(interaction: Interaction, user: Optional[Member], link: Optional[str], file: Optional[Attachment]):
    """Draw Googly eyes on an image. Mention a user to use their avatar. Only works for human faces."""
    await interaction.response.defer(thinking=True)

    if link is None:
        if user is None:
            user = interaction.user
        link = user.display_avatar.with_format("png").url
    else:
        if file is not None:
            link = file.url

    view = ImageView(interaction, link)
    await view.push_eyes()


@app_commands.command()
@app_commands.describe(user="pick a user", link="provide a link", file="upload a file")
async def bob_ross(interaction: Interaction, user: Optional[Member], link: Optional[str], file: Optional[Attachment]):
    """Draw Googly eyes on an image. Mention a user to use their avatar. Only works for human faces."""
    await interaction.response.defer(thinking=True)

    if link is None:
        if user is None:
            user = interaction.user
        link = user.display_avatar.with_format("png").url
    else:
        if file is not None:
            link = file.url

    view = ImageView(interaction, link)
    await view.push_bob()


class Images(commands.Cog):
    """Image manipulation commands"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(ruins)
        self.bot.tree.add_command(tinder)
        self.bot.tree.add_command(tard)
        self.bot.tree.add_command(eyes)
        self.bot.tree.add_command(bob_ross)

    # TODO: Unfuck emoji command.
    # @app_commands.command()
    # @app_commands.describe(emoji="Provide an emote")
    # async def emote(self, interaction: Interaction, emoji: str):
    #     """View a bigger version of an Emoji"""
    #     try:
    #         emoji = await commands.EmojiConverter().convert(ctx, emoji)
    #     except EmojiNotFound:
    #         try:
    #             emoji = await commands.PartialEmojiConverter().convert(ctx, emoji)
    #         except EmojiNotFound:
    #             return await interaction.client.error(interaction, "Invalid emote.")
    #
    #     e = Embed(title=emoji.name)
    #     if emoji.animated:
    #         e.description = "This is an animated emoji."
    #
    #     try:
    #         e.add_field(name="From Server", value=f"{emoji.guild} (ID: {emoji.guild.id})")
    #     except AttributeError:  # Partial Emoji doesn't have guild.
    #         pass
    #
    #     e.colour = await embed_utils.get_colour(emoji.url)
    #     e.set_image(url=emoji.url)
    #     e.set_footer(text=emoji.url)
    #     await interaction.client.reply(interaction, embed=e)

    # TODO: NSFW Knob command.
    # @commands.is_nsfw()
    # @commands.command(usage='<@user, link to image, or upload a file>')
    # async def knob(self, interaction: Interaction,*, target: typing.Union[discord.Member, str] = None):
    #     """Draw knobs in mouth on an image. Mention a user to use their avatar. Only works for human faces."""
    #     image, response, target = await get_faces(ctx, target)
    #
    #     if response is None or response is False:
    #         return await interaction.client.reply(interaction, content="🚫 No faces were detected in your image.")
    #
    #     image = await self.bot.loop.run_in_executor(None, draw_knob, image, response)
    #
    #     base_embed = discord.Embed()
    #     base_embed.colour = 0xff66cc
    #     base_embed.description = interaction.user.mention
    #     base_embed.add_field(name="Source", value=target)
    #     await embed_utils.embed_image(ctx, base_embed, image, filename="Knob.png")


def setup(bot):
    """Load the Images Cog into the bot"""
    bot.add_cog(Images(bot))


@app_commands.command()
@app_commands.describe(user="Select a user", link="Provide a link to an image", attachment="Upload a file")
async def ruins(interaction: Interaction, user: Optional[Member], link: Optional[str], file: Optional[Attachment]):
    """Local man ruins everything"""
    await interaction.response.defer(thinking=True)

    if link is None:
        if user is None:
            user = interaction.user
        link = user.display_avatar.with_format("png").url
    else:
        if file is not None:
            link = file.url

    async with interaction.client.session.get(link) as resp:
        if resp.status != 200:
            return await interaction.client.error(interaction, f"HTTP Error {resp.status} opening {link}.")
        image = await resp.content.read()

    def ruin(img):
        """Generates the Image"""
        im = Image.open(BytesIO(img))
        base = Image.open("Images/localman.png")
        ops = ImageOps.fit(im, (256, 256))
        base.paste(ops, box=(175, 284, 431, 540))
        output = BytesIO()
        base.save(output, "PNG")
        output.seek(0)
        return output

    image = await interaction.client.loop.run_in_executor(None, ruin, image)
    e = Embed(color=Colour.blue())
    return await embed_utils.embed_image(interaction, e, image, filename=f"ruins_everything.png")


@app_commands.command()
@app_commands.describe(quote="enter quote text", target="pick a user")
async def tard(self, interaction: Interaction, quote: str, target: Optional[Union[User, Member]]):
    """Generate an "oh no, it's retarded" image with a user's avatar and a quote"""
    await interaction.response.defer(thinking=True)

    if target is None or target.id == 210582977493598208:
        target = interaction.user

    image = await target.display_avatar.with_format("png").read()

    def draw_tard(img, txt):
        """Draws the "it's retarded" image"""
        # Open Files
        im = Image.open(BytesIO(img))
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

        wid, font = get_first_size(txt)
        quote_fill = textwrap.fill(txt, width=wid)
        # Write lines.
        moveup = font.getsize(quote_fill)[1]
        d.text((245, (80 - moveup)), quote_fill, font=font, fill="#000000")

        # Prepare for sending
        output = BytesIO()
        base.save(output, "PNG")
        output.seek(0)
        return output

    image = await self.bot.loop.run_in_executor(None, draw_tard, image, quote)
    await embed_utils.embed_image(interaction, Embed(colour=Colour.blue()), image, filename="tard.png")


@app_commands.command()
async def tinder(self, interaction):
    """Try to Find your next date."""
    if interaction.guild is None:
        return await interaction.client.error(interaction, "This command cannot be used in DMs")
    av = await interaction.user.display_avatar.with_format("png").read()

    attempts = 10
    while attempts > 0:
        match = random.choice(interaction.guild.members)
        name = match.display_name
        try:
            target = await match.display_avatar.with_format("png").read()
        except AttributeError:
            attempts -= 1
            continue
        else:
            break
    else:
        return await interaction.client.error(interaction, "Nobody swiped right on you.")

    def draw_tinder(image, avatar, user_name):
        """Draw Images for the tinder command"""
        # Base Image
        im = Image.open("Images/tinder.png").convert(mode="RGBA")
        # Prepare mask
        msk = Image.open("Images/circlemask.png").convert('L')
        msk = ImageOps.fit(msk, (185, 185))

        # User Avatar
        avt = Image.open(BytesIO(avatar)).convert(mode="RGBA")
        avo = ImageOps.fit(avt, (185, 185))
        avo.putalpha(msk)
        im.paste(avo, box=(100, 223, 285, 408), mask=msk)

        # Player
        user_av = Image.open(BytesIO(image)).convert(mode="RGBA")
        plo = ImageOps.fit(user_av, (185, 185), centering=(0.5, 0.0))
        plo.putalpha(msk)
        im.paste(plo, box=(313, 223, 498, 408), mask=msk)
        # Write "it's a mutual match"
        txt = f"You and {user_name} have liked each other."
        f = ImageFont.truetype('Whitney-Medium.ttf', 24)
        w, h = f.getsize(txt)
        d = ImageDraw.Draw(im)
        d.text((300 - w / 2, 180), txt, font=f, fill="#ffffff")

        out = BytesIO()
        im.save(out, "PNG")
        out.seek(0)
        return out

    output = await self.bot.loop.run_in_executor(None, draw_tinder, target, av, name)
    if match.id == interaction.user.id:
        caption = f"{interaction.user.mention} matched with themself, How pathetic."
    elif match.id == interaction.client.user.id:
        caption = f"{interaction.user.mention} Fancy a shag?"
    else:
        caption = f"{interaction.user.mention} matched with {match.mention}"
    icon = "https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/512/tinder-512.png"
    e = Embed(description=caption, colour=0xFD297B)
    e.set_author(name="Tinder", icon_url=icon)
    await embed_utils.embed_image(interaction, e, output, filename="Tinder.png")
