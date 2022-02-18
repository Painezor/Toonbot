"""Error Handling for Commands"""
import traceback

from discord import ApplicationCommandInvokeError
from discord import Embed, Colour, ButtonStyle
from discord.ext import commands
from discord.ui import View, Button

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class Errors(commands.Cog):
    """Error Handling Cog"""

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Redirect userrs to application commands"""
        e = Embed(title="Slash Commands Migration", colour=Colour.og_blurple())

        if ctx.channel.permissions_for(ctx.author).use_application_commands:
            e.description = "Toonbot now uses /slash commands, type / and they should be listed.\n\n" \
                            "If you do not see any commands listed, kick & re-invite the bot using the link below."
        else:
            e.description = "Toonbot now uses /slash commands, type / and they should be listed.\n\n" \
                            "Please ensure users on your server have the use_application_commands permission.\n"

        v = View()
        v.add_item(Button(style=ButtonStyle.url, url=INVITE_URL, label="Invite Toonbot", emoji="🤖"))
        await ctx.reply(view=v, embed=e)

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx, error):
        """Event listener for when commands raise exceptions"""
        print("==== START OF ERROR ====")
        print("Application command error occurred")
        print("Command: ", ctx.command.qualified_name)
        print("interaction: ", ctx.interaction)
        print("User:", ctx.user)
        print("Guild:", ctx.guild)
        print("Channel:", ctx.channel)
        print(error)
        print("==== END OF ERROR ====")

        # # Embed Assertion errors.
        e = Embed(colour=Colour.red(), title=f"Error: {error.__class__.__name__}")
        # e.description = error.original.
        # return await ctx.reply(embed=e, ephemeral=True)

        if isinstance(error, ApplicationCommandInvokeError):
            cie = error.original
            print(f'{cie.__class__.__name__}: {cie}\n')

            if isinstance(cie, AssertionError):
                e.title = "Error."
                e.description = "".join(cie.args)

            traceback.print_tb(cie.__traceback__)
            e.title = error.original.__class__.__name__
            e.clear_fields()
            e.add_field(name="Internal Error", value="Painezor has been notified of this error.", inline=False)
        else:
            print(type(error), f"error occurred when running {ctx.command} command, execution context")

        await ctx.reply(content='An error occurred when running your command', embed=e)

            
def setup(bot):
    """Load the error handling Cog into the bot"""
    bot.add_cog(Errors(bot))
