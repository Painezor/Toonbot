"""Master file for toonbot."""
from __future__ import annotations

import asyncio
import collections
import datetime
import json
import logging
import typing

import aiohttp
import asyncpg
import asyncpraw
import discord
from discord.ext import commands

from ext.utils.playwright_browser import make_browser

if typing.TYPE_CHECKING:
    from io import BytesIO

    from playwright.async_api import BrowserContext

    import ext.flashscore as fs
    from ext.scores import ScoreChannel
    from ext.streams import Stream
    from ext.ticker import TickerChannel
    from ext.transfers import TransferChannel


with open("credentials.json", mode="r", encoding="utf-8") as fun:
    _credentials = json.load(fun)

COGS = [
    # Slash commands.
    "ext.metatoonbot",
    "ext.admin",
    "ext.bans",
    "ext.fixtures",
    "ext.images",
    "ext.info",
    "ext.logs",
    "ext.lookup",
    "ext.memes",
    "ext.mod",
    "ext.nufc",
    "ext.poll",
    "ext.quotes",
    "ext.reminders",
    "ext.rng",
    "ext.scores",
    "ext.sidebar",
    "ext.stadiums",
    "ext.streams",
    "ext.ticker",
    "ext.transfers",
    "ext.tv",
    "ext.translations",
    "ext.urbandictionary",
    "ext.xkcd",
]

INVITE_URL = (
    "https://discord.com/api/oauth2/authorize?client_id="
    "250051254783311873&permissions=1514244730006"
    "&scope=bot%20applications.commands"
)

logger = logging.getLogger("core")
discord.utils.setup_logging()


class Bot(commands.AutoShardedBot):
    """The core functionality of the bot."""

    def __init__(self, database: asyncpg.Pool) -> None:
        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=commands.when_mentioned,
            owner_id=210582977493598208,
            activity=discord.Game(name="⚽ Football"),
            intents=discord.Intents.all(),
            help_command=None,
        )

        # Admin
        self.available_cogs = COGS

        # Database & Credentials
        self.db: asyncpg.Pool = database  # pylint: disable=C0103
        self.initialised_at: datetime.datetime = datetime.datetime.utcnow()
        self.invite: str = INVITE_URL

        # Fixtures
        self.fixture_defaults: list[asyncpg.Record] = []

        # Livescores
        self.games: list[fs.Fixture] = []
        self.teams: list[fs.Team] = []
        self.competitions: set[fs.Competition] = set()
        self.score_channels: list[ScoreChannel] = []
        self.scores: typing.Optional[asyncio.Task] = None

        # Notifications
        self.notifications_cache: list[asyncpg.Record] = []

        # Polls
        self.active_polls: set[asyncio.Task] = set()

        # QuoteDB
        self.quote_blacklist: list[int] = []
        self.quotes: list[asyncpg.Record] = []

        # Reminders
        self.reminders: set[asyncio.Task] = set()

        # Session // Scraping
        self.browser: BrowserContext
        self.session: aiohttp.ClientSession

        # Sidebar
        self.reddit_teams: list[asyncpg.Record] = []
        self.sidebar: asyncio.Task

        rdt = asyncpraw.Reddit(**_credentials["Reddit"])
        self.reddit: asyncpraw.Reddit = rdt

        # Streams
        self.streams: dict[int, list[Stream]] = collections.defaultdict(list)

        # Ticker
        self.ticker_channels: list[TickerChannel] = []

        # Transfers
        self.transfer_channels: list[TransferChannel] = []
        self.transfers: asyncio.Task
        self.parsed_transfers: list[str] = []

        # TV
        self.tv_dict: dict = {}

        # Announce aliveness
        started = self.initialised_at.strftime("%d-%m-%Y %H:%M:%S")
        started = f"Toonbot __init__ ran: {started}"
        logger.info(f"{started}\n" + "-" * len(started))

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

    def get_competition(self, value: str) -> typing.Optional[fs.Competition]:
        """Retrieve a competition from the ones stored in the bot."""
        if value is None:
            return None

        for i in self.competitions:
            if i.id == value:
                return i

            if i.title.casefold() == value.casefold():
                return i

            if i.url is not None:
                if i.url.rstrip("/") == value.rstrip("/"):
                    return i

        # Fallback - Get First Partial match.
        for i in self.competitions:
            if i.url is not None and "http" in value:
                if value in i.url:
                    logger.info(
                        "Partial url: %s to %s (%s)",
                        value,
                        i.id,
                        i.title,
                    )
                    return i
        return None

    def get_team(self, team_id: str) -> typing.Optional[fs.Team]:
        """Retrieve a Team from the ones stored in the bot."""
        return next((i for i in self.teams if i.id == team_id), None)

    def get_fixture(self, fixture_id: str) -> typing.Optional[fs.Fixture]:
        """Retrieve a Fixture from the ones stored in the bot."""
        return next((i for i in self.games if i.id == fixture_id), None)

    async def dump_image(self, data: BytesIO) -> typing.Optional[str]:
        """Save a stitched image"""
        file = discord.File(fp=data, filename="dumped_image.png")
        channel = self.get_channel(874655045633843240)

        if channel is None:
            return None

        channel = typing.cast(discord.TextChannel, channel)

        img_msg = await channel.send(file=file)
        return img_msg.attachments[0].url


async def run() -> None:
    """Start the bot running, loading all credentials and the database."""
    database = await asyncpg.create_pool(**_credentials["ToonbotDB"])

    if database is None:
        raise ConnectionError("Failed to initialise database.")

    bot: Bot = Bot(database=database)

    try:
        await bot.start(_credentials["bot"]["token"])
    except KeyboardInterrupt:
        for i in bot.cogs:
            await bot.unload_extension(i)

        if bot.db is not None:
            await bot.db.close()

        await bot.close()


asyncio.new_event_loop().run_until_complete(run())
