"""Match Events used for the ticker"""
from __future__ import annotations

from enum import Enum
from typing import Optional, Type

from discord import Colour, Embed
import ext.toonbot_utils.flashscore as fs


class MatchEvent:
    """An object representing an event happening in a fixture"""

    __slots__ = ("note", "description", "player", "team", "time", "fixture")

    colour: Colour
    icon_url: str

    def __init__(self) -> None:
        self.note: Optional[str] = None
        self.description: Optional[str] = None
        self.fixture: Optional[fs.Fixture] = None
        self.player: Optional[fs.Player] = None
        self.team: Optional[fs.Team] = None
        self.time: Optional[str] = None

    def is_done(self) -> bool:
        """Check to see if more information is required"""
        if self.player is None:
            return False
        else:
            return True

    @property
    def embed(self) -> Embed:
        """The Embed for this match event"""
        embed = Embed(description=str(self), colour=self.colour)

        cn = self.__class__.__name__
        if self.team is not None:
            embed.set_thumbnail(url=self.team.logo_url)
            name = f"{cn} ({self.team.name})"
        else:
            name = cn

        embed.set_author(name=name, icon_url=self.icon_url)
        return embed

    @property
    def embed_extended(self) -> Embed:
        """The Extended Embed for this match event"""
        embed = self.embed

        if self.fixture:

            embed.description = ""

            for x in self.fixture.events:
                # We only want the other events, not ourself.
                if x == self:
                    continue

                embed.description += f"\n{str(x)}"
        return embed


class Substitution(MatchEvent):
    """A substitution event for a fixture"""

    Colour = Colour.greyple()

    def __init__(self) -> None:
        super().__init__()
        self.player_off: Optional[fs.Player] = None

    def __str__(self) -> str:
        o = ["`🔄`"] if self.time is None else [f"`🔄 {self.time}`"]
        if self.team is not None:
            o.append(self.team.tag)
        if self.player is not None:
            o.append(f"{fs.INBOUND_EMOJI} {self.player.markdown}")
        if self.player_off is not None:
            o.append(f"{fs.OUTBOUND_EMOJI} {self.player_off.markdown}")
        return " ".join(o)


class Goal(MatchEvent):
    """A Generic Goal Event"""

    colour = Colour.green()

    def __init__(self) -> None:
        super().__init__()
        self.assist: Optional[fs.Player] = None

    def __str__(self) -> str:
        o = [self.timestamp]
        if self.team is not None:
            o.append(self.team.tag)
        if self.player is not None:
            o.append(self.player.markdown)
        if self.assist is not None:
            o.append(f"(ass: {self.assist.markdown})")
        if self.note is not None:
            o.append(f"({self.note})")
        return " ".join(o)

    @property
    def emote(self) -> str:
        """An Emoji representing a Goal"""
        return "⚽"

    @property
    def timestamp(self) -> str:
        """String representing the emoji of the goal type and the time"""
        if self.time is None:
            return f"`{self.emote}`"
        else:
            return f"`{self.emote} {self.time}`"


class OwnGoal(Goal):
    """An own goal event"""

    colour = Colour.dark_green()

    @property
    def emote(self) -> str:
        """A string representing an own goal as an emoji"""
        return "⚽ OG"


class Penalty(Goal):
    """A Penalty Event"""

    __slots__ = ["missed"]

    colour = Colour.brand_green()

    def __init__(self, missed: bool = False) -> None:
        super().__init__()
        self.missed: bool = missed

    @property
    def emote(self) -> str:
        """An emote representing whether this Penalty was scored or not"""
        return "❌" if self.missed else "⚽P"

    @property
    def shootout(self) -> bool:
        """If it ends with a ', it was during regular time"""
        if self.time is None:
            return True
        return not self.time.endswith("'")


class RedCard(MatchEvent):
    """An object representing the event of a dismissal of a player"""

    colour = Colour.red()

    def __str__(self) -> str:

        if self.time is None:
            o = [f"`{self.emote}`"]
        else:
            o = [f"`{self.emote} {self.time}`"]

        if self.team is not None:
            o.append(self.team.tag)

        if self.player is not None:
            o.append(self.player.markdown)

        if self.note is not None:
            if "Red card" not in self.note:
                o.append(f"({self.note})")
        return " ".join(o)

    @property
    def emote(self) -> str:
        """Return an emoji representing a red card"""
        return "🟥"


class SecondYellow(RedCard):
    """An object representing the event of a dismissal of a player
    after a second yellow card"""

    colour = Colour.brand_red()

    def __str__(self) -> str:

        if self.time is None:
            o = [f"{self.emote}`"]
        else:
            o = [f"`{self.emote} {self.time}`"]

        if self.team is not None:
            o.append(self.team.tag)

        if self.player is not None:
            o.append(self.player.markdown)

        if self.note is not None:
            if "Yellow card / Red card" not in self.note:
                o.append(f"({self.note})")
        return " ".join(o)

    @property
    def emote(self) -> str:
        """Return an emoji representing a second yellow card"""
        return "🟨🟥"


class Booking(MatchEvent):
    """An object representing the event of a player being given
    a yellow card"""

    colour = Colour.yellow()

    def __str__(self) -> str:

        if self.time is None:
            o = [f"`{self.emote}`"]
        else:
            o = [f"`{self.emote} {self.time}`"]

        if self.team is not None:
            o.append(self.team.tag)

        if self.player is not None:
            o.append(self.player.markdown)

        if self.note:
            if self.note.lower().strip() != "yellow card":
                o.append(f"({self.note})")
        return " ".join(o)

    @property
    def emote(self) -> str:
        """Return an emoji representing a booking"""
        return "🟨"


class VAR(MatchEvent):
    """An Object Representing the event of a
    Video Assistant Referee Review Decision"""

    __slots__ = ["in_progress", "assist"]

    colour = Colour.og_blurple()

    def __init__(self, in_progress: bool = False) -> None:
        super().__init__()
        self.assist: Optional[fs.Player] = None
        self.in_progress: bool = in_progress

    def __str__(self) -> str:
        o = ["`📹 VAR`"] if self.time is None else [f"`📹 VAR {self.time}`"]
        if self.team is not None:
            o.append(self.team.tag)
        if self.player is not None:
            o.append(self.player.markdown)
        if self.note is not None:
            o.append(f"({self.note})")
        if self.in_progress:
            o.append("\n**DECISION IN PROGRESS**")
        return " ".join(o)


class EventType(Enum):
    """An Enum representing an EventType for ticker events"""

    def __init__(
        self,
        value: str,
        colour: Colour,
        db_fields: list[str],
        valid_events: Type[MatchEvent],
    ):
        self._value_ = value
        self.colour = colour
        self.db_fields = db_fields
        self.valid_events = valid_events

    # Goals
    GOAL = "Goal", Colour.dark_green(), ["goal"], Goal | VAR
    VAR_GOAL = "VAR Goal", Colour.og_blurple(), ["var"], VAR
    GOAL_OVERTURNED = "Goal Overturned", Colour.og_blurple(), ["var"], VAR

    # Cards
    RED_CARD = "Red Card", Colour.red(), ["var"], RedCard | VAR
    VAR_RED_CARD = "VAR Red Card", Colour.og_blurple(), ["var"], VAR
    RED_CARD_OVERTURNED = (
        "Red Card Overturned",
        Colour.og_blurple(),
        ["var"],
        VAR,
    )

    # State Changes
    DELAYED = "Match Delayed", Colour.orange(), ["delayed"], type(None)
    INTERRUPTED = (
        "Match Interrupted",
        Colour.dark_orange(),
        ["delayed"],
        type(None),
    )
    CANCELLED = "Match Cancelled", Colour.red(), ["delayed"], type(None)
    POSTPONED = "Match Postponed", Colour.red(), ["delayed"], type(None)
    ABANDONED = "Match Abandoned", Colour.red(), ["full_time"], type(None)
    RESUMED = "Match Resumed", Colour.light_gray(), ["kick_off"], type(None)

    # Period Changes
    KICK_OFF = "Kick Off", Colour.green(), ["kick_off"], type(None)
    HALF_TIME = "Half Time", 0x00FFFF, ["half_time"], type(None)
    SECOND_HALF_BEGIN = (
        "Second Half",
        Colour.light_gray(),
        ["second_half_begin"],
        type(None),
    )
    PERIOD_BEGIN = (
        "Period #PERIOD#",
        Colour.light_gray(),
        ["second_half_begin"],
        type(None),
    )
    PERIOD_END = (
        "Period #PERIOD# Ends",
        Colour.light_gray(),
        ["half_time"],
        type(None),
    )

    FULL_TIME = "Full Time", Colour.teal(), ["full_time"], type(None)
    FINAL_RESULT_ONLY = (
        "Final Result",
        Colour.teal(),
        ["final_result_only"],
        type(None),
    )
    SCORE_AFTER_EXTRA_TIME = (
        "Score After Extra Time",
        Colour.teal(),
        ["full_time"],
        type(None),
    )

    NORMAL_TIME_END = (
        "End of normal time",
        Colour.greyple(),
        ["extra_time"],
        type(None),
    )
    EXTRA_TIME_BEGIN = (
        "ET: First Half",
        Colour.lighter_grey(),
        ["extra_time"],
        type(None),
    )
    HALF_TIME_ET_BEGIN = (
        "ET: Half Time",
        Colour.light_grey(),
        ["half_time", "extra_time"],
        type(None),
    )
    HALF_TIME_ET_END = (
        "ET: Second Half",
        Colour.dark_grey(),
        ["second_half_begin", "extra_time"],
        type(None),
    )
    EXTRA_TIME_END = (
        "ET: End of Extra Time",
        Colour.darker_gray(),
        ["extra_time"],
        type(None),
    )

    PENALTIES_BEGIN = (
        "Penalties Begin",
        Colour.dark_gold(),
        ["penalties"],
        type(None),
    )
    PENALTY_RESULTS = (
        "Penalty Results",
        Colour.gold(),
        ["penalties"],
        type(None),
    )
