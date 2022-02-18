"""Testing Cog for new commands."""
from discord import InputTextStyle, Embed, Interaction, Color
from discord.ext import commands
from discord.ui import Modal, InputText


class MyModal(Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(InputText(label="Months", placeholder="Enter number of months", max_length=2, required=False))
        self.add_item(InputText(label="Days", placeholder="Enter number of days", max_length=2, required=False))
        self.add_item(InputText(label="Hours", placeholder="Enter number of hours", max_length=2, required=False))
        self.add_item(InputText(label="Minutes", placeholder="Enter number of minutes", max_length=2, required=False))

        self.add_item(
            InputText(
                label="Reminder Description",
                placeholder="Enter a description of your reminder",
                style=InputTextStyle.long,
                required=False
            )
        )

        # MODALS HAVE LIMIT OF 5 BOXES.

    async def callback(self, interaction: Interaction):
        """Testing. Fuck off."""
        months = int(self.children[0].value) if self.children[0].value.isdigit() else 0
        days = int(self.children[1].value) if self.children[1].value.isdigit() else 0
        hours = int(self.children[2].value) if self.children[1].value.isdigit() else 0
        minutes = int(self.children[3].value) if self.children[1].value.isdigit() else 0
        description = self.children[4].value

        embed = Embed(title="Your Modal Results", color=Color.random())
        embed.add_field(name="First Input", value=self.children[0].value, inline=False)
        embed.add_field(name="Second Input", value=self.children[1].value, inline=False)
        await interaction.response.send_message(embeds=[embed])


class Test(commands.Cog):
    """Various testing functions"""

    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(guild_ids=[250252535699341312])
    async def modal(self, ctx):
        modal = MyModal(title="Slash Command Modal")
        await ctx.interaction.response.send_modal(modal)


def setup(bot):
    """Add the testing cog to the bot"""
    bot.add_cog(Test(bot))

# Maybe TO DO: Button to Toggle Substitutes in Extended Views
