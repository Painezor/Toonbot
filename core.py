"""Master file for toonbot."""
from __future__ import annotations

import logging
from asyncio import new_event_loop
from collections import defaultdict
from datetime import datetime
from json import load
from typing import Optional, Callable, TYPE_CHECKING

import discord.utils
from aiohttp import ClientSession, TCPConnector
from asyncpg import create_pool
from asyncpraw import Reddit
from discord import Intents, Game, File
from discord.ext.commands import AutoShardedBot

from ext.utils.playwright_browser import make_browser
from ext.utils.reply import reply, error

if TYPE_CHECKING:
    from ext.scores import ScoreChannel
    from ext.ticker import TickerChannel
    from ext.transfers import TransferChannel
    from asyncio import Task, Semaphore
    from asyncpg import Record, Pool
    from playwright.async_api import BrowserContext
    from io import BytesIO
    import ext.toonbot_utils.flashscore as fs

discord.utils.setup_logging()

with open('credentials.json') as f:
    credentials = load(f)

COGS = ['errors',  # Utility Cogs
        # Slash commands.
        'metatoonbot',
        'admin', 'bans', 'fixtures', 'fun', 'images', 'info', 'logs', 'lookup', 'mod', 'nufc', 'poll', 'quotes',
        'reminders', 'scores', 'sidebar', 'streams', 'ticker', 'transfers', 'tv', 'translations'
        ]

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


# TODO: Global Speed optimisation -- Replace all += strings with a .join() method

class Bot(AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, **kwargs) -> None:

        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb",
            owner_id=210582977493598208,
            activity=Game(name="with /slash_commands"),
            intents=Intents.all(),
            help_command=None
        )

        # Reply Handling
        self.ticker_semaphore: Semaphore = None
        self.reply: Callable = reply
        self.error: Callable = error

        # Database & Credentials
        self.db: Pool = kwargs.pop("database")
        self.credentials: dict = credentials
        self.initialised_at = datetime.utcnow()
        self.invite: str = INVITE_URL

        # Admin
        self.COGS = COGS

        # Livescores
        self.games: list[fs.Fixture] = []
        self.teams: list[fs.Team] = []
        self.competitions: list[fs.Competition] = []
        self.score_channels: list[ScoreChannel] = []
        self.scores: Task | None = None

        # Notifications
        self.notifications_cache: list[Record] = []

        # QuoteDB
        self.quote_blacklist: list[int] = []
        self.quotes: list[Record] = []

        # Reminders
        self.reminders: set[Task] = set()

        # Session // Scraping
        self.browser: Optional[BrowserContext] = None
        self.session: Optional[ClientSession] = None

        # Sidebar
        self.reddit_teams: list[Record] = []
        self.sidebar: Optional[Task] = None
        self.reddit = Reddit(**self.credentials["Reddit"])

        # Streams
        self.streams: dict[int, list] = defaultdict(list)

        # Ticker
        self.ticker_channels: list[TickerChannel] = []

        # Transfers
        self.transfer_channels: list[TransferChannel] = []
        self.transfers: Optional[Task] | None = None
        self.parsed_transfers: list[str] = []

        # TV
        self.tv: dict = {}

        print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

    async def setup_hook(self) -> None:
        """Load Cogs asynchronously"""
        self.browser = await make_browser(self)
        self.session = ClientSession(loop=self.loop, connector=TCPConnector(ssl=False))

        for c in COGS:
            try:
                await self.load_extension(f'ext.{c}')
                logging.info(f'Loaded ext.{c}')
            except Exception as e:
                logging.error(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
        return

    def get_competition(self, comp_id: str) -> Optional[fs.Competition]:
	    """Retrieve a competition from the ones stored in the bot."""
	    return next((i for i in self.competitions if i.id == comp_id), None)

    def get_team(self, team_id: str) -> Optional[fs.Team]:
	    """Retrieve a Team from the ones stored in the bot."""
	    return next((i for i in self.teams if i.id == team_id), None)

    def get_fixture(self, fixture_id: str) -> Optional[fs.Fixture]:
	    """Retrieve a Fixture from the ones stored in the bot."""
	    return next((i for i in self.games if i.id == fixture_id), None)

    async def dump_image(self, data: BytesIO) -> str:
        """Save a stitched image"""
        ch = self.get_channel(874655045633843240)
        if ch is None:
            return None

        img_msg = await ch.send(file=File(fp=data, filename="dumped_image.png"))
        return img_msg.attachments[0].url


async def run() -> None:
    """Start the bot running, loading all credentials and the database."""
    db = await create_pool(**credentials['ToonbotDB'])
    bot = Bot(database=db)
    try:
        await bot.start(credentials['bot']['token'])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i)
        await db.close()
        await bot.close()


new_event_loop().run_until_complete(run())
