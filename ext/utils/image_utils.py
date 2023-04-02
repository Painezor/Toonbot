"""Utilities for Image manipulation"""
from __future__ import annotations

import io

from PIL import Image


def stitch(images: list[Image.Image]) -> io.BytesIO:
    """Stitch images side by side"""
    # images is a list of opened PIL images.
    wid = int(images[0].width / 3 * 2 + sum(i.width / 3 for i in images))
    hgt = images[0].height
    canvas = Image.new("RGB", (wid, hgt))
    x_pos = 0
    for i in images:
        canvas.paste(i, (x_pos, 0))
        x_pos += int(i.width / 3)
    canvas.save(output := io.BytesIO(), "PNG")

    output.seek(0)
    return output


def stitch_vertical(images: list[io.BytesIO]) -> io.BytesIO:
    """Stitch Images Vertically"""
    if len(images) == 1:
        return images[0]

    img = [Image.open(i) for i in images]

    width = img[0].width
    canvas = Image.new("RGB", (width, sum(i.height for i in img)))
    y_pos = 0
    for i in img:
        canvas.paste(i, (0, y_pos))
        y_pos += i.height
    canvas.save(output := io.BytesIO(), "PNG")
    output.seek(0)
    canvas.close()

    for i in img:
        i.close()

    return output
