"""User Created Polls"""
from __future__ import annotations

from asyncio import sleep
from datetime import timedelta
from typing import TYPE_CHECKING

from discord import ButtonStyle, Embed, Colour, TextStyle, Interaction, Message, HTTPException, SelectOption
from discord.app_commands import command
from discord.ext.commands import Cog
from discord.ui import Button, View, Modal, TextInput, Select
from discord.utils import utcnow

from ext.utils.timed_events import Timestamp

if TYPE_CHECKING:
    from core import Bot
    from asyncio import Task

# TODO: Database table, persistent views
_active_polls: set[Task] = set()


class PollButton(Button):
    """A Voting Button"""

    def __init__(self, custom_id: str, emoji: str = None, label: str = None) -> None:
        super().__init__(emoji=emoji, label=label, style=ButtonStyle.primary, custom_id=custom_id)

    async def callback(self, interaction: Interaction) -> Message:
        """Reply to user to let them know their vote has changed."""
        bot: Bot = interaction.client
        ej = f"{self.emoji} " if self.emoji is not None else ""
        if interaction.user.id in self.view.votes:
            await bot.reply(interaction, f'Your vote has been changed to {ej}{self.label}', ephemeral=True)
        else:
            await bot.reply(interaction, f'You have voted for {ej}{self.label}', ephemeral=True)

        votes: dict[str, list] = self.view.votes

        for key, vote_list in votes.items():
            try:
                vote_list.remove(interaction.user.id)
            except ValueError:
                continue

        self.view.votes[self.label].append(interaction.user.id)
        return await self.view.update()


class PollSelect(Select):
    """A Voting Dropdown"""

    def __init__(self, options: list[str], votes: int, custom_id: str) -> None:
        ph = "Make your choice" if votes == 1 else f"Select up to {votes} choices"
        super().__init__(max_values=min(votes, len(options)),
                         options=[SelectOption(label=x, value=x) for x in options],
                         placeholder=ph, custom_id=custom_id)

    async def callback(self, interaction: Interaction) -> None:
        """Remove old votes and add new ones."""
        bot: Bot = interaction.client
        if interaction.user.id in self.view.votes:
            await bot.reply(interaction, f'Your vote has been changed to {self.values}', ephemeral=True)
        else:
            await bot.reply(interaction, f'You have voted for {self.values}', ephemeral=True)

        votes: dict[str, list] = self.view.votes

        for key, vote_list in votes.items():
            try:
                vote_list.remove(interaction.user.id)
            except ValueError:
                continue

        [self.view.votes[x].append(interaction.user.id) for x in self.values]
        return await self.view.update()


class PollView(View):
    """View for a poll commands"""

    def __init__(self, interaction: Interaction, question: str, answers: list[str], minutes: int, votes: int) -> None:
        self.interaction: Interaction = interaction
        self.question: str = question
        self.votes: dict[str, list[int]] = {k: [] for k in answers}
        self.bot: Bot = interaction.client

        self.ends_at: Timestamp = Timestamp(utcnow() + timedelta(minutes=minutes))

        super().__init__()

        # Validate Uniqueness.
        if votes > 1 or len(self.votes) > 5:
            self.add_item(PollSelect(self.votes, votes, custom_id=f"{interaction.id}-{question}"))
        else:
            for label in self.votes.keys():
                self.add_item(PollButton(label=label, custom_id=f"{interaction.id}-{label}"))

        task = interaction.client.loop.create_task(self.destruct(minutes), name=f"Poll - {question}")
        _active_polls.add(task)
        task.add_done_callback(_active_polls.discard)

    async def destruct(self, minutes: int) -> Message:
        """End the poll after the specified amount of minutes."""
        await sleep(60 * minutes)

        e = Embed(colour=Colour.green(), title=self.question)
        e.set_author(name=f"{self.interaction.user.name} asked…", icon_url=self.interaction.user.display_avatar.url)

        srt = sorted(self.votes, key=lambda key: len(self.votes[key]), reverse=True)

        if srt:
            winning = srt.pop(0)
            voters = ', '.join([self.bot.get_user(i).mention for i in winning])
            e.description = f"🥇 **{winning}: {len(self.votes[winning])} votes**\n{' '.join(voters)}\n"

            for k in srt:
                voters = ', '.join([self.bot.get_user(i).mention for i in self.votes[k]])
                e.description += f"**{k}: {len(self.votes[k])} votes**\n{voters}\n"
        else:
            e.description = "No Votes were cast"

        e.set_footer(text=f"Final Results | {sum([len(self.votes[i]) for i in self.votes])} votes")

        try:
            m = await self.interaction.channel.send(embed=e)
        except HTTPException:
            m = await self.interaction.edit_original_response(embed=e)
        else:
            try:
                await self.interaction.delete_original_response()
            except HTTPException:
                pass

        return m

    async def update(self, content: str = None) -> Message:
        """Refresh the view and send to user"""
        e: Embed = Embed(colour=Colour.og_blurple(), title=self.question + "?", description="")
        e.set_author(name=f"{self.interaction.user.name} asks…", icon_url=self.interaction.user.display_avatar.url)

        srt = sorted(self.votes, key=lambda key: len(self.votes[key]), reverse=True)
        if srt:
            winning = srt.pop(0)
            voters = ', '.join([self.bot.get_user(i).mention for i in winning])
            e.description = f"Poll Ends at {self.ends_at.time_relative}\n" \
                            f"🥇 **{winning}: {len(self.votes[winning])} votes**\n" \
                            f"{' '.join(voters)}\n"

            for k in srt:
                voters = ', '.join([self.bot.get_user(i).mention for i in self.votes[k]])
                e.description += f"**{k}: {len(self.votes[k])} votes**\n{voters}\n"
        else:
            e.description = "No votes yet."

        e.set_footer(text=f"Voting in Progress | {sum([len(self.votes[i]) for i in self.votes])} votes")
        return await self.bot.reply(self.interaction, content=content, view=self, embed=e)


class PollModal(Modal, title="Create a poll"):
    """UI Sent to user to ask them to create a poll."""
    minutes = TextInput(label="Enter Poll Duration in Minutes", default="60", placeholder="60", max_length=4)
    question = TextInput(label="Question", placeholder="Enter your question here")
    answers = TextInput(label="Answers (one per line)", style=TextStyle.paragraph, placeholder="Red\nBlue\nYellow")
    votes = TextInput(label="Max votes per user", default="1", placeholder="1", max_length=2)

    def __init__(self) -> None:
        super().__init__()

    async def on_submit(self, interaction: Interaction) -> Message:
        """When the Modal is submitted, pick at random and send the reply back"""
        question = self.question.value
        answers = self.answers.value.split('\n')[:25]

        # Discard null
        answers = [i.strip() for i in answers if i.strip()]

        if len(answers) < 2:
            answers = ["Yes", "No"]

        try:
            max_votes = int(self.votes.value)
        except ValueError:
            max_votes = 1
            await interaction.client.error(interaction, "Invalid number of votes provided, defaulting to 1")

        try:
            time = int(self.minutes.value)
        except ValueError:
            time = 60
            await interaction.client.error(interaction, "Invalid number of minutes provided, defaulting to 60")

        return await PollView(interaction, question, answers, time, max_votes).update()


class Poll(Cog):
    """User Created Polls"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @command()
    async def poll(self, interaction: Interaction) -> PollModal:
        """Create a poll with multiple answers. Use the UI to set your options."""
        return await interaction.response.send_modal(PollModal())


async def setup(bot: Bot) -> None:
    """Add the Poll cog to the Bot"""
    await bot.add_cog(Poll(bot))
