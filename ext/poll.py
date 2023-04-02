"""User Created Polls"""
from __future__ import annotations

import datetime
import operator
import typing

import discord
from discord.ext import commands

from ext.utils import timed_events, view_utils

if typing.TYPE_CHECKING:
    from core import Bot


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
        emoji = f"{self.emoji} " if self.emoji is not None else ""

        reply = f"Vote set to {emoji}{self.label}"
        await interaction.response.send_message(reply, ephemeral=True)

        votes: dict[str, list] = self.view.votes
        for vote_list in votes.values():
            try:
                vote_list.remove(interaction.user.id)
            except ValueError:
                continue

        self.view.votes[self.label].append(interaction.user.id)
        return await self.view.update()


class PollSelect(discord.ui.Select):
    """A Voting Dropdown"""

    view: PollView

    def __init__(self, options: list[str], votes: int, custom_id: str) -> None:
        if votes == 1:
            placeholder = "Make your choice"
        else:
            placeholder = f"Select up to {votes} choices"

        super().__init__(
            max_values=min(votes, len(options)),
            options=[discord.SelectOption(label=x, value=x) for x in options],
            placeholder=placeholder,
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

        for i in self.view.votes:
            self.view.votes[i].append(interaction.user.id)
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

        self.end = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        self.ends_at = timed_events.Timestamp(self.end).countdown

        super().__init__(interaction)

        # Validate Uniqueness.
        if votes > 1 or len(self.votes) > 5:
            cid = f"{interaction.id}-{question}"
            self.add_item(PollSelect(answers, votes, custom_id=cid))
        else:
            for label in self.votes.keys():
                cid = f"{interaction.id}-{label}"
                self.add_item(PollButton(label=label, custom_id=cid))

        task = interaction.client.loop.create_task(self.destruct())
        interaction.client.active_polls.add(task)
        task.add_done_callback(interaction.client.active_polls.discard)

    def read_votes(self, final=False) -> str:
        """Parse the votes and conver it to a string"""
        output = ""

        votes = self.votes
        srt = sorted(votes, key=lambda x: len(self.votes[x]), reverse=True)

        if [v for v in self.votes.values() if v]:
            winning = self.votes[key := srt.pop(0)]
            voters = ", ".join([f"<@{i}>" for i in winning])
            output = f"🥇 **{key}**: {len(winning)} votes\n{voters}\n\n"

            for k in srt:
                voters = ", ".join([f"<@{i}>" for i in self.votes[k]])
                item_votes = len(self.votes[k])
                output += f"**{k}**: {item_votes} votes\n"
                if item_votes:
                    output += f"{voters}\n"
        else:
            output = "No Votes cast"

        if not final:
            output += f"\n\nPoll ends: {self.ends_at}"
        return output

    async def destruct(self) -> discord.Message | None:
        """End the poll after the specified amount of minutes."""
        await discord.utils.sleep_until(self.end)

        embed = discord.Embed(colour=discord.Colour.dark_gold())
        embed.title = self.question + "?"
        embed.description = self.read_votes(final=True)

        votes_cast = sum([len(self.votes[i]) for i in self.votes])
        embed.set_footer(text=f"Final Results | {votes_cast} votes")

        if icon := operator.attrgetter("icon.url")(self.interaction.guild):
            embed.set_thumbnail(url=icon)

        try:
            return await self.interaction.edit_original_response(embed=embed)
        except discord.HTTPException:
            pass

        chan = typing.cast(discord.TextChannel, self.interaction.channel)
        if chan is not None:
            try:
                return await chan.send(embed=embed)
            except (discord.NotFound, discord.Forbidden):
                pass

    async def update(self) -> discord.InteractionMessage:
        """Refresh the view and send to user"""

        embed = discord.Embed(title=self.question + "?")
        embed.colour = discord.Colour.og_blurple()

        embed.description = self.read_votes()

        user = self.interaction.user
        ico = user.display_avatar.url
        embed.set_author(name=f"{user.name} asked…", icon_url=ico)

        total_votes = sum([len(self.votes[i]) for i in self.votes])
        embed.set_footer(text=f"Voting in Progress | {total_votes} votes")

        edit = self.interaction.edit_original_response
        return await edit(view=self, embed=embed)


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
        await interaction.response.defer(thinking=True)
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

        return await PollView(
            interaction, question, answers, time, votes
        ).update()


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
