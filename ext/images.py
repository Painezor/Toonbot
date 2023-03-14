"""Various image manipulation """
from __future__ import annotations

import io
import json
import random
import asyncio
from typing import Optional
import typing

from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord import Embed, Attachment, Message, File
import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot


with open("credentials.json", "r") as f:
    credentials = json.load(f)


class ImageView(view_utils.BaseView):
    """Holder View for Image Manipulation functions."""

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
        h = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": credentials["Oxford"]["OxfordKey"],
        }
        p = {
            "returnFaceId": "False",
            "returnFaceLandmarks": "True",
            "returnFaceAttributes": "headPose",
        }
        d = json.dumps({"url": self.target_url})
        url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

        # Get Project Oxford reply
        async with session.post(url, params=p, headers=h, data=d) as resp:
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
            im = Image.open(io.BytesIO(self.image))
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
            im.save(output := io.BytesIO(), "PNG")
            output.seek(0)
            im.close()

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
            im = Image.open(io.BytesIO(self.image)).convert(mode="RGBA")
            knob = Image.open("Images/knob.png")

            for coordinates in self.coordinates:
                mlx = int(coordinates["faceLandmarks"]["mouthLeft"]["x"])
                mrx = int(coordinates["faceLandmarks"]["mouthRight"]["x"])
                lip_y = int(
                    coordinates["faceLandmarks"]["upperLipBottom"]["y"]
                )
                lip_x = int(
                    coordinates["faceLandmarks"]["upperLipBottom"]["x"]
                )

                angle = int(
                    coordinates["faceAttributes"]["headPose"]["roll"] * -1
                )
                w = int((mrx - mlx)) * 2
                h = w
                tk = ImageOps.fit(knob, (w, h)).rotate(angle)
                im.paste(tk, box=(int(lip_x - w / 2), int(lip_y)), mask=tk)

            im.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            im.close()
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
            im = Image.open(io.BytesIO(self.image)).convert(mode="RGBA")
            bob = Image.open("Images/ross face.png")
            for coordinates in self.coordinates:
                x = int(coordinates["faceRectangle"]["left"])
                y = int(coordinates["faceRectangle"]["top"])
                w = int(coordinates["faceRectangle"]["width"])
                h = int(coordinates["faceRectangle"]["height"])
                roll = (
                    int(coordinates["faceAttributes"]["headPose"]["roll"]) * -1
                )
                top_left = int(x - (w / 4))
                bottom_left = int(y - (h / 2))
                top_right = int(x + (w * 1.25))
                bottom_right = int((y + (h * 1.25)))

                this = ImageOps.fit(
                    bob, (top_right - top_left, bottom_right - bottom_left)
                ).rotate(roll)
                im.paste(
                    this,
                    box=(top_left, bottom_left, top_right, bottom_right),
                    mask=this,
                )
            im.save(output := io.BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            im.close()
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

        e = discord.Embed(colour=0xFFFFFF, description=i.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        e.set_image(url="attachment://img")
        file = discord.File(fp=self.output, filename="img")

        edit = self.interaction.edit_original_response
        return await edit(attachments=[file], embed=e, view=self)


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
        file: Optional[Attachment],
    ) -> Message:
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
        av = await interaction.user.display_avatar.with_format("png").read()

        if interaction.guild is None:
            raise

        for _ in range(10):
            match = random.choice(interaction.guild.members)
            name = match.display_name
            try:
                target = await match.display_avatar.with_format("png").read()
                break
            except AttributeError:
                continue
        else:
            return await self.bot.error(
                interaction, "Nobody swiped right on you."
            )

        def draw(image: bytes, avatar: bytes, user_name: str) -> io.BytesIO:
            """Draw Images for the tinder command"""
            # Open The Tinder Image File
            im = Image.open("Images/tinder.png").convert(mode="RGBA")

            # Prepare the Mask and set size.
            mask = ImageOps.fit(
                Image.open("Images/circle mask.png").convert("L"), (185, 185)
            )

            # Open the User's Avatar, fit to size, apply mask.
            av = ImageOps.fit(
                Image.open(io.BytesIO(avatar)).convert(mode="RGBA"), (185, 185)
            )
            av.putalpha(mask)
            im.paste(av, box=(100, 223, 285, 408), mask=mask)

            # Open the second user's avatar, do same.
            other = ImageOps.fit(
                Image.open(io.BytesIO(image)).convert(mode="RGBA"),
                (185, 185),
                centering=(0.5, 0.0),
            )
            other.putalpha(mask)
            im.paste(other, box=(313, 223, 498, 408), mask=mask)

            # Cleanup
            mask.close()
            av.close()
            other.close()

            # Write "it's a mutual match"
            text = f"You and {user_name} have liked each other."
            font = ImageFont.truetype("Whitney-Medium.ttf", 24)
            w = font.getsize(text)[0]  # Width, Height
            ImageDraw.Draw(im).text(
                (300 - w / 2, 180), text, font=font, fill="#ffffff"
            )

            im.save(out := io.BytesIO(), "PNG")
            im.close()
            out.seek(0)
            return out

        u = interaction.user.mention
        output = await asyncio.to_thread(draw, target, av, name)
        if match.id == interaction.user.id:
            caption = f"{u} matched with themself, How pathetic."
        elif match.id == self.bot.application_id:
            caption = f"{u} Fancy a shag?"
        else:
            caption = (
                f"{interaction.user.mention} matched with {match.mention}"
            )
        icon = (
            "https://cdn0.iconfinder.com/data/icons/"
            "social-flat-rounded-rects/512/tinder-512.png"
        )
        e: Embed = Embed(description=caption, colour=0xFD297B)
        e.set_author(name="Tinder", icon_url=icon)
        e.set_image(url="attachment://Tinder.png")
        file = File(fp=output, filename="Tinder.png")
        return await interaction.client.reply(interaction, file=file, embed=e)


async def setup(bot: Bot) -> None:
    """Load the Images Cog into the bot"""
    await bot.add_cog(Images(bot))
