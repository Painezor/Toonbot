import asyncio
import json
from copy import deepcopy
from datetime import datetime

import aiohttp
import asyncpg
import discord
from discord.ext import commands
from discord.ext.commands import ExtensionAlreadyLoaded

with open('credentials.json') as f:
    credentials = json.load(f)


async def run():
    db = await asyncpg.create_pool(**credentials['Postgres'])
    bot = Bot(database=db)
    try:
        await bot.start(credentials['bot']['token'])
    except KeyboardInterrupt:
        for i in bot.cogs:
            bot.unload_extension(i.name)
        await db.close()
        await bot.logout()


class Bot(commands.Bot):
    def __init__(self, **kwargs):
        
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb ",
            owner_id=210582977493598208,
            activity=discord.Game(name="Use .tb help"),
            intents=intents
        )
        self.db = kwargs.pop("database")
        self.credentials = credentials
        self.initialised_at = datetime.utcnow()
        self.session = aiohttp.ClientSession(loop=self.loop)

    # Custom reply handler.
    async def reply(self, ctx, text=None, embed=None, file=None, mention_author=False, delete_after=None):

        spare = deepcopy(file)  # File objects are onetime use, this allows us to try multiple variations of send.
        
        # First we attempt to use direct reply functionality
        try:
            await ctx.reply(text, embed=embed, file=spare, mention_author=mention_author, delete_after=delete_after)
            if file is not None:
                file.close()
            return
        except discord.HTTPException:
            pass
    
        # Fall back to straight up reply
        spare = deepcopy(file)
        try:
            await ctx.send(text, embed=embed, file=spare, delete_after=delete_after)
            if file is not None:
                file.close()
            return
        except discord.HTTPException:
            pass
    
        # Final fallback, DM invoker.
        try:
            await ctx.author.send(f"I cannot reply to your {ctx.command} command in {ctx.channel} on {ctx.guild}")
            return await ctx.author.send(text, embed=embed, file=file)
        except discord.HTTPException:
            if ctx.author.id == 210582977493598208:
                print(text)
    
        # At least try to warn them.
        return None

    async def on_ready(self):
        print(f'{self.user}: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')
        # Startup Modules
        load = [
            'ext.reactions',  # needs to be loaded fist.
            'ext.automod', 'ext.admin', 'ext.errors', 'ext.fixtures', 'ext.fun', 'ext.goals', 'ext.help', 'ext.images',
            'ext.info', 'ext.mod', 'ext.mtb', 'ext.notifications', 'ext.nufc', 'ext.quotes', 'ext.reminders',
            'ext.scores', 'ext.sidebar', 'ext.twitter', 'ext.lookup', "ext.transfers", 'ext.tv',
        ]
        for c in load:
            try:
                self.load_extension(c)
            except ExtensionAlreadyLoaded:
                pass
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")


loop = asyncio.get_event_loop()
loop.run_until_complete(run())
