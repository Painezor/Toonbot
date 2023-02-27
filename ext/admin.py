"""Administration commands for Painezor, including logging, debugging,
   and loading of modules"""
from __future__ import annotations

import datetime
import logging
from inspect import isawaitable
from os import system
from sys import version
from traceback import format_exception
from typing import TYPE_CHECKING, Optional

from discord.ext import commands
import discord
from discord import Interaction, Embed, Message, Object

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

logger = logging.getLogger("Admin")


def error_to_codeblock(error) -> str:
    """Formatting of python errors into codeblocks"""
    fmt = format_exception(type(error), error, error.__traceback__)
    return (
        f":no_entry_sign: {type(error).__name__}: {error}```py\n"
        f'{"".join(fmt)}```'
    )


async def cg_ac(
    ctx: Interaction[Bot | PBot], current: str
) -> list[discord.app_commands.Choice]:
    """Autocomplete from list of cogs"""
    results = []
    for i in ctx.client.cogs.values():
        name = i.qualified_name

        if current.lower() in name.lower():
            results.append(discord.app_commands.Choice(name=name, value=name))
    return results[:25]


class Admin(commands.Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @commands.is_owner()
    @commands.command(name="sync")
    async def sync(self, ctx, guild: Optional[int] = None) -> Message:
        """Sync the command tree with discord"""

        if not guild:
            await self.bot.tree.sync()
            txt = "Asked discord to sync, please wait up to 1 hour."
            return await ctx.send(txt)
        else:
            await self.bot.tree.sync(guild=Object(id=guild))
            g = self.bot.get_guild(guild)
            return await ctx.send(f"Guild {g} Synced")

    cogs = discord.app_commands.Group(
        name="cogs",
        description="Load and unload modules",
        guild_ids=[250252535699341312],
    )

    @cogs.command(name="reload")
    @discord.app_commands.describe(cog="pick a cog to reload")
    @discord.app_commands.autocomplete(cog=cg_ac)
    async def reload(self, interaction: Interaction[Bot], cog: str) -> Message:
        """Reloads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.reload_extension(f"ext.{cog.lower()}")
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))
        e = discord.Embed(title="Modules", colour=discord.Colour.og_blurple())
        e.description = f"⚙️ Reloaded {cog}"
        return await interaction.edit_original_response(embed=e)

    @cogs.command()
    @discord.app_commands.autocomplete(cog=cg_ac)
    @discord.app_commands.describe(cog="pick a cog to load")
    async def load(self, interaction: Interaction[Bot], cog: str) -> Message:
        """Loads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.load_extension(f"ext.{cog.lower()}")
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e = discord.Embed(title="Modules", colour=discord.Colour.og_blurple())
        e.description = f"⚙️ Loaded {cog}"
        return await interaction.edit_original_response(embed=e)

    @cogs.command()
    @discord.app_commands.autocomplete(cog=cg_ac)
    async def unload(self, interaction: Interaction[Bot], cog: str) -> Message:
        """Unloads a module."""

        await interaction.response.defer(thinking=True)

        try:
            await self.bot.unload_extension(f"ext.{cog.lower()}")
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

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
        self, interaction: Interaction[Bot], to_print: str
    ) -> Message:
        """Print something to console."""

        await interaction.response.defer(thinking=True)
        if not interaction.user.id == self.bot.owner_id:
            raise commands.NotOwner

        logger.info("Print command output\n%s", to_print)
        e = discord.Embed(colour=discord.Colour.og_blurple())
        e.description = f"```\n{to_print}```"
        return await interaction.edit_original_response(embed=e)

    @console.command(name="clear")
    async def clear(self, interaction: Interaction) -> Message:
        """Clear the command window."""

        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        system("cls")
        _ = f"{self.bot.user}: {self.bot.initialised_at}"
        logger.info(
            f'{_}\n{"-" * len(_)}\nConsole cleared at:\n'
            f"{datetime.datetime.utcnow().replace(microsecond=0)}"
        )

        e = Embed(title="Bot Console", colour=discord.Colour.blurple())
        e.description = "```\nConsole Log Cleared.```"
        return await interaction.edit_original_response(embed=e)

    @discord.app_commands.command(name="quit")
    @discord.app_commands.guilds(250252535699341312)
    async def quit(self, interaction: Interaction) -> None:
        """Log the bot out gracefully."""
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        await self.bot.reply(interaction, content="Logging out.")
        return await self.bot.close()

    @discord.app_commands.command(name="debug")
    @discord.app_commands.guilds(250252535699341312)
    @discord.app_commands.describe(code=">>> Code Go Here")
    async def debug(self, interaction: Interaction[Bot], code: str) -> Message:
        """Evaluates code."""

        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise commands.NotOwner

        code = code.strip("` ")
        env = {
            "bot": self.bot,
            "ctx": Interaction,
            "interaction": interaction,
        }
        env.update(globals())

        e1 = discord.Embed(title="Input", colour=discord.Colour.lighter_grey())
        e2 = discord.Embed(title="Output", colour=discord.Colour.darker_grey())
        e2.set_footer(text=f"Python Version: {version}")

        try:
            if isawaitable(result := eval(code, env)):
                result = await result
        except Exception as err:
            result = error_to_codeblock(err)

        e1.description = f"```py\n{code}\n```"
        e2.description = f"```py\n{result}\n```"
        if len(e2.description) > 4000:
            logger.info("DEBUG command input\n%s", code)
            logger.info("DEBUG command output\n%s", result)
            e2.description = "Too long for discord, output sent to logger."
        return await self.bot.reply(interaction, embeds=[e1, e2])

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: Interaction[Bot],
        cmd: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        """Log commands as they are run"""
        guild = interaction.guild.name if interaction.guild else "DM"
        a = interaction.user
        logger.info("Command Ran [%s %s] /%s", a, guild, cmd.qualified_name)
        return


async def setup(bot: Bot | PBot) -> None:
    """Load the Administration cog into the Bot"""
    await bot.add_cog(Admin(bot))
