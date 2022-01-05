"""Commands related to the Quote Database Functionality"""
import asyncio
import typing
from importlib import reload

import discord
from asyncpg import UniqueViolationError
from discord.ext import commands

from ext.utils import embed_utils, view_utils


# TODO: Select / Button Pass.

class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot):
        self.bot = bot
        self.emoji = "💬"
        reload(embed_utils)

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
            return await self.bot.reply(ctx, content=failure)

        embeds = await self.embed_quotes(r)
        view = view_utils.Paginator(ctx.author, embeds)
        view.message = await self.bot.reply(ctx, content=f"Fetching {success}", view=view)
        await view.update()

    @commands.group(invoke_without_command=True, aliases=["quotes"],
                    usage="[quote id number or a @user to search quotes from them]")
    async def quote(self, ctx, quote_id: typing.Optional[int], users: commands.Greedy[discord.User]):
        """Get a random quote from this server. (optionally by Quote ID# or user(s)."""
        if len(str(quote_id)) > 6:
            return await self.bot.reply(ctx, content="Too long to be a quote ID. if you're trying to add a quote, "
                                                     f"use `{ctx.prefix}quote add number` instead")
        await self._get_quote(ctx, quote_id=quote_id, users=users)

    # Add quote
    @quote.command(invoke_without_command=True, usage="quote add [message id or message link "
                                                      "or @member to grab their last message]")
    @commands.guild_only()
    async def add(self, ctx, target: typing.Union[discord.Message, discord.User]):
        """Add a quote, either by message ID or grabs the last message a user sent"""
        if isinstance(target, discord.Member):
            messages = await ctx.history(limit=50).flatten()
            m = discord.utils.get(messages, channel=ctx.channel, author=target)
            if not m:
                return await self.bot.reply(ctx, content="No messages from that user found in last 50 messages, "
                                                         "please use message's id or link")

        elif isinstance(target, discord.Message):
            m = target
        else:
            return await self.bot.reply(ctx, content='Invalid argument provided for target.')

        if m.author.id == ctx.author.id:
            return await self.bot.reply(ctx, content="You can't quote yourself.")

        if not m.content:
            return await self.bot.reply(ctx, content='That message has no content.')

        await self.bot.reply(ctx, content="Attempting to add quote to db...", delete_after=5)
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
            await self.bot.reply(ctx, content=":white_check_mark: Successfully added quote to database", embed=e[0])
        except UniqueViolationError:
            await self.bot.reply(ctx, content="That quote is already in the database!")
        finally:
            await self.bot.db.release(connection)

    # Find quote
    @quote.command(aliases=['global'], usage="[Optional: @member]")
    async def all(self, ctx, users: commands.Greedy[discord.User]):
        """Get a random quote from any server, optionally from a specific user."""
        await self._get_quote(ctx, users=users, all_guilds=True)

    @quote.group(usage="<message text to search for>)", invoke_without_command=True)
    async def search(self, ctx, *, qry: commands.clean_content):
        """Search for a quote by quote text"""
        await self._get_quote(ctx, qry=qry)

    @search.command(name="all", usage="<message text to search for>", aliases=['global'])
    async def _all(self, ctx, *, qry: commands.clean_content):
        """Search for a quote **from any server** by quote text"""
        await self._get_quote(ctx, qry=qry, all_guilds=True)

    @quote.group(invoke_without_command=True, usage='[@user]')
    async def last(self, ctx, users: commands.Greedy[discord.User]):
        """Gets the last quoted message (optionally from user)"""
        await self._get_quote(ctx, users=users, random=False)

    @last.command(name="all", aliases=['global'], usage="quote last all (Optional: @member @member2)")
    async def last_all(self, ctx, users: commands.Greedy[discord.User]):
        """Gets the last quoted message (optionally from users) from any server."""
        await self._get_quote(ctx, users=users, random=False, all_guilds=True)

    # Delete quotes
    @quote.command(name="del", aliases=['remove'], usage="<quote id number to delete>")
    @commands.guild_only()
    async def _del(self, ctx, quote_id: int):
        """Delete quote by quote ID"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow(f"SELECT * FROM quotes WHERE quote_id = $1", quote_id)
        await self.bot.db.release(connection)
        
        if r is None:
            return await self.bot.reply(ctx, content=f"No quote found with ID #{quote_id}")

        if r["guild_id"] != ctx.guild.id:
            if ctx.author.id != self.bot.owner_id:
                return await self.bot.reply(ctx, content=f"You can't delete other servers quotes.")

        e = await self.embed_quotes([r])
        e = e[0]  # There will only be one quote to return for this.

        async def delete():
            """Delete a quote from the database"""
            c = await self.bot.db.acquire()
            async with c.transaction():
                await c.execute("DELETE FROM quotes WHERE quote_id = $1", quote_id)
            await self.bot.db.release(c)
            await self.bot.reply(ctx, content=f"Quote #{quote_id} has been deleted.")

        _ = ctx.author.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or ctx.channel.permissions_for(ctx.author).manage_messages:
            try:
                m = await self.bot.reply(ctx, content="Delete this quote?", embed=e)
                await embed_utils.bulk_react(ctx, m, ["👍", "👎"])
            except AssertionError:  # Skip confirm if can't react.
                return await delete()

            def check(reaction, user):
                """Verify user reacting is the invoker of the command"""
                if reaction.message.id == m.id and user == ctx.author:
                    emoji = str(reaction.emoji)
                    return emoji.startswith(("👍", "👎"))

            try:
                res = await self.bot.wait_for("reaction_add", check=check, timeout=30)
            except asyncio.TimeoutError:
                await m.clear_reactions()
                return await self.bot.reply(ctx, content="Response timed out after 30 seconds, quote not deleted")
            res = res[0]

            if res.emoji.startswith("👎"):
                await self.bot.reply(ctx, content=f"Quote {quote_id} was not deleted")

            elif res.emoji.startswith("👍"):
                await delete()
            await m.clear_reactions()
        else:
            return await self.bot.reply(ctx,
                                        content="Only people involved with the quote or moderators can delete quotes")
        
    # Quote Stats.
    @quote.command(usage="<#channel or @user>")
    async def stats(self, ctx, target: typing.Union[discord.Member, discord.TextChannel] = None):
        """See quote stats for a user or channel"""
        e = discord.Embed(color=discord.Color.og_blurple())
        if target is None:
            target = ctx.author
        try:
            e.description = target.mention
        except AttributeError:
            e.description = str(target)

        if isinstance(target, discord.Member):
            sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                            (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
            escaped = [target.id, ctx.guild.id]
        else:
            sql = """SELECT (SELECT COUNT(*) FROM quotes) AS total,
                            (SELECT COUNT(*) FROM quotes WHERE guild_id = $1) AS guild,
                            (SELECT COUNT(*) FROM quotes WHERE channel_id = $2) AS channel"""
            escaped = [ctx.guild.id, target.id]
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow(sql, *escaped)
        await self.bot.db.release(connection)

        e.set_author(icon_url="https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png", name="Quote Stats")

        if isinstance(target, discord.Member):
            e.set_thumbnail(url=target.display_avatar.url)
            if ctx.guild:
                e.add_field(name=ctx.guild.name, value=f"Quoted {r['auth_g']} times.\n Added {r['sub_g']} quotes.",
                            inline=False)
            e.add_field(name="Global", value=f"Quoted {r['author']} times.\n Added {r['sub']} quotes.", inline=False)
        else:
            e.set_thumbnail(url=target.guild.icon.url)
            e.add_field(name="Channel quotes", value=f"{r['channel']} quotes from in this channel", inline=False)
            e.add_field(name=f"{target.guild.name} quotes", value=f"{r['guild']} quotes found from this guild.",
                        inline=False)
            e.add_field(name="All Quotes", value=f"{r['total']} total quotes in database", inline=False)
        e.set_footer(text=f"This information was requested by {ctx.author}")
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the quote database module into the bot"""
    bot.add_cog(QuoteDB(bot))
