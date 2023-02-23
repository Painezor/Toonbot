"""Reply Handling for bots"""
from __future__ import annotations

import logging

import discord
from discord import Embed, Interaction, Message, Colour, InteractionResponse
from discord.app_commands import (
    AppCommandError,
    BotMissingPermissions,
    MissingPermissions,
)
from discord.ext.commands import Cog, NotOwner

from ext.quotes import TargetOptedOutError, OptedOutError
from ext.utils import view_utils

from typing import TYPE_CHECKING

from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


logger = logging.getLogger("reply")


async def error(
    i: Interaction,
    content: str,
    message: Message = None,
    followup: bool = True,
    **kwargs,
) -> Message:
    """Send a Generic Error Embed"""
    e: Embed = Embed(colour=Colour.red(), description=content)

    kwargs.pop("view", None)

    v = BaseView(i)
    v.add_item(view_utils.Stop())
    return await reply(
        i,
        message=message,
        embed=e,
        ephemeral=True,
        followup=followup,
        view=v,
        **kwargs,
    )


async def reply(
    i: Interaction, message: Message = None, followup: bool = True, **kwargs
) -> Message:
    """Generic reply handler."""
    r: InteractionResponse = i.response
    if message is None and not r.is_done():
        await r.send_message(**kwargs)
        return await i.original_response()

    try:
        att = kwargs.copy()
        if "file" in kwargs:
            att["attachments"] = [att.pop("file")]
        elif "files" in kwargs:
            att["attachments"] = att.pop("files")
        att.pop("ephemeral", None)
        return await i.edit_original_response(**att)
    except discord.HTTPException:
        if not followup:
            return
        followup: discord.Webhook = i.followup
        try:
            return await followup.send(
                **kwargs, wait=True
            )  # Return the message.
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
        self, interaction: Interaction, err: AppCommandError
    ) -> Message:
        """Event listener for when commands raise exceptions"""
        # Unpack CI
        msg = f"An Internal error occurred.\n{err.args}"
        await self.bot.error(interaction, msg)

        i1 = interaction.command.qualified_name
        i2 = interaction.data.items()
        logger.error("Error from %s\n%s", i1, i2)
        raise err.with_traceback


async def setup(bot: Bot | PBot):
    """Load the reply into the bot"""
    await bot.add_cog(Reply(bot))
