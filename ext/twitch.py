"""Track when users begin streaming"""
from __future__ import annotations

import logging
import typing
import json

import discord
import twitchio
from discord.ext import commands
from iso639 import Lang
from twitchio.ext.commands import Bot as TBot

from ext.logs import stringify_seconds
from ext.utils import embed_utils, flags, timed_events, view_utils
from ext.utils import wows_api as api

if typing.TYPE_CHECKING:
    from painezBot import PBot

with open("credentials.json", encoding="utf-8") as fun:
    credentials = json.load(fun)


CCS = "https://wows-static-content.gcdn.co/cms-data/contributors_wg.json"
CC_BADGE = "https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png"
PARTNER_ICON = """https://static-cdn.jtvnw.net/badges/v1/d12a2e27-16f6-41d0-ab7
7-b780518f00a3/1"""
PROGRAM_INFO = "https://worldofwarships.eu/en/content/contributors-program/"
REGIONS = typing.Literal["eu", "na", "cis", "sea"]
TWITCH_LOGO = """https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklo
go.com.png"""
TWITCH_DIRECTORY = "https://www.twitch.tv/directory/game/World%20of%20Warships"
WOWS_GAME_ID = 32502

logger = logging.getLogger("twitch")


class Contributor:
    """An Object representing a World of Warships CC"""

    bot: typing.ClassVar[PBot]

    def __init__(
        self,
        name: str,
        links: list[str],
        language: list[str],
        region: api.Region,
    ):
        self.name: str = name
        self.links: list[str] = links
        self.language: list[str] = language
        self.region: api.Region = region

    @property
    def language_names(self) -> list[str]:
        """Get the name of each language"""
        return [Lang(lang).name for lang in self.language]

    @property
    def markdown(self) -> str:
        """Return comma separated list of [name](link) social markdowns"""
        output = []
        for i in self.links:

            if "youtube" in i:
                output.append(f"• [YouTube]({i})")
            elif "twitch" in i:
                output.append(f"• [Twitch]({i})")
            elif "bilibili" in i:
                output.append(f"• [bilibili]({i})")
            elif "reddit" in i:
                output.append(f"• [Reddit]({i})")
            elif "nicovideo" in i:
                output.append(f"• [Niconico]({i})")
            elif "facebook" in i:
                output.append(f"• [Facebook]({i})")
            elif "instagram" in i:
                output.append(f"• [Instagram]({i})")
            elif "twitter" in i:
                output.append(f"• [Twitter]({i})")
            elif "discord" in i:
                output.append(f"• [Discord]({i})")
            elif "yandex" in i:
                output.append(f"• [Zen]({i})")
            elif "trovo" in i:
                output.append(f"• [Trovo]({i})")
            elif "forum.worldofwarships" in i:
                output.append(f"• [WoWs Forum]({i})")
            else:
                logger.info("Unhandled social %s", i)
                output.append(f"• {i}")
        return "\n".join(output)

    @property
    def flag(self) -> str:
        """Return a flag emoji for each of a CC's languages"""
        return ", ".join([flags.get_flag(x) for x in self.language])

    @property
    def row(self) -> str:
        """Return a short row representing all of a CC's social media info"""
        emote = self.region.emote
        return f"{emote} {self.name} ({self.flag})\n{self.markdown}"

    @property
    def auto_complete(self) -> str:
        """String to search for to identify this CC"""
        return f"{self.name} {self.markdown}".casefold()


class Stream:
    """A World of Warships Stream"""

    def __init__(
        self,
        language: str,
        user: twitchio.PartialUser,
        viewers: int,
        title: str,
        timestamp: timed_events.Timestamp,
    ) -> None:
        self.language: str = language
        self.viewers: int = viewers
        self.user: typing.Optional[str] = user.name
        self.title: str = title
        self.timestamp: timed_events.Timestamp = timestamp
        self.contributor: typing.Optional[bool] = None

    @property
    def flag(self) -> str:
        """Get an emoji flag representation of the language"""
        return flags.get_flag(self.language)

    @property
    def is_cc(self) -> str:
        """Return '[CC] ' if stream is marked as contributor"""
        return "[CC] " if self.contributor else ""

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
        return (
            f"{self.flag} **{self.markdown}**"
            f"```\n{self.title}```\n"
            f"{self.viewers} viewers, live since {self.live_time}\n"
        )


class TrackerChannel:
    """A Twitch Tracker Channel"""

    bot: typing.ClassVar[PBot]

    def __init__(self, channel: discord.TextChannel) -> None:
        self.tracked: list[discord.Role] = []
        self.channel: discord.TextChannel = channel

    async def create_tracker(self) -> TrackerChannel:
        """Create a ticker for the channel"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                         ON CONFLICT DO NOTHING"""
                await connection.execute(sql, self.channel.guild.id)

                sql = """INSERT INTO tracker_channels (guild_id, channel_id)
                         VALUES ($1, $2) ON CONFLICT DO NOTHING"""
                await connection.execute(
                    sql, self.channel.guild.id, self.channel.id
                )
        return self

    async def get_tracks(self) -> list[discord.Role]:
        """Set the list of tracked roles for the TrackerChannel"""

        sql = """SELECT role_id FROM tracker_ids WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql, self.channel.id)

        tracked = []
        for i in records:
            role = self.channel.guild.get_role(i["role_id"])
            if role is not None:
                tracked.append(role)
        self.tracked = tracked
        return tracked

    async def track(self, role: discord.Role) -> list[discord.Role]:
        """Add a user to the list of tracked users for Go Live notifications"""
        sql = """INSERT INTO tracker_ids (channel_id, role_id)
                 VALUES ($1, $2)"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, self.channel.id, role.id)

        self.tracked.append(role)
        return self.tracked

    async def untrack(self, roles: list[str]) -> list[discord.Role]:
        """Remove a list of users or roles from the list of tracked roles."""
        sql = """DELETE FROM tracker_ids
                 WHERE (channel_id, role_id) = ($1, $2)"""

        role_ids: list[int] = [int(r) for r in roles]
        rows = [(self.channel.id, r) for r in role_ids]
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.executemany(sql, rows)

        self.tracked = [t for t in self.tracked if t.id not in role_ids]
        return self.tracked

    def view(self, interaction: discord.Interaction[PBot]) -> TrackerConfig:
        """Return a Config View for this Tracker Channel"""
        return TrackerConfig(interaction, self)


async def cc_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice]:
    """Autocomplete from the list of stored CCs"""
    bot: PBot = interaction.client
    ccs = bot.contributors
    ccs = [i for i in ccs if i.name is not None]

    # Region Filtering
    if region := interaction.namespace.region:
        ccs = [i for i in ccs if i.region.name.lower() == region]

    ccs = sorted(ccs, key=lambda x: x.name)
    cur = current.casefold()

    choices = []
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


async def language_ac(
    interaction: discord.Interaction[PBot], current: str
) -> list[discord.app_commands.Choice]:
    """Filter by Language"""

    ccs = interaction.client.contributors

    langs = set(a for b in [y.language_names for y in ccs] for a in b)

    cur = current.casefold()

    choices = []
    for i in langs:
        if cur not in i.casefold():
            continue

        choices.append(discord.app_commands.Choice(name=i, value=i))

        if len(choices) == 25:
            break

    return choices


class TrackerConfig(view_utils.BaseView):
    """Config View for a Twitch Tracker channel"""

    def __init__(
        self, interaction: discord.Interaction[PBot], chan: TrackerChannel
    ):
        super().__init__(interaction)
        self.chan: TrackerChannel = chan
        self.index: int = 0
        self.pages: list[discord.Embed] = []

    async def creation_dialogue(self) -> bool:
        """Send a dialogue to check if the user
        wishes to create a new ticker."""
        self.clear_items()

        itr = self.interaction
        view = view_utils.Confirmation(
            itr, "Create tracker", "Cancel", discord.ButtonStyle.green
        )

        chan = self.chan.channel.mention
        notfound = f"{chan} does not have a twitch tracker, create one now?"
        await itr.edit_original_response(content=notfound, view=view)
        await view.wait()

        if not view.value:
            txt = f"Cancelled tracker creation for {chan}"
            view.clear_items()
            await self.bot.error(self.interaction, txt, view=view)
            return False

        await self.chan.create_tracker()
        await self.update(f"Twitch Tracker was created in {chan}")
        return True

    async def remove_tracked(
        self, roles: list[str]
    ) -> discord.InteractionMessage:
        """Bulk remove tracked items from a Twitch Tracker channel"""
        # Ask user to confirm their choice.
        itr = self.interaction
        view = view_utils.Confirmation(
            itr, "Remove", "Cancel", discord.ButtonStyle.red
        )

        mentions = "\n•".join(f"<@&{i}>" for i in roles)

        mention = self.chan.channel.mention
        embed = discord.Embed()
        embed.description = f"Remove items from {mention}?\n\n•{mentions}"

        edit = self.interaction.edit_original_response
        await edit(embed=embed, view=view)
        await view.wait()

        if view.value:
            await self.chan.untrack(roles)
            embed = discord.Embed(title="Tracked roles removed")
            embed.description = f"{mention}\n{mentions}"
            embed_utils.user_to_footer(embed, self.interaction.user)
            await self.interaction.followup.send(embed=embed)

        return await edit(view=self)

    async def update(
        self, content: typing.Optional[str] = None
    ) -> discord.InteractionMessage:
        """Regenerate view and push to message"""
        self.clear_items()

        if not self.chan.tracked:
            await self.chan.get_tracks()

        embed = discord.Embed(colour=0x9146FF, title="Twitch Go Live Tracker")
        embed.set_thumbnail(url=TWITCH_LOGO)

        missing = []
        perms = self.chan.channel.permissions_for(self.chan.channel.guild.me)
        if not perms.send_messages:
            missing.append("send_messages")
        if not perms.embed_links:
            missing.append("embed_links")

        if missing:
            txt = (
                "```yaml\nThis tracker channel will not work currently"
                f"I am missing the following permissions.\n{missing}```\n"
            )
            embed.add_field(name="Missing Permissions", value=txt)

        if not self.chan.tracked:
            ment = self.chan.channel.mention
            embed.description = f"{ment} has no tracked roles."

        else:
            header = f"Tracked roles for {self.chan.channel.mention}\n"

            rows = [i.mention for i in self.chan.tracked]
            embeds = embed_utils.rows_to_embeds(embed, rows, 25, header)
            self.pages = embeds

            self.add_item(view_utils.Stop(row=1))
            embed = self.pages[self.index]

            roles = sorted(self.chan.tracked, key=lambda i: i.name)

            # Get everything after index * 25 (page len),
            #  then up to 25 items from that page.
            if len(roles) > 25:
                roles = roles[self.index * 25 :][:25]
            self.add_item(Untrack(roles))
        edit = self.interaction.edit_original_response
        return await edit(content=content, embed=embed, view=self)


class Untrack(discord.ui.Select):
    """Dropdown to roles from a Twitch Tracker Channel."""

    view: TrackerConfig

    def __init__(self, roles: list[discord.Role], row: int = 0) -> None:
        roles = sorted(set(roles), key=lambda role: role.name)
        super().__init__(
            placeholder="Remove tracked role(s)",
            row=row,
            max_values=len(roles),
        )
        # No idea how we're getting duplicates here but fuck it I don't care.
        for i in roles:
            self.add_option(
                label=i.name,
                emoji=i.unicode_emoji,
                description=str(i.id),
                value=str(i.id),
            )

    async def callback(
        self, interaction: discord.Interaction[PBot]
    ) -> discord.InteractionMessage:
        """When a league is selected, delete channel / league row from DB"""

        await interaction.response.defer()
        return await self.view.remove_tracked(self.values)


class TwitchTracker(commands.Cog):
    """Track when users go live to twitch."""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot
        TrackerChannel.bot = bot

    async def cog_load(self) -> None:
        """On cog load, generate list of Tracker Channels"""
        await self.fetch_ccs()
        await self.update_cache()
        client = TBot.from_client_credentials(**credentials["Twitch API"])
        self.bot.twitch = client
        self.bot.loop.create_task(self.bot.twitch.connect())

    async def update_cache(self) -> list[TrackerChannel]:
        """Load the databases' tracker channels into the bot"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                channel_ids = await connection.fetch(
                    """SELECT DISTINCT channel_id FROM tracker_channels"""
                )

        channel_ids = [r["channel_id"] for r in channel_ids]

        # Purge Old.
        cached = [
            i.channel.id
            for i in self.bot.tracker_channels
            if i.channel.id in channel_ids
        ]

        # Fetch New
        trackers = []
        for c_id in channel_ids:
            channel = self.bot.get_channel(c_id)

            if channel is None or c_id in cached:
                continue

            channel = typing.cast(discord.TextChannel, channel)

            chan = TrackerChannel(channel)
            await chan.get_tracks()
            trackers.append(chan)
        self.bot.tracker_channels = trackers
        return self.bot.tracker_channels

    async def fetch_ccs(self) -> list[Contributor]:
        """Fetch details about all World of Warships CCs"""
        async with self.bot.session.get(CCS) as resp:
            if resp.status != 200:
                raise ConnectionError(f"Failed to connect to {CCS}")
            ccs = await resp.json()

        contributors = []

        for i in ccs:
            realm = {
                "ASIA": api.Region.SEA,
                "NA": api.Region.NA,
                "EU": api.Region.EU,
            }[i["realm"]]

            i = Contributor(i["name"], i["links"], i["lang"].split(","), realm)

            contributors.append(i)
        self.bot.contributors = contributors
        return self.bot.contributors

    async def make_twitch_embed(self, member: discord.Member) -> discord.Embed:
        """Generate the embed for the twitch user"""

        if not isinstance(member.activity, discord.Streaming):
            return discord.Embed(title="This user is not streaming")

        embed = discord.Embed(title=member.activity.name)
        embed.url = member.activity.url

        desc = []

        if twitch_name := member.activity.twitch_name:
            embed.colour = 0x9146FF

            info = await self.bot.twitch.fetch_channel(twitch_name)

            if info.delay > 0:
                minutes, seconds = divmod(info.delay, 60)
                delay = f"{minutes} minutes"
                if seconds:
                    delay += f" {seconds} seconds"
                embed.add_field(name="Stream Delay", value=delay)

            desc.append(flags.get_flag(info.language))
            user = await info.user.fetch(force=True)
            settings = await user.fetch_chat_settings()

            modes = []
            if settings.emote_mode:
                modes.append("This channel is in emote only mode")
            if settings.follower_mode:
                fmd = settings.follower_mode_duration
                modes.append(f"This channel is in {fmd} minute follower mode.")
            if settings.subscriber_mode:
                modes.append("This channel is in subscriber only mode.")
            if settings.slow_mode and settings.slow_mode_wait_time:
                smd = stringify_seconds(settings.slow_mode_wait_time)
                modes.append(f"This channel is in {smd} slow mode.")
            if modes:
                txt = "Chat Restrictions"
                embed.add_field(name=txt, value="\n".join(modes))

            time = timed_events.Timestamp().relative
            desc.append(f"{member.mention}: {time}")

            # Stream Tags
            tags: list[twitchio.Tag] = await user.fetch_tags()
            if tags:
                localised = ", ".join(
                    [i.localization_names["en-us"] for i in tags]
                )
                desc.append(f"\n**Tags**: {localised}")

            plt = member.activity.platform
            nom = user.display_name
            ico = member.display_avatar.url
            embed.set_author(name=f"{nom} went live on {plt}", icon_url=ico)
            embed.set_thumbnail(url=user.profile_image)

            game = member.activity.game

            type_ = user.broadcaster_type
            if type_ == user.broadcaster_type.partner:
                txt = f"Partner streaming {game}"
                embed.set_footer(text=txt, icon_url=PARTNER_ICON)
            elif type_ == user.broadcaster_type.affiliate:
                embed.set_footer(text=f"Affiliate streaming {game}")
            else:
                embed.set_footer(text=f"Streaming {game}")
        else:
            platform = member.activity.platform
            logger.error("Unhandled stream tracker platform %s", platform)

        embed.description = " ".join(desc)
        return embed

    @commands.Cog.listener()
    async def on_presence_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """When the user updates presence, we check if they started streaming
        We then check if they are in the channel's list of tracked users."""
        if not self.bot.tracker_channels:
            await self.update_cache()

        if before.activity == after.activity:
            return

        if not isinstance(after.activity, discord.Streaming):
            return

        chns = self.bot.tracker_channels
        tcs = [i for i in chns if i.channel.guild.id == after.guild.id]

        valid_channels: list[TrackerChannel] = []
        valid_role_ids = [r.id for r in after.roles]
        for i in tcs:
            for role in i.tracked:
                if role.id in valid_role_ids:
                    valid_channels.append(i)
                    break

        if not valid_channels:
            return

        embed = await self.make_twitch_embed(after)
        for i in valid_channels:
            try:
                await i.channel.send(embed=embed)
            except discord.HTTPException:
                continue

    # TODO: Create a view, with CC & Language Filtering.
    @discord.app_commands.command()
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(
        contributor="Get streamers who are/not members of the CC program"
    )
    async def streams(
        self,
        interaction: discord.Interaction[PBot],
        contributor: typing.Optional[bool] = None,
    ) -> discord.InteractionMessage:
        """Get a list of current World of Warships streams on Twitch"""

        await interaction.response.defer()

        ftch = await self.bot.twitch.fetch_streams(game_ids=[WOWS_GAME_ID])

        streams = []
        for i in ftch:
            views = i.viewer_count
            timestamp = timed_events.Timestamp(i.started_at)
            stm = Stream(i.language, i.user, views, i.title.strip(), timestamp)
            streams.append(stm)

        if contributor is not None:
            cc_twitch = "".join(i.markdown for i in self.bot.contributors)
            for i in streams:
                if f"http://www.twitch.tv/{i.user}" in cc_twitch:
                    i.contributor = True
            streams = [i for i in streams if i.contributor is contributor]

        embed = discord.Embed(title="Live World of Warships Streams")
        embed.colour = 0x9146FF
        embed.set_thumbnail(url=TWITCH_LOGO)
        embed.url = TWITCH_DIRECTORY

        ordered = sorted(streams, key=lambda x: x.viewers, reverse=True)
        rows = [i.row for i in ordered]

        rows = embed_utils.rows_to_embeds(embed, rows)
        return await view_utils.Paginator(interaction, rows).update()

    async def make_cc_embed(self, cont: Contributor) -> discord.Embed:
        """Create an embed about the CC"""
        embed = discord.Embed(title=f"{cont.name} ({cont.region.name})")
        embed.description = cont.markdown
        embed.colour = cont.region.colour
        embed.set_author(name="World of Warships Community Contributor")
        embed.set_thumbnail(url=CC_BADGE)

        try:
            twitch = next(i for i in cont.links if "twitch" in i)
            twitch_id = twitch.split("/")[-1]
            user = await self.bot.twitch.fetch_users(names=[twitch_id])
            user = user[0]
            embed.set_image(url=user.profile_image)

            # TODO: Fetch Twitch Info into Embed
            # TODO: Official channel Schedule
            # https://dev.twitch.tv/docs/api/reference#get-channel-stream-schedule
            # https://dev.twitch.tv/docs/api/reference#get-channel-emotes
            print(dir(user))
        except StopIteration:
            pass

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
        interaction: discord.Interaction[PBot],
        search: typing.Optional[str] = None,
        region: typing.Optional[REGIONS] = None,
        language: typing.Optional[str] = None,
    ) -> discord.InteractionMessage:
        """Fetch The List of all CCs"""

        await interaction.response.defer(thinking=True)

        ccs = self.bot.contributors

        if search is not None:
            ccs = [i for i in ccs if search == i.name]
            if len(ccs) == 1:  # Send an individual Profile
                embed = await self.make_cc_embed(ccs[0])
                return await interaction.edit_original_response(embed=embed)

        if search is not None:
            ccs = [i for i in ccs if search in i.auto_complete]

        if region is not None:
            ccs = [i for i in ccs if i.region.db_key == region]

        if language is not None:
            ccs = [i for i in ccs if language in i.language_names]

        embed = discord.Embed(title="World of Warships Community Contributors")
        embed.url = PROGRAM_INFO
        embed.set_thumbnail(
            url="https://i.postimg.cc/Y0r43P0m/CC-Logo-Small.png"
        )
        embed.colour = discord.Colour.dark_blue()

        embeds = embed_utils.rows_to_embeds(embed, [i.row for i in ccs])
        return await view_utils.Paginator(interaction, embeds).update()

    track = discord.app_commands.Group(
        name="twitch_tracker",
        description="Go Live Tracker",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @track.command()
    @discord.app_commands.describe(
        role="Role to track Twitch Go Lives from",
        channel="Add to Which channel?",
    )
    async def add(
        self,
        interaction: discord.Interaction[PBot],
        role: discord.Role,
        channel: typing.Optional[discord.TextChannel] = None,
    ) -> discord.InteractionMessage:
        """Add a role of this discord to the twitch tracker."""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        try:
            tkr = self.bot.tracker_channels
            chan = next(i for i in tkr if i.channel.id == channel.id)
        except StopIteration:
            chan = TrackerChannel(channel)
            success = await chan.view(interaction).creation_dialogue()
            if not success:
                text = "Ticker Creation Cancelled"
                edit = interaction.edit_original_response
                return await edit(content=text, view=None)

            self.bot.tracker_channels.append(chan)

        await chan.track(role)
        txt = f"Added {role.name} to {channel.mention} Twitch Tracker"
        return await chan.view(interaction).update(content=txt)

    @track.command()
    @discord.app_commands.describe(channel="Manage which channel's Trackers?")
    async def manage(
        self,
        interaction: discord.Interaction[PBot],
        channel: typing.Optional[discord.TextChannel] = None,
    ) -> discord.InteractionMessage:
        """View or remove tracked twitch go live roles"""

        await interaction.response.defer(thinking=True)
        if channel is None:
            channel = typing.cast(discord.TextChannel, interaction.channel)

        try:
            tkr = self.bot.tracker_channels
            chan = next(i for i in tkr if i.channel.id == channel.id)
        except StopIteration:
            chan = TrackerChannel(channel)
            success = await chan.view(interaction).creation_dialogue()
            if success:
                self.bot.tracker_channels.append(chan)
        return await chan.view(interaction).update()

    # Database Cleanup
    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> list[TrackerChannel]:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM tracker_channels WHERE channel_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, channel.id)

        # Lists are Mutable.
        trk = self.bot.tracker_channels
        trk = [i for i in trk if i.channel.id != channel.id]
        return trk


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(TwitchTracker(bot))
