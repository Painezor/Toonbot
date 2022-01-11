"""Commands related to the Quote Database Functionality"""

import discord
from asyncpg import UniqueViolationError
from discord import Option
from discord.ext import commands

from ext.utils import view_utils

# TODO: Optout command.


MEMBER = Option(discord.Member, "Get a quote from a specific user", required=False, default=None)
QUOTE_ID = Option(int, "Get a quote by it's ID number", required=False, default=None)
MESSAGE_ID = Option(int, "Add a message to the quote DB by it's ID number", required=False, default=None)
ALL_SERVERS = Option(bool, "Include all servers?", required=False, default=False)
MOST_RECENT = Option(bool, "Get the most recent quote only?", required=False, default=False)


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot):
        self.bot = bot

    async def embed_quotes(self, records: list):
        """Create an embed for a list of quotes"""
        embeds = []
        for r in records:
            # Fetch data.
            channel = self.bot.get_channel(r["channel_id"])
            submitter = self.bot.get_user(r["submitter_user_id"])
    
            guild = self.bot.get_guild(r["guild_id"])
            message_id = r["message_id"]
            
            e = discord.Embed(color=0x7289DA, description="")
            quote_img = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"
            try:
                author = self.bot.get_user(r["author_user_id"])
                e.set_author(name=f"{author.display_name} in #{channel}", icon_url=quote_img)
                e.set_thumbnail(url=author.display_avatar.url)
            except AttributeError:
                e.set_author(name=f"Deleted User in #{channel}")
                e.set_thumbnail(url=quote_img)
            
            try:
                jumpurl = f"https://discordapp.com/channels/{guild.id}/{r['channel_id']}/{message_id}"
                e.description += f"**__[Quote #{r['quote_id']}]({jumpurl})__**\n"
            except AttributeError:
                e.description += f"**__Quote #{r['quote_id']}__**\n"
            
            e.description += r["message_content"]
                
            try:
                e.set_footer(text=f"Added by {submitter}", icon_url=submitter.display_avatar.url)
            except AttributeError:
                e.set_footer(text="Added by a Deleted User")
            
            e.timestamp = r["timestamp"]
            embeds.append(e)
        return embeds

    async def _get_quote(self, ctx, users=None, quote_id=None, all_guilds=False, random=True, qry=None):
        """Get a quote."""
        sql = """SELECT * FROM quotes"""
        multi = False
        if quote_id:
            all_guilds = True  # (override it.)
            sql += """ WHERE quote_id = $1"""
            escaped = [quote_id]
            success = f"Displaying quote #{quote_id}"
            failure = f"Quote #{quote_id} was not found."
        elif qry:
            multi = True
            random = False
            # TODO: tsvector column, index, search query.
            # sql ="""SELECT * FROM quotes WHERE to_tsvector(message_content) @@ phraseto_tsquery($1)"""
            sql += """ WHERE message_content ILIKE $1"""
            escaped = [f"%{qry}%"]
            success = f"Displaying matching quotes for {qry}"
            failure = f"Found no matches for {qry}"
        else:
            escaped = []
            success = "Displaying random quote"
            failure = "Couldn't find any quotes"

        if users:  # Returned from discord.Greedy
            and_where = "WHERE" if not escaped else "AND"
            sql += f""" {and_where} author_user_id in (${len(escaped) + 1})"""
            escaped += [i.id for i in users]
            success += " from specified user(s)"
            failure += " from specified user(s)"

        if not all_guilds:
            and_where = "WHERE" if not escaped else "AND"
            sql += f""" {and_where} guild_id = ${len(escaped) + 1}"""
            escaped += [ctx.guild.id]
            success += f" from {ctx.guild.name}"
            failure += f" from {ctx.guild.name}"

        if random:
            sql += """ ORDER BY random()"""
        else:
            success = success.replace('random', 'most recent')
            sql += """ ORDER BY quote_id DESC"""
        
        # Fetch.
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            if multi:
                r = await connection.fetch(sql, *escaped)
            else:
                r = await connection.fetchrow(sql, *escaped)
                if r:
                    r = [r]

        await self.bot.db.release(connection)

        if not r:
            return await self.bot.error(ctx, failure)

        embeds = await self.embed_quotes(r)
        view = view_utils.Paginator(ctx, embeds)
        view.message = await self.bot.reply(ctx, content=f"Fetching {success}", view=view)
        await view.update()

    @commands.slash_command()
    async def quote(self, ctx, quote_id: QUOTE_ID, user: MEMBER, include_all_servers: ALL_SERVERS, recent: MOST_RECENT):
        """Get a random quote from this server."""
        await self._get_quote(ctx, quote_id=quote_id, users=[user], all_guilds=include_all_servers, random=recent)

    # Add quote
    @commands.slash_command()
    async def quote_add(self, ctx, user: MEMBER, message_id: MESSAGE_ID):
        """Add a quote, either by message ID or grabs the last message a user sent"""
        await ctx.interaction.response.defer()

        if ctx.guild is None:
            return await self.bot.error(ctx, "This command cannot be used in DMs")

        if message_id is not None:
            try:
                m = ctx.channel.fetch_message(message_id)
            except discord.NotFound:
                return await self.bot.error(ctx, "Could not find that message.")

        elif user is not None:
            messages = await ctx.history(limit=50).flatten()
            m = discord.utils.get(messages, channel=ctx.channel, author=user)
            if not m:
                return await self.bot.error(ctx, "No messages from that user found in last 50 channel messages.")

        else:
            return await self.bot.error(ctx, "You need to specify either a message ID or a user to quote.")

        if m.author.id == ctx.author.id:
            return await self.bot.errorr(ctx, "You can't quote yourself.")
        elif m.author.bot:
            return await self.bot.errorr(ctx, "You can't quote a bot.")

        if not m.content:
            return await self.bot.error(ctx, 'That message has no content.')

        message = await self.bot.reply(ctx, content="Attempting to add quote to db...")
        connection = await self.bot.db.acquire()

        try:
            ch = m.channel.id
            gu = m.guild.id
            ms = m.id
            au = m.author.id
            qu = ctx.author.id
            st = m.clean_content
            dt = m.created_at

            async with connection.transaction():
                r = await connection.fetchrow(
                    """INSERT INTO quotes
                    (channel_id,guild_id,message_id,author_user_id,submitter_user_id,message_content,timestamp)
                    VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""", ch, gu, ms, au, qu, st, dt)
            e = await self.embed_quotes([r])
            await message.edit(content=":white_check_mark: Successfully added quote to database", embed=e[0])
        except UniqueViolationError:
            await self.bot.error(ctx, "That quote is already in the database!", message=message)
        finally:
            await self.bot.db.release(connection)

    @commands.slash_command()
    async def quote_search(self, ctx, *, text):
        """Search for a quote by quote text"""
        await self._get_quote(ctx, qry=text)

    # Delete quotes
    @commands.slash_command()
    async def quote_delete(self, ctx, quote_id: Option(int, "Enter quote ID number")):
        """Delete quote by quote ID"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow(f"SELECT * FROM quotes WHERE quote_id = $1", quote_id)
        await self.bot.db.release(connection)

        if r is None:
            return await self.bot.error(ctx, f"No quote found with ID #{quote_id}")

        if r["guild_id"] != ctx.guild.id:
            if ctx.author.id not in [r["author_user_id"], r["submitter_user_id"], self.bot.owner_id]:
                return await self.bot.error(ctx, f"You can't delete other servers quotes.")

        e = await self.embed_quotes([r])
        e = e[0]  # There will only be one quote to return for this.

        async def delete(message):
            """Delete a quote from the database"""
            c = await self.bot.db.acquire()
            async with c.transaction():
                await c.execute("DELETE FROM quotes WHERE quote_id = $1", quote_id)
            await self.bot.db.release(c)
            await message.edit(content=f"Quote #{quote_id} has been deleted.", view=None, embed=None)

        _ = ctx.author.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or ctx.channel.permissions_for(ctx.author).manage_messages:

            view = view_utils.Confirmation(ctx, label_a="Delete", colour_a=discord.ButtonStyle.red, label_b="Cancel")
            m = await self.bot.reply(ctx, content="Delete this quote?", embed=e, view=view)
            view.message = m
            if view.value:
                await delete(message=m)
            else:
                await m.edit(content="Quote not deleted", embed=None, view=None)
        else:
            return await self.bot.error(ctx, "Only people involved with the quote or moderators can delete a quote")

    # Quote Stats.
    @commands.slash_command()
    async def quote_stats(self, ctx, user: MEMBER):
        """See quote stats for a user"""
        target = ctx.author if user is None else user
        e = discord.Embed(color=discord.Color.og_blurple())

        try:
            e.description = target.mention
        except AttributeError:
            e.description = str(target)

        sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                        (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                        (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                        (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
        escaped = [target.id, ctx.guild.id]

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow(sql, *escaped)
        await self.bot.db.release(connection)

        e.set_author(icon_url="https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png", name="Quote Stats")

        e.set_thumbnail(url=target.display_avatar.url)
        if ctx.guild:
            e.add_field(name=ctx.guild.name, value=f"Quoted {r['auth_g']} times.\n Added {r['sub_g']} quotes.", )
        e.add_field(name="Global", value=f"Quoted {r['author']} times.\n Added {r['sub']} quotes.", inline=False)
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the quote database module into the bot"""
    bot.add_cog(QuoteDB(bot))
