"""Flag emoji convertor"""
import logging

from pycountry import countries

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
    "N/A": "x",
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
    "Vietnam": "vn"}

UNI_DICT = {
    "a": "🇦", "b": "🇧", "c": "🇨", "d": "🇩", "e": "🇪",
    "f": "🇫", "g": "🇬", "h": "🇭", "i": "🇮", "j": "🇯",
    "k": "🇰", "l": "🇱", "m": "🇲", "n": "🇳", "o": "🇴",
    "p": "🇵", "q": "🇶", "r": "🇷", "s": "🇸", "t": "🇹",
    "u": "🇺", "v": "🇻", "w": "🇼", "x": "🇽", "y": "🇾", "z": "🇿"
}


def get_flag(country: str) -> str | None:
    """Get a flag emoji from a string representing a country"""
    for x in ['Retired', 'Without Club']:
        country = country.strip().replace(x, '')

    if not country.strip():
        return ''

    if (country := country.strip()) in country_dict:
        country = country_dict.get(country)

    match country.lower():
        case "england" | 'en':
            return '🏴󠁧󠁢󠁥󠁮󠁧󠁿'
        case "scotland":
            return '🏴󠁧󠁢󠁳󠁣󠁴󠁿'
        case "wales":
            return '🏴󠁧󠁢󠁷󠁬󠁳󠁿'
        case 'uk':
            return '🇬🇧'
        case "world":
            return '🌍'
        case 'cs':
            return '🇨🇿'
        case 'da':
            return '🇩🇰'
        case 'ko':
            return '🇰🇷'
        case 'zh':
            return '🇨🇳'
        case 'ja':
            return '🇯🇵'
        case 'usa':
            return '🇺🇸'
        case 'pan_america':
            return "<:PanAmerica:991330048390991933>"
        case "commonwealth":
            return "<:Commonwealth:991329664591212554>"
        case "ussr":
            return "<:USSR:991330483445186580>"
        case 'europe':
            return "🇪🇺"
        case "other":
            return '🌍'

    # Check if py country has country
    try:
        country = countries.get(name=country.title()).alpha_2
    except (KeyError, AttributeError):
        pass

    if len(country) != 2:
        logging.info(f'No flag country found for {country}')
        return ''

    return ''.join(UNI_DICT[c] for c in country.lower() if c)
