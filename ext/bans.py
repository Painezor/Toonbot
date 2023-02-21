"""Cog for managing and bulk banning members"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord.utils
from discord import Embed, BanEntry, SelectOption, Colour, TextStyle, NotFound, HTTPException
from discord.app_commands import command, default_permissions, describe
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ui import Select, Modal, TextInput

from ext.utils.view_utils import add_page_buttons, BaseView

if TYPE_CHECKING:
    from discord import Interaction, Message
    from core import Bot
    from painezBot import PBot

logger = logging.getLogger('bans')


class BanView(BaseView):
    """View to hold the BanList"""

    def __init__(self, interaction: Interaction, bans: list[BanEntry]) -> None:
        super().__init__(interaction)
        self.bot: Bot | PBot = interaction.client

        self.pages = [bans[i:i + 25] for i in range(0, len(bans), 25)]
        self.index = 0

        self.bans = bans
        self.page_bans: list[BanEntry] = []

    @property
    def embed(self) -> Embed:
        """Generic Embed for this server"""
        e = Embed(title=f"{self.interaction.guild.name} bans", colour=Colour.blurple())
        if self.interaction.guild.icon:
            e.set_thumbnail(url=self.interaction.guild.icon.url)
        return e

    async def update(self) -> None:
        """Refresh the view with the latest page"""
        # Clear Old items
        self.pages = [self.bans[i:i + 25] for i in range(0, len(self.bans), 25)]

        self.clear_items()
        self.page_bans = self.pages[self.index]
        e = self.embed.copy()

        self.add_item(BanSelect([SelectOption(label=str(b.user), description=f"User #{b.user.id}", emoji="☠",
                                              value=str(b.user.id)) for b in self.page_bans]))
        e.description = '\n'.join([f"`{b.user.id}` {b.user.mention} {str(b.user)}" for b in self.page_bans])

        add_page_buttons(self, 1)
        logger.info('Dispatching Reply')
        return await self.bot.reply(self.interaction, view=self, embed=e)

    async def unban(self, bans: list[str]):
        """Perform unbans on the entries passed back from the SelectOption"""
        e = Embed(colour=Colour.green(), title="Users unbanned", description="", timestamp=discord.utils.utcnow())
        e.set_footer(text=f"Action performed by {self.interaction.user}\n{self.interaction.user.id}",
                     icon_url=self.interaction.user.display_avatar.url)

        for ban in [b for b in self.page_bans if str(b.user.id) in bans]:
            await self.interaction.guild.unban(ban.user, reason=f"Requested by {self.interaction.user}")
            e.description += f"{ban.user} {ban.user.mention} ({ban.user.id})\n"
            self.bans.remove(ban)

        self.pages = [self.bans[i:i + 25] for i in range(0, len(self.bans), 25)]

        self.clear_items()
        self.page_bans = self.pages[self.index]
        e = self.embed.copy()

        self.add_item(BanSelect([SelectOption(label=str(b.user), description=f"User #{b.user.id}", emoji="☠",
                                              value=str(b.user.id)) for b in self.page_bans]))
        e.description = '\n'.join([f"`{b.user.id}` {b.user.mention} {str(b.user)}" for b in self.page_bans])

        add_page_buttons(self, 1)
        return await self.bot.reply(self.interaction, embed=e, view=self)


class BanSelect(Select):
    """Dropdown to unban members"""
    view: BanView

    def __init__(self, options: list[SelectOption]) -> None:
        super().__init__(placeholder="Unban members", max_values=len(options), options=options, row=0)

    async def callback(self, interaction: Interaction) -> Message:
        """When the select is triggered"""
        await interaction.response.defer()
        return await self.view.unban(self.values)


class BanModal(Modal, title="Bulk ban user IDs"):
    """Modal for user to enter multi line bans on."""
    ban_list = TextInput(label="Enter User IDs to ban, one per line", style=TextStyle.paragraph,
                         placeholder="12345678901234\n12345678901235\n12345678901236\n…")
    reason = TextInput(label="Enter a reason", placeholder="<Insert your reason here>", default="No reason provided")

    def __init__(self, bot: Bot | PBot) -> None:
        super().__init__()
        self.bot: Bot | PBot = bot

    async def on_submit(self, interaction: Interaction) -> None:
        """Ban users on submit."""
        e: Embed = Embed(title="Users Banned", description="")
        e.add_field(name="reason", value=self.reason.value)

        targets = [int(i.strip()) for i in self.ban_list.value.split('\n') if i]

        async def ban_user(identifier: str) -> str:
            """Attempt to ban user"""
            try:
                user = await self.bot.fetch_user(int(identifier))
            except NotFound:
                return f"No user exists with ID# {identifier}"
            except ValueError:
                return f"{identifier} is not a valid user ID"

            try:
                await self.bot.http.ban(identifier, interaction.guild.id)
            except HTTPException:
                return f"🚫 Could not ban {user.mention} (#{identifier})."
            else:
                return f'☠ {user.mention} was banned (#{identifier})'

        e.description = '\n'.join([await ban_user(i) for i in targets])
        await self.bot.reply(interaction, embed=e)


class BanCog(Cog):
    """Single Command Cog for managing user bans"""

    def __init__(self, bot: Bot | PBot) -> None:
        self.bot = bot

    @command()
    @default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def ban(self, interaction: Interaction):
        """Bans a list of user IDs"""
        await interaction.response.send_modal(BanModal(self.bot))

    @command()
    @describe(name="Search by name")
    @default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def banlist(self, interaction: Interaction, name: str = None) -> Message:
        """Show the ban list for the server"""
        await interaction.response.defer(thinking=True)

        # Exhaust All Bans.
        if not (bans := [i async for i in interaction.guild.bans()]):
            return await self.bot.error(interaction, f"{interaction.guild.name} has no bans!")

        if name is not None:
            if not (bans := [i for i in bans if name in i.user.name]):
                return await self.bot.error(interaction, f"No bans found matching {name}")
        return await BanView(interaction, bans).update()


async def setup(bot) -> None:
    """Load the Cog into the bot"""
    await bot.add_cog(BanCog(bot))
