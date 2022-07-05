"""Error Handling for Commands"""
from typing import TYPE_CHECKING, Union

from discord import Message, Interaction
from discord.app_commands import CommandInvokeError, BotMissingPermissions, MissingPermissions
from discord.ext.commands import Cog, NotOwner

from ext.quotes import OptedOutError, TargetOptedOutError

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Errors(Cog):
    """Error Handling Cog"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot
        self.bot.tree.on_error = self.error_handler

    async def error_handler(self, i: Interaction, error) -> Message:
        """Event listener for when commands raise exceptions"""
        # Unpack CIE
        if isinstance(error, NotOwner):
            return await self.bot.error(i, 'You do not own this bot.')

        if isinstance(error, CommandInvokeError):
            error = error.original

        match error:
            case TargetOptedOutError() | OptedOutError():  # QuoteDB Specific
                return await self.bot.error(i, error.args[0])
            case BotMissingPermissions():
                miss = ', '.join(error.missing_permissions)
                return await self.bot.error(i, f"The bot requires the {miss} permissions to run this command")
            case MissingPermissions():
                miss = ', '.join(error.missing_permissions)
                return await self.bot.error(i, f"You required {miss} permissions to run this command")
            case _:
                try:
                    return await self.bot.error(i, 'An Internal error occurred.')
                finally:
                    if i.command.parent:
                        print(f'/{i.command.parent.name} {i.command.name}')
                    else:
                        print(f'/{i.command.name}')
                    raise error


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Load the error handling Cog into the bot"""
    await bot.add_cog(Errors(bot))
