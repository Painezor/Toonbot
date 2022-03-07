"""Custom Utilities revolving around the usage of Discord Embeds"""
import asyncio
import typing
from copy import deepcopy
from io import BytesIO

import aiohttp
import discord
from PIL import UnidentifiedImageError
from colorthief import ColorThief

PAGINATION_FOOTER_ICON = "http://pix.iemoji.com/twit33/0056.png"


async def embed_image(interaction, e, image, filename=None, message=None):
    """Utility / Shortcut to upload image & set it within an embed."""
    try:  # If it's an application command, defer while we process the image.
        await interaction.response.defer()
    except AttributeError:
        pass

    filename = filename.replace('_', '').replace(' ', '').replace(':', '')
    e.set_image(url=f"attachment://{filename}")
    file = make_file(image=image, name=filename)
    await interaction.client.reply(interaction, file=file, embed=e, message=message)


async def get_colour(url=None):
    """Use colour thief to grab a sampled colour from an image for an Embed"""
    if url is None or url == discord.Embed.Empty:
        return discord.Colour.og_blurple()
    async with aiohttp.ClientSession() as cs:
        async with cs.get(url) as resp:
            r = await resp.read()
            f = BytesIO(r)
            try:
                loop = asyncio.get_running_loop()
                c = await loop.run_in_executor(None, ColorThief(f).get_color)
                # Convert to base 16 int.
                return int('%02x%02x%02x' % c, 16)
            except UnidentifiedImageError:
                return discord.Colour.og_blurple()


def rows_to_embeds(base_embed, rows, rows_per=10, header="", footer="") -> typing.List[discord.Embed]:
    """Create evenly distributed rows of text from a list of data"""
    desc, count = header + "\n", 0
    embeds = []
    for row in rows:
        if len(desc + footer + row) <= 4096 and (count + 1 <= rows_per if rows_per is not None else True):
            desc += f"{row}\n"
            count += 1
        else:
            desc += footer
            base_embed.description = desc
            embeds.append(deepcopy(base_embed))
            desc, count = f"{header}\n{row}\n", 0

    desc += footer
    base_embed.description = desc
    embeds.append(deepcopy(base_embed))
    return embeds


def make_file(image=None, name=None):
    """Create a discord File object for sending images"""
    if image is None:
        return None

    return discord.File(fp=image, filename=name) if name is not None else discord.File(image)
