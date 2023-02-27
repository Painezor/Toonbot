"""Utilities for Image manipulation"""
from __future__ import annotations

import io
from PIL import Image


def stitch(images: list[Image.Image]) -> io.BytesIO:
    """Stitch images side by side"""
    # images is a list of opened PIL images.
    w = int(images[0].width / 3 * 2 + sum(i.width / 3 for i in images))
    h = images[0].height
    canvas = Image.new("RGB", (w, h))
    x = 0
    for i in images:
        canvas.paste(i, (x, 0))
        x += int(i.width / 3)
    canvas.save(output := io.BytesIO(), "PNG")

    output.seek(0)
    return output


def stitch_vertical(images: list[io.BytesIO]) -> io.BytesIO:
    """Stitch Images Vertically"""
    if len(images) == 1:
        return images[0]

    img = [Image.open(i) for i in images]

    w = img[0].width
    canvas = Image.new("RGB", (w, sum(i.height for i in img)))
    y = 0
    for i in img:
        canvas.paste(i, (0, y))
        y += i.height
    canvas.save(output := io.BytesIO(), "PNG")
    output.seek(0)
    canvas.close()

    [i.close() for i in img]

    return output
