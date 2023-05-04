from __future__ import annotations

import logging
from lxml import html
from typing import TYPE_CHECKING

from pydantic import BaseModel


from .constants import FLASHSCORE, GOAL_EMOJI


if TYPE_CHECKING:
    from playwright.async_api import Page
    from .players import FSPlayer
    from .team import Team

logger = logging.getLogger("flashscore.top_scorers")


class HasScorers:
    url: str | None

    async def get_scorers(self, page: Page) -> list[TopScorer]:
        """Get a list of TopScorer objects for the Flashscore Item"""
        link = f"{self.url}/standings/"

        # Example link "#/nunhS7Vn/top_scorers"
        # This requires a competition ID, annoyingly.
        if link not in page.url:
            logger.info("Forcing page change %s -> %s", page.url, link)
            await page.goto(link)

        top_scorer_button = page.locator("a", has_text="Top Scorers")
        await top_scorer_button.wait_for(timeout=5000)

        if await top_scorer_button.get_attribute("aria-current") != "page":
            await top_scorer_button.click()

        tab_class = page.locator("#tournament-table-tabs-and-content")
        await tab_class.wait_for()

        btn = page.locator(".topScorers__showMore")
        while await btn.count():
            await btn.last.click()

        raw = await tab_class.inner_html()
        tree = html.fromstring(raw)
        rows = tree.xpath('.//div[@class="ui-table__body"]/div')
        return [parse_scorer(i) for i in rows]


class TopScorer(BaseModel):
    """A Top Scorer object fetched from a Flashscore Item"""

    player: FSPlayer
    team: Team | None = None
    goals: int = 0
    rank: int = 0
    assists: int = 0

    def __init__(self, player: FSPlayer) -> None:
        self.player = player

    @property
    def output(self) -> str:
        """Return a formatted string output for this TopScorer"""
        text = f"`{str(self.rank).rjust(3)}.` {GOAL_EMOJI} {self.goals}"
        if self.assists:
            text += f" (+{self.assists})"
        text += f" {self.player.flags[0]} {self.player.markdown}"
        if self.team:
            text += f" ({self.team.markdown})"
        return text


def parse_scorer(node: html.HtmlElement) -> TopScorer:
    """Turn an xpath node into a TopScorer Object"""
    from .team import Team

    xpath = "./div[1]//text()"
    name = "".join(node.xpath(xpath))

    xpath = "./div[1]//@href"
    url = FLASHSCORE + "".join(node.xpath(xpath))

    scorer = TopScorer(FSPlayer(forename=None, surname=name, url=url))
    xpath = "./span[1]//text()"
    scorer.rank = int("".join(node.xpath(xpath)).strip("."))

    xpath = './/span[contains(@class,"flag")]/@title'
    scorer.player.country = node.xpath(xpath)

    xpath = './/span[contains(@class, "--goals")]/text()'
    try:
        scorer.goals = int("".join(node.xpath(xpath)))
    except ValueError:
        pass

    xpath = './/span[contains(@class, "--gray")]/text()'
    try:
        scorer.assists = int("".join(node.xpath(xpath)))
    except ValueError:
        pass

    team_url = FLASHSCORE + "".join(node.xpath("./a/@href"))
    team_id = team_url.split("/")[-2]

    tmn = "".join(node.xpath("./a/text()"))
    team_link = "".join(node.xpath(".//a/@href"))
    tm = Team(id=team_id, name=tmn, url=team_link)

    scorer.team = tm
    return scorer
