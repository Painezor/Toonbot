"""Generic Objects for discord Views"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING, ClassVar, Any
from discord import ButtonStyle, NotFound, Embed, SelectOption
from discord.ui import Button, Select, Modal, View, TextInput

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot
    from discord import Message, Interaction


logger = logging.getLogger("view_utils")


class BaseView(View):
    """Error Handler."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_error(self, interaction: Interaction, error: Exception, item):
        """Log the stupid fucking error"""
        logger.error(f"{error}")
        logger.error(f"This error brought to you by item {item}")


def add_page_buttons(view: View, row: int = 0) -> View:
    """Helper function to bulk add page buttons (Prev, Jump, Next, Stop)"""
    if hasattr(view, "parent"):
        if view.parent:
            view.add_item(Parent())

    pages = len(getattr(view, 'pages', []))
    if pages > 1:
        view.add_item(Previous(view, row=row))
        view.add_item(Jump(view, row=row))

        n = Next(view, row=row)
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
        super().__init__(emoji="⏮", row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = 0
        return await self.view.update()


class Previous(Button):
    """Get the previous item in a Pagination View"""

    def __init__(self, view: View, row: int = 0) -> None:
        super().__init__(emoji="◀", row=row, disabled=getattr(view, 'index', 0) == 0)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        try:
            self.view.index = max(self.view.index - 1, 0)
        except AttributeError:
            self.view.index = 0
        return await self.view.update()


class Jump(Button):
    """Jump to a specific page in a Pagination view"""

    def __init__(self, view: View, row: int = 0):
        # Super Init first so we can access the view's properties.
        super().__init__(style=ButtonStyle.blurple, emoji='🔎', row=row)

        index = getattr(view, 'index', 0)
        pages = getattr(view, 'pages', [])

        try:
            iter(pages)
            self.label = f"{index + 1}/{len(pages)}"
        except TypeError:
            # View.pages is not Iterable
            self.label = f"{index + 1}/{pages}"
        except AttributeError:
            pass

        try:
            self.disabled = len(pages) < 3
        except AttributeError:
            self.disabled = True

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

        pages: list = getattr(self.view, "pages", [])
        update: Callable = getattr(self.view, "update")
        try:
            _ = pages[int(self.page.value)]
            self.view.index = int(self.page.value) - 1  # Humans index from 1
            return await update()
        except (ValueError, IndexError):  # Number was out of range.
            self.view.index = len(pages) - 1
            return await update()


class Next(Button):
    """Get the next item in a Pagination View"""

    def __init__(self, view: View, row: int = 0) -> None:
        super().__init__(emoji="▶", row=row, disabled=getattr(view, 'index', 0) + 1 >= len(getattr(view, 'pages', [])))

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        try:
            if self.view.index + 1 < len(self.view.pages):
                self.view.index += 1
        except AttributeError:
            self.view.index = 0
        return await self.view.update()


class Last(Button):
    """Get the last item in a Pagination View"""

    def __init__(self, view: View, row: int = 0) -> None:
        super().__init__(label="Last", emoji="⏭", row=row)
        self.disabled = len(getattr(view, "pages", [])) == getattr(view, "index", 0)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = len(getattr(self.view, "pages", []))
        return await self.view.update()


class Stop(Button):
    """A generic button to stop a View"""

    def __init__(self, row=3) -> None:
        super().__init__(emoji="🚫", row=row)

    async def callback(self, interaction: Interaction) -> None:
        """Do this when button is pressed"""
        try:
            await self.view.interaction.delete_original_response()
        except NotFound:
            pass
        except AttributeError:
            # For anything with a message instead.
            await self.view.message.delete()

        if (page := getattr(self.view, "page", None)) is not None and not page.isClosed():
            await page.close()
        self.view.stop()


class PageSelect(Select):
    """Page Selector Dropdown"""

    def __init__(self, placeholder: str = None, options: list = None, row: int = 4) -> None:
        super().__init__(placeholder=placeholder, options=options, row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Set View Index"""
        await interaction.response.defer()
        self.view.index = int(self.values[0]) - 1
        self.view.remove_item(self)
        return await self.view.update()


class ObjectSelectView(BaseView):
    """Generic Object Select and return"""
    def __init__(self, interaction: Interaction, objects: list[Any], timeout: int = 180) -> None:
        self.interaction: Interaction = interaction
        self.value: Any = None  # As Yet Unset
        self.index: int = 0
        self.objects: list = objects
        self.pages: list[list[Any]] = [self.objects[i:i + 25] for i in range(0, len(self.objects), 25)]
        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Assure only the command's invoker can select a result"""
        return interaction.user.id == self.interaction.user.id

    def embed(self) -> Embed:
        """Embeds look prettier, ok?"""
        e = Embed()
        e.set_author(name="Use the dropdown below")
        e.description = "\n".join([i[1] for i in self.pages[self.index]])
        return e

    async def update(self, content: str = None) -> Message:
        """Send new version of view to user"""
        self.clear_items()
        add_page_buttons(self, row=1)
        self.add_item(ItemSelect(placeholder="Select Matching Item…", options=self.pages[0]))
        bot: Bot = self.interaction.client
        return await bot.reply(self.interaction, content=content, view=self, embed=self.embed)

    async def on_timeout(self) -> Message:
        """Cleanup"""
        self.clear_items()
        self.stop()
        bot: Bot = self.interaction.client
        return await bot.error(self.interaction, "Timed out waiting for you to select a match.", followup=False)


class MultipleSelect(Select):
    """Select multiple matching items."""

    def __init__(self, placeholder: str, options: list[tuple[str, str, str]], attribute: str, row: int = 0) -> None:
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

    def __init__(self, placeholder: str, options: list[tuple[str, str, str]], row: int = 0) -> None:
        super().__init__(placeholder=placeholder)
        self.row = row
        for index, (emoji, label, description) in enumerate(options):
            self.add_option(emoji=emoji, label=label, description=description[:100], value=str(index))

    async def callback(self, interaction: Interaction) -> None:
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.view.index * 25 + int(self.values[0])
        self.view.stop()


@dataclass
class Funcable:
    """A 'Selectable Function' to be used with generate_function_row to create either a FuncDropdown
    or row of FuncButtons"""
    def __init__(self, label: str, function: Callable, args: list = None, kw: dict = None, emoji: str = None,
                 description: str = None, style: ButtonStyle = None, disabled: bool = False):

        self.label: str = label
        self.emoji: str = emoji
        self.description: str = description
        self.style: ButtonStyle = ButtonStyle.gray if style is None else style
        self.disabled: bool = disabled

        self.function: Callable = function
        self.args: list = [] if args is None else args
        self.kw: dict = {} if kw is None else kw


def generate_function_row(view: View, items: list[Funcable], row: int = 0, placeholder: str = None):
    """A very ugly method that will create a row of up to 5 Buttons, or a dropdown up to 25 buttons"""
    if len(items) > 25:
        raise ValueError('Too many items')
    if len(items) < 6:
        for x in items:
            view.add_item(FuncButton(x.label, x.function, x.args, x.kw, disabled=x.disabled, row=row, emoji=x.emoji,
                                     style=x.style))
    else:
        view.add_item(FuncSelect(items, row, placeholder))


class FuncSelect(Select):
    """A Select that ties to individually passed functions"""

    def __init__(self, items: list[Funcable], row: int, placeholder: str = None):
        self.items: dict[str, Funcable] = {}

        super().__init__(row=row, placeholder=placeholder)

        for num, i in enumerate(items):
            self.items[str(num)] = i
            self.add_option(label=i.label, emoji=i.emoji, description=i.description, value=str(num))

    async def callback(self, interaction: Interaction) -> Any:
        """The handler for the FuncSelect Dropdown"""
        await interaction.response.defer()
        value: Funcable = self.items[self.values[0]]
        return await value.function(*value.args, **value.kw)


class FuncButton(Button):
    """A Generic Button with a passed through function."""

    def __init__(self, label: str, func: Callable, args: list = None, kw: dict = None, **kwargs) -> None:
        super().__init__(label=label, **kwargs)

        self.func: Callable = func
        self.args: list = [] if args is None else args
        self.kwargs: dict = {} if kw is None else kw

    async def callback(self, interaction: Interaction) -> None:
        """The Callback performs the passed function with any passed args/kwargs"""
        await interaction.response.defer()
        return await self.func(*self.args, **self.kwargs)


# TODO: Deprecate FuncDropdown in favour of Funcable and generate_function_row
class FuncDropdown(Select):
    """Perform function based on user's dropdown choice"""

    # Passed List of [Select Option, Dict of args to setattr, Function to apply.]

    def __init__(self, options: list[tuple[SelectOption, dict, Callable]],
                 placeholder: str = None, row: int = 3) -> None:
        self.raw = options
        super().__init__(placeholder=placeholder, options=[o[0] for o in options][:25], row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Set View Index"""
        await interaction.response.defer()

        for k, v in self.raw[index := int(self.values[0])][1].items():
            setattr(self.view, k, v)
        return await self.raw[index][2]()


class Paginator(BaseView):
    """Generic Paginator that returns nothing."""
    bot: ClassVar[Bot | PBot] = None

    def __init__(self, interaction: Interaction, embeds: list[Embed]) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.pages: list[Embed] = embeds
        self.index: int = 0
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


class Confirmation(BaseView):
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
        super().__init__(label=label, style=ButtonStyle.secondary if colour is None else colour)
        self.value: bool = value

    async def callback(self, interaction: Interaction) -> None:
        """On Click Event"""
        self.view.value = self.value
        self.view.stop()
