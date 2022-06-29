"""Reply Handling for bots"""
from discord import Embed, Interaction, Message, NotFound, Colour


async def error(i: Interaction, content: str, message: Message = None, ephemeral: bool = True,
                followup: bool = True, **kwargs) -> Message:
	"""Send a Generic Error Embed"""
	e: Embed = Embed(title="An Error occurred.", colour=Colour.red(), description=content)
	return await reply(i, message=message, embed=e, ephemeral=ephemeral, followup=followup, **kwargs)


async def reply(i: Interaction, message: Message = None, followup: bool = True, **kwargs) -> Message:
	"""Generic reply handler."""
	if message is None and not i.response.is_done():
		await i.response.send_message(**kwargs)
		return await i.original_message()

	kwargs.pop("ephemeral", None)
	try:
		message = await i.original_message() if message is None else message
		f = kwargs.pop('file', None)
		if f is not None:
			kwargs['attachments'] = [f]
		return await message.edit(**kwargs)
	except NotFound:
		if followup:  # Don't send messages if the message has previously been deleted.
			return await i.followup.send(**kwargs, wait=True)  # Return the message.
