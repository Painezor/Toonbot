"""Cog for managing and bulk banning members"""
from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Embed, BanEntry, SelectOption, Colour, TextStyle, NotFound, HTTPException
from discord.app_commands import command, default_permissions, describe
from discord.app_commands.checks import bot_has_permissions
from discord.ext.commands import Cog
from discord.ui import Select, View, Modal, TextInput

from ext.utils.view_utils import add_page_buttons

if TYPE_CHECKING:
    from discord import Interaction, Message
    from core import Bot
    from painezBot import PBot


class BanView(View):
    """View to hold the BanList"""

    def __init__(self, interaction: Interaction, members: list[list[BanEntry]]) -> None:
        super().__init__()
        self.interaction = interaction
        self.message = None
        self.bot: Bot | PBot = interaction.client

        self.pages = members
        self.page = 0
        self.entries: dict[int, BanEntry] = {}  # discord id, BanEntry

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Make sure only the person running the command can select options"""
        return self.interaction.user.id == interaction.user.id

    @property
    def embed(self) -> Embed:
        """Generic Embed for this server"""
        e = Embed(title=f"{self.message.guild.name} bans", colour=Colour.blurple())
        e.set_thumbnail(url=self.message.guild.icon.url)
        return e

    async def update(self):
        """Refresh the view with the latest page"""
        # Clear Old items
        self.clear_items()

        page = self.pages[self.page]

        options = []
        self.entries.clear()

        e = self.embed.copy()
        strings = []
        for b in page:
            uid = str(b.user.id)
            options.append(SelectOption(label=f"{b.user}", description=f"User #{uid}", emoji="☠", value=uid))
            self.entries.update({b.user.id: b})
            strings += [f"`{b.user.id}`", b.user.mention, str(b.user)]
        e.description = "".join(strings)

        self.add_item(BanSelect(options))
        add_page_buttons(self, 1)
        return self.bot.reply(view=self, embed=e)

    async def unban(self, bans: list[str]):
        """Perform unbans on the entries passed back from the SelectOption"""
        entries = [self.entries[int(i)] for i in bans]

        e = Embed(colour=Colour.green(), title="The following users were unbanned")
        e.set_footer(text=f"Action performed by {self.interaction.user}")
        for ban in entries:
            await self.message.guild.unban(ban.user, reason=f"Requested by {self.interaction.user}")
            e.description += f"{ban.user} {ban.user.mention} ({ban.user.id})\n"

        return self.bot.reply(self.interaction, embed=e)


class BanSelect(Select):
    """Dropdown to unban members"""
    view: BanView

    def __init__(self, options: list[SelectOption]) -> None:
        super().__init__(placeholder="Unban members", max_values=len(options), options=options, row=0)

    async def callback(self, interaction: Interaction) -> Message:
        """When the select is triggered"""
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
    @describe(name="Search for a specific user in the ban list")
    @default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def banlist(self, interaction: Interaction, name: str = None) -> Message:
        """Show the ban list for the server"""

        bans: list[BanEntry] = []
        # Exhaust All Bans.
        async for ban in interaction.guild.bans():
            if name is not None and name not in ban.user.name:
                continue

            bans.append(ban)

        if not bans:
            return await self.bot.reply(interaction, f"{interaction.guild.name} has no bans!")

        pages = [bans[i:i + 25] for i in range(0, len(bans), 25)]
        return await BanView(interaction, pages).update()


async def setup(bot) -> None:
    """Load the Cog into the bot"""
    await bot.add_cog(BanCog(bot))
