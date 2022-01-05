"""Error Handling for Commands"""
import traceback

import discord
from discord.ext import commands
from discord.ext.commands import DisabledCommand


async def react(ctx, emoji):
    """Add a Discord reaction to a message"""
    try:
        await ctx.message.add_reaction(emoji)
    except discord.HTTPException:
        pass


class Errors(commands.Cog):
    """Error Handling Cog"""

    # @commands.Cog.listener()
    # async def on_application_command_error(self, ctx, error):
    #     """Event listener for when commands raise exceptions"""
    #     #     if isinstance(error, DisabledCommand):
    #     #         return await react(ctx, content='🚫')
    #
    #     # Embed Assertion errors.
    #     e = discord.Embed()
    #     e.colour = discord.Colour.red()
    #     e.title = f"Error: {error.__class__.__name__}"
    #     e.description = error.original.message
    #     return await self.bot.reply(ctx, embed=e, ephemeral=True)
    # #
    #     if isinstance(error, commands.NoPrivateMessage):
    #         if ctx.guild is None:
    #             e.title = '\🚫 NoPrivateMessage'
    #             e.description = '```yaml\nThis command cannot be used in DMs```'
    #
    #     elif isinstance(error, commands.MissingPermissions):
    #         e.title = "\🚫 Access Denied"
    #         _ = ", ".join(error.missing_permissions)
    #         e.description = f'You do not have these required permissions to run this command.```yaml\n{_}```'
    #
    #     elif isinstance(error, commands.BotMissingPermissions):
    #         e.title = "\🚫 Missing Permissions"
    #         _ = ", ".join(error.missing_permissions)
    #         e.description = f'I do not have these required permissions to run this command.```yaml\n{_}```'
    #
    #     elif isinstance(error, commands.BadUnionArgument):
    #         e.description = f"Invalid input {error.param.name} provided."
    #         e.add_field(name="Command Usage Example", value=usage)
    #
    #     elif isinstance(error, commands.MissingRequiredArgument):
    #         print(f'Missing Argument Error: {ctx.command} - {error.param.name}')
    #         e.description = f"{error.param.name} is a required argument but was not provided"
    #         e.add_field(name="Command Usage Example", value=usage)
    #
    #     elif isinstance(error, commands.ChannelNotFound):
    #         e.description = f"No channel called #{error.argument} found on this server."
    #
    #     elif isinstance(error, commands.CommandOnCooldown):
    #         e.description = f'⏰ On cooldown for {str(error.retry_after).split(".")[0]}s'
    #         return await ctx.bot.reply(ctx, embed=e, delete_after=2)
    #
    #     elif isinstance(error, commands.NSFWChannelRequired):
    #         e.title = "\🚫 NSFW Only"
    #         e.description = f"This command can only be used in NSFW channels."
    #
    #     elif isinstance(error, commands.CommandInvokeError):
    #         cie = error.original
    #         if isinstance(cie, AssertionError):
    #             e.title = "Sorry."
    #             e.description = "".join(cie.args)
    #
    #         location = "a DM" if ctx.guild is None else f"#{ctx.channel.name} on {ctx.guild.name} ({ctx.guild.id})"
    #
    #         print(f"Command invoke Error occurred in {location} ({ctx.author})")
    #         print(f"Command ran: {ctx.message.content}")
    #
    #         traceback.print_tb(cie.__traceback__)
    #         print(f'{cie.__class__.__name__}: {cie}\n')
    #
    #         e.title = error.original.__class__.__name__
    #         e.clear_fields()
    #         e.add_field(name="Internal Error", value="Painezor has been notified of this error.", inline=False)
    #
    #     elif isinstance(error, commands.CheckFailure):
    #         return
    #
    #     await ctx.bot.reply(ctx, content='An error occurred when running your command', embed=e)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Event listener for when commands raise exceptions"""
        if isinstance(error, commands.CommandNotFound):
            return  # Fail silently.

        if isinstance(error, DisabledCommand):
            return await react(ctx, '🚫')

        # Embed errors.
        e = discord.Embed()
        e.colour = discord.Colour.red()
        e.title = f"Error: {error.__class__.__name__}"
        e.set_thumbnail(url=str(ctx.me.display_avatar.url))

        usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"

        if isinstance(error, commands.NoPrivateMessage):
            if ctx.guild is None:
                e.title = '\🚫 NoPrivateMessage'
                e.description = '```yaml\nThis command cannot be used in DMs```'

        elif isinstance(error, commands.MissingPermissions):
            e.title = "\🚫 Access Denied"
            _ = ", ".join(error.missing_permissions)
            e.description = f'You do not have these required permissions to run this command.```yaml\n{_}```'

        elif isinstance(error, commands.BotMissingPermissions):
            e.title = "\🚫 Missing Permissions"
            _ = ", ".join(error.missing_permissions)
            e.description = f'I do not have these required permissions to run this command.```yaml\n{_}```'

        elif isinstance(error, commands.BadUnionArgument):
            e.description = f"Invalid input {error.param.name} provided."
            e.add_field(name="Command Usage Example", value=usage)

        elif isinstance(error, commands.MissingRequiredArgument):
            print(f'Missing Argument Error: {ctx.command} - {error.param.name}')
            e.description = f"{error.param.name} is a required argument but was not provided"
            e.add_field(name="Command Usage Example", value=usage)

        elif isinstance(error, commands.ChannelNotFound):
            e.description = f"No channel called #{error.argument} found on this server."

        elif isinstance(error, commands.CommandOnCooldown):
            e.description = f'⏰ On cooldown for {str(error.retry_after).split(".")[0]}s'
            return await ctx.bot.reply(ctx, embed=e, delete_after=2)

        elif isinstance(error, commands.NSFWChannelRequired):
            e.title = "\🚫 NSFW Only"
            e.description = f"This command can only be used in NSFW channels."
        
        elif isinstance(error, commands.CommandInvokeError):
            cie = error.original
            if isinstance(cie, AssertionError):
                e.title = "Sorry."
                e.description = "".join(cie.args)

            location = "a DM" if ctx.guild is None else f"#{ctx.channel.name} on {ctx.guild.name} ({ctx.guild.id})"

            print(f"Command invoke Error occurred in {location} ({ctx.author})")
            print(f"Command ran: {ctx.message.content}")

            traceback.print_tb(cie.__traceback__)
            print(f'{cie.__class__.__name__}: {cie}\n')

            e.title = error.original.__class__.__name__
            e.clear_fields()
            e.add_field(name="Internal Error", value="Painezor has been notified of this error.", inline=False)

        elif isinstance(error, commands.CheckFailure):
            return

        await ctx.bot.reply(ctx, content='An error occurred when running your command', embed=e)

            
def setup(bot):
    """Load the error handling Cog into the bot"""
    bot.add_cog(Errors(bot))
