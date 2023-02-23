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

with open("credentials.json", "r") as f:
    credentials = load(f)

COGS = [
    "reply",  # Utility Cogs
    # Slash commands.
    "metatoonbot",
    "admin",
    "bans",
    "fixtures",
    "images",
    "info",
    "logs",
    "lookup",
    "memes",
    "mod",
    "nufc",
    "poll",
    "quotes",
    "reminders",
    "rng",
    "scores",
    "sidebar",
    "streams",
    "ticker",
    "transfers",
    "tv",
    "translations",
    "urbandictionary",
    "xkcd",
]

INVITE_URL = (
    "https://discord.com/api/oauth2/authorize?client_id="
    "250051254783311873&permissions=1514244730006"
    "&scope=bot%20applications.commands"
)


class Bot(AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, **kwargs) -> None:

        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb",
            owner_id=210582977493598208,
            activity=Game(name="with /slash_commands"),
            intents=Intents.all(),
            help_command=None,
        )

        # Reply Handling
        self.ticker_semaphore: Optional[Semaphore] = None
        self.reply: Callable = None
        self.error: Callable = None

        # Database & Credentials
        self.db: Pool = kwargs.pop("database")
        self.credentials: dict = credentials
        self.initialised_at = datetime.utcnow()
        self.invite: str = INVITE_URL

        # Admin
        self.cogs = COGS

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
        self.tv_dict: dict = {}
        x = f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}'
        logging.info(f"{x}\n" + "-" * len(x))

    async def setup_hook(self) -> None:
        """Load Cogs asynchronously"""
        self.browser = await make_browser()
        connector = TCPConnector(ssl=False)
        self.session = ClientSession(loop=self.loop, connector=connector)

        for c in COGS:
            try:
                await self.load_extension(f"ext.{c}")
                logging.info("Loaded ext.%s", c)
            except Exception as error:
                err = f"{type(error).__name__}: {error}"
                logging.error("Failed to load cog %s\n%s", c, err)
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
        try:
            file = File(fp=data, filename="dumped_image.png")
            channel = self.get_channel(874655045633843240)
            img_msg = await channel.send(file=file)
            return img_msg.attachments[0].url
        except AttributeError:
            return None

    async def cache_quotes(self) -> None:
        """Cache the QuoteDB"""
        async with self.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM quotes"""
                self.quotes = await connection.fetch(sql)


async def run() -> None:
    """Start the bot running, loading all credentials and the database."""
    database = await create_pool(**credentials["ToonbotDB"])
    bot = Bot(database=database)
    try:
        await bot.start(credentials["bot"]["token"])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i)
        await database.close()
        await bot.close()


new_event_loop().run_until_complete(run())
