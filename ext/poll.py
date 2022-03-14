"""User Created Polls"""
from collections import Counter
from typing import List, TYPE_CHECKING

from discord import ButtonStyle, Embed, Colour, app_commands, TextStyle, Interaction, Message
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

if TYPE_CHECKING:
    from core import Bot

# TODO: Timers, /end poll command, database entry, persistent view.


class PollButton(Button):
    """A Voting Button"""

    def __init__(self, emoji=None, label=None, row=0):
        super().__init__(emoji=emoji, label=label, row=row, style=ButtonStyle.primary)

    async def callback(self, interaction):
        """Reply to user to let them know their vote has changed."""
        ej = f"{self.emoji} " if self.emoji is not None else ""
        if interaction.user.id in self.view.answers:
            await interaction.response.send_message(f'Your vote has been changed to {ej}{self.label}', ephemeral=True)
        else:
            await interaction.response.send_message(f'You have voted for {ej}{self.label}', ephemeral=True)
        self.view.answers.update({interaction.user.mention: self.label})
        await self.view.update()


class PollView(View):
    """View for a poll commands"""

    def __init__(self, interaction: Interaction, question: str, answers: List[str]):
        self.interaction: Interaction = interaction
        self.answers = {}
        self.question = question
        super().__init__(timeout=3600)

        buttons = [(None, i) for i in answers if i] if answers else [('👍', 'Yes'), ('👎', 'No')]
        for x, y in enumerate(buttons):
            row = x // 5
            self.add_item(PollButton(emoji=y[0], label=y[1], row=row))

    async def on_timeout(self) -> None:
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        await self.update(final=True)
        self.stop()

    async def update(self, content: str = "", final: bool = False) -> Message:
        """Refresh the view and send to user"""
        e = Embed(colour=Colour.og_blurple() if not final else Colour.green())
        e.set_author(name=f"{self.interaction.user.name} asks...", icon_url=self.interaction.user.display_avatar.url)

        e.title = self.question + "?"

        e.description = ""
        counter = Counter(self.answers.values())
        results = sorted(counter)
        if results:
            winning = results.pop(0)
            voters = [i for i in self.answers if self.answers[i] == winning]
            e.description = f"🥇 **{winning}: {counter[winning]} votes**\n{' '.join(voters)}\n"
        else:
            e.description = "No Votes yet."

        for x in results:
            voters = ' '.join([i for i in self.answers if self.answers[i] == x])
            e.description += f"**{x}: {counter[x]} votes**\n{voters}\n"

        votes = f"{len(self.answers)} responses"
        state = "Voting in Progress" if not final else "Final Results"
        e.set_footer(text=f"{state} | {votes}")
        return await self.interaction.client.reply(self.interaction, content=content, view=self, embed=e)


class PollModal(Modal, title="Create a poll"):
    """UI Sent to user to ask them to create a poll."""
    question = TextInput(label="Enter a question", placeholder="What is your favourite colour?")
    answers = TextInput(label="Answers (one per line)", style=TextStyle.paragraph, placeholder="Red\nBlue\nYellow")

    async def on_submit(self, interaction: Interaction) -> Message:
        """When the Modal is submitted, pick at random and send the reply back"""
        question = self.question.value
        answers = self.answers.value.split('\n')

        if len(answers) > 25:
            i = interaction
            return await i.client.error(i, 'Too many answers provided. 25 is more than enough thanks.')
        return await PollView(interaction, question=question, answers=answers).update()


class Poll(commands.Cog):
    """User Created Polls"""

    def __init__(self, bot: 'Bot') -> None:
        self.bot: Bot = bot

    @app_commands.command()
    async def poll(self, interaction: Interaction) -> PollModal:
        """Create a poll with multiple answers. Polls end after 1 hour of no responses."""
        return await interaction.response.send_modal(PollModal())


async def setup(bot: 'Bot') -> None:
    """Add the Poll cog to the Bot"""
    await bot.add_cog(Poll(bot))
