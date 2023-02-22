"""User Created Polls"""
from __future__ import annotations

from asyncio import sleep
from datetime import timedelta


from discord import (ButtonStyle, Embed, Colour, TextStyle, Interaction,
                     Message, HTTPException, SelectOption)
from discord.app_commands import command
from discord.ext.commands import Cog
from discord.ui import Button, Modal, TextInput, Select
from discord.utils import utcnow

from ext.utils.timed_events import Timestamp
from ext.utils.view_utils import BaseView

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core import Bot
    from asyncio import Task

# TODO: Database table, persistent views
_active_polls: set[Task] = set()


class PollButton(Button):
    """A Voting Button"""

    def __init__(self, custom_id: str, emoji: str = None,
                 label: str = None) -> None:

        super().__init__(emoji=emoji, label=label, style=ButtonStyle.primary,
                         custom_id=custom_id)

    async def callback(self, interaction: Interaction) -> Message:
        """Reply to user to let them know their vote has changed."""
        ej = f"{self.emoji} " if self.emoji is not None else ""

        e = f'Vote set to {ej}{self.label}'
        await interaction.response.send_message(e, ephemeral=True)

        votes: dict[str, list] = self.view.votes
        for vote_list in votes.values():
            try:
                vote_list.remove(interaction.user.id)
            except ValueError:
                continue

        self.view.votes[self.label].append(interaction.user.id)
        return await self.view.update()


class PollSelect(Select):
    """A Voting Dropdown"""

    def __init__(self, options: list[str], votes: int, custom_id: str) -> None:

        if votes == 1:
            ph = "Make your choice"
        else:
            ph = f"Select up to {votes} choices"

        super().__init__(
            max_values=min(votes, len(options)),
            options=[SelectOption(label=x, value=x) for x in options],
            placeholder=ph, custom_id=custom_id)

    async def callback(self, interaction: Interaction) -> None:
        """Remove old votes and add new ones."""

        bot: Bot = interaction.client

        if interaction.user.id in self.view.votes:
            rep = f'Your vote has been changed to {self.values}'
        else:
            rep = f'You have voted for {self.values}'

        await bot.reply(interaction, rep, ephemeral=True)

        votes: dict[str, list] = self.view.votes

        for vote_list in votes.values():
            try:
                vote_list.remove(interaction.user.id)
            except ValueError:
                continue

        [self.view.votes[x].append(interaction.user.id) for x in self.values]
        return await self.view.update()


class PollView(BaseView):
    """View for a poll commands"""

    def __init__(self, interaction: Interaction, question: str,
                 answers: list[str], minutes: int, votes: int) -> None:
        self.question: str = question
        self.votes: dict[str, list[int]] = {k: [] for k in answers}
        self.ends_at = Timestamp(utcnow() + timedelta(minutes=minutes))

        super().__init__(interaction)

        # Validate Uniqueness.
        if votes > 1 or len(self.votes) > 5:
            cid = f"{interaction.id}-{question}"
            self.add_item(PollSelect(self.votes, votes, custom_id=cid))
        else:
            for label in self.votes.keys():
                cid = f"{interaction.id}-{label}"
                self.add_item(PollButton(label=label, custom_id=cid))

        task = interaction.client.loop.create_task(
            self.destruct(minutes), name=f"Poll - {question}")
        _active_polls.add(task)
        task.add_done_callback(_active_polls.discard)

    async def destruct(self, minutes: int) -> Message:
        """End the poll after the specified amount of minutes."""
        await sleep(60 * minutes)

        e = Embed(colour=Colour.green(), title=self.question)
        e.set_author(name=f"{self.interaction.user.name} asked…",
                     icon_url=self.interaction.user.display_avatar.url)

        srt = sorted(self.votes, key=lambda x: len(self.votes[x]),
                     reverse=True)

        if list(srt):
            winning = self.votes[key := srt.pop(0)]
            voters = ', '.join([f"<@{i}>" for i in winning])
            e.description = f"🥇 **{key}**: {len(winning)} votes\n{voters}\n\n"

            for k in srt:
                voters = ', '.join([f"<@{i}>" for i in self.votes[k]])
                votes = len(self.votes[k])
                e.description += f"**{k}**: {votes} votes\n{voters}\n\n"
        else:
            e.description = "No Votes were cast"

        votes_cast = sum([len(self.votes[i]) for i in self.votes])
        e.set_footer(text=f"Final Results | {votes_cast} votes")

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

        e: Embed = Embed(colour=Colour.og_blurple(), title=self.question + "?")

        e.set_author(name=f"{self.interaction.user.name} asks…",
                     icon_url=self.interaction.user.display_avatar.url)

        srt = sorted(self.votes, key=lambda x: len(self.votes[x]),
                     reverse=True)

        if list(srt):
            winning = self.votes[key := srt.pop(0)]
            voters = ', '.join([f"<@{i}>" for i in winning])
            e.description = (f"Poll Ends at {self.ends_at.time_relative}\n"
                             f"🥇 **{key}: {len(winning)} votes**\n{voters}\n")

            for k in srt:
                voters = ', '.join([f"<@{i}>" for i in self.votes[k]])
                votes = len(self.votes[k])

                e.description += f"**{k}: {votes} votes**\n{voters}\n"
        else:
            e.description = "No votes have been cast"

        total_votes = sum([len(self.votes[i]) for i in self.votes])
        e.set_footer(text=f"Voting in Progress | {total_votes} votes")
        await self.bot.reply(self.interaction, content, view=self, embed=e)


class PollModal(Modal, title="Create a poll"):
    """UI Sent to user to ask them to create a poll."""

    minutes = TextInput(
        label="Enter Poll Duration in Minutes", default="60",
        placeholder="60", max_length=4)

    question = TextInput(
        label="Question", placeholder="Enter your question here")

    answers = TextInput(
        label="Answers (one per line)", style=TextStyle.paragraph,
        placeholder="Red\nBlue\nYellow")

    votes = TextInput(
        label="Max votes per user", default="1",
        placeholder="1", max_length=2)

    def __init__(self) -> None:
        super().__init__()

    async def on_submit(self, interaction: Interaction) -> Message:
        """When the Modal is submitted, pick at random and send back"""
        q = self.question.value
        answers = self.answers.value.split('\n')[:25]

        # Discard null
        answers = [i.strip() for i in answers if i.strip()]

        if len(answers) < 2:
            answers = ["Yes", "No"]

        try:
            max_votes = int(self.votes.value)
        except ValueError:
            max_votes = 1
            err = "Invalid number of votes provided, defaulting to 1"
            await interaction.client.error(interaction, err)

        try:
            time = int(self.minutes.value)
        except ValueError:
            time = 60
            err = "Invalid number of minutes provided, defaulting to 60"
            await interaction.client.error(interaction, )

        await PollView(interaction, q, answers, time, max_votes).update()


class Poll(Cog):
    """User Created Polls"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @command()
    async def poll(self, interaction: Interaction) -> PollModal:
        """Create a poll with multiple answers.
           Use the UI to set your options."""
        return await interaction.response.send_modal(PollModal())


async def setup(bot: Bot) -> None:
    """Add the Poll cog to the Bot"""
    await bot.add_cog(Poll(bot))
