from lxml import html

from pydantic import BaseModel

from .constants import (
    FLASHSCORE,
    GOAL_EMOJI,
    INJURY_EMOJI,
    RED_CARD_EMOJI,
    TEAM_EMOJI,
    YELLOW_CARD_EMOJI,
)
from .players import FSPlayer


class SquadMember(BaseModel):
    """A Player that is a member of a team"""

    player: FSPlayer
    position: str

    squad_number: int
    position: str
    appearances: int
    goals: int
    assists: int
    yellows: int
    reds: int
    injury: str

    @property
    def output(self) -> str:
        """Return a row representing the Squad Member"""
        plr = self.player
        pos = self.position
        pmd = f"[{plr.name}]({plr.url})"
        text = f"`#{self.squad_number}` {plr.flags} {pmd} ({pos}): "

        if self.goals:
            text += f" {GOAL_EMOJI} {self.goals}"
        if self.appearances:
            text += f" {TEAM_EMOJI} {self.appearances}"
        if self.reds:
            text += f" {RED_CARD_EMOJI} {self.reds}"
        if self.yellows:
            text += f" {YELLOW_CARD_EMOJI} {self.yellows}"
        if self.injury:
            text += f" {INJURY_EMOJI} {self.injury}"
        return text


def parse_squad_member(row: html.HtmlElement, position: str) -> SquadMember:
    from .players import FSPlayer

    xpath = './/div[contains(@class, "cell--name")]/a/@href'
    link = FLASHSCORE + "".join(row.xpath(xpath))

    xpath = './/div[contains(@class, "cell--name")]/a/text()'
    name = "".join(row.xpath(xpath)).strip()
    try:  # Name comes in reverse order.
        sur, first = name.rsplit(" ", 1)
    except ValueError:
        first, sur = None, name

    plr = FSPlayer(forename=first, surname=sur, url=link)
    xpath = './/div[contains(@class,"flag")]/@title'
    plr.country = [str(x.strip()) for x in row.xpath(xpath) if x]
    xpath = './/div[contains(@class,"cell--age")]/text()'
    if age := "".join(row.xpath(xpath)).strip():
        plr.age = int(age)

    xpath = './/div[contains(@class,"jersey")]/text()'
    num = int("".join(row.xpath(xpath)) or 0)

    xpath = './/div[contains(@class,"matchesPlayed")]/text()'
    if apps := "".join(row.xpath(xpath)).strip():
        apps = int(apps)
    else:
        apps = 0

    xpath = './/div[contains(@class,"cell--goal")]/text()'
    if goals := "".join(row.xpath(xpath)).strip():
        goals = int(goals)
    else:
        goals = 0

    xpath = './/div[contains(@class,"yellowCard")]/text()'
    if yellows := "".join(row.xpath(xpath)).strip():
        yellows = int(yellows)
    else:
        yellows = 0

    xpath = './/div[contains(@class,"redCard")]/text()'
    if reds := "".join(row.xpath(xpath)).strip():
        reds = int(reds)
    else:
        reds = 0

    xpath = './/div[contains(@title,"Injury")]/@title'
    injury = "".join(row.xpath(xpath)).strip()

    return SquadMember(
        player=plr,
        position=position,
        squad_number=num,
        appearances=apps,
        goals=goals,
        assists=0,
        yellows=yellows,
        reds=reds,
        injury=injury,
    )
