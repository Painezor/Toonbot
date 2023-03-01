"""The Flashscore Search Feature, with language controls."""
from __future__ import annotations

import typing
from urllib.parse import quote

from discord import Locale

from ext.toonbot_utils import flashscore as fs

if typing.TYPE_CHECKING:
    from typing import Literal

    from discord import Interaction

    from core import Bot

# slovak - 7
# Hebrew - 17
# Slovenian - 24
# Estonian - 26
# Indonesian - 35
# Catalan - 43
# Georgian - 44

locales = {
    Locale.american_english: 1,  # 'en-US'
    Locale.british_english: 1,  # 'en-GB' flashscore.co.uk
    Locale.bulgarian: 40,  # 'bg'
    Locale.chinese: 19,  # 'zh-CN'
    Locale.taiwan_chinese: 19,  # 'zh-TW'
    Locale.french: 16,  # 'fr'    flashscore.fr
    Locale.croatian: 14,  # 'hr'  # Could also be 25?
    Locale.czech: 2,  # 'cs'
    Locale.danish: 8,  # 'da'
    Locale.dutch: 21,  # 'nl'
    Locale.finnish: 18,  # 'fi'
    Locale.german: 4,  # 'de'
    Locale.greek: 11,  # 'el'
    Locale.hindi: 1,  # 'hi'
    Locale.hungarian: 15,  # 'hu'
    Locale.italian: 6,  # 'it'
    Locale.japanese: 42,  # 'ja'
    Locale.korean: 38,  # 'ko'
    Locale.lithuanian: 27,  # 'lt'
    Locale.norwegian: 23,  # 'no'
    Locale.polish: 3,  # 'pl'
    Locale.brazil_portuguese: 20,  # 'pt-BR'   # Could also be 31
    Locale.romanian: 9,  # 'ro'
    Locale.russian: 12,  # 'ru'
    Locale.spain_spanish: 13,  # 'es-ES'
    Locale.swedish: 28,  # 'sv-SE'
    Locale.thai: 1,  # 'th'
    Locale.turkish: 10,  # 'tr'
    Locale.ukrainian: 41,  # 'uk'
    Locale.vietnamese: 37,  # 'vi'
}


async def fs_search(
    interaction: Interaction[Bot], query: str, mode: Literal["comp", "team"]
) -> list[fs.Competition | fs.Team]:
    """Fetch a list of items from flashscore matching the user's query"""
    query = quote(query.translate(dict.fromkeys(map(ord, "'[]#<>"), None)))

    bot = interaction.client

    try:
        lang_id = locales[interaction.locale]
    except KeyError:
        try:
            if interaction.guild_locale is None:
                lang_id = 1
            else:
                lang_id = locales[interaction.guild_locale]
        except KeyError:
            lang_id = 1

    # Type IDs: 1 - Team | Tournament, 2 - Team, 3 - Player 4 - PlayerInTeam
    url = (
        f"https://s.livesport.services/api/v2/search/?q={query}"
        f"&lang-id={lang_id}&type-ids=1,2,3,4&sport-ids=1"
    )

    async with bot.session.get(url) as resp:
        match resp.status:
            case 200:
                res = typing.cast(dict, await resp.json())
            case _:
                err = f"HTTP {resp.status} error while searching flashscore"
                raise LookupError(err)

    results: list[fs.Competition | fs.Team] = []
    for x in res:
        for t in x["participantTypes"]:
            match t["name"]:
                case "National" | "Team":
                    if mode == "comp":
                        continue

                    if not (team := bot.get_team(x["id"])):

                        team = fs.Team(x["id"], x["name"], x["url"])
                        team.logo_url = x["images"][0]["path"]
                        team.gender = x["gender"]["name"]
                        await save_team(interaction, team)
                    results.append(team)
                case "TournamentTemplate":
                    if mode == "team":
                        continue

                    if not (comp := bot.get_competition(x["id"])):
                        ctry = x["defaultCountry"]["name"]
                        nom = x["name"]
                        comp = fs.Competition(x["id"], nom, ctry, x["url"])
                        comp.logo_url = x["images"][0]["path"]
                        await save_comp(interaction, comp)
                    results.append(comp)
                case _:
                    continue  # This is a player, we don't want those.

    if not results:
        raise LookupError("Flashscore Search: No results found for %s", query)
    return results


# DB Management
async def save_team(interaction: Interaction[Bot], t: fs.Team) -> None:
    """Save the Team to the Bot Database"""
    sql = """INSERT INTO fs_teams (id, name, logo_url, url)
             VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"""
    bot = interaction.client
    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(sql, t.id, t.name, t.logo_url, t.url)
    bot.teams.append(t)


async def save_comp(i: Interaction[Bot], c: fs.Competition) -> None:
    """Save the competition to the bot database"""
    bot = i.client
    sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
                 VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING"""
    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(sql, c.id, c.country, c.name, c.logo_url, c.url)
    bot.competitions.append(c)
