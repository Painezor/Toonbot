"""Custom Help-formatting for displaying information on how to use commands within Toonbot"""
import discord
from discord.ext import commands

INV = f"[Join the Toonbot Help & Testing Discord](http://www.discord.gg/a5NHvPx)" \
      f"\n[Donate to the Author](https://paypal.me/Toonbot)"


class Help(commands.HelpCommand):
    """The Toonbot help command."""

    async def command_callback(self, ctx, *, command=None):
        """Get the command's invocation context."""
        e = discord.Embed()
        e.set_thumbnail(url=self.context.me.display_avatar.url)
        e.colour = 0x2ecc71
        e.description = "```yaml\nToonbot now uses slash commands due to changes made by Discord.\n" \
                        "If you do not see any commands when you type a '/' kick and re-invite the bot to your server."
        e.add_field(name="Links", value=INV, inline=False)
        await ctx.reply(embed=e)


class HelpCog(commands.Cog):
    """If you need help for help, you're beyond help"""
    def __init__(self, bot):
        self._original_help_command = bot.help_command
        bot.help_command = Help()
        bot.help_command.cog = self
        self.bot = bot

    def cog_unload(self):
        """Reset to default help formatter when cog is unloaded."""
        self.bot.help_command = self._original_help_command


def setup(bot):
    """Load Custom Help Command into the bot."""
    bot.add_cog(HelpCog(bot))
