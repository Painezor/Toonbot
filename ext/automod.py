from discord.ext import commands
import discord
import asyncpg
import typing


class AutoMod(commands.Cog):
	def __init__(self, bot):
		self.bot = bot
		self.bot.loop.create_task(self.update_cache())
	
	async def update_cache(self):
		self.automod_cache = {}
		connection = await self.bot.db.acquire()
		async with connection.transaction():
			records =  await connection.fetch("""SELECT * FROM mention_spam""")
		await self.bot.db.release(connection)
		
		for r in records:
			thisrecord = r['guild_id'] = {mention_threshold : r["mention_threshold"], mention_action : r['mention_action']}
			self.automod_cache.update(thisrecord)

	@commands.has_permissions(kick_members=True)
	@commands.bot_has_permissions(ban_members=False)
	@commands.command(usage="mentionspam <number of pings> <'kick', 'mute' or 'ban'>",aliases=["pingspam"])	
	async def mentionspam(self,ctx,threshhold : typing.Optional[int] = None,action=None):
		""" Automatically kick or ban a member for pinging more than x users in a message. Use '0' for threshhold to turn off."""
		guild_cache = self.bot.automod_cache[ctx.guild.id]
		if threshhold is None:
			# Get current data.
			try:
				output = f"I will {guild_cache['mention_action']} members who ping {guild_cache['mention_threshold']} or more other users in a message."
			except KeyError:
				output = f"No action is currently being taken against users who spam mentions. Use {ctx.prefix}mentionspam <number> <action ('kick', 'ban' or 'mute')> to change this"
			return await ctx.send(output)
		elif threshold < 4:
			return await ctx.send()
		
		
		if action is None or action.lower() not in ['kick','ban','mute']:
			return await ctx.send("🚫 Invalid action specified, valid actions are 'kick', 'ban', or 'mute'.")
			
		action = action.lower()
		if action == "kick":
			if not ctx.me.permissions_in(ctx.channel).kick_members:
				return await ctx.send("🚫 I need the 'kick_members' permission to do that.")
		elif action == "ban":
			if not ctx.me.permissions_in(ctx.channel).ban_members:
				return await ctx.send("🚫 I need the 'ban_members' permission to do that.")
		
		connection = await self.db.acquire()
		await connection.execute("""
		INSERT INTO mention_spam (mention_threshold,mention_action)
		VALUES ($1,$2)
		ON CONFLICT DO UPDATE SET
			(mention_threshold,mention_action = $1,$2)
		""",threshhold,action)
		
		return await ctx.send(f"✅ I will {action} users who ping {threshhold} other users in a message.")

	@commands.Cog.listener()
	async def on_message(self,message):
		try:
			guild_cache = self.automod_cache[message.guild.id]
		except (KeyError,AttributeError):
			return
		if guild_cache["mention_threshold"] > len(message.mentions):
			return
		
		if guild_cache["action"] == "kick":
			await message.author.kick(reason=f"Mentioning {guild_cache['mention_threshold']} members in a message.")
			return await message.channel.send(f"{message.author.mention} was kicked for mention spamming.")
		elif guild_cache["action"] == "ban":
			await message.author.ban(reason=f"Mentioning {guild_cache['mention_threshold']} members in a message.")
			return await message.channel.send(f"☠️ {message.author.mention} was banned for mention spamming.")
		elif guild_cache["action"] == "mute":
			mrole = discord.utils.get(message.guild.roles, name='Muted')
			if not mrole:
				mrole = await message.guild.create_role(name="Muted")
				pos = message.guild.me.top_role.position - 1
				await mrole.edit(position=pos)		
				moverwrite = discord.PermissionOverwrite()
				moverwrite.add_reactions = False
				moverwrite.send_messages = False		
				for i in ctx.guild.text_channels:
					await i.set_permissions(mrole,overwrite=moverwrite)

				await message.author.add_roles(*[mrole])
				await message.channel.send(f"{message.author.mention} was muted for mention spam.")
				await mutechan.send(f"{message.author.mention} was muted for mention spam.")
def setup(bot):
	bot.add_cog(AutoMod(bot))