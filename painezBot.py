"""Master file for painezBot."""
from __future__ import annotations

import logging
from asyncio import new_event_loop
from datetime import datetime
from json import load
from typing import TYPE_CHECKING, Callable

import discord
from aiohttp import ClientSession, TCPConnector
from asyncpg import create_pool
from discord.ext.commands import AutoShardedBot, when_mentioned

from ext.painezbot_utils.clan import ClanBuilding, Clan
from ext.utils.playwright_browser import make_browser

if TYPE_CHECKING:
    from ext.painezbot_utils.player import Map, GameMode, Player
    from ext.painezbot_utils.ship import ShipType, Module, Ship
    from ext.news_tracker import NewsChannel, Article
    from ext.devblog import Blog
    from ext.twitch import Contributor, TrackerChannel, TBot
    from playwright.async_api import BrowserContext
    from typing import Optional
    from asyncpg import Record, Pool
    from asyncio import Task

discord.utils.setup_logging()

with open("credentials.json") as f:
    credentials = load(f)

COGS = [
    # Utility Cogs
    "reply",
    "metapainezbot",
    # Slash commands.
    "admin",
    "bans",
    "devblog",
    "images",
    "info",
    "logs",
    "mod",
    "reminders",
    "news_tracker",
    "translations",
    "twitch",
    "warships",
]


class PBot(AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, **kwargs) -> None:

        super().__init__(
            description="World of Warships bot by Painezor#8489",
            command_prefix=when_mentioned,
            owner_id=210582977493598208,
            activity=discord.Game(name="World of Warships"),
            intents=discord.Intents.all(),
            help_command=None,
        )

        # Reply Handling
        self.reply: Callable = None
        self.error: Callable = None

        # Admin
        self.COGS: list[str] = COGS

        # Database & API Credentials
        self.db: Pool = kwargs.pop("database")
        self.credentials: dict = credentials
        self.initialised_at: datetime = datetime.utcnow()

        # Notifications
        self.notifications_cache: list[Record] = []

        # Reminders
        self.reminders: set[Task] = set()

        # Dev BLog
        self.dev_blog: Optional[Task] = None
        self.dev_blog_cache: list[Blog] = []
        self.dev_blog_channels: list[int] = []

        # RSS: Cache & Channels
        self.news: Optional[Task] = None
        self.news_cache: list[Article] = []
        self.news_channels: list[NewsChannel] = []

        # Session // Scraping
        self.browser: Optional[BrowserContext] = None
        self.session: Optional[ClientSession] = None

        # Twitch API
        self.twitch: TBot = None
        self.tracker_channels: list[TrackerChannel] = []

        # Wargaming API
        self.wg_id: str = kwargs.pop("wg_id")

        self.contributors: list[Contributor] = []
        self.clans: list[Clan] = []
        self.clan_buildings: list[ClanBuilding] = []
        self.players: list[Player] = []
        self.maps: list[Map] = []
        self.modes: list[GameMode] = []
        self.modules: list[Module] = []
        self.pr_data: dict = {}
        self.pr_data_updated_at: Optional[datetime] = None
        self.pr_sums: tuple[int, int, int]  # Dmg WR Kills
        self.ships: list[Ship] = []
        self.ship_types: list[ShipType] = []

        # Callables
        self.get_ship: Callable = None
        fm = "%d-%m-%Y %H:%M:%S"
        strt = f"Bot started: {datetime.now().strftime(fm)}"
        logging.info(f"{strt}\n{'=' * len(strt)}")

    def get_clan(self, clan_id: int) -> Clan:
        """Get a Clan object from Stored Clans"""
        try:
            clan = next(i for i in self.clans if i.clan_id == clan_id)
        except StopIteration:
            clan = Clan(self, clan_id)
            self.clans.append(clan)
        return clan

    def get_player(self, account_id: int) -> Player:
        """Get a Player object from stored or generate a one."""
        try:
            return next(i for i in self.players if i.account_id == account_id)
        except StopIteration:
            p = Player(account_id)
            self.players.append(p)
            return p

    def get_ship_type(self, match: str) -> ShipType:
        """Get a ShipType object matching a string"""
        return next(i for i in self.ship_types if i.match == match)

    async def setup_hook(self):
        """Load Cogs asynchronously"""
        self.browser = await make_browser()
        connector = TCPConnector(ssl=False)
        self.session = ClientSession(loop=self.loop, connector=connector)

        for c in COGS:
            try:
                await self.load_extension("ext." + c)
                logging.info(f"Loaded extension {c}")
            except Exception as e:
                logging.info(f"Cog Load Failed: {c}\n{type(e).__name__}: {e}")


async def run():
    """Start the bot running, loading all credentials and the database."""
    db = await create_pool(**credentials["painezBotDB"])

    bot = PBot(database=db, wg_id=credentials["Wargaming"]["client_id"])

    try:
        await bot.start(credentials["painezbot"]["token"])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i)
        await db.close()
        await bot.close()


new_event_loop().run_until_complete(run())
