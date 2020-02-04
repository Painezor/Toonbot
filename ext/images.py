from PIL import Image, ImageDraw, ImageOps, ImageFont
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
import datetime
import textwrap
import discord
import asyncio
import random
import json
from io import BytesIO


class ImageManip(commands.Cog):
	""" Edit images for you """
	
	def __init__(self, bot):
		self.bot = bot
	
	@commands.command()
	@commands.cooldown(2, 90, BucketType.user)
	async def tinder(self, ctx):
		""" Try to Find your next date. """
		with ctx.typing():
			if ctx.author.id == 272722118192529409:
				return await ctx.send("Nobody will ever swipe right on you, Kegs.")
			match = random.choice([True, False, False])
			if not match:
				return await ctx.send("Nobody swiped right on you.")
			
			async with self.bot.session.get(str(ctx.author.avatar_url_as(format="png"))) as resp:
				av = await resp.content.read()
			match = random.choice(ctx.guild.members)
			name = match.display_name
			
			async with self.bot.session.get(str(match.avatar_url_as(format="png"))) as resp:
				target = await resp.content.read()
				df = await self.bot.loop.run_in_executor(None, self.dtin, target, av, name)
			
			if match == ctx.author:
				await ctx.send("Congratulations, you matched with yourself. How pathetic.", file=df)
			elif match == ctx.me:
				await ctx.send("Fancy a shag?", file=df)
			else:
				await ctx.send(file=df)
	
	def dtin(self, image, av, name):
		# Base Image
		im = Image.open("tinder.png").convert(mode="RGBA")
		# Prepare mask
		msk = Image.open("retardedmask.png").convert('L')
		msk = ImageOps.fit(msk, (185, 185))
		# User Avatar
		avt = Image.open(BytesIO(av)).convert(mode="RGBA")
		avo = ImageOps.fit(avt, (185, 185))
		avo.putalpha(msk)
		im.paste(avo, box=(100, 223, 285, 408), mask=msk)
		# Player
		plt = Image.open(BytesIO(image)).convert(mode="RGBA")
		plo = ImageOps.fit(plt, (185, 185), centering=(0.5, 0.0))
		plo.putalpha(msk)
		im.paste(plo, box=(313, 223, 498, 408), mask=msk)
		# Write "it's a mutual match"
		txt = f"You and {name} have liked each other."
		f = ImageFont.truetype('Whitney-Medium.ttf', 24)
		w, h = f.getsize(txt)
		d = ImageDraw.Draw(im)
		d.text((300 - w / 2, 180), txt, font=f, fill="#ffffff")
		# Cleanup & return as discord.file
		todel = [plt, plo, im, avt, avo, msk, d]
		output = BytesIO()
		im.save(output, "PNG")
		output.seek(0)
		for i in todel:
			del i
		df = discord.File(output, filename="tinder.png")
		return df
	
	async def get_faces(self, ctx, target):
		""" Retrieve face features from Prokect Oxford """
		# Prepare POST
		oxk = self.bot.credentials['Oxford']['OxfordKey']
		h = {"Content-Type": "application/json",
		     "Ocp-Apim-Subscription-Key": oxk}
		body = {"url": target}
		p = {"returnFaceId": "False",
		     "returnFaceLandmarks": "True",
		     "returnFaceAttributes": "headPose"}
		d = json.dumps(body)
		url = "https://westeurope.api.cognitive.microsoft.com/face/v1.0/detect"
		session = self.bot.session
		
		# Get Project Oxford reply
		async with session.post(url, params=p, headers=h, data=d) as resp:
			if resp.status != 200:
				if resp.status == 400:
					await ctx.send(await resp.json())
				else:
					await ctx.send(
						f"HTTP Error {resp.status} recieved accessing project oxford's facial recognition API.")
				return None, None
			respjson = await resp.json()
		
		# Get target image as file
		async with session.get(target) as resp:
			if resp.status != 200:
				await ctx.send(f"{resp.status} code accessing project oxford.")
			image = await resp.content.read()
		return image, respjson
	
	async def get_target(self, ctx, target):
		if ctx.message.mentions:
			target = str(ctx.message.mentions[0].avatar_url_as(format="png"))
		if target == None:
			for i in ctx.message.attachments:
				if i.height is None:  # Not an image.
					continue
				return i.url
			await ctx.send(':no_entry_sign: To use this command either upload an image, tag a user, or specify a url.')
			return None
		else:
			return target
	
	@commands.command(aliases=["bob", "ross"])
	async def bobross(self, ctx, *, target=None):
		""" Bob Rossify """
		with ctx.typing():
			target = await self.get_target(ctx, target)
			if not target:
				return  # rip.
			
			image, respjson = await self.get_faces(ctx, target)
			if respjson is None:
				return await ctx.send("No faces were detected in your image.")
			
			df = await self.bot.loop.run_in_executor(None, self.draw_bob, image, respjson)
			await ctx.send(file=df)
			try:
				await ctx.message.delete()
			except discord.Forbidden:
				pass
	
	def draw_bob(self, image, respjson):
		""" Pillow Bob Rossifying """
		im = Image.open(BytesIO(image)).convert(mode="RGBA")
		bob = Image.open("Images/rossface.png")
		for coords in respjson:
			x = int(coords["faceRectangle"]["left"])
			y = int(coords["faceRectangle"]["top"])
			w = int(coords["faceRectangle"]["width"])
			h = int(coords["faceRectangle"]["height"])
			roll = int(coords["faceAttributes"]["headPose"]["roll"]) * -1
			vara = int(x - (w / 4))
			varb = int(y - (h / 2))
			varc = int(x + (w * 1.25))
			vard = int((y + (h * 1.25)))
			xsize = varc - vara
			ysize = vard - varb
			thisbob = ImageOps.fit(bob, (xsize, ysize)).rotate(roll)
			im.paste(thisbob, box=(vara, varb, varc, vard), mask=thisbob)
		output = BytesIO()
		im.save(output, "PNG")
		output.seek(0)
		
		# cleanup
		del bob
		del im
		
		df = discord.File(output, filename="withbob.png")
		return df
	
	@commands.command()
	async def knob(self, ctx, *, target=None):
		""" Draw knobs in mouth on an image.
		Mention a user to use their avatar.
		Only works for human faces."""
		with ctx.typing():
			target = await self.get_target(ctx, target)
			if not target:
				return  # rip
			
			image, respjson = await self.get_faces(ctx, target)
			if respjson is None:
				return await ctx.send("No faces were detected in your image.")
			
			df = await self.bot.loop.run_in_executor(None, self.draw_knob, image, respjson)
			await ctx.send(ctx.author.mention, file=df)
			try:
				await ctx.message.delete()
			except discord.Forbidden:
				pass
	
	def draw_knob(self, image, respjson):
		im = Image.open(BytesIO(image)).convert(mode="RGBA")
		knob = Image.open("Images/knob.png")
		
		for coords in respjson:
			mlx = int(coords["faceLandmarks"]["mouthLeft"]["x"])
			mrx = int(coords["faceLandmarks"]["mouthRight"]["x"])
			lipy = int(coords["faceLandmarks"]["upperLipBottom"]["y"])
			lipx = int(coords["faceLandmarks"]["upperLipBottom"]["x"])
			
			angle = int(coords["faceAttributes"]["headPose"]["roll"] * -1)
			w = int((mrx - mlx)) * 2
			h = w
			tk = ImageOps.fit(knob, (w, h)).rotate(angle)
			im.paste(tk, box=(int(lipx - w / 2), int(lipy)), mask=tk)
		output = BytesIO()
		im.save(output, "PNG")
		output.seek(0)
		df = discord.File(output, filename="withknobs.png")
		return df
	
	@commands.command()
	async def eyes(self, ctx, *, target=None):
		""" Draw Googly eyes on an image.
			Mention a user to use their avatar.
			Only works for human faces."""
		with ctx.typing():
			target = await self.get_target(ctx, target)
			if not target:
				return  # rip
			image, respjson = await self.get_faces(ctx, target)
			if respjson is None:
				return await ctx.send("No faces were detected in your image.")
			
			# Pass it off to the executor
			df = await self.bot.loop.run_in_executor(None, self.draw_eyes, image, respjson)
			await ctx.send(ctx.author.mention, file=df)
			try:
				await ctx.message.delete()
			except:
				pass
	
	def draw_eyes(self, image, respjson):
		""" Draws the eyes """
		im = Image.open(BytesIO(image))
		draw = ImageDraw.Draw(im)
		for i in respjson:
			# Get eye bounds
			lix = int(i["faceLandmarks"]["eyeLeftInner"]["x"])
			lox = int(i["faceLandmarks"]["eyeLeftOuter"]["x"])
			lty = int(i["faceLandmarks"]["eyeLeftTop"]["y"])
			lby = int(i["faceLandmarks"]["eyeLeftBottom"]["y"])
			rox = int(i["faceLandmarks"]["eyeRightOuter"]["x"])
			rix = int(i["faceLandmarks"]["eyeRightInner"]["x"])
			rty = int(i["faceLandmarks"]["eyeRightTop"]["y"])
			rby = int(i["faceLandmarks"]["eyeRightBottom"]["y"])
			
			lw = lix - lox
			rw = rox - rix
			
			# Inflate
			lix = lix + lw
			lox = lox - lw
			lty = lty - lw
			lby = lby + lw
			rox = rox + rw
			rix = rix - rw
			rty = rty - rw
			rby = rby + rw
			
			# Recalculate with new sizes.
			lw = lix - lox
			rw = rox - rix
			
			# Open Eye Image, resize, paste twice
			eye = Image.open("Images/eye.png")
			left = ImageOps.fit(eye, (lw, lw))
			right = ImageOps.fit(eye, (rw, rw))
			im.paste(left, box=(lox, lty), mask=left)
			im.paste(right, box=(rix, rty), mask=right)
		
		# Prepare for sending and return
		output = BytesIO()
		im.save(output, "PNG")
		output.seek(0)
		df = discord.File(output, filename="witheyes.png")
		
		# cleanup
		del draw
		del im
		
		return df
	
	@commands.command(usage='tard <@user> <quote>')
	async def tard(self, ctx, target: discord.Member, *, quote):
		""" Generate an "oh no, it's retarded" image
		with a user's avatar and a quote "
		"""
		with ctx.typing():
			if target.id == 210582977493598208:
				target = ctx.author
				quote = "I think I'm smarter than Painezor"
			cs = self.bot.session
			async with cs.get(str(target.get_avatar_url_as(format="png", size=1024))) as resp:
				if resp.status != 200:
					return await ctx.send(f"Error retrieving avatar for target {target} {resp.status}")
				image = await resp.content.read()
			df = await self.bot.loop.run_in_executor(None, self.draw_tard, image, quote)
			await ctx.send(file=df)
	
	@tard.error
	async def tard_error(self, ctx, exc):
		if isinstance(exc, commands.BadArgument):
			return await ctx.send("🚫 Bad argument provided: Make sure you're pinging a user or using their ID")
	
	def draw_tard(self, image, quote):
		""" Draws the "it's retarded" image """
		# Open Files
		im = Image.open(BytesIO(image))
		base = Image.open("Images/retardedbase.png")
		msk = Image.open("Images/retardedmask.png").convert('L')
		
		# Resize avatar, make circle, paste
		ops = ImageOps.fit(im, (250, 250))
		ops.putalpha(msk)
		smallmsk = msk.resize((35, 40))
		small = ops.resize((35, 40))
		largemsk = msk.resize((100, 100))
		large = ops.resize((100, 100)).rotate(-20)
		base.paste(small, box=(175, 160, 210, 200), mask=smallmsk)
		base.paste(large, box=(325, 90, 425, 190), mask=largemsk)
		
		# Drawing tex
		d = ImageDraw.Draw(base)
		
		# Get best size for text
		def get_first_size(quote):
			fntsize = 72
			ttf = 'Whitney-Medium.ttf'
			f = ImageFont.truetype(ttf, fntsize)
			wid = 300
			quote = textwrap.fill(quote, width=wid)
			while fntsize > 0:
				# Make lines thinner if too wide.
				while wid > 1:
					if f.getsize(quote)[0] < 237 and f.getsize(quote)[1] < 89:
						return (wid, f)
					wid -= 1
					quote = textwrap.fill(quote, width=wid)
					f = ImageFont.truetype(ttf, fntsize)
				fntsize -= 1
				f = ImageFont.truetype(ttf, fntsize)
				wid = 40
		
		wid, f = get_first_size(quote)
		quote = textwrap.fill(quote, width=wid)
		# Write lines.
		moveup = f.getsize(quote)[1]
		d.text((245, (80 - moveup)), quote, font=f, fill="#000000")
		
		# Prepare for sending
		output = BytesIO()
		base.save(output, "PNG")
		output.seek(0)
		df = discord.File(output, filename="retarded.png")
		
		# Cleanup
		for i in [d, ops, msk, im, smallmsk, largemsk, msk, large, f, base]:
			del i
		return df
	
	@commands.command(hidden=True)
	@commands.is_owner()
	async def fquote(self, ctx, user: discord.Member, *, qtext):
		""" Generate a fake quote from a user """
		# Delete original message
		await ctx.message.delete()
		
		# Get user info, set colors.
		cs = self.bot.session
		async with cs.get(user.avatar_url_as(format="png", size=256)) as resp:
			if resp.status != 200:
				err = f"{resp.status} error attempting to retrieve avatar url"
				await ctx.send(err, delete_after=5)
			image = await resp.content.read()
		df = await self.bot.loop.run_in_executor(None, self.draw_fquote, image, user, qtext)
		await ctx.send(file=df)
	
	def draw_fquote(self, image, user, qtext):
		now = datetime.datetime.now()
		timestamp = datetime.datetime.strftime(now, "Today at %I:%M %p")
		timestamp = timestamp.replace("at 0", "at ")
		name = user.display_name
		if user.color.to_rgb() == (0, 0, 0):
			color = (255, 255, 255, 255)
		else:
			color = user.color.to_rgb() + (255,)
		timecolor = (255, 255, 255, 51)
		qcolor = (255, 255, 255, 179)
		
		# Open Avatar, apply mask, shrink.
		base = Image.open(BytesIO(image))
		msk = Image.open("Images/retardedmask.png").convert('L')
		ops = ImageOps.fit(base, (250, 250))
		ops.putalpha(msk)
		large = ops.resize((40, 40), Image.ANTIALIAS)
		
		# Generate text, get sizes, determine image size
		nfnt = ImageFont.truetype('Whitney Medium Regular_0.ttf', 16)  # name
		qfnt = ImageFont.truetype('Whitney Medium Regular_0.ttf', 15)  # quote
		tfnt = ImageFont.truetype('Whitney Light Regular_0.ttf', 12)  # ts
		w1, h1 = nfnt.getsize(name)
		w2, h2 = qfnt.getsize(qtext)
		w3, h3 = tfnt.getsize(timestamp)
		w = max(w2, w1 + w3)
		
		# Generate New image and paste Avatar.
		bgcolor = (54, 57, 62, 255)
		top = Image.new('RGBA', (w + 70, 60), bgcolor)
		top.paste(large, box=(0, 0, 40, 40))
		# Write quote
		d = ImageDraw.Draw(top)
		d.text((60, 0), name, font=nfnt, fill=color)
		d.text((65 + w1, 4), timestamp, font=tfnt, fill=timecolor)
		d.text((60, 20), qtext, font=qfnt, fill=qcolor)
		
		# Save output and send
		output = BytesIO()
		top.save(output, "PNG")
		output.seek(0)
		# cleanup
		for i in [d, nfnt, qfnt, tfnt, base, top, msk, large, ops]:
			del i
		df = discord.File(output, filename="retarded.png")
		return df
	
	@commands.command(aliases=["localman", "local", "ruin"], hidden=True)
	async def ruins(self, ctx, *, user: discord.User = None):
		""" Local man ruins everything """
		with ctx.typing():
			if user == None:
				user = ctx.author
			av = str(user.avatar_url_as(format="png", size=256))
			async with self.bot.session.get(av) as resp:
				if resp.status != 200:
					await ctx.send(f"{resp.status} Error getting {user}'s avatar")
				image = await resp.content.read()
			df = await self.bot.loop.run_in_executor(None, self.ruin, image)
			await ctx.send(file=df)
	
	def ruin(self, image):
		""" Generates the Image """
		im = Image.open(BytesIO(image))
		base = Image.open("Images/localman.png")
		ops = ImageOps.fit(im, (256, 256))
		base.paste(ops, box=(175, 284, 431, 540))
		output = BytesIO()
		base.save(output, "PNG")
		output.seek(0)
		# output
		df = discord.File(output, filename="retarded.png")
		return df
	
	@commands.is_owner()
	async def autism(self, ctx):
		await ctx.trigger_typing()
		autists = [210581854758109184, 178631560650686465, 141665281683488768, 202780724078575616]
		autmessages = []
		autcontent = ["reee", "lawler", "ayy"]
		async for i in ctx.history():
			if i.author.id in autists:
				autmessages.append(i)
			elif i.content == i.content.upper():
				autmessages.append(i)
				autists.append(i.author.id)
			else:
				for j in autcontent:
					if j.lower() in i.content.lower():
						autmessages.append(i)
						autists.append(i.author.id)
		
		l = self.bot.loop
		aut = await l.run_in_executor(None, self.draw_autists, len(autmessages))
		await ctx.send(file=aut)
		if 35 < len(autmessages):
			await ctx.send("**AUTISM LEVELS OFF THE CHART, "
			               "TAKING REMEDIARY ACTION**")
			for i in autists:
				u = ctx.guild.get_member(i)
				await ctx.send(f"{u.mention} has been kicked.")
				await u.kick(reason="Autism prevention")
			await ctx.delete_messages(autmessages)
			await ctx.send(f"{len(autmessages)} messages were deleted.")
	
	def draw_autists(self, count):
		""" Draw the autism meter """
		if count < 5:
			color = "#e2edff"  # W
		elif 4 < count < 10:
			color = "#009a66"  # G
		elif 9 < count < 18:
			color = "#3566cd"  # B
		elif 17 < count < 25:
			color = "#fde100"  # Y
		elif 24 < count < 35:
			color = "#ff6500"  # O
		else:
			color = "#ff6500"  # R
		x = 115
		y = 28
		w = x + 10 * count
		h = y + 50
		base = Image.open("autism.png")
		d = ImageDraw.Draw(base)
		d.rectangle((x, y, w, h), fill=color)
		output = BytesIO()
		base.save(output, "PNG")
		output.seek(0)
		df = discord.File(output, filename="autism.png")
		# Cleanup
		del base
		del d
		return df
	
	@commands.command(hidden=True)
	async def butter(self, ctx):
		""" What is my purpose? """
		await ctx.send(file=discord.File("Images/butter.png"))
	
	@commands.command(hidden=True)
	async def fixed(self, ctx):
		""" Fixed! """
		await ctx.send(file=discord.File("Images/fixed.png"))
	
	@commands.command(hidden=True)
	async def ructions(self, ctx):
		""" WEW. RUCTIONS. """
		await ctx.send(file=discord.File("Images/ructions.png"))
	
	@commands.command(hidden=True)
	async def helmet(self, ctx):
		""" Helmet"""
		await ctx.send(file=discord.File("Images/helmet.jpg"))
	
	@commands.command(hidden=True, aliases=["f"])
	async def pressf(self, ctx):
		""" Press F to pay respects """
		await ctx.send("https://i.imgur.com/zrNE05c.gif")
	
	@commands.command(hidden=True)
	async def goala(self, ctx):
		""" Party on Garth """
		await ctx.send(file=discord.File('goala.gif'))
	
	@commands.command()
	@commands.cooldown(1, 120, BucketType.user)
	async def cat(self, ctx):
		""" Adopt a random cat """
		await ctx.trigger_typing()
		retries = 0
		while retries < 3:
			async with self.bot.session.get("http://random.cat/meow") as resp:
				if resp.status != 200:
					await asyncio.sleep(1)
					retries += 1
					continue
				else:
					cat = await resp.json()
					async with self.bot.session.get(cat["file"]) as resp:
						cat = await resp.content.read()
						fp = discord.File(BytesIO(cat), filename="cat.png")
						try:
							return await ctx.author.send("😺 Here's your cat:", file=fp)
						except:
							return await ctx.send(
								"Tried to send you your cat, but I can't send you messages. Guess he's not getting adopted then.")
		await ctx.send("😿 Sorry, no cats want to be adopted by you.")


def setup(bot):
	bot.add_cog(ImageManip(bot))
