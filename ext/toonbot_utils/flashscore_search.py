"""The Flashscore Search Feature, with language controls."""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from discord import Locale

from ext.utils import view_utils
from ext.toonbot_utils import flashscore as fs

if TYPE_CHECKING:
    from discord import Interaction, Message
    from typing import Literal
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


async def fs_search(interaction: Interaction, query: str, mode: Literal['comp', 'team'], get_recent: bool = False) \
        -> fs.Competition | fs.Team | Message:
    """Fetch a list of items from flashscore matching the user's query"""
    query = quote(query.translate(dict.fromkeys(map(ord, "'[]#<>"), None)))

    bot: Bot = interaction.client

    try:
        lang_id = locales[interaction.locale]
    except KeyError:
        try:
            lang_id = locales[interaction.guild_locale]
        except KeyError:
            lang_id = 1

    # Type IDs: 1 - Team | Tournament, 2 - Team, 3 - Player 4 - PlayerInTeam
    url = f"https://s.livesport.services/api/v2/search/?q={query}&lang-id={lang_id}&type-ids=1,2,3,4&sport-ids=1"

    async with bot.session.get(url) as resp:
        match resp.status:
            case 200: res = await resp.json()
            case _: return await interaction.client.error(interaction, f"HTTP {resp.status} error in fs_search")

    results: list[fs.Competition | fs.Team] = []
    for x in res:
        for t in x["participantTypes"]:
            match t["name"]:
                case "National" | "Team":
                    if mode == "comp":
                        continue

                    if not (team := bot.get_team(x['id'])):
                        team = fs.Team(bot)
                        team.name = x['name']
                        team.url = x['url']
                        team.id = x['id']
                        team.logo_url = x['images'][0]["path"]
                        team.gender = x['gender']['name']
                        await team.save_to_db()
                    results.append(team)
                case "TournamentTemplate":
                    if mode == "team":
                        continue

                    if not (comp := bot.get_competition(x['id'])):
                        comp = fs.Competition(bot)
                        comp.country = x['defaultCountry']['name']
                        comp.id = x['id']
                        comp.url = x['url']
                        comp.logo_url = x['images'][0]['path']
                        comp.name = x['name']
                        await comp.save_to_db()
                    results.append(comp)
                case _: continue  # This is a player, we don't want those.

    if not results:
        return await interaction.client.error(f"Flashscore Search: No results found for {query}")

    if len(results) == 1:
        fsr = next(results)
    else:
        view = view_utils.ObjectSelectView(interaction, [('🏆', str(i), i.link) for i in results], timeout=60)
        await view.update()
        await view.wait()
        if view.value is None:
            return None
        fsr = results[view.value]

    if not get_recent:
        return fsr

    if not (items := await fsr.results()):
        return await interaction.client.error(interaction, f"No recent games found for {fsr.title}")

    view = view_utils.ObjectSelectView(interaction, objects=[("⚽", i.score_line, f"{i.competition}") for i in items],
                                       timeout=60)
    await view.wait()

    if view.value is None:
        return await interaction.client.error(interaction, 'Timed out waiting for you to select a recent game.')

    return items[view.value]

# Old Version
# async def search(interaction: Interaction, query: str, mode: Literal['comp', 'team'], get_recent: bool = False) \
#         -> Competition | Team | Message:
#     """Fetch a list of items from flashscore matching the user's query"""
#     query = query.translate(dict.fromkeys(map(ord, "'[]#<>"), None))
#
#     bot: Bot = interaction.client
#
#     query = quote(query)
#     # One day we could probably expand upon this if we ever figure out what the other variables are.
#     async with bot.session.get(f"https://s.flashscore.com/search/?q={query}&l=1&s=1&f=1%3B1&pid=2&sid=1") as resp:
#         match resp.status:
#             case 200:
#                 res = await resp.text(encoding="utf-8")
#             case _:
#                 raise ConnectionError(f"HTTP {resp.status} error in fs_search")
#
#     # Un-fuck FS JSON reply.
#     res = loads(res.lstrip('cjs.search.jsonpCallback(').rstrip(");"))
#
#     results: list[Competition | Team] = []
#
#     for i in res['results']:
#         match i['participant_type_id']:
#             case 0:
#                 if mode == "team":
#                     continue
#
#                 if not (comp := bot.get_competition(i['id'])):
#                     comp = Competition(bot)
#                     comp.country = i['country_name']
#                     comp.id = i['id']
#                     comp.url = i['url']
#                     comp.logo_url = i['logo_url']
#                     name = i['title'].split(': ')
#                     try:
#                         name.pop(0)  # Discard COUNTRY
#                     except IndexError:
#                         pass
#                     comp.name = name[0]
#                     await comp.save_to_db()
#                 results.append(comp)
#
#             case 1:
#                 if mode == "comp":
#                     continue
#
#                 if not (team := bot.get_team(i['id'])):
#                     team = Team(bot)
#                     team.name = i['title']
#                     team.url = i['url']
#                     team.id = i['id']
#                     team.logo_url = i['logo_url']
#                     await team.save_to_db()
#                 results.append(team)
#             case _:
#                 continue
#
#     if not results:
#         return await interaction.client.error(interaction, f"Flashscore Search: No results found for {query}")
#
#     if len(results) == 1:
#         fsr = next(results)
#     else:
#         view = ObjectSelectView(interaction, [('🏆', str(i), i.link) for i in results], timeout=30)
#         await view.update()
#         await view.wait()
#         if view.value is None:
#             return None
#         fsr = results[view.value]
#
#     if not get_recent:
#         return fsr
#
#     if not (items := await fsr.results()):
#         return await interaction.client.error(interaction, f"No recent games found for {fsr.title}")
#
#     view = ObjectSelectView(interaction, objects=[("⚽", i.score_line, f"{i.competition}") for i in items])
#     await view.update()
#     await view.wait()
#
#     if view.value is None:
#         raise builtins.TimeoutError('Timed out waiting for you to select a recent game.')
#
#     return items[view.value]
#
