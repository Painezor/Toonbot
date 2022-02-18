"""Miscellaneous toys built for my own personal entertainment."""
import collections
import random
import re
from copy import deepcopy

from discord import ButtonStyle, HTTPException, Colour, Embed, Interaction
from discord.commands import Option
from discord.ext import commands
from discord.ui import Button, View

from ext.utils import view_utils

EIGHTBALL_IMAGE = "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/" \
                  "thumbs/120/samsung/265/pool-8-ball_1f3b1.png"
COIN_IMAGE = "https://www.iconpacks.net/icons/1/free-heads-or-tails-icon-456-thumb.png"


# TODO: Upgrade roll command into dice roller box. Buttons for D4, D6, D8, D10, D12, D20, New Line, Clear.
# TODO: Modals pass
# TODO: Grouped Commands pass
# TODO: Slash attachments pass
# TODO: Permissions Pass.


class CoinView(View):
    """A View with a counter for 2 results"""

    def __init__(self, ctx, count: int = 1):
        super().__init__()
        self.ctx = ctx
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
        return self.ctx.author.id == interaction.user.id

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
            self.message = await self.ctx.reply(content=content, view=self, embed=e)
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


class Fun(commands.Cog):
    """Various Toys for you to play with."""

    def __init__(self, bot):
        self.bot = bot

    # Migrate these into FUN group command
    @commands.slash_command(name="8ball")
    async def eight_ball(self, ctx, *, message):
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

        e = Embed(title=message, colour=0x000001, description=random.choice(res))
        e.set_author(icon_url=ctx.author.display_avatar.url, name=f'🎱 8 Ball')
        await ctx.reply(embed=e)

    @commands.slash_command()
    async def lenny(self, ctx):
        """( ͡° ͜ʖ ͡°)"""
        lennys = ['( ͡° ͜ʖ ͡°)', '(ᴗ ͜ʖ ᴗ)', '(⟃ ͜ʖ ⟄) ', '(͠≖ ͜ʖ͠≖)', 'ʕ ͡° ʖ̯ ͡°ʔ', '( ͠° ͟ʖ ͡°)', '( ͡~ ͜ʖ ͡°)',
                  '( ͡◉ ͜ʖ ͡◉)', '( ͡° ͜V ͡°)', '( ͡ᵔ ͜ʖ ͡ᵔ )',
                  '(☭ ͜ʖ ☭)', '( ° ͜ʖ °)', '( ‾ ʖ̫ ‾)', '( ͡° ʖ̯ ͡°)', '( ͡° ل͜ ͡°)', '( ͠° ͟ʖ ͠°)', '( ͡o ͜ʖ ͡o)',
                  '( ͡☉ ͜ʖ ͡☉)', 'ʕ ͡° ͜ʖ ͡°ʔ', '( ͡° ͜ʖ ͡ °)']
        await ctx.reply(content=random.choice(lennys))

    @commands.slash_command()
    async def thatsthejoke(self, ctx):
        """That's the joke"""
        await ctx.reply(content="https://www.youtube.com/watch?v=xECUrlnXCqk")

    @commands.slash_command()
    async def dead(self, ctx):
        """STOP, STOP HE'S ALREADY DEAD"""
        await ctx.reply(content="https://www.youtube.com/watch?v=mAUY1J8KizU")

    @commands.slash_command()
    async def coin(self, ctx, count: int = 1):
        """Flip a coin"""
        if count > 10000:
            return await ctx.reply(content='Too many coins.')

        view = CoinView(ctx, count=count)
        view.add_item(FlipButton())

        for _ in [5, 10, 100, 1000]:
            view.add_item(FlipButton(label=f"Flip {_}", count=_))
        view.add_item(view_utils.StopButton(row=1))
        view.message = await ctx.reply(content="Flipping coin...", view=view)
        await view.update()

    @commands.slash_command()
    async def urban(self, ctx, *, lookup: Option(str, "Search query")):
        """Lookup a definition from urban dictionary"""
        url = f"http://api.urbandictionary.com/v0/define?term={lookup}"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                await ctx.reply(content=f"🚫 HTTP Error, code: {resp.status}", ephemeral=True)
                return
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
            e.description = f"🚫 No results found for {lookup}."
            embeds = [e]

        view = view_utils.Paginator(ctx, embeds=embeds)
        view.message = await ctx.reply(content=f"Fetching definitions for `{lookup}`", view=view)
        await view.update()

    @commands.slash_command(usage="1d6+3")
    async def roll(self, ctx, *, roll_string="d20"):
        """Roll a set of dice in the format XdY+Z. Use 'adv' or 'dis' for (dis)advantage"""
        advantage = True if roll_string.startswith("adv") else False
        disadvantage = True if roll_string.startswith("dis") else False

        e = Embed()
        e.title = "🎲 Dice Roller"
        if advantage:
            e.title += " (Advantage)"
        if disadvantage:
            e.title += " (Disadvantage)"

        e.description = ""

        roll_list = roll_string.split(' ')
        if len(roll_list) == 1:
            roll_list = [roll_string]

        total = 0
        bonus = 0
        for roll in roll_list:
            if not roll:
                continue

            if roll.isdecimal():
                if roll == "1":
                    e.description += f"{roll}: **1**\n"
                    total += 1
                    continue
                result = random.randint(1, int(roll))
                e.description += f"{roll}: **{result}**\n"
                total += int(result)
                continue

            try:
                if "+" in roll:
                    roll, b = roll.split('+')
                    bonus += int(b)
                elif "-" in roll:
                    roll, b = roll.split("-")
                    bonus -= int(b)
            except ValueError:
                bonus = 0

            if roll in ["adv", "dis"]:
                sides = 20
                dice = 1
            else:
                try:
                    dice, sides = roll.split('d')
                    dice = int(dice)
                except ValueError:
                    dice = 1
                    try:
                        sides = int("".join([i for i in roll if i.isdigit()]))
                    except ValueError:
                        sides = 20
                else:
                    sides = int(sides)

                if dice > 1000:
                    return await ctx.reply(content='Too many dice', ephemeral=True)
                if sides > 1000000:
                    return await ctx.reply(content='Too many sides', ephemeral=True)

            e.description += f"{roll}: "
            total_roll = 0
            roll_info = ""
            curr_rolls = []
            for i in range(dice):
                first_roll = random.randrange(1, 1 + sides)
                roll_outcome = first_roll

                if roll in ["adv", "dis"]:
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

        await ctx.reply(embed=e)

    @commands.message_command(name="MoCk")
    async def mock(self, ctx, message):
        """AlTeRnAtInG cApS"""
        content = "".join(c.lower() if i & 1 else c.upper() for i, c in enumerate(message.content))
        await ctx.reply(content=content)

    @commands.slash_command()
    async def choose(self, ctx, choices: Option(str, "Separate, choices, with, commas")):
        """Make a decision for you (separate choices with commas)"""
        e = Embed()
        e.set_author(icon_url=ctx.author.display_avatar.url, name=f'Choose')
        e.colour = ctx.author.colour

        choices = str(choices).split(", ")
        random.shuffle(choices)
        _ = choices.pop(0)
        e.description = f"\n\n🥇 **{_}**\n"
        try:
            _ = choices.pop(0)
            e.description += f"🥈 **{_}**\n"
            _ = choices.pop(0)
            e.description += f"🥉 **{_}**\n"
            e.description += ' ,'.join([f"*{i}*" for i in choices])
        except IndexError:
            pass
        await ctx.reply(embed=e)


def setup(bot):
    """Load the Fun cog into the bot"""
    bot.add_cog(Fun(bot))
