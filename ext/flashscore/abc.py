from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, validator  # type: ignore

from ext.utils import timed_events

from .constants import (
    GOAL_EMOJI,
    COMPETITION_EMOJI,
    FLASHSCORE,
    TEAM_EMOJI,
    RED_CARD_EMOJI,
)
from .gamestate import GameState

if TYPE_CHECKING:
    from .competitions import Competition
    from .team import Team
    from .matchevents import MatchIncident
    from .photos import MatchPhoto


logger = logging.getLogger("flashscore.abc")


class BaseCompetition(BaseModel):
    # Constant
    emoji = COMPETITION_EMOJI

    # Required
    name: str

    # Optional
    id: str | None = None
    country: str | None = None
    url: str | None = None
    logo_url: str | None = None

    # Fetched
    table: str | None = None

    class Config:
        validate_assignment = True

    @validator("country")
    def fmt_country(cls, value: str | None) -> str | None:
        if value:
            return value.split(":")[0]
        return value

    @validator("logo_url")
    def fmt_logo_url(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.rsplit("/", maxsplit=1)[-1]

            if value.endswith(".gif"):  # empty-logo-team-share
                return f"{FLASHSCORE}/res/image/{value}".replace("'", "")

            # Extraneous ' needs removed.
            return f"{FLASHSCORE}/res/image/data/{value}".replace("'", "")

    @validator("url", always=True)
    def fmt_url(cls, value: str | None, values: dict[str, Any]) -> str | None:
        if value and FLASHSCORE in value:
            return value.rstrip("/")

        if values["country"] is not None and value is not None:
            ctr = values["country"].lower().replace(" ", "-")
            return f"{FLASHSCORE}/football/{ctr}/{value}"

        logger.error("failed validating url from %s", values)
        return None

    @property
    def markdown(self) -> str:
        return f"[{self.title}]({self.url})"

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        return self.name

    @property
    def ac_row(self) -> str:
        return f"{self.emoji} {self.title}"


class BaseTeam(BaseModel):
    name: str | None = None
    id: str | None = None  # pylint: disable=C0103
    url: str | None = None

    logo_url: str | None = None

    competition: BaseCompetition | None = None
    gender: str | None = None
    logo_url: str | None = None

    emoji = TEAM_EMOJI

    @property
    def ac_row(self) -> str:
        """Autocomplete"""
        txt = f"{self.emoji} {self.title}"
        if self.competition is not None:
            txt += f" ({self.competition.name})"
        return f"{self.emoji} {txt}"

    @property
    def markdown(self) -> str:
        return f"[{self.name}]({self.url})"

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        if self.name is None:
            return "???"

        if len(self.name.split()) == 1:
            return "".join(self.name[:3]).upper()
        return "".join([i for i in self.name if i.isupper()])

    @property
    def title(self) -> str:
        return f"{TEAM_EMOJI} {self.name}"


class Participant(BaseModel):
    team: BaseTeam

    cards: int = 0
    score: int | None = None
    pens: int | None = None


class BaseFixture(BaseModel):
    emoji = GOAL_EMOJI

    # Required
    home: Participant
    away: Participant

    # Optional
    id: str | None = None
    kickoff: datetime.datetime | None = None
    time: str | GameState | None = None
    competition: Competition | None = None
    url: str | None = None

    # Match Events
    incidents: list[MatchIncident] = []

    # Extra data
    attendance: int | None = None
    infobox: str | None = None
    images: list[MatchPhoto] = []
    referee: str | None = None
    stadium: str | None = None

    @validator("home", "away", always=True)
    def partcipantify(cls, value: Team) -> Participant:
        return Participant(team=value)

    @validator("url")
    def strip_slash(cls, value: str | None) -> str | None:
        if value is not None:
            return value.rstrip("/")

    def __str__(self) -> str:
        if self.time in [
            GameState.LIVE,
            GameState.STOPPAGE_TIME,
            GameState.EXTRA_TIME,
        ]:
            time = self.state.name if self.state else None
        elif isinstance(self.time, GameState):
            time = self.ko_relative
        else:
            time = self.time

        return f"{time}: {self.bold_markdown}"

    @property
    def ac_row(self) -> str:
        """Get team names and comp name for autocomplete searches"""
        out = f"⚽ {self.home.team.name} {self.score} {self.away.team.name}"
        if self.competition:
            out += f" ({self.competition.title})"
        return out

    @property
    def bold_markdown(self) -> str:
        """Markdown Formatting bold **winning** team, with
        [score](as markdown link)."""
        home = self.home.team
        away = self.away.team
        if self.home.score is None or self.away.score is None:
            return f"[{home.name} vs {away.name}]({self.url})"

        # Embolden Winner
        if self.home.score > self.away.score:
            home = f"**{home}**"
        elif self.away.score > self.home.score:
            away = f"**{away}**"

        def parse_cards(cards: int | None) -> str:
            """Get a number of icons matching number of cards"""
            if not cards:
                return ""
            if cards == 1:
                return f"`{RED_CARD_EMOJI}` "
            return f"`{RED_CARD_EMOJI} x{cards}` "

        h_s, a_s = self.home.score, self.away.score
        h_c = parse_cards(self.home.cards)
        a_c = parse_cards(self.away.cards)
        return f"{home} {h_c}[{h_s} - {a_s}]({self.url}){a_c} {away}"

    @property
    def ko_relative(self) -> str:
        """Return a relative timestamp representing the kickoff time"""
        if self.kickoff is None:
            return ""

        time = timed_events.Timestamp(self.kickoff)
        dtn = datetime.datetime.now(tz=datetime.timezone.utc)
        if self.kickoff.date == dtn.date:
            # If the match is today, return HH:MM
            return time.time_hour
        elif self.kickoff.year != dtn.year:
            # if a different year, return DD/MM/YYYY
            return time.date
        elif self.kickoff > dtn:  # For Upcoming
            return time.date_long
        else:
            return time.relative

    @property
    def live_score_text(self) -> str:
        """Text for livescores output:
        home [cards] [score - score or vs] [cards] away"""
        output: list[str] = []
        if self.state is not None:
            output.append(f"`{self.state.emote}")

            if isinstance(self.time, str):
                output.append(self.time)
            else:
                if self.state is not GameState.SCHEDULED:
                    output.append(self.state.shorthand)
            output.append("` ")

        hm_n = self.home.team.name
        aw_n = self.away.team.name

        if self.home.score is None or self.away.score is None:
            time = timed_events.Timestamp(self.kickoff).time_hour
            output.append(f" {time} [{hm_n} v {aw_n}]({self.url})")
        else:
            # Penalty Shootout
            if self.home.pens is not None:
                pens = f" (p: {self.home.pens} - {self.away.pens}) "
                sco = min(self.home.score, self.away.score)
                score = f"[{sco} - {sco}]({self.url})"
                output.append(f"{hm_n} {score}{pens}{aw_n}")
            else:
                output.append(self.bold_markdown)
        return "".join(output)

    @property
    def logo_url(self) -> str | None:
        if self.competition is not None:
            return self.competition.logo_url

    @property
    def name(self) -> str:
        return f"{self.home.team.name} v {self.away.team.name}"

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.score_line}"

    @property
    def score(self) -> str:
        """Return "X - Y", or 'vs' if scores are None"""
        if self.home.score is None:
            return "vs"

        if self.home.pens:
            ph = self.home.pens
            pa = self.away.pens
            return f"({self.home.score}) ({ph}) - ({pa}) {self.away.score}"

        return f"{self.home.score} - {self.away.score}"

    @property
    def score_line(self) -> str:
        """This is used for dropdowns so is left without links
        Outputs in format Home 0 - 0 Away"""
        return f"{self.home.team.name} {self.score} {self.away.team.name}"

    @property
    def state(self) -> GameState | None:
        """Get a GameState value from stored _time"""
        if isinstance(self.time, str):
            if "+" in self.time:
                return GameState.STOPPAGE_TIME
            return GameState.LIVE
        return self.time

    @property
    def table_url(self) -> str:
        if self.url is None:
            raise AttributeError("Fixture has no URL for get_table")
        return self.url.rstrip("/") + "/#/standings"
