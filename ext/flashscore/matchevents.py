"""Match Events used for the ticker"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from lxml import html


from .constants import FLASHSCORE
from .players import FSPlayer

if TYPE_CHECKING:
    from .abc import BaseTeam, BaseFixture


logger = logging.getLogger("matchevents")


class IncidentParser:
    """A parser to generate matchincident classes from a fixture's html"""

    def __init__(self, fixture: BaseFixture, tree: html.HtmlElement) -> None:
        self.fixture = fixture
        self.incidents: list[MatchIncident] = []
        self.tree = tree
        self.parse()

    @staticmethod
    def fmt_player(name: str, url: str) -> FSPlayer:
        """Flip Names around & add link."""
        if url:
            url = FLASHSCORE + url

        try:
            second, first = name.rsplit(" ", 1)
        except ValueError:
            first, second = None, name
        return FSPlayer(forename=first, surname=second, url=url)

    @staticmethod
    def get_note(node: html.HtmlElement) -> str | None:
        xpath = ".//div[@class='smv__subIncident']/text()"
        sub_i = "".join(node.xpath(xpath)).strip()
        if sub_i:
            return sub_i

    def get_assist(self, node: html.HtmlElement) -> FSPlayer | None:
        ct = 'contains(@class, "assist") or contains(@class, "incidentSubOut")'
        xpath = f".//*[{ct}]//text()"
        if name := "".join(node.xpath(xpath)):
            name = name.strip("()")

            if not name:
                return

            xpath = f".//*[{ct}]//@href"
            url = "".join(node.xpath(xpath))
            return self.fmt_player(name, url)

    @staticmethod
    def get_description(node: html.HtmlElement) -> str | None:
        xpath = './/div[contains(@class, "incidentIcon")]//@title'
        title = "".join(node.xpath(xpath)).replace("<br />", " ").strip()
        if title:
            return title

    def get_player(self, node: html.HtmlElement) -> FSPlayer | None:
        xpath = './a[contains(@class, "playerName")]//text()'
        if name := "".join(node.xpath(xpath)).strip():
            xpath = './a[contains(@class, "playerName")]//@href'
            url = "".join(node.xpath(xpath)).strip()
            return self.fmt_player(name, url)

    def parse(self):
        """Find what parser we need to use and send data to it"""
        xpath = './/div[contains(@class, "verticalSections")]/div'
        for i in self.tree.xpath(xpath):
            team_detection = i.attrib["class"]
            if "Header" in team_detection:
                self.parse_header(i)
                continue

            try:
                # event node -- if we can't find one, we can't parse one.
                node = i.xpath('./div[contains(@class, "incident")]')[0]
            except IndexError:
                continue

            xpath = './/div[contains(@class, "timeBox")]//text()'
            time = "".join(node.xpath(xpath)).strip()
            class_ = "".join(node.xpath(".//svg/@class"))
            xlink = "".join(node.xpath(".//svg/use/@*[name()='xlink:href']"))
            if xlink.strip():
                class_ = xlink.rsplit("#", maxsplit=1)[-1].strip()

            type = "".join(node.xpath(".//svg//text()")).strip()

            event = MatchIncident(time=time, svg_class=class_, type=type)
            event.note = self.get_note(node)
            event.player = self.get_player(node)
            event.assist = self.get_assist(node)
            event.description = self.get_description(node)

            if "home" in team_detection:
                event.team = self.fixture.home.team
            elif "away" in team_detection:
                event.team = self.fixture.away.team

            self.incidents.append(event)

    def parse_header(self, i: html.HtmlElement) -> None:
        """Store Penalties"""
        text = [x.strip() for x in i.xpath(".//text()")]
        if "Penalties" in text:
            try:
                self.fixture.home.pens = int(text[1])
                self.fixture.away.pens = int(text[3])
                logger.info("Parsed a 2 part penalties OK!!")
            except (ValueError, IndexError):
                # If Penalties are still in progress, it's actually
                # in format ['Penalties', '1 - 2']
                _, pen_string = text
                home, away = pen_string.split(" - ")
                self.fixture.home.pens = int(home)
                self.fixture.away.pens = int(away)


class MatchIncident(BaseModel):
    """An object representing an event happening in a fixture"""

    time: str
    type: str
    svg_class: str

    player: FSPlayer | None = None
    assist: FSPlayer | None = None
    team: BaseTeam | None = None
    description: str | None = None
    note: str | None = None

    class Config:
        validate_assignment = True


from .abc import BaseTeam  # noqa

MatchIncident.update_forward_refs()
