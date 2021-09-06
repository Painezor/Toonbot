"""Utilities for working with future events"""
import datetime


# Time Formats:


class Timestamp:
	"""A Utility class for quick timezone conversion"""

	def __init__(self, time: datetime.datetime = datetime.datetime.now()):
		self.time = str(time.timestamp()).split('.')[0]

	def __str__(self):
		return f"<t:{self.time}:t>"  # <t:1628343360:t>  14:36

	@property
	def long(self):
		"""Return string in form '7 August 2021 14:36 (a few seconds ago)'"""
		return f"<t:{self.time}:f> (<t:{self.time}:R>)"

	@property
	def date_relative(self):
		"""Return string in form '07/08/2021 (a few seconds ago)'"""
		return f"<t:{self.time}:d> (<t:{self.time}:R>)"

	@property
	def time_relative(self):
		"""Return string in form '14:36 (a few seconds ago)'"""
		return f"<t:{self.time}:t> (<t:{self.time}:R>)"

	@property
	def countdown(self):
		"""Return string in form 'a few seconds ago'"""
		return f"<t:{self.time}:R>"

	@property
	def date(self):
		"""Return string in form '07/08/2021'"""
		return f"<t:{self.time}:d>"  # <t:1628343360:d>  07/08/2021

	def date_long(self):
		"""Return string in form '7 August 2021'"""
		return f"<t:{self.time}:D>"

	@property
	def datetime(self):
		"""Return string in form '7 August 2021 14:36'"""
		return f"<t:{self.time}:f>"

	@property
	def day_time(self):
		"""Return string in form 'Saturday, 7 August 2021 14:36'"""
		return f"<t:{self.time}:F>"

	@property
	def time_seconds(self):
		"""Return string in form '14:36:00'"""
		return f"<t:{self.time}:T>"


async def parse_time(time):
	"""Parse a 1d2dh3m4s formatted time string."""
	delta = datetime.timedelta()
	if "d" in time:
		d, time = time.split("d")
		delta += datetime.timedelta(days=int(d))
	if "h" in time:
		h, time = time.split("h")
		delta += datetime.timedelta(hours=int(h))
	if "m" in time:
		m, time = time.split("m")
		delta += datetime.timedelta(minutes=int(m))
	if "s" in time:
		s = time.split("s")[0]
		delta += datetime.timedelta(seconds=int(s))
	return delta
