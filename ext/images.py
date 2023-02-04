"""Various image manipulation """
from __future__ import annotations

from asyncio import to_thread
from copy import deepcopy
from io import BytesIO
from json import dumps
from random import choice
from re import findall
from typing import Optional, TYPE_CHECKING

from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord import Embed, Colour, Member, Attachment, Interaction, User, Message, PartialEmoji
from discord.app_commands import command, describe, guild_only
from discord.ext.commands import Cog
from discord.ui import View
from discord.utils import utcnow

from ext.utils.embed_utils import embed_image, get_colour
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot

KNOB_ICON = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/86/18_icon_TV_%28Hungary%29.svg" \
            "/48px-18_icon_TV_%28Hungary%29.svg.png"


def message_emojis(s: str) -> list[PartialEmoji]:
    """ Returns a list of custom emojis in a message. """
    emojis = findall(r'<(?P<animated>a?):(?P<name>\w{2,32}):(?P<id>\d{18,22})>', s)
    return [PartialEmoji(animated=bool(animated), name=name, id=e_id) for animated, name, e_id in emojis]


def get_target(user: User | Member = None, link: str = None, file: Attachment = None) -> str:
    """Get the requested link from passed arguments"""
    if link is not None:
        return link
    if file is not None:
        return file.url
    return user.display_avatar.with_format("png").url


def draw_tinder(image: bytes, avatar: bytes, user_name) -> BytesIO:
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
    mask: Image = Image.open("Images/circle mask.png")
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


# TODO: XKCD Command. https://xkcd.com/json.html
# TODO: Select / Button Pass: Dropdown for ImageView
# TODO: User Commands Pass
# TODO: NSFW Knob command.

# @is_nsfw()
# @command(usage='<@user, link to image, or upload a file>')
# async def knob(self, interaction: Interaction,*, target: typing.Union[discord.Member, str] = None):
#     """Draw knobs in mouth on an image. Mention a user to use their avatar. Only works for human faces."""
#     image, response, target = await get_faces(ctx, target)
#
#     if response is None or response is False:
#         return await interaction.client.reply(interaction, content="🚫 No faces were detected in your image.")
#
#     image = await to_thread(draw_knob, image, response)
#
#     base_embed = discord.Embed()
#     base_embed.colour = 0xff66cc
#     base_embed.description = interaction.user.mention
#     base_embed.add_field(name="Source", value=target)
#     await embed_image(ctx, base_embed, image, filename="Knob.png")


class ImageView(View):
    """Holder View for Image Manipulation functions."""

    def __init__(self, bot: Bot, interaction: Interaction, target: str) -> None:
        self.interaction: Interaction = interaction
        self.coordinates: dict = {}
        self.embed: Embed | None = None
        self.image: bytes | None = None
        self.target_url: str = target
        self.bot: Bot = bot
        super().__init__()

    def draw_knob(self) -> BytesIO:
        """Draw a knob in someone's mouth for the knob command"""
        im = Image.open(BytesIO(self.image)).convert(mode="RGBA")
        knob = Image.open("Images/knob.png")

        for coordinates in self.coordinates:
            mlx = int(coordinates["faceLandmarks"]["mouthLeft"]["x"])
            mrx = int(coordinates["faceLandmarks"]["mouthRight"]["x"])
            lip_y = int(coordinates["faceLandmarks"]["upperLipBottom"]["y"])
            lip_x = int(coordinates["faceLandmarks"]["upperLipBottom"]["x"])

            angle = int(coordinates["faceAttributes"]["headPose"]["roll"] * -1)
            w = int((mrx - mlx)) * 2
            h = w
            tk = ImageOps.fit(knob, (w, h)).rotate(angle)
            im.paste(tk, box=(int(lip_x - w / 2), int(lip_y)), mask=tk)
        output = BytesIO()
        im.save(output, "PNG")
        output.seek(0)
        return output

    def draw_eyes(self) -> BytesIO:
        """Draws the eyes"""
        im: Image = Image.open(BytesIO(self.image))
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
        im.close()
        return output

    def draw_bob(self) -> BytesIO:
        """Add bob ross overlay to image."""
        im = Image.open(BytesIO(self.image)).convert(mode="RGBA")
        bob = Image.open("Images/ross face.png")
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

    async def get_faces(self) -> Optional[Message]:
        """Retrieve face features from Project Oxford"""
        # Prepare POST
        h = {"Content-Type": "application/json",
             "Ocp-Apim-Subscription-Key": self.bot.credentials['Oxford']['OxfordKey']}
        p = {"returnFaceId": "False", "returnFaceLandmarks": "True", "returnFaceAttributes": "headPose"}
        d = dumps({"url": self.target_url})
        url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"

        # Get Project Oxford reply
        async with self.bot.session.post(url, params=p, headers=h, data=d) as resp:
            match resp.status:
                case 200:
                    self.coordinates = await resp.json()
                case 400:
                    return await self.bot.error(self.interaction, await resp.json())
                case _:
                    err = f"HTTP Error {resp.status} accessing facial recognition API."
                    return await self.bot.error(self.interaction, err)

        # Get target image as file
        async with self.bot.session.get(self.target_url) as resp:
            match resp.status:
                case 200:
                    self.image = await resp.content.read()
                case _:
                    err = f"HTTP Error {resp.status} opening {self.target_url}."
                    return await self.bot.error(self.interaction, err)

    async def push_eyes(self) -> Message:
        """Draw the googly eyes"""
        if self.image is None:
            maybe_error = await self.get_faces()
            if isinstance(maybe_error, Message):
                return maybe_error

        image = await to_thread(self.draw_eyes)

        e: Embed = Embed(colour=0xFFFFFF, description=self.interaction.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        await embed_image(self.interaction, e, image, filename="eyes.png")

    async def push_knob(self) -> Message:
        """Push the bob ross image to View"""
        if self.image is None:
            maybe_error = await self.get_faces()
            if isinstance(maybe_error, Message):
                return maybe_error

        image = await to_thread(self.draw_knob)

        e: Embed = Embed(colour=0xFFFFFF, description=self.interaction.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        await embed_image(self.interaction, e, image, filename="knob.png")

    async def push_bob(self) -> Message:
        """Push the bob ross image to View"""
        if self.image is None:
            maybe_error = await self.get_faces()
            if isinstance(maybe_error, Message):
                return maybe_error

        self.image = await to_thread(self.draw_bob)

        e: Embed = Embed(colour=0xFFFFFF, description=self.interaction.user.mention)
        e.add_field(name="Source Image", value=self.target_url)
        self.embed = e
        return await self.update()

    async def update(self) -> Message:
        """Push the latest versio of the view to the user"""
        return await embed_image(self.interaction, self.embed, self.image, filename="bob.png")


class Images(Cog):
    """Image manipulation commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @command()
    @describe(user="Select a user to fetch their avatar")
    async def avatar(self, interaction: Interaction, user: User | Member = None) -> Message:
        """Shows a member's avatar"""
        await interaction.response.defer(thinking=True)

        if user is None:
            user = interaction.user

        e: Embed = Embed(description=f"{user}'s avatar", colour=user.colour)
        e.colour = user.color
        e.set_footer(text=user.display_avatar.url)
        e.set_image(url=user.display_avatar.url)
        e.timestamp = utcnow()
        return await self.bot.reply(interaction, embed=e)

    @command()
    @describe(user="pick a user", link="provide a link", file="upload a file")
    async def eyes(self, interaction: Interaction, user: Member | User = None, link: str = None,
                   file: Attachment = None) -> Message:
        """Draw Googly eyes on an image. Mention a user to use their avatar. Only works for human faces."""
        await interaction.response.defer(thinking=True)
        if user is None:
            user = interaction.user

        link = get_target(user, link, file)
        view = ImageView(self.bot, interaction, link)
        return await view.push_eyes()

    @command()
    @describe(user="Select a user", link="Provide a link to an image", file="Upload a file")
    async def ruins(self, interaction: Interaction, user: Member | User = None, link: str = None,
                    file: Attachment = None) -> Message:
        """Local man ruins everything"""
        await interaction.response.defer(thinking=True)
        if user is None:
            user = interaction.user

        link = get_target(user, link, file)
        async with self.bot.session.get(link) as resp:
            match resp.status:
                case 200:
                    image = await resp.content.read()
                case _:
                    return await self.bot.error(interaction, f"HTTP Error {resp.status} opening {link}.")

        def ruin(img: bytes):
            """Generates the Image"""
            img = ImageOps.fit(Image.open(BytesIO(img)), (256, 256))
            base = Image.open("Images/local man.png")
            base.paste(img, box=(175, 284, 431, 540))

            output = BytesIO()
            base.save(output, "PNG")
            output.seek(0)

            # Cleanup!
            img.close()
            base.close()
            return output

        image = await to_thread(ruin, image)
        return await embed_image(interaction, Embed(color=Colour.blue()), image, filename=f"ruins_everything.png")

    @command()
    @describe(user="pick a user", link="provide a link", file="upload a file")
    async def bob_ross(self, interaction: Interaction, user: User | Member = None, link: str = None,
                       file: Attachment = None) -> Message:
        """Draw Bob Ross Hair on an image. Only works for human faces."""
        if user is None:
            user = interaction.user

        await interaction.response.defer(thinking=True)
        link = get_target(user, link, file)
        view = ImageView(self.bot, interaction, link)
        return await view.push_bob()

    @command()
    @guild_only()
    async def tinder(self, interaction: Interaction) -> Message:
        """Try to Find your next date."""
        av = await interaction.user.display_avatar.with_format("png").read()

        for x in range(10):
            match = choice(interaction.guild.members)
            name = match.display_name
            try:
                target = await match.display_avatar.with_format("png").read()
                break
            except AttributeError:
                continue
        else:
            return await self.bot.error(interaction, content="Nobody swiped right on you.")

        output = await to_thread(draw_tinder, target, av, name)
        if match.id == interaction.user.id:
            caption = f"{interaction.user.mention} matched with themself, How pathetic."
        elif match.id == self.bot.user.id:
            caption = f"{interaction.user.mention} Fancy a shag?"
        else:
            caption = f"{interaction.user.mention} matched with {match.mention}"
        icon = "https://cdn0.iconfinder.com/data/icons/social-flat-rounded-rects/512/tinder-512.png"
        e: Embed = Embed(description=caption, colour=0xFD297B)
        e.set_author(name="Tinder", icon_url=icon)
        return await embed_image(interaction, e, output, filename="Tinder.png")

    @command()
    @describe(emoji="enter a list of emotes")
    async def emote(self, interaction: Interaction, emoji: str) -> Message:
        """View a bigger version of an Emoji"""
        await interaction.response.defer(thinking=True)

        if not (emojis := message_emojis(emoji)):
            return await self.bot.error(interaction, f"No emotes found in {emoji}")

        embeds = []
        for emoji in emojis:
            e: Embed = Embed(title=emoji.name)
            if emoji.animated:
                e.description = "This is an animated emoji."

            e.colour = await get_colour(emoji.url)
            e.set_image(url=emoji.url)
            e.set_footer(text=emoji.url)
            embeds.append(deepcopy(e))

        return await Paginator(interaction, embeds).update()


async def setup(bot: Bot) -> None:
    """Load the Images Cog into the bot"""
    await bot.add_cog(Images(bot))
