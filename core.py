"""Master file for toonbot."""
import asyncio
import json
from abc import ABC
from datetime import datetime

import asyncpg
from discord import Intents, Game, Colour, Embed, Interaction, Message, app_commands, http
from discord.ext import commands

from ext.scores import LiveScores

# MESSAGE INTENTS
http._set_api_version(9)

with open('credentials.json') as f:
    credentials = json.load(f)

COGS = ['errors', 'session',  # Utility Cogs
        # Slash commands.
        'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv', 'logs', 'lookup', 'mod',
        'nufc', 'quotes', 'reminders', 'rss', 'sidebar', 'streams', 'warships',

        # Testing
        'testing'
        ]

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


async def error(interaction: Interaction, error_message: str, message: Message = None, ephemeral: bool = True) \
        -> Message:
    """Send a Generic Error Embed"""
    e = Embed(colour=Colour.red(), description=error_message)

    if message is None:
        return await interaction.response.send_message(embed=e, ephemeral=ephemeral)
    else:
        return await message.edit(embed=e)


async def reply(interaction: Interaction, message=None, **kwargs) -> Message:
    """Send a Generic Interaction Reply"""
    if interaction.response.is_done():  # If we need to do a followup.
        return await interaction.followup.send(**kwargs)

    if message is None:
        return await interaction.response.send_message(**kwargs)
    else:
        return await message.edit(**kwargs)


class Bot(commands.Bot, ABC):
    """The core functionality of the bot."""

    def __init__(self, **kwargs):
        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb ",
            owner_id=210582977493598208,
            activity=Game(name="with /slash_commands"),
            intents=Intents(bans=True, guilds=True, members=True, messages=True, reactions=True, voice_states=True,
                            emojis=True, message_content=True)
        )

        self.db = kwargs.pop("database")
        self.credentials = credentials
        self.initialised_at = datetime.utcnow()
        self.invite = INVITE_URL
        self.tree = app_commands.CommandTree(self)

        # Hackjob for reloading. Remove later.
        self.tree.add_command(LiveScores())

        self.error = error
        self.reply = reply

        print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

        for c in COGS:
            try:
                self.load_extension('ext.' + c)
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


loop = asyncio.new_event_loop()
loop.run_until_complete(run())
