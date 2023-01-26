"""Commands related to the Quote Database Functionality"""
from __future__ import annotations

from random import randrange
from typing import TYPE_CHECKING

from asyncpg import UniqueViolationError, Record
from discord import Embed, ButtonStyle, Interaction, Colour, Message, Member
from discord.app_commands import Group, context_menu, describe, autocomplete, Choice, AppCommandError
from discord.ext import commands
from discord.ui import Button, View

from ext.utils import view_utils

if TYPE_CHECKING:
    from core import Bot


class OptedOutError(AppCommandError):
    """User invoking command has opted out of quote DB"""

    def __init__(self) -> None:
        self.message = f"You have opted out of the quote DB."
        super().__init__(self.message)


class TargetOptedOutError(AppCommandError):
    """Target user of command has opted out of quote DB"""

    def __init__(self, user: Member):
        self.message = f"{user.mention} has opted out of the quote DB."
        super().__init__(self.message)


# Delete quotes
class DeleteQuote(Button):
    """Button to spawn a new view to delete a quote."""

    def __init__(self, bot: Bot, quote: Record, row: int = 3) -> None:
        self.bot: Bot = bot
        self.quote: Record = quote
        super().__init__(style=ButtonStyle.red, label="Delete", emoji="🗑️", row=row)

    async def callback(self, interaction: Interaction):
        """Delete quote by quote ID"""
        r = self.quote

        if r["guild_id"] != interaction.guild.id or interaction.guild.id is None:
            if interaction.user.id not in [r["author_user_id"], r["submitter_user_id"], self.bot.owner_id]:
                return await self.view.update(content=f"You can't delete other servers quotes.")

        _ = self.view.interaction.user.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or interaction.app_permissions.manage_messages:
            view = view_utils.Confirmation(self.view.interaction, label_a="Delete",
                                           colour_a=ButtonStyle.red, label_b="Cancel")
            m = await self.bot.reply(interaction, content="Delete this quote?", view=view)
            await view.wait()

            try:
                await m.delete()
            except AttributeError:
                pass

            if view.value:
                async with self.bot.db.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute("DELETE FROM quotes WHERE quote_id = $1", r['quote_id'])

                await self.view.update(content=f"Quote #{r['quote_id']} has been deleted.")
                if self.view.index != 0:
                    self.view.index -= 1
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
        self.view.index = 0
        return await self.view.update()


class RandomQuote(Button):
    """Push a random quote to the view."""

    def __init__(self, row: int = 3) -> None:
        super().__init__(row=row, label="Random", emoji="🎲")

    async def callback(self, interaction: Interaction) -> Message:
        """Randomly select a number"""
        await interaction.response.defer()
        quotes = self.view.pages if self.view.all_guilds else self.view.all
        try:
            self.view.index = max(randrange(len(quotes)) - 1, 0)  # Avoid IndexError
        except ValueError:
            self.view.index = 0
        return await self.view.update()


class QuotesView(View):
    """Generic Paginator that returns nothing."""

    def __init__(self, interaction: Interaction, quotes: list[Record], rand: bool = False, last: bool = False) -> None:
        super().__init__()
        self.pages: list[Record] = list(filter(lambda x: x['guild_id'] == interaction.guild.id, quotes))
        self.all: list[Record] = quotes
        self.interaction = interaction
        self.bot: Bot = interaction.client
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
        return await self.bot.reply(self.interaction, view=None, followup=False)

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

    async def update(self, content: str = None) -> Message:
        """Refresh the view and send to user"""
        self.clear_items()

        if self.all_guilds:
            self.add_item(Global(label=f"Show All Servers", style=ButtonStyle.blurple))
        else:
            self.add_item(Global(label=f"Show {self.interaction.guild.name} only", style=ButtonStyle.gray))

        try:
            q = self.all[self.index] if self.all_guilds else self.pages[self.index]
            is_mod = self.interaction.user.resolved_permissions.manage_messages
            if self.interaction.user.id in [q['author_user_id'], q['submitter_user_id']] or is_mod:
                self.add_item(DeleteQuote(self.bot, quote=q))
        except IndexError:
            q = None

        if len(self.pages) > 1:
            p = view_utils.Previous()
            if self.index == 0:
                p.disabled = True
            self.add_item(p)

            if len(self.pages) > 3:
                self.add_item(view_utils.Jump(label=f"Page {self.index + 1} of {len(self.pages)}"))

            n = view_utils.Next()
            if self.index + 1 >= self.pages:
                n.disabled = True
            self.add_item(n)
            self.add_item(RandomQuote())
            self.add_item(view_utils.Stop(row=0))
        else:
            self.add_item(view_utils.Stop())

        e = self.embed_quote(q)
        return await self.bot.reply(self.interaction, content=content, embed=e, view=self)


OPT_IN = "You are currently opted out of quotes, opting back in will allow " \
         "others to add quotes from you to the database. Are you sure?"


# MESSAGE COMMAND, (right click message -> Add quote)
@context_menu(name="Add to QuoteDB")
async def quote_add(interaction: Interaction, message: Message) -> Message:
    """Add a quote, either by message ID or grabs the last message a user sent"""
    bot: Bot = interaction.client
    await interaction.response.defer(thinking=True)
    blacklist = bot.quote_blacklist

    if interaction.user.id in blacklist:
        raise OptedOutError
    if message.author.id in blacklist:
        raise TargetOptedOutError(message.author)
    if interaction.guild is None:
        return await bot.error(interaction, content='This command cannot be used in DMs.')
    if message.author.id == interaction.user.id:
        return await bot.error(interaction, content='You cannot quote yourself.')
    if message.author.bot:
        return await bot.error(interaction, content='You cannot quote a bot.')
    if not message.content:
        return await bot.error(interaction, content='That message has no content.')

    async with bot.db.acquire() as connection:
        async with connection.transaction():
            try:
                r = await connection.fetchrow(
                    """INSERT INTO quotes
                    (channel_id,guild_id,message_id,author_user_id,submitter_user_id,message_content,timestamp)
                    VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
                    message.channel.id, message.guild.id, message.id, message.author.id, interaction.user.id,
                    message.content, message.created_at)
            except UniqueViolationError:
                return await bot.error(interaction, content="That quote is already in the database!")
    await QuotesView(interaction, [r]).update(content="Quote added to database.")


# USER COMMANDS: right click user
@context_menu(name="QuoteDB: Get Quotes")
async def u_quote(interaction: Interaction, user: Member):
    """Get a random quote from this user."""
    bot: Bot = interaction.client
    blacklist = bot.quote_blacklist

    if interaction.user.id in blacklist:
        raise OptedOutError
    if user.id in blacklist:
        raise TargetOptedOutError(user)

    async with bot.db.acquire() as connection:
        async with connection.transaction():
            sql = """SELECT * FROM quotes WHERE author_user_id = $1 ORDER BY random()"""
            r = await connection.fetch(sql, user.id)

    await QuotesView(interaction, r).update()


@context_menu(name="QuoteDB: Get Stats")
async def quote_stats(interaction: Interaction, member: Member):
    """See quote stats for a user"""
    bot: Bot = interaction.client
    blacklist: list[int] = bot.quote_blacklist  # We can't use dot notation because client != bot

    if interaction.user.id in blacklist:
        raise OptedOutError
    if member.id in blacklist:
        raise TargetOptedOutError(member)

    sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                    (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                    (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                    (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
    escaped = [member.id, interaction.guild.id]

    async with bot.db.acquire() as connection:
        async with connection.transaction():
            r = await connection.fetchrow(sql, *escaped)

    e: Embed = Embed(color=Colour.og_blurple(), description=member.mention)
    e.set_author(icon_url="https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png", name="Quote Stats")
    e.set_thumbnail(url=member.display_avatar.url)
    if interaction.guild:
        e.add_field(name=interaction.guild.name, value=f"Quoted {r['auth_g']} times.\nAdded {r['sub_g']} quotes.", )
    e.add_field(name="Global", value=f"Quoted {r['author']} times.\n Added {r['sub']} quotes.", inline=False)
    await bot.reply(interaction, embed=e)


async def quote_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete from guild quotes"""
    bot: Bot = interaction.client
    results = [i for i in bot.quotes if i['guild_id'] == interaction.guild.id]
    if interaction.namespace.user is not None:
        results = [i for i in results if i['author_user_id'] == interaction.namespace.user.id]

    results = [Choice(name=f"#{r['quote_id']}: {r['message_content']}"[:100],
                      value=str(r['quote_id'])) for r in results if current.lower() in r['message_content'].lower()]
    return results[:25]


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot: Bot) -> None:
        bot.tree.add_command(quote_add)
        bot.tree.add_command(quote_stats)
        bot.tree.add_command(u_quote)
        self.bot: Bot = bot

    async def cog_load(self) -> None:
        """When the cog loads…"""
        await self.opt_outs()
        await self.cache_quotes()

    async def opt_outs(self) -> None:
        """Cache the list of users who have opted out of the quote DB"""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM quotes_optout""")
        self.bot.quote_blacklist = [r['userid'] for r in records]

    async def cache_quotes(self) -> None:
        """Cache the Quote DB inside the bot for autocomplete etc."""
        async with self.bot.db.acquire() as connection:
            async with connection.transaction():
                self.bot.quotes = await connection.fetch("""SELECT * FROM quotes""")

    quotes = Group(name="quote", description="Get from or add to the quote database")

    @quotes.command()
    async def random(self, interaction: Interaction) -> Message:
        """Get a random quote."""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        return await QuotesView(interaction, self.bot.quotes, rand=True).update()

    @quotes.command()
    async def last(self, interaction: Interaction) -> Message:
        """Get the most recent quote"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        return await QuotesView(interaction, self.bot.quotes, last=True).update()

    @quotes.command()
    @autocomplete(text=quote_ac)
    @describe(text="Search by quote text")
    async def search(self, interaction: Interaction, text: str, user: Member = None) -> Message:
        """Search for a quote by quote text"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        if user is not None:
            if user.id in self.bot.quote_blacklist:
                raise TargetOptedOutError(user)

        try:
            quotes = [i for i in self.bot.quotes if i['quote_id'] == int(text)]
        except ValueError:
            quotes = [i for i in self.bot.quotes if text in i['message_content']]

        if not quotes:
            quotes = [i for i in self.bot.quotes if text.lower() in i['message_content'].lower()]
        return await QuotesView(interaction, quotes).update()

    @quotes.command()
    @describe(quote_id="Enter quote ID#")
    async def id(self, interaction: Interaction, quote_id: int) -> Message:
        """Get a quote by its ID Number"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError

        quotes = [i for i in self.bot.quotes if i['quote_id'] == quote_id]
        if quotes:
            return await QuotesView(interaction, quotes).update()
        return await self.bot.error(interaction, f"Quote #{quote_id} was not found.")

    @quotes.command()
    async def opt_out(self, i: Interaction):
        """Remove all quotes about, or added by you, and prevent future quotes being added."""
        if i.user.id in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            v = view_utils.Confirmation(i, label_a="Opt In", colour_a=ButtonStyle.green, label_b="Cancel")
            await self.bot.reply(i, content=OPT_IN, view=v)
            await v.wait()

            if v.value:  # User has chosen to opt in.
                async with self.bot.db.acquire() as connection:
                    await connection.execute("""DELETE FROM quotes_optout WHERE userid = $1""", i.user.id)

                await self.bot.reply(i, content="You have opted back into the Quotes Database.", view=None)
            else:
                await self.bot.error(i, "Opt in cancelled, quotes cannot be added about you.")
        else:
            sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                            (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                            (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""

            async with self.bot.db.acquire() as connection:
                async with connection.transaction():
                    r = await connection.fetchrow(sql, i.user.id, i.guild.id)

            # Warn about quotes that will be deleted.
            output = []
            if all(v == 0 for v in [r['author'], r['auth_g'], r['sub'], r['sub_g']]):
                e = None
            else:
                output.append(f"You have been quoted {r['author']} times")
                if r['auth'] and i.guild is not None:
                    output.append(f" ({r['auth_g']} times on {i.guild.name})")
                output.append('\n')

                output.append(f"You have submitted {r['sub']} quotes")
                if r['sub'] and i.guild is not None:
                    output.append(f" ({r['sub_g']} times on {i.guild.name})")

                msg = "".join(output) + "\n\n**ALL of these quotes will be deleted if you opt out.**"
                title = "Your quotes will be deleted if you opt out."
                e = Embed(colour=Colour.red(), title=title, description=msg)

            v = view_utils.Confirmation(i, label_a="Opt out", colour_a=ButtonStyle.red, label_b="Cancel")
            v.message = await self.bot.reply(i, content="Opt out of QuoteDB?", embed=e, view=v)

            if not v.value:
                return await self.bot.error(i, "Opt out cancelled, you can still quote and be quoted")

            if e is not None:
                async with self.bot.db.acquire() as connection:
                    async with connection.transaction():
                        sql = """DELETE FROM quotes WHERE author_user_id = $1 OR submitter_user_id = $2"""
                        r = await connection.execute(sql, i.user.id, i.user.id)
                e.description = r.split(' ')[-1] + " quotes were deleted."
            await self.bot.reply(i, content=f"You were opted out of the quote DB", embed=e)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
