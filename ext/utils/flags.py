"""Flag emoji convertor"""
import logging
import unicodedata

from pycountry import countries

logger = logging.getLogger("flags")

# TODO: string.translate mapping instead of dict.
# Manual Country Code Flag dict
country_dict = {
    "American Virgin Islands": "vi",
    "Antigua and Barbuda": "ag",
    "Bolivia": "bo",
    "Bosnia-Herzegovina": "ba",
    "Bosnia and Herzegovina": "ba",
    "Botsuana": "bw",
    "British Virgin Islands": "vg",
    "Cape Verde": "cv",
    "Cayman-Inseln": "ky",
    "Chinese Taipei (Taiwan)": "tw",
    "Congo DR": "cd",
    "Curacao": "cw",
    "DR Congo": "cd",
    "Cote d'Ivoire": "ci",
    "CSSR": "cz",
    "Czech Republic": "cz",
    "East Timor": "tl",
    "Faroe Island": "fo",
    "Federated States of Micronesia": "fm",
    "Hongkong": "hk",
    "Iran": "ir",
    "Ivory Coast": "ci",
    "Korea, North": "kp",
    "Korea, South": "kr",
    "Kosovo": "xk",
    "Laos": "la",
    "Macedonia": "mk",
    "Mariana Islands": "mp",
    "Moldova": "md",
    "Netherlands Antilles": "nl",
    "Neukaledonien": "nc",
    "Northern Ireland": "gb",
    "Osttimor": "tl",
    "Palästina": "ps",
    "Palestine": "pa",
    "Republic of the Congo": "cd",
    "Rumänien": "ro",
    "Russia": "ru",
    "Sao Tome and Principe": "st",
    "Sao Tome and Princip": "st",
    "Sint Maarten": "sx",
    "Southern Sudan": "ss",
    "South Korea": "kr",
    "St. Kitts & Nevis": "kn",
    "St. Lucia": "lc",
    "St. Vincent & Grenadinen": "vc",
    "Syria": "sy",
    "Tahiti": "fp",
    "Tanzania": "tz",
    "The Gambia": "gm",
    "Trinidad and Tobago": "tt",
    "Turks- and Caicosinseln": "tc",
    "USA": "us",
    "Venezuela": "ve",
    "Vietnam": "vn",
}
backup_dict = {
    # UK Subflags
    "england": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "en": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "uk": "🇬🇧",
    # World
    "other": "🌍",
    "world": "🌍",
    # Language Code Hacky ISOs
    "cs": "🇨🇿",
    "da": "🇩🇰",
    "ja": "🇯🇵",
    "ko": "🇰🇷",
    "zh": "🇨🇳",
    # Transfer Market Misc
    "retired": "❌",
    "without club": "❌",
    "n/a": "❌",
    # Warships
    "commonwealth": "<:Commonwealth:991329664591212554>",
    "europe": "🇪🇺",
    "pan_america": "<:PanAmerica:991330048390991933>",
    "usa": "🇺🇸",
    "ussr": "<:USSR:991330483445186580>",
}


def to_indicators(inp: str) -> str:
    """Convert letters to regional indicators"""
    return "".join(unicodedata.lookup(f"REGIONAL INDICATOR {i}") for i in inp)


def get_flag(country: str | list[str]) -> str:
    """Get a flag emoji from a string representing a country"""

    if isinstance(country, str):
        country = [country]  # Make into list.

    output = []
    for country in [i.strip() for i in country]:

        if not country:
            continue

        # Try pycountry
        try:
            retrieved = countries.get(name=country).alpha_2
            output.append(to_indicators(retrieved))
            continue
        except (KeyError, AttributeError):
            try:
                retrieved = countries.lookup(country).alpha_2
                output.append(to_indicators(retrieved))
                continue
            except (AttributeError, LookupError):
                pass

        # Use manual fallbacks
        try:
            output.append(to_indicators(country_dict[country]))
            continue
        except KeyError:
            pass

        # Other.
        try:
            output.append(backup_dict[country.casefold()])
            continue
        except KeyError:
            logger.error("No country found for '%s'", country)
    return " ".join(output)
