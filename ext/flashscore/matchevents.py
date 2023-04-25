"""Match Events used for the ticker"""
from __future__ import annotations

import enum
import logging
from lxml import html
from typing import Any, TYPE_CHECKING, Optional, Type

import discord

from .constants import (
    FLASHSCORE,
    INBOUND_EMOJI,
    OUTBOUND_EMOJI,
    GOAL_EMOJI,
    RED_CARD_EMOJI,
    YELLOW_CARD_EMOJI,
)

from .players import FSPlayer

if TYPE_CHECKING:
    from .fixture import Fixture
    from .team import Team


logger = logging.getLogger("matchevents")


def parse_header(i: html.HtmlElement, fixture: Fixture) -> None:
    """Store Penalties"""
    text = [x.strip() for x in i.xpath(".//text()")]
    if "Penalties" in text:
        try:
            fixture.penalties_home = text[1]
            fixture.penalties_away = text[3]
            logger.info("Parsed a 2 part penalties OK!!")
        except IndexError:
            # If Penalties are still in progress, it's actually
            # in format ['Penalties', '1 - 2']
            _, pen_string = text
            home, away = pen_string.split(" - ")
            fixture.penalties_home = home
            fixture.penalties_away = away


def parse_events(fixture: Fixture, tree: Any) -> list[MatchEvent]:
    """Get a list of match events"""
    events: list[MatchEvent] = []
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

        svg_text = "".join(node.xpath(".//svg//text()")).strip()
        svg_class = "".join(node.xpath(".//svg/@class")).strip()
        sub_i = "".join(node.xpath(".//div[@class='smv__subIncident']/text()"))

        # Try to figure out what kind of event this is.
        if svg_class == "soccer":
            # This is a goal.

            if sub_i == "(Penalty)":
                event = Penalty(fixture)

            elif sub_i:
                logger.info("Unhandled goal sub_incident %s", sub_i)
                event = Goal(fixture)

            else:
                event = Goal(fixture)

        elif "footballOwnGoal-ico" in svg_class:
            event = OwnGoal(fixture)

        elif "Penalty missed" in sub_i:
            event = Penalty(fixture, missed=True)

        # cards
        elif (
            "Yellow card / Red card" in svg_text
            or "redyellowcard-ico" in svg_class.casefold()
        ):
            event = SecondYellow(fixture)

        elif "redCard-ico" in svg_class:
            event = RedCard(fixture)

        elif "yellowCard-ico" in svg_class:
            event = Booking(fixture)

        elif "card-ico" in svg_class:
            event = Booking(fixture)
            logger.info("Fallback reached, card-ico")

        # VAR
        elif "var" in svg_class:
            event = VAR(fixture)
            if svg_class != "var":
                logger.info("var has svg_clas %s", svg_class)

        # Subs
        elif "substitution" in svg_class:
            event = Substitution(fixture)
            event.set_player_off(node)

        else:
            logger.info("parsing match events on %s", fixture.url)
            logger.error("Match Event Not Handled correctly.")
            logger.info("text: %s, class: %s", svg_text, svg_class)
            if sub_i:
                logger.info("sub_incident: %s", sub_i)

            event = MatchEvent(fixture)

        # Event Player.
        event.set_player(node)

        # Assist of a goal.
        if isinstance(event, Goal):
            event.set_assist(node)

        if "home" in team_detection:
            event.team = fixture.home
        elif "away" in team_detection:
            event.team = fixture.away

        xpath = './/div[contains(@class, "timeBox")]//text()'
        time = "".join(node.xpath(xpath)).strip()
        event.time = time
        event.note = svg_text

        # Description of the event.
        xpath = './/div[contains(@class, "incidentIcon")]//@title'
        title = "".join(node.xpath(xpath)).strip().replace("<br />", " ")
        event.description = title

        events.append(event)
    return events


class MatchEvent:
    """An object representing an event happening in a fixture"""

    fixture: Fixture

    assist: Optional[FSPlayer] = None
    colour: discord.Colour = discord.Colour.dark_embed()
    description: Optional[str] = None
    icon_url: Optional[str] = None
    player: Optional[FSPlayer] = None
    team: Optional[Team] = None
    note: Optional[str] = None
    time: Optional[str] = None

    def __init__(self, fixture: Fixture) -> None:
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
                surname, forename = a_name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, a_name
            self.assist = FSPlayer(forename, surname, a_url)

    def set_player(self, node: html.HtmlElement) -> None:
        xpath = './/a[contains(@class, "playerName")]//text()'
        if p_name := "".join(node.xpath(xpath)).strip():
            xpath = './/a[contains(@class, "playerName")]//@href'
            p_url = "".join(node.xpath(xpath)).strip()
            if p_url:
                p_url = FLASHSCORE + p_url

            try:
                surname, forename = p_name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, p_name
            self.player = FSPlayer(forename, surname, p_url)

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
    player_off: Optional[FSPlayer] = None

    def set_player_off(self, node: html.HtmlElement) -> None:
        xpath = './/div[contains(@class, "incidentSubOut")]/a/'
        if s_name := "".join(node.xpath(xpath + "text()")):
            s_name = s_name.strip()

            s_url = "".join(node.xpath(xpath + "@href"))
            if s_url:
                s_url = FLASHSCORE + s_url

            try:
                surname, forename = s_name.rsplit(" ", 1)
            except ValueError:
                forename, surname = None, s_name
            player = FSPlayer(forename, surname, s_url)
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


class Goal(MatchEvent):
    """A Generic Goal Event"""

    colour = discord.Colour.green()
    assist: Optional[FSPlayer] = None

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

    colour = discord.Colour.dark_green()

    @property
    def emote(self) -> str:
        """A string representing an own goal as an emoji"""
        return "⚽ OG"


class Penalty(Goal):
    """A Penalty Event"""

    colour = discord.Colour.brand_green()
    missed: bool

    def __init__(self, fixture: Fixture, missed: bool = False) -> None:
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
        return RED_CARD_EMOJI


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
        return f"{YELLOW_CARD_EMOJI} {RED_CARD_EMOJI}"


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
        return YELLOW_CARD_EMOJI


class VAR(MatchEvent):
    """An Object Representing the event of a
    Video Assistant Referee Review Decision"""

    in_progress: bool = False
    colour = discord.Colour.og_blurple()
    assist: Optional[FSPlayer] = None

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
        valid_events: Type[MatchEvent],
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
