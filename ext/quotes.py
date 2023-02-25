"""Commands related to the Quote Database Functionality"""
from __future__ import annotations

import random
from importlib import reload
from types import NoneType
from typing import TYPE_CHECKING, Optional

import discord
from asyncpg import UniqueViolationError, Record
from discord import (
    Embed,
    ButtonStyle,
    Interaction,
    Colour,
    Message,
    Member,
)
from discord.app_commands import (
    Group,
    context_menu,
    describe,
    autocomplete,
    Choice,
    AppCommandError,
)
from discord.ext import commands
from discord.ui import Button

from ext.utils import view_utils
from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot

QT = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"
OPT_IN = (
    "You are currently opted out of quotes, opting back in will allow "
    "others to add quotes from you to the database. Are you sure?"
)

QT_SQL = """
SELECT
(SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
(SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2)
AS auth_g,
(SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
(SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2)
AS sub_g
"""


class TargetOptedOutError(AppCommandError):
    """Target user of command has opted out of quote DB"""

    def __init__(self, user: discord.User | discord.Member):
        super().__init__(f"{user.mention} has opted out of the quote DB.")


# Delete quotes
class DeleteQuote(Button):
    """Button to spawn a new view to delete a quote."""

    view: QuotesView

    def __init__(self, quote: Record, row: int = 3) -> None:
        self.quote: Record = quote
        super().__init__(
            style=ButtonStyle.red, label="Delete", emoji="🗑️", row=row
        )

    async def callback(self, interaction: Interaction[Bot]):
        """Delete quote by quote ID"""
        bot: Bot = interaction.client
        r = self.quote

        if interaction.guild is None or interaction.guild.id != r["guild_id"]:
            valid = [r["author_user_id"], r["submitter_user_id"], bot.owner_id]
            if interaction.user.id not in valid:
                err = "You can't delete other servers quotes."
                return await bot.error(interaction, err)

        user = interaction.user
        in_quote = user.id in [r["author_user_id"], r["submitter_user_id"]]

        if isinstance(user, Member):
            mod = user.guild_permissions.manage_messages
        else:
            mod = False

        i = self.view.interaction
        dlt = view_utils.Confirmation(i, style_a=discord.ButtonStyle.red)
        if in_quote or mod:

            txt = "Delete this quote?"
            await interaction.client.reply(interaction, txt, view=dlt)

            await dlt.wait()
            if dlt.value:
                qid = r["quote_id"]
                async with bot.db.acquire(timeout=60) as connection:
                    async with connection.transaction():
                        sql = "DELETE FROM quotes WHERE quote_id = $1"
                        await connection.execute(sql, qid)

                aq = self.view.all_quotes
                gq = self.view.guild_quotes
                aq = [i for i in aq if i != r]
                gq = [i for i in gq if i != r]

                txt = f"Quote #{qid} has been deleted."
                await self.view.interaction.followup.send(txt)
                await self.view.update()

                if self.view.index != 0:
                    self.view.index -= 1
            else:
                await self.view.interaction.followup.send("Quote not deleted")
        else:
            err = "You need manage_messages perms to delete a quote"
            await self.view.interaction.followup.send(err)


class Global(Button):
    """Toggle This Server Only or Global"""

    view: QuotesView

    def __init__(self, view: QuotesView, row: int = 3) -> None:

        if view.all_guilds:
            style = discord.ButtonStyle.green
        else:
            style = discord.ButtonStyle.gray

        super().__init__(style=style, row=row, emoji="🌍")

    async def callback(self, interaction: Interaction) -> Message:
        """Flip the bool."""

        await interaction.response.defer()
        self.view.all_guilds = not self.view.all_guilds
        self.view.index = 0
        return await self.view.update()


class RandomQuote(Button):
    """Push a random quote to the view."""

    view: QuotesView

    def __init__(self, row: int = 3) -> None:
        super().__init__(row=row, emoji="🎲")

    async def callback(self, interaction: Interaction) -> Message:
        """Randomly select a number"""

        await interaction.response.defer()
        self.view.index = random.randrange(0, len(self.view.pages))
        return await self.view.update()


class QuotesView(BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(
        self, interaction: Interaction[Bot], all_guilds: bool = False
    ) -> None:

        super().__init__(interaction)

        self.all_guilds: bool = all_guilds
        self.all_quotes: list[Record] = interaction.client.quotes

        self.guild_quotes: list[Record]

        if interaction.guild is None:
            self.guild_quotes = []

        else:
            g = interaction.guild.id
            q = [i for i in self.all_quotes if i["guild_id"] == g]
            self.guild_quotes = q

        self.jump_button: Button

    async def on_timeout(self) -> Message:
        """Remove buttons and dropdowns when listening stops."""

        if self.jump_button is not None:
            v = discord.ui.View()
            v.add_item(self.jump_button)
        else:
            v = None

        return await self.bot.reply(self.interaction, view=v, followup=False)

    async def update(self) -> Message:
        """Refresh the view and send to user"""
        self.clear_items()

        self.pages = self.all_quotes if self.all_guilds else self.guild_quotes

        if self.index is None:
            # Pull a random quote.
            try:
                quote = random.choice(self.pages)
                self.index = self.pages.index(quote)
            except IndexError:
                e = Embed(description="No quotes found", color=Colour.red())
                self.add_item(Global(self))
                self.add_item(view_utils.Stop())

                edit = self.interaction.edit_original_response
                return await edit(embed=e, view=self)
        else:
            quote = self.pages[self.index]

        e = Embed(color=0x7289DA, timestamp=quote["timestamp"])
        if (g := self.bot.get_guild(quote["guild_id"])) is None:
            guild = "Deleted Server"
        else:
            guild = g.name

        if (channel := self.bot.get_channel(quote["channel_id"])) is None:
            channel = "Deleted Channel"
        else:
            if not isinstance(
                channel,
                discord.abc.PrivateChannel
                | discord.ForumChannel
                | discord.StageChannel
                | discord.CategoryChannel
                | NoneType,
            ):
                message = await channel.fetch_message(quote["message_id"])

                btn = discord.ui.Button(row=3, emoji="🔗")
                btn.style = discord.ButtonStyle.link
                btn.url = message.jump_url
                btn.row = 3

                self.jump_button = btn
                self.add_item(self.jump_button)

                channel = channel.name

        auth_id = quote["author_user_id"]
        sub_id = quote["submitter_user_id"]
        if (submitter := self.bot.get_user(sub_id)) is None:
            submitter = "Deleted User"
            ico = QT
        else:
            ico = submitter.display_avatar.url

        e.set_footer(
            text=f"Quote #{quote['quote_id']}\n{guild} #{channel}\n"
            f"Added by {submitter}",
            icon_url=ico,
        )

        if (author := self.bot.get_user(quote["author_user_id"])) is None:
            e.set_author(name="Deleted User", icon_url=QT)
        else:
            e.set_author(name=f"{author}", icon_url=author.display_avatar.url)

        if isinstance(self.interaction.user, discord.Member):

            perms = self.interaction.user.resolved_permissions
            is_mod = perms and perms.manage_messages and not self.all_guilds

            if self.interaction.user.id in [auth_id, sub_id] or is_mod:
                self.add_item(DeleteQuote(quote))

        e.description = quote["message_content"]

        self.add_item(RandomQuote(row=0))
        self.add_page_buttons()

        return await self.bot.reply(self.interaction, embed=e, view=self)


# MESSAGE COMMAND, (right click message -> Add quote)
@context_menu(name="Add to QuoteDB")
async def quote_add(ctx: Interaction[Bot], message: Message) -> Message:
    """Add this message to the quote database"""
    bot: Bot = ctx.client
    await ctx.response.defer(thinking=True)

    blacklist = bot.quote_blacklist

    if ctx.user.id in blacklist:
        return await bot.error(ctx, "You are opted out of the QuoteDB.")
    if message.author.id in blacklist:
        auth = message.author.mention
        return await bot.error(ctx, f"{auth} is opted out of the QuoteDB.")

    if ctx.guild is None:
        err = "This command cannot be used in DMs."
        return await bot.error(ctx, err)
    if message.author.id == ctx.user.id:
        return await bot.error(ctx, "You cannot quote yourself.")
    if message.author.bot:
        return await bot.error(ctx, "You cannot quote a bot.")
    if not message.content:
        return await bot.error(ctx, "That message has no content.")

    guild = message.guild.id if message.guild else None
    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            try:
                await connection.fetchrow(
                    """
                    INSERT INTO quotes (channel_id, guild_id, message_id,
                    author_user_id, submitter_user_id, message_content,
                    timestamp) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING *
                    """,
                    message.channel.id,
                    guild,
                    message.id,
                    message.author.id,
                    ctx.user.id,
                    message.content,
                    message.created_at,
                )
            except UniqueViolationError:
                err = "That quote is already in the database!"
                return await bot.error(ctx, err)

        await bot.cache_quotes()

        e = Embed(colour=Colour.green(), description="Added to quote database")
        await ctx.followup.send(embed=e, ephemeral=True)

        v = QuotesView(ctx)
        v.index = -1
        return await v.update()


async def quote_ac(ctx: Interaction[Bot], current: str) -> list[Choice[str]]:
    """Autocomplete from guild quotes"""
    bot: Bot = ctx.client

    qdb = bot.quotes
    if ctx.guild:
        results = [i for i in qdb if i["guild_id"] == ctx.guild.id]
    else:
        results = qdb

    if (u := ctx.namespace.user) is not None:
        results = [i for i in results if i["author_user_id"] == u.id]

    results = []
    for r in results:
        auth = bot.get_user(r["author_user_id"])
        cont = r["message_content"]
        qid = r["quote_id"]
        fmt = f"#{qid}: {auth} {cont}"[:100]
        if current.lower() in cont.lower():
            results.append(Choice(name=fmt, value=str(qid)))
    return results[:25]


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot: Bot) -> None:
        bot.tree.add_command(quote_add)
        self.bot: Bot = bot

        reload(view_utils)

    async def cog_load(self) -> None:
        """When the cog loads…"""
        await self.opt_outs()
        await self.bot.cache_quotes()

    async def opt_outs(self) -> None:
        """Cache the list of users who have opted out of the quote DB"""

        q = """SELECT * FROM quotes_optout"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(q)

        self.bot.quote_blacklist = [r["userid"] for r in records]

    quotes = Group(
        name="quote", description="Get from or add to the quote database"
    )

    @quotes.command()
    async def random(self, interaction: Interaction[Bot]) -> Message:
        """Get a random quote."""

        await interaction.response.defer(thinking=True)

        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        view = QuotesView(interaction)
        view.index = random.randrange(0, len(view.guild_quotes) - 1)
        return await view.update()

    @quotes.command()
    async def last(
        self, interaction: Interaction[Bot], all_guilds: bool = False
    ) -> Message:
        """Get the most recent quote"""

        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        v = QuotesView(interaction, all_guilds=all_guilds)
        v.index = -1
        return await v.update()

    @quotes.command()
    @autocomplete(text=quote_ac)
    @describe(text="Search by quote text")
    async def search(
        self,
        interaction: Interaction[Bot],
        text: str,
        user: Optional[discord.Member] = None,
    ) -> Message:
        """Search for a quote by quote text"""
        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        if user is not None:
            if user.id in self.bot.quote_blacklist:
                raise TargetOptedOutError(user)

        v = QuotesView(interaction)
        q = v.guild_quotes
        v.index = q.index(next(i for i in q if i["quote_id"] == int(text)))
        return await v.update()

    @quotes.command()
    async def user(self, interaction: Interaction[Bot], member: Member):
        """Get a random quote from this user."""
        bot: Bot = interaction.client
        blacklist = bot.quote_blacklist

        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        if member.id in blacklist:
            raise TargetOptedOutError(member)

        sql = """SELECT * FROM quotes WHERE author_user_id = $1
                 ORDER BY random()"""
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():

                r = await connection.fetch(sql, member.id)

        await QuotesView(interaction, r).update()

    @quotes.command()
    @describe(quote_id="Enter quote ID#")
    async def id(
        self, interaction: Interaction[Bot], quote_id: int
    ) -> Message:
        """Get a quote by its ID Number"""
        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        try:
            v = QuotesView(interaction)
            v.all_guilds = True

            q = v.all_quotes
            v.index = q.index(next(i for i in q if i["quote_id"] == quote_id))
            return await v.update()
        except StopIteration:
            err = f"Quote #{quote_id} was not found."
            return await self.bot.error(interaction, err)

    @quotes.command()
    async def stats(self, interaction: Interaction[Bot], member: Member):
        """See quote stats for a user"""
        bot: Bot = interaction.client
        blacklist: list[int] = bot.quote_blacklist

        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        if member.id in blacklist:
            raise TargetOptedOutError(member)

        g = interaction.guild.id if interaction.guild else None
        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetchrow(QT_SQL, member.id, g)

        e: Embed = Embed(color=Colour.og_blurple(), title="Quote Stats")

        nom = f"{member} ({member.id})"
        e.set_author(icon_url=member.display_avatar.url, name=nom)

        e.description = (
            f"Quoted {r['auth_g']} times ({r['auth']} Globally)\n"
            f"Added {r['sub_g']} quotes ({r['sub']} Globally)"
        )

        await bot.reply(interaction, embed=e)

    @quotes.command()
    async def opt_out(self, ctx: Interaction[Bot]):
        """Remove all quotes about, or added by you, and prevent
        future quotes being added."""

        g = ctx.guild.id if ctx.guild else None
        u = ctx.user.id

        sql = """DELETE FROM quotes_optout WHERE userid = $1"""
        if u in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            style = ButtonStyle.green
            v = view_utils.Confirmation(ctx, "Opt In", "Cancel", style)

            await self.bot.reply(ctx, OPT_IN, view=v)
            await v.wait()

            if v.value:
                # User has chosen to opt in.
                async with self.bot.db.acquire(timeout=60) as connection:
                    await connection.execute(sql, u)

                msg = "You have opted back into the Quotes Database."
            else:
                msg = "Opt in cancelled, quotes cannot be added about you."
            return await self.bot.reply(ctx, msg, view=None)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetchrow(QT_SQL, u, g)

        # Warn about quotes that will be deleted.
        truthy = [r["author"], r["auth_g"], r["sub"], r["sub_g"]]
        if all(v == 0 for v in truthy):
            e = None
        else:
            output = [f"You have been quoted {r['author']} times"]

            guild = ctx.guild
            if r["auth"] and guild is not None:
                output.append(f" ({r['auth_g']} times on {guild.name})")
            output.append("\n")

            output.append(f"You have submitted {r['sub']} quotes")
            if r["sub"] and guild is not None:
                output.append(f" ({r['sub_g']} times on {guild.name})")

            s = "\n\n**ALL of these quotes will be deleted if you opt out.**"
            output.append(s)

            e = Embed(colour=discord.Colour.red())

            e.description = "".join(output)
            e.title = "Your quotes will be deleted if you opt out."

        v = view_utils.Confirmation(
            ctx,
            "Opt out",
            "Cancel",
            discord.ButtonStyle.red,
        )

        txt = "Opt out of QuoteDB?"
        await self.bot.reply(ctx, txt, embed=e, view=v)

        await v.wait()
        if not v.value:
            err = "Opt out cancelled, you can still quote and be quoted"
            return await self.bot.error(ctx, err)

        sql = """DELETE FROM quotes WHERE author_user_id = $1
                 OR submitter_user_id = $2"""

        if e is not None:
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    r = await connection.execute(sql, u, u)

            e.description = r.split(" ")[-1] + " quotes were deleted."

        txt = "You were removed from the Quote Database"
        await self.bot.reply(ctx, txt, embed=e)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
