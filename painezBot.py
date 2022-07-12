"""Master file for painezBot."""
from __future__ import annotations

from asyncio import new_event_loop
from datetime import datetime
from json import load
from logging import basicConfig, INFO
from typing import TYPE_CHECKING, Tuple

from aiohttp import ClientSession, TCPConnector
from asyncpg import create_pool
from discord import Intents, Game
from discord.ext.commands import AutoShardedBot, when_mentioned
from twitchio.ext import commands

from ext.painezbot_utils.clan import ClanBuilding, Clan
from ext.painezbot_utils.player import Player
from ext.painezbot_utils.ship import ShipSentinel
from ext.utils.pw_browser import make_browser
from ext.utils.reply import reply, error

if TYPE_CHECKING:
	from ext.painezbot_utils.player import Map, GameMode
	from ext.painezbot_utils.ship import ShipType, Module, Ship
	from ext.news_tracker import NewsChannel, Article
	from ext.devblog import Blog
	from ext.twitch_tracker import Contributor, TrackerChannel
	from playwright.async_api import BrowserContext
	from typing import List, Optional
	from asyncpg import Record, Pool
	from asyncio import Task

basicConfig(level=INFO)

with open('credentials.json') as f:
	credentials = load(f)

COGS = [
	# Utility Cogs
	'errors', 'meta_painezbot',
	# Slash commands.
	'admin', 'devblog', 'info', 'logs', 'mod', 'reminders', 'news_tracker',
	'twitch_tracker', 'warships'
]


class PBot(AutoShardedBot):
	"""The core functionality of the bot."""

	def __init__(self, **kwargs) -> None:

		super().__init__(
			description="World of Warships bot by Painezor#8489",
			command_prefix=when_mentioned,
			owner_id=210582977493598208,
			activity=Game(name="World of Warships"),
			intents=Intents.all(),
			help_command=None
		)

		# Reply Handling
		self.reply = reply
		self.error = error

		# Admin
		self.COGS = COGS

		# Database & API Credentials
		self.db: Pool = kwargs.pop("database")
		self.credentials: dict = credentials
		self.initialised_at = datetime.utcnow()

		# Notifications
		self.notifications_cache: List[Record] = []

		# Reminders
		self.reminders: List[Task] = []

		# Dev BLog
		self.dev_blog: Optional[Task] = None
		self.dev_blog_cache: List[Blog] = []
		self.dev_blog_channels: List[int] = []

		# RSS: Cache & Channels
		self.news: Optional[Task] = None
		self.news_cache: List[Article] = []
		self.news_channels: List[NewsChannel] = []

		# Session // Scraping
		self.browser: Optional[BrowserContext] = None
		self.session: Optional[ClientSession] = None

		# Twitch API
		self.twitch: TwitchBot = kwargs.pop('tbot')
		self.tracker_channels: List[TrackerChannel] = []

		# Wargaming API
		self.WG_ID = kwargs.pop("wg_id")

		self.contributors: List[Contributor] = []
		self.clans: List[Clan] = []
		self.clan_buildings: List[ClanBuilding] = []
		self.maps: List[Map] = []
		self.modes: List[GameMode] = []
		self.modules: List[Module] = []
		self.players: List[Player] = []
		self.pr_data: dict = {}
		self.pr_data_updated_at: Optional[datetime] = None
		self.pr_sums: Tuple[int, int, int]  # Dmg WR Kills
		self.ships: List[Ship] = []
		self.ship_types: List[ShipType] = []

		print(f'Bot __init__ ran: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

	async def setup_hook(self):
		"""Load Cogs asynchronously"""
		self.browser = await make_browser(self)
		self.session = ClientSession(loop=self.loop, connector=TCPConnector(ssl=False))

		for c in COGS:
			try:
				await self.load_extension('ext.' + c)
				print(f"Loaded extension {c}")
			except Exception as e:
				print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')

	def get_player(self, account_id: int) -> Player:
		"""Get a Player object from those stored within the bot, or generate a new one."""
		try:
			return next(i for i in self.players if i.account_id == account_id)
		except StopIteration:
			p = Player(self, account_id)
			self.players.append(p)
			return p

	def get_ship(self, identifier: str | int) -> Optional[Ship | ShipSentinel]:
		"""Get a Ship object from a list of the bots ships"""
		if identifier is None:
			return None

		try:
			return next(i for i in self.ships if getattr(i, 'ship_id_str', None) == identifier)
		except StopIteration:  # Fallback
			try:
				return next(i for i in self.ships if getattr(i, 'ship_id', None) == identifier)
			except StopIteration:
				return next(i for i in ShipSentinel if i.id == identifier)

	def get_clan(self, clan_id: int) -> Clan:
		"""Get a Clan object from Stored Clans"""
		try:
			clan = next(i for i in self.clans if i.clan_id == clan_id)
		except StopIteration:
			clan = Clan(self, clan_id)
			self.clans.append(clan)
		return clan

	def get_ship_type(self, match: str) -> ShipType:
		"""Get a ShipType object matching a string"""
		return next(i for i in self.ship_types if i.match == match)


class TwitchBot(commands.Bot):
	"""Twitch Bot."""
	def __init__(self, twitch_token: str):
		super().__init__(token=twitch_token, prefix="!")


async def run():
	"""Start the bot running, loading all credentials and the database."""
	db = await create_pool(**credentials['painezBotDB'])
	wg_id = credentials['Wargaming']['client_id']
	tbot = TwitchBot.from_client_credentials(**credentials['Twitch API'])
	bot = PBot(database=db, wg_id=wg_id, tbot=tbot)

	try:
		await bot.start(credentials['painezbot']['token'])
		await bot.twitch.start()
	except KeyboardInterrupt:
		for i in bot.cogs:
			await bot.unload_extension(i)
		await db.close()
		await bot.close()


new_event_loop().run_until_complete(run())
