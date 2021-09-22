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
    async def on_message(self, message):
        """If user pings bot, send reply with their prefixes"""
        ctx = await self.bot.get_context(message)
        if ctx.message.content == ctx.me.mention:
            if message.guild is None:
                return await self.bot.reply(ctx, text=f'What?')
            _ = ', '.join(self.bot.prefix_cache[message.guild.id])
            await self.bot.reply(ctx, text=f"Forgot your prefixes? They're ```css\n{_}```", ping=True)
    
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Create database entry for new guild"""
        await self.create_guild(guild.id)
        await self.update_prefixes()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete guild's info upon leaving one."""
        await self.delete_guild(guild.id)
        await self.update_prefixes()
    
    async def create_guild(self, guild_id):
        """Insert the database entry for a new guild"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""
                with gid as (INSERT INTO guild_settings (guild_id) VALUES ($1) RETURNING guild_id)
                INSERT INTO prefixes (prefix, guild_id)
                VALUES ($2, (SELECT guild_id FROM gid));
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
        """Set new prefixes for guild"""
        self.bot.prefix_cache.clear()
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            records = await connection.fetch("""SELECT * FROM prefixes""")
        await self.bot.db.release(connection)
        
        for r in records:
            guild_id = r["guild_id"]
            if self.bot.get_guild(guild_id) is None:
                continue
            
            prefix = r["prefix"]
            self.bot.prefix_cache[guild_id].append(prefix)
        
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
        m = await self.bot.reply(ctx, text='Are you sure you want me to go? All of your settings will be wiped.',
                                 ping=True)
        await embed_utils.bulk_react(ctx, m, ['✅', '🚫'])

        def check(reaction, user):
            """Check user reacting is the one invoking the message"""
            if reaction.message.id == m.id and user == ctx.author:
                emoji = str(reaction.emoji)
                return emoji.startswith(('✅', '🚫'))
            
        try:
            res = await self.bot.wait_for("reaction_add", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await self.bot.reply(ctx, text="Response timed out after 30 seconds, I will stay for now.",
                                        ping=True)
        res = res[0]

        if res.emoji.startswith('✅'):
            await self.bot.reply(ctx, text='Farewell!')
            await ctx.guild.leave()
        else:
            await self.bot.reply(ctx, text="Okay, I'll stick around a bit longer then.")
            await m.clear_reactions()

    @commands.command(aliases=['nick'])
    @commands.has_permissions(manage_nicknames=True)
    async def name(self, ctx, *, new_name: str):
        """Rename the bot for your server."""
        await ctx.me.edit(nick=new_name)
        await self.bot.reply(ctx, text=f"My new name is {new_name} on your server.")

    @commands.command(usage="[Channel] <what you want the bot to say>")
    @commands.check(me_or_mod)
    async def say(self, ctx, destination: typing.Optional[discord.TextChannel] = None, *, msg):
        """Say something as the bot in specified channel"""
        if destination is None:
            destination = ctx
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        assert destination.guild.id == ctx.guild.id, "You cannot send messages to other servers."
        await destination.send(msg)
    
    @commands.command(usage="topic <New Channel Topic>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def topic(self, ctx, *, new_topic):
        """Set the topic for the current channel"""
        await ctx.channel.edit(topic=new_topic)
        await self.bot.reply(ctx, text=f"Topic changed to: '{new_topic}'")
    
    @commands.command(usage="pin <(Message ID you want pinned) or (new message to pin.)>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def pin(self, ctx, *, message: typing.Union[discord.Message, int, str]):
        """Pin a message to the current channel"""
        if isinstance(message, int):
            message = await ctx.channel.fetch_message(message)
        elif isinstance(message, str):
            message = await self.bot.reply(ctx, text=message, ping=True)
        await message.pin()
    
    @commands.command(usage="rename <member> <new name>")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def rename(self, ctx, member: discord.Member, nickname: commands.clean_content):
        """Rename a member"""
        try:
            await member.edit(nick=str(nickname))
        except discord.Forbidden:
            await self.bot.reply(ctx, text="⛔ I can't change that member's nickname.", ping=True)
        except discord.HTTPException:
            await self.bot.reply(ctx, text="❔ Member edit failed.", ping=True)
        else:
            await self.bot.reply(ctx, text=f"{member.mention} has been renamed.")
    
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
        await self.bot.reply(ctx, text=f'Found and deleted {len(deleted)} empty roles: {", ".join(deleted)}')
    
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
            await self.bot.reply(ctx, text=f"✅ {', '.join(success)} kicked for: \"{reason}\".")
        if fail:
            await self.bot.reply(ctx, text=f"⚠ Kicking failed for {', '.join(fail)}.", ping=True)
            
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
                    await self.bot.reply(ctx, text=outstr)
                except discord.Forbidden:
                    await self.bot.reply(ctx, text=f"⛔ Sorry, I can't ban {i.mention}.", ping=True)
                except discord.HTTPException:
                    await self.bot.reply(ctx, text=f"⚠ Banning failed for {i.mention}.", ping=True)
                except Exception as e:
                    await self.bot.reply(ctx, text=f"⚠ Banning failed for {i.mention}.", ping=True)
                    print("Failed while banning member\n", e)
            else:
                try:
                    await self.bot.http.ban(i, ctx.message.guild.id)
                    target = await self.bot.fetch_user(i)
                    outstr = f"☠ UserID {i} {target} was banned for reason: \"{reason}\""
                    if delete_days:
                        outstr += f", messages from last {delete_days} day(s) were deleted."
                    await self.bot.reply(ctx, text=outstr)
                except discord.HTTPException:
                    await self.bot.reply(ctx, text=f"⚠ Banning failed for UserID# {i}.", ping=True)
                except Exception as e:
                    await self.bot.reply(ctx, text=f"⚠ Banning failed for UserID# {i}.", ping=True)
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
                await self.bot.reply(ctx, text="⛔ I can't unban that user.", ping=True)
            except discord.HTTPException:
                await self.bot.reply(ctx, text="❔ Unban failed.", ping=True)
            else:
                await self.bot.reply(ctx, text=f"🆗 {who} was unbanned")
        else:
            try:
                un, discrim = who.split('#')
                for i in await ctx.guildG.bans():
                    if i.user.display_name == un and i.discriminator == discrim:
                        try:
                            await self.bot.http.unban(i.user.id, ctx.guild.id)
                        except discord.Forbidden:
                            await self.bot.reply(ctx, text="⛔ I can't unban that user.", ping=True)
                        except discord.HTTPException:
                            await self.bot.reply(ctx, text="❔ Unban failed.", ping=True)
                        else:
                            await self.bot.reply(ctx, text=f"🆗 {who} was unbanned")
                        return  # Stop iterating when found.
            except ValueError:
                for i in await ctx.guild.bans():
                    if i.user.name == who:
                        try:
                            await self.bot.http.unban(i.user.id, ctx.guild.id)
                        except discord.Forbidden:
                            await self.bot.reply(ctx, text=f"⛔ I can't unban {i}.", ping=True)
                        except discord.HTTPException:
                            await self.bot.reply(ctx, text=f"❔ Unban failed for {i.user}", ping=True)
                        else:
                            await self.bot.reply(ctx, text=f"🆗 {i.user} was unbanned")
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
        e.set_author(name=n, icon_url=ctx.guild.icon.url)
        e.set_thumbnail(url="https://i.ytimg.com/vi/eoTDquDWrRI/hqdefault.jpg")
        e.title = "User (Reason)"

        embeds = embed_utils.rows_to_embeds(e, ban_lines, rows_per=25)
        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching banlist...", view=view)
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

        await self.bot.reply(ctx, text=f'Blocked {" ,".join([i.mention for i in members])} from {channel.mention}')

    @commands.command(usage="unblock <Optional: #channel> <@member1 @member2> <Optional: reason>")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unblock(self, ctx, channel:typing.Optional[discord.TextChannel], members:commands.Greedy[discord.Member]):
        """Unblock a user from seeing or talking in this channel"""
        if channel is None:
            channel = ctx.channel

        assert channel.guild.id == ctx.guild.id, "You cannot unblock a user from channels on other servers."

        for i in members:
            await channel.set_permissions(i, overwrite=None)

        await self.bot.reply(ctx, text=f'Unblocked {" ,".join([i.mention for i in members])} from {channel.mention}')
        
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    @commands.command(usage="mute <@user1 @user2 @user3> <reason>")
    async def mute(self, ctx, members: commands.Greedy[discord.Member], *, reason="No reason given."):
        """Prevent member(s) from talking on your server."""
        if not members:
            return await self.bot.reply(ctx, 'No members specified.')

        muted_role = discord.utils.get(ctx.guild.roles, name='Muted')
        if not muted_role:
            muted_role = await ctx.guild.create_role(name="Muted")  # Read Messages / Read mesasge history.
            await muted_role.edit(position=ctx.me.top_role.position - 1)
            m_overwrite = discord.PermissionOverwrite(send_messages=False)

            for i in ctx.guild.text_channels:
                await i.set_permissions(muted_role, overwrite=m_overwrite)
        
        muted = []
        not_muted = []
        for i in members:
            if i.top_role >= ctx.me.top_role:
                not_muted.append(i)
            else:
                muted.append(i)
                await i.add_roles(muted_role, reason=f"{ctx.author}: {reason}")

        if muted:
            await self.bot.reply(ctx, text=f"Muted {', '.join([i.mention for i in muted])} for {reason}")
        if not_muted:
            await self.bot.reply(ctx, text=f"⚠ Could not mute {', '.join([i.mention for i in not_muted])},"
                                           f" they are the same or higher role than me.", ping=True)
        
                
    @commands.command(usage="<@user @user2>")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self, ctx, members: commands.Greedy[discord.Member]):
        """Allow members to talk again."""
        muted_role = discord.utils.get(ctx.guild.roles, name='Muted')
        if not muted_role:
            return await self.bot.reply(ctx, text=f"No 'muted' role found on {ctx.guild.name}", ping=True)
        
        success, fail = [], []
        for i in members:
            try:
                await i.remove_roles(muted_role)
            except discord.Forbidden:
                fail.append(i.mention)
            else:
                success.append(i.mention)
        
        if success:
            await self.bot.reply(ctx, text=f"🆗 Unmuted {', '.join(success)}")
        if fail:
            await self.bot.reply(ctx, text=f"🚫 Could not unmute {', '.join(fail)}", ping=True)

    
    @commands.command(aliases=["clear"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clean(self, ctx, number: int = 10):
        """Deletes my messages from the last x messages in channel"""
        try:
            prefixes = tuple(self.bot.prefix_cache[ctx.guild.id])
        except KeyError:
            prefixes = ctx.prefix
        
        def is_me(m):
            """Delete only messages that look like a command, or are from the bot."""
            return m.author == ctx.me or m.content.startswith(prefixes)
        
        try:
            deleted = await ctx.channel.purge(limit=number, check=is_me)
        except discord.HTTPException:
            return await self.bot.reply(ctx, f'An error occured when deleting some messages...', delete_after=5)
        
        await self.bot.reply(ctx, text=f'♻ Deleted {len(deleted)} bot and command messages'
                                       f'{"s" if len(deleted) > 1 else ""}', delete_after=5)
    
    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def prefix(self, ctx):
        """Add, remove, or List bot prefixes for this server to use them instead of the default .tb"""
        try:
            prefixes = self.bot.prefix_cache[ctx.guild.id]
        except KeyError:
            prefixes = ['.tb ']
            connection = await self.bot.db.acquire()
            await connection.execute("""INSERT INTO prefixes (guild_id,prefix) VALUES ($1,$2)""", ctx.guild.id, '.tb ')
            await self.bot.db.release(connection)
            await self.update_prefixes()
        
        prefixes = ', '.join([f"'{i}'" for i in prefixes])
        await self.bot.reply(ctx, text=f"Messages starting with the following treated as commands: ```{prefixes}```")
    
    @prefix.command(name="add", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    async def pref_add(self, ctx, prefix):
        """Add a prefix to your server's list of bot prefixes"""
        try:
            prefixes = self.bot.prefix_cache[ctx.guild.id]
        except KeyError:
            prefixes = ['.tb ']
        
        if prefix not in prefixes:
            connection = await self.bot.db.acquire()
            await connection.execute("""INSERT INTO prefixes (guild_id,prefix) VALUES ($1,$2)""", ctx.guild.id,
                                     prefix)
            await self.bot.db.release(connection)
            await self.bot.reply(ctx, text=f"Added '{prefix}' to {ctx.guild.name}'s prefixes list.")
            await self.update_prefixes()
        else:
            await self.bot.reply(ctx, text=f"'{prefix}' was already in {ctx.guild.name}'s prefix list")
        
        prefixes = ', '.join([f"'{i}'" for i in self.bot.prefix_cache[ctx.guild.id]])
        await self.bot.reply(ctx, text=f"Messages starting with the following treated as commands: ```{prefixes}```")
    
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
            await self.bot.reply(ctx, text=f"Deleted '{prefix}' from {ctx.guild.name}'s prefixes list.")
            await self.update_prefixes()
        else:
            await self.bot.reply(ctx, text=f"'{prefix}' was not in {ctx.guild.name}'s prefix list")
        
        prefixes = ', '.join([f"'{i}'" for i in self.bot.prefix_cache[ctx.guild.id]])
        await self.bot.reply(ctx, text=f"Messages starting with the following treated as commands: ```{prefixes}```")
    
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
                return await self.bot.reply(ctx, text=f"The {command} command is not disabled on this server.")
            else:
                connection = await self.bot.db.acquire()
                async with connection.transaction():
                    await connection.execute("""
                        DELETE FROM disabled_commands WHERE (guild_id,command) = ($1,$2)
                       """, ctx.guild.id, command)
                await self.bot.db.release(connection)
                await self.update_cache()
                return await self.bot.reply(ctx, text=f"The {command} command was enabled for {ctx.guild.name}")
        elif ctx.invoked_with == "disable":
            if command in self.bot.disabled_cache[ctx.guild.id]:
                return await self.bot.reply(ctx, text=f"The {command} command is already disabled on this server.")
        
        
        if command in ('disable', 'enable'):
            return await self.bot.reply(ctx, text='You cannot disable the disable command.', ping=True)
        elif command not in [i.name for i in list(self.bot.commands)]:
            return await self.bot.reply(ctx, text='Unrecognised command name.', ping=True)
        
        connection = await self.bot.db.acquire()
        await connection.execute("""INSERT INTO disabled_commands (guild_id,command) VALUES ($1,$2)""",
                                 ctx.guild.id, command)
        await self.bot.db.release(connection)
        await self.update_cache()
        return await self.bot.reply(ctx, text=f"The {command} command was disabled for {ctx.guild.name}")

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
        view.message = await self.bot.reply(ctx, "Fetching disabled commands...", view=view)
        await view.update()

    # @commands.command(usage="tempban <members: @member1 @member2> <time (e.g. 1d1h1m1s)> <(Optional: reason)>")
    # @commands.has_permissions(ban_members=True)
    # @commands.bot_has_permissions(ban_members=True)
    # async def tempban(self, ctx, members: commands.Greedy[discord.Member], time, *,
    #                   reason: commands.clean_content = None):
    #     """Temporarily ban member(s)"""
    #     try:
    #         delta = await parse_time(time.lower())
    #     except ValueError:
    #         return await self.bot.reply(ctx, text='Invalid time format, please use `1d1h30m10s`', ping=True)
    #     remind_at = datetime.datetime.now() + delta
    #     human_time = datetime.datetime.strftime(remind_at, "%H:%M:%S on %a %d %b")
    #
    #     for i in members:
    #         try:
    #             await ctx.guild.ban(i, reason=reason)
    #         except discord.Forbidden:
    #             await self.bot.reply(ctx, text=f"🚫 I can't ban {i.mention}.", ping=True)
    #             continue
    #
    #         connection = await self.bot.db.acquire()
    #         record = await connection.fetchrow("""INSERT INTO reminders (message_id, channel_id, guild_id,
    #         reminder_content,
    #         created_time, target_time. user_id, mod_action, mod_target) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    #         RETURNING *""", ctx.message.id, ctx.channel.id, ctx.guild.id, reason, datetime.datetime.now(), remind_at,
    #                                           ctx.author.id, "unban", i.id)
    #         await self.bot.db.release(connection)
    #         self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(ctx.bot, record)))
    #
    #     e = discord.Embed()
    #     e.title = "⏰ User banned"
    #     e.description = f"{[i.mention for i in members]} will be unbanned for \n{reason}\nat\n {human_time}"
    #     e.colour = 0x00ffff
    #     e.timestamp = remind_at
    #     await self.bot.reply(ctx, embed=e)

    # @commands.command(usage="tempmute <members: @member1 @member2> <time (e.g. 1d1h1m1s)> <(Optional: reason)>")
    # @commands.has_permissions(kick_members=True)
    # @commands.bot_has_permissions(kick_members=True)
    # async def tempmute(self, ctx, members: commands.Greedy[discord.Member], time, *,
    #                    reason: commands.clean_content = None):
    #     """Temporarily mute member(s)"""
    #     try:
    #         delta = await parse_time(time.lower())
    #     except ValueError:
    #         return await self.bot.reply(ctx, text='Invalid time format, use `1d1h30m10s`', ping=True)
    #     remind_at = datetime.datetime.now() + delta
    #     human_time = datetime.datetime.strftime(remind_at, "%H:%M:%S on %a %d %b")
    #
    #     # Role.
    #     muted_role = discord.utils.get(ctx.guild.roles, name='Muted')
    #     if not muted_role:
    #         muted_role = await ctx.guild.create_role(name="Muted")  # Read Messages / Read mesasge history.
    #         await muted_role.edit(position=ctx.me.top_role.position - 1)
    #         m_overwrite = discord.PermissionOverwrite(add_reactions=False, send_messages=False)
    #
    #         for i in ctx.guild.text_channels:
    #             await i.set_permissions(muted_role, overwrite=m_overwrite)
    #
    #     # Mute
    #     for i in members:
    #         await i.add_roles(muted_role, reason=f"{ctx.author}: {reason}")
    #         connection = await self.bot.db.acquire()
    #
    #         async with connection.transaction():
    #             record = await connection.fetchrow("""INSERT INTO reminders (message_id, channel_id, guild_id,
    #             reminder_content, created_time, target_time, user_id, mod_action, mod_target)
    #             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *""",
    #             ctx.message.id, ctx.channel.id, ctx.guild.id, reason, ctx.message.created_at, remind_at, ctx.author.id,
    #                                                "unmute", i.id)
    #         await self.bot.db.release(connection)
    #         self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(ctx.bot, record)))
    #
    #     e = discord.Embed()
    #     e.title = "⏰ User muted"
    #     e.description = f"{', '.join([i.mention for i in members])} temporarily muted:"
    #     e.add_field(name="Until", value=human_time)
    #     if reason is not None:
    #         e.add_field(name="Reason", value=str(reason))
    #     e.colour = 0x00ffff
    #     e.timestamp = remind_at
    #     await self.bot.reply(ctx, embed=e)

    # @commands.command(usage="tempblock <members: @member1 @member2> <time (e.g. 1d1h1m1s)> <(Optional: reason)>")
    # @commands.has_permissions(kick_members=True)
    # @commands.bot_has_permissions(kick_members=True)
    # async def tempblock(self, ctx, channel: typing.Optional[discord.TextChannel],
    #                     members: commands.Greedy[discord.Member], time, *, reason: commands.clean_content = None):
    #     """Temporarily block member(s) from a channel"""
    #     if channel is None:
    #         channel = ctx.channel
    #
    #     try:
    #         delta = await parse_time(time.lower())
    #     except ValueError:
    #         return await self.bot.reply(ctx, text='Invalid time format, use `1d1h30m10s`', ping=True)
    #     remind_at = datetime.datetime.now() + delta
    #     human_time = datetime.datetime.strftime(remind_at, "%H:%M:%S on %a %d %b")
    #
    #     ow = discord.PermissionOverwrite(read_messages=False, send_messages=False)
    #
    #     # Mute, send to notification channel if exists.
    #     for i in members:
    #         await channel.set_permissions(i, overwrite=ow)
    #
    #         connection = await self.bot.db.acquire()
    #         record = await connection.fetchval("""INSERT INTO reminders (message_id, channel_id, guild_id,
    #         reminder_content,
    #         created_time, target_time. user_id, mod_action, mod_target) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    #         RETURNING *""", ctx.message.id, channel.id, ctx.guild.id, reason, datetime.datetime.now(), remind_at,
    #                                           ctx.author.id, "unblock", i.id)
    #         await self.bot.db.release(connection)
    #         self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(ctx.bot, record)))
    #
    #     e = discord.Embed()
    #     e.title = "⏰ User blocked"
    #     e.description = f"{', '.join([i.mention for i in members])} will be blocked from {channel.mention} " \
    #                     f"\n{reason}\nuntil\n {human_time}"
    #     e.colour = 0x00ffff
    #     e.timestamp = remind_at
    #     await self.bot.reply(ctx, embed=e)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def lockdown(self, ctx, top_role: typing.Optional[discord.Role]):
        """Anti-raid command: Stop un-roled people sending messages in the discord.
        Mention a role to stop people below that role from sending messages as the cutoff."""
        if not top_role:
            top_role = ctx.guild.default_role
        
        target_position = top_role.position
        
        if ctx.author.top_role.position < target_position:
            target_position = ctx.author.top_role.position - 1
        
        new_perms = discord.Permissions(send_messages=False)

        self.bot.lockdown_cache[ctx.guild.id] = []
        modified_roles = []
        for i in ctx.guild.roles:
            if not i.permissions.send_messages:  # if role does not have send message perm override set, skip.
                continue
            
            if i.position <= target_position:  # If we are below the target position
                self.bot.lockdown_cache[ctx.guild.id].append((i.id, i.permissions))  # Save id, permissions tuple.
                await i.edit(permissions=new_perms, reason="Raid lockdown.")
                modified_roles.append(i.name)
                
        if not modified_roles:
            return await self.bot.reply(ctx, text='⚠ No roles were modified.', ping=True)
        await self.bot.reply(ctx, text=f"⚠ {len(modified_roles)} roles can no longer send messages.",
                             ping=True)
        output = modified_roles.pop(0)
        for x in modified_roles:
            if len(x + output + 10 > 2000):
                output += f", {x}"
            else:
                await self.bot.reply(ctx, text=f"```{output}```", ping=True)
                output = x
        await self.bot.reply(ctx, text=f"```{output}```", ping=True)

    @commands.command(usage="")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unlock(self, ctx):
        """Unlock a previously set lockdown."""
        if not ctx.guild.id in self.bot.lockdown_cache:
            return await self.bot.reply(ctx, text='Lockdown not in progress.')
        
        count = 0
        for role in self.bot.lockdown_cache[ctx.guild.id]:
            # Role tuple is role id, permissions.
            r = ctx.guild.get_role(role[0])
            await r.edit(permissions=role[1], reason="Unlock raid.")
            count += 1

        self.bot.lockdown_cache.pop(ctx.guild.id)  # dump from cache, no longer needed.
        await self.bot.reply(ctx, text=f'Restored send_messages permissions to {count} roles', ping=True)
    

def setup(bot):
    """Load the mod cog into the bot"""
    bot.add_cog(Mod(bot))
