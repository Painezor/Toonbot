"""Various image manipulation """
from __future__ import annotations

import asyncio
import logging
import json
import io
import random
import typing

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageOps, ImageFont

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]

# Project Oxford
API = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

TINDER = """https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/51
2/tinder-512.png"""


with open("credentials.json", mode="r", encoding="utf-8") as fun:
    credentials = json.load(fun)


logger = logging.getLogger("images")


class KnobButton(discord.ui.Button["ImageView"]):
    """Push the Knob image to View"""

    def __init__(self):
        super().__init__(label="knob", emoji="🍆")

    async def callback(self, interaction: Interaction) -> None:
        assert self.view is not None

        if self.view.image is None:
            self.view.image = await self.view.get_faces()

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.view.target_url)
        embed.set_image(url="attachment://img")
        output = await asyncio.to_thread(
            self.draw, self.view.image, self.view.coordinates
        )

        file = discord.File(fp=output, filename="img")
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self.view)

    def draw(self, target: bytes, coords: dict) -> io.BytesIO:
        """Draw a knob in someone's mouth for the knob command"""
        assert self.view is not None
        if self.view.cache["knob"] is not None:
            return self.view.cache["knob"]

        image = Image.open(io.BytesIO(target)).convert(mode="RGBA")
        knob = Image.open("Images/knob.png")

        for coords in self.view.coordinates:
            mlx = int(coords["faceLandmarks"]["mouthLeft"]["x"])
            mrx = int(coords["faceLandmarks"]["mouthRight"]["x"])
            lip_y = int(coords["faceLandmarks"]["upperLipBottom"]["y"])
            lip_x = int(coords["faceLandmarks"]["upperLipBottom"]["x"])

            angle = int(coords["faceAttributes"]["headPose"]["roll"] * -1)
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

        self.view.cache["knob"] = output
        return output


class EyesButton(discord.ui.Button["ImageView"]):
    """Push the eyes image to View"""

    def __init__(self):
        super().__init__(label="eyes", emoji="👀")

    async def callback(self, interaction: Interaction) -> None:
        assert self.view is not None

        if self.view.image is None:
            self.view.image = await self.view.get_faces()

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.view.target_url)
        embed.set_image(url="attachment://img")
        output = await asyncio.to_thread(
            self.draw, self.view.image, self.view.coordinates
        )

        file = discord.File(fp=output, filename="img")
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self.view)

    def draw(self, target: bytes, coords: dict) -> io.BytesIO:
        """Draw a knob in someone's mouth for the knob command"""
        assert self.view is not None
        if self.view.cache["eyes"] is not None:
            return self.view.cache["eyes"]

        image = Image.open(io.BytesIO(target))
        for i in coords:
            # Get eye bounds
            lix = int(i["faceLandmarks"]["eyeLeftInner"]["x"])
            lox = int(i["faceLandmarks"]["eyeLeftOuter"]["x"])
            lty = int(i["faceLandmarks"]["eyeLeftTop"]["y"])
            # lby = int(i["faceLandmarks"]["eyeLeftBottom"]["y"])
            rox = int(i["faceLandmarks"]["eyeRightOuter"]["x"])
            rix = int(i["faceLandmarks"]["eyeRightInner"]["x"])
            rty = int(i["faceLandmarks"]["eyeRightTop"]["y"])
            # rby = int(i["faceLandmarks"]["eyeRightBottom"]["y"])

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

        self.view.cache["eyes"] = output
        return output


class BobButton(discord.ui.Button["ImageView"]):
    """Push the eyes image to View"""

    def __init__(self):
        super().__init__(label="bob ross", emoji="🖌️")

    async def callback(self, interaction: Interaction) -> None:
        assert self.view is not None

        if self.view.image is None:
            self.view.image = await self.view.get_faces()

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.view.target_url)
        embed.set_image(url="attachment://img")
        output = await asyncio.to_thread(
            self.draw, self.view.image, self.view.coordinates
        )

        file = discord.File(fp=output, filename="img")
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self.view)

    def draw(self, target: bytes, coords: dict) -> io.BytesIO:
        """Add bob ross overlay to image."""
        assert self.view is not None
        if self.view.cache["bob"] is not None:
            return self.view.cache["bob"]

        image = Image.open(io.BytesIO(target)).convert(mode="RGBA")
        bob = Image.open("Images/ross face.png")

        for i in coords:
            pos_x = int(i["faceRectangle"]["left"])
            pos_y = int(i["faceRectangle"]["top"])
            wid = int(i["faceRectangle"]["width"])
            hght = int(i["faceRectangle"]["height"])
            roll = int(i["faceAttributes"]["headPose"]["roll"]) * -1

            top = int(pos_x + (wid * 1.25)) - int(pos_x - (wid / 4))
            bot = int((pos_y + (hght * 1.25))) - int(pos_y - (hght / 2))

            _ = ImageOps.fit(bob, (top, bot)).rotate(roll)
            image.paste(_, box=(top, bot), mask=_)

        image.save(output := io.BytesIO(), "PNG")
        output.seek(0)

        # Cleanup.
        image.close()
        bob.close()
        self.view.cache["bob"] = output
        return output


class RuinsButton(discord.ui.Button["ImageView"]):
    """Local Man Ruins Everything"""

    def __init__(self):
        super().__init__(label="eyes", emoji="📰")

    async def callback(self, interaction: Interaction) -> None:
        """Push the Local man ruins everything image to view"""
        assert self.view is not None

        if self.view.image is None:
            self.view.image = await self.view.get_faces()

        embed = discord.Embed(colour=0xFFFFFF)
        embed.add_field(name="Source Image", value=self.view.target_url)
        embed.set_image(url="attachment://img")
        output = await asyncio.to_thread(
            self.draw,
            self.view.image,
        )

        file = discord.File(fp=output, filename="img")
        edit = interaction.response.edit_message
        return await edit(attachments=[file], embed=embed, view=self.view)

    def draw(self, target: bytes) -> io.BytesIO:
        """Generates the Image"""
        assert self.view is not None
        if self.view.cache["ruins"] is not None:
            return self.view.cache["ruins"]

        img = ImageOps.fit(Image.open(io.BytesIO(target)), (256, 256))
        base = Image.open("Images/local man.png")
        base.paste(img, box=(175, 284, 431, 540))

        base.save(output := io.BytesIO(), "PNG")
        output.seek(0)

        # Cleanup
        img.close()
        base.close()

        self.view.cache["ruins"] = output
        return output


class ImageView(view_utils.BaseView):
    """Holder View for Image Manipulation functions."""

    def __init__(
        self,
        interaction: Interaction,
        user: typing.Optional[discord.User | discord.Member] = None,
        link: typing.Optional[str] = None,
        file: typing.Optional[discord.Attachment] = None,
    ) -> None:

        if link is not None:
            self.target_url = link
        elif file is not None:
            self.target_url = file.url
        elif user is not None:
            self.target_url = user.display_avatar.with_format("png").url

        self.image: typing.Optional[bytes] = None
        self.coordinates: dict = {}

        # Cache these, so if people re-click...
        self.cache: dict[str, typing.Optional[io.BytesIO]] = {
            "bob": None,
            "eyes": None,
            "knob": None,
            "ruins": None,
        }

        super().__init__()
        self.add_item(EyesButton())
        self.add_item(BobButton())
        self.add_item(RuinsButton())

        if isinstance(interaction.channel, discord.TextChannel):
            if interaction.channel.is_nsfw():
                self.add_item(KnobButton())

    async def get_faces(self) -> bytes:
        """Retrieve face features from Project Oxford,
        Returns True if fine."""

        # Prepare POST
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": credentials["Oxford"]["OxfordKey"],
        }
        params = {
            "returnFaceId": "False",
            "returnFaceLandmarks": "True",
            "returnFaceAttributes": "headPose",
        }
        data = json.dumps({"url": self.target_url})

        async with aiohttp.ClientSession() as session:
            async with session.post(
                API, params=params, headers=headers, data=data
            ) as resp:
                if resp.status != 200:
                    logger.error("%s", await resp.json(), exc_info=True)
                self.coordinates = await resp.json()

            # Get target image as file
            async with session.get(self.target_url) as resp:
                if resp.status != 200:
                    logger.error("%s", self.target_url, exc_info=True)
                return await resp.content.read()


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
        user: typing.Optional[discord.User | discord.Member],
        link: typing.Optional[str],
        file: typing.Optional[discord.Attachment],
    ) -> None:
        """Draw Googly eyes on an image. Mention a user to use their avatar.
        Only works for human faces."""
        user = interaction.user if not user else user
        view = ImageView(interaction, user, link, file)
        btn = next(i for i in view.children if isinstance(i, EyesButton))
        return await btn.callback(interaction)

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def ruins(
        self,
        interaction: Interaction,
        user: typing.Optional[discord.User | discord.Member],
        link: typing.Optional[str],
        file: typing.Optional[discord.Attachment],
    ) -> None:
        """Local man ruins everything"""
        user = interaction.user if not user else user
        view = ImageView(interaction, user, link, file)
        btn = next(i for i in view.children if isinstance(i, RuinsButton))
        return await btn.callback(interaction)

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def bob_ross(
        self,
        interaction: Interaction,
        user: typing.Optional[discord.User | discord.Member],
        link: typing.Optional[str],
        file: typing.Optional[discord.Attachment],
    ) -> None:
        """Draw Bob Ross Hair on an image. Only works for human faces."""
        user = interaction.user if not user else user
        view = ImageView(interaction, user, link, file)
        btn = next(i for i in view.children if isinstance(i, BobButton))
        return await btn.callback(interaction)

    @images.command()
    @discord.app_commands.guild_only()
    async def tinder(
        self, interaction: Interaction
    ) -> discord.InteractionMessage:
        """Try to Find your next date."""
        await interaction.response.defer(thinking=True)
        avata = await interaction.user.display_avatar.with_format("png").read()

        if interaction.guild is None:
            raise discord.app_commands.errors.NoPrivateMessage

        for _ in range(10):
            match = random.choice(interaction.guild.members)
            name = match.display_name
            try:
                target = await match.display_avatar.with_format("png").read()
                break
            except AttributeError:
                continue
        else:
            embed = discord.Embed(colour=discord.Colour.red())
            # Exhaust All Bans.
            embed.description = "❌ Nobody swiped right on you."
            return await interaction.edit_original_response(embed=embed)

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

            # Write "it's a mutual match"
            text = f"You and {user_name} have liked each other."
            font = ImageFont.truetype("Whitney-Medium.ttf", 24)
            wid = font.getsize(text)[0]  # Width, Height

            size = (300 - wid / 2, 180)
            ImageDraw.Draw(base).text(size, text, font=font, fill="#ffffff")

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

        edit = interaction.edit_original_response
        return await edit(attachments=[file], embed=embed)


async def setup(bot: Bot) -> None:
    """Load the Images Cog into the bot"""
    await bot.add_cog(Images(bot))
