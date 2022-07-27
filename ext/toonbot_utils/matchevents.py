"""Match Events used for the ticker"""
from __future__ import annotations

from enum import Enum
from typing import Optional, List, TYPE_CHECKING, Type

from discord import Colour
from lxml import etree

from ext.toonbot_utils.gamestate import GameTime

if TYPE_CHECKING:
    from ext.toonbot_utils.flashscore import Team, Fixture, Player


# TODO: Create .embed attribute for events.


def parse_events(fixture: Fixture, tree: etree) -> list[MatchEvent]:
    """Get a list of match events"""
    from ext.toonbot_utils.flashscore import Player

    events = []

    for i in tree.xpath('.//div[contains(@class, "verticalSections")]/div'):
        team_detection = i.attrib['class']

        # Detection of Teams
        match team_detection:
            case team_detection if "Header" in team_detection:
                parts = [x.strip() for x in i.xpath('.//text()')]
                if "Penalties" in parts:
                    try:
                        _, fixture.penalties_home, _, fixture.penalties_away = parts
                    except ValueError:
                        _, pen_string = parts
                        fixture.penalties_home, fixture.penalties_away = pen_string.split(' - ')
                continue
            case team_detection if "home" in team_detection:
                team = fixture.home
            case team_detection if "away" in team_detection:
                team = fixture.away
            case team_detection if "empty" in team_detection:
                continue  # No events in half signifier.
            case _:
                raise ValueError(f"No team found for team_detection {team_detection}")

        node = i.xpath('./div[contains(@class, "incident")]')[0]  # event_node
        icon = ''.join(node.xpath('.//div[contains(@class, "incidentIcon")]//svg/@class')).strip()
        title = ''.join(node.xpath('.//div[contains(@class, "incidentIcon")]//@title')).strip()
        description = title.replace('<br />', ' ')
        icon_desc = ''.join(node.xpath('.//div[contains(@class, "incidentIcon")]//svg//text()')).strip()

        match (icon, icon_desc):
            # Missed Penalties
            case ("penaltyMissed-ico", _) | (_, "Penalty missed"):
                event = Penalty(missed=True)
            case (_, "Penalty") | (_, "Penalty Kick"):
                event = Penalty()
            case (_, "Own goal") | ("footballOwnGoal-ico", _):
                event = OwnGoal()
            case (_, "Goal") | ("footballGoal-ico", _):
                event = Goal()
                if icon_desc and icon_desc.lower() != "goal":
                    raise ValueError(f"unhandled icon_desc for goal {icon_desc}")
            # Red card
            case (_, "Red Card") | ("card-ico", _):
                event = RedCard()
                if icon_desc != "Red Card":
                    event.note = icon_desc
            # Second Yellow
            case (_, "Yellow card / Red card") | ("redYellowCard-ico", _):
                event = SecondYellow()
                if "card / Red" not in icon_desc:
                    event.note = icon_desc
            # Single Yellow
            case ("yellowCard-ico", _):
                event = Booking()
                event.note = icon_desc
            case (_, "Substitution - In") | ("substitution-ico", _):
                event = Substitution()
                p = Player(fixture.bot)
                p.name = "".join(node.xpath('.//div[contains(@class, "incidentSubOut")]/a/text()')).strip()
                p.url = "".join(node.xpath('.//div[contains(@class, "incidentSubOut")]/a/@href')).strip()
                event.player_off = p
            case ("var-ico", _):
                event = VAR()
                icon_desc = icon_desc if icon_desc else ''.join(node.xpath('./div//text()')).strip()
                if icon_desc:
                    event.note = icon_desc
            case ("varLive-ico", _):
                event = VAR(in_progress=True)
                event.note = icon_desc
            case _:
                raise ValueError(f"Unhandled Match Event (icon: {icon}, icon_desc: {icon_desc}")

        event.team = team

        # Data not always present.
        name = ''.join(node.xpath('.//a[contains(@class, "playerName")]//text()')).strip()
        if name:
            p = Player(fixture.bot)
            p.name = name
            p.url = ''.join(node.xpath('.//a[contains(@class, "playerName")]//@href')).strip()
            event.player = p

        assist = ''.join(node.xpath('.//div[contains(@class, "assist")]//text()'))
        if assist:
            p = Player(fixture.bot)
            p.name = assist.strip('()')
            p.url = ''.join(node.xpath('.//div[contains(@class, "assist")]//@href'))
            event.assist = p

        if description:
            event.description = description

        event.time = GameTime(''.join(node.xpath('.//div[contains(@class, "timeBox")]//text()')).strip())
        events.append(event)
    return events


class MatchEvent:
    """An object representing an event happening in a football fixture from Flashscore"""
    __slots__ = ("note", "description", "player", "team", "time")

    def __init__(self) -> None:
        self.note: Optional[str] = None
        self.description: Optional[str] = None
        self.player: Optional[Player] = None
        self.team: Optional[Team] = None
        self.time: Optional[GameTime] = None


class Substitution(MatchEvent):
    """A substitution event for a fixture"""
    __slots__ = ['player_off']

    def __init__(self) -> None:
        super().__init__()
        self.player_off: Optional[Player] = None

    def __str__(self) -> str:
        o = ['`🔄`:'] if self.time is None else [f"`🔄 {self.time.value}`:"]
        if self.player_off is not None:
            o.append(f"🔻 {self.player_off.markdown}")
        if self.player_on is not None:
            o.append(f"🔺 {self.player_on.markdown}")
        if self.team is not None:
            o.append(f"({self.team.tag})")
        return ' '.join(o)

    @property
    def player_on(self) -> Optional[Player]:
        """player_on is an alias to player."""
        return self.player


class Goal(MatchEvent):
    """A Generic Goal Event"""
    __slots__ = "assist"

    def __init__(self) -> None:
        super().__init__()
        self.assist: Optional[Player] = None

    def __str__(self) -> str:
        o = [self.timestamp]
        if self.player is not None:
            o.append(self.player.markdown)
        if self.assist is not None:
            o.append(f"(ass: {self.assist.markdown})")
        if self.note is not None:
            o.append(f"({self.note})")
        if self.team is not None:
            o.append(f"- {self.team.tag}")
        return ' '.join(o)

    @property
    def emote(self) -> str:
        """An Emoji representing a Goal"""
        return '⚽'

    @property
    def timestamp(self) -> str:
        """String representing the emoji of the goal type and the in game time"""
        return f"`{self.emote}`:" if self.time is None else f"`{self.emote} {self.time.value}`:"


class OwnGoal(Goal):
    """An own goal event"""

    def __init__(self) -> None:
        super().__init__()

    @property
    def emote(self) -> str:
        """A string representing an own goal as an emoji"""
        return "⚽ OG"


class Penalty(Goal):
    """A Penalty Event"""
    __slots__ = ['missed']

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
        return not self.time.value.endswith("'")


class RedCard(MatchEvent):
    """An object representing the event of a dismissal of a player"""

    def __init__(self) -> None:
        super().__init__()

    def __str__(self) -> str:
        o = [f"`{self.emote}`:"] if self.time is None else [f"`{self.emote} {self.time.value}`:"]
        if self.player is not None:
            o.append(self.player.markdown)
        if self.note is not None and 'Red card' not in self.note:
            o.append(f"({self.note})")
        if self.team is not None:
            o.append(f"- {self.team.tag}")
        return ' '.join(o)

    @property
    def emote(self) -> str:
        """Return an emoji representing a red card"""
        return '🟥'


class SecondYellow(RedCard):
    """An object representing the event of a dismissal of a player after a second yellow card"""

    def __init__(self) -> None:
        super().__init__()

    def __str__(self) -> str:
        o = [f"{self.emote}`:"] if self.time is None else [f"`{self.emote} {self.time.value}`:"]
        if self.player is not None:
            o.append(self.player.markdown)
        if self.note is not None and 'Yellow card / Red card' not in self.note:
            o.append(f"({self.note})")
        if self.team is not None:
            o.append(f"- {self.team.tag}")
        return ' '.join(o)

    @property
    def emote(self) -> str:
        """Return an emoji representing a second yellow card"""
        return '🟨🟥'


class Booking(MatchEvent):
    """An object representing the event of a player being given a yellow card"""

    def __init__(self) -> None:
        super().__init__()

    def __str__(self) -> str:
        o = [f"`{self.emote}`:"] if self.time is None else [f"`{self.emote} {self.time.value}`:"]
        if self.player is not None:
            o.append(self.player.markdown)
        if self.note and self.note.lower().strip() != 'yellow card':
            o.append(f"({self.note})")
        if self.team is not None:
            o.append(f"- {self.team.tag}")
        return ' '.join(o)

    @property
    def emote(self) -> str:
        """Return an emoji representing a booking"""
        return '🟨'


class VAR(MatchEvent):
    """An Object Representing the event of a Video Assistant Referee Review Decision"""
    __slots__ = ["in_progress", "assist"]

    def __init__(self, in_progress: bool = False) -> None:
        super().__init__()
        self.assist: Optional[Player] = None
        self.in_progress: bool = in_progress

    def __str__(self) -> str:
        o = ["`📹 VAR`:"] if self.time is None else [f"`📹 VAR {self.time.value}`:"]
        if self.player is not None:
            o.append(self.player.markdown)
        if self.note is not None:
            o.append(f"({self.note})")
        if self.team is not None:
            o.append(f"- {self.team.tag}")
        if self.in_progress:
            o.append("\n**DECISION IN PROGRESS**")
        return ' '.join(o)


class EventType(Enum):
    """An Enum representing an EventType for ticker events"""

    def __init__(self, value: str, colour: Colour, db_fields: List, valid_events: Type[MatchEvent]):
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
    RED_CARD_OVERTURNED = "Red Card Overturned", Colour.og_blurple(), ["var"], VAR

    # State Changes
    DELAYED = "Match Delayed", Colour.orange(), ["delayed"], type(None)
    INTERRUPTED = "Match Interrupted", Colour.dark_orange(), ["delayed"], type(None)
    CANCELLED = "Match Cancelled", Colour.red(), ["delayed"], type(None)
    POSTPONED = "Match Postponed", Colour.red(), ["delayed"], type(None)
    ABANDONED = "Match Abandoned", Colour.red(), ["full_time"], type(None)
    RESUMED = "Match Resumed", Colour.light_gray(), ["kick_off"], type(None)

    # Period Changes
    KICK_OFF = "Kick Off", Colour.green(), ["kick_off"], type(None)
    HALF_TIME = "Half Time", 0x00ffff, ["half_time"], type(None)
    SECOND_HALF_BEGIN = "Second Half", Colour.light_gray(), ["second_half_begin"], type(None)
    PERIOD_BEGIN = "Period #PERIOD#", Colour.light_gray(), ["second_half_begin"], type(None)
    PERIOD_END = "Period #PERIOD# Ends", Colour.light_gray(), ["half_time"], type(None)

    FULL_TIME = "Full Time", Colour.teal(), ["full_time"], type(None)
    FINAL_RESULT_ONLY = "Final Result", Colour.teal(), ["final_result_only"], type(None)
    SCORE_AFTER_EXTRA_TIME = "Score After Extra Time", Colour.teal(), ["full_time"], type(None)

    NORMAL_TIME_END = "End of normal time", Colour.greyple(), ["extra_time"], type(None)
    EXTRA_TIME_BEGIN = "ET: First Half", Colour.lighter_grey(), ["extra_time"], type(None)
    HALF_TIME_ET_BEGIN = "ET: Half Time", Colour.light_grey(), ["half_time", "extra_time"], type(None)
    HALF_TIME_ET_END = "ET: Second Half", Colour.dark_grey(), ["second_half_begin", "extra_time"], type(None)
    EXTRA_TIME_END = "ET: End of Extra Time", Colour.darker_gray(), ["extra_time"], type(None)

    PENALTIES_BEGIN = "Penalties Begin", Colour.dark_gold(), ["penalties"], type(None)
    PENALTY_RESULTS = "Penalty Results", Colour.gold(), ["penalties"], type(None)
