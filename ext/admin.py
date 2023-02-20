"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
from __future__ import annotations

import datetime
import logging
from inspect import isawaitable
from os import system
from sys import version
from traceback import format_exception
from typing import TYPE_CHECKING

from discord import Interaction, Embed, Colour, Activity, Attachment, Message, Object
from discord.app_commands import Choice, describe, autocomplete, Group, command, guilds, Command, ContextMenu
from discord.ext.commands import Cog, NotOwner

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

NO_SLASH_COMM = ("Due to changes with discord, I will soon be unable to parse messages to find commands\n"
                 "All commands have been moved to use the new /slashcommands system, bots must be re-invited to servers"
                 " with a new scope to use them. Use the link below to re-invite me. All old prefixes are disabled.")

logger = logging.getLogger('Admin')


def error_to_codeblock(error):
    """Formatting of python errors into codeblocks"""
    return f':no_entry_sign: {type(error).__name__}: {error}```py\n' \
           f'{"".join(format_exception(type(error), error, error.__traceback__))}```'


async def cg_ac(interaction: Interaction, current: str) -> list[Choice]:
    """Autocomplete from list of cogs"""
    bot: Bot | PBot = interaction.client
    return [Choice(name=c, value=c) for c in sorted(bot.cogs) if current.lower() in c.lower()]


class Admin(Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @command(name="sync")
    @describe(guild="enter guild ID")
    async def sync(self, interaction: Interaction, guild: bool = False) -> Message:
        """Sync the command tree with discord"""
        await interaction.response.defer(thinking=True)

        if not guild:
            await self.bot.tree.sync()
            return await self.bot.reply(interaction, content="Asked discord to sync, please wait up to 1 hour.")
        else:
            await self.bot.tree.sync(guild=Object(id=interaction.guild.id))
            return await self.bot.reply(interaction, content="Guild Synced")

    cogs = Group(name="cogs", description="Load and unload modules", guild_ids=[250252535699341312])

    @cogs.command(name="reload")
    @describe(cog="pick a cog to reload")
    @autocomplete(cog=cg_ac)
    async def reload(self, interaction: Interaction, cog: str) -> Message:
        """Reloads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.reload_extension(f'ext.{cog.lower()}')
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))
        e: Embed = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Reloaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @autocomplete(cog=cg_ac)
    @describe(cog="pick a cog to load")
    async def load(self, interaction: Interaction, cog: str) -> Message:
        """Loads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.load_extension(f'ext.{cog.lower()}')
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e: Embed = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Loaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @autocomplete(cog=cg_ac)
    async def unload(self, interaction: Interaction, cog: str) -> Message:
        """Unloads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.unload_extension(f'ext.{cog.lower()}')
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e: Embed = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Unloaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    async def list(self, interaction: Interaction) -> Message:
        """List all currently loaded modules"""
        await interaction.response.defer(thinking=True)

        loaded = sorted([i for i in self.bot.cogs])
        e: Embed = Embed(title="Currently loaded Cogs", colour=Colour.og_blurple(), description="\n".join(loaded))
        return await self.bot.reply(interaction, embed=e)

    console = Group(name="console", description="Console Commands", guild_ids=[250252535699341312])

    @console.command(name="print")
    async def _print(self, interaction: Interaction, to_print: str) -> Message:
        """Print something to console."""
        await interaction.response.defer(thinking=True)
        if not interaction.user.id == self.bot.owner_id:
            raise NotOwner

        logging.critical(f"Print command output\n{to_print}")
        e: Embed = Embed(colour=Colour.og_blurple(), description=f"```\n{to_print}```")
        return await self.bot.reply(interaction, embed=e)

    @console.command(name="clear")
    async def clear(self, interaction: Interaction) -> Message:
        """Clear the command window."""
        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner

        system('cls')
        _ = f'{self.bot.user}: {self.bot.initialised_at}'
        logging.info(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')

        e: Embed = Embed(title="Bot Console", colour=Colour.og_blurple(), description="```\nConsole Log Cleared.```")
        return await self.bot.reply(interaction, embed=e)

    @command(name="quit")
    @guilds(250252535699341312)
    async def quit(self, interaction: Interaction) -> Message:
        """Log the bot out gracefully."""
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner
        await self.bot.reply(interaction, content='Logging out.')
        return await self.bot.close()

    @command(name="debug")
    @guilds(250252535699341312)
    @describe(code=">>> Code Go Here")
    async def debug(self, interaction: Interaction, code: str) -> Message:
        """Evaluates code."""
        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner

        code = code.strip('` ')
        env = {'bot': self.bot, 'ctx': interaction, 'interaction': interaction}
        env.update(globals())

        e1: Embed = Embed(title="Input", colour=Colour.lighter_grey())
        e2: Embed = Embed(title="Output", colour=Colour.darker_grey())
        e2.set_footer(text=f"Python Version: {version}")

        try:
            if isawaitable(result := eval(code, env)):
                result = await result
        except Exception as err:
            result = error_to_codeblock(err)

        e1.description = f"```py\n{code}\n```"
        e2.description = f"```py\n{result}\n```"
        if len(e2.description) > 4000:
            logger.log("DEBUG command input\n", code)
            logger.log("DEBUG command output\n", result)
            e2.description = 'Too long for discord, output sent to logger.'
        return await self.bot.reply(interaction, embeds=[e1, e2])

    @command(name="notify")
    @guilds(250252535699341312)
    @describe(notification="Message to send to aLL servers.")
    async def notify(self, interaction: Interaction, notification: str) -> Message:
        """Send a global notification to channels that track it."""
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner

        await interaction.response.defer(thinking=True)

        self.bot.dispatch("bot_notification", notification)
        e: Embed = Embed(title="Bot notification dispatched", description=notification)
        e.set_thumbnail(url=self.bot.user.avatar.url)
        return await self.bot.reply(interaction, embed=e)

    edit_bot = Group(name="bot", description="Edit the bot profile", guild_ids=[250252535699341312])

    @edit_bot.command()
    @describe(file='The file to upload', link="Provide a link")
    async def avatar(self, interaction: Interaction, file: Attachment = None, link: str = None) -> Message:
        """Change the avatar of the bot"""
        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner

        if file is not None:
            avatar = file.url
        elif link:
            avatar = link
        else:
            return await self.bot.error(interaction, content="You need to provide either a link or an attachment.")

        async with self.bot.session.get(avatar) as resp:
            match resp.status:
                case 200:
                    new_avatar = await resp.read()  # Needs to be bytes.
                case _:
                    return await self.bot.reply(interaction, content=f"HTTP Error: Status Code {resp.status}")

        await self.bot.user.edit(avatar=new_avatar)
        e: Embed = Embed(title="Avatar Updated", colour=Colour.og_blurple())
        e.set_image(url=self.bot.user.avatar.url)
        return await self.bot.reply(interaction, embed=e)

    # Presence Commands
    status = Group(name="status", description="Set bot activity", parent=edit_bot)

    @status.command(name="playing")
    @describe(status="What game is the bot playing")
    async def playing(self, interaction: Interaction, status: str) -> Message:
        """Set bot status to playing {status}"""
        await interaction.response.defer(thinking=True)

        return await self.update_presence(interaction, Activity(type=0, name=status))

    @status.command(name="streaming")
    @describe(status="What is the bot streaming")
    async def streaming(self, interaction: Interaction, status: str) -> Message:
        """Change status to streaming {status}"""
        await interaction.response.defer(thinking=True)
        return await self.update_presence(interaction, Activity(type=1, name=status))

    @status.command(name="watching")
    @describe(status="What is the bot watching")
    async def watching(self, interaction: Interaction, status: str) -> Message:
        """Change status to watching {status}"""
        await interaction.response.defer(thinking=True)

        return await self.update_presence(interaction, Activity(type=2, name=status))

    @status.command(name="listening")
    @describe(status="What is the bot listening to")
    async def listening(self, interaction: Interaction, status: str) -> Message:
        """Change status to listening to {status}"""
        await interaction.response.defer(thinking=True)

        return await self.update_presence(interaction, Activity(type=3, name=status))

    async def update_presence(self, interaction: Interaction, act: Activity) -> Message:
        """Pass the updated status."""
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner
        await self.bot.change_presence(activity=act)

        e: Embed = Embed(title="Activity", colour=Colour.og_blurple())
        e.description = f"Set status to {act.type} {act.name}"
        return await self.bot.reply(interaction, embed=e)

    @Cog.listener()
    async def on_app_command_completion(self, interaction: Interaction, cmd: Command | ContextMenu) -> None:
        """Log commands as they are run"""
        guild = interaction.guild.name if interaction.guild else 'DM'
        logger.info(f'Command Ran [{interaction.user} {guild}] /{cmd.qualified_name}')
        return


async def setup(bot: Bot | PBot) -> None:
    """Load the Administration cog into the Bot"""
    await bot.add_cog(Admin(bot))
