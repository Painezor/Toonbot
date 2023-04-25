"""Administration commands for Painezor, including logging, debugging,
   and loading of modules"""
from __future__ import annotations

import logging
from inspect import isawaitable
import os
from sys import version
from traceback import format_exception
import typing

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]

logger = logging.getLogger("Admin")


def error_to_codeblock(error: Exception) -> str:
    """Formatting of python errors into codeblocks"""
    fmt = format_exception(type(error), error, error.__traceback__)
    return f"🚫 {type(error).__name__}: {error}\n```py\n" f'{"".join(fmt)}```'


async def cg_ac(
    interaction: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete from list of cogs"""
    results: list[discord.app_commands.Choice[str]] = []

    cur = current.casefold()
    for i in interaction.client.available_cogs:
        if cur in i.casefold():
            i = i.rsplit(".", maxsplit=1)[-1]
            results.append(discord.app_commands.Choice(name=i, value=i))
    return results[:25]


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @commands.Cog.listener()
    async def on_command_error(self, _, error: discord.DiscordException):
        raise error

    @commands.is_owner()
    @commands.command(name="sync")
    async def sync(
        self, ctx: commands.Context[Bot], guild_id: typing.Optional[int] = None
    ) -> discord.Message:
        """Sync the command tree with discord"""
        try:
            if not guild_id:
                await self.bot.tree.sync()
                txt = "Sync request sent, can take up to 1 hour."
                return await ctx.send(txt)
            await self.bot.tree.sync(guild=discord.Object(id=guild_id))
            guild = self.bot.get_guild(guild_id)
            return await ctx.send(f"Guild {guild} Synced")
        except discord.DiscordException as err:
            logger.error(err, exc_info=True)
            return await ctx.send("Something fucked up")

    cogs = discord.app_commands.Group(
        name="cogs",
        description="Load and unload modules",
        guild_ids=[250252535699341312],
    )

    @cogs.command(name="reload")
    @discord.app_commands.describe(cog="pick a cog to reload")
    @discord.app_commands.autocomplete(cog=cg_ac)
    async def reload(self, interaction: Interaction, cog: str) -> None:
        """Reloads a module."""
        await interaction.response.defer(thinking=True)
        try:
            await self.bot.reload_extension("ext." + cog.casefold())
        except commands.ExtensionError as err:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = error_to_codeblock(err)
            await interaction.edit_original_response(embed=embed)
            raise

        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.description = f"⚙️ Reloaded {cog}"
        await interaction.edit_original_response(embed=embed)

    @cogs.command()
    @discord.app_commands.autocomplete(cog=cg_ac)
    @discord.app_commands.describe(cog="pick a cog to load")
    async def load(self, interaction: Interaction, cog: str) -> None:
        """Loads a module."""
        try:
            await self.bot.load_extension("ext." + cog.casefold())
        except commands.ExtensionError as err:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = error_to_codeblock(err)
            await interaction.response.send_message(embed=embed)
            raise

        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.description = f"⚙️ Loaded {cog}"
        return await interaction.response.send_message(embed=embed)

    @cogs.command()
    @discord.app_commands.autocomplete(cog=cg_ac)
    async def unload(self, interaction: Interaction, cog: str) -> None:
        """Unloads a module."""
        try:
            await self.bot.unload_extension("ext." + cog.casefold())
        except commands.ExtensionFailed as err:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = error_to_codeblock(err)
            await interaction.response.send_message(embed=embed)
            raise

        embed = discord.Embed(title="Modules")
        embed.colour = discord.Colour.og_blurple()
        embed.description = f"⚙️ Unloaded {cog}"
        return await interaction.response.send_message(embed=embed)

    console = discord.app_commands.Group(
        name="console",
        description="Console Commands",
        guild_ids=[250252535699341312],
    )

    @console.command(name="print")
    async def _print(self, interaction: Interaction, to_print: str) -> None:
        """Print something to console."""
        if not interaction.user.id == self.bot.owner_id:
            raise commands.NotOwner

        logger.info("Print command output\n%s", to_print)
        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.description = f"```\n{to_print}```"
        return await interaction.response.send_message(embed=embed)

    @console.command(name="clear")
    async def clear(self, interaction: Interaction) -> None:
        """Clear the command window."""
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        os.system("cls")
        initial = f"{self.bot.user}: {self.bot.initialised_at}"
        logger.info("%s", f'{initial}\n{"-" * len(initial)}')

        embed = discord.Embed(colour=discord.Colour.blurple())
        embed.description = "```\nConsole Log Cleared.```"
        return await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="quit")
    @discord.app_commands.guilds(250252535699341312)
    async def quit(self, interaction: Interaction) -> None:
        """Log the bot out gracefully."""
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        await interaction.response.send_message(content="Logging out.")
        return await self.bot.close()

    @discord.app_commands.command(name="debug")
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(code=">>> Code Go Here")
    async def debug(self, interaction: Interaction, code: str) -> None:
        """Evaluates code."""
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        code = code.strip("` ")
        env = {
            "bot": self.bot,
            "ctx": interaction,
            "interaction": interaction,
        }
        env.update(globals())

        in_embed = discord.Embed(colour=discord.Colour.lighter_grey())
        out_embed = discord.Embed(colour=discord.Colour.darker_grey())
        out_embed.set_footer(text=f"Python Version: {version}")

        try:
            # pylint: disable= W0123
            if isawaitable(result := eval(code, env)):  # type: ignore
                result = await result
            desc = f"```py\n{result}\n```"
        except Exception as err:
            result = error_to_codeblock(err)
            desc = result

        in_embed.description = f"```py\n{code}\n```"

        if len(desc) > 4000:
            logger.info("DEBUG command input\n%s", code)
            logger.info("DEBUG command output\n%s", result)
            out_embed.description = (
                "Too long for discord, output sent to logger."
            )
        out_embed.description = desc
        embeds = [in_embed, out_embed]
        return await interaction.response.send_message(embeds=embeds)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: Interaction, cmd: typing.Any
    ) -> None:
        """Log commands as they are run"""
        guild = interaction.guild.name if interaction.guild else "DM"
        user = interaction.user

        c_n = cmd.qualified_name
        if isinstance(cmd, discord.app_commands.ContextMenu):
            logger.info("Command Ran [%s %s] /%s", user, guild, c_n)
            return

        params = ", ".join([f"{k}={val}" for k, val in interaction.namespace])
        logger.info("Command Ran [%s %s] /%s %s", user, guild, c_n, params)
        return


async def setup(bot: Bot | PBot) -> None:
    """Load the Administration cog into the Bot"""
    await bot.add_cog(Admin(bot))
