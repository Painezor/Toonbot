"""Reply Handling for bots"""
from __future__ import annotations

import logging

import discord
from discord import Embed, Interaction, Message, Colour, InteractionResponse
from discord.app_commands import AppCommandError
from discord.ext.commands import Cog

from ext.utils import view_utils

from typing import TYPE_CHECKING

from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


logger = logging.getLogger("reply")


async def error(
    i: Interaction[Bot | PBot],
    content: str,
    followup: bool = True,
    **kwargs,
) -> Message | None:
    """Send a Generic Error Embed"""
    e: Embed = Embed(colour=Colour.red(), description=content)

    kwargs.pop("view", None)

    v = BaseView(i)
    v.add_item(view_utils.Stop())
    return await reply(
        i, embed=e, ephemeral=True, followup=followup, view=v, **kwargs
    )


async def reply(
    i: Interaction[Bot | PBot], followup: bool = True, **kwargs
) -> Message | None:
    """Generic reply handler."""
    r: InteractionResponse[Bot | PBot] = i.response
    if not r.is_done():
        await r.send_message(**kwargs)
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

        fl: discord.Webhook = i.followup
        try:
            return await fl.send(**kwargs, wait=True)  # Return the message.
        except discord.HTTPException:
            try:
                return await i.user.send(**kwargs)
            except discord.HTTPException:
                return  # Shrug?


class Reply(Cog):
    """Reply Handler"""

    def __init__(self, bot: Bot | PBot):
        self.bot: Bot | PBot = bot
        self.bot.reply = reply
        self.bot.error = error
        # self.bot.tree.on_error = self.error_handler

    async def error_handler(
        self, interaction: Interaction[Bot], err: AppCommandError
    ) -> Message:
        """Event listener for when commands raise exceptions"""
        # Unpack CI
        msg = f"An Internal error occurred.\n{err.args}"
        await self.bot.error(interaction, msg)

        if interaction.command:
            i1 = interaction.command.qualified_name
        else:
            i1 = "No Command."

        if interaction.data:
            i2 = interaction.data.items()
        else:
            i2 = "{}"
        logger.error("Error from %s\n%s", i1, i2)
        raise err


async def setup(bot: Bot | PBot):
    """Load the reply into the bot"""
    await bot.add_cog(Reply(bot))
