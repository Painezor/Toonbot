from __future__ import annotations

import datetime
import logging
from lxml import html
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, validator  # type: ignore

from .constants import (
    GOAL_EMOJI,
    COMPETITION_EMOJI,
    FLASHSCORE,
    TEAM_EMOJI,
)
from .gamestate import GameState

if TYPE_CHECKING:
    from .photos import MatchPhoto
    from .tv import TVListing


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
        return None

    @property
    def title(self) -> str:
        """Return COUNTRY: league"""
        if self.country is not None:
            return f"{self.country.upper()}: {self.name}"
        return self.name


class BaseTeam(BaseModel):
    name: str
    id: str | None = None  # pylint: disable=C0103
    url: str | None = None

    logo_url: str | None = None

    competition: BaseCompetition | None = None
    gender: str | None = None

    emoji = TEAM_EMOJI

    class Config:
        validate_assignment = True

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

        elif value:
            return FLASHSCORE + value

        if values["id"] and values["name"]:
            return f"{FLASHSCORE}/team/{values['name'].lower()}/{values['id']}"
        return None

    @property
    def title(self) -> str:
        return f"{self.name} ({self.id})"


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
    competition: BaseCompetition | None = None
    url: str | None = None

    # Extra data
    attendance: int | None = None
    infobox: str | None = None
    images: list[MatchPhoto] = []
    referee: str | None = None
    stadium: str | None = None
    tv: list[TVListing] = []

    class Config:
        fields = {"_time": "time"}

    @classmethod
    def from_mobi(cls, node: html.HtmlElement, id_: str) -> BaseFixture | None:
        link = "".join(node.xpath(".//a/@href"))
        url = FLASHSCORE + link

        xpath = "./text()"
        teams = [str(i.strip()) for i in node.xpath(xpath) if i.strip()]

        if teams[0].startswith("updates"):
            # Awaiting Updates.
            teams[0] = teams[0].replace("updates", "")

        if len(teams) == 1:
            teams = teams[0].split(" - ")

        if len(teams) == 2:
            home_name, away_name = teams

        elif len(teams) == 3:
            if teams[1] == "La Duchere":
                home_name = f"{teams[0]} {teams[1]}"
                away_name = teams[2]
            elif teams[2] == "La Duchere":
                home_name = teams[0]
                away_name = f"{teams[1]} {teams[2]}"

            elif teams[0] == "Banik Most":
                home_name = f"{teams[0]} {teams[1]}"
                away_name = teams[2]
            elif teams[1] == "Banik Most":
                home_name = teams[0]
                away_name = f"{teams[1]} {teams[2]}"
            else:
                logger.error("BAD: Fetch games found %s", teams)
                return None
        else:
            logger.error("BAD: Fetch games found teams %s", teams)
            return None

        home = Participant(team=BaseTeam(name=home_name))
        away = Participant(team=BaseTeam(name=away_name))
        obj = cls(home=home, away=away, id=id_, url=url)
        return obj

    @validator("url")
    def strip_slash(cls, value: str | None) -> str | None:
        if value is not None:
            return value.rstrip("/")

    @property
    def logo_url(self) -> str | None:
        if self.competition is not None:
            return self.competition.logo_url

    @property
    def name(self) -> str:
        return f"{self.home.team.name} v {self.away.team.name}"

    def get_time(self) -> str | None:
        if time := getattr(self.time, "name", None):
            return time
        elif isinstance(self.time, str):
            return self.time
        return None

    @property
    def title(self) -> str:
        return self.score_line

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
    def base_url(self) -> str:
        if self.url is None:
            raise AttributeError("Fixture has no URL for get_table")
        return self.url.rstrip("/") + "/#"
