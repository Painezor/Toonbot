"""Generic Objects for discord Views"""
from __future__ import annotations

from typing import Iterable, List, Callable, Tuple, TYPE_CHECKING, Dict, ClassVar

from discord import Interaction, ButtonStyle, NotFound, Embed, Message, SelectOption
from discord.ui import Button, Select, Modal, View, TextInput
from pyppeteer.page import Page

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


def add_page_buttons(view: View, row: int = 0) -> View:
    """Helper function to bulk add page buttons"""
    if hasattr(view, "parent"):
        if view.parent:
            view.add_item(Parent())

    index = getattr(view, "index", 1)
    pages = len(getattr(view, "pages", []))

    if pages > 1:
        p = Previous(row=row)
        p.disabled = index == 0
        view.add_item(p)

        j = Jump(row=row, label=f"Page {index + 1} of {pages}")
        j.disabled = pages < 3
        view.add_item(j)

        n = Next(row=row)
        n.disabled = index + 1 >= pages  # index 0 plus 1, len pages = 1
        view.add_item(n)
    view.add_item(Stop(row=row))
    return view


class Parent(Button):
    """If a view has a "parent" view, add a button to allow user to go to it."""

    def __init__(self, row: int = 0, label: str = "Back") -> None:
        super().__init__(label=label, emoji='⬆', row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """When clicked, call the parent view's update button"""
        return await self.view.parent.update()



class First(Button):
    """Get the first item in a Pagination View"""

    def __init__(self, row: int = 0) -> None:
        super().__init__(label="First", emoji="⏮", row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = 0
        return await self.view.update()


class Previous(Button):
    """Get the previous item in a Pagination View"""
    def __init__(self, row: int = 0) -> None:
        super().__init__(label="Previous", emoji="◀", row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = max(self.view.index - 1, 0)
        return await self.view.update()


class Jump(Button):
    """Jump to a specific page in a Pagination view"""
    def __init__(self, label: str = "Jump to page", row: int = 0):
        super().__init__(label=label, style=ButtonStyle.blurple, emoji='⤴', row=row)

    async def callback(self, interaction: Interaction) -> Modal:
        """When button is clicked…"""
        return await interaction.response.send_modal(JumpModal(self.view))


class JumpModal(Modal):
    """Type page number in box, set index to that page."""
    page = TextInput(label="Enter a page number")

    def __init__(self, view: View, title: str = "Jump to page") -> None:
        super().__init__(title=title)
        self.view = view
        pages = getattr(self.view, "pages")
        self.page.placeholder = f"1 - {len(pages)}"

    async def on_submit(self, interaction: Interaction) -> Message:
        """Validate entered data & set parent index."""
        await interaction.response.defer()

        pages: List = getattr(self.view, "pages", [])
        update: Callable = getattr(self.view, "update")
        try:
            _ = pages[int(self.page.value)]
            self.view.index = int(self.page.value)
            return await update()
        except ValueError:  # User did not enter a number.
            return await update(content="Invalid page selected.")
        except IndexError:  # Number was out of range.
            self.view.index = len(pages) - 1
            return await update()


class Next(Button):
    """Get the next item in a Pagination View"""

    def __init__(self, row: int = 0) -> None:
        super().__init__(label="Next", emoji="▶", row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        if self.view.index + 1 < len(self.view.pages):
            self.view.index += 1
        return await self.view.update()


class Last(Button):
    """Get the last item in a Pagination View"""

    def __init__(self, row: int = 0) -> None:
        super().__init__(label="Last", emoji="⏭", row=row)
        pages = getattr(self.view, "pages", [])
        index = getattr(self.view, "index", 0)
        if len(pages) == index:
            self.disabled = True

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = len(getattr(self.view, "pages", [None])) - 1  # -1 because List index from 0 vs human index 1
        return await self.view.update()


class Stop(Button):
    """A generic button to stop a View"""

    def __init__(self, row=3) -> None:
        super().__init__(label="Hide", emoji="🚫", row=row)

    async def callback(self, interaction: Interaction) -> None:
        """Do this when button is pressed"""
        try:
            await self.view.interaction.delete_original_message()
        except NotFound:
            pass

        page: Page = getattr(self.view, "page", None)
        if page is not None and not page.isClosed():
            await page.close()
        self.view.stop()


class PageSelect(Select):
    """Page Selector Dropdown"""

    def __init__(self, placeholder: str = None, options: List = None, row: int = 4) -> None:
        super().__init__(placeholder=placeholder, options=options, row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Set View Index"""
        await interaction.response.defer()
        self.view.index = int(self.values[0]) - 1
        self.view.remove_item(self)
        return await self.view.update()


class ObjectSelectView(View):
    """Generic Object Select and return"""
    bot: ClassVar[Bot] = None

    def __init__(self, interaction: Interaction, objects: list, timeout: int = 180) -> None:
        self.interaction: Interaction = interaction
        self.value = None  # As Yet Unset
        self.index: int = 0
        self.objects: list = objects
        self.pages = [self.objects[i:i + 25] for i in range(0, len(self.objects), 25)]

        if self.__class__.bot is None:
            self.__class__.bot = interaction.client

        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    @property
    def embed(self) -> Embed:
        """Embeds look prettier, ok?"""
        e: Embed = Embed(title="Use the dropdown below to select from the following list.")
        e.set_author(name="Multiple results found")
        e.description = "\n".join([i[1] for i in self.pages[self.index]])
        return e

    async def update(self, content: str = None) -> Message:
        """Send new version of view to user"""
        self.clear_items()

        add_page_buttons(self, row=1)

        _ = ItemSelect(placeholder="Select Matching Item…", options=self.pages[0])
        _.label = f"Page {self.index + 1} of {len(self.pages)}"
        self.add_item(_)
        self.add_item(Stop(row=1))
        return await self.bot.reply(self.interaction, content=content, view=self, embed=self.embed)

    async def on_timeout(self) -> Message:
        """Cleanup"""
        self.clear_items()
        err = "Timed out waiting for you to select a match."
        self.stop()
        return await self.bot.error(self.interaction, err, followup=False)


class MultipleSelect(Select):
    """Select multiple matching items."""

    def __init__(self, placeholder: str, options: Iterable[Tuple[str, str, str]], attribute: str, row: int = 0) -> None:
        self.attribute = attribute

        super().__init__(placeholder=placeholder, max_values=len(list(options)), row=row)
        for emoji, label, description in options:
            self.add_option(label=label, emoji=emoji, description=description[:100], value=label)

    async def callback(self, interaction: Interaction) -> Message:
        """When selected assign view's requested attribute to value of selection."""
        await interaction.response.defer()
        setattr(self.view, self.attribute, self.values)
        self.view.index = 0
        return await self.view.update()


class ItemSelect(Select):
    """A Dropdown That Returns a Generic Selected Item"""

    def __init__(self, placeholder: str, options: list[Tuple[str, str, str]], row: int = 0) -> None:
        super().__init__(placeholder=placeholder)
        self.row = row
        for index, (emoji, label, description) in enumerate(options):
            self.add_option(emoji=emoji, label=label, description=description[:100], value=str(index))

    async def callback(self, interaction: Interaction) -> None:
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.view.index * 25 + int(self.values[0])
        self.view.stop()


class FuncButton(Button):
    """A Generic Button with a passed through function."""

    def __init__(self, label: str, func: Callable, kwargs: dict = None, emoji: str = None,
                 style: ButtonStyle = ButtonStyle.secondary, row: int = 2, disabled: bool = False) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row, disabled=disabled)
        self.func: Callable = func
        if kwargs is None:
            kwargs = dict()
        self.kwargs: dict = kwargs

    async def callback(self, interaction: Interaction) -> None:
        """A Generic Callback"""
        for k, v in self.kwargs.items():
            setattr(self.view, k, v)

        await interaction.response.defer()
        return await self.func()


class FuncDropdown(Select):
    """Perform function based on user's dropdown choice"""

    # Passed List of [Select Option, Dict of args to setattr, Function to apply.]

    def __init__(self, options: list[Tuple[SelectOption, Dict, Callable]],
                 placeholder: str = None, row: int = 3) -> None:
        self.raw = options
        super().__init__(placeholder=placeholder, options=[o[0] for o in options][:25], row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Set View Index"""
        await interaction.response.defer()

        index = int(self.values[0])
        for k, v in self.raw[index][1].items():
            setattr(self.view, k, v)

        return await self.raw[index][2]()


class Paginator(View):
    """Generic Paginator that returns nothing."""
    bot: ClassVar[Bot | PBot] = None

    def __init__(self, interaction: Interaction, embeds: list[Embed]) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.pages: list[Embed] = embeds
        self.index: int = 0

        if self.__class__.bot is None:
            self.__class__.bot = interaction.client

    async def on_timeout(self) -> Message:
        """Remove buttons and dropdowns when listening stops."""
        return await self.bot.reply(self.interaction, view=None, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.interaction.user.id == interaction.user.id

    async def update(self, content: str = None) -> Message:
        """Refresh the view and send to user"""
        self.clear_items()
        add_page_buttons(self)
        return await self.bot.reply(self.interaction, content=content, embed=self.pages[self.index], view=self)


class Confirmation(View):
    """Ask the user if they wish to confirm an option."""

    def __init__(self, interaction: Interaction, label_a: str = "Yes", label_b: str = "No",
                 colour_a: ButtonStyle = None, colour_b: ButtonStyle = None) -> None:
        super().__init__()
        self.interaction = interaction
        self.add_item(BoolButton(label=label_a, colour=colour_a))
        self.add_item(BoolButton(label=label_b, colour=colour_b, value=False))
        self.value = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify only invoker of command can use the buttons."""
        return interaction.user.id == self.interaction.user.id


class BoolButton(Button):
    """Set View value"""

    def __init__(self, label="Yes", colour: ButtonStyle = None, value: bool = True) -> None:
        if colour is None:
            colour = ButtonStyle.secondary
        super().__init__(label=label, style=colour)
        self.value: bool = value

    async def callback(self, interaction: Interaction) -> None:
        """On Click Event"""
        self.view.value = self.value
        self.view.stop()
