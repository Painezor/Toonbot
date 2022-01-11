"""Administration commands for Painezor, including logging, debugging, and loading of modules"""
import datetime
import inspect
import sys
from collections import Counter
from importlib import reload
from os import system

import discord
from discord.commands import Option
from discord.commands import permissions
from discord.ext import commands

from ext.utils import codeblocks, embed_utils, browser, view_utils


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.socket_stats = Counter()
        for r in [view_utils, embed_utils, codeblocks, browser]:
            reload(r)

    @property
    def base_embed(self):
        """Base Embed for commands in this cog."""
        e = discord.Embed()
        e.colour = discord.Colour.og_blurple()
        return e

    @commands.slash_command(guild_ids=[250252535699341312], name="print", default_permission=False)
    @permissions.is_owner()
    async def _print(self, ctx, *, to_print):
        """Print something to console."""
        print(to_print)
        e = self.base_embed
        e.description = f"```\n{to_print}```"
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def cc(self, ctx):
        """Clear the command window."""
        system('cls')
        _ = f'{self.bot.user}: {self.bot.initialised_at}'
        print(f'{_}\n{"-" * len(_)}\nConsole cleared at: {datetime.datetime.utcnow().replace(microsecond=0)}')
        e = self.base_embed
        e.title = "Bot Console"
        e.description = "```\nConsole Log Cleared.```"
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def reload(self, ctx, *, module: str):
        """Reloads a module."""
        e = self.base_embed
        e.title = 'Modules'

        try:
            self.bot.reload_extension(module)
        except Exception as err:
            return await self.bot.error(ctx, codeblocks.error_to_codeblock(err))
        else:
            e.description = f':gear: Reloaded {module}'
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def load(self, ctx, *, module: str):
        """Loads a module."""
        e = self.base_embed
        e.title = 'Modules'

        try:
            self.bot.load_extension(module)
        except Exception as err:
            return await self.bot.error(ctx, codeblocks.error_to_codeblock(err))
        else:
            e.description = f':gear: Loaded {module}'
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def scores_refresh(self, ctx):
        """ ADMIN: Force a cache refresh of the live scores"""
        self.bot.games = []
        e = discord.Embed(colour=discord.Colour.og_blurple(), description="[ADMIN] Cleared global games cache.")
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def unload(self, ctx, *, module: str):
        """Unloads a module."""
        e = self.base_embed
        e.title = 'Modules'

        try:
            self.bot.unload_extension(module)
        except Exception as err:
            return await self.bot.error(ctx, codeblocks.error_to_codeblock(err))
        else:
            e.description = f':gear: Unloaded {module}'

        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
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
            e.description = f"**Input**```py\n>>> {code}```**Output**```py\n{result}```"
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def status(self, ctx,
                     mode: Option(str, autocomplete=["playing", "streaming", "watching", "listening"]),
                     new_status: Option(str)):
        """Change status to <cmd> {status}"""
        values = {"playing": 0, "streaming": 1, "watching": 2, "listening": 3}
        act = discord.Activity(type=values[mode], name=new_status)
        await self.bot.change_presence(activity=act)

        e = self.base_embed
        e.title = "Activity"
        e.description = f"Set status to {mode} {new_status}"
        await self.bot.reply(ctx, emebd=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def shared(self, ctx, user_id: int):
        """Check ID for shared servers"""
        if user_id is None:
            user_id = ctx.author.id

        matches = [f"`{i.id}:` **{i.name}**" for i in self.bot.guilds if i.get_member(user_id) is not None]

        if not matches:
            return await self.bot.reply(ctx, content=f"User id {user_id} not found on any servers.")

        user = self.bot.get_user(user_id)
        e = self.base_embed
        e.title = f"User found on {len(matches)} servers."
        e.set_footer(text=f"{user} (ID: {user_id})", icon_url=user.display_avatar.url)

        embeds = embed_utils.rows_to_embeds(e, matches, 20)

        view = view_utils.Paginator(ctx, embeds)
        view.message = await self.bot.reply(ctx, content="Fetching Shared Servers...", view=view)
        await view.update()

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def kill_browser(self, ctx):
        """ Restart browser when you potato. """
        await self.bot.browser.close()
        await browser.make_browser(ctx.bot)
        e = self.base_embed
        e.description = ":gear: Restarting Browser."
        e.colour = discord.Colour.og_blurple()
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def setavatar(self, ctx, new_pic: str = None):
        """Change the avatar of the bot"""
        if ctx.message.attachments:
            new_pic = ctx.attachments[0].url

        async with self.bot.session.get(new_pic) as resp:
            if resp.status != 200:
                return await self.bot.reply(ctx, content=f"HTTP Error: Status Code {resp.status}")
            new_avatar = await resp.read()

        await self.bot.user.edit(avatar=new_avatar)
        e = self.base_embed
        e.title = "Avatar Updated!"
        e.set_image(url=new_avatar)
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def version(self, ctx):
        """Get local environment python version"""
        e = self.base_embed
        e.title = "Python Version"
        e.description = sys.version
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312], default_permission=False)
    @permissions.is_owner()
    async def commandstats(self, ctx):
        """Counts how many commands have been ran this session."""
        e = self.base_embed
        e.title = f"{sum(self.bot.commands_used.values())} commands ran this session"
        embeds = embed_utils.rows_to_embeds(e, [f"{k}: {v}" for k, v in self.bot.commands_used.most_common()], 20)
        view = view_utils.Paginator(ctx, embeds)
        view.message = await self.bot.reply(ctx, content="Fetching Command Usage Stats...", view=view)
        await view.update()


def setup(bot):
    """Load the Administration cog into the Bot"""
    bot.add_cog(Admin(bot))
