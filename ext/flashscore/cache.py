from __future__ import annotations

import logging
from pydantic import parse_obj_as
from asyncpg import Pool, Record
from .abc import BaseTeam, BaseCompetition, BaseFixture

logger = logging.getLogger("fsdatabase")


class FSCache:
    """Container for all cached data"""

    database: Pool[Record]
    competitions: list[BaseCompetition] = []
    games: list[BaseFixture] = []
    teams: list[BaseTeam] = []

    def __init__(self, database: Pool[Record]) -> None:
        self.database = database

    async def cache_teams(self) -> None:
        teams = await self.database.fetch("""SELECT * from fs_teams""")
        FSCache.teams = parse_obj_as(list[BaseTeam], teams)

    async def cache_competitions(self) -> None:
        comps = await self.database.fetch("""SELECT * from fs_competitions""")
        FSCache.competitions = parse_obj_as(list[BaseCompetition], comps)

    async def save_competitions(self, comps: list[BaseCompetition]) -> None:
        """Save the competition to the bot database"""
        sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
            VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
            (country, name, logo_url, url) =
            (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
            """

        rows = [(i.id, i.country, i.name, i.logo_url, i.url) for i in comps]
        await self.database.executemany(sql, rows, timeout=60)
        await self.cache_competitions()

    async def save_teams(self, teams: list[BaseTeam]) -> None:
        """Save the Team to the Bot Database"""
        sql = """INSERT INTO fs_teams (id, name, logo_url, url)
                VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE SET
                (name, logo_url, url)
                = (EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
                """
        rows = [(i.id, i.name, i.logo_url, i.url) for i in teams if i.url]
        await self.database.executemany(sql, rows, timeout=10)
        await self.cache_teams()

    def get_competition(
        self,
        *,
        id: str | None = None,
        url: str | None = None,
        title: str | None = None,
    ) -> BaseCompetition | None:
        """Retrieve a competition from the ones stored in the cache."""
        cmp = FSCache.competitions
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

    def get_game(self, id: str) -> BaseFixture | None:
        return next((i for i in FSCache.games if i.id == id), None)

    def get_team(self, id: str) -> BaseTeam | None:
        """Retrieve a Team from the ones stored in the cache."""
        return next((i for i in FSCache.teams if i.id == id), None)

    def live_competitions(self) -> list[BaseCompetition]:
        """Get all live competitions"""
        comps: list[BaseCompetition] = []
        for i in self.games:
            if i.competition and i.competition not in comps:
                comps.append(i.competition)
        return comps
