"""Generic Objects for discord Views"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING, Any, Optional
from discord import ButtonStyle, NotFound, Embed, SelectOption
from discord.ui import Button, Select, Modal, View, TextInput

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot
    from discord import Message, Interaction


logger = logging.getLogger("view_utils")


class BaseView(View):
    """Error Handler."""

    def __init__(self, interaction: Interaction[Bot | PBot], *args, **kwargs):

        self.bot = interaction.client
        self.interaction: Interaction[Bot | PBot] = interaction

        self.index: int = 0
        self.update: Callable
        self.pages: list[Any] = []
        self.parent: Optional[FuncButton] = kwargs.pop("parent", None)

        self.value: list[str] = []

        super().__init__(*args, **kwargs)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Make sure only the person running the command can select options"""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> None:
        """Cleanup"""
        await self.bot.reply(self.interaction, view=None, followup=False)

    def add_page_buttons(self, row: int = 0) -> None:
        """Helper function to bulk add page buttons (Prev, Jump, Next, Stop)"""
        if self.parent:
            self.add_item(self.parent)

        pages = len(self.pages)
        if pages > 1:
            self.add_item(Previous(self, row=row))
            self.add_item(Jump(self, row=row))

            n = Next(self, row=row)
            self.add_item(n)
        self.add_item(Stop(row=row))
        return

    def add_function_row(
        self,
        items: list[Funcable],
        row: int = 0,
        placeholder: str = "More Options...",
    ):
        """A very ugly method that will create a row of up to 5 Buttons,
        or a dropdown up to 25 buttons"""

        if len(items) > 25:
            raise ValueError("Too many items")

        if len(items) < 6:
            for x in items:
                f = FuncButton(x.label, x.function, x.args, x.keywords)
                f.row = row
                f.disabled = x.disabled
                f.style = x.style
                f.emoji = x.emoji
                self.add_item(f)
        else:
            self.add_item(FuncSelect(items, row, placeholder))

    async def on_error(self, ctx: Interaction[Bot], error: Exception, item):
        """Log the stupid fucking error"""
        logger.error(error)
        logger.error("This error brought to you by item %s", item)
        await ctx.client.reply(ctx, f"Something broke\n{error}")


class First(Button):
    """Get the first item in a Pagination View"""

    view: BaseView

    def __init__(self, row: int = 0) -> None:
        super().__init__(emoji="⏮", row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = 0
        return await self.view.update()


class Previous(Button):
    """Get the previous item in a Pagination View"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        d = getattr(view, "index", 0) == 0
        super().__init__(emoji="◀", row=row, disabled=d)

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

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0):
        # Super Init first so we can access the view's properties.
        super().__init__(style=ButtonStyle.blurple, emoji="🔎", row=row)

        index = view.index
        pages = view.pages

        try:
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

        self.view = view

    async def callback(self, interaction: Interaction[Bot | PBot]) -> None:
        """When button is clicked…"""
        return await interaction.response.send_modal(JumpModal(self.view))


class JumpModal(Modal):
    """Type page number in box, set index to that page."""

    page = TextInput(label="Enter a page number")

    def __init__(self, view: BaseView, title: str = "Jump to page") -> None:
        super().__init__(title=title)
        self.view = view
        self.page.placeholder = f"1 - {len(view.pages)}"

    async def on_submit(self, interaction: Interaction) -> Message:
        """Validate entered data & set parent index."""

        await interaction.response.defer()

        pages: list = self.view.pages
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

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        pg_len = len(view.pages)
        d = view.index + 1 >= pg_len
        super().__init__(emoji="▶", row=row, disabled=d)

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""

        await interaction.response.defer()
        if self.view.index + 1 < len(self.view.pages):
            self.view.index += 1
        return await self.view.update()


class Last(Button):
    """Get the last item in a Pagination View"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        super().__init__(label="Last", emoji="⏭", row=row)
        pg_len = len(view.pages)
        self.disabled = pg_len == view.index

    async def callback(self, interaction: Interaction) -> Message:
        """Do this when button is pressed"""

        await interaction.response.defer()
        self.view.index = len(getattr(self.view, "pages", []))
        return await self.view.update()


class Stop(Button):
    """A generic button to stop a View"""

    view: BaseView

    def __init__(self, row=3) -> None:
        super().__init__(emoji="🚫", row=row)

    async def callback(self, interaction: Interaction) -> None:
        """Do this when button is pressed"""
        try:
            await self.view.interaction.delete_original_response()
        except NotFound:
            pass
        self.view.stop()


class PageSelect(Select):
    """Page Selector Dropdown"""

    view: BaseView

    def __init__(
        self,
        placeholder: Optional[str] = None,
        options: list = [],
        row: int = 4,
    ) -> None:
        super().__init__(placeholder=placeholder, options=options, row=row)

    async def callback(self, interaction: Interaction) -> Message:
        """Set View Index"""

        await interaction.response.defer()
        self.view.index = int(self.values[0]) - 1
        self.view.remove_item(self)
        return await self.view.update()


class ItemSelect(Select):
    """A Select that sets the view value to one selected item"""

    view: BaseView

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: Interaction) -> None:
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.values
        self.view.stop()


@dataclass
class Funcable:
    """A 'Selectable Function' to be used with generate_function_row to
    create either a FuncDropdown or row of FuncButtons"""

    def __init__(
        self,
        label: str,
        function: Callable,
        args: list = [],
        keywords: dict = {},
        emoji: Optional[str] = None,
        description: Optional[str] = None,
        style: ButtonStyle = ButtonStyle.gray,
        disabled: bool = False,
    ):

        self.label: str = label
        self.emoji: Optional[str] = emoji
        self.description: Optional[str] = description
        self.style: ButtonStyle = style
        self.disabled: bool = disabled

        self.function: Callable = function
        self.args: list = [] if args is None else args
        self.keywords: dict = {} if keywords is None else keywords


class FuncSelect(Select):
    """A Select that ties to individually passed functions"""

    def __init__(
        self,
        items: list[Funcable],
        row: int,
        placeholder: Optional[str] = None,
    ):

        self.items: dict[str, Funcable] = {}

        super().__init__(row=row, placeholder=placeholder)

        for num, i in enumerate(items):
            self.items[str(num)] = i
            self.add_option(
                label=i.label,
                emoji=i.emoji,
                description=i.description,
                value=str(num),
            )

    async def callback(self, interaction: Interaction) -> Any:
        """The handler for the FuncSelect Dropdown"""

        await interaction.response.defer()
        value: Funcable = self.items[self.values[0]]
        return await value.function(*value.args, **value.keywords)


class FuncButton(Button):
    """A Generic Button with a passed through function."""

    def __init__(
        self,
        label: str,
        func: Callable,
        args: list = [],
        kw: dict = {},
        **kwargs,
    ) -> None:

        super().__init__(label=label, **kwargs)

        self.func: Callable = func
        self.args: list = args
        self.kwargs: dict = kw

    async def callback(self, interaction: Interaction) -> None:
        """The Callback performs the passed function with any passed
        args/kwargs"""

        await interaction.response.defer()
        return await self.func(*self.args, **self.kwargs)


# TODO: Deprecate FuncDropdown in favour of Funcable and generate_function_row
class FuncDropdown(Select):
    """Perform function based on user's dropdown choice"""

    # [Select Option, Dict of args to setattr, Function to apply.]

    def __init__(
        self,
        options: list[tuple[SelectOption, dict, Callable]],
        placeholder: Optional[str] = None,
        row: int = 3,
    ) -> None:

        self.raw = options
        super().__init__(
            placeholder=placeholder,
            options=[o[0] for o in options][:25],
            row=row,
        )

    async def callback(self, interaction: Interaction) -> Message:
        """Set View Index"""

        await interaction.response.defer()

        for k, v in self.raw[index := int(self.values[0])][1].items():
            setattr(self.view, k, v)
        return await self.raw[index][2]()


class Paginator(BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(
        self, interaction: Interaction[Bot | PBot], embeds: list[Embed]
    ) -> None:
        super().__init__(interaction)

    async def update(self, content: Optional[str] = None) -> Message:
        """Refresh the view and send to user"""
        self.clear_items()
        self.add_page_buttons()
        e = self.pages[self.index]
        return await self.bot.reply(
            self.interaction, content, embed=e, view=self
        )


class Confirmation(BaseView):
    """Ask the user if they wish to confirm an option."""

    def __init__(
        self,
        interaction: Interaction[Bot | PBot],
        label_a: str = "Yes",
        label_b: str = "No",
        style_a: ButtonStyle = ButtonStyle.grey,
        style_b: ButtonStyle = ButtonStyle.grey,
    ) -> None:

        super().__init__(interaction)

        self.add_item(BoolButton(label_a, style_a))
        self.add_item(BoolButton(label_b, style_b, value=False))

        self.value: bool


class BoolButton(Button):
    """Set View value"""

    view: Confirmation

    def __init__(
        self,
        label: str = "Yes",
        style: ButtonStyle = ButtonStyle.gray,
        value: bool = True,
    ) -> None:

        super().__init__(label=label, style=style)
        self.value: bool = value

    async def callback(self, interaction: Interaction) -> None:
        """On Click Event"""
        self.view.value = self.value
        self.view.stop()
