"""Error Handling for Commands"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord import Message, Interaction
from discord.app_commands import CommandInvokeError, BotMissingPermissions, MissingPermissions
from discord.ext.commands import Cog, NotOwner

from ext.quotes import OptedOutError, TargetOptedOutError

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

logger = logging.getLogger('Errors')


class Errors(Cog):
    """Error Handling Cog"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot
        self.bot.tree.on_error = self.error_handler

    async def error_handler(self, interaction: Interaction, error) -> Message:
        """Event listener for when commands raise exceptions"""
        # Unpack CIE
        if isinstance(error, CommandInvokeError):
            error = error.original

        match error:
            case NotOwner():
                return await self.bot.error(interaction, 'You do not own this bot.')
            case TargetOptedOutError() | OptedOutError():  # QuoteDB Specific
                return await self.bot.error(interaction, error.args[0])
            case BotMissingPermissions():
                miss = ', '.join(error.missing_permissions)
                return await self.bot.error(interaction, f"The bot requires the {miss} permissions to run this command")
            case MissingPermissions():
                miss = ', '.join(error.missing_permissions)
                return await self.bot.error(interaction, f"You required {miss} permissions to run this command")
            case _:
                await self.bot.error(interaction, f'An Internal error occurred.\n{error.args}')

                logger.error(f"Error from {interaction.command.qualified_name} {interaction.data.items()}")
                raise error


async def setup(bot: Bot | PBot) -> None:
    """Load the error handling Cog into the bot"""
    await bot.add_cog(Errors(bot))
