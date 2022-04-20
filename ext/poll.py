"""User Created Polls"""
from collections import Counter
from typing import List, TYPE_CHECKING, Union

from discord import ButtonStyle, Embed, Colour, TextStyle, Interaction, Message
from discord.app_commands import command
from discord.ext.commands import Cog
from discord.ui import Button, View, Modal, TextInput

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


# TODO: Database table, persistent views
# TODO: Timed Poll
# TODO: End Poll command.


class PollButton(Button):
    """A Voting Button"""

    def __init__(self, emoji: str = None, label: str = None, row: int = 0):
        super().__init__(emoji=emoji, label=label, row=row, style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction) -> Message:
        """Reply to user to let them know their vote has changed."""
        ej = f"{self.emoji} " if self.emoji is not None else ""
        if interaction.user.id in self.view.votes:
            await interaction.response.send_message(f'Your vote has been changed to {ej}{self.label}', ephemeral=True)
        else:
            await interaction.response.send_message(f'You have voted for {ej}{self.label}', ephemeral=True)
        self.view.votes.update({interaction.user.mention: self.label})
        return await self.view.update()


class PollView(View):
    """View for a poll commands"""

    def __init__(self, bot: Union['Bot', 'PBot'], interaction: Interaction, question: str, answers: List[str]):
        self.interaction: Interaction = interaction
        self.question: str = question
        self.votes: dict = {}
        self.bot: Bot | PBot = bot
        super().__init__(timeout=3600)

        buttons = [(None, i) for i in answers if i] if answers else [('👍', 'Yes'), ('👎', 'No')]
        for x, y in enumerate(buttons):
            row = x // 5
            self.add_item(PollButton(emoji=y[0], label=y[1], row=row))

    async def on_timeout(self) -> None:
        """Remove buttons and dropdowns when listening stops."""
        return await self.finalise()

    async def finalise(self) -> None:
        """Finalise the view"""
        e = Embed(colour=Colour.green(), title=self.question + "?", description="")
        e.set_author(name=f"{self.interaction.user.name} asked...", icon_url=self.interaction.user.display_avatar.url)
        counter = Counter(self.votes.values())
        results = sorted(counter)
        if results:
            winning = results.pop(0)
            voters = [i for i in self.votes if self.votes[i] == winning]
            e.description = f"🥇 **{winning}: {counter[winning]} votes**\n{' '.join(voters)}\n"
        else:
            e.description = "No Votes yet."

        for x in results:
            voters = ' '.join([i for i in self.votes if self.votes[i] == x])
            e.description += f"**{x}: {counter[x]} votes**\n{voters}\n"

        votes = f"{len(self.votes)} responses"
        e.set_footer(text=f"Final Results | {votes} votes")
        await self.bot.reply(self.interaction, view=None, embed=e)
        self.stop()

    async def update(self, content: str = "") -> Message:
        """Refresh the view and send to user"""
        e: Embed = Embed(colour=Colour.og_blurple(), title=self.question + "?", description="")
        e.set_author(name=f"{self.interaction.user.name} asks...", icon_url=self.interaction.user.display_avatar.url)

        counter = Counter(self.votes.values())
        results = sorted(counter)
        if results:
            winning = results.pop(0)
            voters = [i for i in self.votes if self.votes[i] == winning]
            e.description = f"🥇 **{winning}: {counter[winning]} votes**\n{' '.join(voters)}\n"
        else:
            e.description = "No Votes yet."

        for x in results:
            voters = ' '.join([i for i in self.votes if self.votes[i] == x])
            e.description += f"**{x}: {counter[x]} votes**\n{voters}\n"

        e.set_footer(text=f"Voting in Progress | {len(self.votes)} votes")
        return await self.bot.reply(self.interaction, content=content, view=self, embed=e)


class PollModal(Modal, title="Create a poll"):
    """UI Sent to user to ask them to create a poll."""
    question = TextInput(label="Enter a question", placeholder="What is your favourite colour?")
    answers = TextInput(label="Answers (one per line)", style=TextStyle.paragraph, placeholder="Red\nBlue\nYellow")

    def __init__(self, bot: Union['Bot', 'PBot']):
        self.bot: Bot | PBot = bot
        super().__init__()

    async def on_submit(self, interaction: Interaction) -> Message:
        """When the Modal is submitted, pick at random and send the reply back"""
        question = self.question.value
        answers = self.answers.value.split('\n')

        if len(answers) > 25:
            return await self.bot.error(interaction, 'Too many answers provided. 25 is more than enough thanks.')
        return await PollView(self.bot, interaction, question=question, answers=answers).update()


class Poll(Cog):
    """User Created Polls"""

    def __init__(self, bot: Union['Bot', 'PBot']) -> None:
        self.bot: Bot | PBot = bot

    @command()
    async def poll(self, interaction: Interaction) -> PollModal:
        """Create a poll with multiple answers. Polls end after 1 hour of no responses."""
        return await interaction.response.send_modal(PollModal(self.bot))


async def setup(bot: Union['Bot', 'PBot']) -> None:
    """Add the Poll cog to the Bot"""
    await bot.add_cog(Poll(bot))
