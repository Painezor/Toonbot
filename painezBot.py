"""Master file for painezBot."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import TYPE_CHECKING

import aiohttp
import asyncpg
import discord
from discord.ext import commands

from ext.utils.playwright_browser import make_browser

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

    from ext.devblog import Blog
    from ext.news_tracker import Article, NewsChannel

    import ext.wows_api as api
    from ext.wows_api.warships import Ship
    from ext.twitch import Contributor, TBot, TrackerChannel


with open("credentials.json", encoding="utf-8") as fun:
    _credentials = json.load(fun)

COGS = [
    # Utility Cogs
    "ext.metapainezbot",
    # Slash commands.
    "ext.admin",
    "ext.bans",
    "ext.clans",
    "ext.codes",
    "ext.devblog",
    "ext.fitting",
    "ext.helpme",
    "ext.howitworks",
    "ext.info",
    "ext.logs",
    "ext.memeswows",
    "ext.mod",
    "ext.overmatch",
    "ext.reminders",
    "ext.news_tracker",
    "ext.translations",
    "ext.twitch",
    "ext.wows_encyclopedia",
    "ext.wows_stats",
]


logger = logging.getLogger("painezBot")
discord.utils.setup_logging()


class PBot(commands.AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, datab: asyncpg.Pool[asyncpg.Record]) -> None:
        super().__init__(
            description="World of Warships bot by Painezor#8489",
            command_prefix=commands.when_mentioned,
            owner_id=210582977493598208,
            activity=discord.Game(name="World of Warships"),
            intents=discord.Intents.all(),
            help_command=None,
        )

        # Admin
        self.available_cogs = COGS

        # Database & API Credentials
        self.db: asyncpg.Pool[asyncpg.Record] = datab  # pylint: disable=C0103
        self.initialised_at: datetime.datetime = datetime.datetime.utcnow()

        # Notifications
        self.notifications_cache: list[asyncpg.Record] = []

        # Reminders
        self.reminders: set[asyncio.Task[None]] = set()

        # Dev BLog
        self.dev_blog: asyncio.Task[None]
        self.dev_blog_cache: list[Blog] = []
        self.dev_blog_channels: list[int] = []

        # RSS: Cache & Channels
        self.news: asyncio.Task[None]
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
        self.clan_buildings: list[api.ClanBuilding] = []
        self.clan_battle_seasons: list[api.ClanBattleSeason]
        self.clan_battle_winners: dict[int, list[api.ClanBattleWinner]]
        self.maps: set[api.Map] = set()
        self.modes: set[api.GameMode] = set()
        self.modules: dict[int, api.Module] = dict()
        self.ships: list[Ship] = []

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
            except commands.ExtensionError:
                logger.exception("Failed to load cog %s", i, exc_info=True)
        return


async def run() -> None:
    """Start the bot running, loading all credentials and the database."""
    database = await asyncpg.create_pool(**_credentials["painezBotDB"])

    if database is None:
        raise ConnectionError("Failed to initialise database.")

    bot = PBot(datab=database)

    try:
        await bot.start(_credentials["painezbot"]["token"])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i)

        await bot.db.close()
        await bot.close()


asyncio.new_event_loop().run_until_complete(run())
