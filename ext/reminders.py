"""Commands for creating time triggered message reminders."""
import datetime
from importlib import reload

import asyncpg
from dateutil.relativedelta import relativedelta
from discord import Embed, Interaction, HTTPException, SlashCommandGroup, InputTextStyle, Message
from discord.ext import commands
from discord.ui import View, Button, Modal, InputText
from discord.utils import sleep_until

from ext.utils import timed_events, embed_utils, view_utils


# TODO: Slash attachments pass - Add an attachment.


async def spool_reminder(bot, r: asyncpg.Record):
    """Bulk dispatch reminder messages"""
    # Get data from records
    await sleep_until(r["target_time"])
    rv = ReminderView(bot, r)
    await rv.dispatch()


class RemindModal(Modal):
    """A Modal Dialogue asking the user to enter a time & message for their reminder."""

    def __init__(self, ctx, message: Message = None) -> None:
        super().__init__(title="Create a new reminder")
        self.ctx = ctx
        self.message = message
        self.add_item(InputText(label="Months", placeholder="Enter number of months", max_length=2, required=False))
        self.add_item(InputText(label="Days", placeholder="Enter number of days", max_length=2, required=False))
        self.add_item(InputText(label="Hours", placeholder="Enter number of hours", max_length=2, required=False))
        self.add_item(InputText(label="Minutes", placeholder="Enter number of minutes", max_length=2, required=False))
        self.add_item(InputText(label="Reminder Description", placeholder="Enter a description of your reminder",
                                style=InputTextStyle.long, required=False))

    async def callback(self, interaction: Interaction):
        """Insert entry to the database when the form is submitted"""
        months = int(self.children[0].value) if self.children[0].value.isdigit() else 0
        days = int(self.children[1].value) if self.children[1].value.isdigit() else 0
        hours = int(self.children[2].value) if self.children[1].value.isdigit() else 0
        minutes = int(self.children[3].value) if self.children[1].value.isdigit() else 0
        description = self.children[4].value

        delta = relativedelta(minutes=minutes, hours=hours, days=days, months=months)

        remind_at = datetime.datetime.now(datetime.timezone.utc) + delta
        connection = await self.ctx.bot.db.acquire()

        msg_id = None if self.message is None else self.message.id
        ch_id = None if self.message is None else self.ctx.channel.id

        try:
            gid = self.ctx.guild.id if self.ctx.guild is not None else None
            time = datetime.datetime.now(datetime.timezone.utc)
            async with connection.transaction():
                record = await connection.fetchrow("""INSERT INTO reminders
                (message_id, channel_id, guild_id, reminder_content, created_time, target_time, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""", msg_id, ch_id, gid, description,
                                                   time, remind_at, self.ctx.author.id)
        finally:
            await self.ctx.bot.db.release(connection)

        self.ctx.bot.reminders.append(self.ctx.bot.loop.create_task(spool_reminder(self.ctx.bot, record)))

        t = timed_events.Timestamp(remind_at).time_relative
        e = Embed(colour=0x00ffff, description=f"**{t}**\n\n> {description}")
        e.set_author(name="⏰ Reminder Created")
        await self.ctx.reply(embed=e, ephemeral=True)


class ReminderView(View):
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

        if r['message_id'] is not None:
            msg = await channel.fetch_message(r['message_id'])
            if msg is not None:
                self.add_item(Button(label="Original Message", url=msg.jump_url))

        e = Embed(colour=0x00ff00)
        e.set_author(name="⏰ Reminder")
        e.description = timed_events.Timestamp(r['created_time']).date_relative
        e.description += f"\n\n> {r['reminder_content']}" if r['reminder_content'] is not None else ""
        self.add_item(view_utils.StopButton(row=0))

        try:
            self.message = await channel.send(f"<@{r['user_id']}>", embed=e, view=self)
        except HTTPException:
            try:
                self.message = await self.bot.get_user(r["user_id"]).send(embed=e, view=self)
            except HTTPException:
                pass

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute('''DELETE FROM reminders WHERE message_id = $1''', r['message_id'])
        finally:
            await self.bot.db.release(connection)

    async def interaction_check(self, interaction: Interaction):
        """Only reminder owner can interact to hide or snooze"""
        return interaction.user.id == self.record['user_id']

    async def on_timeout(self):
        """Delete the record"""
        self.clear_items()
        await self.message.edit(view=self)


class Reminders(commands.Cog):
    """Set yourself reminders"""

    def __init__(self, bot):
        self.bot = bot
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

    reminder = SlashCommandGroup("reminder", "manage or add reminders")

    @reminder.command()
    async def add(self, ctx):
        """Remind you of something at a specified time."""
        modal = RemindModal(ctx)
        await ctx.interaction.response.send_modal(modal)

    @commands.message_command(name="Create reminder")
    async def add_reminder(self, ctx, message):
        """Create a reminder with a link to a message."""
        modal = RemindModal(ctx, message=message)
        await ctx.interaction.response.send_modal(modal)

    @reminder.command()
    async def list(self, ctx):
        """Check your active reminders"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM reminders WHERE user_id = $1""", ctx.author.id)
        finally:
            await self.bot.db.release(connection)

        def short(r: asyncpg.Record):
            """Get oneline version of reminder"""
            time = timed_events.Timestamp(r['target_time']).time_relative
            guild = "@me" if r['guild_id'] is None else r['guild_id']
            j = f"https://com/channels/{guild}/{r['channel_id']}/{r['message_id']}"
            return f"**{time}**: [{r['reminder_content']}]({j})"

        _ = [short(r) for r in records] if records else ["You have no reminders set."]

        e = Embed(colour=0x7289DA, title="Your reminders")
        embeds = embed_utils.rows_to_embeds(e, _)

        view = view_utils.Paginator(ctx, embeds)
        view.message = await ctx.reply(content="Fetching your reminders...", view=view)
        await view.update()


def setup(bot):
    """Load the reminders Cog into the bot"""
    bot.add_cog(Reminders(bot))
