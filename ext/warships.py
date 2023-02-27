"""Private world of warships related commands"""
from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

from discord import Embed, ButtonStyle, Message, Colour
import discord
from discord.app_commands import (
    default_permissions,
    autocomplete,
    Choice,
    guilds,
    Range,
    Group,
)
from discord.ext.commands import Cog
from discord.ui import View, Button

from ext.painezbot_utils.clan import ClanBuilding, League, Leaderboard
from ext.painezbot_utils.player import Region, Map, GameMode, Player
from ext.painezbot_utils.ship import Nation, ShipType, Ship
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from painezBot import PBot
    from discord import Interaction

# TODO: Browse all Ships command. Filter Dropdowns.
# Dropdown to show specific ships.
# TODO: Clan Base Commands
# https://api.worldofwarships.eu/wows/clans/glossary/
# TODO: Recent command.
# https://api.worldofwarships.eu/wows/account/statsbydate/
# TODO: Refactor to take player stats from website instead.

logger = logging.getLogger("warships")

DISCORD = "https://media.discordapp.net/attachments/"

ASLAIN = (
    "https://aslain.com/index.php?/topic/2020-download-%E2%98%85-"
    "world-of-warships-%E2%98%85-modpack/"
)
HELP_ME_BUILDS = "http://wo.ws/builds"
HELP_ME_DISCORD = "https://discord.gg/c4vK9rM"
HELP_ME_LOGO = (
    DISCORD + "443846252019318804/992914761723433011/Logo_Discord2.png"
)
HOW_IT_WORKS = (
    "https://wowsp-wows-eu.wgcdn.co/dcont/fb/image/tmb/"
    "2f4c2e32-4315-11e8-84e0-ac162d8bc1e4_1200x.jpg"
)
# noinspection SpellCheckingInspection

MODSTATION = "https://worldofwarships.com/en/content/modstation/"
MOD_POLICY = "https://worldofwarships.com/en/news/general-news/mods-policy/"
OVERMATCH = DISCORD + "303154190362869761/990588535201484800/unknown.png"
# noinspection SpellCheckingInspection
RAGNAR = (
    "Ragnar is inherently underpowered. It lacks the necessary"
    "attributes to make meaningful impact on match result. No burst "
    "damage to speak of, split turrets, and yet still retains a fragile "
    "platform. I would take 1 Conqueror..Thunderer or 1 DM or even 1 of "
    "just about any CA over 2 Ragnars on my team any day of the week. "
    "Now... If WG gave it the specialized repair party of the "
    "Nestrashimy ( and 1 more base charge)... And maybe a few more "
    "thousand HP if could make up for where it is seriously lacking with"
    " longevity"
)

API_PATH = "https://api.worldofwarships.eu/wows/"
INFO = API_PATH + "encyclopedia/info/"
CLAN = API_PATH + "clans/glossary/"
CLAN_SEARCH = "https://api.worldofwarships.eu/wows/clans/list/"
MAPS = API_PATH + "encyclopedia/battlearenas/"
MODES = API_PATH + "encyclopedia/battletypes/"
SHIPS = API_PATH + "encyclopedia/ships/"
PLAYERS = API_PATH + "account/list/"

REGION = Literal["eu", "na", "cis", "sea"]

# TODO: Overmatch DD
OM_BB = {
    13: ["Tier 5 Superstructure"],
    16: [
        "Tier 5 Superstructure",
        "Tier 2-3 Bow/Stern",
        "Tier 3-7 British Battlecruiser Bow/Stern",
    ],
    19: [
        "Tier 5 Bow/Stern",
        "All Superstructure",
        "Tier 3-7 British Battlecruiser Bow/Stern",
    ],
    25: [
        "Tier 5 Bow/Stern",
        "All Superstructure",
        (
            "Florida, Mackensen, Prinz Heinrich, Borodino\n"
            "Constellation, Slava Bow/Stern"
        ),
        "All UK BattleCruiser Bow/Stern",
    ],
    26: [
        "Tier 7 Bow/Stern",
        "All Superstructure",
        "Florida/Borodino/Constellation/Slava Bow/Stern",
        "UK BattleCruiser Bow/Stern",
    ],
    27: [
        "Tier 7 Bow/Stern",
        "All Superstructure",
        "Borodino/Constellation/Slava Bow/Stern",
        "UK BattleCruiser Bow/Stern",
        "German Battlecruiser Upper Bow/Stern",
    ],
    32: [
        "All Bow/Stern except German/Kremlin/Italian Icebreaker",
        "French/British Casemates",
        "Slava Deck",
    ],
}

OM_CA = {
    6: ["Tier 3 Plating"],
    10: ["Tier 3 Plating", "Tier 5 Superstructure"],
    13: [
        "Tier 5 Plating",
        "Tier 7 Most Superstructures",
        "Tier 7 Super light (127mms) plating",
    ],
    16: [
        "Tier 5 Plating",
        "Tier 7 Superstructure",
        "Tier 7 Bow/Stern (Except Pensacola/New Orleans/Yorck)",
        r"Tier \⭐ British CL/Smolensk plating",
        "127mm and below equipped super lights",
        "",
    ],
    19: [
        "Tier 7 CL Side plating",
        "All Superstructure",
        "Tier 7 Bow/Stern (Except Pensacola/New Orleans/Yorck). ",
        r"Tier \⭐ British CL/Smolensk plating",
        "127mm super lights plating",
    ],
    25: [
        "Tier 7 everywhere",
        "Tier 10 CL side plating",
        r"Tier \⭐ bow/stern (except US & German Heavy, and icebreakers)",
        r"Tier \⭐ British CL/Smolensk plating",
    ],
    27: [
        "Tier 9 decks",
        r"Tier \⭐ bow/stern",
        r"Tier \⭐ British CL/Smolensk plating",
    ],
    30: [r"Tier \⭐ Decks", r"Tier \⭐ bow/stern", r"Tier \⭐ plating"],
    32: [
        r"Tier \⭐ Decks",
        r"Tier \⭐ bow/stern",
        r"Tier \⭐ plating",
        "Austin/Jinan Casemate",
    ],
    35: [
        r"Tier \⭐ Decks",
        r"Tier \⭐ bow/stern",
        r"Tier \⭐ plating",
        "Austin/Jinan Casemate",
        "Riga Deck",
    ],
}


# TODO: Calculation of player's PR
# https://wows-numbers.com/personal/rating


# Autocomplete.
async def map_ac(
    interaction: Interaction[PBot], current: str
) -> list[Choice[int]]:
    """Autocomplete for the list of maps in World of Warships"""
    # Run Once
    bot = interaction.client
    if not bot.maps:
        p = {"application_id": bot.wg_id, "language": "en"}
        async with bot.session.get(MAPS, params=p) as resp:
            match resp.status:
                case 200:
                    items = await resp.json()
                case _:
                    raise ConnectionError(
                        f"{resp.status} Error accessing {MAPS}"
                    )

        maps = []

        _maps = items["data"]
        for k, v in _maps.items():
            name = v["name"]
            description = v["description"]
            icon = v["icon"]
            map_id = k
            maps.append(Map(name, description, map_id, icon))

        bot.maps = maps

    filtered = sorted(
        [i for i in bot.maps if current.lower() in i.ac_match.lower()],
        key=lambda x: x.name,
    )
    return [
        Choice(name=i.ac_row[:100], value=i.battle_arena_id) for i in filtered
    ][:25]


async def mode_ac(ctx: Interaction[PBot], cur: str) -> list[Choice[str]]:
    """Fetch a Game Mode"""
    choices = []
    for i in ctx.client.modes:
        if i.tag not in ["PVE_PREMADE", "EVENT", "BRAWL"]:
            continue
        if cur.lower() not in i.name.lower():
            continue
        choices.append(Choice(name=i.name, value=i.tag))
    return choices[:25]


async def player_ac(
    interaction: Interaction[PBot], current: str
) -> list[Choice[str]]:
    """Fetch player's account ID by searching for their name."""
    bot: PBot = interaction.client
    p = {"application_id": bot.wg_id, "search": current, "limit": 25}

    region = getattr(interaction.namespace, "region", None)
    region = next((i for i in Region if i.db_key == region), Region.EU)

    link = PLAYERS.replace("eu", region.domain)
    async with bot.session.get(link, params=p) as resp:
        match resp.status:
            case 200:
                players = await resp.json()
            case _:
                return []

    data = players.pop("data", None)
    if data is None:
        return []

    choices = []
    for i in data:
        player = bot.get_player(i["account_id"])
        player.nickname = i["nickname"]

        if player.clan is None:
            choices.append(
                Choice(name=player.nickname, value=str(player.account_id))
            )
        else:
            choices.append(
                Choice(
                    name=f"[{player.clan.tag}] {player.nickname}",
                    value=str(player.account_id),
                )
            )
    return choices


async def clan_ac(
    interaction: Interaction[PBot], current: str
) -> list[Choice[str]]:
    """Autocomplete for a list of clan names"""
    bot: PBot = interaction.client

    region = getattr(interaction.namespace, "region", None)
    region = next((i for i in Region if i.db_key == region), Region.EU)

    link = CLAN_SEARCH.replace("eu", region.domain)
    p = {"search": current, "limit": 25, "application_id": bot.wg_id}

    async with bot.session.get(link, params=p) as resp:
        match resp.status:
            case 200:
                clans = await resp.json()
            case _:
                return []

    choices = []
    for i in clans.pop("data", []):
        clan = interaction.client.get_clan(i["clan_id"])
        clan.tag = i["tag"]
        clan.name = i["name"]
        choices.append(
            Choice(name=f"[{clan.tag}] {clan.name}", value=str(clan.clan_id))
        )
    return choices


async def ship_ac(ctx: Interaction[PBot], cur: str) -> list[Choice[str]]:
    """Autocomplete for the list of maps in World of Warships"""
    options = []
    for i in sorted(ctx.client.ships, key=lambda s: s.name):
        if cur.lower() in i.ac_row.lower() and i.ship_id_str:
            options.append(Choice(name=i.ac_row[:100], value=i.ship_id_str))

    return options[:25]


class Warships(Cog):
    """World of Warships related commands"""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

        # override our custom classes.
        Player.bot = bot

    async def cog_load(self) -> None:
        """Fetch Generics from API and store to bot."""
        p = {"application_id": self.bot.wg_id, "language": "en"}
        if not self.bot.ship_types:
            async with self.bot.session.get(INFO, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        err = f"{resp.status} fetching ship type data {INFO}"
                        raise ConnectionError(err)

            for k, v in data["data"]["ship_types"].items():
                images = data["data"]["ship_type_images"][k]
                s_t = ShipType(k, v, images)
                self.bot.ship_types.append(s_t)

        if not self.bot.modes:
            async with self.bot.session.get(MODES, params=p) as resp:
                match resp.status:
                    case 200:
                        data = await resp.json()
                    case _:
                        return

            for k, v in data["data"].items():
                self.bot.modes.append(GameMode(**v))

        if not self.bot.ships:
            self.bot.ships = await self.cache_ships()

        # if not self.bot.clan_buildings:
        #     self.bot.clan_buildings = await self.cache_clan_base()

    async def cache_clan_base(self) -> list[ClanBuilding]:
        """Cache the CLan Buildings from the API"""
        raise NotImplementedError  # TODO: Cache Clan Base
        # buildings = json.pop()
        # output = []
        # for i in buildings:
        #
        # self.building_id: int = building_id
        # self.building_type_id: int = kwargs.pop('building_type_id', None)
        # self.bonus_type: Optional[str] = kwargs.pop('bonus_type', None)
        # self.bonus_value: Optional[int] = kwargs.pop('bonus_value', None)
        # self.cost: Optional[int] = kwargs.pop('cost', None)  # Price in Oil
        # self.max_members: Optional[int] = kwargs.pop('max_members', None)
        #
        # max_members = buildings.pop()
        #
        # b = ClanBuilding()

    async def cache_ships(self) -> list[Ship]:
        """Cache the ships from the API."""
        # Run Once.
        if self.bot.ships:
            return self.bot.ships

        max_iter: int = 1
        count: int = 1
        ships: list[Ship] = []
        while count <= max_iter:
            # Initial Pull.
            p = {
                "application_id": self.bot.wg_id,
                "language": "en",
                "page_no": count,
            }
            async with self.bot.session.get(SHIPS, params=p) as resp:
                match resp.status:
                    case 200:
                        items = await resp.json()
                        count += 1
                    case _:
                        raise ConnectionError(
                            f"{resp.status} Error accessing {SHIPS}"
                        )

            max_iter = items["meta"]["page_total"]

            for ship, data in items["data"].items():
                ship = Ship(self.bot)

                nation = data.pop("nation", None)
                if nation:
                    ship.nation = next(i for i in Nation if nation == i.match)

                ship.type = self.bot.get_ship_type(data.pop("type"))

                modules = data.pop("modules")
                ship._modules = modules
                for k, v in data.items():
                    setattr(ship, k, v)
                ships.append(ship)
        return ships

    async def send_code(
        self,
        interaction: Interaction[PBot],
        code: str,
        regions: list[str],
        contents: str,
    ) -> Message:
        """Generate the Embed for the code."""
        e = Embed(
            title=code,
            url=f"https://eu.wargaming.net/shop/redeem/?bonus_mode={code}",
            colour=Colour.red(),
        )
        e.set_author(
            name="Bonus Code",
            icon_url=(
                "https://cdn.iconscout.com/icon/"
                "free/png-256/wargaming-1-283119.png"
            ),
        )
        e.set_thumbnail(
            url="https://wg-art.com/media/filer_public_thumbnails"
            "/filer_public/72/22/72227d3e-d42f-4e16-a3e9-012eb239214c/"
            "wg_wows_logo_mainversion_tm_fullcolor_ru_previewwebguide.png"
        )
        if contents:
            e.add_field(name="Contents", value=f"```yaml\n{contents}```")
        e.set_footer(text="Click on a button below to redeem for your region")

        view = View()
        for i in regions:
            region = next(r for r in Region if i == r.db_key)

            dom = region.code_prefix
            url = f"https://{dom}.wargaming.net/shop/redeem/?bonus_mode={code}"
            view.add_item(
                Button(
                    url=url,
                    label=region.name,
                    style=ButtonStyle.url,
                    emoji=region.emote,
                )
            )
        return await self.bot.reply(interaction, embed=e, view=view)

    @discord.app_commands.command()
    async def ragnar(self, interaction: Interaction) -> Message:
        """Ragnar is inherently underpowered"""
        return await self.bot.reply(interaction, content=RAGNAR)

    @discord.app_commands.command()
    async def armory(self, interaction: Interaction) -> Message:
        """Get a link to the web version of the in-game Armory"""
        e = Embed(
            title="World of Warships Armory",
            description="Access the armory for each region below",
        )
        e.set_thumbnail(
            url=(
                "https://wows-static-production.gcdn.co/"
                "metashop/898c4bc5/armory.png"
            )
        )
        e.colour = Colour.orange()

        v = View()
        for region in Region:
            v.add_item(
                Button(
                    style=ButtonStyle.url,
                    url=region.armory,
                    emoji=region.emote,
                    label=region.name,
                )
            )
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def inventory(self, interaction: Interaction) -> Message:
        """Get a link to the web version of the in-game Inventory"""
        e = Embed(
            title="World of Warships Inventory",
            colour=Colour.lighter_gray(),
            description="Manage & sell your unused modules/camos/etc below",
        )
        e.set_thumbnail(
            url=DISCORD + "303154190362869761/991811092437274655/unknown.png"
        )

        v = View()
        for region in Region:
            v.add_item(
                Button(
                    style=ButtonStyle.url,
                    url=region.inventory,
                    emoji=region.emote,
                    label=region.name,
                )
            )
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def logbook(self, interaction: Interaction) -> Message:
        """Get a link to the web version of the in-game Captain's Logbook"""
        e = Embed(
            title="World of Warships Captain's Logbook",
            description="Access your region's logbook below.",
        )

        img = DISCORD + "303154190362869761/991811398952816790/unknown.png"
        e.set_thumbnail(url=img)
        e.colour = Colour.dark_orange()

        v = View()
        for region in Region:
            v.add_item(
                Button(
                    style=ButtonStyle.url,
                    url=region.logbook,
                    emoji=region.emote,
                    label=region.name,
                )
            )
        return await self.bot.reply(interaction, embed=e, view=v)

    # TODO: Make this into a view.
    @discord.app_commands.command()
    async def how_it_works(self, interaction: Interaction) -> None:
        """Links to the various How It Works videos"""
        e = Embed(title="How it Works Video Series", colour=Colour.dark_red())
        e.description = (
            "The how it works video series give comprehensive overviews of "
            "some of the game's mechanics, you can find links to them all "
            "below\n\n**Latest Video**: "
            "[In-Game Mechanics](https://youtu.be/hFfBqjqQ-S8)\n\n"
            + ", ".join(
                [
                    "[AA Guns & Fighters](https://youtu.be/Dvrwz-1XhnM)",
                    "[Armour](https://youtu.be/yQcutrneBJQ)",
                    "[Ballistics](https://youtu.be/02pb8VS_mFo)",
                    "[Carrier Gameplay](https://youtu.be/qjyQVM2sGAo)",
                    "[Consumables](https://youtu.be/4XF44GsF2v4)",
                    "[Credits & XP Modifiers](https://youtu.be/KcRF3wNgzRk)",
                    "[Dispersion](https://youtu.be/AitjEbwtdUs)",
                    "[Economy](https://youtu.be/0_bXHAqLkKc)",
                    "[Expenses](https://youtu.be/v6lZE5XBMj0)",
                    "[Fire](https://youtu.be/AGEHZQsYzGE)",
                    "[Flooding](https://youtu.be/SCHNDox0BRM)",
                    "[Game Basics](https://youtu.be/Zl-lWGugzEo)",
                    "[HE Shells](https://youtu.be/B5GzyXj6oPM)",
                    "[Hit Points](https://youtu.be/Iusj8WJx5PQ)",
                    "[Modules](https://youtu.be/Z2JuRf-pnxY)",
                    "[Repair Party](https://youtu.be/mG1iSVIqmC4)",
                    "[SAP Shells](https://youtu.be/zZzlivBoP8s)",
                    "[Spotting](https://youtu.be/OgRUSmzcw2s)",
                    "[Tips & Tricks](https://youtu.be/tD9jaMrrY3I)",
                    "[Torpedoes](https://youtu.be/LPTgi20O15Q)",
                    "[Upgrades](https://youtu.be/zqwa9ZlzMA8)",
                ]
            )
        )
        e.set_thumbnail(url=HOW_IT_WORKS)
        await self.bot.reply(interaction, embed=e)

    @discord.app_commands.command()
    @discord.app_commands.describe(
        code="Enter the code", contents="Enter the reward the code gives"
    )
    @default_permissions(manage_messages=True)
    async def code(
        self,
        interaction: Interaction[PBot],
        code: str,
        contents: str,
        eu: bool = True,
        na: bool = True,
        asia: bool = True,
    ) -> Message:
        """Send a message with region specific redeem buttons"""

        await interaction.response.defer(thinking=True)

        regions = []
        if eu:
            regions.append("eu")
        if na:
            regions.append("na")
        if asia:
            regions.append("sea")
        return await self.send_code(interaction, code, regions, contents)

    @discord.app_commands.command()
    @discord.app_commands.describe(
        code="Enter the code", contents="Enter the reward the code gives"
    )
    @default_permissions(manage_messages=True)
    async def code_cis(
        self, interaction: Interaction[PBot], code: str, contents: str
    ) -> Message:
        """Send a message with a region specific redeem button"""

        await interaction.response.defer(thinking=True)
        return await self.send_code(
            interaction, code, regions=["cis"], contents=contents
        )

    @discord.app_commands.command()
    @discord.app_commands.describe(code_list="Enter a list of codes")
    async def code_parser(
        self, interaction: Interaction[PBot], code_list: str
    ) -> Message:
        """Strip codes for world of warships CCs"""
        code_list = code_list.replace(";", "")
        codes = code_list.split("|")
        codes = "\n".join([i.strip() for i in codes if i])
        return await self.bot.reply(
            interaction, content=f"```\n{codes}```", ephemeral=True
        )

    @discord.app_commands.command()
    @discord.app_commands.autocomplete(name=map_ac)
    @discord.app_commands.describe(name="Search for a map by name")
    async def map(self, interaction: Interaction[PBot], name: str) -> Message:
        """Fetch a map from the world of warships API"""

        await interaction.response.defer(thinking=True)

        if not self.bot.maps:
            raise ConnectionError("Unable to fetch maps from API")

        try:
            map_ = next(i for i in self.bot.maps if i.battle_arena_id == name)
        except StopIteration:
            err = f"Did not find map matching {name}, sorry."
            return await self.bot.error(interaction, err)

        return await self.bot.reply(interaction, embed=map_.embed)

    @discord.app_commands.command()
    async def mods(self, interaction: Interaction) -> Message:
        """information about where to get World of Warships modifications"""
        e = Embed(colour=Colour.red())
        e.set_thumbnail(url="http://i.imgur.com/2LiednG.jpg")
        e.title = "World of Warships Mods"
        e.description = (
            "There are two official sources available for in-game"
            f"modifications.\n • [Modstation]({MODSTATION})\n"
            f"• Official Forum\n\n [Aslain's Modpack]({ASLAIN}) "
            "is a popular third party compilation of mods"
            " available from the official forum\n"
        )
        e.add_field(name="Mod Policy", value=MOD_POLICY)
        v = View()
        v.add_item(Button(url=MODSTATION, label="Modstation"))
        v.add_item(Button(url=ASLAIN, label="Aslain's Modpack"))
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def builds(self, interaction: Interaction) -> Message:
        """The Help Me Build collection"""
        e = Embed(title="Help Me Builds", colour=0xAE8A6D)
        e.description = (
            f"The folks from the [Help Me Discord]({HELP_ME_DISCORD})"
            " have compiled a list of recommended builds, you can find"
            " them, [here]({HELP_ME_BUILDS}) or by using the button below."
        )
        e.set_thumbnail(url=HELP_ME_LOGO)
        v = View()
        v.add_item(
            Button(url=HELP_ME_BUILDS, label="Help Me Builds on Google Docs")
        )
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def help_me(self, interaction: Interaction) -> Message:
        """Help me Discord info"""
        e = Embed(title="Help Me Discord", colour=0xAE8A6D)
        e.description = (
            f"The [Help Me Discord]({HELP_ME_DISCORD}) is full of helpful "
            "players from top level clans who donate their time to give "
            "advice and replay analysis to those in need of it. \nYou can"
            " join by clicking [here](http://wo.ws/builds) or by using "
            "the button below."
        )
        e.set_thumbnail(url=HELP_ME_LOGO)
        v = View()
        v.add_item(Button(url=HELP_ME_DISCORD, label="Help Me Discord"))
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    async def guides(self, interaction: Interaction) -> Message:
        """Yurra's collection of guides"""
        txt = (
            "Yurra's guides contain advice on various game mechanics, play "
            "styles classes, tech tree branches, and some specific ships."
            "\n\nhttps://bit.ly/yurraguides"
        )
        e = Embed(title="Yurra's guides", description=txt)
        e.url = "https://bit.ly/yurraguides"

        yurra = self.bot.get_user(192601340244000769)
        if yurra:
            e.set_author(name=f"{yurra}", icon_url=yurra.display_avatar.url)
        e.colour = Colour.dark_orange()

        v = View()

        btn = discord.ui.Button(
            style=discord.ButtonStyle.url,
            url="https://bit.ly/yurraguides",
            label="Yurra's guides",
        )
        v.add_item(btn)
        return await self.bot.reply(interaction, embed=e, view=v)

    @discord.app_commands.command()
    @discord.app_commands.autocomplete(name=ship_ac)
    @discord.app_commands.describe(name="Search for a ship by it's name")
    async def ship(self, interaction: Interaction[PBot], name: str) -> Message:
        """Search for a ship in the World of Warships API"""

        await interaction.response.defer()

        if not self.bot.ships:
            raise ConnectionError("Unable to fetch ships from API")

        if (ship := self.bot.get_ship(name)) is None:
            raise LookupError(f"Did not find map matching {name}, sorry.")

        return await ship.view(interaction).overview()

    # TODO: Test - Clan Battles
    @discord.app_commands.command()
    @discord.app_commands.autocomplete(
        player_name=player_ac, mode=mode_ac, ship=ship_ac
    )
    @guilds(250252535699341312)
    @discord.app_commands.describe(
        player_name="Search for a player name",
        region="Which region is this player on",
        mode="battle mode type",
        division="1 = solo, 2 = 2man, 3 = 3man, 0 = Overall",
        ship="Get statistics for a specific ship",
    )
    async def stats(
        self,
        interaction: Interaction[PBot],
        region: REGION,
        player_name: Range[str, 3],
        mode: str = "PVP",
        division: Range[int, 0, 3] = 0,
        ship: Optional[str] = None,
    ) -> Message:
        """Search for a player's Stats"""
        _ = region  # Shut up linter.

        await interaction.response.defer(thinking=True)
        player = self.bot.get_player(int(player_name))
        g_mode = next(i for i in self.bot.modes if i.tag == mode)
        if ship:
            g_ship = self.bot.get_ship(ship)
        else:
            g_ship = None
        v = player.view(interaction, g_mode, division, g_ship)
        return await v.mode_stats(g_mode)

    overmatch = Group(
        name="overmatch",
        description="Get information about shell/armour overmatch",
    )

    @overmatch.command()
    @discord.app_commands.describe(
        shell_calibre="Calibre of shell to get over match value of"
    )
    async def calibre(
        self, interaction: Interaction[PBot], shell_calibre: int
    ) -> Message:
        """Get information about what a shell's overmatch parameters"""

        await interaction.response.defer(thinking=True)
        value = round(shell_calibre / 14.3)
        e = Embed(
            title=f"{shell_calibre}mm Shells overmatch {value}mm of Armour",
            colour=0x0BCDFB,
        )
        e.add_field(
            name="Cruisers",
            value="\n".join(OM_CA[max(i for i in OM_CA if i <= value)]),
            inline=False,
        )
        e.add_field(
            name="Battleships",
            value="\n".join(OM_BB[max(i for i in OM_BB if i <= value)]),
            inline=False,
        )
        e.set_thumbnail(url=OVERMATCH)
        e.set_footer(text=f"{shell_calibre}mm / 14.3 = {value}mm")
        return await self.bot.reply(interaction, embed=e)

    @overmatch.command()
    @discord.app_commands.describe(
        armour_thickness="How thick is the armour you need to penetrate"
    )
    async def armour(
        self, interaction: Interaction[PBot], armour_thickness: int
    ) -> Message:
        """Get what gun size is required to overmatch an armour thickness"""
        r = armour_thickness
        value = round(armour_thickness * 14.3)
        e = Embed(
            title=f"{r}mm of Armour is overmatched by {value}mm Guns",
            colour=0x0BCDFB,
        )
        e.add_field(
            name="Cruisers",
            value="\n".join(
                OM_CA[max(i for i in OM_CA if i <= armour_thickness)]
            ),
            inline=False,
        )
        e.add_field(
            name="Battleships",
            value="\n".join(
                OM_BB[max(i for i in OM_BB if i <= armour_thickness)]
            ),
            inline=False,
        )
        e.set_thumbnail(url=OVERMATCH)
        e.set_footer(text=f"{value}mm * 14.3 = {value}mm")
        return await self.bot.reply(interaction, embed=e)

    clan = Group(name="clan", description="Get Clans")

    @clan.command()
    @discord.app_commands.describe(
        query="Clan Name or Tag", region="Which region is this clan from"
    )
    @discord.app_commands.autocomplete(query=clan_ac)
    async def search(
        self,
        interaction: Interaction[PBot],
        region: REGION,
        query: Range[str, 2],
    ) -> Message:
        """Get information about a World of Warships clan"""
        _ = region  # Just to shut the linter up.

        await interaction.response.defer(thinking=True)
        clan = self.bot.get_clan(int(query))
        await clan.get_data()
        return await clan.view(interaction).overview()

    @clan.command()
    @discord.app_commands.describe(
        region="Get only winners for a specific region"
    )
    async def winners(
        self, interaction: Interaction[PBot], region: Optional[REGION] = None
    ) -> Message:
        """Get a list of all past Clan Battle Season Winners"""

        await interaction.response.defer(thinking=True)

        async with self.bot.session.get(
            "https://clans.worldofwarships.eu/api/ladder/winners/"
        ) as resp:
            match resp.status:
                case 200:
                    winners = await resp.json()
                case _:
                    err = f"{resp.status} error accessing Hall of Fame"
                    raise ConnectionError(err)

        seasons = winners.pop("winners")
        if region is None:
            rows = []

            s = seasons.items()
            tuples = sorted(s, key=lambda x: int(x[0]), reverse=True)

            rat = "public_rating"
            for season, winners in tuples:
                wnr = [f"\n**Season {season}**"]

                srt = sorted(winners, key=lambda c: c[rat], reverse=True)
                for clan in srt:
                    tag = "realm"
                    rgn = next(i for i in Region if i.realm == clan[tag])
                    wnr.append(
                        f"{rgn.emote} `{str(clan[rat]).rjust(4)}`"
                        f" **[{clan['tag']}]** {clan['name']}"
                    )
                rows.append("\n".join(wnr))

            e = Embed(
                title="Clan Battle Season Winners", colour=Colour.purple()
            )
            return await Paginator(
                interaction, rows_to_embeds(e, rows, rows=1)
            ).update()
        else:
            rgn = next(i for i in Region if i.db_key == region)
            rows = []
            for season, winners in sorted(
                seasons.items(), key=lambda x: int(x[0]), reverse=True
            ):
                for clan in winners:
                    if clan["realm"] != rgn.realm:
                        continue
                    rows.append(
                        f"`{str(season).rjust(2)}.` **[{clan['tag']}]**"
                        f"{clan['name']} (`{clan['public_rating']}`)"
                    )

            e = Embed(
                title="Clan Battle Season Winners", colour=Colour.purple()
            )
            return await Paginator(
                interaction, rows_to_embeds(e, rows, rows=25)
            ).update()

    @clan.command()
    @discord.app_commands.describe(region="Get Rankings for a specific region")
    async def leaderboard(
        self,
        interaction: Interaction[PBot],
        region: Optional[REGION] = None,
        season: Range[int, 1, 20] = 20,
    ) -> Message:
        """Get the Season Clan Battle Leaderboard"""
        url = "https://clans.worldofwarships.eu/api/ladder/structure/"
        p = {  # league: int, 0 = Hurricane.
            # division: int, 1-3
            "realm": "global"
        }

        if season is not None:
            p.update({"season": str(season)})

        if region is not None:
            rgn = next(i for i in Region if i.db_key == region)
            p.update({"realm": rgn.realm})

        async with self.bot.session.get(url, params=p) as resp:
            match resp.status:
                case 200:
                    json = await resp.json()
                case _:
                    raise ConnectionError(
                        f"Error {resp.status} connecting to {resp.url}"
                    )

        clans = []
        for c in json:
            clan = deepcopy(self.bot.get_clan(c["id"]))

            clan.tag = c["tag"]
            clan.name = c["name"]
            clan.league = next(i for i in League if i.value == c["league"])
            clan.public_rating = c["public_rating"]
            ts = datetime.strptime(c["last_battle_at"], "%Y-%m-%d %H:%M:%S%z")
            clan.last_battle_at = Timestamp(ts)
            clan.is_clan_disbanded = c["disbanded"]
            clan.battles_count = c["battles_count"]
            clan.leading_team_number = c["leading_team_number"]
            clan.season_number = 17 if season is None else season
            clan.rank = c["rank"]

            clans.append(clan)

        return await Leaderboard(interaction, clans).update()


async def setup(bot: PBot):
    """Load the Warships Cog into the bot"""
    await bot.add_cog(Warships(bot))
