"""Match Events used for the ticker"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional, TYPE_CHECKING, Type

from discord import Colour, Embed
from lxml import etree

from ext.toonbot_utils.flashscore import Player

if TYPE_CHECKING:
    from ext.toonbot_utils.flashscore import Team, Fixture


# This function Generates Event Objects from the etree.
def parse_events(fixture: Fixture, tree: etree) -> list[MatchEvent]:
    """Get a list of match events"""

    events = []

    for i in tree.xpath('.//div[contains(@class, "verticalSections")]/div'):
        # Detection of Teams
        team_detection = i.attrib["class"]
        if "Header" in team_detection:
            parts = [x.strip() for x in i.xpath(".//text()")]
            if "Penalties" in parts:
                try:
                    fixture.penalties_home = parts[1]
                    fixture.penalties_away = parts[3]
                except ValueError:
                    _, pen_string = parts
                    h, a = pen_string.split(" - ")
                    fixture.penalties_home = h
                    fixture.penalties_away = a
            continue
        elif "home" in team_detection:
            team = fixture.home
        elif "away" in team_detection:
            team = fixture.away
        elif "empty" in team_detection:
            continue  # No events in half signifier.
        else:
            logging.error(f"No team found for team_detection {team_detection}")
            continue

        node = i.xpath('./div[contains(@class, "incident")]')[0]  # event_node
        xpath = './/div[contains(@class, "incidentIcon")]//@title'
        title = "".join(node.xpath(xpath)).strip()
        description = title.replace("<br />", " ")

        xpath = './/div[contains(@class, "incidentIcon")]//svg//text()'
        icon_desc = "".join(node.xpath(xpath)).strip()

        xpath = './/div[contains(@class, "incidentIcon")]//svg/@class'
        match (icon := "".join(node.xpath(xpath)).strip()).lower():
            # Goal types
            case "footballGoal-ico" | "soccer":
                match icon_desc.lower():
                    case "goal" | "":
                        event = Goal()
                    case "penalty":
                        event = Penalty()
                    case _:
                        logging.error(
                            f"[GOAL] icon: <{icon}> unhandled"
                            f"icon_desc: <{icon_desc}> on {fixture.url}"
                        )
                        continue
            case "footballowngoal-ico" | "soccer footballowngoal-ico":
                event = OwnGoal()
            case "penaltymissed-ico":
                event = Penalty(missed=True)
            # Card Types
            case "yellowcard-ico" | "card-ico yellowcard-ico":
                event = Booking()
                event.note = icon_desc
            case "redyellowcard-ico":
                event = SecondYellow()
                if "card / Red" not in icon_desc:
                    event.note = icon_desc
            case "redcard-ico" | "card-ico redcard-ico":
                event = RedCard()
                if icon_desc != "Red Card":
                    event.note = icon_desc
            case "card-ico":
                event = Booking()
                if icon_desc != "Yellow Card":
                    event.note = icon_desc
            # Substitutions
            case "substitution-ico" | "substitution":
                event = Substitution()

                p = Player()
                xpath = './/div[contains(@class, "incidentSubOut")]/a/text()'
                p.name = "".join(node.xpath(xpath)).strip()

                xpath = './/div[contains(@class, "incidentSubOut")]/a/@href'
                p.url = "".join(node.xpath(xpath)).strip()

                event.player_off = p
            # VAR types
            case "var-ico" | "var":
                event = VAR()
                if not icon_desc:
                    icon_desc = "".join(node.xpath("./div//text()")).strip()
                if icon_desc:
                    event.note = icon_desc
            case "varlive-ico" | "var varlive-ico":
                event = VAR(in_progress=True)
                event.note = icon_desc
            case _:  # Backup checks.
                match icon_desc.strip().lower():
                    case "penalty" | "penalty kick":
                        event = Penalty()
                    case "penalty missed":
                        event = Penalty(missed=True)
                    case "own goal":
                        event = OwnGoal()
                    case "goal":
                        event = Goal()
                        if icon_desc and icon_desc.lower() != "goal":
                            logging.error(f"[GOAL] unh icon_desc: {icon_desc}")
                            continue
                    # Red card
                    case "red card":
                        event = RedCard()
                    # Second Yellow
                    case "yellow card / red card":
                        event = SecondYellow()
                    case "warning":
                        event = Booking()
                    # Substitution
                    case "substitution - in":
                        event = Substitution()
                        p = Player()

                        s = './/div[contains(@class, "incidentSubOut")]/a/'
                        p.name = "".join(node.xpath(s + "text()")).strip()
                        p.url = "".join(node.xpath(s + "@href")).strip()

                        event.player_off = p
                    case _:
                        logging.error(
                            f"Match Event (icon: {icon})\n"
                            f"icon_desc: {icon_desc}\n{fixture.url}"
                        )
                        continue

        event.team = team

        # Data not always present.
        xpath = './/a[contains(@class, "playerName")]//text()'
        if name := "".join(node.xpath(xpath)).strip():
            p = Player(fixture.bot)
            p.name = name
            xpath = './/a[contains(@class, "playerName")]//@href'
            p.url = "".join(node.xpath(xpath)).strip()
            event.player = p

        xpath = './/div[contains(@class, "assist")]//text()'
        if assist := "".join(node.xpath(xpath)):
            p = Player(fixture.bot)
            p.name = assist.strip("()")

            xpath = './/div[contains(@class, "assist")]//@href'
            p.url = "".join(node.xpath(xpath))
            event.assist = p

        if description:
            event.description = description

        xpath = './/div[contains(@class, "timeBox")]//text()'
        event.time = "".join(node.xpath(xpath)).strip()
        events.append(event)
    return events


class MatchEvent:
    """An object representing an event happening in a fixture"""

    __slots__ = ("note", "description", "player", "team", "time", "fixture")

    colour: Colour = None
    icon_url: str = None

    def __init__(self) -> None:
        self.note: Optional[str] = None
        self.description: Optional[str] = None
        self.fixture: Optional[Fixture] = None
        self.player: Optional[Player] = None
        self.team: Optional[Team] = None
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
        eembed = Embed(description=str(self), colour=self.colour)
        eembed.set_author(
            name=f"{self.__class__.__name__} ({self.team.name})",
            icon_url=self.icon_url,
        )

        if self.team is not None:
            eembed.set_thumbnail(url=self.team.logo_url)
        return eembed

    @property
    def embed_extended(self) -> Embed:
        """The Extended Embed for this match event"""
        embed = self.embed
        if self.fixture:
            for x in self.fixture.events:
                if x == self:
                    continue
                embed.description += f"\n{str(x)}"
        return embed


class Substitution(MatchEvent):
    """A substitution event for a fixture"""

    __slots__ = ["player_off"]

    Colour = Colour.greyple()

    def __init__(self) -> None:
        super().__init__()
        self.player_off: Optional[Player] = None

    def __str__(self) -> str:
        o = ["`🔄`"] if self.time is None else [f"`🔄 {self.time}`"]
        if self.team is not None:
            o.append(self.team.tag)
        if self.player is not None:
            o.append(f"🔺 {self.player.markdown}")
        if self.player_off is not None:
            o.append(f"🔻 {self.player_off.markdown}")
        return " ".join(o)


class Goal(MatchEvent):
    """A Generic Goal Event"""

    __slots__ = "assist"

    colour = Colour.green()

    def __init__(self) -> None:
        super().__init__()
        self.assist: Optional[Player] = None

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

    super().__init__()

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

    def __init__(self) -> None:
        super().__init__()

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

    super().__init__()

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

    def __init__(self) -> None:
        super().__init__()

    def __str__(self) -> str:

        if self.time is None:
            o = [f"`{self.emote}`"]
        else:
            [f"`{self.emote} {self.time}`"]

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
        self.assist: Optional[Player] = None
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
