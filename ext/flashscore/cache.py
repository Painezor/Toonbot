from __future__ import annotations

import logging
from lxml import html
from pydantic import BaseModel, parse_obj_as
from typing import TYPE_CHECKING

from asyncpg import Pool, Record

from .constants import FLASHSCORE

if TYPE_CHECKING:
    from .competitions import Competition
    from .fixture import Fixture
    from .team import Team

logger = logging.getLogger("fsdatabase")


class FlashscoreCache(BaseModel):
    """Container for all cached data"""

    database: Pool[Record]
    competitions: list[Competition] = []
    games: list[Fixture] = []
    teams: list[Team] = []

    async def cache_teams(self) -> None:
        teams = await self.database.fetch("""SELECT * from fs_teams""")
        self.teams = parse_obj_as(list[Team], teams)

    async def cache_competitions(self) -> None:
        comps = await self.database.fetch("""SELECT * from fs_competitions""")
        self.competitions = parse_obj_as(list[Competition], comps)

    async def save_competitions(self, comps: list[Competition]) -> None:
        """Save the competition to the bot database"""
        sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
            VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
            (country, name, logo_url, url) =
            (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
            """

        rows = [(i.id, i.country, i.name, i.logo_url, i.url) for i in comps]
        await self.database.executemany(sql, rows, timeout=60)
        await self.cache_competitions()

    async def save_teams(self, teams: list[Team]) -> None:
        """Save the Team to the Bot Database"""
        sql = """INSERT INTO fs_teams (id, name, logo_url, url)
                VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE SET
                (name, logo_url, url)
                = (EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
                """
        rows = [(i.id, i.name, i.logo_url, i.url) for i in teams]
        await self.database.executemany(sql, rows, timeout=10)
        await self.cache_teams()

    def get_competition(
        self,
        *,
        id: str | None = None,
        url: str | None = None,
        title: str | None = None,
    ) -> Competition | None:
        """Retrieve a competition from the ones stored in the cache."""
        cmp = self.competitions
        if id is not None:
            try:
                return next(i for i in cmp if i.id == id)
            except StopIteration:
                pass

        if url is not None:
            url = url.rstrip("/")
            try:
                return next(i for i in cmp if i.url == url)
            except StopIteration:
                pass

        if title is not None:
            title = title.casefold()
            return next((i for i in cmp if i.title.casefold() == title), None)
        return None

    def get_game(self, fixture_id: str) -> Fixture | None:
        return next((i for i in self.games if i.id == fixture_id), None)

    def get_team(self, team_id: str) -> Team | None:
        """Retrieve a Team from the ones stored in the cache."""
        return next((i for i in self.teams if i.id == team_id), None)

    def live_competitions(self) -> list[Competition]:
        """Get all live competitions"""
        comps: list[Competition] = []
        for i in self.games:
            if i.competition and i.competition not in comps:
                comps.append(i.competition)
        return comps

    async def teams_from_fixture(
        self, tree: html.HtmlElement
    ) -> tuple[Team, Team]:
        teams: list[Team] = []
        for attr in ["home", "away"]:
            xpath = f".//div[contains(@class, 'duelParticipant__{attr}')]"
            div = tree.xpath(xpath)
            if not div:
                raise LookupError("Cannot find team on page.")

            div = div[0]  # Only One

            # Get Name
            xpath = ".//a[contains(@class, 'participant__participantName')]/"
            name = "".join(div.xpath(xpath + "text()"))
            url = "".join(div.xpath(xpath + "@href"))

            team_id = url.split("/")[-2]
            if (team := self.get_team(team_id)) is None:
                team = Team(id=team_id, name=name, url=FLASHSCORE + url)

            if team.logo_url is None:
                logo = div.xpath('.//img[@class="participant__image"]/@src')
                logo = "".join(logo)
                if logo:
                    team.logo_url = FLASHSCORE + logo
            teams.append(team)
        await self.save_teams(teams)
        return tuple(teams)
