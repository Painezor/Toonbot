"""Master file for toonbot."""
from asyncio import Task, new_event_loop
from collections import defaultdict
from datetime import datetime
from json import load
from logging import basicConfig, INFO
from typing import Dict, List, Set, Optional

from aiohttp import ClientSession, TCPConnector
from asyncpg import Record, Pool, create_pool
from asyncpraw import Reddit
from discord import Intents, Game, Embed, Message, http
from discord.ext.commands import AutoShardedBot
from pyppeteer.browser import Browser

from ext.utils.browser_utils import make_browser
from ext.utils.football import Fixture, Competition, Team
from ext.utils.reply import reply, error, dump_image

basicConfig(level=INFO)

# TODO: New logging commands
# TODO: Fix News command
# TODO: Verify that new attendance command is working
# TODO: Verify ruins command
# TODO: Verify tard command


http._set_api_version(9)

with open('credentials.json') as f:
    credentials = load(f)

COGS = ['errors',  # Utility Cogs
        # Slash commands.
        'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv', 'logs', 'lookup', 'mod',
        'nufc', 'poll', 'quotes', 'reminders', 'sidebar', 'streams',
        # Testing
        'testing'
        ]

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class Bot(AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, **kwargs):

        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb",
            owner_id=210582977493598208,
            activity=Game(name="with /slash_commands"),
            intents=Intents.all(),
            help_command=None
        )

        # Reply Handling
        self.reply = reply
        self.error = error
        self.dump_image = dump_image

        # Database & Credentials
        self.db: Pool = kwargs.pop("database")
        self.credentials: dict = credentials
        self.initialised_at = datetime.utcnow()
        self.invite: str = INVITE_URL

        # Admin
        self.COGS = COGS

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
        self.notifications_cache: List[Record] = []

        # QuoteDB
        self.quote_blacklist: List[int] = []
        self.quotes: List[Record] = []

        # Reminders
        self.reminders: List[Task] = []

        # RSS
        self.eu_news: Optional[Task] = None
        self.dev_blog: Optional[Task] = None
        self.blog_cache: List[Record] = []
        self.news_cache: List[str] = []
        self.news_cached: bool = False

        # Session // Scraping
        self.browser: Optional[Browser] = None
        self.session: Optional[ClientSession] = None

        # Sidebar
        self.reddit_teams: List[Record] = []
        self.sidebar: Optional[Task] = None
        self.reddit = Reddit(**self.credentials["Reddit"])

        # Streams
        self.streams: Dict[int, List] = defaultdict(list)

        # Transfers
        self.transfers: Optional[Task] | None = None
        self.parsed_transfers: List[str] = []

        # TV
        self.tv: dict = {}

        print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

    async def setup_hook(self):
        """Load Cogs asynchronously"""
        self.browser = await make_browser()
        self.session = ClientSession(loop=self.loop, connector=TCPConnector(ssl=False))

        for c in COGS:
            try:
                await self.load_extension('ext.' + c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")


async def run():
    """Start the bot running, loading all credentials and the database."""
    db = await create_pool(**credentials['ToonbotDB'])
    bot = Bot(database=db)
    try:
        await bot.start(credentials['bot']['token'])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i.name)
        await db.close()
        await bot.close()


loop = new_event_loop()
loop.run_until_complete(run())
