"""Custom Utilities revolving around the usage of Discord Embeds"""
from __future__ import annotations

import asyncio
import io
import logging
import typing

import aiohttp
import discord
from PIL import Image

logger = logging.getLogger("embed_utils")

T = typing.TypeVar("T")
User: typing.TypeAlias = discord.User | discord.Member


def user_to_author(embed: discord.Embed, user: User) -> discord.Embed:
    """Add a user's name, id, and profile picture to the author field"""
    name = f"{user} ({user.id})"
    embed.set_author(name=name, icon_url=user.display_avatar.url)
    return embed


def user_to_footer(
    embed: discord.Embed,
    user: discord.User | discord.Member,
    reason: typing.Optional[str] = None,
) -> discord.Embed:
    """Add the user's name, id, avatar, and an optional reason to the footer of
    an embed"""
    icon = user.display_avatar.url

    text = f"{user}\n{user.id}"
    if reason:
        text += f"\n{reason}"

    embed.set_footer(text=text, icon_url=icon)
    return embed


async def get_colour(url: str) -> discord.Colour | int:
    """Use colour thief to grab a sampled colour from an image for an Embed"""
    if url is None:
        return discord.Colour.og_blurple()
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            raw = await resp.read()

    def get_dominant_color(container: io.BytesIO) -> tuple:
        img = Image.open(container)
        img = img.convert("RGB")
        img = img.resize((1, 1), resample=0)
        dominant_color = img.getpixel((0, 0))
        return dominant_color

    colour = await asyncio.to_thread(get_dominant_color, io.BytesIO(raw))
    try:
        logger.info("Get_dominant_color returns %s", colour)
        return discord.Colour.from_rgb(*colour)
    except (TypeError, ValueError):
        logger.info("get_dominant_color => %s", colour)
        return discord.Colour.og_blurple()


def paginate(items: list[T], num: int = 25) -> list[list[T]]:
    """Paginate a list into a list of lists of length num"""
    return [items[i : i + num] for i in range(0, len(items), num)]


def rows_to_embeds(
    embed: discord.Embed,
    items: list[str],
    rows: int = 10,
    footer: str = "",
    max_length: int = 4096,
) -> list[discord.Embed]:
    """Create evenly distributed rows of text from a list of data"""

    desc = embed.description if embed.description else ""

    count: int = 0
    embeds: list[discord.Embed] = []

    current = embed.copy()
    for row in items:
        # If we haven't hit embed size limit or max count (max_rows)
        if len(f"{desc}{footer}{row}") <= max_length & count < rows:
            desc += f"{row}\n"
            count += 1
            continue

        current.description = desc + footer
        embeds.append(current)
        current = embed.copy()

        # Reset loop
        count = 1

    current.description = desc + footer
    embeds.append(current)
    return embeds


def stack_embeds(embeds: list[discord.Embed]) -> list[list[discord.Embed]]:
    """Paginate a list of embeds up to the maximum size for a Message"""
    this_iter: list[discord.Embed] = []
    output: list[list[discord.Embed]] = []
    length: int = 0

    for i in embeds:
        if length + len(i) < 6000 and len(this_iter) < 10:
            length += len(i)
            this_iter.append(i)
        else:
            output.append(this_iter)
            this_iter = [i]
            length = len(i)

    output.append(this_iter)
    return output
