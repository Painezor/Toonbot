"""Track when users begin streaming"""
from __future__ import annotations

import logging
import typing
import json

import discord
from discord import TextChannel
import twitchio  # type: ignore
from discord.ext import commands

from ext.logs import stringify_seconds
from ext.utils import embed_utils, flags, timed_events, view_utils

if typing.TYPE_CHECKING:
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[PBot]
    User: typing.TypeAlias = discord.User | discord.Member

with open("credentials.json", mode="r", encoding="utf-8") as fun:
    creds = json.load(fun)
    client = twitchio.Client.from_client_credentials(**creds["Twitch API"])


PARTNER_ICON = """https://static-cdn.jtvnw.net/badges/v1/d12a2e27-16f6-41d0-ab7
7-b780518f00a3/1"""
TWITCH_LOGO = """https://seeklogo.com/images/T/twitch-tv-logo-51C922E0F0-seeklo
go.com.png"""
TWITCH_DIRECTORY = "https://www.twitch.tv/directory/game/World%20of%20Warships"
WOWS_GAME_ID = 32502

logger = logging.getLogger("twitch")


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
        self.user: str | None = user.name
        self.title: str = title
        self.timestamp: timed_events.Timestamp = timestamp
        self.contributor: bool | None = None

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


# TODO: Select as decorator, Make Paginator
class TrackerConfig(view_utils.DropdownPaginator):
    """Config View for a Twitch Tracker channel"""

    def __init__(
        self,
        invoker: User,
        channel: TextChannel,
        tracked_roles: list[discord.Role],
    ):
        self.channel: TextChannel = channel
        self.tracked: list[discord.Role] = tracked_roles

        embed = discord.Embed(colour=0x9146FF, title="Twitch Go Live Tracker")
        embed.set_thumbnail(url=TWITCH_LOGO)

        missing: list[str] = []
        perms = channel.permissions_for(channel.guild.me)
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

        options: list[discord.SelectOption] = []
        rows: list[str] = []
        for i in sorted(self.tracked, key=lambda role: role.name):
            opt = discord.SelectOption(label=i.name, value=str(i.id))
            opt.emoji = i.unicode_emoji
            opt.description = str(i.id)
            options.append(opt)
            rows.append(i.mention)

        super().__init__(invoker, embed, rows, options, multi=True)

    @discord.ui.select(placeholder="Remove tracked roles", row=1)
    async def dropdown(self, interaction: Interaction, sel: discord.ui.Select):
        """Bulk remove tracked items from a Twitch Tracker channel"""
        # Ask user to confirm their choice.
        view = view_utils.Confirmation(interaction.user, "Remove", "Cancel")
        view.true.style = discord.ButtonStyle.red

        mentions = "\n•".join(f"<@&{i}>" for i in sel.values)

        mention = self.channel.mention
        embed = discord.Embed()
        embed.description = f"Remove items from {mention}?\n\n•{mentions}"

        edit = interaction.response.edit_message
        await edit(embed=embed, view=view)
        await view.wait()

        if view.value:
            sql = """DELETE FROM tracker_ids
                     WHERE (channel_id, role_id) = ($1, $2)"""

            role_ids: list[int] = [int(r) for r in sel.values]
            rows = [(self.channel.id, r) for r in role_ids]
            await interaction.client.db.executemany(sql, rows)
            self.tracked = [t for t in self.tracked if t.id not in role_ids]
            embed = discord.Embed(title="Tracked roles removed")
            embed.description = f"{mention}\n{mentions}"
            embed_utils.user_to_footer(embed, interaction.user)
            await interaction.followup.send(embed=embed)

        return await edit(view=self)

    async def track(
        self, interaction: Interaction, role: discord.Role
    ) -> list[discord.Role]:
        """Add a user to the list of tracked users for Go Live notifications"""
        sql = """INSERT INTO tracker_ids (channel_id, role_id)
                 VALUES ($1, $2)"""
        await interaction.client.db.execute(sql, self.channel.id, role.id)

        self.tracked.append(role)
        return self.tracked


class TwitchTracker(commands.Cog):
    """Track when users go live to twitch."""

    def __init__(self, bot: PBot) -> None:
        self.bot: PBot = bot

    async def cog_load(self) -> None:
        """On cog load, generate list of Tracker Channels"""
        self.twitch = client
        await client.connect()

    async def get_config(
        self, interaction: Interaction, channel: TextChannel | None
    ) -> TrackerConfig | None:
        if channel is None:
            if isinstance(interaction.channel, discord.TextChannel):
                channel = interaction.channel
            else:
                return

        sql = """SELECT * FROM tracker_ids WHERE channel_id = $1"""
        records = await self.bot.db.fetch(sql, channel.id)

        if records:
            roles = [channel.guild.get_role(r["role_id"]) for r in records]
            _roles = [i for i in roles if i]
        else:
            gid = channel.guild.id
            sql = """INSERT INTO guild_settings (guild_id) VALUES ($1)
                     ON CONFLICT DO NOTHING"""
            await interaction.client.db.execute(sql, gid)
            sql = """INSERT INTO tracker_channels (guild_id, channel_id)
                     VALUES ($1, $2) ON CONFLICT DO NOTHING"""
            await interaction.client.db.execute(sql, gid, channel.id)
            _roles = []
        return TrackerConfig(interaction.user, channel, _roles)

    async def make_twitch_embed(self, member: discord.Member) -> discord.Embed:
        """Generate the embed for the twitch user"""

        if not isinstance(member.activity, discord.Streaming):
            return discord.Embed(title="This user is not streaming")

        embed = discord.Embed(title=member.activity.name)
        embed.url = member.activity.url

        desc: list[str] = []

        if twitch_name := member.activity.twitch_name:
            embed.colour = 0x9146FF

            info = await self.twitch.fetch_channel(twitch_name)

            if info.delay > 0:
                minutes, seconds = divmod(info.delay, 60)
                delay = f"{minutes} minutes"
                if seconds:
                    delay += f" {seconds} seconds"
                embed.add_field(name="Stream Delay", value=delay)

            desc.append(flags.get_flag(info.language))
            user = await info.user.fetch(force=True)
            settings = await user.fetch_chat_settings()

            modes: list[str] = []
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
        if before.activity == after.activity:
            return

        if not isinstance(after.activity, discord.Streaming):
            return

        sql = """SELECT * FROM tracker_channels LEFT OUTER JOIN tracker_ids
                 ON tracker_channels.channel_id = tracker_ids.channel_id
                 WHERE guild_id = $1"""
        records = await self.bot.db.fetch(sql, after.guild.id)

        bad: list[int] = []

        role_ids = [i.id for i in after.roles]
        for r in records:
            channel = self.bot.get_channel(r["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                continue

            if channel.is_news():
                bad.append(r["channel_id"])
                continue

            if r["role_id"] not in role_ids:
                continue

            embed = await self.make_twitch_embed(after)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                bad.append(channel.id)

        if bad:
            logger.info("Twitch Tracker found %s bad channels", len(bad))

    # TODO: Create a view, with CC & Language Filtering.
    @discord.app_commands.command()
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(
        contributor="Get streamers who are/not members of the CC program"
    )
    async def streams(
        self,
        interaction: Interaction,
        contributor: bool | None = None,
    ) -> None:
        """Get a list of current World of Warships streams on Twitch"""

        await interaction.response.defer()

        ftch = await self.twitch.fetch_streams(game_ids=[WOWS_GAME_ID])

        streams: list[Stream] = []
        for i in ftch:
            views = i.viewer_count
            timestamp = timed_events.Timestamp(i.started_at)
            stm = Stream(i.language, i.user, views, i.title.strip(), timestamp)
            streams.append(stm)

        if contributor is not None:
            from .wows_ccs import CommunityContributors

            cog = interaction.client.get_cog(
                CommunityContributors.__qualname__
            )
            if not isinstance(cog, CommunityContributors):
                ccs = []
            else:
                ccs = cog.contributors

            cc_twitch = "".join(i.markdown for i in ccs)
            for i in streams:
                if f"http://www.twitch.tv/{i.user}" in cc_twitch:
                    i.contributor = True
            streams = [i for i in streams if i.contributor is contributor]

        embed = discord.Embed(colour=0x914644)
        embed.title = "Live World of Warships Streams"
        embed.set_thumbnail(url=TWITCH_LOGO)
        embed.url = TWITCH_DIRECTORY

        streams.sort(key=lambda x: x.viewers, reverse=True)
        rows = [i.row for i in streams]

        embeds = embed_utils.rows_to_embeds(embed, rows)
        strms = view_utils.EmbedPaginator(interaction.user, embeds)
        await interaction.response.send_message(view=strms, embed=embeds[0])
        strms.message = await interaction.original_response()

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
        interaction: Interaction,
        role: discord.Role,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Add a role of this discord to the twitch tracker."""
        cfg = await self.get_config(interaction, channel)
        if cfg is None:
            return

        embed = discord.Embed(colour=discord.Colour.dark_blue())
        rol = role.mention
        embed.description = f"Added {rol} to {cfg.channel.mention} Tracker"
        embed_utils.user_to_footer(embed, interaction.user)

        await cfg.track(interaction, role)
        await interaction.response.send_message(view=cfg, embed=cfg.embeds[0])
        await interaction.followup.send(embed=embed)
        cfg.message = await interaction.original_response()

    @track.command()
    @discord.app_commands.describe(channel="Manage which channel's Trackers?")
    async def manage(
        self,
        interaction: Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """View or remove tracked twitch go live roles"""
        cfg = await self.get_config(interaction, channel)
        if cfg is None:
            return
        await interaction.response.send_message(view=cfg, embed=cfg.embeds[0])
        cfg.message = await interaction.original_response()

    # Database Cleanup
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove dev blog trackers from deleted channels"""
        sql = """DELETE FROM tracker_channels WHERE channel_id = $1"""
        await self.bot.db.execute(sql, channel.id)


async def setup(bot: PBot) -> None:
    """Add the cog to the bot"""
    await bot.add_cog(TwitchTracker(bot))
