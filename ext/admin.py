"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
import inspect
import sys
import traceback
from os import system
from typing import Optional

from discord import Interaction, Embed, Colour, ButtonStyle, Activity, Attachment, app_commands, Message, Object
from discord.app_commands import Choice
from discord.ext import commands
from discord.ui import View, Button

NO_SLASH_COMM = ("Due to changes with discord, Toonbot will soon be unable to parse messages to find commands\n"
                 "All commands have been moved to use the new /slashcommands system, bots must be re-invited to servers"
                 " with a new scope to use them. Use the link below to re-invite me. All old prefixes are disabled.")


def error_to_codeblock(error):
    """Formatting of python errors into codeblocks"""
    return f':no_entry_sign: {type(error).__name__}: {error}```py\n' \
           f'{"".join(traceback.format_exception(type(error), error, error.__traceback__))}```'


# AutoComplete
choices = [Choice(name=i, value=i) for i in
           ['errors', 'session', 'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv',
            'logs', 'lookup', 'mod', 'nufc', 'poll', 'quotes', 'reminders', 'rss', 'sidebar', 'streams', 'warships',
            'testing']]


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot) -> None:
        self.bot = bot

    async def on_message(self, message) -> Message:
        """Slash commands warning system."""
        me = message.channel.me
        if me in message.mentions or message.startswith(".tb"):
            name = f"{me.display_name} ({me.name})" if me.display_name != message.me.name else f"{me.name}"
            e = Embed(title=f"{name} now uses slash commands")
            e.colour = Colour.og_blurple()

            if not message.channel.permissions_for(message.author).use_slash_commands:
                e.colour = Colour.red()
                e.description = f"Your server's settings do not allow any of your roles to use slash commands.\n" \
                                "Ask a moderator to give you `use_slash_commands` permissions."
            else:
                e.description = "I use slash commands now, type `/` to see a list of my commands"
                if message.guild is not None:
                    e.description += "\nIf you don't see any slash commands, you need to re-invite the bot using" \
                                     "the link below."

            view = View()
            view.add_item(Button(style=ButtonStyle.url, url=self.bot.invite_url, label="Invite me to your server"))
            e.add_field(name="Discord changes", value=NO_SLASH_COMM)
            return await message.reply(embed=e, view=view)

    @app_commands.command()
    @app_commands.describe(guild="enter guild ID to sync")
    async def sync(self, interaction: Interaction, guild: Optional[str] = None):
        """Sync the command tree with discord"""
        if guild is None:
            await self.bot.tree.sync()
        else:
            guild = Object(int(guild))
            await self.bot.tree.sync(guild)
        await self.bot.reply(interaction, "Asked discord to sync, please wait up to 1 hour.")

    cogs = app_commands.Group(name="cogs", description="Load and unload modules", guild_ids=[250252535699341312])

    @cogs.command()
    @app_commands.describe(cog="pick a cog to reload")
    @app_commands.choices(cog=choices)
    async def reload(self, interaction: Interaction, cog: str):
        """Reloads a module."""
        try:
            self.bot.reload_extension(f'ext.{cog}')
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))
        e = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Reloaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @app_commands.describe(cog="pick a cog to load")
    @app_commands.choices(cog=choices)
    async def load(self, interaction: Interaction, cog: str):
        """Loads a module."""
        try:
            self.bot.load_extension('ext.' + cog)
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Loaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @app_commands.choices(cog=choices)
    async def unload(self, interaction: Interaction, cog: str):
        """Unloads a module."""
        try:
            self.bot.unload_extension('ext.' + cog)
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Unloaded {cog}')
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    async def list(self, interaction: Interaction):
        """List all currently loaded modules"""
        loaded = sorted([i for i in self.bot.cogs])
        e = Embed(title="Currently loaded Cogs", colour=Colour.og_blurple(), description="\n".join(loaded))
        return await self.bot.reply(interaction, embed=e)

    @app_commands.command(name="print")
    @app_commands.guilds(250252535699341312)
    async def _print(self, interaction: Interaction, to_print: str):
        """Print something to console."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        print(to_print)
        e = Embed(colour=Colour.og_blurple(), description=f"```\n{to_print}```")
        return await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.guilds(250252535699341312)
    async def cc(self, interaction):
        """Clear the command window."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        system('cls')
        _ = f'{self.bot.user}: {self.bot.initialised_at}'
        print(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')

        e = Embed(title="Bot Console", colour=Colour.og_blurple(), description="```\nConsole Log Cleared.```")
        return await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.describe(code=">>> Code Go Here")
    @app_commands.guilds(250252535699341312)
    async def debug(self, interaction: Interaction, code: str):
        """Evaluates code."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        code = code.strip('` ')
        env = {'bot': self.bot, 'ctx': interaction, 'interaction': interaction}
        env.update(globals())

        e = Embed(title="Code Evaluation", colour=Colour.og_blurple())
        e.set_footer(text=f"Python Version: {sys.version}")

        try:
            result = eval(code, env)
            if inspect.isawaitable(result):
                result = await result
        except Exception as err:
            result = error_to_codeblock(err)

        e.description = f"**Input**```py\n>>> {code}```**Output**```py\n{result}```"
        if len(e.description) > 4000:
            print(e.description)
            e.description = 'Too long for discord, output sent to console.'
        await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.describe(notification="Message to send to aLL servers.")
    @app_commands.guilds(250252535699341312)
    async def notify(self, interaction: Interaction, notification: str):
        """Send a global notification to channels that track it."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        self.bot.dispatch("bot_notification", notification)
        e = Embed(title="Bot notification dispatched", description=notification)
        e.set_thumbnail(url=self.bot.user.avatar.url)
        await self.bot.reply(interaction, embed=e)

    edit_bot = app_commands.Group(name="editbot", description="Edit the bot profile", guild_ids=[250252535699341312])

    @edit_bot.command()
    @app_commands.describe(file='The file to upload', link="Provide a link")
    async def avatar(self, interaction: Interaction, file: Optional[Attachment] = None, link: Optional[str] = None):
        """Change the avatar of the bot"""
        avatar = file if file else link

        if avatar is None:
            return await self.bot.error(interaction, "You need to provide either a link or an attachment.")

        async with self.bot.session.get(avatar) as resp:
            if resp.status != 200:
                return await self.bot.reply(interaction, content=f"HTTP Error: Status Code {resp.status}")
            new_avatar = await resp.read()  # Needs to be bytes.

        await self.bot.user.edit(avatar=new_avatar)
        e = Embed(title="Avatar Updated", colour=Colour.og_blurple())
        e.set_image(url=new_avatar)
        await self.bot.reply(interaction, embed=e)

    # Presence Commands
    status = app_commands.Group(name="status", description="Set bot activity", parent=edit_bot)

    @status.command()
    @app_commands.describe(status="What game is the bot playing")
    async def playing(self, interaction: Interaction, status: str):
        """Set bot status to playing {status}"""
        await self.update_presence(interaction, Activity(type=0, name=status))

    @status.command()
    @app_commands.describe(status="What is the bot streaming")
    async def streaming(self, interaction: Interaction, status: str):
        """Change status to streaming {status}"""
        await self.update_presence(interaction, Activity(type=1, name=status))

    @status.command()
    @app_commands.describe(status="What is the bot watching")
    async def watching(self, interaction: Interaction, status: str):
        """Change status to watching {status}"""
        await self.update_presence(interaction, Activity(type=2, name=status))

    @status.command()
    @app_commands.describe(status="What is the bot listening to")
    async def listening(self, interaction: Interaction, status: str):
        """Change status to listening to {status}"""
        await self.update_presence(interaction, Activity(type=3, name=status))

    async def update_presence(self, interaction: Interaction, act: Activity):
        """Pass the updated status."""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")
        await self.bot.change_presence(activity=act)

        e = Embed(title="Activity", colour=Colour.og_blurple())
        e.description = f"Set status to {act.type} {act.name}"
        await self.bot.reply(interaction, embed=e)


def setup(bot):
    """Load the Administration cog into the Bot"""
    bot.add_cog(Admin(bot))
