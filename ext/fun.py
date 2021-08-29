"""Miscellaneous toys built for my own personal entertainment."""
import collections
import datetime
import random
import re
from copy import deepcopy
from importlib import reload

import discord
from discord.ext import commands

from ext.utils import embed_utils, view_utils

EIGHTBALL_IMAGE = "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/" \
                  "thumbs/120/samsung/265/pool-8-ball_1f3b1.png"
COIN_IMAGE = "https://www.iconpacks.net/icons/1/free-heads-or-tails-icon-456-thumb.png"


class HoroscopeView(discord.ui.View):
    """A view with a single select option that pages between different horoscopes"""

    def __init__(self, author):
        self.author = author
        super().__init__()
        self.message = None
        self.embed = discord.Embed(colour=0x7289DA)
        self.embed.description = '*"The stars and planets will not affect your life in any way, and they never will."*'
        sun = datetime.datetime.today() - datetime.timedelta((datetime.datetime.today().weekday() + 1) % 7)
        sat = sun + datetime.timedelta(days=6)
        self.embed.set_footer(text=f"Horoscope for week {sun.strftime('%a %d %B %Y')} - {sat.strftime('%a %d %B %Y')}")

    async def on_timeout(self):
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        await self.message.edit(view=self)
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.author.id == interaction.user.id

    async def update(self):
        """Refresh the view and send to user"""
        await self.message.edit(view=self, embed=self.embed, allowed_mentions=discord.AllowedMentions.none())
        await self.wait()


class HoroscopeSelect(discord.ui.Select):
    """The Dropdown for the Horoscope View"""

    def __init__(self):
        h = [("Aquarius", "♒", "January 20 – February 18"),
             ("Aries", "♈", "March 21 – April 19"),
             ("Cancer", "♋", "June 21 – July 22"),
             ("Capricorn", "♑", "December 22 – January 19"),
             ("Gemini", "♊", "May 21 – June 20"),
             ("Leo", "♌", "July 23 – August 22"),
             ("Libra", "♎", "September 23 – October 22"),
             ("Scorpio", "♏", "October 23 – November 21"),
             ("Sagittarius", "♐", "November 22 – December 21"),
             ("Pisces", "♓", "February 19 – March 20"),
             ("Taurus", "♉", "April 20 – May 20"),
             ("Virgo", "♍", "August 23 – September 22")]

        self.items = h

        super().__init__()
        for value, (sign, symbol, date) in enumerate(h):
            self.add_option(label=sign, emoji=symbol, description=date, value=str(value))

    async def callback(self, interaction):
        """Push new values to view"""
        await interaction.response.defer()
        v = self.items[int(self.values[0])]
        self.view.embed.set_author(name=f"{v[1]} {v[0]}")
        self.view.embed.title = v[2]
        await self.view.update()


class PollButton(discord.ui.Button):
    """A Voting Button"""

    def __init__(self, emoji=None, label=None, row=0):
        super().__init__(emoji=emoji, label=label, row=row, style=discord.ButtonStyle.primary)

    async def callback(self, interaction):
        """Reply to user to let them know their vote has changed."""
        ej = f"{self.emoji} " if self.emoji is not None else ""
        if interaction.user.id in self.view.answers:
            await interaction.response.send_message(f'Your vote has been changed to {ej}{self.label}', ephemeral=True)
        else:
            await interaction.response.send_message(f'You have voted for {ej}{self.label}', ephemeral=True)
        self.view.answers.update({interaction.user.mention: self.label})
        await self.view.update()


class PollView(discord.ui.View):
    """View for a poll commands"""

    def __init__(self, ctx, question, answers):
        self.ctx = ctx
        self.message = None
        self.answers = {}
        self.question = question
        super().__init__(timeout=3600)

        buttons = [(None, i) for i in answers if i] if answers else [('👍', 'Yes'), ('👎', 'No')]
        for x, y in enumerate(buttons):
            row = x // 5
            self.add_item(PollButton(emoji=y[0], label=y[1], row=row))

    async def on_timeout(self):
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        e = self.prepare_embed(final=True)
        try:
            await self.message.edit(embed=e, view=self)
        except discord.HTTPException:
            pass
        self.stop()

    def prepare_embed(self, final=False):
        """Calculate current poll results"""
        e = discord.Embed()
        e.set_author(name=f"{self.ctx.author.name} asks...", icon_url=self.ctx.author.display_avatar.url)
        e.colour = discord.Colour.og_blurple() if not final else discord.Colour.green()
        if self.question:
            e.title = self.question + "?"

        e.description = ""
        counter = collections.Counter(self.answers.values())
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
        return e

    async def update(self):
        """Refresh the view and send to user"""
        e = self.prepare_embed()
        await self.message.edit(view=self, embed=e, allowed_mentions=discord.AllowedMentions.none())
        await self.wait()


class CoinView(discord.ui.View):
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
        except discord.HTTPException:
            return
        finally:
            self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.ctx.author.id == interaction.user.id

    async def update(self):
        """Update embed and push to view"""
        e = discord.Embed()
        e.colour = discord.Colour.og_blurple()
        e.set_thumbnail(url=COIN_IMAGE)
        e.title = "🪙 Coin Flip"

        e.description = f"**{self.results[-1]}**\n\n"

        if len(self.results) > 1:
            counter = collections.Counter(self.results)
            for c in counter.most_common():
                e.add_field(name=f"Total {c[0]}", value=c[1])

            e.description += "\n" + f"{'...' if len(self.results) > 200 else ''}"
            e.description += ', '.join([f'*{i}*' for i in self.results[-200:]])

        await self.message.edit(content="", view=self, embed=e, allowed_mentions=discord.AllowedMentions.none())
        await self.wait()


class FlipButton(discord.ui.Button):
    """Flip a coin and pass the result to the view"""

    def __init__(self, label="Flip a Coin", count=1):
        super().__init__()
        self.label = label
        self.emoji = "🪙"
        self.count = count
        self.style = discord.ButtonStyle.primary

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
        self.emoji = "🤡"
        reload(embed_utils)

    @commands.command(name="8ball", aliases=["8"])
    async def eight_ball(self, ctx, *, message=None):
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

        e = discord.Embed()
        e.set_author(name=f'🎱 {ctx.command.qualified_name.title()}')
        e.colour = 0x000001
        e.set_thumbnail(url=ctx.author.display_avatar.url)
        e.description = ctx.author.mention

        e.title = "" if message is None else message
        e.description = f"{ctx.author.mention} {random.choice(res)}"
        await self.bot.reply(ctx, embed=e)

    @commands.command()
    async def lenny(self, ctx):
        """( ͡° ͜ʖ ͡°)"""
        lennys = ['( ͡° ͜ʖ ͡°)', '(ᴗ ͜ʖ ᴗ)', '(⟃ ͜ʖ ⟄) ', '(͠≖ ͜ʖ͠≖)', 'ʕ ͡° ʖ̯ ͡°ʔ', '( ͠° ͟ʖ ͡°)', '( ͡~ ͜ʖ ͡°)',
                  '( ͡◉ ͜ʖ ͡◉)', '( ͡° ͜V ͡°)', '( ͡ᵔ ͜ʖ ͡ᵔ )',
                  '(☭ ͜ʖ ☭)', '( ° ͜ʖ °)', '( ‾ ʖ̫ ‾)', '( ͡° ʖ̯ ͡°)', '( ͡° ل͜ ͡°)', '( ͠° ͟ʖ ͠°)', '( ͡o ͜ʖ ͡o)',
                  '( ͡☉ ͜ʖ ͡☉)', 'ʕ ͡° ͜ʖ ͡°ʔ', '( ͡° ͜ʖ ͡ °)']
        await self.bot.reply(ctx, text=random.choice(lennys))

    @commands.command(aliases=["horo"])
    async def horoscope(self, ctx):
        """Find out your horoscope for this week"""
        # Get Sunday Just Gone.
        view = HoroscopeView(author=ctx.author)
        view.add_item(HoroscopeSelect())
        view.message = await self.bot.reply(ctx, "Fetching horoscopes...", view=view)
        await view.update()

    # TODO: Expand this to it's own cog. Timers, .stoppoll command, databse entry, persisatant view...
    @commands.command(usage="What is your favourite colour? Red, Blue, Green")
    async def poll(self, ctx, *, poll_string=None):
        """Create a poll with multiple choice answers.
        End the question with a ? and separate each answer with a ','

        Polls end after 1 hour of no responses."""
        if poll_string is None:
            question = ""
            answers = []
        else:
            try:
                question, answers = poll_string.split('?')
                answers = answers.split(',')
            except ValueError:
                if "," in poll_string:
                    question, answers = None, poll_string.split(',')
                else:
                    question, answers = poll_string, []

        if len(answers) > 25:
            return await self.bot.reply(ctx, 'Too many answers provided. 25 is more than enough thanks.')

        view = PollView(ctx, question=question, answers=answers)
        view.message = await self.bot.reply(ctx, embed=view.prepare_embed(), view=view)

    @commands.command(aliases=["choice", "pick", "select"], usage="<Option 1, Option 2, Option 3 ...>", emoji="🎲")
    async def choose(self, ctx, *, choices=None):
        """Make a decision for me (seperate choices with commas)"""
        if choices is None:
            return await self.bot.reply(ctx, "You need to specify some options to choose from.")

        e = discord.Embed()
        e.set_author(name=f'❔ {ctx.command.qualified_name.title()}')
        e.colour = ctx.author.colour
        e.set_thumbnail(url=ctx.author.display_avatar.url)
        e.description = ctx.author.mention

        choices = str(choices).split(", ")
        random.shuffle(choices)
        _ = choices.pop(0)
        e.description += f"\n\n🥇 **{_}**\n"
        try:
            _ = choices.pop(0)
            e.description += f"🥈 **{_}**\n"
            _ = choices.pop(0)
            e.description += f"🥉 **{_}**\n"
            e.description += ' ,'.join([f"*{i}*" for i in choices])
        except IndexError:
            pass
        await self.bot.reply(ctx, embed=e)

    @commands.command(aliases=["flip", "coinflip"])
    async def coin(self, ctx, count: int = 1):
        """Flip a coin"""
        if count > 10000:
            return await self.bot.reply(ctx, 'Too many coins.', ping=True)

        view = CoinView(ctx, count=count)
        view.add_item(FlipButton())

        for _ in [5, 10, 100, 1000]:
            view.add_item(FlipButton(label=f"Flip {_}", count=_))
        view.message = await self.bot.reply(ctx, "Flipping coin...", view=view)
        await view.update()

    @commands.command(aliases=["urbandictionary"])
    async def ud(self, ctx, *, lookup: commands.clean_content):
        """Lookup a definition from urban dictionary"""
        url = f"http://api.urbandictionary.com/v0/define?term={lookup}"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                await self.bot.reply(ctx, text=f"🚫 HTTP Error, code: {resp.status}")
                return
            resp = await resp.json()

        tn = "http://d2gatte9o95jao.cloudfront.net/assets/apple-touch-icon-2f29e978facd8324960a335075aa9aa3.png"

        embeds = []

        resp = resp["list"]
        # Populate Embed, add to list
        e = discord.Embed(color=0xFE3511)
        e.set_author(name=f"Urban Dictionary")
        e.set_thumbnail(url=tn)
        e.set_footer(text=ctx.author, icon_url=ctx.author.display_avatar.url)

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

        view = view_utils.Paginator(author=ctx.author, embeds=embeds)
        view.message = await self.bot.reply(ctx, "Fetching definitions...", view=view)
        await view.update()

    @commands.command(usage="1d6+3")
    async def roll(self, ctx, *, roll_string="d20"):
        """Roll a set of dice in the format XdY+Z. Start the roll with 'adv' or 'dis' to roll with (dis)advantage"""
        advantage = True if roll_string.startswith("adv") else False
        disadvantage = True if roll_string.startswith("dis") else False

        e = discord.Embed()
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
                
                if dice > 100 or sides > 10001:
                    return await self.bot.reply(ctx, text='Fuck off, no.', ping=True)
            
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
                        e.colour = discord.Colour.red()
                        e.set_footer(text="Critical Failure")
                    elif roll_outcome == sides:
                        e.colour = discord.Colour.green()
                        e.set_footer(text="Critical.")
            
            roll_info += ", ".join(curr_rolls)
            
            if bonus:
                roll_info += f" + {str(bonus)}" if bonus > 0 else f" {str(bonus).replace('-', ' - ')}"
            total_roll += bonus
            e.description += f"{roll_info} = **{total_roll}**" + "\n"

            total += total_roll

        if len(roll_list) > 1:
            e.description += f"\n**Total: {total}**"

        await self.bot.reply(ctx, embed=e)

    # Hidden One-Liners
    @commands.command(hidden=True)
    async def ttj(self, ctx):
        """That's the joke"""
        await self.bot.reply(ctx, text="https://www.youtube.com/watch?v=xECUrlnXCqk")

    @commands.command(hidden=True)
    async def dead(self, ctx):
        """STOP STOP HE'S ALREADY DEAD"""
        await self.bot.reply(ctx, text="https://www.youtube.com/watch?v=mAUY1J8KizU")


def setup(bot):
    """Loadthe Fun cog into the bot"""
    bot.add_cog(Fun(bot))
