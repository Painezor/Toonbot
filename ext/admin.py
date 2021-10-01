"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
import inspect
import sys
from collections import Counter
from importlib import reload
from os import system

import discord
from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded, ExtensionNotFound

from ext.utils import codeblocks, embed_utils, browser, view_utils


def shared_check():
    """Verify command is being ran on specific server or by Painezor"""

    def predicate(ctx):
        """THe actual check"""
        return ctx.author.id == 210582977493598208 or ctx.guild.id == 533677885748150292
    return commands.check(predicate)


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🛠️"
        self.bot.socket_stats = Counter()
        self.bot.loop.create_task(self.update_ignored())
        for r in [view_utils, embed_utils, codeblocks, browser]:
            reload(r)

    @property
    def base_embed(self):
        """Base Embed for commands in this cog."""
        e = discord.Embed()
        e.set_author(name=f"{self.emoji} {self.qualified_name}")
        e.colour = discord.Colour.og_blurple()
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        return e

    async def update_ignored(self):
        """Refresh the cache of ignored users"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""SELECT * FROM ignored_users""")
        self.bot.ignored = {}
        for r in records:
            self.bot.ignored.update({r["user_id"]: r["reason"]})
        await self.bot.db.release(connection)

    @commands.command(name="print")
    @commands.is_owner()
    async def _print(self, ctx, *, to_print):
        """Print something to console."""
        print(to_print)
        e = self.base_embed
        e.description = f"```\n{to_print}```"
        await self.bot.reply(ctx, embed=e)

    @commands.command()
    @commands.is_owner()
    async def setavatar(self, ctx, new_pic: str = None):
        """Change the avatar of the bot"""
        if ctx.message.attachments:
            new_pic = ctx.attachments[0].url

        async with self.bot.session.get(new_pic) as resp:
            if resp.status != 200:
                return await self.bot.reply(ctx, text=f"HTTP Error: Status Code {resp.status}", ping=True)
            new_avatar = await resp.read()

        await self.bot.user.edit(avatar=new_avatar)
        e = self.base_embed
        e.title = "Avatar Updated!"
        e.set_image(url=new_avatar)
        await self.bot.reply(ctx, embed=e)

    @commands.command(aliases=['clean_console', 'cc'])
    @commands.is_owner()
    async def clear_console(self, ctx):
        """Clear the command window."""
        system('cls')
        _ = f'{self.bot.user}: {self.bot.initialised_at}'
        print(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')
        e = self.base_embed
        e.title = "Bot Console"
        e.description = "```\nConsole Log Cleared.```"
        await self.bot.reply(ctx, embed=e)

    @commands.command(aliases=["releoad", "relaod"])  # I can't fucking type.
    @commands.is_owner()
    async def reload(self, ctx, *, module: str):
        """Reloads a module."""
        e = self.base_embed
        e.title = 'Modules'

        try:
            self.bot.reload_extension(module)
        except ExtensionNotLoaded:
            try:
                self.bot.load_extension(module)
            except ExtensionNotFound:
                e.description = f"🚫 Invalid extension {module}"
                ping = True
                e.colour = discord.Colour.red()
            else:
                e.description = f':gear: Loaded {module}'
                ping = False
        except Exception as err:
            e.description = codeblocks.error_to_codeblock(err)
            ping = True
            e.colour = discord.Colour.red()
        else:
            e.description = f':gear: Reloaded {module}'
            ping = False

        await self.bot.reply(ctx, embed=e, ping=ping)

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, *, module: str):
        """Loads a module."""
        e = self.base_embed
        e.title = 'Modules'

        try:
            self.bot.load_extension(module)
        except Exception as err:
            e.description = codeblocks.error_to_codeblock(err)
            ping = True
            e.colour = discord.Colour.red()
        else:
            ping = False
            e.description = f':gear: Loaded {module}'
        await self.bot.reply(ctx, embed=e, ping=ping)

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, *, module: str):
        """Unloads a module."""
        e = self.base_embed
        e.title = 'Modules'

        try:
            self.bot.unload_extension(module)
        except Exception as err:
            ping = True
            e.colour = discord.Colour.red()
            e.description = codeblocks.error_to_codeblock(err)
        else:
            ping = False
            e.description = f':gear: Unloaded {module}'

        await self.bot.reply(ctx, embed=e, ping=ping)

    @commands.command()
    @commands.is_owner()
    async def debug(self, ctx, *, code: str):
        """Evaluates code."""
        code = code.strip('` ')
        env = {'bot': self.bot, 'ctx': ctx}
        env.update(globals())

        e = self.base_embed

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
            e.description = f"```py\n{result}```"
        await self.bot.reply(ctx, embed=e)

    @commands.command()
    @commands.is_owner()
    async def commandstats(self, ctx):
        """Counts how many commands have been ran this session."""
        e = self.base_embed
        e.title = f"{sum(self.bot.commands_used.values())} commands ran this session"
        embeds = embed_utils.rows_to_embeds(e, [f"{k}: {v}" for k, v in self.bot.commands_used.most_common()], 20)
        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching Command Usage Stats...", view=view)
        await view.update()

    @commands.is_owner()
    @commands.command(aliases=['logout', 'restart'])
    async def kill(self, ctx):
        """Restarts the bot"""
        e = self.base_embed
        e.description = ":gear: Restarting."
        e.colour = discord.Colour.red()
        await self.bot.reply(ctx, embed=e)
        await self.bot.db.close()
        await self.bot.logout()

    @commands.is_owner()
    @commands.command(aliases=['streaming', 'watching', 'listening'])
    async def playing(self, ctx, *, status):
        """Change status to <cmd> {status}"""
        values = {"playing": 0, "streaming": 1, "watching": 2, "listening": 3}
        act = discord.Activity(type=values[ctx.invoked_with], name=status)
        await self.bot.change_presence(activity=act)

        e = self.base_embed
        e.title = "Activity"
        e.description = f"Set status to {ctx.invoked_with} {status}"
        await self.bot.reply(ctx, emebd=e)

    @commands.command(aliases=["python"])
    @commands.is_owner()
    async def version(self, ctx):
        """Get local environment python version"""
        e = self.base_embed
        e.title = "Python Version"
        e.description = sys.version
        await self.bot.reply(ctx, embed=e)

    @commands.command()
    @commands.is_owner()
    async def shared(self, ctx, *, user_id: int = None):
        """Check ID for shared servers"""
        if user_id is None:
            user_id = ctx.author.id

        matches = [f"`{i.id}:` **{i.name}**" for i in self.bot.guilds if i.get_member(user_id) is not None]

        if not matches:
            return await self.bot.reply(ctx, text=f"User id {user_id} not found on any servers.")

        user = self.bot.get_user(user_id)
        e = self.base_embed
        e.title = f"User found on {len(matches)} servers."
        e.set_footer(text=f"{user} (ID: {user_id})", icon_url=user.display_avatar.url)

        embeds = embed_utils.rows_to_embeds(e, matches, 20)

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching Shared Servers...", view=view)
        await view.update()

    @commands.command()
    @commands.is_owner()
    async def ignore(self, ctx, users: commands.Greedy[discord.User], *, reason=None):
        """Toggle Ignoring commands from a user (reason optional)"""
        connection = await self.bot.db.acquire()
        e = self.base_embed
        e.title = "Ignoring Users"
        e.description = ""
        async with connection.transaction():
            for i in users:
                if i.id in self.bot.ignored:
                    sql = """DELETE FROM ignored_users WHERE user_id = $1"""
                    escaped = [i.id]
                    e.description += f"Stopped ignoring commands from {i}.\n"
                else:
                    sql = """INSERT INTO ignored_users (user_id,reason) VALUES ($1,$2)"""
                    escaped = [i.id, reason]
                    self.bot.ignored.update({i.id: reason})
                    e.description += f"Ignoring commands from {i}."
                await connection.execute(sql, *escaped)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, embed=e)

    @commands.command()
    @commands.is_owner()
    async def ignored(self, ctx):
        """List all ignored users."""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            ignored_list = await connection.fetchrow("""SELECT * FROM ignored_users""")
        await self.bot.db.release(connection)
        rows = [i['user_id'] for i in ignored_list]
        embeds = embed_utils.rows_to_embeds(self.base_embed, rows)
        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching Ignored Users...", view=view)
        await view.update()

    @commands.command()
    @commands.is_owner()
    async def kill_browser(self, ctx):
        """ Restart browser when you potato. """
        await self.bot.browser.close()
        await browser.make_browser(ctx.bot)
        e = self.base_embed
        e.description = ":gear: Restarting Browser."
        e.colour = discord.Colour.red()
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the Administration cog into the Bot"""
    bot.add_cog(Admin(bot))
