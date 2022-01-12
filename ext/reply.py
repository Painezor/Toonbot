"""Reply Handlers"""
import discord
from discord.ext import commands


class ReplyHandler(commands.Cog):
    """Handle Toonbot Message Replying."""

    def __init__(self, bot):
        self.bot = bot
        self.bot.reply = self.reply
        self.bot.error = self.error

    # Custom reply handler.
    async def reply(self, ctx, **kwargs):
        """Master reply handler for bot, with fallbacks."""
        if self.bot.is_closed():
            return

        if isinstance(ctx, discord.ApplicationContext):
            interaction = await ctx.respond(**kwargs)
            try:
                return await interaction.original_message()
            except AttributeError:  # actually a WebhookMessage, bot already responded
                return interaction
        elif isinstance(ctx, commands.Context):
            try:  # First we attempt to use direct reply functionality
                return await ctx.reply(**kwargs, mention_author=False)
            except discord.HTTPException:
                try:
                    return await ctx.send(**kwargs)
                except discord.HTTPException:
                    pass

            # Final fallback, DM invoker.
            try:
                target = ctx.author
                return await target.send(**kwargs)
            except discord.HTTPException:
                pass

    # Custom reply handler.
    async def error(self, ctx, text, view=None, message=None):
        """Master reply handler for bot, with fallbacks."""
        e = discord.Embed()
        e.colour = discord.Colour.red()
        e.description = text
        if view is not None:
            if message is None:
                await self.reply(ctx, embed=e, view=view, ephemeral=True)
            else:
                await message.edit(embed=e, view=view)
        else:
            if message is None:
                await self.reply(ctx, embed=e, ephemeral=True)
            else:
                await message.edit(embed=e)


def setup(bot):
    """Load the Images Cog into the bot"""
    bot.add_cog(ReplyHandler(bot))
