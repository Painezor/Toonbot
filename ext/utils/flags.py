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
    "Vietnam": "vn",
}

UNI_DICT = {
    "a": "🇦",
    "b": "🇧",
    "c": "🇨",
    "d": "🇩",
    "e": "🇪",
    "f": "🇫",
    "g": "🇬",
    "h": "🇭",
    "i": "🇮",
    "j": "🇯",
    "k": "🇰",
    "l": "🇱",
    "m": "🇲",
    "n": "🇳",
    "o": "🇴",
    "p": "🇵",
    "q": "🇶",
    "r": "🇷",
    "s": "🇸",
    "t": "🇹",
    "u": "🇺",
    "v": "🇻",
    "w": "🇼",
    "x": "🇽",
    "y": "🇾",
    "z": "🇿",
}


def get_flag(country: str | list[str]) -> str:
    """Get a flag emoji from a string representing a country"""

    if isinstance(country, str):
        country = [country]

    output = []
    for c in country:
        for x in ["Retired", "Without Club"]:
            c = c.strip().replace(x, "")

        c = country_dict.get(c, c)

        match c.lower():
            case "england" | "en":
                output.append("🏴󠁧󠁢󠁥󠁮󠁧󠁿")
            case "scotland":
                output.append("🏴󠁧󠁢󠁳󠁣󠁴󠁿")
            case "wales":
                output.append("🏴󠁧󠁢󠁷󠁬󠁳󠁿")
            case "uk":
                output.append("🇬🇧")
            case "world":
                output.append("🌍")
            case "cs":
                output.append("🇨🇿")
            case "da":
                output.append("🇩🇰")
            case "ko":
                output.append("🇰🇷")
            case "zh":
                output.append("🇨🇳")
            case "ja":
                output.append("🇯🇵")
            case "usa":
                output.append("🇺🇸")
            case "pan_america":
                output.append("<:PanAmerica:991330048390991933>")
            case "commonwealth":
                output.append("<:Commonwealth:991329664591212554>")
            case "ussr":
                output.append("<:USSR:991330483445186580>")
            case "europe":
                output.append("🇪🇺")
            case "other":
                output.append("🌍")

        # Check if py country has country
        try:
            c = countries.get(name=c.title()).alpha_2
        except (KeyError, AttributeError):
            pass

        if len(c) != 2:
            logging.info(f"No flag country found for {c}")
            continue

        output.append("".join(UNI_DICT[i] for i in c.lower() if i))
    return " ".join(output)
