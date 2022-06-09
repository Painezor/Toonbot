"""Private world of warships related commands"""
from typing import TYPE_CHECKING

from discord import Interaction, Embed, ButtonStyle, Message
from discord.app_commands import command, describe, default_permissions
from discord.ext.commands import Cog
from discord.ui import View, Button

from ext.utils.wows_utils import Region

if TYPE_CHECKING:
    from painezBot import PBot

# TODO: Go Live Tracker

RAGNAR = "Ragnar is inherently underpowered. It lacks the necessary attributes to make meaningful impact on match " \
         "result. No burst damage to speak of, split turrets, and yet still retains a fragile platform. I would take" \
         " 1 Conqueror..Thunderer or 1 DM or even 1 of just about any CA over 2 Ragnars on my team any day of the" \
         " week. Now... If WG gave it the specialized repair party of the Nestrashimy ( and 1 more base charge)..." \
         " And maybe a few more thousand HP if could make up for where it is seriously lacking with longevity"


class Warships(Cog):
    """World of Warships related commands"""

    def __init__(self, bot: 'PBot') -> None:
        self.bot: PBot = bot

    async def send_code(self, code: str, contents: str, interaction: Interaction, **kwargs) -> Message:
        """Generate the Embed for the code."""
        e = Embed(title="World of Warships Redeemable Code")
        e.title = code
        e.description = ""
        e.set_author(name="World of Warships Bonus Code")
        e.set_thumbnail(url=interaction.client.user.avatar.url)
        if contents:
            e.description += f"Contents:\n```yaml\n{contents}```"
        e.description += "Click on a button below to redeem for your region"

        for k, v in kwargs.items():
            if v:
                print("kwarg", k, v)
                region = next(i for i in Region if k == i.db_key)
                e.colour = region.colour
                break

        view = View()
        for k, v in kwargs.items():
            if v:
                region = next(i for i in Region if k == i.db_key)
                url = f"https://{region.code_prefix}.wargaming.net/shop/redeem/?bonus_mode=" + code
                view.add_item(Button(url=url, label=region.db_key.upper(), style=ButtonStyle.url, emoji=region.emote))

        return await self.bot.reply(interaction, embed=e, view=view)

    @command()
    async def ragnar(self, interaction: Interaction) -> Message:
        """Ragnar is inherently underpowered"""
        return await self.bot.reply(interaction, content=RAGNAR)

    @command()
    @describe(code="Enter the code", contents="Enter the reward the code gives")
    @default_permissions(manage_messages=True)
    async def code(self, interaction: Interaction, code: str, contents: str,
                   eu: bool = True, na: bool = True, asia: bool = True) -> Message:
        """Send a message with region specific redeem buttons"""
        await interaction.response.defer(thinking=True)
        return await self.send_code(code, contents, interaction, eu=eu, na=na, sea=asia)

    @command()
    @describe(code="Enter the code", contents="Enter the reward the code gives")
    @default_permissions(manage_messages=True)
    async def code_cis(self, interaction: Interaction, code: str, contents: str) -> Message:
        """Send a message with a region specific redeem button"""
        await interaction.response.defer(thinking=True)
        return await self.send_code(code, contents, interaction, cis=True)

    @command()
    @describe(code_list="Enter a list of codes, | and , will be stripped, and a list will be returned.")
    async def cc_code_parser(self, interaction: Interaction, code_list: str) -> None:
        """Strip codes for world of warships CCs"""
        code_list = code_list.replace(';', '')
        code_list = code_list.split('|')
        code_list = "\n".join([i.strip() for i in code_list if i])

        await self.bot.reply(interaction, content=f"```\n{code_list}```", ephemeral=True)

    # @commands.command()
    # async def twitch(self, interaction):
    #     """Test command for twitch embeds"""
    #     if interaction.user.id != self.bot.owner_id:
    #         return await interaction.client.error(interaction, "You do not own this bot.")
    #     e: Embed = Embed()
    #     e.title = "World of Warships"
    #     e.set_author(name="Twitch: Painezor", url="http://www.twitch.tv/Painezor")
    #     e.colour = 0x6441A4
    #     tw = "http://www.twitch.tv/Painezor"
    #     e.description = f"[**{interaction.guild.get_member(interaction.client.owner_id).mention}
    #     just went live!**]({tw})\n"
    #     e.description += "\nGold League Ranked & Regrinding Destroyers!"
    #     e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    #     url = interaction.guild.get_member(interaction.client.owner_id).display_avatar.url
    #     e.set_thumbnail(url=url)
    #
    #     await interaction.client.reply(interaction, tw, embed=e)


async def setup(bot: 'PBot'):
    """Load the cog into the bot"""
    await bot.add_cog(Warships(bot))
