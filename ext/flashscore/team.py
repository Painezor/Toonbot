"""Working with teams retrieved from flashscore"""
from __future__ import annotations

import typing

import asyncpg

from .abc import FlashScoreItem
from .competitions import Competition
from .constants import FLASHSCORE, TEAM_EMOJI
from .search import save_team

if typing.TYPE_CHECKING:
    from core import Bot


class Team(FlashScoreItem):
    """An object representing a Team from Flashscore"""

    __slots__ = {
        "competition": "The competition the team belongs to",
        "logo_url": "A link to a logo representing the competition",
        "gender": "The Gender that this team is comprised of",
    }

    # Constant
    emoji = TEAM_EMOJI

    def __init__(
        self, fs_id: typing.Optional[str], name: str, url: typing.Optional[str]
    ) -> None:
        # Example URL:
        # https://www.flashscore.com/team/thailand-stars/jLsL0hAF/
        # https://www.flashscore.com/?r=3:jLsL0hAF

        if fs_id is None and url:
            fs_id = url.split("/")[-1]
        elif url and fs_id and FLASHSCORE not in url:
            url = f"{FLASHSCORE}/team/{url}/{fs_id}"
        elif fs_id and not url:
            url = f"https://www.flashscore.com/?r=3:{id}"

        super().__init__(fs_id, name, url)

        self.gender: typing.Optional[str] = None
        self.competition: typing.Optional[Competition] = None

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Team:
        """Retrieve a Team object from an asyncpg Record"""
        team = Team(record["id"], record["name"], record["url"])
        team.logo_url = record["logo_url"]
        return team

    @classmethod
    async def from_fixture_html(
        cls, bot: Bot, tree, home: bool = True
    ) -> Team:
        """Parse a team from the HTML of a flashscore FIxture"""
        attr = "home" if home else "away"

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

        if (team := bot.get_team(team_id)) is not None:
            if team.name != name:
                team.name = name
        else:
            for i in bot.teams:
                if i.url and url in i.url:
                    team = i
                    break
            else:
                team = Team(team_id, name, FLASHSCORE + url)

        if team.logo_url is None:
            logo = div.xpath('.//img[@class="participant__image"]/@src')
            logo = "".join(logo)
            if logo:
                team.logo_url = FLASHSCORE + logo

        if team not in bot.teams:
            await save_team(bot, team)

        return team

    def __str__(self) -> str:
        output = self.name or "Unknown Team"
        if self.competition is not None:
            output = f"{output} ({self.competition.title})"
        return output

    @property
    def tag(self) -> str:
        """Generate a 3 letter tag for the team"""
        if len(self.name.split()) == 1:
            return "".join(self.name[:3]).upper()
        else:
            return "".join([i for i in self.name if i.isupper()])
