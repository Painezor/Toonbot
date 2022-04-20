"""Code I need to save for later."""
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
#     async def update(self) -> Message:
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
#         view.add_item(Stop(row=2))
#         await view.update()


targets = ["andejay", "andy_the_cupid_stunt", "chaosmachinegr", "Charede", "darknessdreams_1", "DobbyM8",
           "frostinator08", "GameProdigy", "Jamdearest", "KidneyCowboy", "Lord_Zath", "Masterchief1567", "nebelfuss",
           "painezor", "Pelzmorph", "pops_place", "Redberen", "SeaRaptor00", "song_mg", "spacepickshovel", "StatsBloke",
           "tcfreer", "texashula", "the_shadewe", "thegrumpybeard", "TigersDen", "wookie_legend", "Xairen", "Yuzral"]

# def make_bauble(img):
#     """Make a single bauble"""
#     # Open Avatar file.
#     avatar = Image.open(r"F:/Logos/" + img).convert(mode="RGBA")
#
#     # Create Canvas & Paste Avatar
#     canvas = Image.new("RGBA", (300, 350), (0, 0, 0, 255))
#     canvas.paste(avatar, (0, 50))
#
#     # Apply Bauble mask.
#     msk = Image.open("images/Bauble_MASK.png").convert('L')
#     canvas.putalpha(msk)
#
#     # Apply bauble top overlay
#     bauble_top = Image.open("images/BaubleTop.png").convert(mode="RGBA")
#     canvas.paste(bauble_top, mask=bauble_top)
#
#     output_loc = r"F:/Logo-Output/" + img.split('.')[0]
#     canvas.save(output_loc + ".png")
#
#
# def bulk_image():
#     """Batch Export Baubles"""
#     directory = r'F:\Logos'
#     for img in os.listdir(directory):
#         make_bauble(img)
