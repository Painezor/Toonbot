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

    User: typing.TypeAlias = discord.User | discord.Member


logger = logging.getLogger("view_utils")


class BaseView(discord.ui.View):
    """Error Handler."""

    message: discord.Message

    def __init__(
        self,
        invoker: User,
        *,
        parent: typing.Optional[BaseView] = None,
        timeout: typing.Optional[float] = 180,
    ):
        # User ID of the person who invoked the command.
        super().__init__(timeout=timeout)

        self.invoker: int = invoker.id
        self.index: int = 0

        self.parent = parent
        if parent is None:
            self.remove_item(self.parent_button)

    @discord.ui.button(label="Back", emoji="🔼")
    async def parent_button(self, interaction: Interaction, _) -> None:
        """Send Parent View"""
        assert self.parent is not None
        return await self.parent.entry_point(interaction)

    async def entry_point(self, interaction: Interaction):
        """Handle instantiation of a view from interaction alone"""
        await interaction.response.edit_message(view=self, embed=None)

    async def interaction_check(self, interaction: Interaction, /) -> bool:
        """Make sure only the person running the command can select options"""
        return interaction.user.id == self.invoker

    async def on_timeout(self) -> None:
        """Cleanup"""
        for i in self.children:
            i.disabled = True

        if self.message is None:
            logger.error("Message not set on view %s", self.__class__.__name__)
            return
        await self.message.edit(view=self)

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
    ) -> None:
        """Log errors"""
        logger.error("Error on view item %s", item, exc_info=True)
        edit = interaction.response.edit_message
        txt = f"Something broke\n```py\n{error}```"
        try:
            return await edit(content=txt, embed=None)
        except discord.NotFound:
            self.stop()


class JumpModal(discord.ui.Modal):
    """Type page number in box, set index to that page."""

    page = discord.ui.TextInput(label="Enter a page number")

    def __init__(self, view: Paginator, title: str = "Jump to page") -> None:
        super().__init__(title=title)
        self.view = view
        self.page.placeholder = f"1 - {len(view.pages)}"

    async def on_submit(self, interaction: Interaction, /) -> None:
        """Validate entered data & set parent index."""

        await interaction.response.defer()

        try:
            _ = self.view.pages[int(self.page.value)]
            self.view.index = int(self.page.value) - 1  # Humans index from 1
        except (ValueError, IndexError):  # Number was out of range.
            self.view.index = len(self.view.pages) - 1
        return await self.view.handle_page(interaction)


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


# TODO: AsyncPaginator
# TODO: AsyncDropdownPaginator
# TODO: Deperecate rows_to_embeds
# TODO: Stop() to decorator of baseview
class Paginator(BaseView):
    """A Paginator takes a list of Embeds and an Optional list of
    lists of SelectOptions. When a button is clicked, the page is changed
    and the embed at the current index is pushed. If a list of selects
    is also provided that matches the embed, the options are also updated"""

    def __init__(
        self,
        invoker: User,
        embeds: list[discord.Embed],
        *,
        parent: typing.Optional[BaseView] = None,
        timeout: typing.Optional[float] = None,
    ) -> None:
        super().__init__(invoker, parent=parent, timeout=timeout)

        self.pages = embeds

        if self.index + 1 > len(self.pages):
            self.next.disabled = True
        if self.index == 0:
            self.previous.disabled = True

        self.jump.label = f"{self.index + 1}/{len(self.pages)}"
        self.jump.disabled = len(self.pages) < 3

    async def entry_point(self, interaction: Interaction):
        embed = self.pages[self.index]
        await interaction.response.edit_message(view=self, embed=embed)
        self.message = await interaction.original_response()

    async def handle_page(self, interaction: Interaction) -> None:
        """Refresh the view and send to user"""
        embed = self.pages[self.index]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀️", row=0)
    async def previous(self, interaction: Interaction, _) -> None:
        """Go to previous page"""
        self.index = max(self.index - 1, 0)
        await self.handle_page(interaction)

    @discord.ui.button(emoji="🔎", row=0, style=discord.ButtonStyle.blurple)
    async def jump(self, interaction: Interaction, _) -> None:
        """When button is clicked…"""
        return await interaction.response.send_modal(JumpModal(self))

    @discord.ui.button(emoji="▶️", row=0)
    async def next(self, interaction: Interaction, _) -> None:
        """Go To next Page"""
        logger.info("You pressed the next button.")
        self.index = min(self.index + 1, len(self.pages))
        self.jump.label = f"{self.index + 1}/{len(self.pages)}"
        await self.handle_page(interaction)


class DropdownPaginator(Paginator):
    """A Paginator takes an embed, a list of rows, and a list of SelectOptions.

    When a button is clicked, the page is changed and the embed at the current
    index is pushed. The options for that page are also updated"""

    def __init__(
        self,
        invoker: User,
        embed: discord.Embed,
        rows: list[str],
        options: list[discord.SelectOption],
        length: int = 25,
        footer: str = "",
        *,
        parent: typing.Optional[BaseView] = None,
        timeout: typing.Optional[float] = None,
    ) -> None:
        embeds = embed_utils.rows_to_embeds(embed, rows, length, footer)
        self.dropdowns = embed_utils.paginate(options, length)

        self.dropdown: discord.ui.Select
        self.dropdown.options = self.dropdowns[0]
        self.options = options
        super().__init__(invoker, embeds, parent=parent, timeout=timeout)

    @discord.ui.select()
    async def dropdown(self, itr: Interaction, _: discord.ui.Select) -> None:
        """Raise because you didn't subclass, dickweed."""
        logger.info(itr.command.__dict__)
        raise NotImplementedError  # Always subclass this!

    async def handle_page(self, interaction: Interaction) -> None:
        """Refresh the view and send to user"""
        embed = self.pages[self.index]
        self.dropdown.options = self.dropdowns[self.index]
        self.jump.label = f"{self.index + 1}/{len(self.pages)}"
        return await interaction.response.edit_message(embed=embed, view=self)


class PagedItemSelect(DropdownPaginator):
    """An Item Select with multiple dropdowns the user can cycle through"""

    def __init__(
        self,
        invoker: User,
        options: list[discord.SelectOption],
        **kwargs,
    ):
        embed = discord.Embed(title="Select from multiple pages")
        rows = [i.label for i in options]
        super().__init__(invoker, embed, rows, options, **kwargs)
        self.dropdown.max_values = len(self.dropdown.options)

        self.values: set[str] = set()
        self.interaction: Interaction  # passback

    async def handle_page(self, interaction: Interaction) -> None:
        """Set the items to checked"""
        embed = self.pages[self.index]
        self.dropdown.options = self.dropdowns[self.index]
        self.dropdown.max_values = len(self.dropdown.options)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(row=1, options=[])
    async def dropdown(self, itr: Interaction, sel: discord.ui.Select) -> None:
        """Response object for view"""
        await itr.response.defer()

        for i in sel.options:
            # If this item has been selected:
            if i.value in sel.values and i.value not in self.values:
                self.values.add(i.value)

            # if this item has NOT been selected
            elif i.value not in sel.values and i.value in self.values:
                self.values.remove(i.value)

    @discord.ui.button(label="Done", row=2, style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: Interaction, _) -> None:
        """Stop the view and allow retrieval of interaction and values"""
        self.stop()
        self.interaction = interaction


@dataclasses.dataclass(slots=True)
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


class Confirmation(BaseView):
    """Ask the user if they wish to confirm an option."""

    def __init__(
        self,
        invoker: User,
        true: str = "Yes",
        false: str = "No",
    ) -> None:
        super().__init__(invoker)
        # Set By Buttons before stopping
        self.value: bool
        self.interaction: Interaction
        self.true.label = true
        self.false.label = false

    @discord.ui.button(label="Yes")
    async def true(self, interaction: Interaction, _) -> None:
        """Set Value to true, stop the view, save the interaction"""
        self.value = True
        self.interaction = interaction
        self.stop()

    @discord.ui.button(label="No")
    async def false(self, interaction: Interaction, _) -> None:
        """Set Value to false, stop the view, save the interaction"""
        self.value = False
        self.interaction = interaction
        self.stop()
