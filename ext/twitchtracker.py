from typing import Union, TYPE_CHECKING

import discord
from discord import Member

if TYPE_CHECKING:
	from core import Bot
	from painezBot import PBot

from discord.ext.commands import Cog


class TwitchTracker(Cog):
	"""Track when users go live to twitch."""

	def __init__(self, bot: Union['Bot', 'PBot']):
		self.bot: Bot | PBot = bot

	@Cog.listener()
	async def on_presence_update(self, before: Member, after: Member):
		"""When the user updates their presence, we check against the DB to find if they have began streaming"""
		if not after.activity == discord.Streaming:
			return

		if after.guild.id != 250252535699341312:
			return

		print("MEMBER BEGAN STREAMING", after)


async def setup(bot: Union['Bot', 'PBot']):
	"""Add the cog to the bot"""
	await bot.add_cog(TwitchTracker(bot))
