"""Commands about the meta-state of the bot and information about users and servers"""
import datetime
import typing
from collections import Counter
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import timed_events, embed_utils


# TODO: Select / Button Pass.

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

    @commands.command()
    async def invite(self, ctx):
        """Get my invite link"""
        e = discord.Embed(colour=0x2ecc71, timestamp=self.bot.user.created_at)
        owner = await self.bot.fetch_user(self.bot.owner_id)
        e.set_footer(text=f"Toonbot is coded (badly) by {owner} and was created on ")
        e.set_thumbnail(url=ctx.me.display_avatar.url)
        e.title = f"{ctx.me.display_name} ({ctx.me})" if not ctx.me.display_name == "ToonBot" else "Toonbot"
        e.description = f"[Click to invite me](https://discordapp.com/oauth2/authorize?client_id=250051254783311873" \
                        f"&permissions=67488768&scope=bot)\n"
        await self.bot.reply(ctx, embed=e)

    @commands.command(aliases=['botstats', "uptime", "hello"])
    async def about(self, ctx):
        """Tells you information about the bot itself."""
        e = discord.Embed(colour=0x2ecc71, timestamp=self.bot.user.created_at)
        owner = await self.bot.fetch_user(self.bot.owner_id)
        e.set_footer(text=f"Toonbot is coded (badly) by {owner} and was created on ")
        e.set_thumbnail(url=ctx.me.display_avatar.url)
        e.title = f"{ctx.me.display_name} ({ctx.me})" if not ctx.me.display_name == "ToonBot" else "Toonbot"

        # statistics
        total_members = sum(len(s.members) for s in self.bot.guilds)
        members = f"{total_members} Members across {len(self.bot.guilds)} servers."
        
        prefixes = f"\nYou can use `.tb help` to see my commands."
        
        e.description = f"I do football lookup related things.\n I have {members}"
        e.description += prefixes
        
        technical_stats = f"{datetime.datetime.now() - self.bot.initialised_at}\n"
        technical_stats += f"{sum(self.bot.commands_used.values())} commands ran this session."
        e.add_field(name="Uptime", value=technical_stats, inline=False)
        
        invite_and_stuff = f"[Invite me to your server]" \
                           f"(https://discordapp.com/oauth2/authorize?client_id=250051254783311873" \
                           f"&permissions=67488768&scope=bot)\n"
        invite_and_stuff += f"[Join my Support Server](http://www.discord.gg/a5NHvPx)\n"
        
        e.add_field(name="Using me", value=invite_and_stuff, inline=False)
        e.add_field(name="Donate", value="If you'd like to donate, you can do so [here](https://paypal.me/Toonbot)")
        
        await self.bot.reply(ctx, embed=e)
    
    @commands.command(aliases=["perms"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def permissions(self, ctx, *, member: discord.Member = None):
        """Shows a member's permissions."""
        if member is None:
            member = ctx.author
        permissions = ctx.channel.permissions_for(member)
        permissions = "\n".join([f"{i[0]} : {i[1]}" for i in permissions])
        await self.bot.reply(ctx, text=f"```py\n{permissions}```")
    
    @commands.command(aliases=["lastmsg", "lastonline", "lastseen"], usage="seen @user")
    async def seen(self, ctx, target: discord.Member):
        """Find the last message from a user in this channel"""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        with ctx.typing():
            if ctx.author == target:
                return await self.bot.reply(ctx, text="Last seen right now, being an idiot.", ping=True)
            
            async for msg in ctx.channel.history(limit=1000):
                if msg.author.id == target.id:
                    c = f"Last message in {ctx.channel.mention} from {target.mention}: {msg.jump_url}"
                    break
                else:
                    c = "Couldn't find a recent message from that user."
            await self.bot.reply(ctx, text=c)
    
    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def info(self, ctx, *, member: typing.Union[discord.Member, discord.User] = None):
        """Shows info about a member.
        This cannot be used in private messages. If you don't specify
        a member then the info returned will be yours.
        """
        member = ctx.author if member is None else member

        e = discord.Embed(colour=member.colour)
        e.description = f"{'🤖 ' if member.bot else ''}{member.mention}\nUser ID: {member.id}"

        try:
            roles = [role.mention for role in reversed(member.roles) if not role.position == 0]
            e.add_field(name='Roles', value=' '.join(roles))
            status = str(member.status).title()

            if status == "Online":
                status = "🟢 Online\n"
            elif status == "Offline":
                status = "🔴 Offline\n"
            else:
                status = f"🟡 {status}\n"

            activity = member.activity
            try:
                activity = f"{discord.ActivityType[activity.type]} {activity.name}\n"
            except KeyError:  # Fix on custom status update.
                activity = ""
        except AttributeError:
            status = ""
            activity = ""
            pass

        shared = sum(1 for m in self.bot.get_all_members() if m.id == member.id) - 1

        e.set_author(name=str(member), icon_url=member.display_avatar.url)

        try:
            if member.is_on_mobile():
                e.description += "\n📱 Using mobile app."
        except AttributeError:  # User.
            pass

        if member.avatar:
            e.set_thumbnail(url=member.display_avatar.url)

        if isinstance(member, discord.Member):
            e.description += f'\nJoined Server: {timed_events.Timestamp(member.joined_at).countdown}'
        e.description += f'\nCreated Account: {timed_events.Timestamp(member.createrd_at).countdown}'

        try:
            voice = member.voice
            if voice is not None:
                voice = voice.channel
                voice_members = len(voice.members) - 1
                voice = f'In {voice.mention} {f"with {voice_members} others" if voice_members else "Alone"}'
                e.description += f'\n\n**Voice Chat**: {voice}'
        except AttributeError:
            pass

        if member.bot:
            e.description += "\n**🤖 This user is a bot account.**"

        if shared:
            e.set_footer(text=f"User shares {shared} discords with Toonbot")

        await self.bot.reply(ctx, embed=e)
    
    @info.command(name='guild', aliases=["server"])
    @commands.guild_only()
    async def server_info(self, ctx):
        """Shows information about the server"""
        guild = ctx.guild
        
        # figure out what channels are 'secret'
        text_channels = 0
        for channel in guild.channels:
            text_channels += isinstance(channel, discord.TextChannel)
        
        regular_channels = len(guild.channels)
        voice_channels = len(guild.channels) - text_channels
        
        e = discord.Embed()
        e.title = guild.name
        try:
            e.description = f"Owner: {guild.owner.mention}\nGuild ID: {guild.id}"
        except AttributeError:
            e.description = f"Guild ID: {guild.id}"
        e.description += f'\n\n{guild.member_count} Members' \
                         f"\n{regular_channels} text channels "
        if voice_channels:
            e.description += f"and {voice_channels} Voice channels"
            
        if guild.premium_subscription_count:
            e.description += f"\n{guild.premium_subscription_count} Nitro Boosts"
        
        if guild.discovery_splash:
            e.set_image(url=guild.discovery_splash_url)

        if guild.icon:
            e.set_thumbnail(url=guild.icon_url)
            e.colour = await embed_utils.get_colour(str(guild.icon_url))

        emojis = ""
        for emoji in guild.emojis:
            if len(emojis) + len(str(emoji)) < 1024:
                emojis += str(emoji)
        if emojis:
            e.add_field(name="Custom Emojis", value=emojis, inline=False)

        if guild.vanity_url is not None:
            e.add_field(name="Custom invite URL", value=guild.vanity_url)

        roles = [role.mention for role in guild.roles]
        e.add_field(name='Roles', value=', '.join(roles) if len(roles) < 20 else f'{len(roles)} roles', inline=False)
        e.add_field(name="Creation Date", value=timed_events.Timestamp(guild.created_at).date_relative)
        e.set_footer(text=f"\nRegion: {str(guild.region).title()}")
        await self.bot.reply(ctx, embed=e)
    
    @commands.command()
    async def avatar(self, ctx, user: typing.Union[discord.User, discord.Member] = None):
        """Shows a member's avatar"""
        if user is None:
            user = ctx.author
        e = discord.Embed()
        e.colour = user.color
        e.set_footer(text=user.display_avatar.url)
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        e.description = f"{user.mention}'s avatar"
        e.set_image(url=str(user.display_avatar.url))
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the Info cog into the bot"""
    bot.add_cog(Info(bot))
