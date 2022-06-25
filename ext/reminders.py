"""Commands for creating time triggered message reminders."""
import datetime
from typing import TYPE_CHECKING, Union, Optional

from asyncpg import Record
from dateutil.relativedelta import relativedelta
from discord import Embed, Interaction, HTTPException, TextStyle, Message
from discord.app_commands import Group, context_menu
from discord.ext.commands import Cog
from discord.ui import View, Button, Modal, TextInput
from discord.utils import sleep_until

from ext.utils.embed_utils import rows_to_embeds
from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import Paginator

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot
    from discord import Client


# TODO: Slash attachments pass - Add an attachment.


class Hide(Button):
    """A generic button to stop a View"""

    def __init__(self, row=3):
        super().__init__(label="Hide", emoji="🚫", row=row)

    async def callback(self, interaction: Interaction):
        """Do this when button is pressed"""
        await self.view.message.delete()


async def spool_reminder(bot: Union['Bot', 'PBot'], r: Record):
    """Bulk dispatch reminder messages"""
    # Get data from records
    await sleep_until(r["target_time"])
    rv = ReminderView(bot, r)
    await rv.dispatch()


class RemindModal(Modal):
    """A Modal Dialogue asking the user to enter a time & message for their reminder."""
    months = TextInput(label="Number of months", default="0", placeholder="1", max_length=2, required=False)
    days = TextInput(label="Number of days", default="0", placeholder="1", max_length=2, required=False)
    hours = TextInput(label="Number of hours", default="0", placeholder="1", max_length=2, required=False)
    minutes = TextInput(label="Number of minutes", default="0", placeholder="1", max_length=2, required=False)
    description = TextInput(label="Reminder Description", placeholder="Remind me about…", style=TextStyle.paragraph)

    def __init__(self, bot: Union['Bot', 'PBot', 'Client'], title: str, target_message: Message = None):
        super().__init__(title=title)
        self.interaction: Optional[Interaction] = None
        self.target_message: Message = target_message
        self.bot: Bot | Client | PBot = bot

    async def on_submit(self, interaction: Interaction):
        """Insert entry to the database when the form is submitted"""
        hours = int(self.hours.value) if self.hours.value.isdigit() else 0
        minutes = int(self.minutes.value) if self.minutes.value.isdigit() else 0
        days = int(self.days.value) if self.days.value.isdigit() else 0
        months = int(self.months.value) if self.months.value.isdigit() else 0
        delta = relativedelta(minutes=minutes, hours=hours, days=days, months=months)

        remind_at = datetime.datetime.now(datetime.timezone.utc) + delta
        msg_id = None if self.target_message is None else self.target_message.id
        gid = None if interaction.guild is None else interaction.guild.id
        ch_id = interaction.channel.id
        time = datetime.datetime.now(datetime.timezone.utc)

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                record = await connection.fetchrow("""INSERT INTO reminders
                (message_id, channel_id, guild_id, reminder_content, created_time, target_time, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""", msg_id, ch_id, gid, self.description.value,
                                                   time, remind_at, interaction.user.id)
        finally:
            await self.bot.db.release(connection)

        self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(self.bot, record)))

        t = Timestamp(remind_at).time_relative
        e: Embed = Embed(colour=0x00ffff, description=f"**{t}**\n\n> {self.description}")
        e.set_author(name="⏰ Reminder Created")
        await self.bot.reply(interaction, embed=e, ephemeral=True)


class ReminderView(View):
    """View for user requested reminders"""

    def __init__(self, bot: 'Bot', r: Record):
        super().__init__(timeout=None)
        self.bot: Bot = bot
        self.record: Record = r
        self.message: Optional[Message] = None

    async def dispatch(self):
        """Send message to appropriate destination"""
        r = self.record

        channel = self.bot.get_channel(r['channel_id'])

        if r['message_id'] is not None:
            msg = await channel.fetch_message(r['message_id'])
            if msg is not None:
                self.add_item(Button(label="Original Message", url=msg.jump_url))

        e: Embed = Embed(colour=0x00ff00)
        e.set_author(name="⏰ Reminder")
        e.description = Timestamp(r['created_time']).date_relative
        e.description += f"\n\n> {r['reminder_content']}" if r['reminder_content'] is not None else ""
        self.add_item(Hide(row=0))

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

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Only reminder owner can interact to hide or snooze"""
        return interaction.user.id == self.record['user_id']


@context_menu(name="Create reminder")
async def add_reminder(interaction: Interaction, message: Message):
    """Create a reminder with a link to a message."""
    await interaction.response.send_modal(
        RemindModal(interaction.client, title="Remind me about this message", target_message=message))


class Reminders(Cog):
    """Set yourself reminders"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot
        self.bot.reminders = []  # A list of tasks.
        self.bot.tree.add_command(add_reminder)

    async def cog_load(self) -> None:
        """Do when the cog loads"""
        connection = await self.bot.db.acquire()
        records = await connection.fetch("""SELECT * FROM reminders""")
        async with connection.transaction():
            for r in records:
                self.bot.reminders.append(self.bot.loop.create_task(spool_reminder(self.bot, r)))
        await self.bot.db.release(connection)

    async def cog_unload(self) -> None:
        """Cancel all active tasks on cog reload"""
        self.bot.tree.remove_command(add_reminder.name)
        for i in self.bot.reminders:
            i.cancel()

    reminder = Group(name="reminder", description="Set Reminders for yourself")

    @reminder.command()
    async def add(self, interaction: Interaction) -> Message:
        """Remind you of something at a specified time."""
        return await interaction.response.send_modal(RemindModal(self.bot, title="Create a reminder"))

    @reminder.command()
    async def list(self, interaction: Interaction) -> Message:
        """Check your active reminders"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM reminders WHERE user_id = $1""", interaction.user.id)
        finally:
            await self.bot.db.release(connection)

        def short(r: Record):
            """Get oneline version of reminder"""
            time = Timestamp(r['target_time']).time_relative
            guild = "@me" if r['guild_id'] is None else r['guild_id']
            j = f"https://com/channels/{guild}/{r['channel_id']}/{r['message_id']}"
            return f"**{time}**: [{r['reminder_content']}]({j})"

        _ = [short(r) for r in records] if records else ["You have no reminders set."]

        e: Embed = Embed(colour=0x7289DA, title="Your reminders")
        embeds = rows_to_embeds(e, _)

        view = Paginator(self.bot, interaction, embeds)
        return await view.update()


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Load the reminders Cog into the bot"""
    await bot.add_cog(Reminders(bot))
