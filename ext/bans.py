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

    Interaction: typing.TypeAlias = (
        discord.Interaction[Bot] | discord.Interaction[PBot]
    )

logger = logging.getLogger("bans")


class BanView(view_utils.BaseView):
    """View to hold the BanList"""

    def __init__(
        self,
        interaction: Interaction,
        bans: list[discord.BanEntry],
    ) -> None:
        super().__init__(interaction)

        self.pages = embed_utils.paginate(bans)

        self.bans = bans
        self.page_bans: list[discord.BanEntry] = []

    @property
    def embed(self) -> discord.Embed:
        """Generic Embed for this server"""
        guild = typing.cast(discord.Guild, self.interaction.guild)
        embed = discord.Embed(title=f"{guild.name} bans")
        embed.colour = discord.Colour.blurple()
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed

    def add_select(self) -> str:
        """Add the select option and return the generated text"""
        opts = []
        txt = ""
        for ban in self.page_bans:
            opt = discord.SelectOption(label=str(ban.user))
            opt.value = str(ban.user.id)
            opt.emoji = "☠"
            opt.description = f"User #{ban.user.id}"
            opts.append(opt)
            txt += f"`{ban.user.id}` {ban.user.mention} ({ban.user})\n"
        self.add_item(BanSelect(opts))
        return txt

    async def update(self) -> discord.InteractionMessage:
        """Refresh the view with the latest page"""
        # Clear Old items
        self.pages = embed_utils.paginate(self.bans)
        self.clear_items()
        self.page_bans = self.pages[self.index]
        embed = self.embed.copy()

        embed.description = self.add_select()

        self.add_page_buttons(1)
        edit = self.interaction.edit_original_response
        return await edit(view=self, embed=embed)

    async def unban(self, bans: list[str]):
        """Perform unbans on the entries passed back from the SelectOption"""
        embed = discord.Embed(colour=discord.Colour.green())
        embed.title = "Users unbanned"
        embed.description = ""
        embed.timestamp = discord.utils.utcnow()

        guild = typing.cast(discord.Guild, self.interaction.guild)

        embed_utils.user_to_footer(embed, self.interaction.user)

        reason = f"Requested by {self.interaction.user}"
        for ban in [b for b in self.page_bans if str(b.user.id) in bans]:
            await guild.unban(ban.user, reason=reason)
            embed.description += (
                f"{ban.user} {ban.user.mention} ({ban.user.id})\n"
            )
            self.bans.remove(ban)

        self.pages = embed_utils.paginate(self.bans)

        self.clear_items()
        self.page_bans = self.pages[self.index]
        embed = self.embed.copy()
        embed.description = self.add_select()
        self.add_page_buttons(1)

        edit = self.interaction.edit_original_response
        return await edit(embed=embed, view=self)


class BanSelect(discord.ui.Select):
    """Dropdown to unban members"""

    view: BanView

    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Unban members",
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """When the select is triggered"""

        await interaction.response.defer()
        return await self.view.unban(self.values)


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

    def __init__(self) -> None:
        super().__init__()

    async def on_submit(self, interaction: Interaction) -> None:
        """Ban users on submit."""
        embed = discord.Embed(title="Users Banned")
        embed.description = ""
        embed.add_field(name="reason", value=self.reason.value)

        guild = typing.cast(discord.Guild, interaction.guild)

        targets = [
            int(i.strip()) for i in self.ban_list.value.split("\n") if i
        ]

        async def ban_user(user_id: int) -> str:
            """Attempt to ban user"""
            try:
                await interaction.client.http.ban(user_id, guild.id)
            except discord.HTTPException:
                return f"🚫 Could not ban <@{user_id}> (#{user_id})."
            else:
                return f"☠ <@{user_id}> was banned (#{user_id})"

        embed.description = "\n".join([await ban_user(i) for i in targets])
        await interaction.edit_original_response(embed=embed)


class BanCog(commands.Cog):
    """Single Command Cog for managing user bans"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot: Bot | PBot = bot

    @discord.app_commands.command()
    @discord.app_commands.default_permissions(ban_members=True)
    @discord.app_commands.checks.bot_has_permissions(ban_members=True)
    async def ban(self, interaction: Interaction) -> None:
        """Bans a list of user IDs"""
        await interaction.response.send_modal(BanModal())
        return

    @discord.app_commands.command()
    @discord.app_commands.describe(name="Search by name")
    @discord.app_commands.default_permissions(ban_members=True)
    @discord.app_commands.checks.bot_has_permissions(ban_members=True)
    async def banlist(
        self,
        interaction: Interaction,
        name: typing.Optional[str],
    ) -> discord.InteractionMessage:
        """Show the ban list for the server"""
        await interaction.response.defer(thinking=True)
        guild = typing.cast(discord.Guild, interaction.guild)

        embed = discord.Embed(colour=discord.Colour.red())
        # Exhaust All Bans.
        if not (bans := [i async for i in guild.bans()]):
            embed.description = f"{guild.name} has no bans!"
            return await interaction.edit_original_response(embed=embed)

        if name is not None:
            if not (bans := [i for i in bans if name in i.user.name]):
                embed.description = f"No bans found matching {name}"
                return await interaction.edit_original_response(embed=embed)
        return await BanView(interaction, bans).update()


async def setup(bot: Bot | PBot) -> None:
    """Load the Cog into the bot"""
    await bot.add_cog(BanCog(bot))
