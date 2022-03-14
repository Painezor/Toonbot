"""Utilities for Image manipulation"""
from io import BytesIO
from typing import List, TYPE_CHECKING

from PIL import Image
from discord import File

if TYPE_CHECKING:
    from discord import Client


# Dump Image Util
async def dump_image(bot: 'Client', img: BytesIO):
    """Dump an image to discord & return its URL to be used in embeds"""
    ch = bot.get_channel(874655045633843240)
    img_msg = await ch.send(file=File(fp=img, filename="embed_image.png"))
    url = img_msg.attachments[0].url
    return None if url == "none" else url


def stitch(images: List[Image.Image]) -> BytesIO:
    """Stitch images side by side"""
    # images is a list of opened PIL images.
    w = int(images[0].width / 3 * 2 + sum(i.width / 3 for i in images))
    h = images[0].height
    canvas = Image.new('RGB', (w, h))
    x = 0
    for i in images:
        canvas.paste(i, (x, 0))
        x += int(i.width / 3)
    output = BytesIO()
    canvas.save(output, 'PNG')

    output.seek(0)
    return output


def stitch_vertical(images: List[BytesIO]) -> BytesIO:
    """Stitch Images Vertically"""
    if len(images) == 1:
        return images[0]

    images = [Image.open(i) for i in images]

    w = images[0].width
    h = sum(i.height for i in images)
    canvas = Image.new('RGB', (w, h))
    y = 0
    for i in images:
        canvas.paste(i, (0, y))
        y += i.height
    output = BytesIO()
    canvas.save(output, 'PNG')
    output.seek(0)
    canvas.close()

    [i.close() for i in images]

    return output
