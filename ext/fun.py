"""Miscellaneous toys built for my own personal entertainment."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from random import choice, randint, randrange, shuffle
from re import finditer
from typing import TYPE_CHECKING

from discord import ButtonStyle, Colour, Embed, Interaction, TextStyle, Message, File
from discord.app_commands import command, context_menu, describe
from discord.ext.commands import Cog
from discord.ui import Button, View, Modal, TextInput

from ext.utils.view_utils import Stop, Paginator

if TYPE_CHECKING:
    from core import Bot

EIGHTBALL_IMAGE = "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/" \
                  "thumbs/120/samsung/265/pool-8-ball_1f3b1.png"
COIN_IMAGE = "https://www.iconpacks.net/icons/1/free-heads-or-tails-icon-456-thumb.png"


# TODO: Upgrade roll command into dice roller box. Buttons for D4, D6, D8, D10, D12, D20, New Line, Clear.
# Add Timestamp of the last roll.

# Send modal for custom roll
# TODO: Slash attachments pass
# TODO: Macros Command OPTION enum for command.


class CoinView(View):
    """A View with a counter for 2 results"""

    def __init__(self, interaction: Interaction, count: int = 1) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.flip_results: list[str] = []
        self.bot: Bot = interaction.client
        for x in range(count):
            self.flip_results.append(choice(['Heads', 'Tails']))

    async def on_timeout(self) -> Message:
        """Clear view"""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.interaction.user.id == interaction.user.id

    async def update(self, content: str = None) -> Message:
        """Update embed and push to view"""
        e: Embed = Embed(colour=Colour.og_blurple(), title=self.flip_results[-1])
        e.set_thumbnail(url=COIN_IMAGE)
        e.set_author(name="🪙 Coin Flip")

        if len(self.flip_results) > 1:
            counter = Counter(self.flip_results)
            for c in counter.most_common():
                e.add_field(name=f"Total {c[0]}", value=c[1])

            res = [f'*{i}*' for i in self.flip_results[-200:]]
            if len(self.flip_results) > 200:
                res.append("\n…")
            e.description = ', '.join(res)
        return await self.bot.reply(self.interaction, content=content, view=self, embed=e)


class FlipButton(Button):
    """Flip a coin and pass the result to the view"""

    def __init__(self, label="Flip a Coin", count=1) -> None:
        super().__init__(label=label, emoji="🪙", style=ButtonStyle.primary)
        self.count: int = count

    async def callback(self, interaction: Interaction) -> View:
        """When clicked roll"""
        await interaction.response.defer()
        for x in range(self.count):
            self.view.flip_results.append(choice(['Heads', 'Tails']))
        return await self.view.update()


class ChoiceModal(Modal):
    """Send a Modal to the User to enter their options in."""
    question = TextInput(label="Enter a question", placeholder="What should I do?")
    answers = TextInput(label="Answers (one per line)", style=TextStyle.paragraph, placeholder="Sleep\nPlay FIFA")

    def __init__(self) -> None:
        super().__init__(title="Make a Decision")

    async def on_submit(self, interaction: Interaction) -> Message:
        """When the Modal is submitted, pick at random and send the reply back"""
        e: Embed = Embed(colour=interaction.user.colour, title=self.question)
        e.set_author(icon_url=interaction.user.display_avatar.url, name=f'Choose')

        choices = str(self.answers).split("\n")
        shuffle(choices)

        output, medals = [], ['🥇', '🥈', '🥉']
        for x in range(min(len(choices), 3)):
            output.append(f"{medals.pop()} **{choices.pop()}**")

        if choices:
            output.append(', '.join(f"*{i}*" for i in choices))

        e.description = '\n'.join(output)
        bot: Bot = interaction.client
        return await bot.reply(interaction, embed=e)


# Context Menu commands must be free floating.
@context_menu(name="MoCk")
async def mock(interaction: Interaction, message: Message) -> Message:
    """AlTeRnAtInG cApS"""
    bot: Bot = interaction.client
    if not message.content:
        return await bot.error(interaction, content="That message has no content.")

    content = ''.join(c.lower() if i & 1 else c.upper() for i, c in enumerate(message.content))
    return await bot.reply(interaction, content=content)


class Fun(Cog):
    """Various Toys for you to play with."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.bot.tree.add_command(mock)  # Must be free floating.

    @command(name="8ball")
    @describe(question="enter a question")
    async def eight_ball(self, interaction: Interaction, question: str) -> Message:
        """Magic Geordie 8ball"""
        res = ["probably", "Aye", "aye mate", "wey aye.", "aye trust is pal.",
               "Deffo m8", "fuckin aye.", "fucking rights", "think so", "absofuckinlutely",
               # Negative
               "me pal says nar.", "divn't think so", "probs not like.", "nar pal soz", "fuck no",
               "deffo not.", "nar", "wey nar", "fuck off ya daftie", "absofuckinlutely not",
               # later
               "am not sure av just had a bucket", "al tel you later", "giz a minute to figure it out",
               "mebbe like", "dain't bet on it like"
               ]

        if len(question) > 256:
            question = f"{question[:255]}…"

        e: Embed = Embed(title=question, colour=0x000001, description=choice(res))
        e.set_author(icon_url=self.bot.user.display_avatar.url, name=f'🎱 8 Ball')
        return await self.bot.reply(interaction, embed=e)

    @command()
    async def lenny(self, interaction: Interaction) -> Message:
        """( ͡° ͜ʖ ͡°)"""
        lennys = ['( ͡° ͜ʖ ͡°)', '(ᴗ ͜ʖ ᴗ)', '(⟃ ͜ʖ ⟄) ', '(͠≖ ͜ʖ͠≖)', 'ʕ ͡° ʖ̯ ͡°ʔ', '( ͠° ͟ʖ ͡°)', '( ͡~ ͜ʖ ͡°)',
                  '( ͡◉ ͜ʖ ͡◉)', '( ͡° ͜V ͡°)', '( ͡ᵔ ͜ʖ ͡ᵔ )',
                  '(☭ ͜ʖ ☭)', '( ° ͜ʖ °)', '( ‾ ʖ̫ ‾)', '( ͡° ʖ̯ ͡°)', '( ͡° ل͜ ͡°)', '( ͠° ͟ʖ ͠°)', '( ͡o ͜ʖ ͡o)',
                  '( ͡☉ ͜ʖ ͡☉)', 'ʕ ͡° ͜ʖ ͡°ʔ', '( ͡° ͜ʖ ͡ °)']
        return await self.bot.reply(interaction, content=choice(lennys))

    @command()
    async def thatsthejoke(self, interaction: Interaction) -> Message:
        """That's the joke"""
        return await self.bot.reply(interaction, content="https://www.youtube.com/watch?v=xECUrlnXCqk")

    @command()
    async def helmet(self, interaction: Interaction) -> Message:
        """Helmet"""
        return await self.bot.reply(interaction, file=File(fp="Images/helmet.jpg"))

    @command()
    async def dead(self, interaction: Interaction) -> Message:
        """STOP, STOP HE'S ALREADY DEAD"""
        return await self.bot.reply(interaction, content="https://www.youtube.com/watch?v=mAUY1J8KizU")

    @command()
    @describe(count="Enter a number of coins")
    async def coin(self, interaction: Interaction, count: int = 1) -> Message:
        """Flip a coin"""
        if count > 10000:
            return await self.bot.error(interaction, content='Too many coins.')

        v = CoinView(interaction, count=count)
        v.add_item(FlipButton())

        for _ in [5, 10, 100, 1000]:
            v.add_item(FlipButton(label=f"Flip {_}", count=_))
        v.add_item(Stop(row=1))
        return await v.update()

    @command()
    @describe(query="enter a search term")
    async def urban(self, interaction: Interaction, query: str) -> Message:
        """Lookup a definition from urban dictionary"""
        url = f"http://api.urbandictionary.com/v0/define?term={query}"
        async with self.bot.session.get(url) as resp:
            match resp.status:
                case 200:
                    resp = await resp.json()
                case _:
                    return await self.bot.error(interaction, f"🚫 HTTP Error, code: {resp.status}")
        tn = "http://d2gatte9o95jao.cloudfront.net/assets/apple-touch-icon-2f29e978facd8324960a335075aa9aa3.png"

        # Populate Embed, add to list
        e: Embed = Embed(color=0xFE3511).set_author(name=f"Urban Dictionary").set_thumbnail(url=tn)

        embeds = []
        for i in resp["list"]:
            embed = deepcopy(e)
            embed.title = i["word"]
            embed.url = i["permalink"]
            de = rde = i["definition"]
            for z in finditer(r'\[(.*?)]', de):
                z1 = z.group(1).replace(' ', "%20")
                z = z.group()
                de = de.replace(z, f"{z}(https://www.urbandictionary.com/define.php?term={z1})")

            de = f"{de[:2046]} …" if len(rde) > 2048 else rde

            if i["example"]:
                ex = rex = i['example']
                for z in finditer(r'\[(.*?)]', ex):
                    z1 = z.group(1).replace(' ', "%20")
                    z = z.group()
                    rex = ex.replace(z, f"{z}(https://www.urbandictionary.com/define.php?term={z1})")

                ex = f"{ex[:1023]}…" if len(rex) > 1024 else rex

                embed.add_field(name="Example", value=ex)

            embed.description = de
            embeds.append(embed)

        if not embeds:
            e.description = f"🚫 No flip_results found for {query}."
            embeds = [e]

        return await Paginator(interaction, embeds=embeds).update()

    @command()
    @describe(dice="enter a roll (format: 1d20+3)")
    async def roll(self, interaction: Interaction, dice: str = "d20") -> Message:
        """Roll a set of dice in the format XdY+Z. Use 'adv' or 'dis' for (dis)advantage"""
        await interaction.response.defer(thinking=True)

        advantage = dice.startswith("adv")
        disadvantage = dice.startswith("dis")

        if advantage:
            e: Embed = Embed(title="🎲 Dice Roller (Advantage)")
        elif disadvantage:
            e: Embed = Embed(title="🎲 Dice Roller (Disadvantage)")
        else:
            e: Embed = Embed(title="🎲 Dice Roller")

        e.description = ""

        roll_list = dice.split(' ')
        if len(roll_list) == 1:
            roll_list = [dice]

        total = 0
        bonus = 0
        for r in roll_list:
            if not r:
                continue

            if r.isdecimal():
                if r == "1":
                    e.description += f"{r}: **1**\n"
                    total += 1
                    continue
                result = randint(1, int(r))
                e.description += f"{r}: **{result}**\n"
                total += int(result)
                continue

            try:
                if "+" in r:
                    r, b = r.split('+')
                    bonus += int(b)
                elif "-" in r:
                    r, b = r.split("-")
                    bonus -= int(b)
            except ValueError:
                bonus = 0

            if r in ["adv", "dis"]:
                sides = 20
                dice = 1
            else:
                try:
                    dice, sides = r.split('d')
                    dice = int(dice)
                except ValueError:
                    dice = 1
                    try:
                        sides = int(''.join([i for i in r if i.isdigit()]))
                    except ValueError:
                        sides = 20
                else:
                    sides = int(sides)

                if dice > 1000:
                    return await self.bot.error(interaction, content='Too many dice')
                if sides > 1000000:
                    return await self.bot.error(interaction, content='Too many sides')
                if sides < 1:
                    return await self.bot.error(interaction, content='Not enough sides')

            e.description += f"{r}: "
            total_roll = 0
            roll_info = ""
            curr_rolls = []
            for i in range(dice):
                first_roll = randrange(1, 1 + sides)
                roll_outcome = first_roll

                if dice in ["adv", "dis"]:
                    second_roll = randrange(1, 1 + sides)
                    if (advantage and second_roll > first_roll) or (disadvantage and second_roll < first_roll):
                        roll_outcome = second_roll
                        roll_info += f"({first_roll}, __{second_roll}__)"
                    else:
                        roll_info += f"(__{first_roll}__, {second_roll})"
                else:
                    curr_rolls.append(str(roll_outcome))

                total_roll += roll_outcome

                if dice == 1 and sides >= 20:
                    match roll_outcome:
                        case 1:
                            e.colour = Colour.red()
                            e.set_footer(text="Critical Failure")
                        case sides:
                            e.colour = Colour.green()
                            e.set_footer(text="Critical.")

            roll_info += ", ".join(curr_rolls)

            if bonus:
                roll_info += f" + {bonus}" if bonus > 0 else f" {str(bonus).replace('-', ' - ')}"
            total_roll += bonus
            e.description += f"{roll_info} = **{total_roll}**\n"

            total += total_roll

        if len(roll_list) > 1:
            e.description += f"\n**Total: {total}**"

        return await self.bot.reply(interaction, embed=e)

    @command()
    async def choose(self, interaction: Interaction) -> ChoiceModal:
        """Make a decision for you (separate choices with new lines)"""
        return await interaction.response.send_modal(ChoiceModal())

    @command(name="f")
    async def press_f(self, interaction) -> Message:
        """Press F to pay respects"""
        return await self.bot.reply(interaction, content="https://i.imgur.com/zrNE05c.gif")


async def setup(bot: Bot) -> None:
    """Load the Fun cog into the bot"""
    return await bot.add_cog(Fun(bot))
