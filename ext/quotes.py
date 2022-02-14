"""Commands related to the Quote Database Functionality"""
import random
import typing

import asyncpg
import discord
from asyncpg import UniqueViolationError
from discord import Option, SlashCommandGroup
from discord.ext import commands

from ext.utils import view_utils


# Delete quotes
class DeleteButton(discord.ui.Button):
    """Button to spawn a new view to delete a quote."""

    def __init__(self):
        super().__init__(style=discord.ButtonStyle.red, label="Delete", emoji="🗑️")

    async def callback(self, interaction):
        """Delete quote by quote ID"""
        r = self.view.current_quote

        if r["guild_id"] != interaction.guild.id:
            if interaction.user.id not in [r["author_user_id"], r["submitter_user_id"], self.view.ctx.bot.owner_id]:
                return await self.view.update(f"You can't delete other servers quotes.")

        _ = self.view.ctx.author.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or self.view.ctx.channel.permissions_for(self.view.ctx.author).manage_messages:
            view = view_utils.Confirmation(self.view.ctx, label_a="Delete", colour_a=discord.ButtonStyle.red,
                                           label_b="Cancel")
            m = await self.view.message.edit(content="Delete this quote?", view=view)
            view.message = m

            await view.wait()

            if view.value:
                connection = await self.view.ctx.bot.db.acquire()
                try:
                    async with connection.transaction():
                        await connection.execute("DELETE FROM quotes WHERE quote_id = $1", r['quote_id'])
                finally:
                    await self.view.ctx.bot.db.release(connection)
                await self.view.update(content=f"Quote #{r['quote_id']} has been deleted.")
            else:
                await self.view.update(content="Quote not deleted")
        else:
            await self.view.update("Only people involved with the quote or moderators can delete a quote")


class GlobalButton(discord.ui.Button):
    """Toggle This Server Only or Global"""

    def __init__(self, all_guilds: bool, row=1):
        style = discord.ButtonStyle.blurple if all_guilds else discord.ButtonStyle.gray
        label = "All Servers" if all_guilds else self.view.ctx.guild.name + " Only"
        super().__init__(style=style, label=label, row=row, emoji="🌍")

    async def callback(self, interaction: discord.Interaction):
        """Flip the bool."""
        await interaction.response.defer()
        self.view.all_guilds = not self.view.all_guilds
        self.view.index = 0
        await self.view.update()


class RandButton(discord.ui.Button):
    """Push a random quote to the view."""

    def __init__(self):
        super().__init__(row=0, label="Random", emoji="🎲")

    async def callback(self, interaction: discord.Interaction):
        """Randomly select a number"""
        await interaction.response.defer()
        self.view.index = random.randrange(len(self.view.pages) - 1)
        await self.view.update()


class Paginator(discord.ui.View):
    """Generic Paginator that returns nothing."""

    def __init__(self, ctx, quotes: typing.List[asyncpg.Record], rand=False, last=False):
        super().__init__()
        self.index = 0
        self.quotes = quotes
        self.pages = []
        self.ctx = ctx
        self.message = None

        self.first_random = rand
        self.first_last = last

        self.current_quote = None
        self.all_guilds = False

    async def on_timeout(self):
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        self.stop()
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.ctx.author.id == interaction.user.id

    def embed_quote(self):
        """Create an embed for a list of quotes"""
        r = self.current_quote

        channel = self.ctx.bot.get_channel(r["channel_id"])
        submitter = self.ctx.bot.get_user(r["submitter_user_id"])

        guild = self.ctx.bot.get_guild(r["guild_id"])
        message_id = r["message_id"]

        e = discord.Embed(color=0x7289DA, description="")
        quote_img = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"
        try:
            author = self.ctx.bot.get_user(r["author_user_id"])
            e.set_author(name=f"{author.display_name} in #{channel}", icon_url=quote_img)
            e.set_thumbnail(url=author.display_avatar.url)
        except AttributeError:
            e.set_author(name=f"Deleted User in #{channel}")
            e.set_thumbnail(url=quote_img)

        try:
            link = f"https://discordapp.com/channels/{guild.id}/{r['channel_id']}/{message_id}"
            e.description += f"**__[Quote #{r['quote_id']}]({link})__**\n"
        except AttributeError:
            e.description += f"**__Quote #{r['quote_id']}__**\n"

        e.description += r["message_content"]

        try:
            e.set_footer(text=f"Added by {submitter}", icon_url=submitter.display_avatar.url)
        except AttributeError:
            e.set_footer(text="Added by a Deleted User")

        e.timestamp = r["timestamp"]
        return e

    async def update(self, content=""):
        """Refresh the view and send to user"""
        _ = filter(lambda x: x['guild_id'] == self.ctx.guild.id, self.quotes) if self.all_guilds else self.quotes
        self.pages = _

        if self.first_last:
            self.first_last = False
            self.index = len(self.pages) - 1

        if self.first_random:
            self.first_random = False
            self.index = random.randrange(len(self.pages) - 1)

        self.current_quote = _[self.index]

        self.clear_items()

        _ = view_utils.PreviousButton()
        _.disabled = True if self.index == 0 else False
        self.add_item(_)

        _ = view_utils.PageButton()
        _.label = f"Page {self.index + 1} of {len(self.quotes)}"
        _.disabled = True if len(self.quotes) == 1 else False
        self.add_item(_)

        _ = view_utils.NextButton()
        _.disabled = True if self.index == len(self.quotes) - 1 else False
        self.add_item(_)

        self.add_item(RandButton())
        self.add_item(DeleteButton())
        self.add_item(GlobalButton(self.all_guilds))
        self.add_item(view_utils.StopButton(row=1))

        await self.message.edit(content=content, embed=self.embed_quote(), view=self)
        await self.wait()


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.opt_outs())
        self.blacklist = []

    async def opt_outs(self):
        """Cache the list of users who have opted out of the quote DB"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM quotes_optout""")
                self.blacklist = [r['userid'] for r in records]
        finally:
            await self.bot.db.release(connection)

    async def get_quote(self, ctx, quote_id=None, qry=None, rand=False, last=False):
        """Get quotes."""
        connection = await self.bot.db.acquire()

        try:
            async with connection.transaction():
                if quote_id is not None:
                    r = await connection.fetch("""SELECT * FROM quotes WHERE quote_id = $1""", quote_id)
                    if not r:
                        return await ctx.error(f"Quote #{quote_id} was not found.")
                elif qry is not None:
                    r = await connection.fetch("""SELECT * FROM quotes WHERE message_content ~~* $1""", qry)
                    if not r:
                        return await ctx.error(f"No quotes matching '{qry}' found.")
                else:
                    r = await connection.fetch("""SELECT * FROM quotes""")
        finally:
            await self.bot.db.release(connection)

        view = Paginator(ctx, r, rand, last)
        view.message = await self.bot.reply(ctx, content=f"Grabbing quotes.", view=view)
        await view.update()

    # Options for quote SlashCommands.
    SEARCH = Option(str, "Quote text to search for")

    quote = SlashCommandGroup("QuoteDB", "Get quotes from the database")

    @quote.command()
    async def optout(self, ctx):
        """Remove all quotes about, or added by you, and prevent future quotes being added."""
        if ctx.author.id in self.blacklist:
            #   Opt Back In confirmation Dialogue
            view = view_utils.Confirmation(ctx, label_a="Opt In", colour_a=discord.ButtonStyle.green, label_b="Cancel")
            view.message = await self.bot.reply(ctx, "You are currently opted out of quotes, opting back in will allow "
                                                     "others to add quotes from you to the database. Are you sure?")
            await view.wait()

            if view.value:  # User has chosen to opt in.
                connection = await self.bot.db.acquire()
                try:
                    await connection.execute("""DELETE FROM quotes_optout WHERE userid = $1""", ctx.author.id)
                finally:
                    await self.bot.db.release(connection)
                await view.message.edit(content="You have opted back into the Quotes Database.", view=None)
            else:
                await view.message.edit(content="Opt in cancelled, quotes cannot be added about you.", view=None)
        else:
            sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                            (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
            escaped = [ctx.author.id, ctx.guild.id]

            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    r = await connection.fetchrow(sql, *escaped)
            finally:
                await self.bot.db.release(connection)

            # Warn about quotes that will be deleted.
            if not all(v == 0 for v in [r['auth'], r['auth_g'], r['sub'], r['sub_g']]):
                auth = f"You have been quoted {r['auth']} times" if r['auth'] else ""
                if ctx.guild is not None:
                    auth += f" ({r['auth_g']} times on {ctx.guild.name})" if r['auth_g'] else ""

                sub = f"You have submitted {r['sub']} quotes" if r['sub'] else ""
                if ctx.guild is not None:
                    sub += f" ({r['sub_g']} times on {ctx.guild.name})" if r['sub_g'] else ""

                msg = ("\n".join([i for i in [auth, sub] if i]) +
                       "\n\n**ALL of these quotes will be deleted if you opt out.**")

                e = discord.Embed()
                e.colour = discord.Colour.red()
                e.title = "Your quotes will be deleted if you opt out."
                e.description = msg
            else:
                e = None

            view = view_utils.Confirmation(ctx, label_a="Opt out", colour_a=discord.ButtonStyle.red, label_b="Cancel")
            view.message = await self.bot.reply(ctx, "Are you sure you wish to opt out of the quote database?",
                                                embed=e, view=view)

            if not view.value:
                return await view.message.edit(content="Optout cancelled, you can still quote and be quoted", view=None)
            else:
                if e is not None:
                    connection = await self.bot.db.acquire()
                    try:
                        async with connection.transaction():
                            sql = """DELETE FROM quotes WHERE author_user_id = $1 OR submitter_user_id = $2"""
                            r = await connection.execute(sql, ctx.author.id, ctx.author.id)
                    finally:
                        await self.bot.db.release(connection)
                    e.description = r.split(' ')[-1] + " quotes were deleted."

            await view.message.edit(content=f"You were opted out of the quote DB", embed=e)

    @quote.command()
    async def random(self, ctx):
        """Get a random quote."""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        await self.get_quote(ctx, rand=True)

    @quote.command()
    async def id(self, ctx, quote_id: Option(int, "Enter quote ID number")):
        """Get a quote by its ID Number"""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        await self.get_quote(ctx, quote_id=quote_id)

    @quote.command()
    async def last(self, ctx):
        """Get the most recent quote"""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        await self.get_quote(ctx, last=True)

    @quote.command()
    async def search(self, ctx, text: SEARCH):
        """Search for a quote by quote text"""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        await self.get_quote(ctx, qry=text)

    # MESSAGE COMMAND, (right click message -> Add quote)
    @commands.message_command(name="Add to QuoteDB")
    async def quote_add(self, ctx, m):
        """Add a quote, either by message ID or grabs the last message a user sent"""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        if ctx.author.id in self.blacklist:
            return await ctx.error("You cannot add quotes to the database, you have opted out of quotes.")

        elif m.author.id in self.blacklist:
            return await ctx.error("That user has opted out of quotes, quote cannot be added.")

        await ctx.interaction.response.defer()

        if ctx.guild is None:
            return await ctx.error("This cannot be used in DMs")

        if m.author.id == ctx.author.id:
            return await ctx.error("You can't quote yourself.")
        elif m.author.bot:
            return await ctx.error("You can't quote a bot.")

        if not m.content:
            return await ctx.error('That message has no content.')

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
            await message.edit(content="Quote added to database", embed=e[0])
        except UniqueViolationError:
            await ctx.error("That quote is already in the database!", message=message)
        finally:
            await self.bot.db.release(connection)

    # USER COMMANDS: right click user
    @commands.user_command(name="QuoteDB: Get Quotes")
    async def u_quote(self, ctx, usr):
        """Get a random quote from this user."""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                sql = """SELECT * FROM quotes WHERE author_user_id = $1 ORDER BY random()"""
                r = await connection.fetch(sql, usr.id)
                embeds = await self.embed_quotes(r)
        finally:
            await self.bot.db.release(connection)

        view = Paginator(ctx, embeds)
        view.message = await self.bot.reply(ctx, content=f"Grabbing quotes.", view=view)
        await view.update()

    @commands.user_command(name="QuoteDB: Get Stats")
    async def quote_stats(self, ctx, member):
        """See quote stats for a user"""
        if ctx.author.id in self.blacklist:
            return await ctx.error("You have opted out of quotes.")

        e = discord.Embed(color=discord.Color.og_blurple())
        e.description = member.mention

        sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                        (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                        (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                        (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
        escaped = [member.id, ctx.guild.id]

        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow(sql, *escaped)
        await self.bot.db.release(connection)

        e.set_author(icon_url="https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png", name="Quote Stats")

        e.set_thumbnail(url=member.display_avatar.url)
        if ctx.guild:
            e.add_field(name=ctx.guild.name, value=f"Quoted {r['auth_g']} times.\n Added {r['sub_g']} quotes.", )
        e.add_field(name="Global", value=f"Quoted {r['author']} times.\n Added {r['sub']} quotes.", inline=False)
        await self.bot.reply(ctx, embed=e)


def setup(bot):
    """Load the quote database module into the bot"""
    bot.add_cog(QuoteDB(bot))
