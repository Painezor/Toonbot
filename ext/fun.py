"""Miscellaneous toys built for my own personal entertainment."""
import collections
import random
import re
from copy import deepcopy

from discord import ButtonStyle, HTTPException, Colour, Embed, Interaction, app_commands, TextStyle, Message
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

from ext.utils import view_utils, embed_utils

EIGHTBALL_IMAGE = "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/" \
                  "thumbs/120/samsung/265/pool-8-ball_1f3b1.png"
COIN_IMAGE = "https://www.iconpacks.net/icons/1/free-heads-or-tails-icon-456-thumb.png"


# TODO: Upgrade roll command into dice roller box. Buttons for D4, D6, D8, D10, D12, D20, New Line, Clear.
# TODO: Slash attachments pass
# TODO: Permissions Pass.
# TODO: Macros Command OPTION enum for command.


class CoinView(View):
    """A View with a counter for 2 results"""

    def __init__(self, interaction: Interaction, count: int = 1):
        super().__init__()
        self.interaction = interaction
        self.message = None
        self.results = []
        for x in range(count):
            self.results.append(random.choice(['Heads', 'Tails']))

    async def on_timeout(self):
        """Clear view"""
        self.clear_items()
        try:
            await self.message.edit(view=self)
        except HTTPException:
            return
        finally:
            self.stop()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.interaction.user.id == interaction.user.id

    async def update(self, content=""):
        """Update embed and push to view"""
        e = Embed(title="🪙 Coin Flip", colour=Colour.og_blurple(), description=f"**{self.results[-1]}**\n\n")
        e.set_thumbnail(url=COIN_IMAGE)

        if len(self.results) > 1:
            counter = collections.Counter(self.results)
            for c in counter.most_common():
                e.add_field(name=f"Total {c[0]}", value=c[1])

            e.description += "\n" + f"{'...' if len(self.results) > 200 else ''}"
            e.description += ', '.join([f'*{i}*' for i in self.results[-200:]])

        if self.message is None:
            i = self.interaction
            self.message = await i.client.reply(i, content=content, view=self, embed=e)
        else:
            await self.message.edit(content=content, view=self, embed=e)
        await self.wait()


class FlipButton(Button):
    """Flip a coin and pass the result to the view"""

    def __init__(self, label="Flip a Coin", count=1):
        super().__init__()
        self.label = label
        self.emoji = "🪙"
        self.count = count
        self.style = ButtonStyle.primary

    async def callback(self, interaction):
        """When clicked roll"""
        await interaction.response.defer()
        for x in range(self.count):
            self.view.results.append(random.choice(['Heads', 'Tails']))
        await self.view.update()


class PollModal(Modal, title="Make a Decision"):
    """Send a Modal to the User to enter their options in."""
    question = TextInput(label="Enter a question", placeholder="What should I do?")
    answers = TextInput(label="Answers (one per line)", style=TextStyle.paragraph, placeholder="Sleep\nPlay FIFA")

    async def on_submit(self, interaction: Interaction):
        """When the Modal is submitted, pick at random and send the reply back"""
        e = Embed(colour=interaction.user.colour, title=self.question)
        e.set_author(icon_url=interaction.user.display_avatar.url, name=f'Choose')

        choices = str(self.answers).split("\n")
        random.shuffle(choices)
        e.description = f"\n\n🥇 **{choices.pop(0)}**\n"
        try:
            e.description += f"🥈 **{choices.pop(0)}**\n"
            e.description += f"🥉 **{choices.pop(0)}**\n"
            e.description += ' ,'.join([f"*{i}*" for i in choices])
        except IndexError:
            pass
        await interaction.client.reply(interaction, embed=e)


class Fun(commands.Cog):
    """Various Toys for you to play with."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="8ball")
    @app_commands.describe(question="enter a question")
    async def eight_ball(self, interaction: Interaction, question: str):
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

        e = Embed(title=question, colour=0x000001, description=random.choice(res))
        e.set_author(icon_url=self.bot.user.display_avatar.url, name=f'🎱 8 Ball')
        await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    async def lenny(self, interaction):
        """( ͡° ͜ʖ ͡°)"""
        lennys = ['( ͡° ͜ʖ ͡°)', '(ᴗ ͜ʖ ᴗ)', '(⟃ ͜ʖ ⟄) ', '(͠≖ ͜ʖ͠≖)', 'ʕ ͡° ʖ̯ ͡°ʔ', '( ͠° ͟ʖ ͡°)', '( ͡~ ͜ʖ ͡°)',
                  '( ͡◉ ͜ʖ ͡◉)', '( ͡° ͜V ͡°)', '( ͡ᵔ ͜ʖ ͡ᵔ )',
                  '(☭ ͜ʖ ☭)', '( ° ͜ʖ °)', '( ‾ ʖ̫ ‾)', '( ͡° ʖ̯ ͡°)', '( ͡° ل͜ ͡°)', '( ͠° ͟ʖ ͠°)', '( ͡o ͜ʖ ͡o)',
                  '( ͡☉ ͜ʖ ͡☉)', 'ʕ ͡° ͜ʖ ͡°ʔ', '( ͡° ͜ʖ ͡ °)']
        await self.bot.reply(interaction, content=random.choice(lennys))

    @app_commands.command()
    async def thatsthejoke(self, interaction):
        """That's the joke"""
        await self.bot.reply(interaction, content="https://www.youtube.com/watch?v=xECUrlnXCqk")

    @app_commands.command()
    async def helmet(self, interaction: Interaction):
        """Helmet"""
        await self.bot.reply(interaction, file=embed_utils.make_file(image="Images/helmet.jpg"))

    @app_commands.command()
    async def dead(self, interaction):
        """STOP, STOP HE'S ALREADY DEAD"""
        await self.bot.reply(interaction, content="https://www.youtube.com/watch?v=mAUY1J8KizU")

    @app_commands.command()
    async def coin(self, interaction: Interaction, count: int = 1):
        """Flip a coin"""
        if count > 10000:
            return await self.bot.reply(interaction, content='Too many coins.')

        view = CoinView(interaction, count=count)
        view.add_item(FlipButton())

        for _ in [5, 10, 100, 1000]:
            view.add_item(FlipButton(label=f"Flip {_}", count=_))
        view.add_item(view_utils.StopButton(row=1))
        await view.update()

    @app_commands.command()
    @app_commands.describe(query="enter a search term")
    async def urban(self, interaction: Interaction, *, query: str):
        """Lookup a definition from urban dictionary"""
        url = f"http://api.urbandictionary.com/v0/define?term={query}"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                return await interaction.client.error(interaction, f"🚫 HTTP Error, code: {resp.status}")
            resp = await resp.json()

        tn = "http://d2gatte9o95jao.cloudfront.net/assets/apple-touch-icon-2f29e978facd8324960a335075aa9aa3.png"

        embeds = []

        resp = resp["list"]
        # Populate Embed, add to list
        e = Embed(color=0xFE3511)
        e.set_author(name=f"Urban Dictionary")
        e.set_thumbnail(url=tn)

        if resp:
            for i in resp:
                embed = deepcopy(e)
                embed.title = i["word"]
                embed.url = i["permalink"]
                de = rde = i["definition"]
                for z in re.finditer(r'\[(.*?)]', de):
                    z1 = z.group(1).replace(' ', "%20")
                    z = z.group()
                    de = de.replace(z, f"{z}(https://www.urbandictionary.com/define.php?term={z1})")

                de = de[:2044] + "..." if len(rde) > 2048 else rde

                if i["example"]:
                    ex = rex = i['example']
                    for z in re.finditer(r'\[(.*?)]', ex):
                        z1 = z.group(1).replace(' ', "%20")
                        z = z.group()
                        rex = ex.replace(z, f"{z}(https://www.urbandictionary.com/define.php?term={z1})")

                    ex = ex[:1020] + "..." if len(rex) > 1024 else rex

                    embed.add_field(name="Example", value=ex)

                embed.description = de

                embeds.append(embed)
        else:
            e.description = f"🚫 No results found for {query}."
            embeds = [e]

        view = view_utils.Paginator(interaction, embeds=embeds)
        await view.update()

    @app_commands.command()
    @app_commands.describe(dice="enter a roll (format: 1d20+3)")
    async def roll(self, interaction: Interaction, dice: str = "d20"):
        """Roll a set of dice in the format XdY+Z. Use 'adv' or 'dis' for (dis)advantage"""
        advantage = True if dice.startswith("adv") else False
        disadvantage = True if dice.startswith("dis") else False

        e = Embed(title="🎲 Dice Roller")
        if advantage:
            e.title += " (Advantage)"
        if disadvantage:
            e.title += " (Disadvantage)"

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
                result = random.randint(1, int(r))
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
                    return await interaction.client.error(interaction, 'Too many dice')
                if sides > 1000000:
                    return await interaction.client.error(interaction, 'Too many sides')

            e.description += f"{r}: "
            total_roll = 0
            roll_info = ""
            curr_rolls = []
            for i in range(dice):
                first_roll = random.randrange(1, 1 + sides)
                roll_outcome = first_roll

                if dice in ["adv", "dis"]:
                    second_roll = random.randrange(1, 1 + sides)
                    if (advantage and second_roll > first_roll) or (disadvantage and second_roll < first_roll):
                        roll_outcome = second_roll
                        roll_info += f"({first_roll}, __{second_roll}__)"
                    else:
                        roll_info += f"(__{first_roll}__, {second_roll})"
                else:
                    curr_rolls.append(str(roll_outcome))

                total_roll += roll_outcome

                if dice == 1 and sides >= 20:
                    if roll_outcome == 1:
                        e.colour = Colour.red()
                        e.set_footer(text="Critical Failure")
                    elif roll_outcome == sides:
                        e.colour = Colour.green()
                        e.set_footer(text="Critical.")

            roll_info += ", ".join(curr_rolls)

            if bonus:
                roll_info += f" + {str(bonus)}" if bonus > 0 else f" {str(bonus).replace('-', ' - ')}"
            total_roll += bonus
            e.description += f"{roll_info} = **{total_roll}**" + "\n"

            total += total_roll

        if len(roll_list) > 1:
            e.description += f"\n**Total: {total}**"

        await interaction.client.reply(interaction, embed=e)

    @app_commands.context_menu(name="MoCk")
    async def mock(self, interaction: Interaction, message: Message):
        """AlTeRnAtInG cApS"""
        content = ''.join(c.lower() if i & 1 else c.upper() for i, c in enumerate(message.content))
        await interaction.client.reply(interaction, content=content)

    @app_commands.command()
    async def choose(self, interaction: Interaction):
        """Make a decision for you (separate choices with new lines)"""
        await interaction.response.send_modal(PollModal)

    @app_commands.command(name="f")
    async def press_f(self, interaction):
        """Press F to pay respects"""
        await self.bot.reply(interaction, content="https://i.imgur.com/zrNE05c.gif")


def setup(bot):
    """Load the Fun cog into the bot"""
    bot.add_cog(Fun(bot))
