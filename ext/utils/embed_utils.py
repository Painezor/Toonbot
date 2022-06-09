"""Custom Utilities revolving around the usage of Discord Embeds"""
from asyncio import to_thread
from copy import deepcopy
from io import BytesIO
from typing import List

import aiohttp
from colorthief import ColorThief
from discord import Message, File, Colour, Embed, Interaction


async def embed_image(interaction: Interaction, e: Embed, image: BytesIO | bytes, filename: str = None) -> Message:
    """Utility / Shortcut to upload image & set it within an embed."""
    filename = filename.replace('_', '').replace(' ', '').replace(':', '')
    e.set_image(url=f"attachment://{filename}")
    file = File(fp=image, filename=filename)
    return await interaction.client.reply(interaction, file=file, embed=e)


async def get_colour(url: str) -> Colour | int:
    """Use colour thief to grab a sampled colour from an image for an Embed"""
    if url is None:
        return Colour.og_blurple()
    async with aiohttp.ClientSession() as cs:
        async with cs.get(url) as resp:
            r = await resp.read()

    try:
        f = BytesIO(r)
        c = await to_thread(ColorThief(f).get_color)
        # Convert to base 16 int.
        return int('%02x%02x%02x' % c, 16)
    finally:
        return Colour.og_blurple()


def rows_to_embeds(e: Embed, rows: List[str], max_rows: int = 10, header: str = "", footer: str = "") -> List[Embed]:
    """Create evenly distributed rows of text from a list of data"""
    desc: str = header + "\n" if header else ""
    count: int = 0
    embeds: list[Embed] = []

    for row in rows:
        # If we hit embed size limit or max count (max_rows)
        if len(desc + footer + row) <= 4096:
            if count < max_rows:
                desc += f"{row}\n"
                count += 1
                continue

        if footer:  # Usually "```" to end a codeblock
            desc += footer

        e.description = desc
        embeds.append(deepcopy(e))

        # Reset loop
        desc = f"{header}\n{row}\n" if header else f"{row}\n"
        count = 1

    desc += footer
    e.description = desc
    embeds.append(deepcopy(e))
    return embeds


def stack_embeds(embeds: List[Embed]) -> List[List[Embed]]:
    """Paginate a list of embeds up to the maximum size for a discord Message"""
    this_iter: List[Embed] = []
    output: List[List[Embed]] = []
    length: int = 0

    for x in embeds:
        if length + len(x) < 6000 and len(this_iter) < 10:
            length += len(x)
            this_iter.append(x)
        else:
            output.append(this_iter)
            this_iter = [x]
            length = len(x)

    output.append(this_iter)
    return output
