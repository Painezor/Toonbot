"""Various image manipulation commands."""
import json
import random
import textwrap
from io import BytesIO
from typing import Optional, TYPE_CHECKING

from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord import Embed, Colour, Member, Attachment, Interaction, app_commands, User, Message
from discord.ext import commands
from discord.ui import View

from ext.utils import embed_utils

if TYPE_CHECKING:
    from core import Bot

KNOB_ICON = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/86/18_icon_TV_%28Hungary%29.svg" \
            "/48px-18_icon_TV_%28Hungary%29.svg.png"


def get_target(interaction: Interaction, user: User | Member = None, link: str = None, file: Attachment = None) -> str:
    """Get the requested link from passed arguments"""
    if link is None:
        if user is None:
            user = interaction.user
        link = user.display_avatar.with_format("png").url
    else:
        if file is not None:
            link = file.url
    return link


# TODO: XKCD Command. https://xkcd.com/json.html
# TODO: Select / Button Pass: Dropdown for ImageView
# TODO: User Commands Pass

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


class ImageView(View):
    """Holder View for Image Manipulation functions."""

    def __init__(self, interaction: Interaction, target: str) -> None:
        self.interaction: Interaction = interaction
        self.coordinates: dict = {}
        self.image: bytes | None = None
        self.target_url: str = target
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
            match resp.status:
                case 200:
                    self.coordinates = await resp.json()
                case 400:
                    return await self.interaction.client.error(self.interaction, await resp.json())
                case _:
                    err = f"HTTP Error {resp.status} accessing facial recognition API."
                    return await self.interaction.client.error(self.interaction, err)

        # Get target image as file
        async with self.interaction.client.session.get(self.target_url) as resp:
            if resp.status != 200:
                err = f"HTTP Error {resp.status} opening {self.target_url}."
                return await self.interaction.client.error(self.interaction, err)
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
        await embed_utils.embed_image(self.interaction, e, image, filename="eyes.png")

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
        await embed_utils.embed_image(self.interaction, e, image, filename="knob.png")

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
        await embed_utils.embed_image(self.interaction, e, image, filename="bob.png")

    async def update(self, content: str = "") -> Message:
        """Push latest version to view"""
        return await self.interaction.client.reply(self.interaction, content=content)


class Images(commands.Cog):
    """Image manipulation commands"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    @app_commands.command()
    @app_commands.describe(user="pick a user", link="provide a link", file="upload a file")
    async def eyes(self, interaction: Interaction,
                   user: Optional[Member | User] = None,
                   link: Optional[str] = None,
                   file: Optional[Attachment] = None):
        """Draw Googly eyes on an image. Mention a user to use their avatar. Only works for human faces."""
        await interaction.response.defer(thinking=True)
        link = get_target(interaction, user, link, file)
        view = ImageView(interaction, link)
        await view.push_eyes()

    @app_commands.command()
    @app_commands.describe(user="Select a user", link="Provide a link to an image", file="Upload a file")
    async def ruins(self, interaction: Interaction,
                    user: Optional[Member | User] = None,
                    link: Optional[str] = None,
                    file: Optional[Attachment] = None):
        """Local man ruins everything"""
        await interaction.response.defer(thinking=True)

        link = get_target(interaction, user, link, file)
        async with interaction.client.session.get(link) as resp:
            if resp.status != 200:
                return await interaction.client.error(interaction, f"HTTP Error {resp.status} opening {link}.")
            image = await resp.content.read()

        def ruin(img: bytes):
            """Generates the Image"""
            img = ImageOps.fit(Image.open(BytesIO(img)), (256, 256))
            base = Image.open("Images/localman.png")
            base.paste(img, box=(175, 284, 431, 540))

            output = BytesIO()
            base.save(output, "PNG")
            output.seek(0)

            # Cleanup!
            img.close()
            base.close()
            return output

        image = await interaction.client.loop.run_in_executor(None, ruin, image)
        e = Embed(color=Colour.blue())
        return await embed_utils.embed_image(interaction, e, image, filename=f"ruins_everything.png")

    @app_commands.command()
    @app_commands.describe(user="pick a user", link="provide a link", file="upload a file")
    async def bob_ross(self, interaction: Interaction,
                       user: Optional[User | Member] = None,
                       link: Optional[str] = None,
                       file: Optional[Attachment] = None):
        """Draw Bob Ross Hair on an image. Only works for human faces."""
        await interaction.response.defer(thinking=True)
        link = get_target(interaction, user, link, file)
        view = ImageView(interaction, link)
        await view.push_bob()

    @app_commands.command()
    async def tinder(self, interaction: Interaction) -> Message:
        """Try to Find your next date."""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be used in DMs")
        av = await interaction.user.display_avatar.with_format("png").read()

        for x in range(10):
            match = random.choice(interaction.guild.members)
            name = match.display_name
            try:
                target = await match.display_avatar.with_format("png").read()
                break
            except AttributeError:
                continue
        else:
            return await self.bot.error(interaction, "Nobody swiped right on you.")

        def draw_tinder(image: bytes, avatar: bytes, user_name):
            """Draw Images for the tinder command"""
            # Open The Tinder Image File
            im: Image = Image.open("Images/tinder.png").convert(mode="RGBA")

            # Open the User's Avatar, fit to size, apply mask.
            avatar: Image = Image.open(BytesIO(avatar)).convert(mode="RGBA")
            avatar = ImageOps.fit(avatar, (185, 185))

            # Open the second user's avatar, do same.
            other: Image = Image.open(BytesIO(image)).convert(mode="RGBA")
            other = ImageOps.fit(other, (185, 185), centering=(0.5, 0.0))

            # Prepare the Mask and set size.
            mask: Image = Image.open("Images/circlemask.png")
            mask = ImageOps.fit(mask.convert('L'), (185, 185))
            avatar.putalpha(mask)
            other.putalpha(mask)

            # Paste both images on source image.
            im.paste(avatar, box=(100, 223, 285, 408), mask=mask)
            im.paste(other, box=(313, 223, 498, 408), mask=mask)

            # Cleanup
            mask.close()
            avatar.close()
            other.close()

            # Write "it's a mutual match"
            text = f"You and {user_name} have liked each other."
            f = ImageFont.truetype('Whitney-Medium.ttf', 24)
            w, h = f.getsize(text)
            ImageDraw.Draw(im).text((300 - w / 2, 180), text, font=f, fill="#ffffff")

            out = BytesIO()
            im.save(out, "PNG")
            im.close()
            out.seek(0)
            return out

        output = await self.bot.loop.run_in_executor(None, draw_tinder, target, av, name)
        if match.id == interaction.user.id:
            caption = f"{interaction.user.mention} matched with themself, How pathetic."
        elif match.id == self.bot.user.id:
            caption = f"{interaction.user.mention} Fancy a shag?"
        else:
            caption = f"{interaction.user.mention} matched with {match.mention}"
        icon = "https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/512/tinder-512.png"
        e = Embed(description=caption, colour=0xFD297B)
        e.set_author(name="Tinder", icon_url=icon)
        return await embed_utils.embed_image(interaction, e, output, filename="Tinder.png")

    @app_commands.command()
    @app_commands.describe(quote="enter quote text", target="pick a user")
    async def tard(self, interaction: Interaction, quote: str, target: Optional[User | Member] = None):
        """Generate an "oh no, it's retarded" image with a user's avatar and a quote"""
        await interaction.response.defer(thinking=True)

        if target is None or target.id == self.bot.owner_id:
            target = interaction.user

        image = await target.display_avatar.with_format("png").read()

        def draw_tard(img: bytes, txt):
            """Draws the "it's retarded" image"""
            # Open Files
            img: Image = Image.open(BytesIO(img))
            base: Image = Image.open("Images/retardedbase.png")
            mask: Image = Image.open("Images/circlemask.png").convert('L')

            # Resize avatar, make circle, paste
            img = ImageOps.fit(img, (250, 250))
            img.putalpha(mask)
            mask = mask.resize((35, 40))
            small = img.resize((35, 40))

            base.paste(small, box=(175, 160, 210, 200), mask=small)
            small.close()

            mask = mask.resize((100, 100))
            large = img.resize((100, 100)).rotate(-20)

            base.paste(large, box=(325, 90, 425, 190), mask=mask)
            large.close()
            mask.close()

            # Drawing tex
            d = ImageDraw.Draw(base)

            # Get best size for text
            def get_first_size(quote_text):
                """Measure font and shrink it to appropriate size."""
                font_size = 72
                ft = ImageFont.truetype('Whitney-Medium.ttf', font_size)
                width = 300
                quote_text = textwrap.fill(quote_text, width=width)
                while font_size > 0:
                    # Make lines thinner if too wide.
                    while width > 1:
                        if ft.getsize(quote_text)[0] < 237 and ft.getsize(quote)[1] < 89:
                            return width, ft
                        width -= 1
                        quote_text = textwrap.fill(quote, width=width)
                        ft = ImageFont.truetype('Whitney-Medium.ttf', font_size)
                    font_size -= 1
                    ft = ImageFont.truetype('Whitney-Medium.ttf', font_size)
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
            base.close()
            img.close()
            return output

        image = await self.bot.loop.run_in_executor(None, draw_tard, image, quote)
        await embed_utils.embed_image(interaction, Embed(colour=Colour.blue()), image, filename="tard.png")


def setup(bot: 'Bot'):
    """Load the Images Cog into the bot"""
    bot.add_cog(Images(bot))
