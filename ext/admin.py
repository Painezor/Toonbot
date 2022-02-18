"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
import glob
import inspect
import sys
from collections import Counter
from os import system

from discord import SlashCommandGroup, CommandPermission, Embed, Colour, ButtonStyle, Activity, Attachment
from discord.commands import Option, permissions
from discord.ext import commands
from discord.ui import View, Button

from ext.utils import codeblocks

NO_SLASH_COMM = ("Due to changes with discord, Toonbot will soon be unable to parse messages to find commands\n"
                 "All commands have been moved to use the new /slashcommands system, bots must be re-invited to servers"
                 " with a new scope to use them. Use the link below to re-invite me. All old prefixes are disabled.")


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.socket_stats = Counter()

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

    @commands.slash_command(guild_ids=[250252535699341312], name="print", default_permission=False)
    @permissions.is_owner()
    async def _print(self, ctx, *, to_print):
        """Print something to console."""
        print(to_print)
        e = Embed(colour=Colour.og_blurple())
        e.description = f"```\n{to_print}```"
        await ctx.reply(embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def cc(self, ctx):
        """Clear the command window."""
        system('cls')
        _ = f'{self.bot.user}: {self.bot.initialised_at}'
        print(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')

        e = Embed(title="Bot Console", colour=Colour.og_blurple(), description="```\nConsole Log Cleared.```")
        await ctx.reply(embed=e)

    COGS = Option(str, "Select the cog to reload or load", options=glob.glob("/ext/*.py"))
    modules = SlashCommandGroup("cogs", "Load/Unload bot cogs", permissions=[CommandPermission("owner", 2)])

    @modules.command(guild_ids=[250252535699341312])
    async def reload(self, ctx, *, module: COGS):
        """Reloads a module."""
        e = Embed(title="Modules", colour=Colour.og_blurple())

        try:
            self.bot.reload_extension(f'ext.{module}')
        except Exception as err:
            return await ctx.error(codeblocks.error_to_codeblock(err))
        else:
            e.description = f':gear: Reloaded {module}'
        await ctx.reply(embed=e)

    @modules.command(guild_ids=[250252535699341312])
    async def load(self, ctx, *, module: COGS):
        """Loads a module."""
        e = Embed(title="Modules", colour=Colour.og_blurple())

        try:
            self.bot.load_extension('ext.' + module)
        except Exception as err:
            return await ctx.error(codeblocks.error_to_codeblock(err))
        else:
            e.description = f':gear: Loaded {module}'
        await ctx.reply(embed=e)

    @modules.command(guild_ids=[250252535699341312])
    async def unload(self, ctx, *, module: COGS):
        """Unloads a module."""
        e = Embed(title="Modules", colour=Colour.og_blurple())

        try:
            self.bot.unload_extension('ext.' + module)
        except Exception as err:
            return await ctx.error(codeblocks.error_to_codeblock(err))
        else:
            e.description = f':gear: Unloaded {module}'

        await ctx.reply(embed=e)

    @modules.command()
    async def list(self, ctx):
        """List all currently loaded modules"""
        loaded = sorted([i for i in self.bot.cogs])
        e = Embed(title="Currently loaded Cogs", colour=Colour.og_blurple(), description="\n".join(loaded))
        await ctx.reply(embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def debug(self, ctx, *, code: str):
        """Evaluates code."""
        code = code.strip('` ')
        env = {'bot': self.bot, 'ctx': ctx}
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
        await ctx.reply(embed=e)

    edit_bot = SlashCommandGroup("bot", "Edit bot presence", permissions=[CommandPermission("owner", 2)])

    @edit_bot.command(guild_ids=[250252535699341312])
    async def avatar(self, ctx,
                     file: Option(Attachment, "Upload a file", required=False),
                     link: Option(str, "Provide a link", required=False)):
        """Change the avatar of the bot"""
        avatar = file if file else link

        if avatar is None:
            return await ctx.error("You need to provide either a link or an attachment.")

        async with self.bot.session.get(avatar) as resp:
            if resp.status != 200:
                return await ctx.reply(content=f"HTTP Error: Status Code {resp.status}")
            new_avatar = await resp.read()  # Needs to be bytes.

        await self.bot.user.edit(avatar=new_avatar)
        e = Embed(title="Avatar Updated", colour=Colour.og_blurple())
        e.set_image(url=new_avatar)
        await ctx.reply(embed=e)

    # Presence Commands
    status = edit_bot.create_subgroup(name="status", description="Set bot activity")

    @status.command(guild_ids=[250252535699341312])
    async def playing(self, ctx, status: Option(str, description="Set the new status")):
        """Set bot status to playing {status}"""
        await self.update_presence(ctx, Activity(type=0, name=status))

    @status.command(guild_ids=[250252535699341312])
    async def streaming(self, ctx, status: Option(str, description="Set the new status")):
        """Change status to streaming {status}"""
        await self.update_presence(ctx, Activity(type=1, name=status))

    @status.command(guild_ids=[250252535699341312])
    async def watching(self, ctx, status: Option(str, description="Set the new status")):
        """Change status to watching {status}"""
        await self.update_presence(ctx, Activity(type=2, name=status))

    @status.command(guild_ids=[250252535699341312])
    async def listening(self, ctx, status: Option(str, description="Set the new status")):
        """Change status to listening to {status}"""
        await self.update_presence(ctx, Activity(type=3, name=status))

    async def update_presence(self, ctx, act: Activity):
        """Pass the updated status."""
        await self.bot.change_presence(activity=act)

        e = Embed(title="Activity", colour=Colour.og_blurple())
        e.description = f"Set status to {ctx.invoked_with} {act.name}"
        await ctx.reply(embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def notify(self, ctx, text: Option(str, name="notification", description="Message to send to aLL servers.")):
        """Send a global notification to channels that track it."""
        await self.bot.dispatch("bot_notification", text)
        e = Embed(title="Bot notification dispatched", description=text)
        e.set_thumbnail(url=ctx.me.avatar.url)
        await ctx.reply(embed=e)


def setup(bot):
    """Load the Administration cog into the Bot"""
    bot.add_cog(Admin(bot))
