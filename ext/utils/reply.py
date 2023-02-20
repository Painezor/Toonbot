"""Reply Handling for bots"""
from discord import Embed, Interaction, Message, NotFound, Colour, Forbidden
from discord.ui import View

from ext.utils.view_utils import Stop


async def error(i: Interaction, content: str,
                message: Message = None,
                followup: bool = True, **kwargs) -> Message:
    """Send a Generic Error Embed"""
    e: Embed = Embed(colour=Colour.red(), description=content)

    kwargs.pop('view', None)

    v = View()
    v.interaction = i
    v.add_item(Stop())
    return await reply(i, message=message, embed=e, ephemeral=True, followup=followup, view=v, **kwargs)


async def reply(i: Interaction, message: Message = None, followup: bool = True, **kwargs) -> Message:
    """Generic reply handler."""
    if message is None and not i.response.is_done():
        await i.response.send_message(**kwargs)
        return await i.original_response()

    kwargs.pop("ephemeral", None)
    try:
        f = kwargs.pop('file', None)
        if f is not None:
            kwargs['attachments'] = [f]
        return await i.edit_original_response(**kwargs)
    except NotFound:
        if followup:  # Don't send messages if the message has previously been deleted.
            try:
                return await i.followup.send(**kwargs, wait=True)  # Return the message.
            except NotFound:
                try:
                    return await i.user.send(**kwargs)
                except Forbidden:
                    pass
