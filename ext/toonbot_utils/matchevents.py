"""Match Events used for the ticker"""
from __future__ import annotations

import enum
import typing
import discord
import ext.toonbot_utils.flashscore as fs


class MatchEvent:
    """An object representing an event happening in a fixture"""

    __slots__ = ("note", "description", "player", "team", "time", "fixture")

    colour: discord.Colour
    icon_url: str

    def __init__(self) -> None:
        self.note: typing.Optional[str] = None
        self.description: typing.Optional[str] = None
        self.fixture: typing.Optional[fs.Fixture] = None
        self.player: typing.Optional[fs.Player] = None
        self.team: typing.Optional[fs.Team] = None
        self.time: typing.Optional[str] = None

    def is_done(self) -> bool:
        """Check to see if more information is required"""
        if self.player is None:
            return False
        else:
            return True

    @property
    def embed(self) -> discord.Embed:
        """The Embed for this match event"""
        embed = discord.Embed(description=str(self), colour=self.colour)

        cname = self.__class__.__name__
        if self.team is not None:
            embed.set_thumbnail(url=self.team.logo_url)
            name = f"{cname} ({self.team.name})"
        else:
            name = cname

        embed.set_author(name=name, icon_url=self.icon_url)
        return embed

    @property
    def embed_extended(self) -> discord.Embed:
        """The Extended Embed for this match event"""
        embed = self.embed

        if self.fixture:

            embed.description = ""

            for i in self.fixture.events:
                # We only want the other events, not ourself.
                if i == self:
                    continue

                embed.description += f"\n{str(i)}"
        return embed


class Substitution(MatchEvent):
    """A substitution event for a fixture"""

    colour = discord.Colour.greyple()

    def __init__(self) -> None:
        super().__init__()
        self.player_off: typing.Optional[fs.Player] = None

    def __str__(self) -> str:
        output = ["`🔄`"] if self.time is None else [f"`🔄 {self.time}`"]
        if self.team is not None:
            output.append(self.team.tag)
        if self.player is not None:
            output.append(f"{fs.INBOUND_EMOJI} {self.player.markdown}")
        if self.player_off is not None:
            output.append(f"{fs.OUTBOUND_EMOJI} {self.player_off.markdown}")
        return " ".join(output)


class Goal(MatchEvent):
    """A Generic Goal Event"""

    colour = discord.Colour.green()

    def __init__(self) -> None:
        super().__init__()
        self.assist: typing.Optional[fs.Player] = None

    def __str__(self) -> str:
        output = [self.timestamp]
        if self.team is not None:
            output.append(self.team.tag)
        if self.player is not None:
            output.append(self.player.markdown)
        if self.assist is not None:
            output.append(f"(ass: {self.assist.markdown})")
        if self.note is not None:
            output.append(f"({self.note})")
        return " ".join(output)

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

    colour = discord.Colour.dark_green()

    @property
    def emote(self) -> str:
        """A string representing an own goal as an emoji"""
        return "⚽ OG"


class Penalty(Goal):
    """A Penalty Event"""

    __slots__ = ["missed"]

    colour = discord.Colour.brand_green()

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

    colour = discord.Colour.red()

    def __str__(self) -> str:

        if self.time is None:
            output = [f"`{self.emote}`"]
        else:
            output = [f"`{self.emote} {self.time}`"]

        if self.team is not None:
            output.append(self.team.tag)

        if self.player is not None:
            output.append(self.player.markdown)

        if self.note is not None:
            if "Red card" not in self.note:
                output.append(f"({self.note})")
        return " ".join(output)

    @property
    def emote(self) -> str:
        """Return an emoji representing a red card"""
        return "🟥"


class SecondYellow(RedCard):
    """An object representing the event of a dismissal of a player
    after a second yellow card"""

    colour = discord.Colour.brand_red()

    def __str__(self) -> str:

        if self.time is None:
            output = [f"{self.emote}`"]
        else:
            output = [f"`{self.emote} {self.time}`"]

        if self.team is not None:
            output.append(self.team.tag)

        if self.player is not None:
            output.append(self.player.markdown)

        if self.note is not None:
            if "Yellow card / Red card" not in self.note:
                output.append(f"({self.note})")
        return " ".join(output)

    @property
    def emote(self) -> str:
        """Return an emoji representing a second yellow card"""
        return "🟨🟥"


class Booking(MatchEvent):
    """An object representing the event of a player being given
    a yellow card"""

    colour = discord.Colour.yellow()

    def __str__(self) -> str:

        if self.time is None:
            output = [f"`{self.emote}`"]
        else:
            output = [f"`{self.emote} {self.time}`"]

        if self.team is not None:
            output.append(self.team.tag)

        if self.player is not None:
            output.append(self.player.markdown)

        if self.note:
            if self.note.casefold().strip() != "yellow card":
                output.append(f"({self.note})")
        return " ".join(output)

    @property
    def emote(self) -> str:
        """Return an emoji representing a booking"""
        return "🟨"


class VAR(MatchEvent):
    """An Object Representing the event of a
    Video Assistant Referee Review Decision"""

    __slots__ = ["in_progress", "assist"]

    colour = discord.Colour.og_blurple()

    def __init__(self, in_progress: bool = False) -> None:
        super().__init__()
        self.assist: typing.Optional[fs.Player] = None
        self.in_progress: bool = in_progress

    def __str__(self) -> str:
        out = ["`📹 VAR`"] if self.time is None else [f"`📹 VAR {self.time}`"]
        if self.team is not None:
            out.append(self.team.tag)
        if self.player is not None:
            out.append(self.player.markdown)
        if self.note is not None:
            out.append(f"({self.note})")
        if self.in_progress:
            out.append("\n**DECISION IN PROGRESS**")
        return " ".join(out)


class EventType(enum.Enum):
    """An Enum representing an EventType for ticker events"""

    def __init__(
        self,
        value: str,
        colour: discord.Colour,
        valid_events: typing.Type[MatchEvent],
    ):
        self._value_ = value
        self.colour = colour
        self.valid_events = valid_events

    # Goals
    GOAL = "Goal", discord.Colour.dark_green(), Goal | VAR
    VAR_GOAL = "VAR Goal", discord.Colour.og_blurple(), VAR
    GOAL_OVERTURNED = "Goal Overturned", discord.Colour.og_blurple(), VAR

    # Cards
    RED_CARD = "Red Card", discord.Colour.red(), RedCard | VAR
    VAR_RED_CARD = "VAR Red Card", discord.Colour.og_blurple(), VAR
    RED_CARD_OVERTURNED = (
        "Red Card Overturned",
        discord.Colour.og_blurple(),
        VAR,
    )

    # State Changes
    DELAYED = "Match Delayed", discord.Colour.orange(), None
    INTERRUPTED = "Match Interrupted", discord.Colour.dark_orange(), None
    CANCELLED = "Match Cancelled", discord.Colour.red(), None
    POSTPONED = "Match Postponed", discord.Colour.red(), None
    ABANDONED = "Match Abandoned", discord.Colour.red(), None
    RESUMED = "Match Resumed", discord.Colour.light_gray(), None

    # Period Changes
    KICK_OFF = "Kick Off", discord.Colour.green(), None
    HALF_TIME = "Half Time", 0x00FFFF, None
    SECOND_HALF_BEGIN = "Second Half", discord.Colour.light_gray(), None
    PERIOD_BEGIN = "Period #PERIOD#", discord.Colour.light_gray(), None
    PERIOD_END = "Period #PERIOD# Ends", discord.Colour.light_gray(), None

    FULL_TIME = "Full Time", discord.Colour.teal(), None
    FINAL_RESULT_ONLY = "Final Result", discord.Colour.teal(), None
    SCORE_AFTER_EXTRA_TIME = (
        "Score After Extra Time",
        discord.Colour.teal(),
        None,
    )
    NORMAL_TIME_END = "End of normal time", discord.Colour.greyple(), None
    EXTRA_TIME_BEGIN = "ET: First Half", discord.Colour.lighter_grey(), None
    HALF_TIME_ET_BEGIN = "ET: Half Time", discord.Colour.light_grey(), None
    HALF_TIME_ET_END = "ET: Second Half", discord.Colour.dark_grey(), None
    EXTRA_TIME_END = (
        "ET: End of Extra Time",
        discord.Colour.darker_gray(),
        None,
    )
    PENALTIES_BEGIN = "Penalties Begin", discord.Colour.dark_gold(), None
    PENALTY_RESULTS = "Penalty Results", discord.Colour.gold(), None
