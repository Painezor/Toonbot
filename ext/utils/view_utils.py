"""Generic Objects for discord Views"""
# Generic Buttons
import typing
from typing import Iterable, List, Callable, Tuple

import discord


class PreviousButton(discord.ui.Button):
    """Previous Button for Pagination Views"""

    def __init__(self, row=0):
        super().__init__()
        self.label = "Previous"
        self.emoji = "⏮"
        self.row = row

    async def callback(self, interaction: discord.Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = self.view.index - 1 if self.view.index > 0 else self.view.index
        await self.view.update()


class PageButton(discord.ui.Button):
    """Button to spawn a dropdown to select pages."""

    def __init__(self, row=0):
        super().__init__()
        self.label = f"Populating..."
        self.emoji = "⏬"
        self.row = row
        self.style = discord.ButtonStyle.primary

    async def callback(self, interaction: discord.Interaction):
        """The pages button."""
        await interaction.response.defer()
        if len(self.view.pages) < 25:
            sliced = self.view.pages
        else:
            if self.view.index < 13:
                sliced = self.view.pages[24:]
            elif self.view.index > len(self.view.pages) - 13:
                sliced = self.view.pages[:24]
            else:
                sliced = self.view.pages[self.view.index - 12:self.view.index + 12]
        options = [discord.SelectOption(label=f"Page {n}", value=str(n)) for n, e in enumerate(sliced, start=1)]
        self.view.add_item(PageSelect(placeholder="Select A Page", options=options, row=self.row + 1))
        self.disabled = True
        await self.view.message.edit(view=self.view)


class NextButton(discord.ui.Button):
    """Get next item in a view's pages"""

    def __init__(self, row=0):
        super().__init__()
        self.label = "Next"
        self.emoji = "⏭"
        self.row = row

    async def callback(self, interaction: discord.Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index += 1 if self.view.index < len(self.view.pages) else self.view.index
        await self.view.update()


class StopButton(discord.ui.Button):
    """A generic button to stop a View"""

    def __init__(self, row=3):
        super().__init__()
        self.label = "Hide"
        self.emoji = "🚫"
        self.row = row

    async def callback(self, interaction: discord.Interaction):
        """Do this when button is pressed"""
        await self.view.message.delete()
        self.view.stop()


# Dropdowns
class PageSelect(discord.ui.Select):
    """Page Selector Dropdown"""

    def __init__(self, placeholder=None, options=None, row=4):
        super().__init__(placeholder=placeholder, options=options)
        self.row = row

    async def callback(self, interaction):
        """Set View Index """
        await interaction.response.defer()
        self.view.index = int(self.values[0]) - 1
        self.view.remove_item(self)
        await self.view.update()


class ObjectSelectView(discord.ui.View):
    """Generic Object Select and return"""

    def __init__(self, owner, objects: list, timeout=180):
        self.owner = owner
        self.value = None  # As Yet Unset
        self.index = 0
        self.message = None
        self.dropdown = None
        self.objects = objects
        self.pages = [self.objects[i:i + 25] for i in range(0, len(self.objects), 25)]
        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.owner.id

    async def update(self):
        """Send new version of view to user"""
        self.clear_items()

        _ = PreviousButton(row=1)
        _.disabled = True if self.index == 0 else False
        self.add_item(_)

        _ = PageButton(row=1)
        _.label = f"Page {self.index + 1} of {len(self.pages)}"
        self.add_item(_)

        _ = NextButton(row=1)
        _.disabled = True if self.index == len(self.pages) - 1 else False
        self.add_item(_)

        _ = ItemSelect(placeholder="Select Matching Item...", options=self.pages[0])
        _.label = f"Page {self.index + 1} of {len(self.pages)}"
        _.row = 0
        self.add_item(_)

        self.add_item(StopButton(row=1))
        await self.message.edit(view=self)

    async def on_timeout(self):
        """Cleanup"""
        try:
            await self.message.delete()
        except discord.NotFound:
            pass
        self.stop()


class MultipleSelect(discord.ui.Select):
    """Select multiple matching items."""
    def __init__(self, placeholder, options: Iterable[Tuple[str, str, str]], attribute):
        self.attribute = attribute

        super().__init__(placeholder=placeholder, max_values=len(list(options)))
        for emoji, label, description in options:
            self.add_option(label=label, emoji=emoji, description=description, value=label)

    async def callback(self, interaction):
        """When selected assign view's requested attribute to values of selection."""
        await interaction.response.defer()
        setattr(self.view, self.attribute, self.values)
        self.view.index = 0
        await self.view.update()


class ItemSelect(discord.ui.Select):
    """A Dropdown That Returns a Generic Selected Item"""

    def __init__(self, placeholder, options: List[Tuple[str, str, str]]):
        super().__init__(placeholder=placeholder)
        for index, (emoji, label, description) in enumerate(options):
            self.add_option(emoji=emoji, label=label, description=description, value=str(index))

    async def callback(self, interaction):
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.view.index * 25 + int(self.values[0])
        self.view.stop()
        await self.view.message.delete()


class Button(discord.ui.Button):
    """A Generic Button with a passed through function."""

    def __init__(self,
                 label: str,
                 func: Callable,
                 emoji: str = None,
                 style: discord.ButtonStyle = discord.ButtonStyle.secondary,
                 row: int = 2,
                 disabled: bool = False):
        super().__init__()
        self.label = label
        self.emoji = emoji
        self.style = style
        self.func = func
        self.row = row
        self.disabled = disabled

    async def callback(self, interaction: discord.Interaction):
        """A Generic Callback"""
        await interaction.response.defer()
        await self.func()


class Paginator(discord.ui.View):
    """Generic Paginator that returns nothing."""

    def __init__(self, author: typing.Union[discord.Member, discord.User], embeds: typing.List[discord.Embed]):
        super().__init__()
        self.index = 0
        self.pages = embeds
        self.author = author
        self.message = None

    async def on_timeout(self):
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        self.stop()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.author.id == interaction.user.id

    async def update(self):
        """Refresh the view and send to user"""
        self.generate_buttons()
        await self.message.edit(content="", embed=self.pages[self.index], view=self,
                                allowed_mentions=discord.AllowedMentions.none())
        await self.wait()

    def generate_buttons(self):
        """Add buttons to the Team embed."""
        self.clear_items()

        _ = PreviousButton()
        _.disabled = True if self.index == 0 else False
        self.add_item(_)

        _ = PageButton()
        _.label = f"Page {self.index + 1} of {len(self.pages)}"
        _.disabled = True if len(self.pages) == 1 else False
        self.add_item(_)

        _ = NextButton()
        _.disabled = True if self.index == len(self.pages) - 1 else False
        self.add_item(_)
        self.add_item(StopButton(row=0))


class ChannelPicker(discord.ui.View):
    """Container View for Channel Select Dropdown"""

    def __init__(self, owner: discord.User, channels):
        super().__init__()
        self.owner = owner
        self.value = None
        self.add_item(ChannelSelect(channels))

    async def interaction_check(self, interaction: discord.Interaction):
        """Verify only invoker of command can use the buttons."""
        return interaction.user.id == self.owner.id


class ChannelSelect(discord.ui.Select):
    """Dropdown to pick a channel."""

    def __init__(self, channels):
        super().__init__(placeholder="Select a Channel...")
        for num, _ in enumerate(channels):
            self.add_option(label=_.name, emoji='#️⃣', description=_.topic, value=str(num))

    async def callback(self, interaction):
        """Upon Item Selection do this"""
        await interaction.response.defer()
        self.view.value = self.values[0]
        await self.view.message.delete()
        self.view.stop()


class Confirmation(discord.ui.View):
    """Ask the user if they wish to create a new ticker"""

    def __init__(self, owner: discord.User,
                 label_a: str = "Yes",
                 label_b: str = "No",
                 colour_a: discord.ButtonStyle = None,
                 colour_b: discord.ButtonStyle = None):
        super().__init__()
        self.message = None
        self.owner = owner
        self.add_item(BoolButton(label=label_a, colour=colour_a, value=True))
        self.add_item(BoolButton(label=label_b, colour=colour_b))
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction):
        """Verify only invoker of command can use the buttons."""
        return interaction.user.id == self.owner.id

    async def on_timeout(self) -> None:
        """Return nothing on timeout."""
        self.value = None
        try:
            await self.message.delete()
        except discord.HTTPException:
            pass
        self.stop()


class BoolButton(discord.ui.Button):
    """Set View value"""

    def __init__(self, label="Yes", colour: discord.ButtonStyle = None, value: bool = False):
        if colour is None:
            colour = discord.ButtonStyle.secondary
        super().__init__(label=label, style=colour)
        self.value = value

    async def callback(self, interaction):
        """On Click Event"""
        self.view.value = self.value
        try:
            await self.view.message.delete()
        except discord.HTTPException:
            pass
        self.view.stop()
