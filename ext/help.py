"""Custom Help formatting for displaying information on how to use commands within Toonbot"""
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import embed_utils


class Help(commands.HelpCommand):
    """The Toonbot help command."""

    @property
    async def base_embed(self):
        """Generic Embed for help commands."""
        e = discord.Embed()
        e.set_thumbnail(url=self.context.me.avatar_url)
        e.colour = 0x2ecc71
        return e

    def get_command_signature(self, command):
        """Example formatting of a command's usage."""
        return f'{self.context.prefix}{command.qualified_name} {command.signature}'

    async def descriptor(self, command):
        """Basic description of command or Group"""
        string = f'• **{command.name.lower().strip()}**\n{command.short_doc.strip()}\n'
        if isinstance(command, commands.Group):
            r_s_c = await self.filter_commands(command.commands)
            if r_s_c:
                string += f"∟○ Subcommands: " + ", ".join([f"`{i.name}`" for i in r_s_c]) + "\n"

        return string

    async def send_bot_help(self, mapping):
        """Painezor's custom helpformatter"""
        # Base Embed
        e = await self.base_embed
        e.set_author(name="Toonbot Help: Category list.")

        invite_and_stuff = f"[Invite me to your discord]" \
                           f"(https://discordapp.com/oauth2/authorize?client_id=250051254783311873" \
                           f"&permissions=67488768&scope=bot)\n"
        invite_and_stuff += f"[Join my Support discord](http://www.discord.gg/a5NHvPx)\n"
        invite_and_stuff += f"[Toonbot on Github](https://github.com/Painezor/Toonbot)\n"
        invite_and_stuff += f"[Donate to the Author](https://paypal.me/Toonbot)"
        
        e.description = "Welcome to the Toonbot Help. Use the reactions below to navigate between pages.\n\n"
        e.description += f"Use {self.context.prefix}help **CategoryName** to view commands for that category only " \
                         f"(case sensitive)\n\n"
        
        e.add_field(name="Useful links", value=invite_and_stuff, inline=False)
        
        cogs = [self.context.bot.get_cog(cog) for cog in self.context.bot.cogs]
        
        embeds = []

        for cog in sorted(cogs, key=lambda x: x.qualified_name):
            cog_embeds = await self.cog_embed(cog)

            if cog_embeds:
                e.description += f"**{cog.qualified_name}**: {cog.description}\n"
                embeds += cog_embeds
                    
        embeds = [e] + embeds
        
        await embed_utils.paginate(self.context, embeds)

    async def send_cog_help(self, cog):
        """Sends help for a single category"""
        embeds = await self.cog_embed(cog)
        await embed_utils.paginate(self.context, embeds, wait_length=300)

    async def cog_embed(self, cog):
        """The Embed containing all of the help documentation for a command Category"""
        e = await self.base_embed
        runnable = await self.filter_commands(cog.get_commands())
        e.title = f'Category Help: {cog.qualified_name}'
        header = f"```fix\n{cog.description}\n```\n**Commands in this category**:\n"

        rows = sorted([await self.descriptor(command) for command in runnable])

        if not rows:
            return []

        e.add_field(value='Use help **command** to view the usage of that command.\n Subcommands are ran by using '
                          f'`{self.context.prefix}command subcommand`', name="More help", inline=False)
        embeds = embed_utils.rows_to_embeds(e, rows, header=header)
        return embeds

    async def send_group_help(self, group):
        """Send an embed containing Help documentation for a group of commands."""
        e = await self.base_embed
        e.title = f'Command help: {group.name.lower()}'
        e.description = f"```fix\n{group.help.strip()}```\nCommand usage:```{self.get_command_signature(group)}```"

        if group.aliases:
            e.description += '*Command Aliases*: ' + ', '.join([f"`{i}`" for i in group.aliases]) + "\n"

        substrings = ""
        for command in await self.filter_commands(group.commands):
            cmd_string = f"{command.short_doc.strip()}\n" if command.help is not None else ""
            cmd_string += f"`{self.get_command_signature(command)}`\n"

            if isinstance(command, commands.Group):
                filtered = await self.filter_commands(command.commands)
                if filtered:
                    cmd_string += f"∟○ Subcommands: " + ", ".join([f"`{i.name}`" for i in filtered]) + "\n"
            substrings += f"\n• {command.name}\n{cmd_string}"

        if substrings:
            e.description += "\n**Subcommands**:" + substrings + "\n"

        e.add_field(name="Command arguments",
                    value='<> around an arguments means it is a <REQUIRED argument>\n'
                          '[] around an argument means it is an [OPTIONAL argument]\n'
                          f'\nUse `{self.context.prefix}help <command> [subcommand]` for info on subcommands\n'
                          f'Don\'t type the <> or [].', inline=False)
        e.add_field(name="More help", inline=False,
                    value='Use help **command** to view the usage of that command.\n'
                          f'Subcommands are ran by using `{self.context.prefix}command subcommand`')
        
        await self.context.bot.reply(self.context, embed=e)

    async def send_command_help(self, command):
        """Send documentation for a single command"""
        e = await self.base_embed
        e.title = f'Command help: {command}'
        e.description = f"```fix\n{command.help}```"

        if command.aliases:
            e.add_field(name='Aliases', value=', '.join(f'`{alias}`' for alias in command.aliases), inline=False)

        e.add_field(name='Usage', value=f"```{self.get_command_signature(command)}```")
        e.add_field(name="Command arguments",
                    value='<> around an arguments means it is a <REQUIRED argument>\n'
                          '[] around an argument means it is an [OPTIONAL argument]\n'
                          f'\nUse `{self.context.prefix}help <command> [subcommand]` for info on subcommands',
                          inline=False)
        await self.context.bot.reply(self.context, embed=e)
    
    async def command_callback(self, ctx, *, command=None):
        """Get the command's invocation context."""
        await self.prepare_help_command(ctx, command)
        
        if command is None:
            mapping = self.get_bot_mapping()
            return await self.send_bot_help(mapping)
        
        cog = ctx.bot.get_cog(command)
        
        if cog is not None:
            return await self.send_cog_help(cog)
        
        keys = command.split(' ')
        cmd = ctx.bot.all_commands.get(keys[0])
        if cmd is None:
            string = await discord.utils.maybe_coroutine(self.command_not_found, self.remove_mentions(keys[0]))
            return await self.send_error_message(string)
        
        for key in keys[1:]:
            try:
                found = cmd.all_commands.get(key)
            except AttributeError:
                string = await discord.utils.maybe_coroutine(self.subcommand_not_found, cmd, self.remove_mentions(key))
                return await self.send_error_message(string)
            else:
                if found is None:
                    string = await discord.utils.maybe_coroutine(self.subcommand_not_found, cmd,
                                                                 self.remove_mentions(key))
                    return await self.send_error_message(string)
                cmd = found
        
        if isinstance(cmd, commands.Group):
            return await self.send_group_help(cmd)
        else:
            return await self.send_command_help(cmd)


class HelpCog(commands.Cog):
    """If you need help for help, you're beyond help"""
    def __init__(self, bot):
        self._original_help_command = bot.help_command
        reload(embed_utils)
        bot.help_command = Help()
        bot.help_command.cog = self
        self.bot = bot

    def cog_unload(self):
        """Reset to default help formatter when cog is unloaded."""
        self.bot.help_command = self._original_help_command


def setup(bot):
    """Load Custom Help Command into the bot."""
    bot.add_cog(HelpCog(bot))
