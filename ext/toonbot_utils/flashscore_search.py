"""The Flashscore Search Feature, with language controls."""
from typing import TYPE_CHECKING
from urllib.parse import quote

from discord import Locale

from ext.utils.view_utils import ObjectSelectView
from flashscore import Competition, Team

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


async def search(interaction: Interaction, query: str, mode: Literal['comp', 'team'], get_recent: bool = False) \
        -> Competition | Team | Message:
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

    # Type IDs: 1 - , 2 - , 3 - Player, 3 - ???, 4 - ???
    url = f"https://s.livesport.services/api/v2/search/?q={query}&lang-id={lang_id}&type-ids=1,2,3,4&sport-ids=1"

    async with bot.session.get(url) as resp:
        match resp.status:
            case 200:
                res = await resp.json()
            case _:
                raise ConnectionError(f"HTTP {resp.status} error in fs_search")

    # Un-fuck FS JSON reply.
    results: list[Competition | Team] = []
    for x in res:
        for t in x["participantTypes"]:
            match t["name"]:
                case "Player":
                    # This is a player, we don't want those.
                    continue
                case "National" | "Team":
                    if not (team := bot.get_team(x['id'])):
                        team = Team(bot)
                        team.name = x['name']
                        team.url = x['url']
                        team.id = x['id']
                        team.logo_url = x['images'][0]["path"]
                        team.gender = x['gender']['name']
                        await team.save_to_db()
                    results.append(team)
                case "TournamentTemplate":
                    if not (comp := bot.get_competition(x['id'])):
                        comp = Competition(bot)
                        comp.country = x['defaultCountry']['name']
                        comp.id = x['id']
                        comp.url = x['url']
                        comp.logo_url = x['images'][0]['path']
                        comp.name = x['name']
                        await comp.save_to_db()
                    results.append(comp)

    if not results:
        raise LookupError(f"Flashscore Search: No results found for {query}")

    if len(results) == 1:
        fsr = next(results)
    else:
        view = ObjectSelectView(interaction, [('🏆', str(i), i.link) for i in results], timeout=30)
        await view.update()
        await view.wait()
        if view.value is None:
            return None
        fsr = results[view.value]

    if not get_recent:
        return fsr

    if not (items := await fsr.results()):
        raise LookupError(f"No recent games found for {fsr.title}")

    view = ObjectSelectView(interaction, objects=[("⚽", i.score_line, f"{i.competition}") for i in items], timeout=30)
    await view.update(content=f'⏬ Please choose a recent game.')
    await view.wait()

    if view.value is None:
        raise TimeoutError('Timed out waiting for you to select a recent game.')

    return items[view.value]
