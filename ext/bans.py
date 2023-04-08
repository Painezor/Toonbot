"""Cog for managing and bulk banning members"""
from __future__ import annotations

import logging
import typing

import discord
from discord.ext import commands

from ext.utils import embed_utils, view_utils

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]
    User: typing.TypeAlias = discord.User | discord.Member

logger = logging.getLogger("bans")


class BanView(view_utils.DropdownPaginator):
    """View to hold the BanList"""

    def __init__(self, invoker: User, bans: list[discord.BanEntry]) -> None:
        self.bans: list[discord.BanEntry] = bans

        embed = discord.Embed(title="Banned Users")
        embed.colour = discord.Colour.dark_red()

        options = []
        rows = []

        for i in self.bans:
            opt = discord.SelectOption(label=str(i.user))
            opt.value = str(i.user.id)
            opt.emoji = "☠"
            opt.description = f"User #{i.user.id}"
            options.append(opt)
            rows.append(f"`{i.user.id}` {i.user.mention} ({i.user})")

        super().__init__(invoker, embed, rows, options)
        self.dropdown.max_values = len(self.dropdown.options)

    async def handle_page(self, interaction: Interaction) -> None:
        await super().handle_page(interaction)
        self.dropdown.max_values = len(self.dropdown.options)

    @discord.ui.select(placeholder="Unban members")
    async def dropdown(
        self, interaction: Interaction, sel: discord.ui.Select
    ) -> None:
        """Perform unbans on the entries passed back from the SelectOption"""

        embed = discord.Embed(colour=discord.Colour.green())
        embed.title = "Users unbanned"
        embed.description = ""
        embed.timestamp = discord.utils.utcnow()

        guild = typing.cast(discord.Guild, interaction.guild)
        embed_utils.user_to_footer(embed, interaction.user)

        reason = f"Requested by {interaction.user}"
        for ban in sel.values:
            entry = next(i for i in self.bans if str(i.user.id) == ban)
            user = entry.user
            await guild.unban(user, reason=reason)

            embed.description += f"{user} {user.mention} ({user.id})\n"
            self.bans.remove(entry)
        await interaction.followup.send(embed=embed)

        new_view = BanView(interaction.user, self.bans)
        edit = interaction.response.edit_message
        return await edit(embed=embed, view=new_view)


class BanModal(discord.ui.Modal, title="Bulk ban user IDs"):
    """Modal for user to enter multi line bans on."""

    ban_list: discord.ui.TextInput = discord.ui.TextInput(
        label="Enter User IDs to ban, one per line",
        style=discord.TextStyle.paragraph,
        placeholder="12345678901234\n12345678901235\n12345678901236\n…",
    )
    reason: discord.ui.TextInput = discord.ui.TextInput(
        label="Enter a reason",
        placeholder="<Insert your reason here>",
        default="No reason provided",
    )

    async def on_submit(self, interaction: Interaction, /) -> None:
        """Ban users on submit."""
        embed = discord.Embed(title="Users Banned")
        embed.description = ""
        embed.add_field(name="reason", value=self.reason.value)

        guild = typing.cast(discord.Guild, interaction.guild)

        mems = self.ban_list.value.split("\n")
        targets = [int(i.strip()) for i in mems if i]

        async def ban_user(user_id: int) -> str:
            """Attempt to ban user"""
            try:
                await interaction.client.http.ban(user_id, guild.id)
            except discord.HTTPException:
                return f"🚫 Could not ban <@{user_id}> (#{user_id})."
            else:
                return f"☠ <@{user_id}> was banned (#{user_id})"

        embed.description = "\n".join([await ban_user(i) for i in targets])
        await interaction.response.send_message(embed=embed)


class BanCog(commands.Cog):
    """Single Command Cog for managing user bans"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(ban_members=True)
    @discord.app_commands.checks.bot_has_permissions(ban_members=True)
    async def ban(self, interaction: Interaction) -> None:
        """Bans a list of user IDs"""
        return await interaction.response.send_modal(BanModal())

    @discord.app_commands.command()
    @discord.app_commands.describe(name="Search by name")
    @discord.app_commands.default_permissions(ban_members=True)
    @discord.app_commands.checks.bot_has_permissions(ban_members=True)
    async def banlist(
        self,
        interaction: Interaction,
        name: typing.Optional[str],
    ) -> None:
        """Show the ban list for the server"""
        guild = typing.cast(discord.Guild, interaction.guild)

        embed = discord.Embed(colour=discord.Colour.red())
        # Exhaust All Bans.
        if not (bans := [i async for i in guild.bans()]):
            embed.description = f"{guild.name} has no bans!"
            await interaction.response.send_message(embed=embed)
            return

        if name is not None:
            if not (bans := [i for i in bans if name in i.user.name]):
                embed.description = f"No bans found matching {name}"
                await interaction.response.send_message(embed=embed)
                return

        view = BanView(interaction.user, bans)
        await interaction.response.send_message(view=view, embed=view.pages[0])


async def setup(bot: Bot | PBot) -> None:
    """Load the Cog into the bot"""
    await bot.add_cog(BanCog(bot))
