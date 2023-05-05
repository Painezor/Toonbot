"""Match Events used for the ticker"""
from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, Any, Type

from lxml import html

from .constants import (
    FLASHSCORE,
    GOAL_EMOJI,
    INBOUND_EMOJI,
    OUTBOUND_EMOJI,
    RED_CARD_EMOJI,
    YELLOW_CARD_EMOJI,
)
from .players import FSPlayer

if TYPE_CHECKING:
    from .abc import BaseFixture, BaseTeam


logger = logging.getLogger("matchevents")


def parse_header(i: html.HtmlElement, fixture: BaseFixture) -> None:
    """Store Penalties"""
    text = [x.strip() for x in i.xpath(".//text()")]
    if "Penalties" in text:
        try:
            fixture.home.pens = int(text[1])
            fixture.away.pens = int(text[3])
            logger.info("Parsed a 2 part penalties OK!!")
        except IndexError:
            # If Penalties are still in progress, it's actually
            # in format ['Penalties', '1 - 2']
            _, pen_string = text
            home, away = pen_string.split(" - ")
            fixture.home.pens = int(home)
            fixture.away.pens = int(away)


def parse_events(fixture: BaseFixture, tree: Any) -> list[MatchIncident]:
    """Get a list of match events"""
    events: list[MatchIncident] = []
    for i in tree.xpath('.//div[contains(@class, "verticalSections")]/div'):
        # Detection of Teams
        team_detection = i.attrib["class"]
        if "Header" in team_detection:
            parse_header(i, fixture)
            continue

        try:
            # event node -- if we can't find one, we can't parse one.
            node = i.xpath('./div[contains(@class, "incident")]')[0]
        except IndexError:
            continue

        svg_t = "".join(node.xpath(".//svg//text()")).strip()
        svg_cl = "".join(node.xpath(".//svg/@class")).strip()
        sub_i = "".join(node.xpath(".//div[@class='smv__subIncident']/text()"))

        logger.info(
            "svg_text: %s, svg_class: %s, sub_i: %s", svg_t, svg_cl, sub_i
        )

        # Try to figure out what kind of event this is.
        if svg_cl == "soccer":
            # This is a goal.

            if sub_i == "(Penalty)":
                event = Penalty(fixture)

            elif sub_i:
                logger.info("Unhandled goal sub_incident %s", sub_i)
                event = Goal(fixture)

            else:
                event = Goal(fixture)

        elif "footballOwnGoal-ico" in svg_cl:
            event = OwnGoal(fixture)

        elif "Penalty missed" in sub_i:
            event = Penalty(fixture, missed=True)

        # cards
        elif (
            "Yellow card / Red card" in svg_t
            or "redyellowcard-ico" in svg_cl.casefold()
        ):
            event = SecondYellow(fixture)

        elif "redCard-ico" in svg_cl:
            event = RedCard(fixture)

        elif "yellowCard-ico" in svg_cl:
            event = Booking(fixture)

        elif "card-ico" in svg_cl:
            event = Booking(fixture)
            logger.info("Fallback reached, card-ico")

        # VAR
        elif "var" in svg_cl:
            event = VAR(fixture)
            if svg_cl != "var":
                logger.info("var has svg_clas %s", svg_cl)

        # Subs
        elif "substitution" in svg_cl:
            event = Substitution(fixture)
            event.set_player_off(node)

        else:
            logger.info("parsing match events on %s", fixture.url)
            logger.error("Match Event Not Handled correctly.")
            logger.info("text: %s, class: %s", svg_t, svg_cl)
            if sub_i:
                logger.info("sub_incident: %s", sub_i)

            event = MatchIncident(fixture)

        # Event Player.
        event.set_player(node)

        # Assist of a goal.
        if isinstance(event, Goal):
            event.set_assist(node)

        if "home" in team_detection:
            event.team = fixture.home.team
        elif "away" in team_detection:
            event.team = fixture.away.team

        xpath = './/div[contains(@class, "timeBox")]//text()'
        time = "".join(node.xpath(xpath)).strip()
        event.time = time
        event.note = svg_t

        # Description of the event.
        xpath = './/div[contains(@class, "incidentIcon")]//@title'
        title = "".join(node.xpath(xpath)).strip().replace("<br />", " ")
        event.description = title

        events.append(event)
    return events


class MatchIncident:
    """An object representing an event happening in a fixture"""

    fixture: BaseFixture

    assist: FSPlayer | None = None
    description: str | None = None
    icon_url: str | None = None
    player: FSPlayer | None = None
    team: BaseTeam | None = None
    note: str | None = None
    time: str | None = None

    def __init__(self, fixture: BaseFixture) -> None:
        self.fixture = fixture

    def is_done(self) -> bool:
        """Check to see if more information is required"""
        return self.player is not None

    def set_assist(self, node: html.HtmlElement) -> None:
        xpath = './/div[contains(@class, "assist")]//text()'
        if a_name := "".join(node.xpath(xpath)):
            a_name = a_name.strip("()")

            xpath = './/div[contains(@class, "assist")]//@href'

            a_url = "".join(node.xpath(xpath))
            if a_url:
                a_url = FLASHSCORE + a_url
            try:
                second, first = a_name.rsplit(" ", 1)
            except ValueError:
                first, second = None, a_name
            self.assist = FSPlayer(forename=first, surname=second, url=a_url)

    def set_player(self, node: html.HtmlElement) -> None:
        xpath = './/a[contains(@class, "playerName")]//text()'
        if name := "".join(node.xpath(xpath)).strip():
            xpath = './/a[contains(@class, "playerName")]//@href'
            url = "".join(node.xpath(xpath)).strip()
            if url:
                url = FLASHSCORE + url

            try:
                sur, first = name.rsplit(" ", 1)
            except ValueError:
                first, sur = None, name
            self.player = FSPlayer(forename=first, surname=sur, url=url)


class Substitution(MatchIncident):
    """A substitution event for a fixture"""

    player_off: FSPlayer | None = None

    def set_player_off(self, node: html.HtmlElement) -> None:
        xpath = './/div[contains(@class, "incidentSubOut")]/a/'
        if name := "".join(node.xpath(xpath + "text()")):
            name = name.strip()

            url = "".join(node.xpath(xpath + "@href"))
            if url:
                url = FLASHSCORE + url

            try:
                surname, forename = name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, name
            player = FSPlayer(forename=forename, surname=surname, url=url)
            self.player_off = player

    def __str__(self) -> str:
        output = ["`🔄`"] if self.time is None else [f"`🔄 {self.time}`"]
        if self.team is not None:
            output.append(self.team.tag)
        if self.player is not None:
            output.append(f"{INBOUND_EMOJI} {self.player.markdown}")
        if self.player_off is not None:
            output.append(f"{OUTBOUND_EMOJI} {self.player_off.markdown}")
        return " ".join(output)


class Goal(MatchIncident):
    """A Generic Goal Event"""

    assist: FSPlayer | None = None

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
        return GOAL_EMOJI

    @property
    def timestamp(self) -> str:
        """String representing the emoji of the goal type and the time"""
        if self.time is None:
            return f"`{self.emote}`"
        return f"`{self.emote} {self.time}`"


class OwnGoal(Goal):
    """An own goal event"""

    @property
    def emote(self) -> str:
        """A string representing an own goal as an emoji"""
        return "⚽ OG"


class Penalty(Goal):
    """A Penalty Event"""

    missed: bool

    def __init__(self, fixture: BaseFixture, missed: bool = False) -> None:
        super().__init__(fixture)
        self.missed = missed

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


class RedCard(MatchIncident):
    """An object representing the event of a dismissal of a player"""

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
        return RED_CARD_EMOJI


class SecondYellow(RedCard):
    """An object representing the event of a dismissal of a player
    after a second yellow card"""

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
        return f"{YELLOW_CARD_EMOJI} {RED_CARD_EMOJI}"


class Booking(MatchIncident):
    """An object representing the event of a player being given
    a yellow card"""

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
        return YELLOW_CARD_EMOJI


class VAR(MatchIncident):
    """An Object Representing the event of a
    Video Assistant Referee Review Decision"""

    in_progress: bool = False
    assist: FSPlayer | None = None

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

    def __init__(self, value: str, valid_events: Type[MatchIncident]):
        self._value_ = value
        self.valid_events = valid_events

    # Goals
    GOAL = "Goal", Goal | VAR
    VAR_GOAL = "VAR Goal", VAR

    # Cards
    RED_CARD = "Red Card", RedCard | VAR
    VAR_RED_CARD = "VAR Red Card", VAR

    # State Changes
    DELAYED = "Match Delayed", None
    INTERRUPTED = "Match Interrupted", None
    CANCELLED = "Match Cancelled", None
    POSTPONED = "Match Postponed", None
    ABANDONED = "Match Abandoned", None
    RESUMED = "Match Resumed", None

    # Period Changes
    KICK_OFF = "Kick Off", None
    HALF_TIME = "Half Time", None
    SECOND_HALF_BEGIN = "Second Half", None
    PERIOD_BEGIN = "Period #PERIOD#", None
    PERIOD_END = "Period #PERIOD# Ends", None
    FULL_TIME = "Full Time", None

    FINAL_RESULT_ONLY = "Final Result", None
    SCORE_AFTER_EXTRA_TIME = "Score After Extra Time", None

    NORMAL_TIME_END = "End of normal time", None
    EXTRA_TIME_BEGIN = "ET: First Half", None
    ET_HT_BEGIN = "ET: Half Time", None
    ET_HT_END = "ET: Second Half", None
    EXTRA_TIME_END = "ET: End of Extra Time", None
    PENALTIES_BEGIN = "Penalties Begin", None
    PENALTY_RESULTS = "Penalty Results", None
