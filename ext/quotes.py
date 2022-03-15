"""Commands related to the Quote Database Functionality"""
import random
from typing import List

import asyncpg
from asyncpg import UniqueViolationError
from discord import app_commands, Embed, ButtonStyle, Interaction, Colour, Message, Member
from discord.ext import commands
from discord.ui import Button, View

from ext.utils import view_utils


# TODO: Store Bot.quotes
# TODO: Autocomplete for quote Search

# Delete quotes
class DeleteButton(Button):
    """Button to spawn a new view to delete a quote."""

    def __init__(self, row=None) -> None:
        super().__init__(style=ButtonStyle.red, label="Delete", emoji="🗑️", row=row)

    async def callback(self, interaction):
        """Delete quote by quote ID"""
        r = self.view.pages[self.view.index]

        if r["guild_id"] != interaction.guild.id or interaction.guild.id is None:
            if interaction.user.id not in [r["author_user_id"], r["submitter_user_id"],
                                           self.view.interaction.client.owner_id]:
                return await self.view.update(f"You can't delete other servers quotes.")

        _ = self.view.interaction.user.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or interaction.permissions.manage_messages:
            view = view_utils.Confirmation(self.view.interaction, label_a="Delete", colour_a=ButtonStyle.red,
                                           label_b="Cancel")
            await self.view.interaction.client.reply(content="Delete this quote?", view=view)
            await view.wait()

            if view.value:
                connection = await self.view.interaction.client.db.acquire()
                try:
                    async with connection.transaction():
                        await connection.execute("DELETE FROM quotes WHERE quote_id = $1", r['quote_id'])
                finally:
                    await self.view.interaction.client.db.release(connection)
                await self.view.update(content=f"Quote #{r['quote_id']} has been deleted.")
                self.view.index -= 1 if self.view.index != 0 else 0
            else:
                await self.view.update(content="Quote not deleted")
        else:
            await self.view.update(content="Only people involved with the quote or moderators can delete a quote")


class GlobalButton(Button):
    """Toggle This Server Only or Global"""

    def __init__(self, label, style, row=3) -> None:
        super().__init__(label=label, style=style, row=row, emoji="🌍")

    async def callback(self, interaction: Interaction):
        """Flip the bool."""
        await interaction.response.defer()

        self.view.all_guilds = not self.view.all_guilds
        self.view.pages = self.view.filtered if self.view.all_guilds else self.view.all

        self.view.index = 0
        await self.view.update()


class RandButton(Button):
    """Push a random quote to the view."""

    def __init__(self) -> None:
        super().__init__(row=1, label="Random", emoji="🎲")

    async def callback(self, interaction: Interaction):
        """Randomly select a number"""
        await interaction.response.defer()
        try:
            self.view.index = random.randrange(len(self.view.pages) - 1)
        except ValueError:
            self.view.index = 0
        await self.view.update()


class QuotesView(View):
    """Generic Paginator that returns nothing."""

    def __init__(self, interaction: Interaction, quotes: List[asyncpg.Record], rand=False, last=False) -> None:
        super().__init__()
        self.index: int = 0
        self.all: List[asyncpg.Record] = quotes
        self.filtered = list(filter(lambda x: x['guild_id'] == interaction.guild.id, quotes))
        self.pages = self.filtered
        self.interaction = interaction

        if rand:
            self.index = random.randrange(len(self.pages) - 1)
        elif last:
            self.index = len(self.pages) - 1

        self.all_guilds = False

    async def on_timeout(self) -> None:
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        await self.interaction.client.reply(self.interaction, view=self, followup=False)
        self.stop()

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.interaction.user.id == interaction.user.id

    def embed_quote(self, quote):
        """Create an embed for a list of quotes"""
        e = Embed(color=0x7289DA, description="")
        quote_img = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"

        if quote is None:
            e.colour = Colour.red()
            e.description = "No quotes found"
            return e

        channel = self.interaction.client.get_channel(quote["channel_id"])
        submitter = self.interaction.client.get_user(quote["submitter_user_id"])

        guild = self.interaction.client.get_guild(quote["guild_id"])
        message_id = quote["message_id"]

        try:
            author = self.interaction.client.get_user(quote["author_user_id"])
            e.set_author(name=f"{author.display_name} in #{channel}", icon_url=quote_img)
            e.set_thumbnail(url=author.display_avatar.url)
        except AttributeError:
            e.set_author(name=f"Deleted User in #{channel}")
            e.set_thumbnail(url=quote_img)

        try:
            link = f"https://discordapp.com/channels/{guild.id}/{quote['channel_id']}/{message_id}"
            e.description += f"**__[Quote #{quote['quote_id']}]({link})__**\n"
        except AttributeError:
            e.description += f"**__Quote #{quote['quote_id']}__**\n"

        e.description += quote["message_content"]

        try:
            e.set_footer(text=f"Added by {submitter}", icon_url=submitter.display_avatar.url)
        except AttributeError:
            e.set_footer(text="Added by a Deleted User")

        e.timestamp = quote["timestamp"]
        return e

    async def update(self, content: str = "") -> Message:
        """Refresh the view and send to user"""
        self.clear_items()
        self.add_item(view_utils.FirstButton(disabled=True if self.index == 0 else False))
        self.add_item(view_utils.Previous(disabled=True if self.index == 0 else False))
        self.add_item(view_utils.PageButton(disabled=True if len(self.pages) == 1 else False,
                                            label=f"Page {self.index + 1} of {len(self.pages)}"))
        self.add_item(view_utils.Next(disabled=True if self.index == len(self.pages) - 1 else False))
        self.add_item(view_utils.LastButton(disabled=True if self.index == len(self.pages) - 1 else False))
        self.add_item(RandButton())
        self.add_item(GlobalButton(label="All" if not self.all_guilds else self.interaction.guild.name + " Only",
                                   style=ButtonStyle.blurple if not self.all_guilds else ButtonStyle.gray))
        self.add_item(view_utils.Stop())

        try:
            q = self.pages[self.index]
            is_mod = self.interaction.permissions.manage_messages
            if self.interaction.user.id in [q['author_user_id'], q['submitter_user_id']] or is_mod:
                self.add_item(DeleteButton(row=3))
        except IndexError:
            q = None

        e = self.embed_quote(q)
        return await self.interaction.client.reply(self.interaction, content=content, embed=e, view=self)


OPT_IN = "You are currently opted out of quotes, opting back in will allow " \
         "others to add quotes from you to the database. Are you sure?"


async def get_quote(interaction: Interaction, quote_id=None, qry=None, rand=False, last=False):
    """Get quotes."""
    connection = await interaction.client.db.acquire()

    try:
        async with connection.transaction():
            if quote_id is not None:
                r = await connection.fetch("""SELECT * FROM quotes WHERE quote_id = $1""", quote_id)
                if not r:
                    return await interaction.client.error(interaction, f"Quote #{quote_id} was not found.")
            elif qry is not None:
                r = await connection.fetch("""SELECT * FROM quotes WHERE message_content ~~* $1""", qry)
                if not r:
                    return await interaction.client.error(interaction, f"No quotes matching '{qry}' found.")
            else:
                r = await connection.fetch("""SELECT * FROM quotes""")
    finally:
        await interaction.client.db.release(connection)

    view = QuotesView(interaction, r, rand, last)
    await view.update()


# MESSAGE COMMAND, (right click message -> Add quote)
@app_commands.context_menu(name="Add to QuoteDB")
async def quote_add(interaction, message: Message):
    """Add a quote, either by message ID or grabs the last message a user sent"""
    if interaction.user.id in interaction.client.quote_blacklist:
        return await interaction.client.error(interaction, "You have opted out of quotes.")

    elif message.author.id in interaction.client.quote_blacklist:
        return await interaction.client.error(interaction, "That user has opted out of quotes, quote cannot be added.")

    await interaction.response.defer(thinking=True)

    if interaction.guild is None:
        return await interaction.client.error(interaction, "This cannot be used in DMs")

    if message.author.id == interaction.user.id:
        return await interaction.client.error(interaction, "You can't quote yourself.")
    elif message.author.bot:
        return await interaction.client.error(interaction, "You can't quote a bot.")

    if not message.content:
        return await interaction.client.error(interaction, 'That message has no content.')

    connection = await interaction.client.db.acquire()

    try:
        async with connection.transaction():
            r = await connection.fetchrow(
                """INSERT INTO quotes
                (channel_id,guild_id,message_id,author_user_id,submitter_user_id,message_content,timestamp)
                VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
                message.channel.id, message.guild.id, message.id, message.author.id, interaction.user.id,
                message.content, message.created_at)

        await QuotesView(interaction, [r]).update(content="Quote added to database.")
    except UniqueViolationError:
        await interaction.client.error(interaction, "That quote is already in the database!")
    finally:
        await interaction.client.db.release(connection)


# USER COMMANDS: right click user
@app_commands.context_menu(name="QuoteDB: Get Quotes")
async def u_quote(interaction, usr: Member):
    """Get a random quote from this user."""
    if interaction.user.id in interaction.client.quote_blacklist:
        return await interaction.client.error(interaction, "You have opted out of quotes.")

    connection = await interaction.client.db.acquire()
    try:
        async with connection.transaction():
            sql = """SELECT * FROM quotes WHERE author_user_id = $1 ORDER BY random()"""
            r = await connection.fetch(sql, usr.id)
    finally:
        await interaction.client.db.release(connection)

    view = QuotesView(interaction, r)
    await view.update()


@app_commands.context_menu(name="QuoteDB: Get Stats")
async def quote_stats(interaction, member: Member):
    """See quote stats for a user"""
    if interaction.user.id in interaction.client.quote_blacklist:
        return await interaction.client.error(interaction, "You have opted out of quotes.")

    sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                    (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                    (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                    (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
    escaped = [member.id, interaction.guild.id]

    connection = await interaction.client.db.acquire()
    async with connection.transaction():
        r = await connection.fetchrow(sql, *escaped)
    await interaction.client.db.release(connection)

    e = Embed(color=Colour.og_blurple(), description=member.mention)
    e.set_author(icon_url="https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png", name="Quote Stats")
    e.set_thumbnail(url=member.display_avatar.url)
    if interaction.guild:
        e.add_field(name=interaction.guild.name, value=f"Quoted {r['auth_g']} times.\n Added {r['sub_g']} quotes.", )
    e.add_field(name="Global", value=f"Quoted {r['author']} times.\n Added {r['sub']} quotes.", inline=False)
    await interaction.client.reply(interaction, embed=e)


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(quote_add)
        self.bot.tree.add_command(quote_stats)
        self.bot.tree.add_command(u_quote)

    async def cog_load(self):
        """When the cog loads..."""
        await self.opt_outs()

    quotes = app_commands.Group(name="quotes", description="Get or add quotes to the quote database")

    @quotes.command()
    async def random(self, interaction):
        """Get a random quote."""
        if interaction.user.id in interaction.client.quote_blacklist:
            return await interaction.client.error(interaction, "You have opted out of quotes.")

        await get_quote(interaction, rand=True)

    @quotes.command()
    async def last(self, interaction):
        """Get the most recent quote"""
        if interaction.user.id in self.bot.quote_blacklist:
            return await self.bot.error(interaction, "You have opted out of quotes.")

        await get_quote(interaction, last=True)

    @quotes.command()
    @app_commands.describe(text="Search by quote text")
    async def search(self, interaction: Interaction, text: str):
        """Search for a quote by quote text"""
        if interaction.user.id in self.bot.quote_blacklist:
            return await self.bot.error(interaction, "You have opted out of quotes.")

        await get_quote(interaction, qry=text)

    @quotes.command()
    @app_commands.describe(quote_id="Enter quote ID#")
    async def id(self, interaction: Interaction, quote_id: int):
        """Get a quote by its ID Number"""
        if interaction.user.id in self.bot.quote_blacklist:
            return await self.bot.error(interaction, "You have opted out of quotes.")

        await get_quote(interaction, quote_id=quote_id)

    @quotes.command()
    async def opt_out(self, interaction: Interaction):
        """Remove all quotes about, or added by you, and prevent future quotes being added."""
        if interaction.user.id in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            v = view_utils.Confirmation(interaction, label_a="Opt In", colour_a=ButtonStyle.green, label_b="Cancel")
            v.message = await self.bot.reply(interaction, content=OPT_IN)
            await v.wait()

            if v.value:  # User has chosen to opt in.
                connection = await self.bot.db.acquire()
                try:
                    await connection.execute("""DELETE FROM quotes_optout WHERE userid = $1""", interaction.user.id)
                finally:
                    await self.bot.db.release(connection)
                await v.message.edit(content="You have opted back into the Quotes Database.", view=None)
            else:
                await v.message.edit(content="Opt in cancelled, quotes cannot be added about you.", view=None)
        else:
            sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                            (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
            escaped = [interaction.user.id, interaction.guild.id]

            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    r = await connection.fetchrow(sql, *escaped)
            finally:
                await self.bot.db.release(connection)

            # Warn about quotes that will be deleted.
            if not all(v == 0 for v in [r['auth'], r['auth_g'], r['sub'], r['sub_g']]):
                auth = f"You have been quoted {r['auth']} times" if r['auth'] else ""
                if interaction.guild is not None:
                    auth += f" ({r['auth_g']} times on {interaction.guild.name})" if r['auth_g'] else ""

                sub = f"You have submitted {r['sub']} quotes" if r['sub'] else ""
                if interaction.guild is not None:
                    sub += f" ({r['sub_g']} times on {interaction.guild.name})" if r['sub_g'] else ""

                msg = ("\n".join([i for i in [auth, sub] if i]) +
                       "\n\n**ALL of these quotes will be deleted if you opt out.**")

                e = Embed(colour=Colour.red(), title="Your quotes will be deleted if you opt out.", description=msg)
            else:
                e = None

            v = view_utils.Confirmation(interaction, label_a="Opt out", colour_a=ButtonStyle.red, label_b="Cancel")
            v.message = await interaction.client.reply(interaction, content="Opt out of QuoteDB?", embed=e, view=v)

            if not v.value:
                return await v.message.edit(content="Opt out cancelled, you can still quote and be quoted", view=None)
            else:
                if e is not None:
                    connection = await interaction.client.db.acquire()
                    try:
                        async with connection.transaction():
                            sql = """DELETE FROM quotes WHERE author_user_id = $1 OR submitter_user_id = $2"""
                            r = await connection.execute(sql, interaction.user.id, interaction.user.id)
                    finally:
                        await interaction.client.db.release(connection)
                    e.description = r.split(' ')[-1] + " quotes were deleted."

            await v.message.edit(content=f"You were opted out of the quote DB", embed=e)

    async def opt_outs(self):
        """Cache the list of users who have opted out of the quote DB"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM quotes_optout""")
                self.bot.quote_blacklist = [r['userid'] for r in records]
        finally:
            await self.bot.db.release(connection)


async def setup(bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
