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
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Event listener for when commands raise exceptions"""
        if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
            return  # Fail silently.

        if isinstance(error, DisabledCommand):
            return await react(ctx, '🚫')
        
        # Embed errors.
        e = discord.Embed()
        e.colour = discord.Colour.red()
        e.title = f"Error: {error.__class__.__name__}"
        e.set_thumbnail(url=str(ctx.me.display_avatar.url))

        usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"
        e.add_field(name="Command Usage Example", value=usage)
        
        if isinstance(error, commands.NoPrivateMessage):
            if ctx.guild is None:
                e.title = 'NoPrivateMessage'  # Ugly override.
                e.description = '🚫 This command cannot be used in DMs'

        elif isinstance(error, commands.BotMissingPermissions):
            if len(error.missing_permissions) == 1:
                perm_string = error.missing_permissions[0]
            else:
                last_perm = error.missing_permissions.pop(-1)
                perm_string = ", ".join(error.missing_permissions) + " and " + last_perm

            e.description = f'\🚫 I need {perm_string} permissions to do that.\n'
            fixing = f'Use {ctx.me.mention} `disable {ctx.command}` to disable this command\n' \
                     f'Use {ctx.me.mention} `prefix remove {ctx.prefix}` ' \
                     f'to stop me using the `{ctx.prefix}` prefix\n' \
                     f'Or give me the missing permissions and I can perform this action.'
            e.add_field(name="Fixing This", value=fixing)
        
        elif isinstance(error, commands.BadUnionArgument):
            e.description = f"Invalid input {error.param.name} provided."
            
        elif isinstance(error, commands.ChannelNotFound):
            e.description = f"No channel called #{error.argument} found on this server."
        
        elif isinstance(error, commands.MissingRequiredArgument):
            print(f'Missing Argument Error: {ctx.command} - {error.param.name}')
            e.description = f"{error.param.name} is a required argument but was not provided"
        
        elif isinstance(error, commands.CommandOnCooldown):
            e.description = f'⏰ On cooldown for {str(error.retry_after).split(".")[0]}s'
            return await ctx.bot.reply(ctx, embed=e, delete_after=2)
                
        elif isinstance(error, commands.NSFWChannelRequired):
            e.description = f"🚫 This command can only be used in NSFW channels."
        
        elif isinstance(error, commands.CommandInvokeError):
            cie = error.original
            if isinstance(cie, AssertionError):
                e.title = "Sorry."
                e.description = "".join(cie.args)

            location = "a DM" if ctx.guild is None else f"#{ctx.channel.name} on {ctx.guild.name} ({ctx.guild.id})"
            
            print(f"Command invoke Error occured in {location} ({ctx.author})")
            print(f"Command ran: {ctx.message.content}")

            traceback.print_tb(cie.__traceback__)
            print(f'{cie.__class__.__name__}: {cie}\n')

            e.title = error.original.__class__.__name__
            e.clear_fields()
            e.add_field(name="Internal Error", value="Painezor has been notified of this error.", inline=False)
            
        # Handle the
        elif not ctx.channel.permissions_for(ctx.me).send_messages:
            return await ctx.author.send(f'Unable to run {ctx.command} command in {ctx.channel} on {ctx.guild}, '
                                         f'I cannot send messages there')
        
        
        await ctx.bot.reply(ctx, text='An error occurred when running your command', embed=e)

            
def setup(bot):
    """Load the error handling Cog into the bot"""
    bot.add_cog(Errors(bot))
