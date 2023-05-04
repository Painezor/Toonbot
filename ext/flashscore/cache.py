from __future__ import annotations

import logging
from lxml import html

from asyncpg import Pool, Record

from .competitions import Competition
from .constants import FLASHSCORE
from .fixture import Fixture
from .team import Team

logger = logging.getLogger("fsdatabase")


class FlashscoreCache:
    """Container for all cached data"""

    competitions: list[Competition] = []
    games: list[Fixture] = []
    teams: list[Team] = []

    def __init__(self, database: Pool[Record]) -> None:
        self._pool: Pool[Record] = database

    async def cache_teams(self) -> None:
        teams = await self._pool.fetch("""SELECT * from fs_teams""")
        self.teams = [Team.parse_obj(i) for i in teams]

    async def cache_competitions(self) -> None:
        comps = await self._pool.fetch("""SELECT * from fs_competitions""")
        self.competitions = [Competition.parse_obj(i) for i in comps]

    async def save_competitions(self, comps: list[Competition]) -> None:
        """Save the competition to the bot database"""
        sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
            VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
            (country, name, logo_url, url) =
            (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
            """

        rows = [(i.id, i.country, i.name, i.logo_url, i.url) for i in comps]
        await self._pool.executemany(sql, rows, timeout=60)
        await self.cache_competitions()

    async def save_teams(self, teams: list[Team]) -> None:
        """Save the Team to the Bot Database"""
        sql = """INSERT INTO fs_teams (id, name, logo_url, url)
                VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE SET
                (name, logo_url, url)
                = (EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
                """
        rows = [(i.id, i.name, i.logo_url, i.url) for i in teams]
        await self._pool.executemany(sql, rows, timeout=10)
        await self.cache_teams()

    def get_competition(self, value: str) -> Competition | None:
        """Retrieve a competition from the ones stored in the cache."""
        value = value.rstrip("/")
        for i in self.competitions:
            if i.id == value:
                return i

            if i.title.casefold() == value.casefold():
                return i

            if i.url:
                if i.url.rstrip("/") == value:
                    return i

        # Fallback - Get First Partial match.
        for i in self.competitions:
            if i.url is not None and "http" in value:
                if value in i.url:
                    ttl = i.title
                    logger.info("Partial url: %s to %s (%s)", value, i.id, ttl)
                    return i
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
