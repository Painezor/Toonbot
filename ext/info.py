"""Commands about the meta-state of the bot and information about users and servers"""
import datetime
import typing
from collections import Counter
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import timed_events, embed_utils

INV = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
      "&scope=bot%20applications.commands"


class Info(commands.Cog):
    """Get information about users or servers."""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "ℹ"
        reload(timed_events)
        if not hasattr(self.bot, "commands_used"):
            self.bot.commands_used = Counter()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        """A counter for how many commands have been used this session"""
        self.bot.commands_used[str(ctx.command)] += 1

    @commands.Cog.listener()
    async def on_slash_command(self, ctx):
        """A counter for how many slash commands have been used this session"""
        self.bot.commands_used[f"{ctx.command} (SLASH)"] += 1

    @commands.slash_command()
    async def about(self, ctx):
        """Tells you information about the bot itself."""
        e = discord.Embed(colour=0x2ecc71, timestamp=self.bot.user.created_at)
        owner = await self.bot.fetch_user(self.bot.owner_id)
        e.set_footer(text=f"Toonbot is coded by {owner} and was created on ")
        e.set_thumbnail(url=ctx.me.display_avatar.url)
        e.title = f"Toonbot ({ctx.me.display})" if not ctx.me.display_name == "Toonbot" else "Toonbot"

        # statistics
        total_members = sum(len(s.members) for s in self.bot.guilds)
        members = f"{total_members} Members across {len(self.bot.guilds)} servers."

        e.description = f"I do football lookup related things.\n I have {members}"

        technical_stats = f"{datetime.datetime.now() - self.bot.initialised_at}\n"
        technical_stats += f"{sum(self.bot.commands_used.values())} commands ran this session."
        e.add_field(name="Uptime", value=technical_stats, inline=False)

        view = discord.ui.View()
        s = ("Join my Support Server", "http://www.discord.gg/a5NHvPx")
        i = ("Invite me to your server", INV)
        d = ("Donate", "https://paypal.me/Toonbot")
        for label, link in [s, i, d]:
            view.add_item(discord.ui.Button(style=discord.ButtonStyle.url, url=link, label=label))

        await self.bot.reply(ctx, embed=e, view=view)

    @commands.slash_command()
    async def invite(self, ctx):
        """Get the bots invite link"""
        view = discord.ui.View()
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.url, url=INV, label="Invite me to your server"))
        e = discord.Embed(description="Use the button below to invite me to your server.")
        await self.bot.reply(ctx, embed=e, view=view, ephemeral=True)

    @commands.slash_command()
    async def permissions(self, ctx, *, member: discord.Member = None):
        """Shows a member's permissions."""
        if not ctx.channel.permissions_for(ctx.author).manage_roles:
            return await self.bot.error(ctx, "You need manage roles permissions to see a member's permissions.")

        if member is None:
            member = ctx.author
        permissions = ctx.channel.permissions_for(member)
        permissions = "\n".join([f"{i[0]} : {i[1]}" for i in permissions])
        await self.bot.reply(ctx, content=f"```yaml\n{permissions}```")

    @commands.slash_command()
    async def info(self, ctx, *, member: discord.Member = None):
        """Shows info about a member, or yourself."""
        member = ctx.author if member is None else member

        e = discord.Embed(colour=member.colour)
        e.set_author(name=member)
        if member.avatar:
            e.set_thumbnail(url=member.display_avatar.url)
        e.description = f"{'🤖 ' if member.bot else ''}{member.mention}\nUser ID: {member.id}"
        try:
            e.description += "\n📱 Using mobile app." if member.is_on_mobile() else ""
            voice = member.voice
            if voice is not None:
                voice = voice.channel
                voice_other = len(voice.members) - 1
                voice = f'In voice channel {voice.mention} {f"with {voice_other} others" if voice_other else "alone"}'
                e.description += f'\n\n{voice}'
        except AttributeError:  # User.
            pass

        roles = [role.mention for role in reversed(member.roles) if not role.position == 0]
        if roles:
            e.add_field(name='Roles', value=' '.join(roles))

        if member.banner is not None:
            e.set_image(url=member.banner.url)

        shared = sum(1 for m in self.bot.get_all_members() if m.id == member.id) - 1
        if shared:
            e.set_footer(text=f"User shares {shared} discords with Toonbot")

        try:
            e.description += f'\nJoined Server: {timed_events.Timestamp(member.joined_at).countdown}'
        except AttributeError:
            pass
        e.description += f'\nCreated Account: {timed_events.Timestamp(member.created_at).countdown}'

        await self.bot.reply(ctx, embed=e)

    @commands.slash_command(guild_ids=[250252535699341312])
    async def server_info(self, ctx):
        """Shows information about the server"""
        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be ran in DMs.")

        e = discord.Embed()
        e.title = ctx.guild.name

        e.description = ctx.guild.descritpion if ctx.guild.description is not None else ""
        e.description += f"Guild ID: {ctx.guild.id}"
        try:
            e.description += f"\nOwner: {ctx.guild.owner.mention}"
        except AttributeError:
            pass
        e.description += f'\n\n{len(ctx.guild.members)} Members'

        # figure out what channels are 'secret'
        text_channels = 0
        for channel in ctx.guild.channels:
            text_channels += isinstance(channel, discord.TextChannel)
        regular_channels = len(ctx.guild.channels)
        voice_channels = regular_channels - text_channels

        e.description += f"\n{regular_channels} text channels "
        if voice_channels:
            e.description += f"\n{voice_channels} Voice channels"

        if ctx.guild.premium_subscription_count:
            e.description += f"\n\n{ctx.guild.premium_subscription_count} Nitro Boosts (Tier {ctx.guild.premium_tier})"

        if ctx.guild.banner is not None:
            e.set_image(url=ctx.guild.banner.url)
        elif ctx.guild.discovery_splash is not None:
            e.set_image(url=ctx.guild.discovery_splash_url)

        if ctx.guild.icon:
            e.set_thumbnail(url=ctx.guild.icon.url)
            e.colour = await embed_utils.get_colour(str(ctx.guild.icon.url))

        emojis = ""
        for emoji in ctx.guild.emojis:
            if len(emojis) + len(str(emoji)) < 1024:
                emojis += str(emoji)

        if emojis:
            e.add_field(name="Emotes", value=emojis, inline=False)

        e.description += f"\n**Emotes**: {len(emojis)} / {ctx.guild.emoji_limit} slots used."
        e.description += f"\n**Stickers**: {len(ctx.guild.stickers)} / {ctx.guild.sticker_limit} slots used."

        try:
            vanity = await ctx.guild.vanity_invite()
            if vanity is not None:
                e.add_field(name="Server Vanity invite", value=vanity)
        except discord.Forbidden:
            pass

        roles = [role.mention for role in ctx.guild.roles]
        e.add_field(name='Roles', value=', '.join(roles) if len(roles) < 20 else f'{len(roles)} roles', inline=False)
        e.add_field(name="Creation Date", value=timed_events.Timestamp(ctx.guild.created_at).date_relative)
        await self.bot.reply(ctx, embed=e)

    @commands.slash_command()
    async def avatar(self, ctx, user: typing.Union[discord.User, discord.Member] = None):
        """Shows a member's avatar"""
        if user is None:
            user = ctx.author
        e = discord.Embed()
        e.colour = user.color
        e.set_footer(text=user.display_avatar.url)
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        e.description = f"{user.mention}'s avatar"
        e.set_image(url=user.display_avatar.url)
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the Info cog into the bot"""
    bot.add_cog(Info(bot))
