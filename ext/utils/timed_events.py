"""Utilities for working with future events"""
import datetime as dt


# Time Formats:


class Timestamp:
    """A Utility class for quick timezone conversion"""

    def __init__(self, time: dt.datetime = None):
        if time is None:
            time = dt.datetime.now()
        self.time = str(time.timestamp()).split('.')[0]

    def __str__(self) -> str:
        return f"<t:{self.time}:t>"  # <t:1628343360:t>  14:36

    @property
    def long(self) -> str:
        """Return string in form '7 August 2021 14:36 (a few seconds ago)'"""
        return f"<t:{self.time}:f> (<t:{self.time}:R>)"

    @property
    def relative(self) -> str:
        """Return string in form (a few seconds ago)'"""
        return f"<t:{self.time}:R>"

    @property
    def date_relative(self) -> str:
        """Return string in form '07/08/2021 (a few seconds ago)'"""
        return f"<t:{self.time}:d> (<t:{self.time}:R>)"

    @property
    def time_hour(self) -> str:
        """Return string in form '14:36'"""
        return f"<t:{self.time}:t>"

    @property
    def time_seconds(self) -> str:
        """Return string in form '14:36:00'"""
        return f"<t:{self.time}:T>"

    @property
    def time_relative(self) -> str:
        """Return string in form '14:36 (a few seconds ago)'"""
        return f"<t:{self.time}:t> (<t:{self.time}:R>)"

    @property
    def countdown(self) -> str:
        """Return string in form 'a few seconds ago'"""
        return f"<t:{self.time}:R>"

    @property
    def date(self) -> str:
        """Return string in form '07/08/2021'"""
        return f"<t:{self.time}:d>"  # <t:1628343360:d>  07/08/2021

    @property
    def date_long(self) -> str:
        """Return string in form '7 August 2021'"""
        return f"<t:{self.time}:D>"

    @property
    def datetime(self) -> str:
        """Return string in form '7 August 2021 14:36'"""
        return f"<t:{self.time}:f>"

    @property
    def day_time(self) -> str:
        """Return string in form 'Saturday, 7 August 2021 14:36'"""
        return f"<t:{self.time}:F>"
