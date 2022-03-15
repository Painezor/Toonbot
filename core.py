"""Master file for toonbot."""
import asyncio
import json
import logging
from asyncio import Task
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Set

import aiohttp
import asyncpg
from asyncpraw import Reddit
from discord import Intents, Game, Colour, Embed, Interaction, Message, http, NotFound, ButtonStyle
from discord.ext import commands
# Typehinting
from discord.ui import View, Button
from pyppeteer.browser import Browser

from ext.utils.football import Fixture, Competition, Team

logging.basicConfig(level=logging.INFO)

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


class Bot(commands.AutoShardedBot):
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
        self.scores_embeds: Dict[str | Competition, List[Embed]] = {}
        self.scores_messages: Dict[int, Dict[Message, List[Embed]]] = defaultdict(dict)
        self.scores_cache: Dict[int, Set[str]] = defaultdict(set)
        self.score_loop: Task | None = None
        self.fs_score_loop: Task | None = None

        # Notifications
        self.notifications_cache: List[asyncpg.Record] = []

        # QuoteDB
        self.quote_blacklist: List[int] = []

        # Reminders
        self.reminders: List[Task] = []

        # RSS
        self.eu_news: Task | None = None
        self.dev_blog: Task | None = None
        self.blog_cache: List[str] = []
        self.news_cached: bool = False
        self.dev_blog_cached: bool = False

        # Sidebar
        self.reddit_teams: List[asyncpg.Record] = []
        self.sidebar: Task | None = None
        self.reddit = Reddit(**self.credentials["Reddit"])

        # Streams
        self.streams: Dict[int, List] = defaultdict(list)

        # Transfers
        self.transfers: Task | None = None
        self.parsed_transfers: List[str] = []

        # TV
        self.tv: dict = {}

        print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

    async def setup_hook(self):
        """Load Cogs asynchronously"""
        for c in COGS:
            try:
                await self.load_extension('ext.' + c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")

    async def error(self, i: Interaction, e: str,
                    message: Message = None,
                    ephemeral: bool = True,
                    followup=False) -> Message:
        """Send a Generic Error Embed"""
        e = Embed(title="An Error occurred.", colour=Colour.red(), description=e)

        view = View()
        b = Button(emoji="<:Toonbot:952717855474991126>", url="http://www.discord.gg/a5NHvPx")
        b.style = ButtonStyle.url
        b.label = "Join Support Server"
        view.add_item(b)

        if message is not None:
            try:
                return await message.edit(embed=e)
            except NotFound:
                pass

        if i.response.is_done():  # If we need to do a followup.
            try:
                return await i.edit_original_message(embed=e)
            except NotFound:
                return await i.followup.send(embed=e, ephemeral=ephemeral)  # Return the message.
        else:
            await i.response.send_message(embed=e, ephemeral=ephemeral)
            return await i.original_message()

    async def reply(self, i: Interaction, message: Message = None, followup: bool = False, **kwargs) -> Message:
        """Send a Generic Interaction Reply"""
        if message is not None:
            try:
                return await message.edit(**kwargs)
            except NotFound:
                pass

        if i.response.is_done():  # If we need to do a followup.
            try:
                return await i.edit_original_message(**kwargs)
            except NotFound:
                if followup:  # Don't send messages if the message has previously been deleted.
                    return await i.followup.send(**kwargs, wait=True)  # Return the message.
        else:
            await i.response.send_message(**kwargs)
            return await i.original_message()


async def run():
    """Start the bot running, loading all credentials and the database."""
    db = await asyncpg.create_pool(**credentials['Postgres'])
    bot = Bot(database=db)
    try:
        await bot.start(credentials['bot']['token'])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i.name)
        await db.close()
        await bot.close()


loop = asyncio.new_event_loop()
loop.run_until_complete(run())
