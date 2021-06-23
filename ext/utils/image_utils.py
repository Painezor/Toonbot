"""Utilities for Image manipulation"""
from io import BytesIO
from typing import List

from PIL import Image


def stitch(images: List[Image.Image]) -> BytesIO:
	"""Stich images side by side"""
	# images is a list of opened PIL images.
	w = int(images[0].width / 3 * 2 + sum(i.width / 3 for i in images))
	h = images[0].height
	canvas = Image.new('RGB', (w, h))
	x = 0
	for i in images:
		canvas.paste(i, (x, 0))
		x += int(i.width / 3)
	output = BytesIO()
	canvas.save(output, 'PNG')
	
	output.seek(0)
	return output


def stitch_vertical(images) -> BytesIO:
	"""Stitch Images Vertically"""
	images = [Image.open(i) for i in images]

	w = images[0].width
	h = sum(i.height for i in images)
	canvas = Image.new('RGB', (w, h))
	y = 0
	for i in images:
		canvas.paste(i, (0, y))
		y += i.height
	output = BytesIO()
	canvas.save(output, 'PNG')
	output.seek(0)
	canvas.close()

	[i.close() for i in images]
	
	return output
