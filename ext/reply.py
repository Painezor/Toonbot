import discord
from discord.ext import commands


def make_file(image=None, name=None):
    """Create a discord File object for sending images"""
    if image is None:
        return None

    if name is not None:
        file = discord.File(fp=image, filename=name)
    else:
        file = discord.File(image)
    return file


class ReplyHandler(commands.Cog):
    """Handle Toonbot Message Replying."""

    def __init__(self, bot):
        self.bot = bot
        self.bot.reply = self.reply

    # Custom reply handler.
    async def reply(self, ctx,
                    text: str = None,
                    view: discord.ui.View = None,
                    embed: discord.Embed = None,
                    image=None,
                    filename: str = None,
                    ping: bool = False,
                    ephemeral: bool = False,
                    delete_after: int = None):
        """Master reply handler for bot, with fallbacks."""
        if self.bot.is_closed():
            return

        try:
            image = make_file(image, filename)
        except KeyError:
            image = None

        try:  # First we attempt to use direct reply functionality
            return await ctx.reply(text, embed=embed, view=view, file=image, delete_after=delete_after,
                                   mention_author=ping)
        except discord.HTTPException:
            try:
                return await ctx.send(text, embed=embed, view=view, file=image, delete_after=delete_after,
                                      mention_author=ping)
            except discord.HTTPException:
                pass

        # Final fallback, DM invoker.
        try:
            target = ctx.author
            return await target.send(text, embed=embed, view=view, file=image, delete_after=delete_after,
                                     mention_author=ping)

        except discord.HTTPException:
            if ctx.author.id == 210582977493598208:
                print(text)

        # At least try to warn them.
        try:
            await ctx.message.add_reaction('🤐')
        except discord.HTTPException:
            return  # Fuck you then.


def setup(bot):
    """Load t he Images Cog into the bot"""
    bot.add_cog(ReplyHandler(bot))
