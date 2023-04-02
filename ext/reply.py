"""Reply Handling for bots"""
from __future__ import annotations

import logging
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils


if typing.TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


logger = logging.getLogger("reply")


async def error(
    i: discord.Interaction[Bot | PBot],
    content: str,
    followup: bool = True,
    **kwargs,
) -> discord.Message | None:
    """Send a Generic Error Embed"""
    embed = discord.Embed(colour=discord.Colour.red(), description=content)

    kwargs.pop("view", None)

    view = view_utils.BaseView(i)
    view.add_item(view_utils.Stop())
    return await reply(
        i, embed=embed, ephemeral=True, webhook=followup, view=view, **kwargs
    )


async def reply(
    i: discord.Interaction[Bot | PBot], followup: bool = True, **kwargs
) -> discord.Message | None:
    """Generic reply handler."""
    response: discord.InteractionResponse[Bot | PBot] = i.response
    if not response.is_done():
        await response.send_message(**kwargs)
        return await i.original_response()

    att = kwargs.copy()
    if "file" in kwargs:
        att["attachments"] = [att.pop("file")]
    elif "files" in kwargs:
        att["attachments"] = att.pop("files")
    att.pop("ephemeral", None)

    try:
        return await i.edit_original_response(**att)
    except discord.HTTPException:
        if not followup:
            return  # We Tried

        webhook: discord.Webhook = i.followup
        try:
            return await webhook.send(
                **kwargs, wait=True
            )  # Return the message.
        except discord.HTTPException:
            try:
                return await i.user.send(**kwargs)
            except discord.HTTPException:
                return  # Shrug?


class Reply(commands.Cog):
    """Reply Handler"""

    def __init__(self, bot: Bot | PBot):
        self.bot: Bot | PBot = bot
        self.bot.error = error


async def setup(bot: Bot | PBot):
    """Load the reply into the bot"""
    await bot.add_cog(Reply(bot))
