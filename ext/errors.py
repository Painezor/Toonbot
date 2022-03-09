"""Error Handling for Commands"""
from pprint import pprint

from discord.ext import commands

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class Errors(commands.Cog):
    """Error Handling Cog"""

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        """Event listener for when commands raise exceptions"""
        print("==== START OF ERROR ====")
        print("Event", event)
        # Prettyprint dicts.
        pprint(args)
        pprint(kwargs)

            
def setup(bot):
    """Load the error handling Cog into the bot"""
    bot.add_cog(Errors(bot))
