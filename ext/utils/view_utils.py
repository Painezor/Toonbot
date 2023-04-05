"""Generic Objects for discord Views"""
from __future__ import annotations

import dataclasses
import logging
import typing

import discord

from ext.utils import embed_utils

if typing.TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: typing.TypeAlias = discord.Interaction[Bot | PBot]


logger = logging.getLogger("view_utils")


class BaseView(discord.ui.View):
    """Error Handler."""

    update: typing.Callable
    message: discord.Message

    def __init__(
        self,
        *,
        parent: typing.Optional[FuncButton] = None,
        timeout: int = 180,
    ):

        self.index: int = 0
        self.pages: list[typing.Any] = []
        self.parent: typing.Optional[FuncButton] = parent

        if parent is not None:
            if not parent.label:
                parent.label = "Back"
            if not parent.emoji:
                parent.emoji = "🔼"

        self.value: list[str] = []

        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        """Make sure only the person running the command can select options"""
        if interaction.message is None:
            return False

        return interaction.message.author.id == interaction.user.id

    async def on_timeout(self) -> discord.Message:
        """Cleanup"""
        item: discord.ui.Item
        for item in self.children:
            item.disabled = True

        return await self.message.edit(view=self)

    def add_page_buttons(self, row: int = 0) -> None:
        """Helper function to bulk add page buttons (Prev, Jump, Next, Stop)"""
        # Clear Old Items on our row.
        for i in self.children:
            if i.row == row:
                self.remove_item(i)

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
            raise ValueError(f"Too many for dropdown: {len(items)} > 25")

        if len(items) < 6 and not force_dropdown:
            for i in items:
                fun = FuncButton(i.function, i.args, i.keywords, label=i.label)
                fun.row = row
                fun.disabled = i.disabled
                fun.style = i.style
                fun.emoji = i.emoji
                self.add_item(fun)
        else:
            self.add_item(FuncSelect(items, row, placeholder))

    async def on_error(
        self, interaction: Interaction, error: Exception, item, /
    ) -> typing.Optional[discord.InteractionMessage]:
        """Log the stupid fucking error"""
        logger.error("Error on view item %s", item, exc_info=True)
        edit = interaction.response.edit_message
        txt = f"Something broke\n```py\n{error}```"
        try:
            return await edit(content=txt, embed=None)
        except discord.NotFound:
            self.stop()


class First(discord.ui.Button):
    """Get the first item in a Pagination View"""

    view: BaseView

    def __init__(self, row: int = 0) -> None:
        super().__init__(emoji="⏮", row=row)

    async def callback(
        self, interaction: Interaction
    ) -> discord.InteractionMessage:
        """Do this when button is pressed"""
        await interaction.response.defer()
        self.view.index = 0
        return await self.view.update(interaction)


class Previous(discord.ui.Button):
    """Get the previous item in a Pagination View"""

    view: BaseView

    def __init__(self, view: BaseView, row: int = 0) -> None:
        disabled = getattr(view, "index", 0) == 0
        super().__init__(emoji="◀", row=row, disabled=disabled)

    async def callback(
        self, interaction: Interaction
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
        super().__init__(emoji="🔎", row=row)

        index = view.index
        pages = view.pages

        self.style = discord.ButtonStyle.blurple

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

    async def callback(self, interaction: Interaction) -> None:
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
        self, interaction: Interaction, /
    ) -> discord.InteractionMessage:
        """Validate entered data & set parent index."""

        await interaction.response.defer()

        pages: list = self.view.pages
        update: typing.Callable = getattr(self.view, "update")
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
        disabled = view.index + 1 >= pg_len
        super().__init__(emoji="▶", row=row, disabled=disabled)

    async def callback(
        self, interaction: Interaction
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
        self, interaction: discord.Interaction
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

    async def callback(self, interaction: discord.Interaction) -> None:
        """Do this when button is pressed"""
        await interaction.response.defer()
        try:
            await interaction.delete_original_response()
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
        placeholder: typing.Optional[str] = None,
        options: typing.Optional[list] = None,
        row: int = 4,
    ) -> None:
        if options is None:
            options = []
        super().__init__(placeholder=placeholder, options=options, row=row)

    async def callback(
        self, interaction: discord.Interaction
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

    async def callback(self, interaction: Interaction) -> None:
        """Response object for view"""
        await interaction.response.defer()
        self.view.value = self.values
        self.view.stop()


class AdditiveItemSelect(discord.ui.Select):
    """One page of a PagedItemSelect"""

    view: PagedItemSelect

    def __init__(
        self, options: list[discord.SelectOption], row: int = 1
    ) -> None:
        super().__init__(max_values=len(options), row=row, options=options)

    async def callback(self, interaction: Interaction) -> None:
        """Response object for view"""
        await interaction.response.defer()

        for i in self.options:
            if i.value in self.view.values and i.value not in self.values:
                self.view.values.remove(i.value)
            elif i.value not in self.view.values and i.value in self.values:
                self.view.values.add(i.value)


class PagedItemSelect(BaseView):
    """An Item Select with multiple dropdowns the user can cycle through"""

    def __init__(
        self,
        items: list[discord.SelectOption],
        timeout: int = 30,
    ):
        super().__init__(timeout=timeout)

        self.values: set[str] = set()
        self.items: list[discord.SelectOption] = items

    async def update(self, interaction: Interaction) -> None:
        """Send the latest version of the view to discord1`"""
        self.clear_items()
        self.pages = embed_utils.paginate(self.items, 25)
        items = self.pages[self.index]

        # Set Defaults based on whether it has been selected.
        for i in items:
            i.default = i.value in self.values

        self.add_item(AdditiveItemSelect(items, row=0))
        self.add_page_buttons(1)
        self.add_item(ConfirmMultiple(2))
        return await interaction.response.edit_message(view=self)


class ConfirmMultiple(discord.ui.Button):
    """Confirm the selection of items from multiple pages"""

    view: PagedItemSelect

    def __init__(self, row: int = 2):
        super().__init__(style=discord.ButtonStyle.primary, label="Save")
        self.row = row

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.view.stop()


@dataclasses.dataclass
class Funcable:
    """A 'Selectable Function' to be used with generate_function_row to
    create either a FuncSelect or row of FuncButtons"""

    def __init__(
        self,
        label: str,
        function: typing.Callable,
        args: typing.Optional[list] = None,
        keywords: typing.Optional[dict] = None,
        emoji: typing.Optional[str] = "🔘",
        description: typing.Optional[str] = None,
        style: discord.ButtonStyle = discord.ButtonStyle.gray,
        disabled: bool = False,
    ):

        self.label: str = label
        self.emoji: typing.Optional[str] = emoji
        self.description: typing.Optional[str] = description
        self.style: discord.ButtonStyle = style
        self.disabled: bool = disabled

        self.function: typing.Callable = function
        self.args: list = [] if args is None else args
        self.keywords: dict = {} if keywords is None else keywords


class FuncSelect(discord.ui.Select):
    """A Select that ties to individually passed functions"""

    def __init__(
        self,
        items: list[Funcable],
        row: int,
        placeholder: typing.Optional[str] = None,
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

    async def callback(self, interaction: Interaction) -> typing.Any:
        """The handler for the FuncSelect Dropdown"""
        await interaction.response.defer()
        value: Funcable = self.items[self.values[0]]
        return await value.function(*value.args, **value.keywords)


class FuncButton(discord.ui.Button):
    """A Generic Button with a passed through function."""

    def __init__(
        self,
        function: typing.Callable,
        args: typing.Optional[list] = None,
        kw: typing.Optional[dict] = None,
        **kwargs,
    ) -> None:

        super().__init__(**kwargs)

        self.function: typing.Callable = function
        self.args: list = [] if args is None else args
        self.kwargs: dict = {} if kw is None else kw

    async def callback(self, interaction: Interaction) -> None:
        """The Callback performs the passed function with any passed
        args/kwargs"""
        await interaction.response.defer()
        return await self.function(*self.args, **self.kwargs)


class Paginator(BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(self, embeds: list[discord.Embed]) -> None:
        super().__init__()

        self.pages = embeds

    async def update(
        self, interaction: Interaction, content: typing.Optional[str] = None
    ) -> None:
        """Refresh the view and send to user"""
        self.clear_items()
        self.add_page_buttons()
        embed = self.pages[self.index]

        edit = interaction.response.edit_message
        return await edit(content=content, embed=embed, view=self)


class Confirmation(BaseView):
    """Ask the user if they wish to confirm an option."""

    def __init__(
        self,
        label_a: str = "Yes",
        label_b: str = "No",
        style_a: discord.ButtonStyle = discord.ButtonStyle.grey,
        style_b: discord.ButtonStyle = discord.ButtonStyle.grey,
    ) -> None:

        super().__init__()

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

    async def callback(self, interaction: Interaction) -> None:
        """On Click Event"""
        await interaction.response.defer()
        self.view.value = self.value
        self.view.stop()
