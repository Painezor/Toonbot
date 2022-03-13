"""Generic Objects for discord Views"""
# Generic Buttons
import typing
from typing import Iterable, List, Callable, Tuple

from discord import Interaction, ButtonStyle, SelectOption, NotFound, Embed, Colour
from discord.ui import Button, Select, Modal, View, TextInput


class FirstButton(Button):
    """Previous Button for Pagination Views"""

    def __init__(self, disabled=False, row=0):
        super().__init__(label="First", emoji="⏮", row=row, disabled=disabled)

    async def callback(self, interaction: Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = 0
        await self.view.update()


class PreviousButton(Button):
    """Previous Button for Pagination Views"""

    def __init__(self, disabled=False, row=0):
        super().__init__(label="Previous", emoji="◀", row=row, disabled=disabled)

    async def callback(self, interaction: Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = self.view.index - 1 if self.view.index > 0 else self.view.index
        await self.view.update()


class PageButton(Button):
    """Button to spawn a dropdown to select pages."""

    def __init__(self, label="Jump to a page", disabled=False, row=0):
        super().__init__(emoji="⏬", label=label, row=row, disabled=disabled, style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        """The pages button."""
        await interaction.response.defer()

        if len(self.view.pages) < 25:
            sliced = self.view.pages
        else:
            if self.view.index < 13:
                sliced = self.view.pages[:24]
            elif self.view.index > len(self.view.pages) - 13:
                sliced = self.view.pages[24:]
            else:
                sliced = self.view.pages[self.view.index - 12:self.view.index + 12]
        options = [SelectOption(label=f"Page {n}", value=str(n)) for n, e in enumerate(sliced, start=1)]

        self.view.clear_items()
        self.view.add_item(PageSelect(placeholder="Select A Page", options=options, row=self.row))
        self.disabled = True

        await self.view.interaction.client.reply(self.view.interaction, view=self.view)


class NextButton(Button):
    """Get next item in a view's pages"""

    def __init__(self, disabled=False, row=0):
        super().__init__(label="Next", emoji="▶", row=row, disabled=disabled)

    async def callback(self, interaction: Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index += 1 if self.view.index < len(self.view.pages) else self.view.index
        await self.view.update()


class LastButton(Button):
    """Get the last item in a paginator."""

    def __init__(self, disabled=False, row=0):
        super().__init__(label="Last", emoji="⏭", row=row, disabled=disabled)

    async def callback(self, interaction: Interaction):
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = len(self.view.pages) - 1
        await self.view.update()


class StopButton(Button):
    """A generic button to stop a View"""

    def __init__(self, row=3):
        super().__init__(label="Hide", emoji="🚫", row=row)

    async def callback(self, interaction: Interaction):
        """Do this when button is pressed"""
        try:
            await self.view.intreaction.delete_original_message()
        except NotFound:
            pass

        if hasattr(self.view, "page"):
            await self.view.page.close()
        self.view.stop()


# Dropdowns
class PageSelect(Select):
    """Page Selector Dropdown"""

    def __init__(self, placeholder=None, options=None, row=4):
        super().__init__(placeholder=placeholder, options=options, row=row)

    async def callback(self, interaction):
        """Set View Index """
        await interaction.response.defer()
        self.view.index = int(self.values[0]) - 1
        self.view.remove_item(self)
        await self.view.update()


class JumpModal(Modal):
    """Type page number in box, set index to that page."""
    page = TextInput(label="Enter a page number")

    def __init__(self, view, title="Jump to page"):
        super().__init__(title=title)
        self.view = view
        self.page.placeholder = f"0 - {len(self.view.pages)}"

    async def on_submit(self, interaction):
        """Validate entered data & set parent index."""
        try:
            _ = self.view.pages[int(str(self.page))]
        except ValueError:  # User did not enter a number.
            await self.view.update(content="Invalid page selected.")
        except IndexError:  # Number was out of range.
            self.view.index = len(self.view.pages) - 1
            await self.view.update()


class ObjectSelectView(View):
    """Generic Object Select and return"""

    def __init__(self, interaction: Interaction, objects: list, timeout=180):
        self.interaction: Interaction = interaction
        self.value = None  # As Yet Unset
        self.index: int = 0
        self.objects: list = objects

        self.pages = [self.objects[i:i + 25] for i in range(0, len(self.objects), 25)]
        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction: Interaction):
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    @property
    def embed(self):
        """Embeds look prettier, ok?"""
        e = Embed(title="Use the dropdown below to select from the following list.")
        e.set_author(name="Multiple results found")
        e.description = "\n".join([i[1] for i in self.pages[self.index]])
        return e

    async def update(self, content=""):
        """Send new version of view to user"""
        self.clear_items()

        if len(self.pages) != 1:
            self.add_item(PreviousButton(row=1, disabled=True if self.index == 0 else False))
            self.add_item(PageButton(row=1, label=f"Page {self.index + 1} of {len(self.pages)}"))
            self.add_item(NextButton(row=1, disabled=True if self.index == len(self.pages) - 1 else False))

        _ = ItemSelect(placeholder="Select Matching Item...", options=self.pages[0])
        _.label = f"Page {self.index + 1} of {len(self.pages)}"
        self.add_item(_)

        self.add_item(StopButton(row=1))
        await self.interaction.client.reply(self.interaction, content=content, view=self, embed=self.embed)

    async def on_timeout(self):
        """Cleanup"""
        self.clear_items()
        e = Embed(colour=Colour.red(), description="Timed out waiting for you to select a match.")
        await self.interaction.client.error(self.interaction, embed=e, view=None, followup=False)
        self.stop()


class MultipleSelect(Select):
    """Select multiple matching items."""

    def __init__(self, placeholder, options: Iterable[Tuple[str, str, str]], attribute, row=0):
        self.attribute = attribute

        super().__init__(placeholder=placeholder, max_values=len(list(options)), row=row)
        for emoji, label, description in options:
            self.add_option(label=label, emoji=emoji, description=description, value=label)

    async def callback(self, interaction):
        """When selected assign view's requested attribute to value of selection."""
        await interaction.response.defer()
        setattr(self.view, self.attribute, self.values)
        self.view.index = 0
        await self.view.update()


class ItemSelect(Select):
    """A Dropdown That Returns a Generic Selected Item"""

    def __init__(self, placeholder, options: List[Tuple[str, str, str]], row=0):
        super().__init__(placeholder=placeholder)
        self.row = row
        for index, (emoji, label, description) in enumerate(options):
            if not label:
                print("Item Select [ERROR]: No label for passed object", index, emoji, label, description)
                continue
            self.add_option(emoji=emoji, label=label, description=description, value=str(index))

    async def callback(self, interaction):
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.view.index * 25 + int(self.values[0])
        self.view.stop()


class FuncButton(Button):
    """A Generic Button with a passed through function."""

    def __init__(self, label: str, func: Callable, emoji: str = None,
                 style: ButtonStyle = ButtonStyle.secondary, row: int = 2, disabled: bool = False):
        super().__init__(label=label, emoji=emoji, style=style, row=row, disabled=disabled)
        self.func = func

    async def callback(self, interaction: Interaction):
        """A Generic Callback"""
        await interaction.response.defer()
        await self.func()


class Paginator(View):
    """Generic Paginator that returns nothing."""

    def __init__(self, interaction: Interaction, embeds: typing.List[Embed]):
        super().__init__()
        self.index = 0
        self.pages = embeds
        self.interaction = interaction

    async def on_timeout(self):
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        await self.interaction.client.reply(self.interaction, view=self, followup=False)
        self.stop()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.interaction.user.id == interaction.user.id

    async def update(self, content=""):
        """Refresh the view and send to user"""
        self.clear_items()

        self.add_item(PreviousButton(disabled=True if self.index == 0 else False))
        self.add_item(PageButton(label=f"Page {self.index + 1} of {len(self.pages)}",
                                 disabled=True if len(self.pages) == 1 else False))
        self.add_item(NextButton(disabled=True if self.index == len(self.pages) - 1 else False))
        self.add_item(StopButton(row=0))

        await self.interaction.client.reply(self.interaction, content=content, embed=self.pages[self.index], view=self)


class Confirmation(View):
    """Ask the user if they wish to confirm an option."""

    def __init__(self, interaction: Interaction, label_a: str = "Yes", label_b: str = "No",
                 colour_a: ButtonStyle = None, colour_b: ButtonStyle = None):
        super().__init__()
        self.interaction = interaction
        self.add_item(BoolButton(label=label_a, colour=colour_a))
        self.add_item(BoolButton(label=label_b, colour=colour_b, value=False))
        self.value = None

    async def interaction_check(self, interaction: Interaction):
        """Verify only invoker of command can use the buttons."""
        return interaction.user.id == self.interaction.user.id


class BoolButton(Button):
    """Set View value"""

    def __init__(self, label="Yes", colour: ButtonStyle = None, value: bool = True):
        colour = ButtonStyle.secondary if colour is None else colour
        super().__init__(label=label, style=colour)
        self.value = value

    async def callback(self, interaction: Interaction):
        """On Click Event"""
        self.view.value = self.value
        self.view.stop()
