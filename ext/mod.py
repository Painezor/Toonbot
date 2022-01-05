"""Moderation Commands"""
import asyncio
# import datetime
import typing
from collections import defaultdict

import discord
from discord.ext import commands

from ext.utils import embed_utils, view_utils


# from ext.utils.timed_events import parse_time
# TODO: Find a way to use a custom converter for temp mute/ban and merge into main command.
# TODO: Select / Button Pass.


async def get_prefix(bot, message):
    """Get allowed prefixes for message context"""
    pref = [".tb ", "!", "-", "`", "!", "?", ""] if message.guild is None else bot.prefix_cache[message.guild.id]
    pref = [".tb "] if not pref else pref
    return commands.when_mentioned_or(*pref)(bot, message)


def me_or_mod(self):
    """Verify the invoker is a moderator, or is Painezor."""

    def predicate(ctx):
        """THe actual check"""
        return ctx.channel.permissions_for(ctx.author).manage_channels or ctx.author.id == self.bot.owner_id

    return commands.check(predicate)


class Mod(commands.Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "🛡️"
        self.bot.loop.create_task(self.update_cache())
        self.bot.prefix_cache = defaultdict(list)
        self.bot.loop.create_task(self.update_prefixes())
        self.bot.command_prefix = get_prefix
        if not hasattr(self.bot, "lockdown_cache"):
            self.bot.lockdown_cache = {}

    # Listeners
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Create database entry for new guild"""
        await self.create_guild(guild.id)
        await self.update_prefixes()

    # @commands.Cog.listener()
    # async def on_guild_remove(self, guild):
    #     """Delete guild's info upon leaving one."""
    #     await self.delete_guild(guild.id)

    async def create_guild(self, guild_id):
        """Insert the database entry for a new guild"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""
                with gid as (INSERT INTO guild_settings (guild_id) VALUES ($1) RETURNING guild_id)
                INSERT INTO prefixes (prefix, guild_id)
                VALUES ($2, (SELECT guild_id FROM gid)) ON CONFLICT DO NOTHING
                """, guild_id, '.tb ')
        finally:
            await self.bot.db.release(connection)
            
    async def delete_guild(self, guild_id):
        """Remove a guild's settings from the database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM guild_settings WHERE guild_id = $1""", guild_id)
        finally:
            await self.bot.db.release(connection)
    
    async def update_prefixes(self):
        """Reload prefix cache guild"""
        self.bot.prefix_cache.clear()
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""SELECT * FROM prefixes""")
        await self.bot.db.release(connection)

        for r in records:
            self.bot.prefix_cache[r["guild_id"]].append(r["prefix"])

        # Items ending in space must come first.
        for guild, pref_list in self.bot.prefix_cache.items():
            for i in range(len(pref_list)):
                if pref_list[i].endswith(' '):
                    pref_list = [pref_list[i]] + pref_list[:i] + pref_list[i + 1:]
            self.bot.prefix_cache[guild] = pref_list

        for g in self.bot.guilds:
            if g.id not in self.bot.prefix_cache:
                await self.create_guild(g.id)
            
    async def update_cache(self):
        """Refresh local cache of disabled commands"""
        self.bot.disabled_cache = defaultdict(list)
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM disabled_commands""")
        await self.bot.db.release(connection)
        
        for r in records:
            try:
                self.bot.disabled_cache[r["guild_id"]].append(r["command"])
            except KeyError:
                self.bot.disabled_cache.update({r["guild_id"]: [r["command"]]})
    
    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def leave(self, ctx):
        """Politely ask me to leave the server."""
        m = await self.bot.reply(ctx, content='Are you sure you want me to go? All of your settings will be wiped.',
                                 )
        await embed_utils.bulk_react(ctx, m, ['✅', '🚫'])

        def check(reaction, user):
            """Check user reacting is the one invoking the message"""
            if reaction.message.id == m.id and user == ctx.author:
                emoji = str(reaction.emoji)
                return emoji.startswith(('✅', '🚫'))

        try:
            res = await self.bot.wait_for("reaction_add", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await self.bot.reply(ctx, content="Response timed out after 30 seconds, I will stay for now.",
                                        )
        res = res[0]

        if res.emoji.startswith('✅'):
            await self.bot.reply(ctx, content='Farewell!')
            await ctx.guild.leave()
        else:
            await self.bot.reply(ctx, content="Okay, I'll stick around a bit longer then.")
            await m.clear_reactions()

    @commands.command(aliases=['nick'])
    @commands.has_permissions(manage_nicknames=True)
    async def name(self, ctx, *, new_name: str):
        """Rename the bot for your server."""
        await ctx.me.edit(nick=new_name)
        await self.bot.reply(ctx, content=f"My new name is {new_name} on your server.")

    @commands.command(usage="[Channel] <what you want the bot to say>")
    @commands.check(me_or_mod)
    async def say(self, ctx, destination: typing.Optional[discord.TextChannel] = None, *, msg=None):
        """Say something as the bot in specified channel"""
        if msg is None:
            return await self.bot.reply(ctx, content="You need to specify a message to send.")

        if destination is None:
            destination = ctx
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        assert destination.guild.id == ctx.guild.id, "You cannot send messages to other servers."
        assert len(msg) < 2000, "Message too long. Keep it under 2000."
        await destination.send(msg)
    
    @commands.command(usage="topic <New Channel Topic>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def topic(self, ctx, *, new_topic):
        """Set the topic for the current channel"""
        await ctx.channel.edit(topic=new_topic)
        await self.bot.reply(ctx, content=f"Topic changed to: '{new_topic}'")
    
    @commands.command(usage="pin <(Message ID you want pinned) or (new message to pin.)>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def pin(self, ctx, *, message: typing.Union[discord.Message, int, str]):
        """Pin a message to the current channel"""
        if isinstance(message, int):
            message = await ctx.channel.fetch_message(message)
        elif isinstance(message, str):
            message = await self.bot.reply(ctx, content=message)
        await message.pin()
    
    @commands.command(usage="rename <member> <new name>")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def rename(self, ctx, member: discord.Member, nickname: commands.clean_content):
        """Rename a member"""
        try:
            await member.edit(nick=str(nickname))
        except discord.Forbidden:
            await self.bot.reply(ctx, content="⛔ I can't change that member's nickname.")
        except discord.HTTPException:
            await self.bot.reply(ctx, content="❔ Member edit failed.")
        else:
            await self.bot.reply(ctx, content=f"{member.mention} has been renamed.")
    
    @commands.command(usage="delete_empty_roles")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def delete_empty_roles(self, ctx):
        """Delete any unused roles on the server"""
        targets = [i for i in ctx.guild.roles if i.name.lower() != "muted" and not i.members]
        deleted = []
        for i in targets:
            deleted.append(i.name)
            await i.delete()
        await self.bot.reply(ctx, content=f'Found and deleted {len(deleted)} empty roles: {", ".join(deleted)}')
    
    @commands.command(usage="kick <@member1  @member2 @member3> <reason>")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, members: commands.Greedy[discord.Member], *, reason="unspecified reason."):
        """Kicks the user from the server"""
        if not members:
            return
        
        success = []
        fail = []
        
        for i in members:
            try:
                await i.kick(reason=f"{ctx.author.name}: {reason}")
            except discord.Forbidden:
                fail.append(f"{i} (Higher Role)")
            except discord.HTTPException:
                fail.append(f"{i.mention} (Error)")
            else:
                success.append(i.mention)
        
        if success:
            await self.bot.reply(ctx, content=f"✅ {', '.join(success)} kicked for: \"{reason}\".")
        if fail:
            await self.bot.reply(ctx, content=f"⚠ Kicking failed for {', '.join(fail)}.")
            
    @commands.command(usage="ban <@member1 [user_id2, @member3, @member4]> "
                            "<(Optional: Days to delete messages from)> <(Optional: reason)>",
                      aliases=["hackban"])
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, targets: commands.Greedy[typing.Union[discord.Member, int]],
                  delete_days: typing.Optional[int] = 0, *, reason="Not specified"):
        """Bans a list of members (or User IDs) from the server, deletes all messages for the last x days"""
        for i in targets:
            if isinstance(i, discord.Member):
                try:
                    delete_days = 7 if delete_days > 7 else delete_days
                    await i.ban(reason=f"{ctx.author.name}: {reason}", delete_message_days=delete_days)
                    outstr = f"☠ {i.mention} was banned by {ctx.author} for: \"{reason}\""
                    if delete_days:
                        outstr += f", messages from last {delete_days} day(s) were deleted."
                    await self.bot.reply(ctx, content=outstr)
                except discord.Forbidden:
                    await self.bot.reply(ctx, content=f"⛔ Sorry, I can't ban {i.mention}.")
                except discord.HTTPException:
                    await self.bot.reply(ctx, content=f"⚠ Banning failed for {i.mention}.")
                except Exception as e:
                    await self.bot.reply(ctx, content=f"⚠ Banning failed for {i.mention}.")
                    print("Failed while banning member\n", e)
            else:
                try:
                    await self.bot.http.ban(i, ctx.message.guild.id)
                    target = await self.bot.fetch_user(i)
                    outstr = f"☠ UserID {i} {target} was banned for reason: \"{reason}\""
                    if delete_days:
                        outstr += f", messages from last {delete_days} day(s) were deleted."
                    await self.bot.reply(ctx, content=outstr)
                except discord.HTTPException:
                    await self.bot.reply(ctx, content=f"⚠ Banning failed for UserID# {i}.")
                except Exception as e:
                    await self.bot.reply(ctx, content=f"⚠ Banning failed for UserID# {i}.")
                    print("Failed while banning ID#.\n", e)
    
    @commands.command(usage="unban <UserID of member: e.g. 13231232131> ")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, *, who):
        """Unbans a user from the server"""
        # Try to get by user_id.
        if who.isdecimal():
            user = discord.Object(who)
            await ctx.guild.unban(user)
            try:
                await self.bot.http.unban(who, ctx.guild.id)
            except discord.Forbidden:
                await self.bot.reply(ctx, content="⛔ I can't unban that user.")
            except discord.HTTPException:
                await self.bot.reply(ctx, content="❔ Unban failed.")
            else:
                await self.bot.reply(ctx, content=f"🆗 {who} was unbanned")
        else:
            try:
                un, discrim = who.split('#')
                for i in await ctx.guildG.bans():
                    if i.user.display_name == un and i.discriminator == discrim:
                        try:
                            await self.bot.http.unban(i.user.id, ctx.guild.id)
                        except discord.Forbidden:
                            await self.bot.reply(ctx, content="⛔ I can't unban that user.")
                        except discord.HTTPException:
                            await self.bot.reply(ctx, content="❔ Unban failed.")
                        else:
                            await self.bot.reply(ctx, content=f"🆗 {who} was unbanned")
                        return  # Stop iterating when found.
            except ValueError:
                for i in await ctx.guild.bans():
                    if i.user.name == who:
                        try:
                            await self.bot.http.unban(i.user.id, ctx.guild.id)
                        except discord.Forbidden:
                            await self.bot.reply(ctx, content=f"⛔ I can't unban {i}.")
                        except discord.HTTPException:
                            await self.bot.reply(ctx, content=f"❔ Unban failed for {i.user}")
                        else:
                            await self.bot.reply(ctx, content=f"🆗 {i.user} was unbanned")
                        return  # Stop iterating when found.
    
    @commands.command(aliases=['bans'])
    @commands.has_permissions(view_audit_log=True)
    @commands.bot_has_permissions(view_audit_log=True)
    async def banlist(self, ctx):
        """Show the banlist for the server"""
        ban_lines = [f"\💀 {x.user.name}#{x.user.discriminator}: {x.reason}" for x in await ctx.guild.bans()]
        if not ban_lines:
            ban_lines = ["☠ No bans found!"]

        e = discord.Embed(color=0x111)
        n = f"≡ {ctx.guild.name} discord ban list"
        _ = ctx.guild.icon.url if ctx.guild.icon is not None else None
        e.set_author(name=n, icon_url=_)
        e.set_thumbnail(url="https://i.ytimg.com/vi/eoTDquDWrRI/hqdefault.jpg")
        e.title = "User (Reason)"

        embeds = embed_utils.rows_to_embeds(e, ban_lines, rows_per=25)
        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, content="Fetching banlist...", view=view)
        await view.update()
    
    ### Mutes & Blocks
    @commands.command(usage="Block <Optional: #channel> <@member1 @member2> <Optional: reason>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def block(self, ctx, channel: typing.Optional[discord.TextChannel], members: commands.Greedy[discord.Member]):
        """Block a user from seeing or talking in this channel"""
        if channel is None:
            channel = ctx.channel

        assert channel.guild.id == ctx.guild.id, "You cannot block a user from channels on other servers."

        ow = discord.PermissionOverwrite(read_messages=False, send_messages=False)
        for i in members:
            await channel.set_permissions(i, overwrite=ow)

        await self.bot.reply(ctx, content=f'Blocked {" ,".join([i.mention for i in members])} from {channel.mention}')

    @commands.command(usage="unblock <Optional: #channel> <@member1 @member2> <Optional: reason>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unblock(self, ctx, channel: typing.Optional[discord.TextChannel],
                      members: commands.Greedy[discord.Member]):
        """Unblock a user from seeing or talking in this channel"""
        if channel is None:
            channel = ctx.channel

        assert channel.guild.id == ctx.guild.id, "You cannot unblock a user from channels on other servers."

        for i in members:
            await channel.set_permissions(i, overwrite=None)

        await self.bot.reply(ctx, content=f'Unblocked {" ,".join([i.mention for i in members])} from {channel.mention}')

    @commands.command(aliases=["clear"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clean(self, ctx, number: int = 10):
        """Deletes my messages from the last x messages in channel"""

        def is_me(m):
            """Delete only messages that look like a command, or are from the bot."""
            return m.author == ctx.me

        try:
            deleted = await ctx.channel.purge(limit=number, check=is_me)
        except discord.HTTPException:
            return await self.bot.reply(ctx, content=f'An error occured when deleting some messages...', delete_after=5)

        await self.bot.reply(ctx, content=f'♻ Deleted {len(deleted)} bot message{"s" if len(deleted) > 1 else ""}',
                             delete_after=5)
    
    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def prefix(self, ctx):
        """Add, remove, or List bot prefixes for this server to use them instead of the default .tb"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                _ = await connection.fetch("""SELECT prefix FROM prefixes WHERE guild_id = $1""", ctx.guild.id)
            prefixes = [r['prefix'] for r in _]
        finally:
            await self.bot.db.release(connection)

        prefixes = ', '.join([f"`{i}`" for i in prefixes])
        await self.bot.reply(ctx, content=f"Messages starting with the following treated as commands: {prefixes}")
    
    @prefix.command(name="add", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    async def pref_add(self, ctx, prefix):
        """Add a prefix to your server's list of bot prefixes"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                _ = await connection.fetch("""SELECT prefix FROM prefixes WHERE guild_id = $1""", ctx.guild.id)
            prefixes = [r['prefix'] for r in _]

            if prefix not in prefixes:
                await connection.execute("""INSERT INTO prefixes (guild_id,prefix) 
                VALUES ($1,$2)""", ctx.guild.id, prefix)
                await self.bot.reply(ctx, content=f"Added '{prefix}' to {ctx.guild.name}'s prefixes list.")
                await self.update_prefixes()
            else:
                await self.bot.reply(ctx, content=f"'{prefix}' was already in {ctx.guild.name}'s prefix list")
        finally:
            await self.bot.db.release(connection)

        prefixes = ', '.join([f"`{i}`" for i in self.bot.prefix_cache[ctx.guild.id]])
        await self.bot.reply(ctx, content=f"Messages starting with the following treated as commands: {prefixes}")
    
    @prefix.command(name="remove", aliases=["delete"])
    @commands.has_permissions(manage_guild=True)
    async def pref_del(self, ctx, prefix):
        """Remove a prefix from your server's list of bot prefixes"""
        try:
            prefixes = self.bot.prefix_cache[ctx.guild.id]
        except KeyError:
            prefixes = ['.tb ']
        if prefix in prefixes:
            connection = await self.bot.db.acquire()
            await connection.execute("""DELETE FROM prefixes WHERE (guild_id,prefix) = ($1,$2)""", ctx.guild.id,
                                     prefix)
            await self.bot.db.release(connection)
            await self.bot.reply(ctx, content=f"Deleted '{prefix}' from {ctx.guild.name}'s prefixes list.")
            await self.update_prefixes()
        else:
            await self.bot.reply(ctx, content=f"'{prefix}' was not in {ctx.guild.name}'s prefix list")
        
        prefixes = ', '.join([f"'{i}'" for i in self.bot.prefix_cache[ctx.guild.id]])
        await self.bot.reply(ctx,
                             content=f"Messages starting with the following treated as commands: ```\n{prefixes}```")
    
    @commands.command(usage="<command name to enable>")
    async def enable(self, ctx, command: str):
        """Re-enables a disabled command for this server"""
        disable = self.bot.get_command('disable')
        await ctx.invoke(disable, command)
    
    @commands.command(usage="<command name to disable>")
    @commands.has_permissions(manage_guild=True)
    async def disable(self, ctx, command: str):
        """Disables a command for this server."""
        command = command.lower()
        
        if ctx.invoked_with == "enable":
            if command not in self.bot.disabled_cache[ctx.guild.id]:
                return await self.bot.reply(ctx, content=f"The {command} command is not disabled on this server.")
            else:
                connection = await self.bot.db.acquire()
                async with connection.transaction():
                    await connection.execute("""
                        DELETE FROM disabled_commands WHERE (guild_id,command) = ($1,$2)
                       """, ctx.guild.id, command)
                await self.bot.db.release(connection)
                await self.update_cache()
                return await self.bot.reply(ctx, content=f"The {command} command was enabled for {ctx.guild.name}")
        elif ctx.invoked_with == "disable":
            if command in self.bot.disabled_cache[ctx.guild.id]:
                return await self.bot.reply(ctx, content=f"The {command} command is already disabled on this server.")
        
        
        if command in ('disable', 'enable'):
            return await self.bot.reply(ctx, content='You cannot disable the disable command.')
        elif command not in [i.name for i in list(self.bot.commands)]:
            return await self.bot.reply(ctx, content='Unrecognised command name.')
        
        connection = await self.bot.db.acquire()
        await connection.execute("""INSERT INTO disabled_commands (guild_id,command) VALUES ($1,$2)""",
                                 ctx.guild.id, command)
        await self.bot.db.release(connection)
        await self.update_cache()
        return await self.bot.reply(ctx, content=f"The {command} command was disabled for {ctx.guild.name}")

    @commands.command(usage="disabled")
    @commands.has_permissions(manage_guild=True)
    async def disabled(self, ctx):
        """Check which commands are disabled on this server"""
        try:
            disabled = self.bot.disabled_cache[ctx.guild.id]
        except KeyError:
            disabled = ["None"]

        header = f"The following commands are disabled on this server:"
        embeds = embed_utils.rows_to_embeds(discord.Embed(), disabled, header=header)

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, content="Fetching disabled commands...", view=view)
        await view.update()

def setup(bot):
    """Load the mod cog into the bot"""
    bot.add_cog(Mod(bot))
