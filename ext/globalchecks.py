"""Handling of disabled commands and ignored users"""
from discord.ext import commands


class GlobalChecks(commands.Cog):
    """Global checks handled by the bot, ignored users & disabled commands"""
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_check(self.disabled_commands)
        self.bot.add_check(self.ignored)
    
    def ignored(self, ctx):
        """A global check to see if the user id is stored in the ignored user list"""
        return ctx.author.id not in self.bot.ignored
    
    def disabled_commands(self, ctx):
        """A global check to make sure that the command being invoked is not disabled on the target server."""
        try:
            if ctx.command.parent is not None:
                if ctx.command.parent.name in self.bot.disabled_cache[ctx.guild.id]:
                    raise commands.DisabledCommand
            
            if ctx.command.name in self.bot.disabled_cache[ctx.guild.id]:
                raise commands.DisabledCommand
            else:
                return True
        except (KeyError, AttributeError):
            return True


def setup(bot):
    """Load the global checking cog into the bot"""
    bot.add_cog(GlobalChecks(bot))
