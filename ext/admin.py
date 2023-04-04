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

logger = logging.getLogger("Admin")


def error_to_codeblock(error) -> str:
    """Formatting of python errors into codeblocks"""
    fmt = format_exception(type(error), error, error.__traceback__)
    return f"🚫 {type(error).__name__}: {error}\n```py\n" f'{"".join(fmt)}```'


async def cg_ac(
    interaction: discord.Interaction[Bot | PBot], current: str
) -> list[discord.app_commands.Choice]:
    """Autocomplete from list of cogs"""
    results = []

    cur = current.casefold()
    for i in interaction.client.cogs.values():
        name = i.qualified_name

        if cur in name.casefold():
            results.append(discord.app_commands.Choice(name=name, value=name))
    return results[:25]


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @commands.is_owner()
    @commands.command(name="sync")
    async def sync(
        self, ctx, guild_id: typing.Optional[int] = None
    ) -> discord.Message:
        """Sync the command tree with discord"""

        if not guild_id:
            await self.bot.tree.sync()
            txt = "Asked discord to sync, please wait up to 1 hour."
            return await ctx.send(txt)
        else:
            await self.bot.tree.sync(guild=discord.Object(id=guild_id))
            guild = self.bot.get_guild(guild_id)
            return await ctx.send(f"Guild {guild} Synced")

    cogs = discord.app_commands.Group(
        name="cogs",
        description="Load and unload modules",
        guild_ids=[250252535699341312],
    )

    @cogs.command(name="reload")
    @discord.app_commands.describe(cog="pick a cog to reload")
    @discord.app_commands.autocomplete(cog=cg_ac)
    async def reload(
        self, interaction: discord.Interaction[Bot | PBot], cog: str
    ) -> discord.InteractionMessage:
        """Reloads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.reload_extension(f"ext.{cog.casefold()}")
        except commands.ExtensionError as err:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = error_to_codeblock(err)
            return await interaction.edit_original_response(embed=embed)

        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.description = f"⚙️ Reloaded {cog}"
        return await interaction.edit_original_response(embed=embed)

    @cogs.command()
    @discord.app_commands.autocomplete(cog=cg_ac)
    @discord.app_commands.describe(cog="pick a cog to load")
    async def load(
        self, interaction: discord.Interaction[Bot | PBot], cog: str
    ) -> discord.InteractionMessage:
        """Loads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.load_extension(f"ext.{cog.casefold()}")
        except commands.ExtensionError as err:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = error_to_codeblock(err)
            return await interaction.edit_original_response(embed=embed)

        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.description = f"⚙️ Loaded {cog}"
        return await interaction.edit_original_response(embed=embed)

    @cogs.command()
    @discord.app_commands.autocomplete(cog=cg_ac)
    async def unload(
        self, interaction: discord.Interaction[Bot | PBot], cog: str
    ) -> discord.InteractionMessage:
        """Unloads a module."""

        await interaction.response.defer(thinking=True)

        try:
            await self.bot.unload_extension(f"ext.{cog.casefold()}")
        except commands.ExtensionFailed as err:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = error_to_codeblock(err)
            return await interaction.edit_original_response(embed=embed)

        embed = discord.Embed(title="Modules")
        embed.colour = discord.Colour.og_blurple()
        embed.description = f":⚙️: Unloaded {cog}"
        return await interaction.edit_original_response(embed=embed)

    console = discord.app_commands.Group(
        name="console",
        description="Console Commands",
        guild_ids=[250252535699341312],
    )

    @console.command(name="print")
    async def _print(
        self, interaction: discord.Interaction[Bot | PBot], to_print: str
    ) -> discord.InteractionMessage:
        """Print something to console."""

        await interaction.response.defer(thinking=True)
        if not interaction.user.id == self.bot.owner_id:
            raise commands.NotOwner

        logger.info("Print command output\n%s", to_print)
        embed = discord.Embed(colour=discord.Colour.og_blurple())
        embed.description = f"```\n{to_print}```"
        return await interaction.edit_original_response(embed=embed)

    @console.command(name="clear")
    async def clear(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """Clear the command window."""
        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        os.system("cls")
        initial = f"{self.bot.user}: {self.bot.initialised_at}"
        logger.info("%s", f'{initial}\n{"-" * len(initial)}')

        embed = discord.Embed(colour=discord.Colour.blurple())
        embed.description = "```\nConsole Log Cleared.```"
        return await interaction.edit_original_response(embed=embed)

    @discord.app_commands.command(name="quit")
    @discord.app_commands.guilds(250252535699341312)
    async def quit(self, interaction: discord.Interaction[Bot | PBot]) -> None:
        """Log the bot out gracefully."""
        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        await interaction.edit_original_response(content="Logging out.")
        return await self.bot.close()

    @discord.app_commands.command(name="debug")
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(code=">>> Code Go Here")
    async def debug(
        self, interaction: discord.Interaction[Bot | PBot], code: str
    ) -> discord.InteractionMessage:
        """Evaluates code."""

        await interaction.response.defer(thinking=True)
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
        except commands.ExtensionError as err:
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
        return await interaction.edit_original_response(
            embeds=[in_embed, out_embed]
        )


async def setup(bot: Bot | PBot) -> None:
    """Load the Administration cog into the Bot"""
    await bot.add_cog(Admin(bot))
