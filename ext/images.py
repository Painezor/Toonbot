"""Various image manipulation """
from __future__ import annotations

import asyncio
import logging
import json
import io
import random

from typing import TYPE_CHECKING, TypeAlias

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageOps, ImageFont
from pydantic import BaseModel

from ext.utils import view_utils

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]

User: TypeAlias = discord.User | discord.Member

# Project Oxford
API = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

TINDER = """https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/51
2/tinder-512.png"""


with open("credentials.json", mode="r", encoding="utf-8") as fun:
    creds = json.load(fun)


logger = logging.getLogger("images")


class FaceRectangle(BaseModel):
    """General Coordinates of the face"""

    top: int
    left: int
    width: int
    height: int


class Point(BaseModel):
    """X & Y coordinates of a pupil"""

    x: float  # pylint: disable=C0103
    y: float  # pylint: disable=C0103


class FaceLandmarks(BaseModel):
    """Various entities on the face"""

    pupilLeft: Point
    pupilRight: Point
    noseTip: Point
    mouthLeft: Point
    mouthRight: Point
    eyebrowLeftOuter: Point
    eyebrowLeftInner: Point
    eyebrowRightInner: Point
    eyebrowRightOuter: Point
    eyeLeftOuter: Point
    eyeLeftInner: Point
    eyeLeftTop: Point
    eyeLeftBottom: Point
    eyeRightInner: Point
    eyeRightOuter: Point
    eyeRightTop: Point
    eyeRightBottom: Point
    noseRootLeft: Point
    noseRootRight: Point
    noseLeftAlarTop: Point
    noseRightAlarTop: Point
    noseLeftAlarOutTip: Point
    noseRightAlarOutTip: Point
    upperLipTop: Point
    upperLipBottom: Point
    underLipTop: Point
    underLipBottom: Point


class FaceAttributes(BaseModel):
    """Kinda useless but how the model goes"""

    headPose: HeadPose


class HeadPose(BaseModel):
    """Yaw / Pitch / Roll of a Head"""

    yaw: int
    pitch: int
    roll: int


class FacialRecognitionAPIResponse(BaseModel):
    """Coordinates returned from project oxford"""

    faceRectangle: FaceRectangle
    faceLandmarks: FaceLandmarks
    faceAttributes: FaceAttributes


class ImageCache:
    """Cached Images for an ImageView"""

    coordinates: list[FacialRecognitionAPIResponse] = []
    image: bytes | None = None
    bob: io.BytesIO | None = None
    eyes: io.BytesIO | None = None
    knob: io.BytesIO | None = None
    ruins: io.BytesIO | None = None


class ImageView(view_utils.BaseView):
    """Holder View for Image Manipulation functions."""

    def __init__(
        self,
        interaction: Interaction,
        user: User | None = None,
        link: str | None = None,
        file: discord.Attachment | None = None,
    ) -> None:
        if link is not None:
            self.target_url = link
        elif file is not None:
            self.target_url = file.url
        elif user is not None:
            self.target_url = user.display_avatar.with_format("png").url

        # Cache these, so if people re-click...
        self.cache = ImageCache()

        super().__init__(interaction.user)
        if not isinstance(interaction.channel, discord.TextChannel):
            self.knob.disabled = True
        elif not interaction.channel.is_nsfw():
            self.knob.disabled = True

    async def get_faces(self, interaction: Interaction) -> bytes:
        """Retrieve face features from Project Oxford,
        Returns True if fine."""

        # Prepare POST
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": creds["Oxford"]["OxfordKey"],
        }
        params = {
            "returnFaceId": "False",
            "returnFaceLandmarks": "True",
            "returnFaceAttributes": "headPose",
        }
        data = json.dumps({"url": self.target_url})

        async with interaction.client.session.post(
            API, params=params, headers=headers, data=data
        ) as resp:
            if resp.status != 200:
                logger.error("%s", await resp.json(), exc_info=True)
            coords = await resp.json()

            logger.info("get_faces resp -> %s", coords)
            coords = [FacialRecognitionAPIResponse(**i) for i in coords]

        # Get target image as file
        async with interaction.client.session.get(self.target_url) as resp:
            if resp.status != 200:
                logger.error("%s", self.target_url, exc_info=True)
            return await resp.content.read()

    async def bob_helper(
        self, interaction: Interaction
    ) -> tuple[discord.File, discord.Embed]:
        """Helper Method for BobRoss image"""
        if self.cache.image is None:
            self.cache.image = await self.get_faces(interaction)

        def draw(target: bytes) -> io.BytesIO:
            """Add bob ross overlay to image."""
            if self.cache.bob is not None:
                return self.cache.bob

            image = Image.open(io.BytesIO(target)).convert(mode="RGBA")
            bob = Image.open("Images/ross face.png")

            for i in self.cache.coordinates:
                pos_x = int(i.faceRectangle.left)
                pos_y = int(i.faceRectangle.top)
                wid = int(i.faceRectangle.width)
                hght = int(i.faceRectangle.height)
                roll = int(i.faceAttributes.headPose.roll * -1)

                top = int(pos_x + (wid * 1.25)) - int(pos_x - (wid / 4))
                bot = int((pos_y + (hght * 1.25))) - int(pos_y - (hght / 2))

                _ = ImageOps.fit(bob, (top, bot)).rotate(roll)
                image.paste(_, box=(top, bot), mask=_)

            image.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            image.close()
            bob.close()
            self.cache.bob = output
            return output

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.target_url)
        embed.set_image(url="attachment://img")
        output = await asyncio.to_thread(draw, self.cache.image)
        file = discord.File(fp=output, filename="img")
        return (file, embed)

    @discord.ui.button(label="Bob Ross", emoji="🖌️")
    async def bob_ross(self, interaction: Interaction, _) -> None:
        """Draw Bob Ross Beard/Hair on Image"""
        file, embed = await self.bob_helper(interaction)
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self)

    async def eyes_helper(
        self, interaction: Interaction
    ) -> tuple[discord.File, discord.Embed]:
        """Helper Method for entry point"""
        if self.cache.image is None:
            self.cache.image = await self.get_faces(interaction)

        def draw(target: bytes) -> io.BytesIO:
            """Draw a knob in someone's mouth for the knob command"""
            if self.cache.eyes is not None:
                return self.cache.eyes

            image = Image.open(io.BytesIO(target))
            for i in self.cache.coordinates:
                # Get eye bounds
                lix = int(i.faceLandmarks.eyeLeftInner.x)
                lox = int(i.faceLandmarks.eyeLeftOuter.x)
                lty = int(i.faceLandmarks.eyeLeftTop.y)
                # lby = int(i["faceLandmarks.eyeLeftBottom.y"])
                rox = int(i.faceLandmarks.eyeRightOuter.x)
                rix = int(i.faceLandmarks.eyeRightInner.x)
                rty = int(i.faceLandmarks.eyeRightTop.y)
                # rby = int(i["faceLandmarks.eyeRightBottom.y"])

                left_width = lix - lox
                right_width = rox - rix

                # Inflate
                lix += left_width
                lox -= left_width
                lty -= left_width
                # lby = lby + lw
                rox += right_width
                rix -= right_width
                rty -= right_width
                # rby = rby + rw

                # Recalculate with new sizes.
                left_width = lix - lox
                right_width = rox - rix

                # Open Eye Image, resize, paste twice
                eye = Image.open("Images/eye.png")
                left = ImageOps.fit(eye, (left_width, left_width))
                right = ImageOps.fit(eye, (right_width, right_width))
                image.paste(left, box=(lox, lty), mask=left)
                image.paste(right, box=(rix, rty), mask=right)

            # Prepare for sending and return
            image.save(output := io.BytesIO(), "PNG")
            output.seek(0)
            image.close()

            self.cache.eyes = output
            return output

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.target_url)
        embed.set_image(url="attachment://img")
        output = await asyncio.to_thread(draw, self.cache.image)

        file = discord.File(fp=output, filename="img")
        return (file, embed)

    @discord.ui.button(label="Eyes", emoji="👀")
    async def eyes(self, interaction: Interaction, _) -> None:
        """Push the eyes image to View"""
        file, embed = await self.eyes_helper(interaction)
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self)

    async def ruins_helper(
        self, interaction: Interaction
    ) -> tuple[discord.File, discord.Embed]:
        """Helper Method for the Ruins button"""
        if self.cache.image is None:
            self.cache.image = await self.get_faces(interaction)

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.target_url)
        embed.set_image(url="attachment://img")

        def draw(target: bytes) -> io.BytesIO:
            """Generates the Image"""
            if self.cache.ruins is not None:
                return self.cache.ruins

            img = ImageOps.fit(Image.open(io.BytesIO(target)), (256, 256))
            base = Image.open("Images/local man.png")
            base.paste(img, box=(175, 284, 431, 540))

            base.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup
            img.close()
            base.close()

            self.cache.ruins = output
            return output

        output = await asyncio.to_thread(draw, self.cache.image)
        file = discord.File(fp=output, filename="img")
        return (file, embed)

    @discord.ui.button(label="ruins", emoji="📰")
    async def ruins(self, interaction: Interaction, _) -> None:
        """Local Man Ruins Everything"""
        file, embed = await self.ruins_helper(interaction)
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self)

    @discord.ui.button(label="knob", emoji="🍆")
    async def knob(self, interaction: Interaction, _) -> None:
        """Push the Knob image to View"""
        if self.cache.image is None:
            self.cache.image = await self.get_faces(interaction)

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.target_url)
        embed.set_image(url="attachment://img")

        def draw(target: bytes) -> io.BytesIO:
            """Draw a knob in someone's mouth for the knob command"""
            if self.cache.knob is not None:
                return self.cache.knob

            image = Image.open(io.BytesIO(target)).convert(mode="RGBA")
            knob = Image.open("Images/knob.png")

            for i in self.cache.coordinates:
                mlx = int(i.faceLandmarks.mouthLeft.x)
                mrx = int(i.faceLandmarks.mouthRight.x)
                lip_y = int(i.faceLandmarks.upperLipBottom.y)
                lip_x = int(i.faceLandmarks.upperLipBottom.x)

                angle = int(i.faceAttributes.headPose.roll * -1)
                wid = int((mrx - mlx)) * 2
                hght = wid
                mask = ImageOps.fit(knob, (wid, hght)).rotate(angle)

                box = (int(lip_x - wid / 2), int(lip_y))
                image.paste(mask, box=box, mask=mask)

            image.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            image.close()
            knob.close()

            self.cache.knob = output
            return output

        output = await asyncio.to_thread(draw, self.cache.image)

        file = discord.File(fp=output, filename="img")
        edit = interaction.response.edit_message
        await edit(attachments=[file], embed=embed, view=self)


class Images(commands.Cog):
    """Image manipulation commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    images = discord.app_commands.Group(
        name="images", description="image manipulation commands"
    )

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def eyes(
        self,
        interaction: Interaction,
        user: User | None,
        link: str | None,
        file: discord.Attachment | None,
    ) -> None:
        """Draw Googly eyes on an image using Facial Recognition API."""
        user = interaction.user if not user else user
        view = ImageView(interaction, user, link, file)
        out, emb = await view.eyes_helper(interaction)

        await interaction.response.send_message(view=view, file=out, embed=emb)

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def ruins(
        self,
        interaction: Interaction,
        user: User | None,
        link: str | None,
        file: discord.Attachment | None,
    ) -> None:
        """Local man ruins everything"""
        user = interaction.user if not user else user
        view = ImageView(interaction, user, link, file)
        out, emb = await view.ruins_helper(interaction)
        await interaction.response.send_message(view=view, file=out, embed=emb)

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def bob_ross(
        self,
        interaction: Interaction,
        user: User | None,
        link: str | None,
        file: discord.Attachment | None,
    ) -> None:
        """Draw Bob Ross Hair on an image using Facial Recognition API"""
        user = interaction.user if not user else user
        view = ImageView(interaction, user, link, file)
        out, emb = await view.bob_helper(interaction)
        await interaction.response.send_message(view=view, file=out, embed=emb)

    @images.command()
    async def tinder(self, interaction: Interaction) -> None:
        """Try to Find your next date."""
        avata = await interaction.user.display_avatar.with_format("png").read()

        if members := getattr(interaction.channel, "members", []):
            match = random.choice(members)
            name = match.display_name
            target = await match.display_avatar.with_format("png").read()
        else:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "❌ Nobody swiped right on you."
            return await interaction.response.send_message(embed=embed)

        def draw(image: bytes, avatar: bytes, user_name: str) -> io.BytesIO:
            """Draw Images for the tinder command"""
            # Open The Tinder Image File
            base = Image.open("Images/tinder.png").convert(mode="RGBA")

            # Prepare the Mask and set size.
            msk = Image.open("Images/circle mask.png").convert("L")
            mask = ImageOps.fit(msk, (185, 185))

            # Open the User's Avatar, fit to size, apply mask.
            avt = Image.open(io.BytesIO(avatar)).convert(mode="RGBA")
            fitted = ImageOps.fit(avt, (185, 185))

            fitted.putalpha(mask)
            base.paste(fitted, box=(100, 223, 285, 408), mask=mask)

            # Open the second user's avatar, do same.
            oth = Image.open(io.BytesIO(image)).convert(mode="RGBA")
            other = ImageOps.fit(oth, (185, 185), centering=(0.5, 0.0))
            other.putalpha(mask)
            base.paste(other, box=(313, 223, 498, 408), mask=mask)

            # Cleanup
            msk.close()
            mask.close()
            avt.close()
            fitted.close()
            other.close()

            # Write Text
            txt = f"You and {user_name} have liked each other."
            font = ImageFont.truetype("Whitney-Medium.ttf", 24)
            wid = font.getsize(txt)[0]  # Width, Height

            size = (300 - wid / 2, float(180))
            drw = ImageDraw.Draw(base)
            drw.multiline_text(size, txt, 0xFFFFFF, font)

            base.save(out := io.BytesIO(), "PNG")
            base.close()
            out.seek(0)
            return out

        user = interaction.user.mention
        output = await asyncio.to_thread(draw, target, avata, name)
        if match.id == interaction.user.id:
            cpt = f"{user} matched with themself, How pathetic."
        elif match.id == self.bot.application_id:
            cpt = f"{user} Fancy a shag?"
        else:
            cpt = f"{user} matched with {match.mention}"

        embed = discord.Embed(description=cpt, colour=0xFD297B)
        embed.set_author(name="Tinder", icon_url=TINDER)
        embed.set_image(url="attachment://Tinder.png")
        file = discord.File(fp=output, filename="Tinder.png")
        send = interaction.response.send_message
        return await send(file=file, embed=embed)


async def setup(bot: Bot) -> None:
    """Load the Images Cog into the bot"""
    await bot.add_cog(Images(bot))
