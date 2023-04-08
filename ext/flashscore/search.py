"""Flashscore Search Function for automcompleting"""
import logging
import typing
from urllib.parse import quote

import discord

from .competitions import Competition
from .team import Team

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]


logger = logging.getLogger("flashscore.search")

# slovak - 7
# Hebrew - 17
# Slovenian - 24
# Estonian - 26
# Indonesian - 35
# Catalan - 43
# Georgian - 44

locales = {
    discord.Locale.american_english: 1,  # 'en-US'
    discord.Locale.british_english: 1,  # 'en-GB' flashscore.co.uk
    discord.Locale.bulgarian: 40,  # 'bg'
    discord.Locale.chinese: 19,  # 'zh-CN'
    discord.Locale.taiwan_chinese: 19,  # 'zh-TW'
    discord.Locale.french: 16,  # 'fr'    flashscore.fr
    discord.Locale.croatian: 14,  # 'hr'  # Could also be 25?
    discord.Locale.czech: 2,  # 'cs'
    discord.Locale.danish: 8,  # 'da'
    discord.Locale.dutch: 21,  # 'nl'
    discord.Locale.finnish: 18,  # 'fi'
    discord.Locale.german: 4,  # 'de'
    discord.Locale.greek: 11,  # 'el'
    discord.Locale.hindi: 1,  # 'hi'
    discord.Locale.hungarian: 15,  # 'hu'
    discord.Locale.italian: 6,  # 'it'
    discord.Locale.japanese: 42,  # 'ja'
    discord.Locale.korean: 38,  # 'ko'
    discord.Locale.lithuanian: 27,  # 'lt'
    discord.Locale.norwegian: 23,  # 'no'
    discord.Locale.polish: 3,  # 'pl'
    discord.Locale.brazil_portuguese: 20,  # 'pt-BR'   # Could also be 31
    discord.Locale.romanian: 9,  # 'ro'
    discord.Locale.russian: 12,  # 'ru'
    discord.Locale.spain_spanish: 13,  # 'es-ES'
    discord.Locale.swedish: 28,  # 'sv-SE'
    discord.Locale.thai: 1,  # 'th'
    discord.Locale.turkish: 10,  # 'tr'
    discord.Locale.ukrainian: 41,  # 'uk'
    discord.Locale.vietnamese: 37,  # 'vi'
}


async def search(
    query: str,
    mode: typing.Literal["comp", "team"],
    interaction: Interaction,
) -> list[Competition | Team]:
    """Fetch a list of items from flashscore matching the user's query"""
    replace = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))
    query = quote(replace)

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

    async with interaction.client.session.get(url) as resp:
        if resp.status != 200:
            logger.error("%s %s: %s", resp.status, resp.reason, resp.url)
        res = await resp.json()

    results: list[Competition | Team] = []

    for i in res:
        if i["participantTypes"] is None:
            if i["type"]["name"] == "TournamentTemplate":
                id_ = i["id"]
                name = i["name"]
                ctry = i["defaultCountry"]["name"]
                url = i["url"]

                comp = interaction.client.get_competition(id_)

                if comp is None:
                    comp = Competition(id_, name, ctry, url)
                    await save_comp(interaction.client, comp)

                if i["images"]:
                    logo_url = i["images"][0]["path"]
                    comp.logo_url = logo_url

                results.append(comp)
            else:
                types = i["participantTypes"]
                logging.info("unhandled particpant types %s", types)
        else:
            for type_ in i["participantTypes"]:
                t_name = type_["name"]
                if t_name in ["National", "Team"]:
                    if mode == "comp":
                        continue

                    if not (team := interaction.client.get_team(i["id"])):
                        team = Team(i["id"], i["name"], i["url"])
                        try:
                            team.logo_url = i["images"][0]["path"]
                        except IndexError:
                            pass
                        team.gender = i["gender"]["name"]
                        await save_team(interaction.client, team)
                    results.append(team)
                elif t_name == "TournamentTemplate":
                    if mode == "team":
                        continue

                    comp = interaction.client.get_competition(i["id"])
                    if not comp:
                        ctry = i["defaultCountry"]["name"]
                        nom = i["name"]
                        comp = Competition(i["id"], nom, ctry, i["url"])
                        try:
                            comp.logo_url = i["images"][0]["path"]
                        except IndexError:
                            pass
                        await save_comp(interaction.client, comp)
                        results.append(comp)
                else:
                    continue  # This is a player, we don't want those.

    return results


async def save_comp(bot: Bot, comp: Competition) -> None:
    """Save the competition to the bot database"""
    sql = """INSERT INTO fs_competitions (id, country, name, logo_url, url)
             VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO UPDATE SET
             (country, name, logo_url, url) =
             (EXCLUDED.country, EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
             """

    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(
                sql, comp.id, comp.country, comp.name, comp.logo_url, comp.url
            )
    bot.competitions.add(comp)
    logger.info("saved competition. %s %s %s", comp.name, comp.id, comp.url)


async def save_team(bot: Bot, team: Team) -> None:
    """Save the Team to the Bot Database"""
    sql = """INSERT INTO fs_teams (id, name, logo_url, url)
             VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO UPDATE SET
             (name, logo_url, url)
             = (EXCLUDED.name, EXCLUDED.logo_url, EXCLUDED.url)
             """
    async with bot.db.acquire(timeout=60) as conn:
        async with conn.transaction():
            await conn.execute(
                sql, team.id, team.name, team.logo_url, team.url
            )
    bot.teams.append(team)
