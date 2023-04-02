"""Various image manipulation """
from __future__ import annotations

import io
import json
import random
import asyncio
from typing import Optional
import typing

from PIL import Image, ImageDraw, ImageOps, ImageFont
import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot

TINDER = """https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/51
2/tinder-512.png"""


with open("credentials.json", mode="r", encoding="utf-8") as fun:
    credentials = json.load(fun)


class ImageView(view_utils.BaseView):
    """Holder View for Image Manipulation functions."""

    interaction: discord.Interaction[Bot]

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        user: typing.Optional[discord.User] = None,
        link: typing.Optional[str] = None,
        file: typing.Optional[discord.Attachment] = None,
    ) -> None:

        if link is not None:
            self.target_url = link
        elif file is not None:
            self.target_url = file.url
        elif user is not None:
            self.target_url = user.display_avatar.with_format("png").url
        else:
            self.target_url = interaction.user.display_avatar.with_format(
                "png"
            ).url

        self.image: typing.Optional[bytes] = None
        self.coordinates: dict = {}

        self.output: io.BytesIO

        # Cache these, so if people re-click...
        self._with_bob: typing.Optional[io.BytesIO] = None
        self._with_eyes: typing.Optional[io.BytesIO] = None
        self._with_knob: typing.Optional[io.BytesIO] = None
        self._with_ruins: typing.Optional[io.BytesIO] = None

        super().__init__(interaction)

    async def get_faces(self) -> None:
        """Retrieve face features from Project Oxford,
        Returns True if fine."""

        session = self.interaction.client.session

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
        url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

        # Get Project Oxford reply
        async with session.post(
            url, params=params, headers=headers, data=data
        ) as resp:
            if resp.status != 200:
                raise ConnectionError(f"{await resp.json()}")
            self.coordinates = await resp.json()

        # Get target image as file
        async with session.get(self.target_url) as resp:
            if resp.status == 200:
                self.image = await resp.content.read()
            else:
                raise ConnectionError(f"Can't open image at {self.target_url}")

    async def push_ruins(self) -> discord.InteractionMessage:
        """Push the Local man ruins everything image to view"""
        if self.image is None:
            await self.get_faces()

        def draw() -> io.BytesIO:
            """Generates the Image"""
            if self._with_ruins is not None:
                return self._with_ruins

            self.image = typing.cast(bytes, self.image)
            img = ImageOps.fit(Image.open(io.BytesIO(self.image)), (256, 256))
            base = Image.open("Images/local man.png")
            base.paste(img, box=(175, 284, 431, 540))

            base.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup
            img.close()
            base.close()

            self._with_ruins = output
            return output

        self.output = await asyncio.to_thread(draw)
        return await self.update()

    async def push_eyes(self) -> discord.InteractionMessage:
        """Draw the googly eyes"""
        if self.image is None:
            await self.get_faces()

        def draw_eyes() -> io.BytesIO:
            """Draws the eyes"""
            if self._with_eyes is not None:
                return self._with_eyes

            self.image = typing.cast(bytes, self.image)
            image = Image.open(io.BytesIO(self.image))
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

            self._with_eyes = output
            return output

        self.output = await asyncio.to_thread(draw_eyes)
        return await self.update()

    async def push_knob(self) -> discord.InteractionMessage:
        """Push the bob ross image to View"""
        if self.image is None:
            await self.get_faces()

        def draw_knob() -> io.BytesIO:
            """Draw a knob in someone's mouth for the knob command"""
            if self._with_knob is not None:
                return self._with_knob

            self.image = typing.cast(bytes, self.image)
            image = Image.open(io.BytesIO(self.image)).convert(mode="RGBA")
            knob = Image.open("Images/knob.png")

            for coords in self.coordinates:
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

            self._with_knob = output
            return output

        self.output = await asyncio.to_thread(draw_knob)
        return await self.update()

    async def push_bob(self) -> discord.InteractionMessage:
        """Push the bob ross image to View"""
        if self.image is None:
            await self.get_faces()

        def draw() -> io.BytesIO:
            """Add bob ross overlay to image."""
            if self._with_bob is not None:
                return self._with_bob

            self.image = typing.cast(bytes, self.image)
            image = Image.open(io.BytesIO(self.image)).convert(mode="RGBA")
            bob = Image.open("Images/ross face.png")
            for coords in self.coordinates:
                pos_x = int(coords["faceRectangle"]["left"])
                pos_y = int(coords["faceRectangle"]["top"])
                wid = int(coords["faceRectangle"]["width"])
                hght = int(coords["faceRectangle"]["height"])
                roll = int(coords["faceAttributes"]["headPose"]["roll"]) * -1
                top_lef = int(pos_x - (wid / 4))
                btm_lef = int(pos_y - (hght / 2))
                top_rig = int(pos_x + (wid * 1.25))
                bot_rig = int((pos_y + (hght * 1.25)))

                box = (top_rig - top_lef, bot_rig - btm_lef)
                this = ImageOps.fit(bob, box).rotate(roll)
                image.paste(this, box=box, mask=this)
            image.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            image.close()
            bob.close()
            self._with_bob = output
            return output

        self.output = await asyncio.to_thread(draw)
        return await self.update()

    async def update(self) -> discord.InteractionMessage:
        """Push the latest versio of the view to the user"""
        self.clear_items()

        funcs = [
            view_utils.Funcable("Eyes", self.push_eyes, emoji="👀"),
            view_utils.Funcable("Bob Ross", self.push_bob, emoji="🖌️"),
            view_utils.Funcable("Ruins", self.push_ruins, emoji="🏚️"),
        ]

        i = self.interaction
        if not isinstance(i.channel, discord.PartialMessageable):
            if i.channel:
                if i.channel.is_nsfw():
                    btn = view_utils.Funcable("Knob", self.push_knob)
                    btn.emoji = "🍆"
                    funcs.append(btn)

        self.add_function_row(funcs)

        embed = discord.Embed(colour=0xFFFFFF, description=i.user.mention)
        embed.add_field(name="Source Image", value=self.target_url)
        embed.set_image(url="attachment://img")
        file = discord.File(fp=self.output, filename="img")

        edit = self.interaction.edit_original_response
        return await edit(attachments=[file], embed=embed, view=self)


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
        interaction: discord.Interaction[Bot],
        user: Optional[discord.User],
        link: Optional[str],
        file: Optional[discord.Attachment],
    ) -> discord.InteractionMessage:
        """Draw Googly eyes on an image. Mention a user to use their avatar.
        Only works for human faces."""
        await interaction.response.defer(thinking=True)
        return await ImageView(interaction, user, link, file).push_eyes()

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def ruins(
        self,
        interaction: discord.Interaction[Bot],
        user: Optional[discord.User],
        link: Optional[str],
        file: Optional[discord.Attachment],
    ) -> discord.InteractionMessage:
        """Local man ruins everything"""
        await interaction.response.defer(thinking=True)
        return await ImageView(interaction, user, link, file).push_ruins()

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def bob_ross(
        self,
        interaction: discord.Interaction[Bot],
        user: Optional[discord.User],
        link: Optional[str],
        file: Optional[discord.Attachment],
    ) -> discord.InteractionMessage:
        """Draw Bob Ross Hair on an image. Only works for human faces."""

        await interaction.response.defer()
        return await ImageView(interaction, user, link, file).push_bob()

    @images.command()
    @discord.app_commands.guild_only()
    async def tinder(
        self, interaction: discord.Interaction[Bot]
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
