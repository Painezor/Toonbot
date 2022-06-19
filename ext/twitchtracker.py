"""Track when users begin streaming"""
from __future__ import annotations

from typing import Union, TYPE_CHECKING, List, Literal, Optional

from discord import Member, ActivityType, Embed, Message, Interaction, Colour
from discord.app_commands import guilds, command, autocomplete, Choice, describe
from discord.ext.commands import Cog
from twitchio import PartialUser

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.transfer_tools import get_flag, UNI_DICT
from ext.utils.view_utils import Paginator
from ext.utils.wows_utils import Region

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot, TwitchBot
    from discord import TextChannel, Role

WOWS_GAME_ID = 32502

PARTNER_ICON = "https://static-cdn.jtvnw.net/badges/v1/d12a2e27-16f6-41d0-ab77-b780518f00a3/1"
REGIONS = Literal['eu', 'na', 'cis', 'sea']


class Contributor:
    """An Object representing a World of Warships CC"""
    bot: PBot = None

    def __init__(self, bot: 'PBot', name: str, links: List[str], languages: List[str], region: Region):
        if self.bot is None:
            self.bot = bot

        self.name: str = name
        self.links: List[str] = links
        self.languages: List[str] = languages
        self.region: Region = region

    @property
    def markdown(self) -> str:
        """Return comma separated list of [name](link) social markdowns"""
        output = []
        for i in self.links:
            match i:
                case i if 'youtube' in i:
                    output.append(f'• [YouTube]({i})')
                case i if 'twitch' in i:
                    output.append(f'• [Twitch]({i})')
                case i if 'bilibili' in i:
                    output.append(f'• [bilibili]({i})')
                case i if 'reddit' in i:
                    output.append(f'• [Reddit]({i})')
                case i if 'nicovideo' in i:
                    output.append(f'• [Niconico]({i})')
                case i if 'facebook' in i:
                    output.append(f'• [Facebook]({i})')
                case i if 'instagram' in i:
                    output.append(f'• [Instagram]({i})')
                case i if 'twitter' in i:
                    output.append(f'• [Twitter]({i})')
                case i if 'discord' in i:
                    output.append(f'• [Discord]({i})')
                case i if 'yandex' in i:
                    output.append(f'• [Zen]({i})')
                case i if 'trovo' in i:
                    output.append(f'• [Trovo]({i})')
                case i if 'forum.worldofwarships' in i:
                    output.append(f'• [WOWS Forum]({i})')
                case _:
                    output.append(f"• {i}")
        return '\n'.join(output)

    @property
    def flag(self) -> str:
        """Return a flag emoji for each of a community contributor's languages"""
        flags = []
        for country in self.languages:
            for key, value in UNI_DICT.items():
                country = country.replace(key, value)
            flags.append(country)

        for index, flag in enumerate(flags):
            match flag:
                case '🇨🇸':
                    flags[index] = '🇨🇿'
                case '🇪🇳':
                    flags[index] = '🇺🇸' if self.region == Region.NA else '🏴󠁧󠁢󠁥󠁮󠁧󠁿'  # England. Fuck the yanks.
                case '🇰🇴':
                    flags[index] = '🇰🇷'
                case '🇯🇦':
                    flags[index] = '🇯🇵'
                case '🇿🇭-🇹🇼':
                    flags[index] = '🇹🇼'
                case '🇿🇭-🇸🇬':
                    flags[index] = '🇸🇬'
                case '🇪🇸-🇲🇽':
                    flags[index] = '🇲🇽'
                case '🇵🇹-🇧🇷':
                    flags[index] = '🇧🇷'
        return ''.join(flags)

    @property
    def row(self) -> str:
        """Return a short row representing all of a CC's social media info"""
        return f'{self.region.emote} {self.name} ({self.flag})\n{self.markdown}'

    @property
    def auto_complete(self) -> str:
        """String to search for to identify this CC"""
        return f"{self.name} {self.markdown}"

    @property
    async def embed(self) -> Embed:
        """Return an embed representing this Contributor"""
        e = Embed(title=f"{self.name} ({self.region.name})", description=self.markdown, colour=self.region.colour)
        e.set_author(name="World of Warships Community Contributor")
        e.set_thumbnail(url='https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png')

        twitch = next((i for i in self.links if 'twitch' in i), None)
        if twitch is not None:
            twitch_id = twitch.split('/')[-1]
            user = await self.bot.twitch.fetch_users(names=[twitch_id])
            user = user[0]
            e.set_image(url=user.profile_image)
            # TODO: Fetch Twitch Info into Embed
            print(user.__dict__)

        # TODO: Pull other website data where possible.
        return e


class Stream:
    """A World of Warships Stream"""

    def __init__(self, language: str, user: PartialUser, viewers: int, title: str, timestamp: Timestamp) -> None:
        self.language: str = language
        self.viewers: int = viewers
        self.user: str = user.name
        self.title: str = title
        self.timestamp: Timestamp = timestamp
        self.contributor: Optional[bool] = None

    @property
    def flag(self) -> str:
        """Get an emoji flag representation of the language"""
        return get_flag(self.language)

    @property
    def cc(self) -> str:
        """Return '[CC] ' if stream is marked as contributor, else return empty string"""
        return '[CC] ' if self.contributor else ''

    @property
    def live_time(self) -> str:
        """Get time elapsed since go live"""
        return self.timestamp.relative

    @property
    def markdown(self) -> str:
        """Return [Name](Link) markdown"""
        return f"[{self.user}](http://www.twitch.tv/{self.user})"

    @property
    def row(self) -> str:
        """Return a row formatted for an embed"""
        return f"{self.flag} {self.cc}{self.markdown} - {self.viewers} viewers, live since {self.live_time}\n" \
               f"{self.title}\n"


class TrackerChannel:
    """A Twitch Tracker Channel"""

    # TODO: Make Database Table for Tracked Roles & Members
    def __init__(self, bot: Union['Bot', 'PBot'], channel: 'TextChannel') -> None:
        self.bot: PBot | Bot = bot
        self.tracked: List[Member | Role] = []
        self.channel: TextChannel = channel

    async def get_tracks(self) -> List[Member | Role]:
        """Set the list of tracked members for the TrackerChannel"""
        sql = """SELECT tracked_id FROM tracker_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()

        try:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)
        finally:
            await self.bot.db.release(connection)

        tracked = []
        for r in records:
            role = self.channel.guild.get_role(r['tracked_id'])
            if role is not None:
                tracked.append(role)
                continue
            member = self.channel.guild.get_member(r['tracked_id'])
            if member is not None:
                tracked.append(member)
        return tracked

    async def track(self, member_or_role: Member | Role) -> List[Member]:
        """Add a user to the list of tracked users for Go Live notifications"""
        sql = """INSERT INTO tracker_channels (guild_id, channel_id, tracked_id) VALUES ($1, $2, $3)"""
        connection = await self.bot.db.acquire()

        try:
            async with connection.transaction():
                await connection.execute(sql, self.channel.guild.id, self.channel.id, member_or_role.id)
        finally:
            await self.bot.db.release(connection)

        self.tracked.append(member_or_role)
        return self.tracked

    async def untrack(self, member_or_role: Union[Member | Role]) -> List[Member]:
        """Remove a user from the list of tracked members."""
        sql = """DELETE FROM tracker_channels WHERE (channel_id, tracked_id) = ($1, $2)"""
        connection = await self.bot.db.acquire()

        try:
            async with connection.transaction():
                await connection.execute(sql, self.channel.id, member_or_role.id)
        finally:
            await self.bot.db.release(connection)
        self.tracked = [t for t in self.tracked if t.id != member_or_role.id]
        return self.tracked

    async def dispatch(self, embed: Embed) -> Message:
        """Send an embed to the TrackerChannel"""
        return await self.channel.send(embed=embed)


async def cc_ac(interaction: Interaction, current: str) -> List[Choice]:
    """Autocomplete from the list of stored CCs"""
    ccs = getattr(interaction.client, "contributors")
    ccs = [i for i in ccs if getattr(i, 'name', None) is not None]

    # Region Filtering
    match interaction.namespace.region:
        case None:
            pass
        case 'eu':
            ccs = [i for i in ccs if i.region == Region.EU]
        case 'na':
            ccs = [i for i in ccs if i.region == Region.NA]
        case 'cis':
            ccs = [i for i in ccs if i.region == Region.CIS]
        case 'sea':
            ccs = [i for i in ccs if i.region == Region.SEA]

    ccs = sorted(ccs, key=lambda x: x.name)
    return [Choice(name=f"{i.name} ({i.region.name})"[:100],
                   value=i.name) for i in ccs if current.lower() in i.auto_complete.lower()][:25]


async def language_ac(interaction: Interaction, current: str) -> List[Choice]:
    """Filter by Language"""
    bot: PBot = getattr(interaction, 'client')

    langs = {}
    for x in bot.contributors:
        for language in x.languages:
            langs.update(language)
    return [Choice(name=x, value=x) for x in langs if current.lower() in x.lower()]


class TwitchTracker(Cog):
    """Track when users go live to twitch."""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot
        self.twitch: TwitchBot = bot.twitch

    async def cog_load(self) -> None:
        """On cog load, generate list of Tracker Channels"""
        await self.update_cache()
        await self.fetch_ccs()

    async def update_cache(self) -> List[TrackerChannel]:
        """Load the databases' tracker channels into the bot"""
        sql = """SELECT DISTINCT channel_id FROM tracker_channels"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                channel_ids = await connection.fetch(sql)
        finally:
            await self.bot.db.release(connection)

        # Purge Old.
        cached = [i.channel.id for i in self.bot.tracker_channels if i.channel.id in channel_ids]

        # Fetch New
        trackers = []
        for c_id in channel_ids:
            channel = self.bot.get_channel(c_id)
            if channel is None:
                continue
            if c_id in cached:
                continue

            tc = TrackerChannel(self.bot, channel)
            await tc.get_tracks()
            trackers.append(tc)
        self.bot.tracker_channels = trackers
        return self.bot.tracker_channels

    async def fetch_ccs(self) -> List[Contributor]:
        """Fetch details about all World of Warships CCs"""
        ccs = 'https://wows-static-content.gcdn.co/contributors-program/members.json'
        async with self.bot.session.get(ccs) as resp:
            match resp.status:
                case 200:
                    ccs = await resp.json()
                case _:
                    return []

        contributors = []
        for i in ccs:
            match i['realm']:
                case 'RU':
                    region = Region.CIS
                case 'ASIA':
                    region = Region.SEA
                case 'NA':
                    region = Region.NA
                case 'EU':
                    region = Region.EU
                case _:
                    print("Missing region identifier for ", [i['realm']])
                    region = None

            c = Contributor(self.bot, name=i['name'], region=region, languages=i['lang'].split(','), links=i['links'])
            contributors.append(c)
        self.bot.contributors = contributors
        return self.bot.contributors

    @Cog.listener()
    async def on_presence_update(self, before: Member, after: Member):
        """When the user updates their presence, we check if they started streaming
        We then check if they are in the channel's list of tracked users."""
        act = getattr(after.activity, 'type', None)
        if act == getattr(before.activity, 'type', None):
            return
        if act != ActivityType.streaming:
            return

        e = Embed(title=after.activity.name, url=after.activity.url,
                  description=f"{after.mention}: {Timestamp().relative}")

        match after.activity.platform:
            case "Twitch":
                e.colour = 0x9146FF
                info = await self.twitch.fetch_channel(after.activity.twitch_name)
                if info.delay > 0:
                    minutes, seconds = divmod(info.delay, 60)
                    delay = f"{minutes} minutes"
                    if seconds:
                        delay += f" {seconds} seconds"
                    e.add_field(name="Stream Delay", value=delay)

                user = await info.user.fetch(force=True)
                print("Displaying all available information about streamer", user.name)
                print(dir(user))
                e.set_author(name=f"{user.display_name} went live on {after.activity.platform}",
                             icon_url=after.display_avatar.url)
                e.set_thumbnail(url=user.profile_image)

                match user.broadcaster_type.name:
                    case "partner":
                        e.set_footer(text=f"Twitch Partner playing {after.activity.game}", icon_url=PARTNER_ICON)
                    case "affiliate":
                        e.set_footer(text=f"Twitch Affiliate streaming {after.activity.game}")
                    case _:
                        e.set_footer(text=f"Streaming {after.activity.game}")

            case _:
                print('Unhandled stream tracker platform', after.activity.platform)
                e.set_thumbnail(url=after.avatar.url)

        return await self.bot.get_channel(303154190362869761).send(embed=e)

    # TODO: Role based tracking.
    # TODO: Go-Live Twitch Tracker Notifications
    # TODO: Create a view, with Region & Language Filtering.

    @command()
    @guilds(250252535699341312)
    @describe(cc="Get streamers who specifically are or are not members of the CC program")
    async def streams(self, interaction: Interaction, cc: bool = None) -> Message:
        """Get a list of everyone currently streaming World of Warships"""
        await interaction.response.defer()

        streams = await self.twitch.fetch_streams(game_ids=[WOWS_GAME_ID])
        streams = [Stream(s.language, s.user, s.viewer_count, s.title, Timestamp(s.started_at)) for s in streams]

        if cc is not None:
            cc_twitch = ''.join(i.markdown for i in self.bot.contributors)
            for s in streams:
                s.contributor = True if f"http://www.twitch.tv/{s.user}" in cc_twitch else False
            streams = [s for s in streams if s.contributor is cc]

        e = Embed(title="Current World of Warships Live Streams", colour=0x9146FF)
        e.url = 'https://www.twitch.tv/directory/game/World%20of%20Warships'
        rows = [s.row for s in sorted(streams, key=lambda x: x.viewers, reverse=True)]
        embeds = rows_to_embeds(e, rows)
        return await Paginator(self.bot, interaction, embeds).update()

    @command()
    @describe(search="search by name (e.g.: painezor, yuzorah), or website name (ex: twitch, dailybounce)",
              region="Filter by region", language='Filter by language')
    @autocomplete(search=cc_ac, language=language_ac)
    async def cc(self, interaction: Interaction,
                 search: str = None,
                 region: REGIONS = None,
                 language: str = None) -> Message:
        """Fetch The List of all CCs"""
        await interaction.response.defer(thinking=True)

        cc = self.bot.contributors
        if search is not None:
            cc = [i for i in cc if search in i.name]

        if len(cc) == 1:  # Send an individual Profile
            return await self.bot.reply(interaction, embed=cc[0].embed)

        ccs = [i for i in self.bot.contributors if search in i.auto_complete]
        match region:
            case 'eu':
                ccs = [i for i in ccs if i.region == Region.EU]
            case 'na':
                ccs = [i for i in ccs if i.region == Region.NA]
            case 'cis':
                ccs = [i for i in ccs if i.region == Region.CIS]
            case 'sea':
                ccs = [i for i in ccs if i.region == Region.SEA]

        if language is not None:
            ccs = [i for i in ccs if language in i.languages]

        e = Embed(title='World of Warships Community Contributors')
        e.url = 'https://worldofwarships.eu/en/content/contributors-program/'
        e.set_thumbnail(url='https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png')
        e.colour = Colour.dark_blue()
        ccs = rows_to_embeds(e, [i.row for i in ccs])
        return await Paginator(self.bot, interaction, ccs).update()

    # Database Cleanup
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove dev blog trackers from deleted channels"""
        q = f"""DELETE FROM tracker_channewls WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id)
        finally:
            await self.bot.db.release(connection)


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(TwitchTracker(bot))
