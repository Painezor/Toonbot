"""Commands for creating time triggered message reminders."""
from __future__ import annotations

import logging
import typing

import asyncpg
from dateutil.relativedelta import relativedelta

import discord
from discord.ext import commands

from ext.utils import embed_utils, view_utils, timed_events

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]


logger = logging.getLogger("reminders")


async def spool_reminder(bot: Bot | PBot, record: asyncpg.Record) -> None:
    """Bulk dispatch reminder messages"""
    # Get data from records
    await discord.utils.sleep_until(record["target_time"])
    view = ReminderView(bot, record)
    await view.send_reminder()


class RemindModal(discord.ui.Modal):
    """A Modal Dialogue asking the user to enter a time & message for
    their reminder."""

    months: discord.ui.TextInput[RemindModal] = discord.ui.TextInput(
        label="Number of months",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    days: discord.ui.TextInput[RemindModal] = discord.ui.TextInput(
        label="Number of days",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    hours: discord.ui.TextInput[RemindModal] = discord.ui.TextInput(
        label="Number of hours",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    minutes: discord.ui.TextInput[RemindModal] = discord.ui.TextInput(
        label="Number of minutes",
        default="0",
        placeholder="1",
        max_length=2,
        required=False,
    )
    description: discord.ui.TextInput[RemindModal] = discord.ui.TextInput(
        label="Reminder Description",
        placeholder="Remind me about…",
        style=discord.TextStyle.paragraph,
    )

    def __init__(
        self, title: str, message: typing.Optional[discord.Message] = None
    ):
        super().__init__(title=title)
        self.message: typing.Optional[discord.Message] = message

    async def on_submit(  # type: ignore
        self, interaction: Interaction, /
    ) -> None:
        """Insert entry to the database when the form is submitted"""
        delta = relativedelta()
        delta.hours = int(self.hours.value) or 0
        delta.minutes = int(self.minutes.value) or 0
        delta.day = int(self.days.value) or 0
        delta.months = int(self.months.value) or 0

        time = discord.utils.utcnow()
        rmd = time + delta
        mid = self.message.id if self.message else None
        gid = interaction.guild.id if interaction.guild else None
        if interaction.channel is not None:
            cid = interaction.channel.id
        else:
            cid = None
        dsc = self.description.value
        uid = interaction.user.id
        bot = interaction.client
        sql = """INSERT INTO reminders (message_id, channel_id, guild_id,
                 reminder_content, created_time, target_time, user_id)
                 VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *"""

        args = [mid, cid, gid, dsc, time, rmd, uid]
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                record = await connection.fetchrow(sql, *args)

        if record is None:
            return

        reminder_task = bot.loop.create_task(spool_reminder(bot, record))
        bot.reminders.add(reminder_task)
        reminder_task.add_done_callback(bot.reminders.discard)

        time = timed_events.Timestamp(rmd).time_relative
        embed = discord.Embed(colour=0x00FFFF)
        embed.description = f"**{time}**\n\n> {dsc}"
        embed.set_author(name="⏰ Reminder Created")

        send = interaction.response.send_message
        return await send(embed=embed, ephemeral=True)


class ReminderView(view_utils.BaseView):
    """View for user requested reminders"""

    def __init__(self, bot: Bot | PBot, record: asyncpg.Record):
        self.bot: Bot | PBot = bot
        self.record: asyncpg.Record = record

        user = discord.Object(id=record["user_id"])  # Pseudo-User.
        super().__init__(typing.cast(discord.User, user), timeout=None)

    async def send_reminder(self):
        """Send message to appropriate destination"""
        record = self.record

        channel = self.bot.get_channel(record["channel_id"])

        channel = typing.cast(discord.TextChannel, channel)

        if (msg := record["message_id"]) is not None:
            guild = record["guild_id"]
            cid = record["channel_id"]
            jump = f"https://www.discord.com/channels/{guild}/{cid}/{msg}"
            lbl = "Original Message"
            self.add_item(discord.ui.Button(url=jump, label=lbl))

        embed = discord.Embed(colour=0x00FF00)
        embed.set_author(name="⏰ Reminder")

        time = record["created_time"]
        embed.description = timed_events.Timestamp(time).date_relative

        if record["reminder_content"]:
            embed.description += f"\n\n> {record['reminder_content']}"

        try:
            mention = f"<@{record['user_id']}>"
            await channel.send(mention, embed=embed, view=self)
        except (discord.HTTPException, AttributeError):
            user = self.bot.get_user(record["user_id"])
            if user is not None:
                try:
                    await user.send(embed=embed, view=self)
                except discord.HTTPException:
                    pass

        sql = """DELETE FROM reminders WHERE created_time = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                await connection.execute(sql, record["created_time"])

    async def interaction_check(  # type: ignore
        self, interaction: Interaction, /
    ) -> bool:
        """Only reminder owner can interact to hide or snooze"""
        return interaction.user.id == self.record["user_id"]


@discord.app_commands.context_menu(name="Create reminder")
async def create_reminder(
    interaction: Interaction, message: discord.Message
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

        for i in records:
            task = self.bot.loop.create_task(spool_reminder(self.bot, i))
            self.bot.reminders.add(task)
            task.add_done_callback(self.bot.reminders.discard)

    async def cog_unload(self) -> None:
        """Cancel all active tasks on cog reload"""
        self.bot.tree.remove_command(create_reminder.name)
        for i in self.bot.reminders:
            i.cancel()

    reminder = discord.app_commands.Group(
        name="reminders", description="Set Reminders for yourself"
    )

    @reminder.command()
    async def create(self, interaction: Interaction) -> None:
        """Remind you of something at a specified time."""
        await interaction.response.send_modal(RemindModal("Create a reminder"))

    @reminder.command()
    async def list(self, interaction: Interaction) -> None:
        """Check your active reminders"""

        sql = """SELECT * FROM reminders WHERE user_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rec = await connection.fetch(sql, interaction.user.id)

        def short(record: asyncpg.Record):
            """Get oneline version of reminder"""
            time = timed_events.Timestamp(record["target_time"]).time_relative
            guild = "@me" if record["guild_id"] is None else record["guild_id"]

            msg = record["message_id"]
            cid = record["channel_id"]
            jump = f"https://www.discord.com/channels/{guild}/{cid}/{msg}"
            return f"**{time}**: [{record['reminder_content']}]({jump})"

        rows = [short(r) for r in rec] if rec else ["You have no reminders"]
        embed = discord.Embed(colour=0x7289DA, title="Your reminders")

        embeds = embed_utils.rows_to_embeds(embed, rows)
        view = view_utils.Paginator(interaction.user, embeds)
        await interaction.response.send_message(view=view, embed=view.pages[0])


async def setup(bot: Bot | PBot) -> None:
    """Load the reminders Cog into the bot"""
    await bot.add_cog(Reminders(bot))
