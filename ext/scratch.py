# import discord
# from ext.utils import embed_utils
#
#
# class DiceRoller(discord.ui.View):
#     """A View to handle dice rolling"""
#
#     def __init__(self, ctx):
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
#         return self.ctx.author.id == interaction.user.id
#
#
# class DiceButton(discord.ui.Button):
#     """A button to roll a dice"""
#
#     def __init__(self, sides, row=3):
#         super().__init__()
#         self.row = row
#         self.label = f"d{sides}"
#         self.results = []
#         self.sides = sides
#
#     async def callback(self, interaction):
#         """Do the rolling"""
#         await interaction.response.defer()
#         self.results.append(random.randint(1, self.sides + 1))
#         await self.view.update()
#
#     @commands.command(aliases=['dice', 'tray'])
#     @commands.is_owner()
#     async def dice_tray(self, ctx):
#         """Roll dice with clicky buttons"""
#         view = DiceRoller(ctx)
#         for num, x in enumerate([4, 6, 8, 10, 12, 20]):
#             row = num // 5
#             view.add_item(DiceButton(x, row=row))
#         view.add_item(StopButton(row=2))
#
#         view.message = await self.bot.reply(ctx, content="Generating Dice Tray...", view=view)
#         await view.update()
#
#     # OLD PICK_CHANNELS FROM TICKER.PY
#     async def _pick_channels(self, ctx, channels):
#         # Assure guild has goal ticker channel.
#         channels = [channels] if isinstance(channels, discord.TextChannel) else channels
#
#         if ctx.guild.id not in [i[0] for i in self.cache]:
#             await self.bot.reply(ctx, content=f'{ctx.guild.name} does not have any tickers.')
#             channels = []
#
#         if channels:
#             # Verify selected channels are actually in the database.
#             checked = []
#             for i in channels:
#                 if i.id not in [c[1] for c in self.cache]:
#                     await self.bot.reply(ctx, content=f"{i.mention} does not have any tickers.")
#                 else:
#                     checked.append(i)
#             channels = checked
#
#         if not channels:
#             channels = [self.bot.get_channel(i[1]) for i in self.cache if i[0] == ctx.guild.id]
#             # Filter out NoneTypes caused by deleted channels.
#             channels = [i for i in channels if i is not None]
#
#         channel_links = [i.mention for i in channels]
#
#         index = await embed_utils.page_selector(ctx, channel_links, choice_text="For which channel?")
#
#         if index == "cancelled" or index == -1 or index is None:
#             return None  # Cancelled or timed out.
#         channel = channels[index]
#         return channel
