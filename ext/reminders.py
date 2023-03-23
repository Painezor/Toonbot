"""Commands for creating time triggered message reminders."""
from __future__ import annotations

import logging
import typing

import asyncpg
from dateutil.relativedelta import relativedelta
from discord import (
    HTTPException,
    Message,
)

import discord
from discord.ext import commands
from discord.utils import utcnow

from ext.utils import embed_utils, view_utils, timed_events

if typing.TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


logger = logging.getLogger("reminders")


async def spool_reminder(bot: Bot | PBot, r: asyncpg.Record):
    """Bulk dispatch reminder messages"""
    # Get data from records
    await discord.utils.sleep_until(r["target_time"])
    rv = ReminderView(bot, r)
    await rv.send_reminder()


class RemindModal(discord.ui.Modal):
    """A Modal Dialogue asking the user to enter a time & message for
    their reminder."""

    months = discord.ui.TextInput(
        label="Number of months",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    days = discord.ui.TextInput(
        label="Number of days",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    hours = discord.ui.TextInput(
        label="Number of hours",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    minutes = discord.ui.TextInput(
        label="Number of minutes",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    description = discord.ui.TextInput(
        label="Reminder Description",
        placeholder="Remind me about…",
        style=discord.TextStyle.paragraph,
    )

    def __init__(
        self, title: str, message: typing.Optional[discord.Message] = None
    ):
        super().__init__(title=title)
        self.message: typing.Optional[discord.Message] = message

    async def on_submit(self, interaction: discord.Interaction[Bot | PBot]):
        """Insert entry to the database when the form is submitted"""
        h = int(self.hours.value) or 0
        m = int(self.minutes.value) or 0
        d = int(self.days.value) or 0
        mo = int(self.months.value) or 0
        delta = relativedelta(minutes=m, hours=h, days=d, months=mo)

        time = utcnow()
        remind_at = time + delta
        msg_id = self.message.id if self.message else None
        gid = interaction.guild.id if interaction.guild else None
        ch_id = interaction.channel.id if interaction.channel else None
        desc = self.description.value
        u = interaction.user.id
        bot = interaction.client
        sql = """INSERT INTO reminders (message_id, channel_id, guild_id,
                 reminder_content, created_time, target_time, user_id)
                 VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *"""

        args = [sql, msg_id, ch_id, gid, desc, time, remind_at, u]
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetchrow(*args)

        reminder_task = bot.loop.create_task(spool_reminder(bot, r))
        bot.reminders.add(reminder_task)
        reminder_task.add_done_callback(bot.reminders.discard)

        t = timed_events.Timestamp(remind_at).time_relative
        e = discord.Embed(colour=0x00FFFF, description=f"**{t}**\n\n> {desc}")
        e.set_author(name="⏰ Reminder Created")
        return await interaction.response.send_message(embed=e, ephemeral=True)


class ReminderView(discord.ui.View):
    """View for user requested reminders"""

    def __init__(self, bot: Bot | PBot, r: asyncpg.Record):
        super().__init__(timeout=None)
        self.bot: Bot | PBot = bot
        self.record: asyncpg.Record = r

    async def send_reminder(self):
        """Send message to appropriate destination"""
        r = self.record

        channel = self.bot.get_channel(r["channel_id"])

        channel = typing.cast(discord.TextChannel, channel)

        if r["message_id"] is not None:
            msg = await channel.fetch_message(r["message_id"])
            if msg is not None:
                lbl = "Original Message"
                btn = discord.ui.Button(url=msg.jump_url, label=lbl)
                self.add_item(btn)

        e = discord.Embed(colour=0x00FF00)
        e.set_author(name="⏰ Reminder")
        e.description = timed_events.Timestamp(r["created_time"]).date_relative

        if r["reminder_content"]:
            e.description += f"\n\n> {r['reminder_content']}"

        self.add_item(view_utils.Stop(row=0))

        try:
            await channel.send(f"<@{r['user_id']}>", embed=e, view=self)
        except discord.HTTPException:
            u = self.bot.get_user(r["user_id"])
            if u is not None:
                try:
                    await u.send(embed=e, view=self)
                except HTTPException:
                    pass

        sql = """DELETE FROM reminders WHERE created_time = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, r["created_time"])

    async def interaction_check(
        self, interaction: discord.Interaction[Bot]
    ) -> bool:
        """Only reminder owner can interact to hide or snooze"""
        return interaction.user.id == self.record["user_id"]


@discord.app_commands.context_menu(name="Create reminder")
async def create_reminder(
    interaction: discord.Interaction[Bot | PBot], message: discord.Message
) -> None:
    """Create a reminder with a link to a message."""
    modal = RemindModal("Remind me", message)
    return await interaction.response.send_modal(modal)


class Reminders(commands.Cog):
    """Set yourself reminders"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot
        self.bot.reminders = set()  # A set of tasks.
        self.bot.tree.add_command(create_reminder)

    async def cog_load(self) -> None:
        """Do when the cog loads"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM reminders""")

        for r in records:
            self.bot.reminders.add(
                self.bot.loop.create_task(spool_reminder(self.bot, r))
            )

    async def cog_unload(self) -> None:
        """Cancel all active tasks on cog reload"""
        self.bot.tree.remove_command(create_reminder.name)
        for i in self.bot.reminders:
            i.cancel()

    reminder = discord.app_commands.Group(
        name="reminders", description="Set Reminders for yourself"
    )

    @reminder.command()
    async def create(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """Remind you of something at a specified time."""
        await interaction.response.send_modal(RemindModal("Create a reminder"))

    @reminder.command()
    async def list(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> Message:
        """Check your active reminders"""

        sql = """SELECT * FROM reminders WHERE user_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rec = await connection.fetch(sql, interaction.user.id)

        def short(r: asyncpg.Record):
            """Get oneline version of reminder"""
            time = timed_events.Timestamp(r["target_time"]).time_relative
            guild = "@me" if r["guild_id"] is None else r["guild_id"]

            m = r["message_id"]
            j = f"https://com/channels/{guild}/{r['channel_id']}/{m}"
            return f"**{time}**: [{r['reminder_content']}]({j})"

        rows = [short(r) for r in rec] if rec else ["You have no reminders"]
        e = discord.Embed(colour=0x7289DA, title="Your reminders")

        embeds = embed_utils.rows_to_embeds(e, rows)
        return await view_utils.Paginator(interaction, embeds).update()


async def setup(bot: Bot | PBot) -> None:
    """Load the reminders Cog into the bot"""
    await bot.add_cog(Reminders(bot))
