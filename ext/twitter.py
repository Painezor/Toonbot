# """Utility for fetching Tweets from Twitter and exporting to Discord"""
# import html as htmlc
# import typing
# from datetime import datetime
#
# import discord
# import tweepy
# import tweepy.asynchronous
# from discord.ext import commands
#
# from ext.utils import embed_utils, view_utils
#
# TWITTER_ICON = "https://abs.twimg.com/icons/apple-touch-icon-192x192.png"
#
#
# # TODO: Select / Button Pass.
# # TODO: Finish working on.
#
# class Twitter(commands.Cog):
#     """Track twitter accounts"""
#
#     def __init__(self, bot):
#         self.bot = bot
#         self.emoji = "📣"
#         self.records = None
#         self.credentials = self.bot.credentials['Twitter']
#         self.client = tweepy.asynchronous.AsyncStream(**self.credentials)
#
#         auth = tweepy.OAuthHandler(self.credentials["consumer_key"], self.credentials["consumer_secret"])
#         auth.set_access_token(self.credentials["access_token"], self.credentials["access_token_secret"])
#         self.api = tweepy.API(auth)
#
#         self.bot.loop.create_task(self.update_cache())
#         self.bot.twitter = self.bot.loop.create_task(self.twat())
#
#     def cog_unload(self):
#         """Cancel the twitter tracker when the cog is unloaded."""
#         self.bot.twitter.cancel()
#
#     async def update_cache(self):
#         """Fetch latest DB copy of tweets"""
#         connection = await self.bot.db.acquire()
#         async with connection.transaction():
#             self.records = await connection.fetch("""SELECT * FROM twitter""")
#         await self.bot.db.release(connection)
#
#     async def twat(self):
#         """Twitter tracker function"""
#         await self.bot.wait_until_ready()
#
#         # Retrieve list of IDs to track
#         ts = self.client.filter(follow=[r.id for r in self.records])
#
#         async with ts as stream:
#             async for tweet in stream:
#                 # Break loop if bot not running.
#                 if self.bot.is_closed():
#                     break
#
#                 # discard malformed tweets
#                 if not hasattr(tweet, "user"):
#                     continue
#
#                 # discard retweets & adverts
#                 if hasattr(tweet, 'retweeted_status') or tweet.text.startswith(("rt", 'ad')):
#                     continue
#
#                 # discard replies
#                 if tweet["in_reply_to_status_id"] is not None:
#                     continue
#
#                 # Set destination or discard non-tracked
#                 records = [i for i in self.records if i.userid == tweet.user.id]
#
#                 if not records:
#                     continue
#
#                 user = tweet.user
#
#                 if tweet.truncated:
#                     text = htmlc.unescape(tweet.extended_tweet.full_text)
#                     ents = dict(tweet.entities)
#                     ents.update(dict(tweet.extended_tweet.entities))
#                 else:
#                     ents = tweet.entities
#                     text = htmlc.unescape(tweet.text)
#
#                 if "hashtags" in ents:
#                     for i in ents["hashtags"]:
#                         text = text.replace(f'#{i.text}', f"[#{i.text}](https://twitter.com/hashtag/{i.text})")
#                 if "urls" in ents:
#                     for i in ents["urls"]:
#                         text = text.replace(i.url, i.expanded_url)
#                 if "user_mentions" in ents:
#                     for i in ents["user_mentions"]:
#                         name = i.screen_name
#                         text = text.replace(f'@{name}', f"[@{name}](https://twitter.com/{name})")
#
#                 e = discord.Embed(description=name)
#                 e.colour = int(user.profile_link_color, 16)
#                 e.set_thumbnail(url=user.profile_image_url)
#                 e.timestamp = datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y")
#                 e.set_footer(icon_url=TWITTER_ICON, text="Twitter")
#
#                 e.title = f"{user.name} (@{user.screen_name})"
#                 e.url = f"http://www.twitter.com/{user.screen_name}/status/{tweet.id_str}"
#
#                 # Extract entities to lists
#                 photos = []
#                 videos = []
#
#                 def extract_entities(alist):
#                     """Fetch List of photo or video entities from Tweet"""
#                     for i in alist:
#                         if i.type in ["photo", "animated_gif"]:
#                             photos.append(i.media_url)
#                         elif i.type == "video":
#                             videos.append(i.video_info.variants[1].url)
#                         else:
#                             print("Unrecognised TWITTER MEDIA TYPE", i)
#
#                 # Fuck this nesting kthx.
#                 if hasattr(tweet, "extended_entities") and hasattr(tweet.extended_entities, "media"):
#                     extract_entities(tweet.extended_entities.media)
#                 if hasattr(tweet, "quoted_status"):
#                     if hasattr(tweet.quoted_status, "extended_entities"):
#                         if hasattr(tweet.quoted_status.extended_entities, "media"):
#                             extract_entities(tweet.quoted_status.extended_entities.media)
#
#                 # Set image if one image, else add embed field.
#                 if len(photos) == 1:
#                     e.set_image(url=photos[0])
#                 elif len(photos) > 1:
#                     en = enumerate(photos, start=1)
#                     v = ", ".join([f"[{i}]({j})" for i, j in en])
#                     e.add_field(name="Attached Photos", value=v)
#
#                 # Add embed field for videos
#                 if videos:
#                     if len(videos) > 1:
#                         en = enumerate(videos, start=1)
#                         v = ", ".join([f"[{i}]({j})" for i, j in en])
#                         e.add_field(name="Attached Videos", value=v)
#
#                 for r in records:
#                     destination = self.bot.get_channel(r.channel_id)
#                     if destination is None:
#                         print(f"Warning: Deleted Twitter Channel: {r.channel_id}")
#                         continue
#                     await destination.send(embed=e)
#                     if videos:
#                         await destination.send(videos[0])
#
#     async def send_config(self, ctx):
#         """List a server's twitter trackers"""
#         e = discord.Embed(color=0x7EB3CD)
#         e.set_thumbnail(url="https://i.imgur.com/jSEtorp.png")
#         e.set_author(name=f"{ctx.guild.name} Tracked Twitter accounts", icon_url=TWITTER_ICON)
#
#         tracked_items = [f"{i['name']} -> {self.bot.get_channel(i['channel_id']).mention}" for i in
#                          self.records if i['guild_id'] == ctx.guild.id]
#         embeds = embed_utils.rows_to_embeds(e, tracked_items)
#
#         view = view_utils.Paginator(ctx.author, embeds)
#         view.message = await self.bot.reply(ctx, "Fetching tracked twitter users...", embeds)
#         await view.update()
#
#     # TODO: Add / remove per channel etc etc.
#     @commands.group(invoke_without_command=True)
#     @commands.is_owner()
#     async def twitter(self, ctx):
#         """View your server's twitter trackers"""
#         await self.send_config(ctx)
#
#     @twitter.command()
#     @commands.is_owner()
#     async def add(self, ctx, channel: typing.Optional[discord.TextChannel] = None, *, username: commands.clean_content):
#         """Add user to track for a target channel"""
#         channel = ctx.channel if channel is None else channel
#         assert channel.guild.id == ctx.guild.id, "You cannot add a twitter tracker to other servers."
#
#         users = self.api.search_users(q=username)
#         e = discord.Embed()
#         e.colour = discord.Colour.blue()
#         embeds = embed_utils.rows_to_embeds(e, [str(i) for i in users])
#
#         index = await embed_utils.page_selector(ctx, embeds)
#         user = users[index]
#
#         connection = await self.bot.db.acquire()
#         async with connection.transaction():
#             self.records = await connection.fetch("""INSERT INTO twitter (userid, guild_id, channel_id)
#             VALUES ($1, $2, $3)""", user.id, ctx.guild.id, channel.id)
#         await self.bot.db.release(connection)
#         await self.update_cache()
#         await self.bot.reply(ctx, f"{username} added to tracked users for {ctx.channel.mention}.")
#         await self.send_config(ctx)
#
#     @twitter.command(name="del", aliases=["remove"])
#     @commands.is_owner()
#     async def _del(self, ctx, username):
#         """Deletes a user from the cahnnel's twitter tracker"""
#         guild_matches = [i.alias for i in self.records if i['guild_id'] == ctx.guild.id and username in i['alias']]
#
#         if not guild_matches:
#             return self.bot.reply(ctx, f"No followed twitter accounts found for {ctx.guild.name}")
#
#         index = await embed_utils.page_selector(ctx, guild_matches)
#         if index is None:
#             return
#
#         r = guild_matches[index]
#
#         connection = await self.bot.db.acquire()
#         async with connection.transaction():
#             self.records = await connection.fetch(
#                 """DELETE FROM twitter WHERE (user_id, guild_id, channel_id, alias) = ($1, $2, $3, $)""",
#                 r['user_id'], ctx.guild.id, r['channel_id'], r['alias'])
#         await self.bot.db.release(connection)
#         await self.update_cache()
#
#         await self.bot.reply(ctx, text=f"{r['alias']} deleted from twitter tracker")
#         await self.update_cache()
#         await self.send_config(ctx)
#
#
# def setup(bot):
#     """Load Twitter tracker cog into the bot"""
#     bot.add_cog(Twitter(bot))
