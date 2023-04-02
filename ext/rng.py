"""Random Number Generation Commands"""
from __future__ import annotations

import collections
import random
import typing

import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
    from core import Bot

COIN = (
    "https://www.iconpacks.net/icons/1/"
    "free-heads-or-tails-icon-456-thumb.png"
)


# TODO: Upgrade roll command into dice roller box.
# Buttons for D4, D6, D8, D10, D12, D20, New Line, Clear.
# Add Timestamp of the last roll.
# Send modal for custom roll


class DiceBox(view_utils.BaseView):
    """A View with buttons for various dice"""

    def __init__(self, interaction: discord.Interaction[Bot]) -> None:
        super().__init__(interaction)
        self.rolls: list[list[int]] = []

    async def update(self) -> discord.InteractionMessage:
        """Update embed and push to view"""
        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.set_author(name="Dice Tray")

        embed.description = ""

        self.clear_items()
        self.add_item(DiceButton(4))
        self.add_item(DiceButton())
        self.add_item(DiceButton(8))
        self.add_item(DiceButton(10))
        self.add_item(DiceButton(12))
        self.add_item(DiceButton(20, row=1))

        for row in self.rolls:
            embed.description += (
                f"{', '.join(str(i) for i in row)} (Sum: {sum(row)})\n"
            )

        edit = self.interaction.edit_original_response
        return await edit(view=self, embed=embed)


class DiceButton(discord.ui.Button):
    """A Generic Button for a die"""

    view: DiceBox

    def __init__(self, sides: int = 6, row: int = 0):
        style = discord.ButtonStyle.blurple
        super().__init__(label=f"Roll D{sides}", row=row, style=style)
        self.sides: int = sides

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When clicked roll"""

        await interaction.response.defer()
        roll = random.randrange(1, self.sides + 1)

        if not self.view.rolls:
            self.view.rolls = [[roll]]
        else:
            self.view.rolls[-1].append(roll)

        return await self.view.update()


class CoinView(view_utils.BaseView):
    """A View with a counter for 2 results"""

    def __init__(
        self, interaction: discord.Interaction[Bot], count: int = 1
    ) -> None:
        super().__init__(interaction)
        self.flip_results = [random.choice(["H", "T"]) for _ in range(count)]

    async def update(
        self, content: typing.Optional[str] = None
    ) -> discord.InteractionMessage:
        """Update embed and push to view"""
        embed = discord.Embed(title=self.flip_results[-1])
        embed.colour = discord.Colour.og_blurple()
        embed.set_thumbnail(url=COIN)
        embed.set_author(name="Coin Flip")

        counter = collections.Counter(self.flip_results)
        embed.description = f"*{self.flip_results[-50:]}*"
        for item in counter.most_common():
            embed.description += f"\n**Total {item[0]}**: {item[1]}"

        edit = self.interaction.edit_original_response
        return await edit(content=content, view=self, embed=embed)


class FlipButton(discord.ui.Button):
    """Flip a coin and pass the result to the view"""

    view: CoinView

    def __init__(self, label: str = "Flip a Coin", count: int = 1) -> None:

        style = discord.ButtonStyle.primary
        super().__init__(label=label, emoji="🪙", style=style)
        self.count: int = count

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """When clicked roll"""

        await interaction.response.defer()
        results = [random.choice(["H", "T"]) for _ in range(self.count)]
        self.view.flip_results = results
        return await self.view.update()


class ChoiceModal(discord.ui.Modal):
    """Send a Modal to the User to enter their options in."""

    question = discord.ui.TextInput(
        label="Enter a question", placeholder="What should I do?"
    )

    answers = discord.ui.TextInput(
        label="Answers (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Sleep\nPlay FIFA",
    )

    def __init__(self) -> None:
        super().__init__(title="Make a Decision")

    async def on_submit(self, interaction: discord.Interaction[Bot]) -> None:
        """When the Modal is submitted, send a random choice back"""

        user = interaction.user

        embed = discord.Embed(colour=user.colour, title=self.question)
        embed.set_author(icon_url=user.display_avatar.url, name="Choose")

        choices = str(self.answers).split("\n")
        random.shuffle(choices)

        output, medals = [], ["🥇", "🥈", "🥉"]
        for _ in range(min(len(choices), 3)):
            output.append(f"{medals.pop()} **{choices.pop()}**")

        if choices:
            output.append(", ".join(f"*{i}*" for i in choices))

        embed.description = "\n".join(output)
        return await interaction.response.send_message(embed=embed)


class Random(commands.Cog):
    """Random Number Generation Cog"""

    def __init__(self, bot: Bot):
        self.bot = bot

    @discord.app_commands.command()
    async def choose(self, interaction: discord.Interaction[Bot]) -> None:
        """Make a decision for you (separate choices with new lines)"""
        return await interaction.response.send_modal(ChoiceModal())

    @discord.app_commands.command()
    @discord.app_commands.describe(count="Enter a number of coins")
    async def coin(
        self, interaction: discord.Interaction[Bot], count: int = 1
    ) -> discord.InteractionMessage:
        """Flip a coin"""
        if count > 10000:
            return await self.bot.error(interaction, content="Too many coins.")

        view = CoinView(interaction, count=count)
        view.add_item(FlipButton())

        for _ in [5, 10, 100, 1000]:
            view.add_item(FlipButton(label=f"Flip {_}", count=_))
        view.add_page_buttons(1)
        return await view.update()

    @discord.app_commands.command(name="8ball")
    @discord.app_commands.describe(question="enter a question")
    async def eight_ball(
        self, interaction: discord.Interaction[Bot], question: str
    ) -> None:
        """Magic Geordie 8ball"""
        res = [
            "probably",
            "Aye",
            "aye mate",
            "wey aye.",
            "aye trust is pal.",
            "Deffo m8",
            "fuckin aye.",
            "fucking rights",
            "think so",
            "absofuckinlutely",
            # Negative
            "me pal says nar.",
            "divn't think so",
            "probs not like.",
            "nar pal soz",
            "fuck no",
            "deffo not.",
            "nar",
            "wey nar",
            "fuck off ya daftie",
            "absofuckinlutely not",
            # later
            "am not sure av just had a bucket",
            "al tel you later",
            "giz a minute to figure it out",
            "mebbe like",
            "dain't bet on it like",
        ]

        embed = discord.Embed(title="8 Ball", colour=0x000001)
        embed.description = f"**{question}**\n{random.choice(res)}"

        usr = interaction.user
        embed.set_author(icon_url=usr.display_avatar.url, name=usr)
        return await interaction.response.send_message(embed=embed)

    @discord.app_commands.command()
    @discord.app_commands.describe(dice="enter a roll (format: 1d20+3)")
    async def roll(
        self, interaction: discord.Interaction[Bot], dice: str = "d20"
    ) -> discord.InteractionMessage:
        """Roll a set of dice in the format XdY+Z.
        Use 'adv' or 'dis' for (dis)advantage"""

        await interaction.response.defer(thinking=True)

        advantage = dice.startswith("adv")
        disadvantage = dice.startswith("dis")

        if advantage:
            embed = discord.Embed(title="🎲 Dice Roller (Advantage)")
        elif disadvantage:
            embed = discord.Embed(title="🎲 Dice Roller (Disadvantage)")
        else:
            embed = discord.Embed(title="🎲 Dice Roller")

        embed.description = ""

        roll_list = dice.split(" ")
        if len(roll_list) == 1:
            roll_list = [dice]

        total = 0
        bonus = 0
        for i in roll_list:
            if not i:
                continue

            if i.isdecimal():
                if i == "1":
                    embed.description += f"{i}: **1**\n"
                    total += 1
                    continue
                result = random.randint(1, int(i))
                embed.description += f"{i}: **{result}**\n"
                total += int(result)
                continue

            try:
                if "+" in i:
                    i, boni = i.split("+")
                    bonus += int(boni)
                elif "-" in i:
                    i, boni = i.split("-")
                    bonus -= int(boni)
            except ValueError:
                bonus = 0

            if i in ["adv", "dis"]:
                sides = 20
                die = 1
            else:
                try:
                    die, sides = i.split("d")
                    die = int(dice)
                except ValueError:
                    die = 1
                    try:
                        sides = int("".join([i for i in i if i.isdigit()]))
                    except ValueError:
                        sides = 20
                else:
                    sides = int(sides)

                if die > 1000:
                    return await self.bot.error(interaction, "Too many dice")
                if sides > 1000000:
                    return await self.bot.error(interaction, "Too many sides")
                if sides < 2:
                    err = "Not enough sides"
                    return await self.bot.error(interaction, err)

            embed.description += f"{i}: "
            total_roll = 0
            roll_info = ""
            curr_rolls = []
            for i in range(die):
                first_roll = random.randrange(1, 1 + sides)
                roll_outcome = first_roll

                if dice in ["adv", "dis"]:
                    second_roll = random.randrange(1, 1 + sides)

                    bool_a = advantage and second_roll > first_roll
                    bool_b = disadvantage and second_roll < first_roll

                    if bool_a or bool_b:
                        roll_outcome = second_roll
                        roll_info += f"({first_roll}, __{second_roll}__)"
                    else:
                        roll_info += f"(__{first_roll}__, {second_roll})"
                else:
                    curr_rolls.append(str(roll_outcome))

                total_roll += roll_outcome

                if dice == 1 and sides >= 20:
                    if roll_outcome == 1:
                        embed.colour = discord.Colour.red()
                        embed.set_footer(text="Critical Failure")
                    elif roll_outcome == sides:
                        embed.colour = discord.Colour.green()
                        embed.set_footer(text="Critical.")

            roll_info += ", ".join(curr_rolls)

            if bonus:
                if bonus > 0:
                    roll_info += f" + {bonus}"
                else:
                    roll_info += f" {str(bonus).replace('-', ' - ')}"

            total_roll += bonus

            embed.description += f"{roll_info} = **{total_roll}**\n"

            total += total_roll

        embed.description += f"\n**Total: {total}**"
        return await interaction.edit_original_response(embed=embed)


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(Random(bot))
