from importlib import reload

import discord
from discord.ext import commands

from ext.utils import embed_utils


def descriptor(command):
    string = f'• **{command.name.title().strip()}**\n*{command.short_doc.strip()}*\n'
    if isinstance(command, commands.Group):
        string += f'\n***Subcommands**:* {", ".join(f"`{sub.name}`" for sub in command.commands)}'
    return string


class Help(commands.HelpCommand):
    """The Toonbot help command."""
    def get_command_signature(self, command):
        return f'{self.context.prefix}{command.qualified_name} {command.signature}'
    
    async def send_bot_help(self, mapping):
        """Painezor's custom helpformatter"""
        # Base Embed
        e = discord.Embed()
        e.set_thumbnail(url=self.context.me.avatar_url)
        e.colour = 0x2ecc71
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
            if not cog.get_commands():
                continue  # Filter utility cogs.
            
            for command in cog.walk_commands():
                try:
                    if not await command.can_run(self.context):
                        continue
                    e.description += f"**{cog.qualified_name}**: {cog.description}\n"
                    embeds += await self.cog_embed(cog)
                    break
                except discord.ext.commands.CommandError:
                    continue
                    
        embeds = [e] + embeds
        
        await embed_utils.paginate(self.context, embeds)

    async def send_cog_help(self, cog):
        embeds = await self.cog_embed(cog)
        await embed_utils.paginate(self.context, embeds, wait_length=300)
    
    async def cog_embed(self, cog):
        e = discord.Embed()
        e.title = f'Category Help: {cog.qualified_name}'
        e.colour = 0x2ecc71
        e.set_thumbnail(url=self.context.me.avatar_url)
        header = f"```fix\n{cog.description}\n```\n**Commands in this category**:\n"
        
        if self.context.guild is not None:
            rows = sorted([descriptor(command) for command in cog.get_commands()
                           if command.can_run and not command.hidden
                           and command.name not in self.context.bot.disabled_cache[self.context.guild.id]])
        else:
            rows = sorted([descriptor(command) for command in cog.get_commands()
                           if command.can_run and not command.hidden])
        
        if not rows:
            return []
        
        e.add_field(value='Use help **command** to view the usage of that command.\n Subcommands are ran by using '
                          f'`{self.context.prefix}command subcommand`', name="More help", inline=False)
        embeds = embed_utils.rows_to_embeds(e, rows, header=header, rows_per=10)
        return embeds
    
    async def send_group_help(self, group):
        e = discord.Embed()
        e.title = f'Command help: {group.name.title()}'
        e.description = f"```fix\n{group.help.strip()}```\nCommand usage:```{self.get_command_signature(group)}```"
        e.colour = 0x2ecc71
        e.set_thumbnail(url=self.context.me.avatar_url)
        
        if group.aliases:
            e.description += '*Command Aliases*: ' + ', '.join([f"`{i}`" for i in group.aliases]) + "\n"

        e.description += "\n**Subcommands**:"
        for command in group.commands:
            cmd_string = f"*{command.help.strip()}*\n" if command.help is not None else ""
            cmd_string += f"`{self.get_command_signature(command)}`\n"
            
            if isinstance(command, commands.Group):
                cmd_string += f"*Subcommands:* " + ", ".join([f"`{i.name}`" for i in command.commands]) + "\n"
            e.description += f"\n• {command.name}\n{cmd_string}"
            
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
        e = discord.Embed()
        e.title = f'Command help: {command}'
        e.description = f"```fix\n{command.help}```"
        e.set_thumbnail(url=self.context.me.avatar_url)
        e.colour = 0x2ecc71
        
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
        self.bot.help_command = self._original_help_command


def setup(bot):
    bot.add_cog(HelpCog(bot))
