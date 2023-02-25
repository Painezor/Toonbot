"""Custom Utilities revolving around the usage of Discord Embeds"""
from __future__ import annotations

from asyncio import to_thread
from io import BytesIO

from aiohttp import ClientSession
from colorthief import ColorThief
from discord import Message, File, Colour, Embed, Interaction

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core import Bot


async def embed_image(
    interaction: Interaction[Bot],
    embed: Embed,
    image: BytesIO | bytes,
    filename: str = "file",
) -> Message:
    """Utility / Shortcut to upload image & set it within an embed."""
    filename = filename.replace("_", "").replace(" ", "").replace(":", "")
    embed.set_image(url=f"attachment://{filename}")
    file = File(fp=image, filename=filename)
    return await interaction.client.reply(interaction, file=file, embed=embed)


async def get_colour(url: str) -> Colour | int:
    """Use colour thief to grab a sampled colour from an image for an Embed"""
    if url is None:
        return Colour.og_blurple()
    async with ClientSession() as cs:
        async with cs.get(url) as resp:
            raw = await resp.read()

    try:
        container = BytesIO(raw)
        c = await to_thread(ColorThief(container).get_color)
        # Convert to base 16 int.
        return int("%02x%02x%02x" % c, 16)
    except ValueError:
        return Colour.og_blurple()


def rows_to_embeds(
    e: Embed,
    items: list[str],
    rows: int = 10,
    header: str = "",
    footer: str = "",
) -> list[Embed]:
    """Create evenly distributed rows of text from a list of data"""
    desc: str = f"{header}\n" if header else ""
    count: int = 0
    embeds: list[Embed] = []

    for row in items:
        # If we hit embed size limit or max count (max_rows)
        if len(f"{desc}{footer}{row}") <= 4096:
            if count < rows:
                desc += f"{row}\n"
                count += 1
                continue

        if footer is not None:  # Usually "```" to end a codeblock
            desc += footer

        e.description = desc
        embeds.append(e.copy())

        # Reset loop
        desc = f"{header}\n{row}\n" if header else f"{row}\n"
        count = 1

    e.description = f"{desc}{footer}" if footer is not None else desc
    embeds.append(e.copy())
    return embeds


def stack_embeds(embeds: list[Embed]) -> list[list[Embed]]:
    """Paginate a list of embeds up to the maximum size for a Message"""
    this_iter: list[Embed] = []
    output: list[list[Embed]] = []
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
