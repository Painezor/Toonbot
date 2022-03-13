"""Error Handling for Commands"""
from pprint import pprint
from typing import TYPE_CHECKING

from discord import Message
from discord.ext import commands

if TYPE_CHECKING:
    from core import Bot

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class Errors(commands.Cog):
    """Error Handling Cog"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs) -> Message | None:
        """Event listener for when commands raise exceptions"""
        print("==== START OF ERROR ====")
        print("Event", event)
        # Prettyprint dicts.
        pprint(args)
        pprint(kwargs)
        return


def setup(bot: 'Bot') -> None:
    """Load the error handling Cog into the bot"""
    bot.add_cog(Errors(bot))
