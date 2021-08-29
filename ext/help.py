"""Custom Help formatting for displaying information on how to use commands within Toonbot"""
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import embed_utils

INV = f"[Invite me to your discord](https://discordapp.com/oauth2/authorize?client_id=250051254783311873" \
      f"&permissions=67488768&scope=bot)\n[Join the Toonbot Help & Testing Discord](http://www.discord.gg/a5NHvPx)" \
      f"\n[Donate to the Author](https://paypal.me/Toonbot)"


# Page Buttons
class HelpButton(discord.ui.Button):
    """Help Button"""

    def __init__(self):
        super().__init__()
        self.label = "Help"
        self.emoji = "❓"

    async def callback(self, interaction):
        """Button: Show Generic Help Embed"""
        await interaction.response.defer()
        await self.view.push_home_embed()


class PreviousButton(discord.ui.Button):
    """Previous Button for Pagination Views"""

    def __init__(self):
        super().__init__()
        self.label = "Previous"
        self.emoji = "⏮"
        self.style = discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = self.view.index - 1 if self.view.index > 0 else self.view.index
        await self.view.update()


class NextButton(discord.ui.Button):
    """Go to the next Page of Help Embeds for a Category"""

    def __init__(self):
        super().__init__()
        self.emoji = '⏭'
        self.label = "Next"
        self.style = discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        """Go to the next embed page if there are multiple"""
        await interaction.response.defer()
        self.view.index += 1 if self.view.index + 1 < len(self.view.cogs) else self.view.index
        await self.view.update()


class StopButton(discord.ui.Button):
    """The Button for hiding the View"""

    def __init__(self):
        super().__init__()
        self.emoji = '🚫'
        self.label = "Hide"
        self.style = discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction):
        """End the paginator and hide it's message."""
        await self.view.message.delete()
        self.view.stop()


class PageButton(discord.ui.Button):
    """The Page Changer / Displayer Button"""

    def __init__(self):
        super().__init__()
        self.label = "Which category would you like help with?"
        self.style = discord.ButtonStyle.primary
        self.disabled = False
        self.emoji = "⏬"

    async def callback(self, interaction: discord.Interaction):
        """The pages button."""
        await interaction.response.defer()
        dropdown = HelpDropDown(placeholder="Select A Category", cogs=self.view.cogs)
        self.view.add_item(dropdown)
        await self.view.message.edit(view=self.view)
        await self.view.wait()


class HelpDropDown(discord.ui.Select):
    """The dropdown for our Cogs"""

    def __init__(self, placeholder, cogs: list):
        self.cogs = cogs
        super().__init__()
        self.placeholder = placeholder
        for index, cog in enumerate(self.cogs):
            emoji = None if not hasattr(cog, 'emoji') else cog.emoji
            self.add_option(label=cog.qualified_name, description=cog.description, emoji=emoji, value=str(index))

    async def callback(self, interaction: discord.Interaction):
        """Return the requested item when the dropdown is selected"""
        # Take Index of Value result and fetch from self.objects.
        match = self.cogs[int(self.values[0])]
        self.view.index = 0
        self.view.value = match
        self.view.current_category = match.qualified_name
        await interaction.response.defer()
        await self.view.push_cog_embed(match)


class HelpView(discord.ui.View):
    """A view for an instance of the help command."""

    def __init__(self, ctx, prefixes, cogs, help_command):
        self.message = None
        self.embeds = []
        self.ctx = ctx
        self.index = 0
        self.current_category = None
        self.cogs = cogs
        self.prefixes = prefixes
        self.help_command = help_command
        super().__init__()

    def populate_buttons(self):
        """Do our button population logic"""
        self.add_item(HelpButton())

        if len(self.embeds) > 1:
            _ = PreviousButton()
            _.disabled = True if self.index == 0 else False
            self.add_item(_)

        _ = PageButton()
        _.label = "Choose a Help Category" if self.current_category is None else f"{self.current_category} Help"
        if len(self.embeds) > 1:
            _.label += f" (Page {self.index + 1} of {len(self.embeds)})"
        self.add_item(_)

        if len(self.embeds) > 1:
            _.disabled = True if self.index == len(self.embeds) - 1 else False
            _ = NextButton()
            self.add_item(_)

        self.add_item(StopButton())

    async def on_timeout(self):
        """Clean up"""
        try:
            await self.message.delete()
        except discord.HTTPException:
            pass

    async def update(self):
        """Update the view"""
        self.clear_items()
        self.populate_buttons()
        await self.message.edit(content=None, view=self, embed=self.embeds[self.index],
                                allowed_mentions=discord.AllowedMentions().none())

    @property
    def base_embed(self):
        """A generic help embed"""
        e = discord.Embed()
        e.set_thumbnail(url=self.ctx.me.display_avatar.url)
        e.colour = 0x2ecc71
        e.set_author(name="Toonbot Help")
        return e

    async def push_home_embed(self):
        """The default Home Embed"""
        e = self.base_embed
        e.description = f"**Running Commands**:\n Use `{self.ctx.prefix}command` to run a command\n" \
                        f"Use `{self.ctx.prefix}help command` to get detailed help for that command."
        e.add_field(name="Navigating Menus", value="Click on buttons to change between pages, "
                                                   "Click on dropdowns to select items on those pages.", inline=False)
        e.add_field(name="Links", value=INV, inline=False)
        pf = f"You can use any of these prefixes to run commands: ```yaml\n {' '.join(self.prefixes)}```"
        e.add_field(name="Prefixes", value=pf, inline=False)
        self.current_category = None
        self.embeds = [e]
        self.index = 0
        await self.update()

    async def push_cog_embed(self, cog):
        """Set the View to show a cog's embeds"""
        self.embeds = await self.cog_embed(cog)
        self.index = 0
        self.current_category = cog.qualified_name
        if self.current_category == "HelpCog":
            await self.push_home_embed()
        else:
            await self.update()

    async def cog_embed(self, cog):
        """The Embed containing help documentation for a cog"""
        e = self.base_embed
        e.title = f'Category Help: {cog.qualified_name}'

        command_list = cog.get_commands()
        runnable = await self.help_command.filter_commands(command_list)
        header = f"```fix\n{cog.description}\n```\n**Commands in this category**:\n"
        rows = sorted([await self.descriptor(command) for command in runnable])

        if not rows:
            return []

        e.add_field(value=f'Use `{self.ctx.prefix}help command` to view extended help of that command.\n'
                          f'Subcommands are ran by using `{self.ctx.prefix}command subcommand`',
                    name="More help", inline=False)
        e.add_field(name="Changing Category", value="Click the blue button below to change help category.")
        embeds = embed_utils.rows_to_embeds(e, rows, header=header)
        return embeds

    async def descriptor(self, command):
        """Basic description of command or Group"""
        string = f'• **{command.name.lower().strip()}**\n{command.short_doc.strip()}\n'
        if isinstance(command, commands.Group):
            runnable = await self.help_command.filter_commands(command.commands)
            if runnable:
                string += f"∟○ Subcommands: " + ", ".join([f"`{i.name}`" for i in runnable]) + "\n"
        return string


class Help(commands.HelpCommand):
    """The Toonbot help command."""

    @property
    def base_embed(self):
        """Generic Embed for help commands."""
        e = discord.Embed()
        e.set_thumbnail(url=self.context.me.display_avatar.url)
        e.colour = 0x2ecc71
        return e

    async def get_prefixes(self):
        """Fetch Bot Prefixes"""
        if self.context.guild is None:
            pref = [".tb ", "!", "-", "`", "!", "?", ""]
        else:
            pref = self.context.bot.prefix_cache[self.context.guild.id]
        pref = [".tb "] if not pref else pref
        return pref

    def get_command_signature(self, command):
        """Example formatting of a command's usage."""
        return f'{self.context.prefix}{command.qualified_name} {command.signature}'

    async def get_valid_cogs(self):
        """Generate SelectOptions for Dropdowns in usable format"""
        options = list(set([i.cog for i in await self.filter_commands(self.context.bot.walk_commands())]))
        return options

    async def send_bot_help(self, mapping):
        """Default Help Command: No Category or Command"""
        cogs = await self.get_valid_cogs()
        view = HelpView(self.context, prefixes=await self.get_prefixes(), cogs=cogs, help_command=self)
        view.message = await self.context.bot.reply(self.context, "Generating Help...", view=view)
        await view.push_home_embed()

    async def send_cog_help(self, cog):
        """Sends help for a single category"""
        cogs = await self.get_valid_cogs()
        view = HelpView(self.context, prefixes=await self.get_prefixes(), cogs=cogs, help_command=self)
        view.message = await self.context.bot.reply(self.context, "Generating Help...", view=view)
        await view.push_cog_embed(cog)

    async def send_group_help(self, group):
        """Send an embed containing Help documentation for a group of commands."""
        e = self.base_embed
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
                          '[] around an argument means it is an [OPTIONAL argument]\n\n*(Do not type the brackets!)*'
                          f'\nUse `{self.context.prefix}help <command> [subcommand]` for info on subcommands\n'
                          f'Don\'t type the <> or [].', inline=False)
        e.add_field(name="More help", inline=False,
                    value='Use help **command** to view the usage of that command.\n'
                          f'Subcommands are ran by using `{self.context.prefix}command subcommand`')
        await self.context.bot.reply(self.context, embed=e)

    async def send_command_help(self, command):
        """Send documentation for a single command"""
        e = self.base_embed
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
        self.emoji = "❓"
        bot.help_command = Help()
        bot.help_command.cog = self
        self.bot = bot

    def cog_unload(self):
        """Reset to default help formatter when cog is unloaded."""
        self.bot.help_command = self._original_help_command


def setup(bot):
    """Load Custom Help Command into the bot."""
    bot.add_cog(HelpCog(bot))
