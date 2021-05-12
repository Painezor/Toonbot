from collections import Counter

from discord.ext import commands


class GlobalChecks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_check(self.disabled_commands)
        self.bot.add_check(self.ignored)
        self.bot.commands_used = Counter()
    
    def ignored(self, ctx):
        return ctx.author.id not in self.bot.ignored
    
    def disabled_commands(self, ctx):
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


class Reactions(commands.Cog):
    """This is a utility cog for the r/NUFC discord to react to certain messages. This category has no commands."""
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_command(self, ctx):
        self.bot.commands_used[str(ctx.command)] += 1
    
    # TODO: Move to notifications.
    # TODO: Create custom Reaction setups per server
    # TODO: Bad words filter.

def setup(bot):
    bot.add_cog(Reactions(bot))
    bot.add_cog(GlobalChecks(bot))
