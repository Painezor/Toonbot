"""Master file for painezBot."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import typing

import aiohttp
import asyncpg
import discord
from discord.ext import commands

from ext.utils.playwright_browser import make_browser

if typing.TYPE_CHECKING:
    from playwright.async_api import BrowserContext

    from ext.devblog import Blog
    from ext.news_tracker import Article, NewsChannel

    import ext.utils.wows_api as api
    from ext.painezbot_utils.module import Module
    from ext.painezbot_utils.ship import Ship, ShipType
    from ext.twitch import Contributor, TBot, TrackerChannel


with open("credentials.json", encoding="utf-8") as fun:
    credentials = json.load(fun)

COGS = [
    # Utility Cogs
    "ext.reply",
    "ext.metapainezbot",
    # Slash commands.
    "ext.admin",
    "ext.bans",
    "ext.clans",
    "ext.codes",
    "ext.devblog",
    "ext.fitting",
    "ext.helpme",
    "ext.images",
    "ext.info",
    "ext.logs",
    "ext.maps",
    "ext.memeswows",
    "ext.mod",
    "ext.overmatch",
    "ext.reminders",
    "ext.news_tracker",
    "ext.translations",
    "ext.twitch",
    "ext.wows_stats",
]


logger = logging.getLogger("painezBot")
discord.utils.setup_logging()


class PBot(commands.AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, database: asyncpg.Pool) -> None:

        super().__init__(
            description="World of Warships bot by Painezor#8489",
            command_prefix=commands.when_mentioned,
            owner_id=210582977493598208,
            activity=discord.Game(name="World of Warships"),
            intents=discord.Intents.all(),
            help_command=None,
        )

        # Reply Handling
        self.error: typing.Callable

        # Database & API Credentials
        self.db: asyncpg.Pool = database
        self.initialised_at: datetime.datetime = datetime.datetime.utcnow()

        # Notifications
        self.notifications_cache: list[asyncpg.Record] = []

        # Reminders
        self.reminders: set[asyncio.Task] = set()

        # Dev BLog
        self.dev_blog: asyncio.Task
        self.dev_blog_cache: list[Blog] = []
        self.dev_blog_channels: list[int] = []

        # RSS: Cache & Channels
        self.news: asyncio.Task
        self.news_cache: list[Article] = []
        self.news_channels: list[NewsChannel] = []

        # Session // Scraping
        self.browser: BrowserContext
        self.session: aiohttp.ClientSession

        # Twitch API
        self.twitch: TBot
        self.tracker_channels: list[TrackerChannel] = []

        # Wows
        self.contributors: list[Contributor] = []
        self.clans: list[api.Clan] = []
        self.clan_buildings: list[api.ClanBuilding] = []
        self.players: list[api.Player] = []
        self.maps: list[api.Map] = []
        self.modes: list[api.GameMode] = []
        self.modules: list[Module] = []
        self.pr_data: dict = {}
        self.pr_data_updated_at: datetime.datetime
        self.pr_sums: tuple[int, int, int]  # Dmg WR Kills
        self.ships: list[Ship] = []
        self.ship_types: list[ShipType] = []

        # Announce aliveness
        started = self.initialised_at.strftime("%d-%m-%Y %H:%M:%S")
        text = f"Bot __init__ ran: {started}"
        logger.info(f"{text}\n" + "-" * len(text))

    async def setup_hook(self) -> None:
        """Create our browsers then load our cogs."""

        # aiohttp
        cnt = aiohttp.TCPConnector(ssl=False)
        self.session = aiohttp.ClientSession(loop=self.loop, connector=cnt)

        # playwright
        self.browser = await make_browser()

        for i in COGS:
            try:
                await self.load_extension(i)
                logger.info("Loaded %s", i)
            except commands.ExtensionError as error:
                err = f"{type(error).__name__}: {error}"
                logger.error("Failed to load cog %s\n%s", i, err)
        return

    def get_clan(self, clan_id: int) -> typing.Optional[api.Clan]:
        """Get a Clan object from Stored Clans"""
        return next((i for i in self.clans if i.clan_id == clan_id), None)

    def get_player(self, account_id: int) -> typing.Optional[api.Player]:
        """Get a Player object from stored or generate a one."""
        plr = self.players
        return next((i for i in plr if i.account_id == account_id), None)

    def get_ship(self, identifier: str | int) -> typing.Optional[Ship]:
        """Get a Ship object from a list of the bots ships"""
        for i in self.ships:
            if i.ship_id_str is None:
                continue

            if i.ship_id_str == identifier:
                return i

            if i.ship_id == identifier:
                return i
        return None

    def get_ship_type(self, match: str) -> ShipType:
        """Get a ShipType object matching a string"""
        return next(i for i in self.ship_types if i.match == match)


async def run() -> None:
    """Start the bot running, loading all credentials and the database."""
    database = await asyncpg.create_pool(**credentials["painezBotDB"])

    if database is None:
        raise ConnectionError("Failed to initialise database.")

    bot = PBot(database=database)

    try:
        await bot.start(credentials["painezbot"]["token"])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i)

        if bot.db is not None:
            await bot.db.close()
        await bot.close()


asyncio.new_event_loop().run_until_complete(run())
