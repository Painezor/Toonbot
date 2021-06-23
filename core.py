"""Master file for toonbot."""
import asyncio
import json
from datetime import datetime

import aiohttp
import asyncpg
import discord
from discord.ext import commands
from discord.ext.commands import ExtensionAlreadyLoaded

with open('credentials.json') as f:
    credentials = json.load(f)


class Bot(commands.Bot):
    """The core functionality of the bot."""
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
    async def reply(self, ctx, text=None, embed=None, file: discord.File = None, mention_author=False,
                    delete_after=None):
        """Master reply handler for bot, with fallbacks."""
        if self.is_closed():
            return

        # First we attempt to use direct reply functionality
        if ctx.me.permissions_in(ctx.channel).send_messages:
            if ctx.me.permissions_in(ctx.channel).embed_links or embed is None:
                try:
                    return await ctx.reply(text, embed=embed, file=file, mention_author=mention_author,
                                           delete_after=delete_after)
                except discord.HTTPException:
                    try:
                        return await ctx.send(text, embed=embed, file=file, delete_after=delete_after)
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
        if ctx.me.permissions_in(ctx.channel).add_reactions:
            await ctx.message.add_reaction('🤐')
        return None

    async def on_ready(self):
        """Print notification to console that the bot has finished loading."""
        print(f'{self.user}: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')
        # Startup Modules
        load = [
            'ext.globalchecks',  # needs to be loaded fist.
            'ext.automod', 'ext.admin', 'ext.errors', 'ext.fixtures', 'ext.fun', 'ext.help', 'ext.images', 'ext.info',
            'ext.mod', 'ext.mtb', 'ext.notifications', 'ext.nufc', 'ext.quotes', 'ext.reminders', 'ext.rss',
            'ext.scores', 'ext.sidebar', 'ext.twitter', 'ext.lookup', 'ext.ticker', "ext.transfers", 'ext.tv',
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


async def run():
    """Start the bot running, loading all credentials and the database."""
    db = await asyncpg.create_pool(**credentials['Postgres'])
    bot = Bot(database=db)
    try:
        await bot.start(credentials['bot']['token'])
    except KeyboardInterrupt:
        for i in bot.cogs:
            bot.unload_extension(i.name)
        await db.close()
        await bot.logout()


loop = asyncio.get_event_loop()
loop.run_until_complete(run())
