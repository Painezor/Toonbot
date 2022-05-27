"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
from inspect import isawaitable
from os import system
from sys import version
from traceback import format_exception
from typing import TYPE_CHECKING, List, Union

from discord import Interaction, Embed, Colour, Activity, Attachment, Message, Object
from discord.app_commands import Choice, describe, autocomplete, Group, command, guilds
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

NO_SLASH_COMM = ("Due to changes with discord, I will soon be unable to parse messages to find commands\n"
                 "All commands have been moved to use the new /slashcommands system, bots must be re-invited to servers"
                 " with a new scope to use them. Use the link below to re-invite me. All old prefixes are disabled.")


def error_to_codeblock(error):
    """Formatting of python errors into codeblocks"""
    return f':no_entry_sign: {type(error).__name__}: {error}```py\n' \
           f'{"".join(format_exception(type(error), error, error.__traceback__))}```'


async def cg_ac(interaction: Interaction, current: str) -> List[Choice]:
    """Autocomplete from list of cogs"""
    cogs = getattr(interaction.client, "COGS")
    return [Choice(name=c, value=c) for c in sorted(cogs) if current.lower() in c.lower()]


class Admin(Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot

    @command()
    @describe(guild="enter guild ID to sync")
    async def sync(self, interaction: Interaction, guild: str = None) -> Message:
        """Sync the command tree with discord"""
        await interaction.response.defer(thinking=True)

        if guild is None:
            await self.bot.tree.sync()
            return await self.bot.reply(interaction, content="Asked discord to sync, please wait up to 1 hour.")
        else:
            await self.bot.tree.sync(guild=Object(int(guild)))
            return await self.bot.reply(interaction, content="Guild synced")

    cogs = Group(name="cogs", description="Load and unload modules", guild_ids=[250252535699341312])

    @cogs.command()
    @describe(cog="pick a cog to reload")
    @autocomplete(cog=cg_ac)
    async def reload(self, interaction: Interaction, cog: str) -> Message:
        """Reloads a module."""
        try:
            await self.bot.reload_extension(f'ext.{cog}')
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))
        e: Embed = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Reloaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @autocomplete(cog=cg_ac)
    @describe(cog="pick a cog to load")
    async def load(self, interaction: Interaction, cog: str) -> Message:
        """Loads a module."""
        try:
            await self.bot.load_extension('ext.' + cog)
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e: Embed = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Loaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @autocomplete(cog=cg_ac)
    async def unload(self, interaction: Interaction, cog: str) -> Message:
        """Unloads a module."""
        try:
            await self.bot.unload_extension('ext.' + cog)
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e: Embed = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Unloaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    async def list(self, interaction: Interaction) -> Message:
        """List all currently loaded modules"""
        loaded = sorted([i for i in self.bot.cogs])
        e: Embed = Embed(title="Currently loaded Cogs", colour=Colour.og_blurple(), description="\n".join(loaded))
        return await self.bot.reply(interaction, embed=e)

    @command(name="print")
    @guilds(250252535699341312)
    async def _print(self, interaction: Interaction, to_print: str) -> Message:
        """Print something to console."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        print("Print command output\n", to_print)
        e: Embed = Embed(colour=Colour.og_blurple(), description=f"```\n{to_print}```")
        return await self.bot.reply(interaction, embed=e)

    @command()
    @guilds(250252535699341312)
    async def cc(self, interaction: Interaction) -> Message:
        """Clear the command window."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        system('cls')
        _ = f'{self.bot.user}: {self.bot.initialised_at}'
        print(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')

        e: Embed = Embed(title="Bot Console", colour=Colour.og_blurple(), description="```\nConsole Log Cleared.```")
        return await self.bot.reply(interaction, embed=e)

    @command()
    @guilds(250252535699341312)
    @describe(code=">>> Code Go Here")
    async def debug(self, interaction: Interaction, code: str) -> Message:
        """Evaluates code."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        code = code.strip('` ')
        env = {'bot': self.bot, 'ctx': interaction, 'interaction': interaction}
        env.update(globals())

        e: Embed = Embed(title="Code Evaluation", colour=Colour.og_blurple())
        e.set_footer(text=f"Python Version: {version}")

        try:
            result = eval(code, env)
            if isawaitable(result):
                result = await result
        except Exception as err:
            result = error_to_codeblock(err)

        e.description = f"**Input**```py\n>>> {code}```**Output**```py\n{result}```"
        if len(e.description) > 4000:
            print("DEBUG command input\n", code)
            print("DEBUG command output\n", e.description)
            e.description = 'Too long for discord, output sent to console.'
        return await self.bot.reply(interaction, embed=e)

    @command()
    @guilds(250252535699341312)
    @describe(notification="Message to send to aLL servers.")
    async def notify(self, interaction: Interaction, notification: str) -> Message:
        """Send a global notification to channels that track it."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        self.bot.dispatch("bot_notification", notification)
        e: Embed = Embed(title="Bot notification dispatched", description=notification)
        e.set_thumbnail(url=self.bot.user.avatar.url)
        return await self.bot.reply(interaction, embed=e)

    edit_bot = Group(name="bot", description="Edit the bot profile", guild_ids=[250252535699341312])

    @edit_bot.command()
    @describe(file='The file to upload', link="Provide a link")
    async def avatar(self, interaction: Interaction, file: Attachment = None, link: str = None) -> Message:
        """Change the avatar of the bot"""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")
        avatar = file if file else link

        if avatar is None:
            return await self.bot.error(interaction, "You need to provide either a link or an attachment.")

        async with self.bot.session.get(avatar) as resp:
            match resp.status:
                case 200:
                    pass
                case _:
                    return await self.bot.reply(interaction, content=f"HTTP Error: Status Code {resp.status}")

            new_avatar = await resp.read()  # Needs to be bytes.

        await self.bot.user.edit(avatar=new_avatar)
        e: Embed = Embed(title="Avatar Updated", colour=Colour.og_blurple())
        e.set_image(url=self.bot.user.avatar.url)
        return await self.bot.reply(interaction, embed=e)

    # Presence Commands
    status = Group(name="status", description="Set bot activity", parent=edit_bot)

    @status.command()
    @describe(status="What game is the bot playing")
    async def playing(self, interaction: Interaction, status: str) -> Message:
        """Set bot status to playing {status}"""
        return await self.update_presence(interaction, Activity(type=0, name=status))

    @status.command()
    @describe(status="What is the bot streaming")
    async def streaming(self, interaction: Interaction, status: str) -> Message:
        """Change status to streaming {status}"""
        return await self.update_presence(interaction, Activity(type=1, name=status))

    @status.command()
    @describe(status="What is the bot watching")
    async def watching(self, interaction: Interaction, status: str) -> Message:
        """Change status to watching {status}"""
        return await self.update_presence(interaction, Activity(type=2, name=status))

    @status.command()
    @describe(status="What is the bot listening to")
    async def listening(self, interaction: Interaction, status: str) -> Message:
        """Change status to listening to {status}"""
        return await self.update_presence(interaction, Activity(type=3, name=status))

    async def update_presence(self, interaction: Interaction, act: Activity) -> Message:
        """Pass the updated status."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")
        await self.bot.change_presence(activity=act)

        e: Embed = Embed(title="Activity", colour=Colour.og_blurple())
        e.description = f"Set status to {act.type} {act.name}"
        return await self.bot.reply(interaction, embed=e)


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Load the Administration cog into the Bot"""
    await bot.add_cog(Admin(bot))
