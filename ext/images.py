"""Various image manipulation """
from __future__ import annotations

from asyncio import to_thread
from io import BytesIO
from json import dumps
import json
from random import choice
from typing import Optional, TYPE_CHECKING

from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord import Embed, Attachment, Interaction, User, Message, File
import discord
from discord.app_commands import guild_only, Group
from discord.ext.commands import Cog

from ext.utils.view_utils import FuncButton, BaseView

if TYPE_CHECKING:
    from core import Bot


with open("credentials.json", "r") as f:
    credentials = json.load(f)


class ImageView(BaseView):
    """Holder View for Image Manipulation functions."""

    def __init__(
        self,
        interaction: Interaction[Bot],
        user: Optional[User] = None,
        link: Optional[str] = None,
        file: Optional[Attachment] = None,
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

        self.image: bytes
        self.coordinates: dict = {}

        self.output: BytesIO

        # Cache these, so if people re-click...
        self._with_bob: BytesIO
        self._with_eyes: BytesIO
        self._with_knob: BytesIO
        self._with_ruins: BytesIO

        super().__init__(interaction)

    async def get_faces(self) -> Optional[Message]:
        """Retrieve face features from Project Oxford"""
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
        d = dumps({"url": self.target_url})
        url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

        # Get Project Oxford reply
        async with self.bot.session.post(
            url, params=p, headers=h, data=d
        ) as resp:
            match resp.status:
                case 200:
                    self.coordinates = await resp.json()
                case 400:
                    return await self.bot.error(
                        self.interaction, await resp.json()
                    )
                case _:
                    err = f"{resp.status} error on facial recognition API."
                    return await self.interaction.followup.send(
                        err, ephemeral=True
                    )

        # Get target image as file
        async with self.bot.session.get(self.target_url) as resp:
            match resp.status:
                case 200:
                    self.image = await resp.content.read()
                case _:
                    return await self.bot.error(
                        self.interaction,
                        f"Error {resp.status} opening {self.target_url}.",
                    )

    async def push_ruins(self) -> Message:
        """Push the Local man ruins everything image to view"""
        if self.image is None:
            if isinstance(err := await self.get_faces(), Message):
                return err

        def draw():
            """Generates the Image"""
            if self._with_ruins is not None:
                return self._with_ruins

            img = ImageOps.fit(Image.open(BytesIO(self.image)), (256, 256))
            base = Image.open("Images/local man.png")
            base.paste(img, box=(175, 284, 431, 540))

            base.save(output := BytesIO(), "PNG")
            output.seek(0)

            # Cleanup
            img.close()
            base.close()

            self._with_ruins = output
            return output

        self.output = await to_thread(draw)
        return await self.update()

    async def push_eyes(self) -> Message:
        """Draw the googly eyes"""
        if self.image is None:
            if isinstance(err := await self.get_faces(), Message):
                return err

        def draw_eyes() -> BytesIO:
            """Draws the eyes"""
            if self._with_eyes is not None:
                return self._with_eyes

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
            im.save(output := BytesIO(), "PNG")
            output.seek(0)
            im.close()

            self._with_eyes = output
            return output

        self.output = await to_thread(draw_eyes)
        return await self.update()

    async def push_knob(self) -> Message:
        """Push the bob ross image to View"""
        if self.image is None:
            maybe_error = await self.get_faces()
            if isinstance(maybe_error, Message):
                return maybe_error

        def draw_knob() -> BytesIO:
            """Draw a knob in someone's mouth for the knob command"""
            if self._with_knob is not None:
                return self._with_knob

            im = Image.open(BytesIO(self.image)).convert(mode="RGBA")
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

            im.save(output := BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            im.close()
            knob.close()

            self._with_knob = output
            return output

        self.output = await to_thread(draw_knob)
        return await self.update()

    async def push_bob(self) -> Message:
        """Push the bob ross image to View"""
        if self.image is None:
            maybe_error = await self.get_faces()
            if isinstance(maybe_error, Message):
                return maybe_error

        def draw() -> BytesIO:
            """Add bob ross overlay to image."""
            if self._with_bob is not None:
                return self._with_bob

            im = Image.open(BytesIO(self.image)).convert(mode="RGBA")
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
            im.save(output := BytesIO(), "PNG")
            output.seek(0)

            # Cleanup.
            im.close()
            bob.close()
            self._with_bob = output
            return output

        self.output = await to_thread(draw)
        return await self.update()

    async def update(self) -> Message:
        """Push the latest versio of the view to the user"""
        self.clear_items()

        self.add_item(FuncButton(label="Eyes", func=self.push_eyes, emoji="👀"))
        self.add_item(FuncButton("Bob Ross", self.push_bob, emoji="🖌️"))
        self.add_item(FuncButton("Ruins", self.push_ruins, emoji="🏚️"))

        i = self.interaction
        if not isinstance(i.channel, discord.PartialMessageable):
            if i.channel:
                if i.channel.is_nsfw():
                    btn = FuncButton("Knob", self.push_knob, emoji="🍆")
                    self.add_item(btn)

        e: Embed = Embed(colour=0xFFFFFF, description=i.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        e.set_image(url="attachment://img")
        file = File(fp=self.output, filename="img")
        return await self.bot.reply(i, file=file, embed=e, view=self)


class Images(Cog):
    """Image manipulation commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    images = Group(name="images", description="image manipulation commands")

    @images.command()
    @discord.app_commands.describe(
        user="Select a user",
        link="Provide a link to an image",
        file="Upload a file",
    )
    async def eyes(
        self,
        interaction: Interaction[Bot],
        user: Optional[User],
        link: Optional[str],
        file: Optional[Attachment],
    ) -> Message:
        """Draw Googly eyes on an image. Mention a user to use their avatar.
        Only works for human faces."""
        await interaction.response.defer(thinking=True)
        return await ImageView(
            interaction, link=link, user=user, file=file
        ).push_eyes()

    @images.command()
    @discord.app_commands.describe(
        user="pick a user", link="provide a link", file="upload a file"
    )
    async def ruins(
        self,
        interaction: Interaction[Bot],
        user: Optional[User],
        link: Optional[str],
        file: Optional[Attachment],
    ) -> Message:
        """Local man ruins everything"""
        await interaction.response.defer(thinking=True)
        return await ImageView(interaction, user, link, file).push_ruins()

    @images.command()
    @discord.app_commands.describe(
        user="pick a user", link="provide a link", file="upload a file"
    )
    async def bob_ross(
        self,
        interaction: Interaction[Bot],
        user: Optional[User],
        link: Optional[str],
        file: Optional[Attachment],
    ) -> Message:
        """Draw Bob Ross Hair on an image. Only works for human faces."""

        await interaction.response.defer()
        return await ImageView(interaction, user, link, file).push_bob()

    @images.command()
    @guild_only()
    async def tinder(self, interaction: Interaction[Bot]) -> Message:
        """Try to Find your next date."""
        av = await interaction.user.display_avatar.with_format("png").read()

        if interaction.guild is None:
            raise

        for x in range(10):
            match = choice(interaction.guild.members)
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

        def draw_tinder(image: bytes, avatar: bytes, user_name) -> BytesIO:
            """Draw Images for the tinder command"""
            # Open The Tinder Image File
            im = Image.open("Images/tinder.png").convert(mode="RGBA")

            # Prepare the Mask and set size.
            mask = ImageOps.fit(
                Image.open("Images/circle mask.png").convert("L"), (185, 185)
            )

            # Open the User's Avatar, fit to size, apply mask.
            av = ImageOps.fit(
                Image.open(BytesIO(avatar)).convert(mode="RGBA"), (185, 185)
            )
            av.putalpha(mask)
            im.paste(av, box=(100, 223, 285, 408), mask=mask)

            # Open the second user's avatar, do same.
            other = ImageOps.fit(
                Image.open(BytesIO(image)).convert(mode="RGBA"),
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

            im.save(out := BytesIO(), "PNG")
            im.close()
            out.seek(0)
            return out

        u = interaction.user.mention
        output = await to_thread(draw_tinder, target, av, name)
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
