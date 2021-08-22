"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
import inspect
import sys
from collections import Counter
from os import system

import discord
from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded, ExtensionNotFound

from ext.utils import codeblocks, embed_utils, browser


# TODO: Select / Button Pass.

class Admin(commands.Cog):
    """Code debug & 1oading of modules"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🛠️"
        self.bot.socket_stats = Counter()
        self.bot.loop.create_task(self.update_ignored())

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
        await self.bot.reply(ctx, f"Printed {to_print} to console.")

    @commands.command()
    @commands.is_owner()
    async def setavatar(self, ctx, new_pic: str):
        """Change the bot's avatar"""
        async with self.bot.session.get(new_pic) as resp:
            if resp.status != 200:
                return await self.bot.reply(ctx, text=f"HTTP Error: Status Code {resp.status}", ping=True)
            profile_img = await resp.read()
        await self.bot.user.edit(avatar=profile_img)

    @commands.command(aliases=['clean_console', 'cc'])
    @commands.is_owner()
    async def clear_console(self, ctx):
        """Clear the command window."""
        system('cls')
        print(f'{self.bot.user}: {self.bot.initialised_at}\n-----------------------------------------')
        e = discord.Embed()
        e.colour = discord.Colour.og_blurple()
        e.description = "[ADMIN] Console Log Cleared."
        await self.bot.reply(ctx, embed=e)
        print(f"Console cleared at: {datetime.datetime.utcnow()}")

    @commands.command(aliases=["releoad", "relaod"])  # I can't fucking type.
    @commands.is_owner()
    async def reload(self, ctx, *, module: str):
        """Reloads a module."""
        try:
            self.bot.reload_extension(module)
            await self.bot.reply(ctx, text=f':gear: Reloaded {module}')
        except ExtensionNotLoaded:
            try:
                self.bot.load_extension(module)
            except ExtensionNotFound:
                return await self.bot.reply(ctx, text=f'🚫 Invalid extension {module}', ping=True)
            await self.bot.reply(ctx, text=f':gear: Loaded {module}')
        except Exception as e:
            await self.bot.reply(ctx, text=codeblocks.error_to_codeblock(e), ping=True)

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, *, module: str):
        """Loads a module."""
        try:
            self.bot.load_extension(module)
        except Exception as e:
            await self.bot.reply(ctx, text=codeblocks.error_to_codeblock(e), ping=True)
        else:
            await self.bot.reply(ctx, text=f':gear: Loaded {module}')

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, *, module: str):
        """Unloads a module."""
        try:
            self.bot.unload_extension(module)
        except Exception as e:
            await self.bot.reply(ctx, text=codeblocks.error_to_codeblock(e), ping=True)
        else:
            await self.bot.reply(ctx, text=f':gear: Unloaded {module}')

    @commands.command()
    @commands.is_owner()
    async def debug(self, ctx, *, code: str):
        """Evaluates code."""
        code = code.strip('` ')

        env = {
            'bot': self.bot,
            'ctx': ctx,
        }
        env.update(globals())
        try:
            result = eval(code, env)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            etc = codeblocks.error_to_codeblock(e)
            if len(etc) > 2000:
                await self.bot.reply(ctx, text='Too long for discord, output sent to console.')
                print(etc)
            else:
                return await self.bot.reply(ctx, text=etc)
        else:
            await self.bot.reply(ctx, text=f"```py\n{result}```")

    @commands.command()
    @commands.is_owner()
    async def commandstats(self, ctx):
        """Counts how many commands have been ran this session."""
        e = discord.Embed()
        e.colour = discord.Colour.og_blurple()
        e.title = f"{sum(self.bot.commands_used.values())} commands ran this session"
        
        counter = self.bot.commands_used
        lines = [f"{k}: {v}"for k, v in counter.most_common()]
        
        embeds = embed_utils.rows_to_embeds(e, lines, 20)
        
        await embed_utils.paginate(ctx, embeds)

    @commands.is_owner()
    @commands.command(aliases=['logout', 'restart'])
    async def kill(self, ctx):
        """Restarts the bot"""
        await self.bot.db.close()
        await self.bot.logout()
        await self.bot.reply(ctx, text=":gear: Restarting.")

    @commands.is_owner()
    @commands.command(aliases=['streaming', 'watching', 'listening'])
    async def playing(self, ctx, *, status):
        """Change status to <cmd> {status}"""
        values = {"playing": 0, "streaming": 1, "watching": 2, "listening": 3}

        act = discord.Activity(type=values[ctx.invoked_with], name=status)

        await self.bot.change_presence(activity=act)
        await self.bot.reply(ctx, text=f"Set status to {ctx.invoked_with} {status}")

    @commands.command()
    @commands.is_owner()
    async def version(self, ctx):
        """Get bot's python version"""
        await self.bot.reply(ctx, text=sys.version)
    
    @commands.command()
    @commands.is_owner()
    async def shared(self, ctx, *, user_id: int):
        """Check ID for shared servers"""
        matches = [f"{i.name} ({i.id})" for i in self.bot.guilds if i.get_member(user_id) is not None]

        if not matches:
            return await self.bot.reply(ctx, text=f"User id {user_id} not found on shared servers.")
        
        user = self.bot.get_user(user_id)
        e = discord.Embed(color=0x00ff00)
        e.title = f"User found on {len(matches)} servers."
        e.set_author(name=f"{user} (ID: {user_id})", icon_url=user.avatar.url or user.default_avatar.url)

        embeds = embed_utils.rows_to_embeds(e, matches)
        await embed_utils.paginate(ctx, embeds)

    @commands.command()
    @commands.is_owner()
    async def ignore(self, ctx, users: commands.Greedy[discord.User], *, reason=None):
        """Toggle Ignoring commands from a user (reason optional)"""
        for i in users:
            if i.id in self.bot.ignored:
                sql = """INSERT INTO ignored_users (user_id,reason) = ($1,$2)"""
                escaped = [i.id, reason]
                await self.bot.reply(ctx, text=f"Stopped ignoring commands from {i}.")
            else:
                sql = """DELETE FROM ignored_users WHERE user_id = $1"""
                escaped = [i.id]
                self.bot.ignored.update({f"{i.id}": reason})
                await self.bot.reply(ctx, text=f"Ignoring commands from {i}.")
            connection = await self.bot.db.acquire()
            async with connection.transaction():
                await connection.execute(sql, *escaped)
            await self.bot.db.release(connection)

    @commands.command()
    @commands.is_owner()
    async def kill_browser(self, ctx):
        """ Restart browser when you potato. """
        await self.bot.browser.close()
        await self.bot.reply(ctx, "Browser closed.")
        await browser.make_browser(ctx.bot)


def setup(bot):
    """Load the Administration cog into the Bot"""
    bot.add_cog(Admin(bot))
