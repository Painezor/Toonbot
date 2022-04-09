"""Commands related to the Quote Database Functionality"""
from random import randrange
from typing import List, TYPE_CHECKING, Optional

from asyncpg import UniqueViolationError, Record
from discord import Embed, ButtonStyle, Interaction, Colour, Message, Member
from discord.app_commands import Group, context_menu, describe, autocomplete, Choice
from discord.ext import commands
from discord.ui import Button, View

from ext.utils.view_utils import Stop, Confirmation, add_page_buttons

if TYPE_CHECKING:
    from core import Bot


class OptedOutError(AssertionError):
    """Generic Optout Error Raiser"""


# Delete quotes
class Delete(Button):
    """Button to spawn a new view to delete a quote."""

    def __init__(self, bot: 'Bot', row: int = None) -> None:
        self.bot: Bot = bot
        super().__init__(style=ButtonStyle.red, label="Delete", emoji="🗑️", row=row)

    async def callback(self, interaction: Interaction):
        """Delete quote by quote ID"""
        r = self.view.pages[self.view.index]

        if r["guild_id"] != interaction.guild.id or interaction.guild.id is None:
            if interaction.user.id not in [r["author_user_id"], r["submitter_user_id"], self.bot.owner_id]:
                return await self.view.update(f"You can't delete other servers quotes.")

        _ = self.view.interaction.user.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or interaction.permissions.manage_messages:
            view = Confirmation(self.view.interaction, label_a="Delete", colour_a=ButtonStyle.red, label_b="Cancel")
            await self.bot.reply(interaction, content="Delete this quote?", view=view)
            await view.wait()

            if view.value:
                connection = await self.bot.db.acquire()
                try:
                    async with connection.transaction():
                        await connection.execute("DELETE FROM quotes WHERE quote_id = $1", r['quote_id'])
                finally:
                    await self.bot.db.release(connection)
                await self.view.update(content=f"Quote #{r['quote_id']} has been deleted.")
                self.view.index -= 1 if self.view.index != 0 else 0
            else:
                await self.view.update(content="Quote not deleted")
        else:
            await self.view.update(content="Only people involved with the quote or moderators can delete a quote")


class Global(Button):
    """Toggle This Server Only or Global"""

    def __init__(self, label: str, style: ButtonStyle, row: int = 3) -> None:
        super().__init__(label=label, style=style, row=row, emoji="🌍")

    async def callback(self, interaction: Interaction) -> Message:
        """Flip the bool."""
        await interaction.response.defer()

        self.view.all_guilds = not self.view.all_guilds
        self.view.pages = self.view.filtered if self.view.all_guilds else self.view.all

        self.view.index = 0
        return await self.view.update()


class Rand(Button):
    """Push a random quote to the view."""

    def __init__(self) -> None:
        super().__init__(row=1, label="Random", emoji="🎲")

    async def callback(self, interaction: Interaction) -> Message:
        """Randomly select a number"""
        await interaction.response.defer()
        try:
            self.view.index = randrange(len(self.view.pages) - 1)
        except ValueError:
            self.view.index = 0
        return await self.view.update()


class QuotesView(View):
    """Generic Paginator that returns nothing."""

    def __init__(self, interaction: Interaction, quotes: List[Record],
                 rand: bool = False, last: bool = False, bot: 'Bot' = None) -> None:
        super().__init__()
        self.pages: List[Record] = list(filter(lambda x: x['guild_id'] == interaction.guild.id, quotes))
        self.all: List[Record] = quotes
        self.interaction = interaction
        self.bot: Bot = bot if bot is not None else interaction.client
        self.index: int = 0

        try:
            if rand:
                self.index = randrange(len(self.pages) - 1)
            elif last:
                self.index = len(self.pages) - 1
        except ValueError:
            self.index = 0

        self.all_guilds = False

    async def on_timeout(self) -> Message:
        """Remove buttons and dropdowns when listening stops."""
        self.clear_items()
        self.stop()
        return await self.interaction.client.reply(self.interaction, view=self, followup=False)

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Verify clicker is owner of interaction"""
        return self.interaction.user.id == interaction.user.id

    def embed_quote(self, quote: Record) -> Embed:
        """Create an embed for a list of quotes"""
        e: Embed = Embed(color=0x7289DA, description="")

        if quote is None:
            e.colour = Colour.red()
            e.description = "No quotes found"
            return e

        channel = self.bot.get_channel(quote["channel_id"])
        submitter = self.bot.get_user(quote["submitter_user_id"])

        guild = self.bot.get_guild(quote["guild_id"])
        message_id = quote["message_id"]

        quote_img = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"
        try:
            author = self.bot.get_user(quote["author_user_id"])
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
        add_page_buttons(self)

        self.add_item(Rand())
        self.add_item(Global(label="All" if not self.all_guilds else self.interaction.guild.name + " Only",
                             style=ButtonStyle.blurple if not self.all_guilds else ButtonStyle.gray))
        self.add_item(Stop())

        try:
            q = self.pages[self.index]
            is_mod = self.interaction.permissions.manage_messages
            if self.interaction.user.id in [q['author_user_id'], q['submitter_user_id']] or is_mod:
                self.add_item(Delete(self.bot, row=3))
        except IndexError:
            q = None

        e = self.embed_quote(q)
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


OPT_IN = "You are currently opted out of quotes, opting back in will allow " \
         "others to add quotes from you to the database. Are you sure?"


# MESSAGE COMMAND, (right click message -> Add quote)
@context_menu(name="Add to QuoteDB")
async def quote_add(interaction: Interaction, message: Message) -> Message:
    """Add a quote, either by message ID or grabs the last message a user sent"""
    blacklist: List = getattr(interaction.client, "quote_blacklist")  # We can't use dot notation because client != bot

    if interaction.user.id in blacklist:
        raise OptedOutError
    if message.author.id in blacklist:
        return await interaction.client.error(interaction, "That user has opted out of quotes, quote cannot be added.")
    if interaction.guild is None:
        return await interaction.client.error(interaction, "This cannot be used in DMs")
    if message.author.id == interaction.user.id:
        return await interaction.client.error(interaction, "You can't quote yourself.")
    if message.author.bot:
        return await interaction.client.error(interaction, "You can't quote a bot.")
    if not message.content:
        return await interaction.client.error(interaction, 'That message has no content.')

    await interaction.response.defer(thinking=True)

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
@context_menu(name="QuoteDB: Get Quotes")
async def u_quote(interaction: Interaction, user: Member):
    """Get a random quote from this user."""
    blacklist: List = getattr(interaction.client, "quote_blacklist")  # We can't use dot notation because client != bot

    if interaction.user.id in blacklist:
        raise OptedOutError

    connection = await interaction.client.db.acquire()
    try:
        async with connection.transaction():
            sql = """SELECT * FROM quotes WHERE author_user_id = $1 ORDER BY random()"""
            r = await connection.fetch(sql, user.id)
    finally:
        await interaction.client.db.release(connection)

    view = QuotesView(interaction, r)
    await view.update()


@context_menu(name="QuoteDB: Get Stats")
async def quote_stats(interaction: Interaction, member: Member):
    """See quote stats for a user"""
    blacklist: List = getattr(interaction.client, "quote_blacklist")  # We can't use dot notation because client != bot

    if interaction.user.id in blacklist:
        raise OptedOutError

    sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                    (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                    (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                    (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
    escaped = [member.id, interaction.guild.id]

    connection = await interaction.client.db.acquire()
    async with connection.transaction():
        r = await connection.fetchrow(sql, *escaped)
    await interaction.client.db.release(connection)

    e: Embed = Embed(color=Colour.og_blurple(), description=member.mention)
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

    async def cog_load(self) -> None:
        """When the cog loads..."""
        await self.opt_outs()
        await self.cache_quotes()

    async def opt_outs(self):
        """Cache the list of users who have opted out of the quote DB"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM quotes_optout""")
                self.bot.quote_blacklist = [r['userid'] for r in records]
        finally:
            await self.bot.db.release(connection)

    async def cache_quotes(self):
        """Cache the Quote DB inside the bot for autocomplete etc."""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM quotes""")
        finally:
            await self.bot.db.release(connection)
        for r in records:
            self.bot.quotes.update({r['quote_id']: r})

    quotes = Group(name="quote", description="Get from or add to the quote database")

    @quotes.command()
    async def random(self, interaction: Interaction) -> Message:
        """Get a random quote."""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        return await QuotesView(interaction, self.bot.quotes.values(), rand=True).update()

    @quotes.command()
    async def last(self, interaction: Interaction) -> Message:
        """Get the most recent quote"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        return await QuotesView(interaction, self.bot.quotes.values(), last=True).update()

    async def quote_ac(self, interaction: Interaction, current: str):
        """Autocomplete from guild quotes"""
        results = list(self.bot.quotes.values())
        results = list(filter(lambda x: x['guild_id'] == interaction.guild.id, results))
        if interaction.namespace.user is not None:
            results = list(filter(lambda x: x['author_id'] == interaction.namespace.user.id, results))

        results = [Choice(name=f"#{r['quote_id']}: {r['message_content']}"[:100],
                          value=r['quote_id']) for r in results if current.lower() in r['message_content'].lower()]
        return results[:25]

    @quotes.command()
    @autocomplete(text=quote_ac)
    @describe(text="Search by quote text")
    async def search(self, interaction: Interaction, text: int, user: Optional[Member]) -> Message:
        """Search for a quote by quote text"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        if user.id in self.bot.quote_blacklist:
            return await self.bot.error(interaction, "That user has opted out of quotes.")
        if text:
            return await QuotesView(interaction, quotes=self.bot.quotes[text]).update()

    @quotes.command()
    @describe(quote_id="Enter quote ID#")
    async def id(self, interaction: Interaction, quote_id: int) -> Message:
        """Get a quote by its ID Number"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        try:
            return await QuotesView(interaction, quotes=[self.bot.quotes[quote_id]]).update()
        except KeyError:
            return await interaction.client.error(interaction, f"Quote #{quote_id} was not found.")

    @quotes.command()
    async def opt_out(self, i: Interaction):
        """Remove all quotes about, or added by you, and prevent future quotes being added."""
        if i.user.id in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            v = Confirmation(i, label_a="Opt In", colour_a=ButtonStyle.green, label_b="Cancel")
            await self.bot.reply(i, content=OPT_IN, view=v)
            await v.wait()

            if v.value:  # User has chosen to opt in.
                connection = await self.bot.db.acquire()
                try:
                    await connection.execute("""DELETE FROM quotes_optout WHERE userid = $1""", i.user.id)
                finally:
                    await self.bot.db.release(connection)
                await self.bot.reply(i, content="You have opted back into the Quotes Database.", view=None)
            else:
                await self.bot.error(i, content="Opt in cancelled, quotes cannot be added about you.", view=None)
        else:
            sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                            (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""

            connection = await self.bot.db.acquire()
            try:
                async with connection.transaction():
                    r = await connection.fetchrow(sql, i.user.id, i.guild.id)
            finally:
                await self.bot.db.release(connection)

            # Warn about quotes that will be deleted.
            if not all(v == 0 for v in [r['auth'], r['auth_g'], r['sub'], r['sub_g']]):
                auth = f"You have been quoted {r['auth']} times" if r['auth'] else ""
                if i.guild is not None:
                    auth += f" ({r['auth_g']} times on {i.guild.name})" if r['auth_g'] else ""

                sub = f"You have submitted {r['sub']} quotes" if r['sub'] else ""
                if i.guild is not None:
                    sub += f" ({r['sub_g']} times on {i.guild.name})" if r['sub_g'] else ""

                msg = ("\n".join([i for i in [auth, sub] if i]) +
                       "\n\n**ALL of these quotes will be deleted if you opt out.**")
                title = "Your quotes will be deleted if you opt out."
                e = Embed(colour=Colour.red(), title=title, description=msg)
            else:
                e = None

            v = Confirmation(i, label_a="Opt out", colour_a=ButtonStyle.red, label_b="Cancel")
            v.message = await self.bot.reply(i, content="Opt out of QuoteDB?", embed=e, view=v)

            if not v.value:
                err = "Opt out cancelled, you can still quote and be quoted"
                return await self.bot.error(i, content=err, view=None)

            if e is not None:
                connection = await self.bot.db.acquire()
                try:
                    async with connection.transaction():
                        sql = """DELETE FROM quotes WHERE author_user_id = $1 OR submitter_user_id = $2"""
                        r = await connection.execute(sql, i.user.id, i.user.id)
                finally:
                    await self.bot.db.release(connection)
                e.description = r.split(' ')[-1] + " quotes were deleted."
            await self.bot.reply(i, content=f"You were opted out of the quote DB", embed=e)


async def setup(bot: 'Bot'):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
