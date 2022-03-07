"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
import glob
import inspect
import sys
from os import system
from typing import Optional, Literal, List

from discord import Interaction, Embed, Colour, ButtonStyle, Activity, Attachment, Object, app_commands
from discord.commands import Option
from discord.ext import commands
from discord.ui import View, Button

from ext.utils import codeblocks

NO_SLASH_COMM = ("Due to changes with discord, Toonbot will soon be unable to parse messages to find commands\n"
                 "All commands have been moved to use the new /slashcommands system, bots must be re-invited to servers"
                 " with a new scope to use them. Use the link below to re-invite me. All old prefixes are disabled.")

TB_GUILD = Object(id=250252535699341312)


class EditBot(app_commands.Group):
    """Set the status of the bot"""

    @app_commands.command()
    @app_commands.describe(attachment='The file to upload', link="Provide a link")
    async def avatar(self, interaction: Interaction, attachment: Optional[Attachment], link: Optional[str]):
        """Change the avatar of the bot"""
        avatar = attachment if attachment else link

        if avatar is None:
            return await interaction.client.error(interaction, "You need to provide either a link or an attachment.")

        async with interaction.client.session.get(avatar) as resp:
            if resp.status != 200:
                return await interaction.client.reply(interaction, content=f"HTTP Error: Status Code {resp.status}")
            new_avatar = await resp.read()  # Needs to be bytes.

        await interaction.client.user.edit(avatar=new_avatar)
        e = Embed(title="Avatar Updated", colour=Colour.og_blurple())
        e.set_image(url=new_avatar)
        await interaction.client.reply(interaction, embed=e)

    # Presence Commands
    status = app_commands.Group(name="status", description="Set bot activity")

    @status.command()
    async def playing(self, interaction: Interaction, status: str):
        """Set bot status to playing {status}"""
        await update_presence(interaction, Activity(type=0, name=status))

    @status.command()
    async def streaming(self, interaction: Interaction, status: Option(str, description="Set the new status")):
        """Change status to streaming {status}"""
        await update_presence(interaction, Activity(type=1, name=status))

    @status.command()
    async def watching(self, interaction: Interaction, status: Option(str, description="Set the new status")):
        """Change status to watching {status}"""
        await update_presence(interaction, Activity(type=2, name=status))

    @status.command()
    async def listening(self, interaction: Interaction, status: Option(str, description="Set the new status")):
        """Change status to listening to {status}"""
        await update_presence(interaction, Activity(type=3, name=status))


async def update_presence(interaction: Interaction, act: Activity):
    """Pass the updated status."""
    if interaction.user.id != interaction.client.owner_id:
        return await interaction.client.error(interaction, "You do not own this bot.")
    await interaction.client.change_presence(activity=act)

    e = Embed(title="Activity", colour=Colour.og_blurple())
    e.description = f"Set status to {act.type} {act.name}"
    await interaction.client.reply(interaction, embed=e)


class Modules(app_commands.Group):
    """Atomic reloading of cogs"""
    files: List[str] = glob.glob("/ext/*.py")
    COGS = Literal[files]

    @app_commands.command()
    @app_commands.describe(cog="pick a cog to reload")
    async def reload(self, interaction: Interaction, cog: COGS):
        """Reloads a module."""
        try:
            interaction.client.reload_extension(f'ext.{cog}')
        except Exception as err:
            return await interaction.client.error(error_messasge=codeblocks.error_to_codeblock(err))
        e = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Reloaded {cog}')
        await sync_commands(interaction.client)
        return await interaction.client.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.describe(cog="pick a cog to load")
    async def load(self, interaction: Interaction, cog: COGS):
        """Loads a module."""
        try:
            interaction.client.load_extension('ext.' + cog)
        except Exception as err:
            return await interaction.client.error(interaction, codeblocks.error_to_codeblock(err))

        e = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Loaded {cog}')
        await sync_commands(interaction.client)
        return await interaction.client.reply(interaction, embed=e)

    @app_commands.command(guild_ids=[250252535699341312])
    async def unload(self, interaction: Interaction, module: COGS):
        """Unloads a module."""
        try:
            interaction.client.unload_extension('ext.' + module)
        except Exception as err:
            return await interaction.client.error(interaction, codeblocks.error_to_codeblock(err))

        e = Embed(title="Modules", colour=Colour.og_blurple(), description=f':gear: Unloaded {module}')
        await sync_commands(interaction.client)
        return await interaction.client.reply(interaction, embed=e)

    @app_commands.command()
    async def list(self, interaction: Interaction):
        """List all currently loaded modules"""
        loaded = sorted([i for i in interaction.client.cogs])
        e = Embed(title="Currently loaded Cogs", colour=Colour.og_blurple(), description="\n".join(loaded))
        return await interaction.client.reply(interaction, embed=e)


@app_commands.command(name="print")
async def _print(interaction: Interaction, *, to_print):
    """Print something to console."""
    if interaction.author.id != interaction.client.owner_id:
        return await interaction.client.error(interaction, "You do not own this bot.")

    print(to_print)
    e = Embed(colour=Colour.og_blurple(), description=f"```\n{to_print}```")
    return await interaction.client.reply(interaction, embed=e)


@app_commands.command()
async def cc(interaction):
    """Clear the command window."""
    if interaction.user.id != interaction.client.owner_id:
        return await interaction.client.error(interaction, "You do not own this bot.")

    system('cls')
    _ = f'{interaction.client.user}: {interaction.client.initialised_at}'
    print(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')

    e = Embed(title="Bot Console", colour=Colour.og_blurple(), description="```\nConsole Log Cleared.```")
    return await interaction.client.reply(interaction, embed=e)


@app_commands.command(guild_ids=[250252535699341312], default_permission=False)
async def debug(interaction: Interaction, code: str):
    """Evaluates code."""
    if interaction.user.id != interaction.client.owner_id:
        return await interaction.client.error(interaction, "You do not own this bot.")

    code = code.strip('` ')
    env = {'bot': interaction.client, 'ctx': interaction, 'interaction': interaction}
    env.update(globals())

    e = Embed(title="Code Evaluation", colour=Colour.og_blurple())
    e.set_footer(text=f"Python Version: {sys.version}")

    try:
        result = eval(code, env)
        if inspect.isawaitable(result):
            result = await result
    except Exception as err:
        etc = codeblocks.error_to_codeblock(err)
        if len(etc) > 2047:
            e.description = 'Too long for discord, output sent to console.'
            print(etc)
        else:
            e.description = etc
    else:
        e.description = f"**Input**```py\n>>> {code}```**Output**```py\n{result}```"
    await interaction.client.reply(interaction, embed=e)


@app_commands.command()
@app_commands.describe(notification="Message to send to aLL servers.")
async def notify(interaction: Interaction, notification: str):
    """Send a global notification to channels that track it."""
    if interaction.user.id != interaction.client.owner_id:
        return await interaction.client.error(interaction, "You do not own this bot.")

    await interaction.client.dispatch("bot_notification", notification)
    e = Embed(title="Bot notification dispatched", description=notification)
    e.set_thumbnail(url=interaction.client.user.avatar.url)
    await interaction.client.reply(interaction, embed=e)


async def sync_commands(bot):
    """Synchronise the command list."""
    await bot.tree.sync(TB_GUILD)
    await bot.tree.sync()


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(_print, guild=TB_GUILD)
        self.bot.tree.add_command(cc, guild=TB_GUILD)
        self.bot.tree.add_command(debug, guild=TB_GUILD)
        self.bot.tree.add_command(Modules(), guild=TB_GUILD)
        self.bot.tree.add_command(EditBot(), guild=TB_GUILD)
        self.bot.tree.add_command(notify, guild=TB_GUILD)
        self.bot.loop.create_task(sync_commands(bot))

    async def on_message(self, message):
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


def setup(bot):
    """Load the Administration cog into the Bot"""
    bot.add_cog(Admin(bot))
