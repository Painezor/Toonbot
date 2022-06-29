"""Master file for toonbot."""
from asyncio import new_event_loop
from collections import defaultdict
from datetime import datetime
from json import load
from logging import basicConfig, INFO
from typing import Dict, List, Optional, Callable, TYPE_CHECKING

from aiohttp import ClientSession, TCPConnector
from asyncpg import create_pool
from asyncpraw import Reddit
from discord import Intents, Game
from discord.ext.commands import AutoShardedBot

from ext.utils.browser_utils import make_browser
from ext.utils.flashscore import Team, Competition, Fixture
from ext.utils.reply import reply, error

if TYPE_CHECKING:
    from ext.scores import ScoreChannel
    from ext.ticker import TickerChannel
    from ext.transfers import TransferChannel

    from asyncio import Task, Semaphore
    from asyncpg import Record, Pool
    from pyppeteer.browser import Browser

basicConfig(level=INFO)


with open('credentials.json') as f:
    credentials = load(f)

COGS = ['errors',  # Utility Cogs
        # Slash commands.
        'meta-toonbot',
        'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv', 'logs', 'lookup', 'mod',
        'nufc', 'poll', 'quotes', 'reminders', 'sidebar', 'streams',
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
        self.games: List[Fixture] = []
        self.teams: List[Team] = []
        self.competitions: List[Competition] = []
        self.score_channels: List[ScoreChannel] = []
        self.scores: Task | None = None

        # Notifications
        self.notifications_cache: List[Record] = []

        # QuoteDB
        self.quote_blacklist: List[int] = []
        self.quotes: List[Record] = []

        # Reminders
        self.reminders: List[Task] = []

        # Session // Scraping
        self.browser: Optional[Browser] = None
        self.session: Optional[ClientSession] = None

        # Sidebar
        self.reddit_teams: List[Record] = []
        self.sidebar: Optional[Task] = None
        self.reddit = Reddit(**self.credentials["Reddit"])

        # Streams
        self.streams: Dict[int, List] = defaultdict(list)

        # Ticker
        self.ticker_channels: List[TickerChannel] = []

        # Transfers
        self.transfer_channels: List[TransferChannel] = []
        self.transfers: Optional[Task] | None = None
        self.parsed_transfers: List[str] = []

        # TV
        self.tv: dict = {}

        print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

    async def setup_hook(self) -> None:
        """Load Cogs asynchronously"""
        self.browser = await make_browser()
        self.browser.bot = self
        self.session = ClientSession(loop=self.loop, connector=TCPConnector(ssl=False))

        for c in COGS:
            try:
                await self.load_extension('ext.' + c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")
        return

    def get_competition(self, comp_id: str) -> Optional[Competition]:
        """Retrieve a competition from the ones stored in the bot."""
        return next((i for i in self.competitions if getattr(i, 'id', None) == comp_id), None)

    def get_team(self, team_id: str) -> Optional[Team]:
        """Retrieve a Team from the ones stored in the bot."""
        return next((i for i in self.teams if getattr(i, 'id', None) == team_id), None)

    def get_fixture(self, fixture_id: str) -> Optional[Fixture]:
        """Retrieve a Fixture from the ones stored in the bot."""
        return next((i for i in self.games if getattr(i, 'id', None) == fixture_id), None)


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


loop = new_event_loop()
loop.run_until_complete(run())
