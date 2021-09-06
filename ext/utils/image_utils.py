"""Utilities for Image manipulation"""
from io import BytesIO
from typing import List

import discord
from PIL import Image


# Dump Image Util
async def dump_image(ctx, img):
    """Dump an image to discord so it's URL can be used in an embed"""
    if img is None:
        return None
    ch = ctx.bot.get_channel(874655045633843240)
    img_msg = await ch.send(file=discord.File(fp=img, filename="embed_image.png"))
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


def stitch_vertical(images) -> BytesIO or None:
    """Stitch Images Vertically"""
    if not images:
        return None

    if len(images) == 1:
        return next(images)

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
