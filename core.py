"""Master file for toonbot."""
from asyncio import Task
from asyncio import new_event_loop
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from json import load
from logging import basicConfig, INFO
from typing import Dict, List, Set

from aiohttp import ClientSession, TCPConnector
from asyncpg import Record, Pool, create_pool
from asyncpraw import Reddit
from discord import Intents, Game, Colour, Embed, Interaction, Message, http, NotFound, ButtonStyle, File
from discord.ext.commands import AutoShardedBot
from discord.ui import View, Button
from pyppeteer.browser import Browser

from ext.utils.browser_utils import make_browser
from ext.utils.football import Fixture, Competition, Team

basicConfig(level=INFO)

http._set_api_version(9)

# TODO: Global deprecation of interaction.client where possible
# TODO: add_page_buttons pass bot
# TODO: New logging commands
# TODO: Verify that new attendance command is working
# TODO: Fix News command
# TODO: Verify emoji command


with open('credentials.json') as f:
    credentials = load(f)

COGS = ['errors',  # Utility Cogs
        # Slash commands.
        'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv', 'logs', 'lookup', 'mod',
        'nufc', 'poll', 'quotes', 'reminders', 'rss', 'sidebar', 'streams', 'warships',

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
            command_prefix=".tb ",
            owner_id=210582977493598208,
            activity=Game(name="with /slash_commands"),
            intents=Intents.all()
        )

        self.db: Pool = kwargs.pop("database")
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
        self.notifications_cache: List[Record] = []

        # QuoteDB
        self.quote_blacklist: List[int] = []
        self.quotes: Dict[int, Record] = {}

        # Reminders
        self.reminders: List[Task] = []

        # RSS
        self.eu_news: Task | None = None
        self.dev_blog: Task | None = None
        self.blog_cache: List[str] = []
        self.news_cached: bool = False
        self.dev_blog_cached: bool = False

        # Session // Scraping
        self.browser: Browser | None = None
        self.session: ClientSession | None = None

        # Sidebar
        self.reddit_teams: List[Record] = []
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
        self.browser = await make_browser()
        self.session = ClientSession(loop=self.loop, connector=TCPConnector(ssl=False))

        for c in COGS:
            try:
                await self.load_extension('ext.' + c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")

    async def dump_image(self, img: BytesIO) -> str | None:
        """Dump an image to discord & return its URL to be used in embeds"""
        ch = self.get_channel(874655045633843240)
        img_msg = await ch.send(file=File(fp=img, filename="dumped_image.png"))
        url = img_msg.attachments[0].url
        return None if url == "none" else url

    @staticmethod
    async def error(i: Interaction, e: str, message: Message = None, ephemeral: bool = True, followup=True) -> Message:
        """Send a Generic Error Embed"""
        e: Embed = Embed(title="An Error occurred.", colour=Colour.red(), description=e)

        view = View()
        b = Button(emoji="<:Toonbot:952717855474991126>", url="http://www.discord.gg/a5NHvPx", style=ButtonStyle.url)
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
                if followup:
                    return await i.followup.send(embed=e, ephemeral=ephemeral)  # Return the message.
        else:
            await i.response.send_message(embed=e, ephemeral=ephemeral)
            return await i.original_message()

    @staticmethod
    async def reply(i: Interaction, message: Message = None, followup: bool = True, **kwargs) -> Message:
        """Generic reply handler."""
        if message is None and not i.response.is_done():
            await i.response.send_message(**kwargs)
            return await i.original_message()

        if hasattr(kwargs, "file"):
            kwargs.update({"attachments": [kwargs.pop("file")]})

        if message is not None:
            try:
                return await message.edit(**kwargs)
            except NotFound:
                pass

        else:
            try:
                return await i.edit_original_message(**kwargs)
            except NotFound:
                if followup:  # Don't send messages if the message has previously been deleted.
                    return await i.followup.send(**kwargs, wait=True)  # Return the message.


async def run():
    """Start the bot running, loading all credentials and the database."""
    db = await create_pool(**credentials['Postgres'])
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
