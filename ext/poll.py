"""User Created Polls"""
from __future__ import annotations

import asyncio
import datetime
import operator
import typing

import discord
from discord.ui import TextInput
from discord import SelectOption
from discord.ext import commands

from ext.utils import timed_events, view_utils

if typing.TYPE_CHECKING:
    from core import Bot

    Interaction: typing.TypeAlias = discord.Interaction[Bot]
    User: typing.TypeAlias = discord.User | discord.Member


class PollView(view_utils.BaseView):
    """View for a poll commands"""

    def __init__(
        self,
        question: str,
        answers: list[str],
        minutes: int,
        max_votes: int,
    ) -> None:
        self.question: str = question
        self.votes: dict[str, set[int]] = {k: set() for k in answers}

        self.end = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        self.ends_at = timed_events.Timestamp(self.end).countdown

        super().__init__(None)

        self.dropdown.options = [SelectOption(label=i) for i in answers]

        # Validate Uniqueness.
        if max_votes != 1:
            self.dropdown.placeholder = f"Select up to {max_votes} choices"
        self.dropdown.max_values = max_votes
        self.task = asyncio.get_running_loop().create_task(self.destruct())
        self.message: discord.Message
        self.remove_item(self._stop)

    @discord.ui.select(placeholder="Make Your Choice")
    async def dropdown(
        self, interaction: Interaction, sel: discord.ui.Select[PollView]
    ) -> None:
        """A Voting Dropdown - Remove old votes and add new ones."""
        new_votes = ", ".join(sel.values)
        if any(interaction.user.id in i for i in self.votes.values()):
            rep = f"Your vote has been changed to {new_votes}"
        else:
            rep = f"You have voted for {new_votes}"

        votes: dict[str, set[int]] = self.votes

        for vote_list in votes.values():
            vote_list.discard(interaction.user.id)

        for i in sel.values:
            self.votes[i].add(interaction.user.id)
        await self.update(interaction)
        await interaction.followup.send(content=rep, ephemeral=True)

    def read_votes(self, final: bool = False) -> str:
        """Parse the votes and conver it to a string"""
        output = ""

        votes = self.votes
        srt = sorted(votes, key=lambda x: len(self.votes[x]), reverse=True)

        if [v for v in self.votes.values() if v]:
            winning = self.votes[key := srt.pop(0)]
            voters = ", ".join([f"<@{i}>" for i in winning])
            output = f"🥇 **{key}**: {len(winning)} votes\n{voters}\n\n"

            for k in srt:
                if not self.votes[k]:
                    continue

                voters = ", ".join([f"<@{i}>" for i in self.votes[k]])
                item_votes = len(self.votes[k])
                output += f"**{k}**: {item_votes} votes\n"
                output += f"{voters}\n"
        else:
            output = "No Votes cast"

        if not final:
            output += f"\n\nPoll ends: {self.ends_at}"
        return output

    async def destruct(self) -> None:
        """End the poll after the specified amount of minutes."""
        await discord.utils.sleep_until(self.end)

        embed = discord.Embed(colour=discord.Colour.dark_gold())
        embed.title = self.question + "?"
        embed.description = self.read_votes(final=True)

        votes_cast = sum([len(self.votes[i]) for i in self.votes])
        embed.set_footer(text=f"Final Results | {votes_cast} votes")

        if icon := operator.attrgetter("icon.url")(self.message.guild):
            embed.set_thumbnail(url=icon)

        try:
            edit = self.message.edit
            await edit(embed=embed, view=None)
            return
        except discord.HTTPException:
            pass

        try:
            await self.message.channel.send(embed=embed)
        except (discord.NotFound, discord.Forbidden):
            pass

    async def update(self, interaction: Interaction) -> None:
        """Refresh the view and send to user"""
        client = interaction.client
        if self.task not in client.active_polls:
            client.active_polls.add(self.task)
            self.task.add_done_callback(client.active_polls.discard)

        embed = discord.Embed(title=self.question + "?")
        embed.colour = discord.Colour.og_blurple()

        embed.description = self.read_votes()

        total_votes = sum([len(self.votes[i]) for i in self.votes])
        embed.set_footer(text=f"Voting in Progress | {total_votes} votes")

        edit = interaction.response.edit_message
        return await edit(view=self, embed=embed)


class PollModal(discord.ui.Modal, title="Create a poll"):
    """UI Sent to user to ask them to create a poll."""

    minutes: TextInput[PollModal] = TextInput(
        label="Enter Poll Duration in Minutes",
        default="60",
        placeholder="60",
        max_length=4,
    )

    question: TextInput[PollModal] = TextInput(
        label="Question", placeholder="Enter your question here"
    )

    answers: TextInput[PollModal] = TextInput(
        label="Answers (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Red\nBlue\nYellow",
    )

    votes: TextInput[PollModal] = TextInput(
        label="Max votes per user", default="1", placeholder="1", max_length=2
    )

    def __init__(self) -> None:
        super().__init__()

    async def on_submit(  # type: ignore
        self, interaction: Interaction, /
    ) -> None:
        """When the Modal is submitted, pick at random and send back"""
        question = self.question.value
        answers = self.answers.value.split("\n")[:25]

        # Discard null
        answers = [i.strip() for i in answers if i.strip()]

        if len(answers) < 2:
            answers = ["Yes", "No"]

        embed = discord.Embed(colour=discord.Colour.red())

        try:
            votes = int(self.votes.value)
        except ValueError:
            votes = 1

            err = "Invalid number of votes provided, defaulting to 1"
            embed.description = err
            await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            time = int(self.minutes.value)
        except ValueError:
            time = 60
            err = "Invalid number of minutes provided, defaulting to 60"
            embed.description = err
            await interaction.followup.send(embed=embed, ephemeral=True)
        view = PollView(question, answers, time, votes)
        await interaction.response.send_message(view=view, embed=embed)
        view.message = await interaction.original_response()


class Poll(commands.Cog):
    """User Created Polls"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot

    @discord.app_commands.command()
    async def poll(self, interaction: Interaction) -> None:
        """Create a poll with multiple answers.
        Use the UI to set your options."""
        return await interaction.response.send_modal(PollModal())


async def setup(bot: Bot) -> None:
    """Add the Poll cog to the Bot"""
    await bot.add_cog(Poll(bot))
