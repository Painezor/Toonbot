"""Private world of warships related commands"""
from typing import TYPE_CHECKING

from discord import app_commands, Interaction
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from painezBot import PBot

# TODO: Go Live Tracker


class Warships(Cog):
    """World of Warships related commands"""

    def __init__(self, bot: 'PBot') -> None:
        self.bot: PBot = bot

    @app_commands.command()
    @app_commands.describe(code_list="Enter a list of codes")
    @app_commands.guilds(250252535699341312)
    async def codes(self, interaction: Interaction, code_list: str) -> None:
        """Strip codes for world of warships"""
        if interaction.user.id != self.bot.owner_id:
            return await self.bot.error(interaction, "You do not own this bot.")

        code_list = code_list.replace(';', '')
        code_list = code_list.split('|')
        code_list = "\n".join([i.strip() for i in code_list if i])

        await self.bot.reply(interaction, content=f"```\n{code_list}```")

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
