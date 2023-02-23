"""Administration commands for Painezor, including logging, debugging,
   and loading of modules"""
from __future__ import annotations

import datetime
import logging
from inspect import isawaitable
from os import system
from sys import version
from traceback import format_exception
from typing import TYPE_CHECKING

from discord import Interaction, Embed, Colour, Message, Object
from discord.app_commands import (
    Choice,
    describe,
    autocomplete,
    Group,
    command,
    guilds,
    Command,
    ContextMenu,
)
from discord.ext.commands import Cog, NotOwner

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

logger = logging.getLogger("Admin")


def error_to_codeblock(error):
    """Formatting of python errors into codeblocks"""
    fmt = format_exception(type(error), error, error.__traceback__)
    return (
        f":no_entry_sign: {type(error).__name__}: {error}```py\n"
        f'{"".join(fmt)}```'
    )


async def cg_ac(interaction: Interaction, current: str) -> list[Choice]:
    """Autocomplete from list of cogs"""
    bot: Bot | PBot = interaction.client

    return [
        Choice(name=c, value=c)
        for c in sorted(bot.cogs)
        if current.lower() in c.lower()
    ]


class Admin(Cog):
    """Code debug & loading of modules"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @command(name="sync")
    @describe(guild="enter guild ID")
    async def sync(
        self, interaction: Interaction, guild: bool = False
    ) -> Message:
        """Sync the command tree with discord"""
        await interaction.response.defer(thinking=True)

        if not guild:
            await self.bot.tree.sync()
            txt = "Asked discord to sync, please wait up to 1 hour."
            return await self.bot.reply(interaction, txt)
        else:
            await self.bot.tree.sync(guild=Object(id=interaction.guild.id))
            return await self.bot.reply(interaction, "Guild Synced")

    cogs = Group(
        name="cogs",
        description="Load and unload modules",
        guild_ids=[250252535699341312],
    )

    @cogs.command(name="reload")
    @describe(cog="pick a cog to reload")
    @autocomplete(cog=cg_ac)
    async def reload(self, interaction: Interaction, cog: str) -> Message:
        """Reloads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.reload_extension(f"ext.{cog.lower()}")
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))
        e = Embed(
            title="Modules",
            colour=Colour.og_blurple(),
            description=f"⚙️ Reloaded {cog}",
        )
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @autocomplete(cog=cg_ac)
    @describe(cog="pick a cog to load")
    async def load(self, interaction: Interaction, cog: str) -> Message:
        """Loads a module."""
        await interaction.response.defer(thinking=True)

        try:
            await self.bot.load_extension(f"ext.{cog.lower()}")
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        e = Embed(
            title="Modules",
            colour=Colour.og_blurple(),
            description=f"⚙️ Loaded {cog}",
        )
        return await self.bot.reply(interaction, embed=e)

    @cogs.command()
    @autocomplete(cog=cg_ac)
    async def unload(self, interaction: Interaction, cog: str) -> Message:
        """Unloads a module."""

        await interaction.response.defer(thinking=True)

        try:
            await self.bot.unload_extension(f"ext.{cog.lower()}")
        except Exception as err:
            return await self.bot.error(interaction, error_to_codeblock(err))

        embed = Embed(
            title="Modules",
            colour=Colour.og_blurple(),
            description=f":⚙️: Unloaded {cog}",
        )
        return await self.bot.reply(interaction, embed=embed)

    console = Group(
        name="console",
        description="Console Commands",
        guild_ids=[250252535699341312],
    )

    @console.command(name="print")
    async def _print(self, interaction: Interaction, to_print: str) -> Message:
        """Print something to console."""

        await interaction.response.defer(thinking=True)
        if not interaction.user.id == self.bot.owner_id:
            raise NotOwner

        logging.critical("Print command output\n%s", to_print)

        e = Embed(
            colour=Colour.og_blurple(), description=f"```\n{to_print}```"
        )
        return await self.bot.reply(interaction, embed=e)

    @console.command(name="clear")
    async def clear(self, interaction: Interaction) -> Message:
        """Clear the command window."""

        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner

        system("cls")
        _ = f"{self.bot.user}: {self.bot.initialised_at}"
        logging.info(
            f'{_}\n{"-" * len(_)}\nConsole cleared at:\n'
            f"{datetime.datetime.utcnow().replace(microsecond=0)}"
        )

        e = Embed(
            title="Bot Console",
            colour=Colour.og_blurple(),
            description="```\nConsole Log Cleared.```",
        )
        return await self.bot.reply(interaction, embed=e)

    @command(name="quit")
    @guilds(250252535699341312)
    async def quit(self, interaction: Interaction) -> Message:
        """Log the bot out gracefully."""
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner
        await self.bot.reply(interaction, content="Logging out.")
        return await self.bot.close()

    @command(name="debug")
    @guilds(250252535699341312)
    @describe(code=">>> Code Go Here")
    async def debug(self, interaction: Interaction, code: str) -> Message:
        """Evaluates code."""

        await interaction.response.defer(thinking=True)
        if interaction.user.id != self.bot.owner_id:
            raise NotOwner

        code = code.strip("` ")
        env = {"bot": self.bot, "ctx": interaction, "interaction": interaction}
        env.update(globals())

        e1: Embed = Embed(title="Input", colour=Colour.lighter_grey())
        e2: Embed = Embed(title="Output", colour=Colour.darker_grey())
        e2.set_footer(text=f"Python Version: {version}")

        try:
            if isawaitable(result := eval(code, env)):
                result = await result
        except Exception as err:
            result = error_to_codeblock(err)

        e1.description = f"```py\n{code}\n```"
        e2.description = f"```py\n{result}\n```"
        if len(e2.description) > 4000:
            logger.log("DEBUG command input\n", code)
            logger.log("DEBUG command output\n", result)
            e2.description = "Too long for discord, output sent to logger."
        return await self.bot.reply(interaction, embeds=[e1, e2])

    @Cog.listener()
    async def on_app_command_completion(
        self, interaction: Interaction, cmd: Command | ContextMenu
    ) -> None:
        """Log commands as they are run"""
        guild = interaction.guild.name if interaction.guild else "DM"
        logger.info(
            f"Command Ran [{interaction.user} {guild}]" "/{cmd.qualified_name}"
        )
        return


async def setup(bot: Bot | PBot) -> None:
    """Load the Administration cog into the Bot"""
    await bot.add_cog(Admin(bot))
