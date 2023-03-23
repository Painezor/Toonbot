"""Generic Objects for discord Views"""
from __future__ import annotations

import traceback
import logging
from dataclasses import dataclass
from typing import Callable, Any, Optional

from ext.utils import embed_utils

import discord
import typing

if typing.TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot


logger = logging.getLogger("view_utils")


class BaseView(discord.ui.View):
    """Error Handler."""

    update: Callable

    def __init__(
        self,
        interaction: discord.Interaction[Bot | PBot],
        *,
        parent: Optional[FuncButton] = None,
        timeout: int = 180,
    ):

        self.bot: Bot | PBot = interaction.client
        self.interaction: discord.Interaction[Bot | PBot] = interaction

        self.index: int = 0
        self.pages: list[Any] = []
        self.parent: Optional[FuncButton] = parent

        if parent is not None:
            if not parent.label:
                parent.label = "Back"
            if not parent.emoji:
                parent.emoji = "🔼"

        self.value: list[str] = []

        super().__init__(timeout=timeout)

    async def interaction_check(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> bool:
        """Make sure only the person running the command can select options"""
        return self.interaction.user.id == interaction.user.id

    async def on_timeout(self) -> Optional[discord.InteractionMessage]:
        """Cleanup"""
        edit = self.interaction.edit_original_response
        try:
            return await edit(view=None)
        except discord.NotFound:
            pass  # Shhhhhhh.

    def add_page_buttons(self, row: int = 0) -> None:
        """Helper function to bulk add page buttons (Prev, Jump, Next, Stop)"""
        # Clear Old Items on our row.
        [self.remove_item(i) for i in self.children if i.row == row]

        if self.parent:
            self.parent.row = row
            self.add_item(self.parent)

        if len(self.pages) > 1:
            self.add_item(Previous(self, row))
            self.add_item(Jump(self, row))
            self.add_item(Next(self, row))
        self.add_item(Stop(row))

    def add_function_row(
        self,
        items: list[Funcable],
        row: int = 0,
        placeholder: str = "More Options...",
        force_dropdown: bool = False,
    ):
        """Create a row of up to 5 Buttons,
        or a dropdown up to 25 options"""

        if len(items) > 25:
            raise ValueError("Too many for dropdown (%s > 25", len(items))

        if len(items) < 6 and not force_dropdown:
            for x in items:
                f = FuncButton(x.function, x.args, x.keywords, label=x.label)
                f.row = row
                f.disabled = x.disabled
                f.style = x.style
                f.emoji = x.emoji
                self.add_item(f)
        else:
            self.add_item(FuncSelect(items, row, placeholder))

    async def on_error(
        self, _: discord.Interaction[Bot], error: Exception, item
    ) -> typing.Optional[discord.InteractionMessage]:
        """Log the stupid fucking error"""
        logger.error(error)
        logger.error("This error brought to you by item %s", item)
        traceback.print_exc()
        r = self.interaction.edit_original_response
        txt = f"Something broke\n```py\n{error}```"
        try:
            return await r(content=txt, embed=None)
        except discord.NotFound:
            self.stop()


class First(discord.ui.Button):
    """Get the first item in a Pagination View"""

    view: BaseView

    def __init__(self, row: int = 0) -> None:
        super().__init__(emoji="⏮", row=row)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = 0
        return await self.view.update()


class Previous(discord.ui.Button):
    """Get the previous item in a Pagination View"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        d = getattr(view, "index", 0) == 0
        super().__init__(emoji="◀", row=row, disabled=d)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """Do this when button is pressed"""

        await interaction.response.defer()
        try:
            self.view.index = max(self.view.index - 1, 0)
        except AttributeError:
            self.view.index = 0
        return await self.view.update()


class Jump(discord.ui.Button):
    """Jump to a specific page in a Pagination view"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0):
        # Super Init first so we can access the view's properties.
        super().__init__(style=discord.ButtonStyle.blurple, emoji="🔎", row=row)

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

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """When button is clicked…"""
        return await interaction.response.send_modal(JumpModal(self.view))


class JumpModal(discord.ui.Modal):
    """Type page number in box, set index to that page."""

    page = discord.ui.TextInput(label="Enter a page number")

    def __init__(self, view: BaseView, title: str = "Jump to page") -> None:
        super().__init__(title=title)
        self.view = view
        self.page.placeholder = f"1 - {len(view.pages)}"

    async def on_submit(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
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


class Next(discord.ui.Button):
    """Get the next item in a Pagination View"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        pg_len = len(view.pages)
        d = view.index + 1 >= pg_len
        super().__init__(emoji="▶", row=row, disabled=d)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """Do this when button is pressed"""

        await interaction.response.defer()
        if self.view.index + 1 < len(self.view.pages):
            self.view.index += 1
        return await self.view.update()


class Last(discord.ui.Button):
    """Get the last item in a Pagination View"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        super().__init__(label="Last", emoji="⏭", row=row)
        pg_len = len(view.pages)
        self.disabled = pg_len == view.index

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """Do this when button is pressed"""

        await interaction.response.defer()
        self.view.index = len(getattr(self.view, "pages", []))
        return await self.view.update()


class Stop(discord.ui.Button):
    """A generic button to stop a View"""

    view: BaseView

    def __init__(self, row=3) -> None:
        super().__init__(emoji="🚫", row=row)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """Do this when button is pressed"""
        await interaction.response.defer()
        try:
            await self.view.interaction.delete_original_response()
        except discord.NotFound:
            pass

        # Handle any cleanup.
        await self.view.on_timeout()

        self.view.stop()


class PageSelect(discord.ui.Select):
    """Page Selector Dropdown"""

    view: BaseView

    def __init__(
        self,
        placeholder: Optional[str] = None,
        options: list = [],
        row: int = 4,
    ) -> None:
        super().__init__(placeholder=placeholder, options=options, row=row)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> discord.InteractionMessage:
        """Set View Index"""

        await interaction.response.defer()
        self.view.index = int(self.values[0]) - 1
        self.view.remove_item(self)
        return await self.view.update()


class ItemSelect(discord.ui.Select):
    """A Select that sets the view value to one selected item"""

    view: BaseView

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.values
        self.view.stop()


class AdditiveItemSelect(discord.ui.Select):

    view: PagedItemSelect

    def __init__(
        self, options: list[discord.SelectOption], row: int = 1
    ) -> None:
        super().__init__(max_values=len(options), row=row, options=options)

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """Response object for view"""
        await interaction.response.defer()

        for i in self.options:
            if i.value in self.view.values and i.value not in self.values:
                self.view.values.remove(i.value)
            elif i.value not in self.view.values and i.value in self.values:
                self.view.values.add(i.value)


class PagedItemSelect(BaseView):
    def __init__(
        self,
        interaction: discord.Interaction[Bot | PBot],
        items: list[discord.SelectOption],
        timeout: int = 30,
    ):
        super().__init__(interaction, timeout=timeout)

        self.values: set[str] = set()
        self.items: list[discord.SelectOption] = items

    async def update(self) -> discord.InteractionMessage:
        self.clear_items()
        self.pages = embed_utils.paginate(self.items, 25)
        items = self.pages[self.index]

        # Set Defaults based on whether it has been selected.
        for i in items:
            i.default = i.value in self.values

        self.add_item(AdditiveItemSelect(items, row=0))
        self.add_page_buttons(1)
        self.add_item(ConfirmMultiple(2))

        return await self.interaction.edit_original_response(view=self)


class ConfirmMultiple(discord.ui.Button):

    view: PagedItemSelect

    def __init__(self, row: int = 2):
        super().__init__(style=discord.ButtonStyle.primary, label="Save")
        self.row = row

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        await interaction.response.defer()
        self.view.stop()


@dataclass
class Funcable:
    """A 'Selectable Function' to be used with generate_function_row to
    create either a FuncSelect or row of FuncButtons"""

    def __init__(
        self,
        label: str,
        function: Callable,
        args: list = [],
        keywords: dict = {},
        emoji: Optional[str] = "🔘",
        description: Optional[str] = None,
        style: discord.ButtonStyle = discord.ButtonStyle.gray,
        disabled: bool = False,
    ):

        self.label: str = label
        self.emoji: Optional[str] = emoji
        self.description: Optional[str] = description
        self.style: discord.ButtonStyle = style
        self.disabled: bool = disabled

        self.function: Callable = function
        self.args: list = [] if args is None else args
        self.keywords: dict = {} if keywords is None else keywords


class FuncSelect(discord.ui.Select):
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

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> Any:
        """The handler for the FuncSelect Dropdown"""

        await interaction.response.defer()
        value: Funcable = self.items[self.values[0]]
        return await value.function(*value.args, **value.keywords)


class FuncButton(discord.ui.Button):
    """A Generic Button with a passed through function."""

    def __init__(
        self,
        function: Callable,
        args: list = [],
        kw: dict = {},
        **kwargs,
    ) -> None:

        super().__init__(**kwargs)

        self.function: Callable = function
        self.args: list = args
        self.kwargs: dict = kw

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """The Callback performs the passed function with any passed
        args/kwargs"""
        await interaction.response.defer()
        return await self.function(*self.args, **self.kwargs)


class Paginator(BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(
        self,
        interaction: discord.Interaction[Bot | PBot],
        embeds: list[discord.Embed],
    ) -> None:
        super().__init__(interaction)

        self.pages = embeds

    async def update(
        self, content: Optional[str] = None
    ) -> discord.InteractionMessage:
        """Refresh the view and send to user"""
        self.clear_items()
        self.add_page_buttons()
        e = self.pages[self.index]

        r = self.interaction.edit_original_response
        return await r(content=content, embed=e, view=self)


class Confirmation(BaseView):
    """Ask the user if they wish to confirm an option."""

    def __init__(
        self,
        interaction: discord.Interaction[Bot | PBot],
        label_a: str = "Yes",
        label_b: str = "No",
        style_a: discord.ButtonStyle = discord.ButtonStyle.grey,
        style_b: discord.ButtonStyle = discord.ButtonStyle.grey,
    ) -> None:

        super().__init__(interaction)

        self.add_item(BoolButton(label_a, style_a))
        self.add_item(BoolButton(label_b, style_b, value=False))

        self.value: bool


class BoolButton(discord.ui.Button):
    """Set View value"""

    view: Confirmation

    def __init__(
        self,
        label: str = "Yes",
        style: discord.ButtonStyle = discord.ButtonStyle.gray,
        value: bool = True,
    ) -> None:

        super().__init__(label=label, style=style)
        self.value: bool = value

    async def callback(
        self, interaction: discord.Interaction[Bot | PBot]
    ) -> None:
        """On Click Event"""
        await interaction.response.defer()
        self.view.value = self.value
        self.view.stop()
