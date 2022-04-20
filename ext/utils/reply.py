"""Reply Handling for bots"""
from io import BytesIO

from discord import Embed, Interaction, Message, NotFound, Colour, File


async def dump_image(self, img: BytesIO) -> str | None:
	"""Dump an image to discord & return its URL to be used in embeds"""
	ch = self.get_channel(874655045633843240)
	img_msg = await ch.send(file=File(fp=img, filename="dumped_image.png"))
	url = img_msg.attachments[0].url
	return None if url == "none" else url


async def error(i: Interaction, e: str, message: Message = None, ephemeral: bool = True, followup=True) -> Message:
	"""Send a Generic Error Embed"""
	e: Embed = Embed(title="An Error occurred.", colour=Colour.red(), description=e)
	return await reply(i, embed=e, message=message, ephemeral=ephemeral, followup=followup)


async def reply(i: Interaction, message: Message = None, followup: bool = True, **kwargs) -> Message:
	"""Generic reply handler."""
	if message is None and not i.response.is_done():
		await i.response.send_message(**kwargs)
		return await i.original_message()

	try:
		message = await i.original_message() if message is None else message
		try_edit = kwargs.copy()

		if "ephemeral" in kwargs:
			try_edit.pop("ephemeral")

		if "file" in kwargs:
			try_edit['attachments'] = [try_edit.pop('file')]

		return await message.edit(**try_edit)
	except NotFound:
		if followup:  # Don't send messages if the message has previously been deleted.
			return await i.followup.send(**kwargs, wait=True)  # Return the message.
