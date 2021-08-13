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

    async def on_ready(self):
        """Print notification to console that the bot has finished loading."""
        print(f'{self.user}: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')
        # Startup Modules
        load = [
            'ext.globalchecks',  # needs to be loaded fist.
            'ext.automod', 'ext.admin', 'ext.errors', 'ext.fixtures', 'ext.fun', 'ext.help', 'ext.images', 'ext.info',
            'ext.mod', 'ext.mtb', 'ext.notifications', 'ext.nufc', 'ext.quotes', 'ext.reminders', 'ext.reply',
            'ext.rss', 'ext.scores', 'ext.sidebar', 'ext.twitter', 'ext.lookup', 'ext.ticker', "ext.transfers",
            'ext.tv', 'ext.warships'
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
        await bot.close()


loop = asyncio.get_event_loop()
loop.run_until_complete(run())
