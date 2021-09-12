"""Commands for creating time triggered message reminders."""
import datetime
from copy import deepcopy
from importlib import reload

import discord
from discord.ext import commands
from discord.utils import sleep_until

from ext.utils import timed_events, embed_utils, view_utils


# TODO: Select / Button Pass.


class Reminders(commands.Cog):
    """Set yourself reminders"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "⏰"
        self.active_module = True
        self.bot.reminders = []  # A list of tasks.
        self.bot.loop.create_task(self.spool_initial())
        reload(timed_events)
        reload(embed_utils)

    async def spool_reminder(self, record):
        """Bulk dispatch reminder messages"""
        # Get data from records
        channel = self.bot.get_channel(record['channel_id'])
        msg = await channel.fetch_message(record['message_id'])
        user_id = record["user_id"]
        try:
            mention = channel.guild.get_member(user_id).mention
        except AttributeError:  # no guild
            mention = channel.recipient.mention

        await sleep_until(record["target_time"])

        e = discord.Embed()
        e.timestamp = record['created_time']
        e.colour = 0x00ff00
        e.title = "⏰ Reminder"

        if record['reminder_content'] is not None:
            e.description = "> " + record['reminder_content']

        if record['mod_action'] is not None:
            if record['mod_action'] == "unban":
                try:
                    await self.bot.http.unban(record["mod_target"], channel.guild)
                    e.description = f'\n\nUser id {record["mod_target"]} was unbanned'
                except discord.NotFound:
                    e.description = f"  \n\nFailed to unban user id {record['mod_target']} - are they already unbanned?"
                    e.colour = 0xFF0000
                else:
                    e.title = "Member unbanned"
            elif record['mod_action'] == "unmute":
                muted_role = discord.utils.get(channel.guild.roles, name="Muted")
                target = channel.guild.get_member(record["mod_target"])
                try:
                    await target.remove_roles(muted_role, reason="Unmuted")
                except discord.Forbidden:
                    e.description = f"Unable to unmute {target.mention}"
                    e.colour = 0xFF0000
                else:
                    e.title = "Member un-muted"
                    e.description = f"{target.mention}"
            elif record['mod_action'] == "unblock":
                target = channel.guild.get_member(record["mod_target"])
                await channel.set_permissions(target, overwrite=None)
                e.title = "Member un-blocked"
                e.description = f"Unblocked {target.mention} from {channel.mention}"

        try:
            e.description += f"\n[Jump to reminder]({msg.jump_url})"
        except AttributeError:
            pass

        try:
            await msg.reply(embed=e, ping=True)
        except discord.NotFound:
            try:
                await msg.channel.send(mention, embed=e)
            except discord.HTTPException:
                try:
                    await self.bot.get_user(user_id).send(mention, embed=e)
                except discord.HTTPException:
                    pass

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute("""DELETE FROM reminders WHERE message_id = $1""", record['message_id'])
        await self.bot.db.release(connection)

    def cog_unload(self):
        """Cancel all active tasks on cog reload"""
        for i in self.bot.reminders:
            i.cancel()

    async def spool_initial(self):
        """Queue all active reminders"""
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM reminders""")
        async with connection.transaction():
            for r in records:
                self.bot.reminders.append(self.bot.loop.create_task(self.spool_reminder(r)))
        await self.bot.db.release(connection)
    
    @commands.group(aliases=['reminder', 'remind', 'remindme'],
                    usage="<Amount of time> <Reminder message>",
                    invoke_without_command=True)
    async def timer(self, ctx, time, *, message: commands.clean_content = "Reminder"):
        """Remind you of something at a specified time.
            Format is remind 1d2h3m4s <note>, e.g. remind 1d3h Kickoff."""
        try:
            delta = await timed_events.parse_time(time.lower())
        except ValueError:
            return await self.bot.reply(ctx, text='Invalid time specified.')
        except OverflowError:
            return await self.bot.reply(ctx, text="You'll be dead by then'")

        try:
            remind_at = datetime.datetime.now(datetime.timezone.utc) + delta
        except OverflowError:
            return await self.bot.reply(ctx, text="You'll be dead by then.")
        human_time = datetime.datetime.strftime(remind_at, "%a %d %b at %H:%M:%S")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                record = await connection.fetchrow("""INSERT INTO reminders
                (message_id, channel_id, guild_id, reminder_content, created_time, target_time, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""", ctx.message.id, ctx.channel.id, ctx.guild.id,
                                                   message, ctx.message.created_at, remind_at, ctx.author.id)
        finally:
            await self.bot.db.release(connection)
        self.bot.reminders.append(self.bot.loop.create_task(self.spool_reminder(record)))

        e = discord.Embed()
        e.title = "⏰ Reminder Set"
        e.description = f"**{human_time}**\n{message}"
        e.colour = 0x00ffff
        e.timestamp = remind_at
        await self.bot.reply(ctx, embed=e)
    
    @timer.command(aliases=["timers"])
    async def list(self, ctx):
        """Check your active reminders"""
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM reminders WHERE user_id = $1""", ctx.author.id)
        await self.bot.db.release(connection)
        
        embeds = []
        e = discord.Embed()
        e.description = ""
        e.colour = 0x7289DA
        e.title = f"⏰ {ctx.author.name}'s reminders"
        for r in records:
            delta = r['target_time'] - datetime.datetime.now(datetime.timezone.utc)
            this_string = "**`" + str(delta).split(".")[0] + "`** " + r['reminder_content'] + "\n"
            if len(e.description) + len(this_string) > 2000:
                embeds.append(deepcopy(e))
                e.description = ""
            else:
                e.description += this_string
        embeds.append(e)

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, "Fetching your reminders...", view=view)
        await view.update()


# TODO: timed poll.


def setup(bot):
    """Load the reminders Cog into the bot"""
    bot.add_cog(Reminders(bot))
