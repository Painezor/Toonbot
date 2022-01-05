"""Commands for creating time triggered message reminders."""
import datetime
from importlib import reload

import asyncpg
import discord
from discord.ext import commands
from discord.utils import sleep_until

from ext.utils import timed_events, embed_utils, view_utils


async def spool_reminder(bot, r: asyncpg.Record):
    """Bulk dispatch reminder messages"""
    # Get data from records
    await sleep_until(r["target_time"])
    rv = ReminderView(bot, r)
    await rv.dispatch()


class SnoozeButton(discord.ui.Button):
    """Button to create snooze dropdown"""

    def __init__(self):
        super().__init__(label="Snooze", emoji='⏰')

    async def callback(self, interaction):
        """Add button on click."""
        self.view.clear_items()
        self.view.add_item(RemindLater())
        await self.view.message.edit(view=self.view)


class RemindLater(discord.ui.Select):
    """Snooze dropdown for reminders."""

    def __init__(self):
        super().__init__(row=1, placeholder="Snooze reminder")

        options = [("Snooze for 5 minutes", 300),
                   ("Snooze for 10 minutes", 600),
                   ("Snooze for 15 minutes", 900),
                   ("Snooze for 30 minutes", 1800),
                   ("Snooze for 1 hour", 3600),
                   ("Snooze for 2 hours", 7200),
                   ("Snooze for 3 hours", 10800),
                   ("Snooze for 6 hours", 21600),
                   ("Snooze for 12 hours", 43200),
                   ("Snooze for 1 day", 86400),
                   ("Snooze for 2 days", 172800),
                   ("Snooze for 3 days", 345600),
                   ("Snooze for 1 week", 604800),
                   ("Snooze for 2 weeks", 1209600),
                   ("Snooze for 28 days", 2419200)]

        for label, value in options:
            self.add_option(label=label, value=str(value))

    async def callback(self, interaction):
        """Push new values to view"""
        await interaction.response.defer()
        await self.view.reinsert(int(self.values[0]))


class ReminderView(discord.ui.View):
    """View for user requested reminders"""

    def __init__(self, bot, r: asyncpg.Record):
        super().__init__(timeout=None)
        self.bot = bot
        self.record = r
        self.message = None

    async def dispatch(self):
        """Send message to appropriate destination"""
        r = self.record

        channel = self.bot.get_channel(r['channel_id'])
        msg = await channel.fetch_message(r['message_id'])

        self.add_item(discord.ui.Button(label="Original Message", url=msg.jump_url))

        e = discord.Embed(colour=0x00ff00)
        e.set_author(name="⏰ Reminder")
        e.description = timed_events.Timestamp(r['created_time']).date_relative
        e.description += f"\n\n> {r['reminder_content']}" if r['reminder_content'] is not None else ""

        if r['mod_action'] == "unban":
            try:
                await self.bot.http.unban(r["mod_target"], channel.guild)
                title = "User Unbanned"
            except discord.NotFound:
                title = "Failed to unban user"
            e.add_field(name=title, value=f"<@{r['mod_target']}>")

        elif r['mod_action'] == "unmute":
            muted_role = discord.utils.get(channel.guild.roles, name="Muted")
            target = channel.guild.get_member(r["mod_target"])
            try:
                await target.remove_roles(muted_role, reason="Unmuted")
                title = "User unmuted"
            except (discord.Forbidden, AttributeError):
                title = "Failed to unmute user"
            e.add_field(name=title, value=f"<@{r['mod_target']}>")

        elif r['mod_action'] == "unblock":
            target = channel.guild.get_member(r["mod_target"])
            try:
                await channel.set_permissions(target, overwrite=None)
                title = f"User unblocked from #{channel.name}"
            except (discord.Forbidden, AttributeError):
                title = f"Failed to unblock user from #{channel.name}"
            e.add_field(name=title, value=f"<@{r['mod_target']}>")

        else:
            self.add_item(SnoozeButton())

        self.add_item(view_utils.StopButton(row=0))

        try:
            self.message = await msg.channel.send(f"<@{r['user_id']}>", embed=e, view=self)
        except discord.HTTPException:
            try:
                self.message = await self.bot.get_user(r["user_id"]).send(embed=e, view=self)
            except discord.HTTPException:
                pass

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute('''DELETE FROM reminders WHERE message_id = $1''', r['message_id'])
        finally:
            await self.bot.db.release(connection)

    async def interaction_check(self, interaction: discord.Interaction):
        """Only reminder owner can interact to hide or snooze"""
        return interaction.user.id == self.record['user_id']

    async def on_timeout(self):
        """Delete the record"""
        self.clear_items()
        await self.message.edit(view=self)

    async def reinsert(self, offset):
        """Snooze the reminder"""
        connection = await self.bot.db.acquire()
        r = self.record

        new_time = r['target_time'] + datetime.timedelta(seconds=offset)

        try:
            async with connection.transaction():
                record = await connection.fetchrow("""INSERT INTO reminders
                (message_id, channel_id, guild_id, reminder_content, created_time, target_time, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7) 
                ON CONFLICT (message_id) DO UPDATE SET target_time = $8
                RETURNING *
                """, r['message_id'], r['channel_id'], r['guild_id'], r['reminder_content'], r['created_time'],
                                                   new_time, r['user_id'], new_time)
        finally:
            await self.bot.db.release(connection)

        self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(self.bot, record)))
        e = discord.Embed()

        e.set_author(name="⏰ Reminder Snoozed")
        t = timed_events.Timestamp(new_time).time_relative
        e.description = f"**{t}**\n\n> {r['reminder_content']}"
        e.colour = 0x00ffff
        await self.message.edit(embed=e, view=None)


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
                self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(self.bot, r)))
        await self.bot.db.release(connection)

    @commands.command(aliases=['reminder', 'remind', 'remindme'], usage="<Amount of time> <Reminder message>")
    async def timer(self, ctx, time, *, message: commands.clean_content = "Reminder"):
        """Remind you of something at a specified time.
            Format is remind 1d2h3m4s <note>, e.g. remind 1d3h Kickoff."""
        try:
            delta = await timed_events.parse_time(time.lower())
        except ValueError:
            return await self.bot.reply(ctx, content='Invalid time specified.')
        except OverflowError:
            return await self.bot.reply(ctx, content="You'll be dead by then'")

        try:
            remind_at = datetime.datetime.now(datetime.timezone.utc) + delta
        except OverflowError:
            return await self.bot.reply(ctx, content="You'll be dead by then.")

        connection = await self.bot.db.acquire()
        try:
            gid = ctx.guild.id if ctx.guild is not None else None
            async with connection.transaction():
                record = await connection.fetchrow("""INSERT INTO reminders
                (message_id, channel_id, guild_id, reminder_content, created_time, target_time, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""", ctx.message.id, ctx.channel.id, gid, message,
                                                   ctx.message.created_at, remind_at, ctx.author.id)
        finally:
            await self.bot.db.release(connection)
        self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(self.bot, record)))

        e = discord.Embed()
        e.set_author(name="⏰ Reminder Set")
        t = timed_events.Timestamp(remind_at).time_relative
        e.description = f"**{t}**\n\n> {message}"
        e.colour = 0x00ffff
        await self.bot.reply(ctx, embed=e)

    @commands.command(aliases=["timers"])
    async def reminders(self, ctx):
        """Check your active reminders"""
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM reminders WHERE user_id = $1""", ctx.author.id)
        await self.bot.db.release(connection)

        def short(r: asyncpg.Record):
            """Get oneline version of reminder"""
            time = timed_events.Timestamp(r['target_time']).time_relative
            guild = "@me" if r['guild_id'] is None else r['guild_id']
            j = f"https://discord.com/channels/{guild}/{r['channel_id']}/{r['message_id']}"
            x = f"\n*{r['mod_action']} <@{r['mod_target']}>" if r['mod_action'] is not None else ""
            return f"**{time}**: [{r['reminder_content']}]({j}){x}"

        _ = [short(r) for r in records] if records else ["You have no reminders set."]

        e = discord.Embed(colour=0x7289DA)
        e.set_author(name=f"⏰ {ctx.author.name}'s reminders")
        embeds = embed_utils.rows_to_embeds(e, _)

        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, content="Fetching your reminders...", view=view)
        await view.update()


# TODO: timed poll.


def setup(bot):
    """Load the reminders Cog into the bot"""
    bot.add_cog(Reminders(bot))
