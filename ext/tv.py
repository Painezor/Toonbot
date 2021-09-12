"""Fetch latest information on televised matches from livesoccertv.com"""
import datetime
import json
from importlib import reload

import discord
from discord.ext import commands
from lxml import html

from ext.utils import embed_utils, view_utils, timed_events


# TODO:  Convert to use new timestamps.
# TODO: Select / Button Pass.

class Tv(commands.Cog):
	"""Search for live TV matches"""

	def __init__(self, bot):
		self.bot = bot
		self.emoji = "📺"
		with open('tv.json') as f:
			bot.tv = json.load(f)
		reload(view_utils)
	
	@commands.command()
	async def tv(self, ctx, *, team: commands.clean_content = None):
		"""Lookup next televised games for a team"""
		em = discord.Embed()
		em.colour = 0x034f76
		em.set_author(name="LiveSoccerTV.com")
		em.description = ""

		# Selection View if team is passed
		if team:
			matches = [i for i in self.bot.tv if str(team).lower() in i.lower()]

			if not matches:
				return await self.bot.reply(ctx, text=f"Could not find a matching team/league for {team}.")

			_ = [('📺', i, self.bot.tv[i]) for i in matches]

			view = view_utils.ObjectSelectView(owner=ctx.author, objects=_, timeout=30)
			view.message = await self.bot.reply(ctx, '⏬ Multiple results found, choose from the dropdown.', view=view)
			await view.wait()

			if view.value is None:
				return None

			team = matches[view.value]
			em.url = self.bot.tv[team]
			em.title = f"Televised Fixtures for {team}"
		else:
			em.url = "http://www.livesoccertv.com/schedules/"
			em.title = f"Today's Televised Matches"

		rows = []
		async with self.bot.session.get(em.url) as resp:
			if resp.status != 200:
				return await self.bot.reply(ctx, text=f"🚫 <{em.url}> returned a HTTP {resp.status} error.")
			tree = html.fromstring(await resp.text())

			match_column = 3 if not team else 5

			for i in tree.xpath(".//table[@class='schedules'][1]//tr"):
				# Discard finished games.
				complete = "".join(i.xpath('.//td[@class="livecell"]//span/@class')).strip()
				if complete in ["narrow ft", "narrow repeat"]:
					continue

				match = "".join(i.xpath(f'.//td[{match_column}]//text()')).strip()
				if not match:
					continue

				try:
					link = i.xpath(f'.//td[{match_column + 1}]//a/@href')[-1]
					link = f"http://www.livesoccertv.com/{link}"
				except IndexError:
					link = ""

				try:
					timestamp = i.xpath('.//@dv')[0]
					timestamp = int(timestamp)
					_ = datetime.datetime.fromtimestamp(timestamp / 1000)
					ts = timed_events.Timestamp(_).datetime
				except (ValueError, IndexError):
					date = "".join(i.xpath('.//td[@class="datecell"]//span/text()')).strip()
					time = "".join(i.xpath('.//td[@class="timecell"]//span/text()')).strip()
					if time not in ["Postp.", "TBA"]:
						print(f"TV.py - invalid timestamp.\nDate [{date}] Time [{time}]")
					ts = time

				rows.append(f'{ts}: [{match}]({link})')

		if not rows:
			rows = [f"No televised matches found, check online at {em.url}"]

		embeds = embed_utils.rows_to_embeds(em, rows)

		view = view_utils.Paginator(ctx.author, embeds)
		view.message = await self.bot.reply(ctx, "Fetching televised matches...", view=view)
		await view.update()


def setup(bot):
	"""Load TV Lookup Module into the bot."""
	bot.add_cog(Tv(bot))
