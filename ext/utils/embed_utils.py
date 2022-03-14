"""Custom Utilities revolving around the usage of Discord Embeds"""
from asyncio import to_thread
from copy import deepcopy
from io import BytesIO
from typing import List

import aiohttp
from PIL import UnidentifiedImageError
from colorthief import ColorThief
from discord import Message, File, Colour, Embed, Interaction


async def embed_image(interaction: Interaction, e: Embed, image: BytesIO | bytes, filename: str = None,
                      message: Message = None) -> Message:
    """Utility / Shortcut to upload image & set it within an embed."""
    if isinstance(image, bytes):
        image = BytesIO(image)

    filename = filename.replace('_', '').replace(' ', '').replace(':', '')
    e.set_image(url=f"attachment://{filename}")
    file = File(fp=image, filename=filename)
    return await interaction.client.reply(interaction, file=file, embed=e, message=message)


async def get_colour(url: str) -> Colour | int:
    """Use colour thief to grab a sampled colour from an image for an Embed"""
    if url is None:
        return Colour.og_blurple()
    async with aiohttp.ClientSession() as cs:
        async with cs.get(url) as resp:
            r = await resp.read()
            f = BytesIO(r)
            try:
                c = await to_thread(ColorThief(f).get_color)
                # Convert to base 16 int.
                return int('%02x%02x%02x' % c, 16)
            except UnidentifiedImageError:
                return Colour.og_blurple()


def rows_to_embeds(e: Embed, rows: List[str], rows_per: int = 10, header: str = "", footer: str = "") -> List[Embed]:
    """Create evenly distributed rows of text from a list of data"""
    desc, count = header + "\n", 0
    embeds = []
    for row in rows:
        if len(desc + footer + row) <= 4096 and (count + 1 <= rows_per if rows_per is not None else True):
            desc += f"{row}\n"
            count += 1
        else:
            desc += footer
            e.description = desc
            embeds.append(deepcopy(e))
            desc, count = f"{header}\n{row}\n", 0

    desc += footer
    e.description = desc
    embeds.append(deepcopy(e))
    return embeds
