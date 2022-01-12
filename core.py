"""Master file for toonbot."""
import asyncio
import json
from datetime import datetime

import asyncpg
import discord
from discord.ext import commands

with open('credentials.json') as f:
    credentials = json.load(f)

COGS = [  # Utility Cogs
    'ext.errors', 'ext.session', 'ext.reply',

    # Slash commands.
    'ext.admin', 'ext.fixtures', 'ext.fun', 'ext.scores', 'ext.ticker', "ext.transfers", 'ext.tv',

    # Slash commands - You should probably check these
    'ext.images', 'ext.logs', 'ext.info', 'ext.lookup', 'ext.mod',

    'ext.quotes',

    # Old commands.
    'ext.help',
    'ext.nufc', 'ext.reminders', 'ext.rss',
    'ext.sidebar', 'ext.warships']


# Pending rewrite?
# 'ext.mtb', 'ext.twitter', 'ext.automod'


class Bot(commands.Bot):
    """The core functionality of the bot."""

    def __init__(self, **kwargs):
        intents = discord.Intents(bans=True, guilds=True, members=True, messages=True, reactions=True,
                                  voice_states=True, emojis=True)
        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb ",
            owner_id=210582977493598208,
            activity=discord.Game(name="Migrated to /slash_commands"),
            intents=intents
        )
        self.db = kwargs.pop("database")
        self.credentials = credentials
        self.initialised_at = datetime.utcnow()

        for c in COGS:
            try:
                self.load_extension(c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")

    async def on_ready(self):
        """Print notification to console that the bot has finished loading."""
        print(f'{self.user}: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')


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


loop = asyncio.new_event_loop()
loop.run_until_complete(run())
