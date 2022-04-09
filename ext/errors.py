"""Error Handling for Commands"""
from pprint import pprint
from typing import TYPE_CHECKING, Optional

from discord import Message, Embed, Colour, Interaction
from discord.app_commands import AppCommandError, ContextMenu, Command, CommandInvokeError
from discord.ext.commands import Context, Cog

if TYPE_CHECKING:
    from core import Bot

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class Errors(Cog):
    """Error Handling Cog"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot
        self.bot.tree.on_error = self.error_handler

    @Cog.listener()
    async def on_command_error(self, ctx: Context, _) -> Optional[Message]:
        """Event listener for .tb commands"""
        if not ctx.message.content.startswith('.tb'):
            return None
        e: Embed = Embed()
        e.description = '.tb commands no longer exist, Toonbot uses /slash_commands due to Discord changes\n\n' \
                        'If you do not see slash commands listed, ask your server owner to enable the "use application' \
                        ' commands" permission.\n\n' \
                        'If you are the server owner and do not see commands, re-invite the bot using ' \
                        f'{ctx.bot.invite} to give it the correct scopes.'
        e.colour = Colour.blurple()
        return await ctx.reply(embed=e)

    async def error_handler(self, interaction: Interaction, command: Command | ContextMenu, error: AppCommandError) \
            -> Optional[Message]:
        """Event listener for when commands raise exceptions"""
        print("==== START OF ERROR ====")
        # Prettyprint dicts.
        pprint(command)
        pprint(error)
        print("==== END OF ERROR ====")

        if isinstance(error, CommandInvokeError):
            return await self.bot.error(interaction, 'An Internal error occurred.')
        raise error


async def setup(bot: 'Bot') -> None:
    """Load the error handling Cog into the bot"""
    await bot.add_cog(Errors(bot))
