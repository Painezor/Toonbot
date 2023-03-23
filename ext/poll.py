"""User Created Polls"""
from __future__ import annotations

from asyncio import sleep
from datetime import timedelta

import asyncio
import discord
from discord.ext import commands
from discord.ui import Select
from discord.utils import utcnow

from ext.utils import view_utils, timed_events

import typing

if typing.TYPE_CHECKING:
    from core import Bot

# TODO: Database table, persistent views
_active_polls: set[asyncio.Task] = set()


class PollButton(discord.ui.Button):
    """A Voting Button"""

    view: PollView

    def __init__(
        self, custom_id: str, label: str, emoji: typing.Optional[str] = None
    ) -> None:

        super().__init__(
            emoji=emoji,
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
        )

        self.label: str

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Reply to user to let them know their vote has changed."""
        ej = f"{self.emoji} " if self.emoji is not None else ""

        e = f"Vote set to {ej}{self.label}"
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

    view: PollView

    def __init__(self, options: list[str], votes: int, custom_id: str) -> None:
        v = votes
        ph = "Make your choice" if votes == 1 else f"Select up to {v} choices"

        super().__init__(
            max_values=min(votes, len(options)),
            options=[discord.SelectOption(label=x, value=x) for x in options],
            placeholder=ph,
            custom_id=custom_id,
        )

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Remove old votes and add new ones."""
        if interaction.user.id in self.view.votes:
            rep = f"Your vote has been changed to {self.values}"
        else:
            rep = f"You have voted for {self.values}"

        await interaction.response.send_message(content=rep, ephemeral=True)

        votes: dict[str, list] = self.view.votes

        for vote_list in votes.values():
            try:
                vote_list.remove(interaction.user.id)
            except ValueError:
                continue

        [self.view.votes[x].append(interaction.user.id) for x in self.values]
        return await self.view.update()


class PollView(view_utils.BaseView):
    """View for a poll commands"""

    def __init__(
        self,
        interaction: discord.Interaction[Bot],
        question: str,
        answers: list[str],
        minutes: int,
        votes: int,
    ) -> None:
        self.question: str = question
        self.votes: dict[str, list[int]] = {k: [] for k in answers}

        ending = utcnow() + timedelta(minutes=minutes)
        self.ends_at = timed_events.Timestamp(ending)

        super().__init__(interaction)

        # Validate Uniqueness.
        if votes > 1 or len(self.votes) > 5:
            cid = f"{interaction.id}-{question}"
            self.add_item(PollSelect(answers, votes, custom_id=cid))
        else:
            for label in self.votes.keys():
                cid = f"{interaction.id}-{label}"
                self.add_item(PollButton(label=label, custom_id=cid))

        task = interaction.client.loop.create_task(
            self.destruct(minutes), name=f"Poll - {question}"
        )
        _active_polls.add(task)
        task.add_done_callback(_active_polls.discard)

    def read_votes(self) -> str:
        output = ""

        vt = self.votes
        srt = sorted(vt, key=lambda x: len(vt[x]), reverse=True)

        if list(srt):
            winning = self.votes[key := srt.pop(0)]
            voters = ", ".join([f"<@{i}>" for i in winning])
            output = f"🥇 **{key}**: {len(winning)} votes\n{voters}\n\n"

            for k in srt:
                voters = ", ".join([f"<@{i}>" for i in self.votes[k]])
                votes = len(self.votes[k])
                output += f"**{k}**: {votes} votes\n{voters}\n\n"
        else:
            output = "No Votes cast"
        return output

    async def destruct(self, minutes: int) -> discord.Message | None:
        """End the poll after the specified amount of minutes."""
        await sleep(60 * minutes)

        e = discord.Embed(colour=discord.Colour.green())
        e.title = self.question + "?"
        e.description = self.read_votes()

        u = self.interaction.user
        e.set_author(name=f"{u.name} asked…", icon_url=u.display_avatar.url)

        votes_cast = sum([len(self.votes[i]) for i in self.votes])
        e.set_footer(text=f"Final Results | {votes_cast} votes")

        try:
            return await self.interaction.edit_original_response(embed=e)
        except discord.HTTPException:
            pass

        chan = typing.cast(discord.TextChannel, self.interaction.channel)
        if chan is not None:
            try:
                return await chan.send(embed=e)
            except (discord.NotFound, discord.Forbidden):
                pass

    async def update(
        self, content: typing.Optional[str] = None
    ) -> discord.InteractionMessage:
        """Refresh the view and send to user"""

        e = discord.Embed(title=self.question + "?")
        e.colour = discord.Colour.og_blurple()

        e.description = self.read_votes()

        u = self.interaction.user
        e.set_author(name=f"{u.name} asked…", icon_url=u.display_avatar.url)

        total_votes = sum([len(self.votes[i]) for i in self.votes])
        e.set_footer(text=f"Voting in Progress | {total_votes} votes")

        edit = self.interaction.edit_original_response
        return await edit(content=content, view=self, embed=e)


class PollModal(discord.ui.Modal, title="Create a poll"):
    """UI Sent to user to ask them to create a poll."""

    minutes = discord.ui.TextInput(
        label="Enter Poll Duration in Minutes",
        default="60",
        placeholder="60",
        max_length=4,
    )

    question = discord.ui.TextInput(
        label="Question", placeholder="Enter your question here"
    )

    answers = discord.ui.TextInput(
        label="Answers (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Red\nBlue\nYellow",
    )

    votes = discord.ui.TextInput(
        label="Max votes per user", default="1", placeholder="1", max_length=2
    )

    def __init__(self) -> None:
        super().__init__()

    async def on_submit(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When the Modal is submitted, pick at random and send back"""
        q = self.question.value
        answers = self.answers.value.split("\n")[:25]

        # Discard null
        answers = [i.strip() for i in answers if i.strip()]

        if len(answers) < 2:
            answers = ["Yes", "No"]

        try:
            votes = int(self.votes.value)
        except ValueError:
            votes = 1
            err = "Invalid number of votes provided, defaulting to 1"
            return await interaction.client.error(interaction, err)

        try:
            time = int(self.minutes.value)
        except ValueError:
            time = 60
            err = "Invalid number of minutes provided, defaulting to 60"
            return await interaction.client.error(interaction, err)

        return await PollView(interaction, q, answers, time, votes).update()


class Poll(commands.Cog):
    """User Created Polls"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @discord.app_commands.command()
    async def poll(self, interaction: discord.Interaction[Bot]) -> None:
        """Create a poll with multiple answers.
        Use the UI to set your options."""
        return await interaction.response.send_modal(PollModal())


async def setup(bot: Bot) -> None:
    """Add the Poll cog to the Bot"""
    await bot.add_cog(Poll(bot))
