# import discord
# from ext.utils import embed_utils
#
#
# class DiceRoller(discord.ui.View):
#     """A View to handle dice rolling"""
#
#     def __init__(self, interaction):
#         self.ctx = ctx
#         self.message = None
#         super().__init__()
#
#     async def update(self):
#         """Create a dice tray to roll in"""
#         e = discord.Embed()
#         e.title = "🎲 Dice Tray"
#
#         for x in self.children:
#             try:
#                 text = ", ".join([str(i) for i in x.results])
#             except AttributeError:
#                 continue
#
#             if len(x.results) > 1:
#                 text += f"\n\n**Total**: {sum(x.results)}"
#
#             if not text:
#                 continue
#             e.add_field(name=x.label, value=text)
#
#         await self.message.edit("", embed=e, view=self)
#         await self.wait()
#
#     async def interaction_check(self, interaction: discord.Interaction) -> bool:
#         """Verify clicker is owner of interaction"""
#         return self.interaction.user.id == interaction.user.id
#
#
# class DiceButton(discord.ui.Button):
#     """A button to roll a dice"""
#
#     def __init__(self, sides, row=3):
#         super().__init__(label = f"d{sides}", row = row)
#         self.results: List = []
#         self.sides: int = sides
#
#     async def callback(self, interaction):
#         """Do the rolling"""
#         await interaction.response.defer()
#         self.results.append(random.randint(1, self.sides + 1))
#         await self.view.update()
#
#     @commands.command(aliases=['dice', 'tray'])
#     async def dice_tray(self, interaction):
#         """Roll dice with clicky buttons"""
#         if interaction.user.id != self.bot.owner_id:
#             return await interaction.client.error(interaction, "You do not own this bot.")
#         view = DiceRoller(ctx)
#         for num, x in enumerate([4, 6, 8, 10, 12, 20]):
#             row = num // 5
#             view.add_item(DiceButton(x, row=row))
#         view.add_item(StopButton(row=2))
#         await view.update()
