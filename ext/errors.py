"""Error Handling for Commands"""
from typing import TYPE_CHECKING, Optional, Union

from discord import Message, Embed, Colour, Interaction, ButtonStyle
from discord.app_commands import ContextMenu, Command, CommandInvokeError, BotMissingPermissions, MissingPermissions
from discord.ext.commands import Context, Cog
from discord.ui import View, Button

from ext.quotes import OptedOutError, TargetOptedOutError, NoSelfQuotesError

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


class Errors(Cog):
    """Error Handling Cog"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot
        self.bot.tree.on_error = self.error_handler

    @Cog.listener()
    async def on_command_error(self, ctx: Context, _) -> Optional[Message]:
        """Event listener for .tb commands"""
        e: Embed = Embed(title="Toonbot now uses Slash Commands", color=Colour.blurple())
        e.set_thumbnail(url=ctx.bot.user.avatar.url)
        e.description = f'{ctx.bot.user.name} no longer supports using commands starting with {ctx.prefix}\n\n' \
                        'Instead due to discord changes, all commands have been moved to /slash_commands\n\n' \
                        'If you are the server owner and do not see any slash commands listed, re-invite the bot' \
                        ' using the link below.'
        view = View().add_item(Button(style=ButtonStyle.url, url=self.bot.invite, label="Colour picker."))
        return await ctx.reply(embed=e, view=view)

    async def error_handler(self, i: Interaction, _: Command | ContextMenu, error) -> Message:
        """Event listener for when commands raise exceptions"""
        # Unpack CIE
        if isinstance(error, CommandInvokeError):
            error = error.original

        match error:
            case TargetOptedOutError() | OptedOutError() | NoSelfQuotesError():  # QuoteDB Specific
                return await self.bot.error(i, error.args[0])
            case BotMissingPermissions():
                miss = ''.join(error.missing_permissions)
                return await self.bot.error(i, f"The bot requires the {miss} permissions to run this command")
            case MissingPermissions():
                miss = ''.join(error.missing_permissions)
                return await self.bot.error(i, f"You required {miss} permissions to run this command")
            case _:
                try:
                    return await self.bot.error(i, 'An Internal error occurred.')
                finally:
                    raise error


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Load the error handling Cog into the bot"""
    await bot.add_cog(Errors(bot))
