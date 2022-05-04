"""Master file for toonbot."""
from asyncio import Task, new_event_loop
from datetime import datetime
from json import load
from logging import basicConfig, INFO
from typing import List, Optional

from aiohttp import ClientSession, TCPConnector
from asyncpg import Record, Pool, create_pool
from discord import Intents, Game
from discord.ext.commands import AutoShardedBot, when_mentioned
from pyppeteer.browser import Browser

from ext.utils.browser_utils import make_browser
from ext.utils.reply import reply, error, dump_image

basicConfig(level=INFO)

# https://vortex.worldofwarships.asia/api/encyclopedia/ships/


with open('credentials.json') as f:
	credentials = load(f)

COGS = [  # Utility Cogs
	'errors',

	# Slash commands.
	'admin', 'fun', 'images', 'info', 'logs', 'mod', 'poll', 'quotes', 'reminders', 'rss', 'twitchtracker',
	'warships',

	# Testing
	'testing'
]

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=964870918738419752&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class PBot(AutoShardedBot):
	"""The core functionality of the bot."""

	def __init__(self, **kwargs):

		super().__init__(
			description="Warships utility bot by Painezor#8489",
			command_prefix=when_mentioned,
			owner_id=210582977493598208,
			activity=Game(name="World of Warships"),
			intents=Intents.all(),
			help_command=None
		)

		# Reply Handling
		self.reply = reply
		self.error = error
		self.dump_image = dump_image

		# Admin
		self.COGS = COGS

		# Database & API Credentials
		self.db: Pool = kwargs.pop("database")
		self.credentials: dict = credentials
		self.initialised_at = datetime.utcnow()
		self.invite: str = INVITE_URL

		# Notifications
		self.notifications_cache: List[Record] = []

		# Reminders
		self.reminders: List[Task] = []

		# RSS
		self.eu_news: Optional[Task] = None
		self.dev_blog_task: Optional[Task] = None
		self.dev_blog_cache: List[Record] = []
		self.dev_blog_channels = List[int]
		self.news_cache: List[str] = []
		self.news_cached: bool = False

		# Session // Scraping
		self.browser: Optional[Browser] = None
		self.session: Optional[ClientSession] = None

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
	db = await create_pool(**credentials['painezBotDB'])
	bot = PBot(database=db)
	try:
		await bot.start(credentials['painezbot']['token'])
	except KeyboardInterrupt:
		for i in bot.cogs:
			await bot.unload_extension(i.name)
		await db.close()
		await bot.close()


loop = new_event_loop()
loop.run_until_complete(run())
