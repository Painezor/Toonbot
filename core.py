"""Master file for toonbot."""
import asyncio
import json
from abc import ABC
from asyncio import Task
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, List

import aiohttp
import asyncpg
from discord import Intents, Game, Colour, Embed, Interaction, Message, http, NotFound
from discord.ext import commands
# Loading of commands.
from pyppeteer.browser import Browser

# MESSAGE INTENTS
from ext.utils.football import Fixture, Competition, Team

http._set_api_version(9)

with open('credentials.json') as f:
    credentials = json.load(f)

COGS = ['errors', 'session',  # Utility Cogs
        # Slash commands.
        'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv', 'logs', 'lookup', 'mod',
        'nufc', 'poll', 'quotes', 'reminders', 'rss', 'sidebar', 'streams', 'warships',

        # Testing
        'testing'
        ]

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


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

        self.db: asyncpg.Pool = kwargs.pop("database")
        self.browser: Browser | None = None
        self.session: aiohttp.ClientSession | None = None
        self.credentials: dict = credentials
        self.initialised_at = datetime.utcnow()
        self.invite: str = INVITE_URL

        # Livescores
        self.games: Dict[str, Fixture] = dict()
        self.teams: Dict[str, Team] = dict()
        self.competitions: Dict[str, Competition] = dict()
        self.fs_games: Dict[str, Fixture] = dict()
        self.scores_embeds: dict = {}
        self.scores_messages: dict = defaultdict(dict)
        self.score_loop: Task | None = None
        self.fs_score_loop: Task | None = None

        # Notifications
        self.notifications_cache: List[asyncpg.Record] = []

        # QuoteDB
        self.quote_blacklist: List[int] = []

        # RSS
        self.eu_news: Task | None = None
        self.dev_blog: Task | None = None
        self.blog_cache: List[str] = []
        self.news_cached: bool = False
        self.dev_blog_cached: bool = False

        print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

        for c in COGS:
            try:
                self.load_extension('ext.' + c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")

    async def error(self, i: Interaction, e: str, message: Message = None, ephemeral: bool = True) -> Optional[Message]:
        """Send a Generic Error Embed"""
        if self.is_closed():
            return None
        e = Embed(colour=Colour.red(), description=e)

        if message is not None:
            try:
                return await message.edit(embed=e)
            except NotFound:
                pass

        if i.response.is_done():  # If we need to do a followup.
            return await i.followup.send(embed=e, ephemeral=ephemeral)
        else:
            return await i.response.send_message(embed=e, ephemeral=ephemeral)

    async def reply(self, i: Interaction, message: Message = None, **kwargs) -> Message | None:
        """Send a Generic Interaction Reply"""
        if self.is_closed():
            return

        if message is not None:
            try:
                return await message.edit(**kwargs)
            except NotFound:
                pass
        if i.response.is_done():  # If we need to do a followup.
            return await i.followup.send(**kwargs)
        else:
            return await i.response.send_message(**kwargs)


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
