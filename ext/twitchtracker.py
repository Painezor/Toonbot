"""Track when users begin streaming"""
from typing import Union, TYPE_CHECKING

from discord import Member, ActivityType

if TYPE_CHECKING:
	from core import Bot
	from painezBot import PBot

from discord.ext.commands import Cog


# TODO: Twitch Tracker
class TwitchTracker(Cog):
	"""Track when users go live to twitch."""

	def __init__(self, bot: Union['Bot', 'PBot']):
		self.bot: Bot | PBot = bot

	@Cog.listener()
	async def on_presence_update(self, _: Member, after: Member):
		"""When the user updates their presence, we check if they started streaming
		We then check if they are in the channel's list of tracked users."""
		if after.guild.id != 250252535699341312:
			return

		if after.activity is None:
			return

		match after.activity.type:
			case ActivityType.streaming:
				print("Status changed to streaming, displaying dict\n====\n", after.activity.__dict__)
		return


# self.now_live_cache: dict = {}
#
#
# async def on_presence_update(self, before: Member, after: Member) -> None:
# 	"""Apply hoisted role to streamers when they go live."""
# 	# Check if this guild is tracking streaming status changes, grab row.:
# 	try:
# 		row = self.now_live_cache[before.guild.id]
# 	except KeyError:
# 		return
#
# 	# Check if member has either started, or stopped streaming.
# 	if not [before.activity, after.activity].count(ActivityType.streaming) == 1:
# 		return
#
# 	# Only output notifications for those users who are being intentionally tracked on the server.
# 	base_role = row["base_role"]
# 	if base_role not in [i.id for i in after.roles]:
# 		return
#
# 	now_live_role = row["now_live_role"]
#
# 	# If User is no longer live, de-hoist them.
# 	if before.activity == ActivityType.streaming:
# 		return await after.remove_roles(now_live_role)
#
# 	# Else If user is GOING live.
# 	await after.add_roles(now_live_role)
# 	ch = self.bot.get_channel(row['announcement_channel'])
#
# 	# Only output if channel exists.
# 	if ch is None:
# 		return
#
# 	activity = after.activity
#
# 	# Build embeds.
# 	e: Embed = Embed()
# 	if activity.platform.lower() == "twitch":
# 		name = f"Twitch: {activity.twitch_name}"
# 		e.colour = 0x6441A4
# 	else:
# 		e.colour = Colour.red() if activity.platform.lower() == "youtube" else Colour.og_blurple()
# 		name = f"{activity.platform}: {after.name}"
# 	e.set_author(name=name, url=activity.url)
# 	e.title = activity.game
#
# 	e.description = f"**[{after.mention} just went live]({activity.url})**\n\n{activity.name}"
# 	e.timestamp = datetime.datetime.now(datetime.timezone.utc)
# 	e.set_thumbnail(url=after.display_avatar.url)
#
# 	await ch.send(embed=e)

async def setup(bot: Union['Bot', 'PBot']):
	"""Add the cog to the bot"""
	await bot.add_cog(TwitchTracker(bot))
