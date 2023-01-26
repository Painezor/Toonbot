"""Track when users begin streaming"""
from __future__ import annotations

import logging
from asyncio import sleep, Semaphore
from typing import TYPE_CHECKING, Literal, Optional, ClassVar

from asyncpg import ForeignKeyViolationError
from discord import ActivityType, Embed, Message, Interaction, Colour, Permissions, ButtonStyle, Role, TextChannel
from discord.app_commands import guilds, command, autocomplete, Choice, describe, Group
from discord.ext.commands import Cog
from discord.ui import View, Select
from iso639 import languages
from twitchio import PartialUser, Tag, ChannelInfo, User, ChatSettings
from twitchio.ext.commands import Bot as TBot

from ext.logs import TWITCH_LOGO
from ext.painezbot_utils.player import Region
from ext.utils.embed_utils import rows_to_embeds
from ext.utils.flags import get_flag
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator, Confirmation, Stop

if TYPE_CHECKING:
    from painezBot import PBot
    from discord import Member

from painezBot import credentials

WOWS_GAME_ID = 32502
PARTNER_ICON = "https://static-cdn.jtvnw.net/badges/v1/d12a2e27-16f6-41d0-ab77-b780518f00a3/1"
REGIONS = Literal['eu', 'na', 'cis', 'sea']


class Contributor:
    """An Object representing a World of Warships CC"""
    bot: ClassVar[PBot] = None

    def __init__(self, name: str, links: list[str], language: list[str], region: 'Region'):
        self.name: str = name
        self.links: list[str] = links
        self.language: list[str] = language
        self.region: Region = region

    @property
    def language_names(self) -> list[str]:
        """Get the name of each language"""
        return [languages.get(alpha2=lang).name for lang in self.language]

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
        return ', '.join([get_flag(x) for x in self.language])

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

        try:
            twitch = next(i for i in self.links if 'twitch' in i)
            twitch_id = twitch.split('/')[-1]
            user = await self.bot.twitch.fetch_users(names=[twitch_id])
            user = user[0]
            e.set_image(url=user.profile_image)

            # TODO: Fetch Twitch Info into Embed
            # TODO: Official channel Schedule
            # https://dev.twitch.tv/docs/api/reference#get-channel-stream-schedule
            # https://dev.twitch.tv/docs/api/reference#get-channel-emotes
            print(dir(user))
        except StopIteration:
            pass

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
        return f"{self.flag} **{self.markdown}**" \
               f"```\n{self.title}```\n" \
               f"{self.viewers} viewers, live since {self.live_time}\n"


class TrackerChannel:
    """A Twitch Tracker Channel"""
    bot: PBot = None

    def __init__(self, channel: 'TextChannel') -> None:
        self.tracked: list[Role] = []
        self.channel: TextChannel = channel

    async def create_tracker(self) -> TrackerChannel:
        """Create a ticker for the channel"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, self.channel.guild.id)

                sql = """INSERT INTO tracker_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(sql, self.channel.guild.id, self.channel.id)
        return self

    async def get_tracks(self) -> list[Role]:
        """Set the list of tracked members for the TrackerChannel"""

        sql = """SELECT role_id FROM tracker_ids WHERE channel_id = $1"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)

        tracked = []
        for r in records:
            role = self.channel.guild.get_role(r['role_id'])
            if role is not None:
                tracked.append(role)
        self.tracked = tracked
        return tracked

    async def track(self, role: Role) -> list[Role]:
        """Add a user to the list of tracked users for Go Live notifications"""
        sql = """INSERT INTO tracker_ids (channel_id, role_id) VALUES ($1, $2)"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute(sql, self.channel.id, role.id)

        self.tracked.append(role)
        return self.tracked

    async def untrack(self, roles: list[str]) -> list[Role]:
        """Remove a list of users or roles from the list of tracked roles."""
        sql = """DELETE FROM tracker_ids WHERE (channel_id, role_id) = ($1, $2)"""

        roles = [int(r) for r in roles]
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(sql, [(self.channel.id, r) for r in roles])

        self.tracked = [t for t in self.tracked if t.id not in roles]
        return self.tracked

    async def dispatch(self, embed: Embed) -> Message:
        """Send an embed to the TrackerChannel"""
        return await self.channel.send(embed=embed)

    def view(self, interaction: Interaction) -> TrackerConfig:
        """Return a Config View for this Tracker Channel"""
        return TrackerConfig(interaction, self)


async def cc_ac(interaction: Interaction, current: str) -> list[Choice]:
    """Autocomplete from the list of stored CCs"""
    bot: PBot = interaction.client
    ccs = bot.contributors
    ccs = [i for i in ccs if i.name is not None]

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


async def language_ac(interaction: Interaction, current: str) -> list[Choice]:
    """Filter by Language"""
    bot: PBot = getattr(interaction, 'client')

    langs = {}
    for x in bot.contributors:
        for language in x.language_names:
            langs.update(language)
    return [Choice(name=x, value=x) for x in langs if current.lower() in x.lower()]


class TrackerConfig(View):
    """Config View for a Twitch Tracker channel"""
    bot: PBot = None

    def __init__(self, interaction: Interaction, tc: TrackerChannel):
        super().__init__()
        self.interaction: Interaction = interaction
        self.tc: TrackerChannel = tc
        self.index: int = 0
        self.pages: list[Embed] = []

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify interactor is person who ran command."""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Message:
        """Hide menu on timeout."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def creation_dialogue(self) -> Message:
        """Send a dialogue to check if the user wishes to create a new ticker."""
        self.clear_items()

        view = Confirmation(self.interaction, colour_a=ButtonStyle.green, label_a=f"Create tracker", label_b="Cancel")
        notfound = f"{self.tc.channel.mention} does not have a twitch tracker, would you like to create one?"
        await self.bot.reply(self.interaction, content=notfound, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled tracker creation for {self.tc.channel.mention}"
            view.clear_items()
            await self.bot.error(self.interaction, txt, view=view)
            return False

        try:
            await self.tc.create_tracker()
        # We have code to handle the ForeignKeyViolation within create_ticker, so rerun it.
        except ForeignKeyViolationError:
            await self.tc.create_tracker()
        return await self.update(content=f"A Twitch Tracker was created for {self.tc.channel.mention}")

    async def remove_tracked(self, roles: list[str]) -> Message:
        """Bulk remove tracked items from a Twitch Tracker channel"""
        # Ask user to confirm their choice.
        _roles = [self.tc.channel.guild.get_role(int(r)) for r in roles]
        view = Confirmation(self.interaction, label_a="Remove", label_b="Cancel", colour_a=ButtonStyle.red)
        mentions = '\n•'.join(i.mention for i in _roles)

        embed = Embed(description=f"Remove these items from {self.tc.channel.mention}?\n\n•{mentions}")
        await self.bot.reply(self.interaction, embed=embed, view=view)
        await view.wait()

        if not view.value:
            return await self.on_timeout()

        await self.tc.untrack(roles)
        txt = "\n".join(i.name for i in _roles)
        return await self.update(f"Removed {self.tc.channel.mention} twitch trackers: {txt}")

    async def update(self, content: str = None) -> Message:
        """Regenerate view and push to message"""
        self.clear_items()

        if not self.tc.tracked:
            await self.tc.get_tracks()

        e = Embed(colour=0x9146FF, title="Twitch Go Live Tracker")
        e.set_thumbnail(url=TWITCH_LOGO)

        missing = []
        perms = self.tc.channel.permissions_for(self.tc.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            v = "```yaml\nThis tracker channel will not work currently, I am missing the following permissions.\n"
            e.add_field(name='Missing Permissions', value=f"{v} {missing}```")

        if not self.tc.tracked:
            e.description = f"{self.tc.channel.mention} has no tracked roles."

        else:
            header = f'Tracked roles for {self.tc.channel.mention}\n'
            embeds = rows_to_embeds(e, [i.mention for i in self.tc.tracked], header=header, rows=25)
            self.pages = embeds

            self.add_item(Stop(row=1))

            e = self.pages[self.index]

            roles = sorted(self.tc.tracked, key=lambda r: r.name)

            # Get everything after index * 25 (page len), then up to 25 items from that page.
            if len(roles) > 25:
                roles = roles[self.index * 25:][:25]
            self.add_item(Untrack(roles))
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


class Untrack(Select):
    """Dropdown to roles from a Twitch Tracker Channel."""

    def __init__(self, roles: list[Role], row: int = 0) -> None:
        roles = sorted(set(roles), key=lambda role: role.name)
        super().__init__(placeholder="Remove tracked role(s)", row=row, max_values=len(roles))
        # No idea how we're getting duplicates here but fuck it I don't care.
        for r in roles:
            self.add_option(label=r.name, emoji=r.unicode_emoji, description=str(r.id), value=str(r.id))

    async def callback(self, interaction: Interaction) -> Message:
        """When a league is selected, delete channel / league row from DB"""
        await interaction.response.defer()
        return await self.view.remove_tracked(self.values)


class TwitchTracker(Cog):
    """Track when users go live to twitch."""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

        self._cached: dict[int, Embed] = {}  # user_id: Embed
        self.semaphore = Semaphore()

        if TrackerConfig.bot is None:
            TrackerConfig.bot = bot
            TrackerChannel.bot = bot

    async def cog_load(self) -> None:
        """On cog load, generate list of Tracker Channels"""
        await self.fetch_ccs()
        await self.update_cache()

        self.bot.twitch = TBot.from_client_credentials(**credentials['Twitch API'])
        await self.bot.twitch.start()

    async def update_cache(self) -> list[TrackerChannel]:
        """Load the databases' tracker channels into the bot"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                channel_ids = await connection.fetch("""SELECT DISTINCT channel_id FROM tracker_channels""")

        channel_ids = [r['channel_id'] for r in channel_ids]

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

            tc = TrackerChannel(channel)
            await tc.get_tracks()
            trackers.append(tc)
        self.bot.tracker_channels = trackers
        return self.bot.tracker_channels

    async def fetch_ccs(self) -> list[Contributor]:
        """Fetch details about all World of Warships CCs"""
        ccs = 'https://wows-static-content.gcdn.co/contributors-program/members.json'
        async with self.bot.session.get(ccs) as resp:
            match resp.status:
                case 200:
                    ccs = await resp.json()
                case _:
                    return []

        contributors = []
        if Contributor.bot is None:
            Contributor.bot = self.bot

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
                    logging.error(f'No identifier found for realm {i["realm"]}')
                    region = None

            c = Contributor(name=i['name'], region=region, language=i['lang'].split(','), links=i['links'])
            contributors.append(c)
        self.bot.contributors = contributors
        return self.bot.contributors

    async def generate_twitch_embed(self, member: 'Member') -> Embed:
        """Generate the embed for the twitch user"""
        e = Embed(title=member.activity.name, url=member.activity.url)

        desc = []
        match member.activity.platform:
            case "Twitch":
                e.colour = 0x9146FF
                info: ChannelInfo = await self.bot.twitch.fetch_channel(member.activity.twitch_name)
                if info.delay > 0:
                    minutes, seconds = divmod(info.delay, 60)
                    delay = f"{minutes} minutes"
                    if seconds:
                        delay += f" {seconds} seconds"
                    e.add_field(name="Stream Delay", value=delay)

                desc.append(get_flag(info.language))
                user: User = await info.user.fetch(force=True)
                settings: ChatSettings = await user.fetch_chat_settings()

                modes = []
                if settings.emote_mode:
                    modes.append('This channel is in emote only mode')
                if settings.follower_mode:
                    modes.append(f'This channel is in {settings.follower_mode_duration} minute follower mode.')
                if settings.subscriber_mode:
                    modes.append('This channel is in subscriber only mode.')
                if settings.slow_mode:
                    modes.append(f'This channel is in {settings.slow_mode_wait_time} second slow mode.')
                if modes:
                    e.add_field(name='Chat Restrictions', value='\n'.join(modes))

                desc.append(f"{member.mention}: {Timestamp().relative}")

                # Stream Tags
                tags: list[Tag] = await user.fetch_tags()
                if tags:
                    desc.append(f"\n**Tags**: {', '.join([i.localization_names['en-us'] for i in tags])}")

                e.set_author(name=f"{user.display_name} went live on {member.activity.platform}",
                             icon_url=member.display_avatar.url)
                e.set_thumbnail(url=user.profile_image)

                match user.broadcaster_type.name:
                    case "partner":
                        e.set_footer(text=f"Twitch Partner playing {member.activity.game}",
                                     icon_url=PARTNER_ICON)
                    case "affiliate":
                        e.set_footer(text=f"Twitch Affiliate streaming {member.activity.game}")
                    case _:
                        e.set_footer(text=f"Streaming {member.activity.game}")
            case _:
                logging.error(f'Unhandled stream tracker platform {member.activity.platform}')

        e.description = " ".join(desc)
        return e

    @Cog.listener()
    async def on_presence_update(self, before: 'Member', after: 'Member') -> None:
        """When the user updates their presence, we check if they started streaming
        We then check if they are in the channel's list of tracked users."""
        if not self.bot.tracker_channels:
            await self.update_cache()

        if after.activity is None or after.activity.type != ActivityType.streaming:
            return
        if before.activity is not None and before.activity.type == ActivityType.streaming:
            return

        this_guild_channels = [i for i in self.bot.tracker_channels if i.channel.guild.id == after.guild.id]
        valid_channels = []
        valid_role_ids = [r.id for r in after.roles]
        for i in this_guild_channels:
            for role in i.tracked:
                if role.id in valid_role_ids:
                    valid_channels.append(i)
                    break

        if not valid_channels:
            return

        async with self.semaphore:
            if after.id in self._cached:
                embed = self._cached[after.id]
            else:
                embed = await self.generate_twitch_embed(after)
                self._cached.update({after.id: embed})

        for channel in valid_channels:
            await channel.dispatch(embed)

        await sleep(60)
        self._cached.pop(after.id)

    # TODO: Create a view, with CC & Language Filtering.
    @command()
    @guilds(250252535699341312)
    @describe(cc="Get streamers who specifically are or are not members of the CC program")
    async def streams(self, interaction: Interaction, cc: bool = None) -> Message:
        """Get a list of everyone currently streaming World of Warships on Twitch"""
        await interaction.response.defer()

        streams = await self.bot.twitch.fetch_streams(game_ids=[WOWS_GAME_ID])
        streams = [Stream(s.language, s.user, s.viewer_count, s.title.strip(),
                          Timestamp(s.started_at)) for s in streams]

        if cc is not None:
            cc_twitch = ''.join(i.markdown for i in self.bot.contributors)
            for s in streams:
                s.contributor = True if f"http://www.twitch.tv/{s.user}" in cc_twitch else False
            streams = [s for s in streams if s.contributor is cc]

        e = Embed(title="Current World of Warships Live Streams", colour=0x9146FF)
        e.set_thumbnail(url=TWITCH_LOGO)
        e.url = 'https://www.twitch.tv/directory/game/World%20of%20Warships'
        rows = [s.row for s in sorted(streams, key=lambda x: x.viewers, reverse=True)]
        return await Paginator(interaction, rows_to_embeds(e, rows)).update()

    @command()
    @describe(search="search by name (e.g.: painezor, yuzorah), or website name (ex: twitch, dailybounce)",
              region="Filter by region", language='Filter by language')
    @autocomplete(search=cc_ac, language=language_ac)
    async def cc(self, interaction: Interaction, search: str = None, region: REGIONS = None, language: str = None) \
            -> Message:
        """Fetch The List of all CCs"""
        await interaction.response.defer(thinking=True)

        ccs = self.bot.contributors

        if search is not None:
            ccs = [i for i in ccs if search == i.name]
            if len(ccs) == 1:  # Send an individual Profile
                e = await ccs[0].embed
                return await self.bot.reply(interaction, embed=e)

        if search is not None:
            ccs = [i for i in self.bot.contributors if search in i.auto_complete]
        if region is not None:
            ccs = [i for i in ccs if i.region.db_key == region]

        if language is not None:
            ccs = [i for i in ccs if language in i.language_names]

        e = Embed(title='World of Warships Community Contributors')
        e.url = 'https://worldofwarships.eu/en/content/contributors-program/'
        e.set_thumbnail(url='https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png')
        e.colour = Colour.dark_blue()
        return await Paginator(interaction, rows_to_embeds(e, [i.row for i in ccs])).update()

    track = Group(name="twitch_tracker", description="Go Live Tracker", guild_only=True,
                  default_permissions=Permissions(manage_channels=True))

    @track.command()
    @describe(role='Role to track Twitch Go Lives from', channel='Add to Which channel?')
    async def add(self, interaction: Interaction, role: Role, channel: TextChannel = None) -> Message:
        """Add a role of this discord to the twitch tracker."""
        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = interaction.channel

        try:
            tc = next(i for i in self.bot.tracker_channels if i.channel.id == channel.id)
        except StopIteration:
            tc = TrackerChannel(channel)
            success = await tc.view(interaction).creation_dialogue()
            if not success:
                return

            self.bot.tracker_channels.append(tc)

        await tc.track(role)
        return await tc.view(interaction).update(f"Added {role.name} to {channel.mention} Twitch Tracker")

    @track.command()
    @describe(channel="Manage which channel's Trackers?")
    async def manage(self, interaction: Interaction, channel: TextChannel = None) -> Message:
        """View or remove tracked twitch go live roles"""
        await interaction.response.defer(thinking=True)

        if channel is None:
            channel = interaction.channel

        try:
            tc = next(i for i in self.bot.tracker_channels if i.channel.id == channel.id)
            await tc.view(interaction).update()
        except StopIteration:
            tc = TrackerChannel(channel)
            success = await tc.view(interaction).creation_dialogue()
            if success:
                self.bot.tracker_channels.append(tc)

    # Database Cleanup
    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> list[TrackerChannel]:
        """Remove dev blog trackers from deleted channels"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                await connection.execute(f"""DELETE FROM tracker_channels WHERE channel_id = $1""", channel.id)

        self.bot.tracker_channels = [i for i in self.bot.tracker_channels if i.channel.id != channel.id]
        return self.bot.tracker_channels


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(TwitchTracker(bot))
