"""Generic Objects for discord Views"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeAlias
import typing

import discord
from discord import Embed, Message, SelectOption
from discord.ui import TextInput, Select

from ext.utils import embed_utils

if TYPE_CHECKING:
    from core import Bot
    from painezbot import PBot

    Interaction: TypeAlias = discord.Interaction[Bot | PBot]
    User: TypeAlias = discord.User | discord.Member


logger = logging.getLogger("view_utils")


class BaseView(discord.ui.View):
    """Error Handler."""

    message: Message | None = None
    embed: Embed | None = None

    def __init__(
        self,
        invoker: User | None,
        *,
        parent: BaseView | None = None,
        timeout: float | None = 180,
    ):
        # User ID of the person who invoked the command.
        super().__init__(timeout=timeout)

        self.invoker: User | None = invoker

        self.parent = parent
        if parent is None:
            self.remove_item(self.parent_button)

    @discord.ui.button(label="Back", emoji="🔼")
    async def parent_button(self, interaction: Interaction, _) -> None:
        """Send Parent View"""
        # This function is only accessible if self.parent is set.
        assert self.parent is not None
        view = self.parent
        edit = interaction.response.edit_message
        await edit(view=view, attachments=[])

    @discord.ui.button(emoji="🚯", row=0, style=discord.ButtonStyle.red)
    async def _stop(self, interaction: Interaction, _) -> None:
        """Delete this message."""
        await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except discord.NotFound:
            pass

        # Handle any cleanup.
        await self.on_timeout()
        self.stop()

    async def interaction_check(
        self, interaction: discord.Interaction, /
    ) -> bool:
        """If an invoker was passed, make sure only they can click"""
        if self.invoker:
            return interaction.user.id == self.invoker.id
        return True

    async def on_timeout(self) -> None:
        """Cleanup"""
        for i in self.children:
            i.disabled = True  # type: ignore

        if self.message is not None:
            await self.message.edit(view=self)
            return
        logger.error("Message not set on view %s", self.__class__.__name__)

    async def on_error(  # type: ignore
        self,
        interaction: Interaction,
        error: Exception,
        item: discord.ui.Item[BaseView],
        /,
    ) -> None:
        """Log errors"""
        logger.error("Error on view item %s", item, exc_info=True)

        if interaction.response.is_done():
            edit = interaction.edit_original_response
        else:
            edit = interaction.response.edit_message
        txt = f"Something broke\n```py\n{error}```"
        try:
            await edit(content=txt, embed=None)
        except discord.NotFound:
            self.stop()


class JumpModal(discord.ui.Modal):
    """Type page number in box, set index to that page."""

    page: TextInput[JumpModal] = TextInput(label="Enter a page number")

    def __init__(self, view: Paginator, title: str = "Jump to page") -> None:
        super().__init__(title=title)
        self.view = view
        self.page.placeholder = f"1 - {view.pages}"

    async def on_submit(  # type: ignore
        self, interaction: Interaction, /
    ) -> None:
        """Validate entered data & set parent index."""
        new_index = int(self.page.value) - 1  # Humans index from 1

        if new_index > self.view.pages:
            new_index = self.view.pages

        self.view.index = new_index
        return await self.view.handle_page(interaction)


# TODO: Deperecate rows_to_embeds
class Paginator(BaseView):
    """A Paginator takes a list of Embeds and an Optional list of
    lists of SelectOptions. When a button is clicked, the page is changed
    and the embed at the current index is pushed. If a list of selects
    is also provided that matches the embed, the options are also updated"""

    def __init__(
        self,
        invoker: User,
        pages: int,
        *,
        parent: BaseView | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(invoker, parent=parent, timeout=timeout)

        self.pages = pages
        self.index: int = 0
        self.update_buttons()

    def update_buttons(self) -> None:
        """Refresh labels & Availability of buttons"""
        pages = len(self.pages) if isinstance(self.pages, list) else self.pages
        self.jump.disabled = pages < 3
        self.next.disabled = self.index + 1 >= pages
        self.previous.disabled = self.index == 0
        self.jump.label = f"{self.index + 1}/{pages}"

    async def handle_page(self, interaction: Interaction) -> None:
        """Refresh the view and send to user"""
        cln = self.__class__.__name__
        raise NotImplementedError("No suitable handle_page found for %s", cln)

    @discord.ui.button(label="◀️", row=0)
    async def previous(self, interaction: Interaction, _) -> None:
        """Go to previous page"""
        self.index -= 1
        await self.handle_page(interaction)

    @discord.ui.button(emoji="🔎", row=0, style=discord.ButtonStyle.blurple)
    async def jump(self, interaction: Interaction, _) -> None:
        """When button is clicked…"""
        return await interaction.response.send_modal(JumpModal(self))

    @discord.ui.button(emoji="▶️", row=0)
    async def next(self, interaction: Interaction, _) -> None:
        """Go To next Page"""
        self.index += 1
        await self.handle_page(interaction)


class EmbedPaginator(Paginator):
    def __init__(
        self,
        invoker: User,
        embeds: list[Embed],
        *,
        index: int = 0,
        parent: BaseView | None = None,
        timeout: float | None = None,
    ) -> None:
        self.embeds: list[Embed] = embeds
        pages = len(embeds)
        super().__init__(invoker, pages, parent=parent, timeout=timeout)
        self.index = index

    async def handle_page(self, interaction: Interaction) -> None:
        embed = self.embeds[self.index]
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)


class DropdownPaginator(EmbedPaginator):
    """A Paginator takes an embed, a list of rows, and a list of SelectOptions.

    When a button is clicked, the page is changed and the embed at the current
    index is pushed. The options for that page are also updated"""

    def __init__(
        self,
        invoker: User,
        embed: Embed,
        rows: list[str],
        options: list[SelectOption],
        length: int = 25,
        footer: str = "",
        *,
        multi: bool = False,
        parent: BaseView | None = None,
        timeout: float | None = None,
    ) -> None:
        embeds = embed_utils.rows_to_embeds(embed, rows, length, footer)
        self.dropdowns = embed_utils.paginate(options, length)

        super().__init__(invoker, embeds, parent=parent, timeout=timeout)

        try:
            if multi:
                self.dropdown.max_values = len(self.dropdowns[0])
            self.dropdown.options = self.dropdowns[0]
        except IndexError:
            self.remove_item(self.dropdown)
        self.options = options

    @discord.ui.select()
    async def dropdown(
        self, itr: Interaction, _: Select[DropdownPaginator]
    ) -> None:
        """Raise because you didn't subclass, dickweed."""
        logger.info(itr.command.__dict__)
        raise NotImplementedError  # Always subclass this!

    async def handle_page(self, interaction: Interaction) -> None:
        """Refresh the view and send to user"""
        embed = self.embeds[self.index]
        self.dropdown.options = self.dropdowns[self.index]
        self.update_buttons()
        return await interaction.response.edit_message(embed=embed, view=self)


class PagedItemSelect(DropdownPaginator):
    """An Item Select with multiple dropdowns the user can cycle through"""

    def __init__(
        self,
        invoker: User,
        options: list[SelectOption],
        **kwargs: typing.Any,
    ):
        embed = Embed(title="Select from multiple pages")
        rows = [i.label for i in options]
        super().__init__(invoker, embed, rows, options, **kwargs)

        self.dropdown.max_values = len(self.dropdowns[self.index])

        self.values: set[str] = set()
        self.interaction: Interaction  # passback

    async def handle_page(self, interaction: Interaction) -> None:
        """Set the items to checked"""
        embed = self.embeds[self.index]
        self.dropdown.options = self.dropdowns[self.index]
        self.dropdown.max_values = len(self.dropdowns[self.index])
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(row=1, options=[])
    async def dropdown(
        self, itr: Interaction, sel: discord.ui.Select[PagedItemSelect]
    ) -> None:
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
