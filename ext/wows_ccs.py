from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias, Literal

import discord
from discord.ext import commands
from iso639 import Lang  # type: ignore

from ext.wows_api import Region
from ext.utils import flags, embed_utils, view_utils

if TYPE_CHECKING:
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[PBot]


CCS = "https://wows-static-content.gcdn.co/cms-data/contributors_wg.json"
CC_BADGE = "https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png"
PROGRAM_INFO = "https://worldofwarships.eu/en/content/contributors-program/"
REGIONS = Literal["eu", "na", "cis", "sea"]


# TODO: Autocompletes to transformers
class Contributor:
    """An Object representing a World of Warships CC"""

    def __init__(
        self,
        name: str,
        links: list[str],
        language: list[str],
        region: Region,
    ):
        self.name: str = name
        self.links: list[str] = links
        self.languages: list[str] = language
        self.region: Region = region

    @property
    def language_names(self) -> list[str]:
        """Get the name of each language"""
        return [Lang(lang).name for lang in self.languages]

    @property
    def markdown(self) -> str:
        """Return bulletpoint list of socials"""
        return "\n".join(f"• {i}" for i in self.links)

    @property
    def flag(self) -> list[str]:
        """Return a flag emoji for each of a CC's languages"""
        return flags.get_flags(self.languages)

    @property
    def row(self) -> str:
        """Return a short row representing all of a CC's social media info"""
        emote = self.region.emote
        return f"{emote} {self.name} ({self.flag})\n{self.markdown}"

    @property
    def auto_complete(self) -> str:
        """String to search for to identify this CC"""
        return f"{self.name} {self.markdown}".casefold()


async def language_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Filter by Language"""

    cog = interaction.client.get_cog(CommunityContributors.__qualname__)
    if not isinstance(cog, CommunityContributors):
        return []
    ccs = cog.contributors

    langs = set(a for b in [y.language_names for y in ccs] for a in b)

    cur = current.casefold()

    choices: list[discord.app_commands.Choice[str]] = []
    for i in langs:
        if cur not in i.casefold():
            continue

        choices.append(discord.app_commands.Choice(name=i, value=i))

        if len(choices) == 25:
            break

    return choices


async def cc_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete from the list of stored CCs"""
    cog = interaction.client.get_cog(CommunityContributors.__qualname__)
    if not isinstance(cog, CommunityContributors):
        return []
    ccs = cog.contributors

    # Region Filtering
    if region := interaction.namespace.region:
        ccs = [i for i in ccs if i.region.name.lower() == region]

    ccs.sort(key=lambda x: x.name)
    cur = current.casefold()

    choices: list[discord.app_commands.Choice[str]] = []
    for i in ccs:
        if cur not in i.auto_complete:
            continue

        name = f"{i.name} ({i.region.name})"[:100]
        value = i.name
        choice = discord.app_commands.Choice(name=name, value=value)

        choices.append(choice)
        if len(choices) == 25:
            break

    return choices


class CommunityContributors(commands.Cog):
    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        self.contributors: list[Contributor] = []

    async def cog_load(self) -> None:
        """On cog load, generate list of Tracker Channels"""
        await self.fetch_ccs()

    async def fetch_ccs(self) -> list[Contributor]:
        """Fetch details about all World of Warships CCs"""
        async with self.bot.session.get(CCS) as resp:
            if resp.status != 200:
                raise ConnectionError(f"Failed to connect to {CCS}")
            ccs = await resp.json()

        self.contributors.clear()

        for i in ccs:
            realm = {
                "ASIA": Region.SEA,
                "NA": Region.NA,
                "EU": Region.EU,
            }[i["realm"]]

            i = Contributor(i["name"], i["links"], i["lang"].split(","), realm)

            self.contributors.append(i)
        return self.contributors

    async def make_cc_embed(self, cont: Contributor) -> discord.Embed:
        """Create an embed about the CC"""
        embed = discord.Embed(title=f"{cont.name} ({cont.region.name})")
        embed.description = cont.markdown
        embed.colour = cont.region.colour
        embed.set_author(name="World of Warships Community Contributor")
        embed.set_thumbnail(url=CC_BADGE)

        # try:
        #     twitch = next(i for i in cont.links if "twitch" in i)
        #     twitch_id = twitch.split("/")[-1]
        #     user = await self.twitch.fetch_users(names=[twitch_id])
        #     user = user[0]
        #     embed.set_image(url=user.profile_image)

        #     # TODO: Fetch Twitch Info into Embed
        #     # TODO: Official channel Schedule
        # https://dev.twitch.tv/docs/api/reference#get-channel-stream-schedule
        # https://dev.twitch.tv/docs/api/reference#get-channel-emotes
        #     print(dir(user))
        # except StopIteration:
        #     pass

        # TODO: Pull other website data where possible.
        return embed

    @discord.app_commands.command()
    @discord.app_commands.describe(
        search="search by name (e.g.: painezor, yuzorah), "
        "or website name (ex: twitch, dailybounce)",
        region="Filter by region",
        language="Filter by language",
    )
    @discord.app_commands.autocomplete(search=cc_ac, language=language_ac)
    async def contributor(
        self,
        interaction: Interaction,
        search: str | None = None,
        region: REGIONS | None = None,
        language: str | None = None,
    ) -> None:
        """Fetch The List of all CCs"""
        ccs = self.contributors

        if search is not None:
            ccs = [i for i in ccs if search == i.name]
            if len(ccs) == 1:  # Send an individual Profile
                embed = await self.make_cc_embed(ccs[0])
                return await interaction.response.send_message(embed=embed)

        if search is not None:
            ccs = [i for i in ccs if search in i.auto_complete]

        if region is not None:
            ccs = [i for i in ccs if i.region.value == region]

        if language is not None:
            ccs = [i for i in ccs if language in i.language_names]

        embed = discord.Embed(title="World of Warships Community Contributors")
        embed.url = PROGRAM_INFO
        embed.set_thumbnail(
            url="https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png"
        )
        embed.colour = discord.Colour.dark_blue()

        embeds = embed_utils.rows_to_embeds(embed, [i.row for i in ccs])
        view = view_utils.EmbedPaginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=embeds[0])
        view.message = await interaction.original_response()


async def setup(bot: PBot) -> None:
    await bot.add_cog(CommunityContributors(bot))
