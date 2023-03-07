"""Commands related to the Quote Database Functionality"""
from __future__ import annotations

import random
import typing
import importlib

import asyncpg
import discord
from discord.ext import commands

from ext.utils import view_utils

if typing.TYPE_CHECKING:
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


async def cache_quotes(self) -> None:
    """Cache the QuoteDB"""
    async with self.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            sql = """SELECT * FROM quotes"""
            self.quotes = await connection.fetch(sql)


class TargetOptedOutError(discord.app_commands.AppCommandError):
    """Target user of command has opted out of quote DB"""

    def __init__(self, user: discord.User | discord.Member):
        super().__init__(f"{user.mention} has opted out of the quote DB.")


# Delete quotes
class DeleteQuote(discord.ui.Button):
    """Button to spawn a new view to delete a quote."""

    view: QuotesView

    def __init__(self, quote: asyncpg.Record, row: int = 3) -> None:
        self.quote: asyncpg.Record = quote
        super().__init__(label="Delete", emoji="🗑️", row=row)
        self.style = discord.ButtonStyle.red

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Delete quote by quote ID"""
        bot: Bot = interaction.client
        r = self.quote

        if interaction.guild is None or interaction.guild.id != r["guild_id"]:
            valid = [r["author_user_id"], r["submitter_user_id"], bot.owner_id]
            if interaction.user.id not in valid:
                err = "You can't delete other servers quotes."
                return await bot.error(interaction, err)

        i = self.view.interaction
        dlt = view_utils.Confirmation(i, style_a=discord.ButtonStyle.red)

        txt = "Delete this quote?"
        edit = self.view.interaction.edit_original_response
        await edit(content=txt, view=dlt)

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
            if self.view.index != 0:
                self.view.index -= 1
        else:
            txt = "Quote not deleted"
        await edit(content=txt)
        return await self.view.update()


class Global(discord.ui.Button):
    """Toggle This Server Only or Global"""

    view: QuotesView

    def __init__(self, view: QuotesView, row: int = 3) -> None:

        if view.all_guilds:
            style = discord.ButtonStyle.green
        else:
            style = discord.ButtonStyle.gray

        super().__init__(style=style, row=row, emoji="🌍")

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Flip the bool."""

        await interaction.response.defer()
        self.view.all_guilds = not self.view.all_guilds
        self.view.index = 0
        return await self.view.update()


class RandomQuote(discord.ui.Button):
    """Push a random quote to the view."""

    view: QuotesView

    def __init__(self, row: int = 3) -> None:
        super().__init__(row=row, emoji="🎲")

    async def callback(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Randomly select a number"""

        await interaction.response.defer()
        self.view.index = random.randrange(0, len(self.view.pages))
        return await self.view.update()


class QuotesView(view_utils.BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(
        self, interaction: discord.Interaction[Bot], all_guilds: bool = False
    ) -> None:

        super().__init__(interaction)

        self.all_guilds: bool = all_guilds
        self.all_quotes: list[asyncpg.Record] = interaction.client.quotes

        self.guild_quotes: list[asyncpg.Record]

        if interaction.guild is None:
            self.guild_quotes = []

        else:
            g = interaction.guild.id
            q = [i for i in self.all_quotes if i["guild_id"] == g]
            self.guild_quotes = q

        self.jump_button: typing.Optional[discord.ui.Button] = None

    async def on_timeout(self) -> discord.InteractionMessage:
        """Remove buttons and dropdowns when listening stops."""

        if self.jump_button is not None:
            v = discord.ui.View()
            v.add_item(self.jump_button)
        else:
            v = None
        return await self.interaction.edit_original_response(view=v)

    async def update(self) -> discord.InteractionMessage:
        """Refresh the view and send to user"""
        self.clear_items()

        self.pages = self.all_quotes if self.all_guilds else self.guild_quotes

        if self.index is None:
            # Pull a random quote.
            try:
                quote = random.choice(self.pages)
                self.index = self.pages.index(quote)
            except IndexError:
                e = discord.Embed(description="No quotes found")
                e.color = discord.Colour.red()
                self.add_item(Global(self))
                self.add_item(view_utils.Stop())

                edit = self.interaction.edit_original_response
                return await edit(embed=e, view=self)
        else:
            quote = self.pages[self.index]

        e = discord.Embed(color=0x7289DA, timestamp=quote["timestamp"])
        if (g := self.bot.get_guild(quote["guild_id"])) is None:
            guild = "Deleted Server"
        else:
            guild = g.name

        if (channel := self.bot.get_channel(quote["channel_id"])) is None:
            channel = "Deleted Channel"
        elif not isinstance(
            channel,
            discord.abc.PrivateChannel
            | discord.ForumChannel
            | discord.StageChannel
            | discord.CategoryChannel,
        ):
            gid = quote["guild_id"]
            cid = quote["channel_id"]
            mid = quote["message_id"]

            url = f"https://discord.com/channels/{gid}/{cid}/{mid}"
            btn = discord.ui.Button(row=3, emoji="🔗", url=url)
            btn.style = discord.ButtonStyle.link

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

        edit = self.interaction.edit_original_response
        return await edit(embed=e, view=self)


# MESSAGE COMMAND, (right click message -> Add quote)
@discord.app_commands.context_menu(name="Add to QuoteDB")
async def quote_add(
    ctx: discord.Interaction[Bot], message: discord.Message
) -> discord.InteractionMessage:
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

    sql = """INSERT INTO quotes (channel_id, guild_id, message_id,
    author_user_id, submitter_user_id, message_content, timestamp)
    VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *"""

    guild = message.guild.id if message.guild else None
    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            try:
                await connection.fetchrow(
                    sql,
                    message.channel.id,
                    guild,
                    message.id,
                    message.author.id,
                    ctx.user.id,
                    message.content,
                    message.created_at,
                )
            except asyncpg.UniqueViolationError:
                err = "That quote is already in the database!"
                return await bot.error(ctx, err)

        await cache_quotes(bot)

        e = discord.Embed(colour=discord.Colour.green())
        e.description = "Added to quote database"
        await ctx.followup.send(embed=e, ephemeral=True)

        v = QuotesView(ctx)
        v.index = -1
        return await v.update()


async def quote_ac(
    ctx: discord.Interaction[Bot], current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete from guild quotes"""

    cur = current.casefold()

    results = []

    client = ctx.client
    for r in sorted(client.quotes, key=lambda r: r["quote_id"]):
        if ctx.guild and r["guild_id"] != ctx.guild.id:
            continue

        if ctx.namespace.user is not None:
            if r["author_user_id"] != ctx.namespace.user.id:
                continue

        if cur not in r["message_content"].casefold():
            continue

        auth = client.get_user(r["author_user_id"])
        qid = r["quote_id"]
        fmt = f"#{qid}: {auth} {r['message_content']}"[:100]

        results.append(discord.app_commands.Choice(name=fmt, value=str(qid)))

        if len(results) == 25:
            break

    return results


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot: Bot) -> None:
        bot.tree.add_command(quote_add)
        self.bot: Bot = bot

        importlib.reload(view_utils)

    async def cog_load(self) -> None:
        """When the cog loads…"""
        await self.opt_outs()
        await cache_quotes(self.bot)

    async def opt_outs(self) -> list[int]:
        """Cache the list of users who have opted out of the quote DB"""

        q = """SELECT * FROM quotes_optout"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(q)

        self.bot.quote_blacklist = [r["userid"] for r in records]
        return self.bot.quote_blacklist

    quotes = discord.app_commands.Group(
        name="quote", description="Get from or add to the quote database"
    )

    @quotes.command()
    async def random(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
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
        self,
        interaction: discord.Interaction[Bot],
        all_guilds: bool = False,
    ) -> discord.InteractionMessage:
        """Get the most recent quote"""
        await interaction.response.defer(thinking=True)
        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        v = QuotesView(interaction, all_guilds=all_guilds)
        v.index = -1
        return await v.update()

    @quotes.command()
    @discord.app_commands.autocomplete(text=quote_ac)
    @discord.app_commands.describe(text="Search by quote text")
    async def search(
        self,
        interaction: discord.Interaction[Bot],
        text: str,
        user: typing.Optional[discord.Member] = None,
    ) -> discord.InteractionMessage:
        """Search for a quote by quote text"""
        await interaction.response.defer(thinking=True)
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
    async def user(
        self, interaction: discord.Interaction[Bot], member: discord.Member
    ) -> discord.InteractionMessage:
        """Get a random quote from this user."""
        await interaction.response.defer(thinking=True)

        if interaction.user.id in self.bot.quote_blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        if member.id in self.bot.quote_blacklist:
            raise TargetOptedOutError(member)

        sql = """SELECT * FROM quotes WHERE author_user_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetch(sql, member.id)

        view = QuotesView(interaction, r)
        view.all_quotes = r
        view.index = random.randrange(len(view.all_quotes) - 1)
        return await view.update()

    @quotes.command()
    @discord.app_commands.describe(quote_id="Enter quote ID#")
    async def id(
        self, interaction: discord.Interaction[Bot], quote_id: int
    ) -> discord.InteractionMessage:
        """Get a quote by its ID Number"""
        await interaction.response.defer(thinking=True)

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
    async def stats(
        self, interaction: discord.Interaction[Bot], member: discord.Member
    ) -> discord.InteractionMessage:
        """See quote stats for a user"""
        await interaction.response.defer(thinking=True)

        blacklist: list[int] = self.bot.quote_blacklist

        if interaction.user.id in blacklist:
            err = "You are opted out of the QuoteDB."
            return await interaction.client.error(interaction, err)

        if member.id in blacklist:
            raise TargetOptedOutError(member)

        g = interaction.guild.id if interaction.guild else None
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetchrow(QT_SQL, member.id, g)

        e = discord.Embed(color=discord.Colour.og_blurple())
        e.title = "Quote Stats"

        nom = f"{member} ({member.id})"
        e.set_author(icon_url=member.display_avatar.url, name=nom)

        e.description = (
            f"Quoted {r['auth_g']} times ({r['auth']} Globally)\n"
            f"Added {r['sub_g']} quotes ({r['sub']} Globally)"
        )

        return await interaction.edit_original_response(embed=e)

    @quotes.command()
    async def opt_out(
        self, interaction: discord.Interaction[Bot]
    ) -> discord.InteractionMessage:
        """Remove all quotes about, or added by you, and prevent
        future quotes being added."""
        await interaction.response.defer(thinking=True)
        g = interaction.guild.id if interaction.guild else None
        u = interaction.user.id

        sql = """DELETE FROM quotes_optout WHERE userid = $1"""
        if u in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            style = discord.ButtonStyle.green
            v = view_utils.Confirmation(interaction, "Opt In", "Cancel", style)

            await interaction.edit_original_response(content=OPT_IN, view=v)
            await v.wait()

            if v.value:
                # User has chosen to opt in.
                async with self.bot.db.acquire(timeout=60) as connection:
                    await connection.execute(sql, u)

                msg = "You have opted back into the Quotes Database."
            else:
                msg = "Opt in cancelled, quotes cannot be added about you."

            edit = interaction.edit_original_response
            return await edit(content=msg, view=None)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetchrow(QT_SQL, u, g)

        # Warn about quotes that will be deleted.
        truthy = [r["author"], r["auth_g"], r["sub"], r["sub_g"]]
        if all(v == 0 for v in truthy):
            e = None
        else:
            output = [f"You have been quoted {r['author']} times"]

            guild = interaction.guild
            if r["auth"] and guild is not None:
                output.append(f" ({r['auth_g']} times on {guild.name})")
            output.append("\n")

            output.append(f"You have submitted {r['sub']} quotes")
            if r["sub"] and guild is not None:
                output.append(f" ({r['sub_g']} times on {guild.name})")

            s = "\n\n**ALL of these quotes will be deleted if you opt out.**"
            output.append(s)

            e = discord.Embed(colour=discord.Colour.red())

            e.description = "".join(output)
            e.title = "Your quotes will be deleted if you opt out."

        v = view_utils.Confirmation(
            interaction,
            "Opt out",
            "Cancel",
            discord.ButtonStyle.red,
        )

        txt = "Opt out of QuoteDB?"
        edit = interaction.edit_original_response
        await edit(content=txt, embed=e, view=v)

        await v.wait()
        if not v.value:
            err = "Opt out cancelled, you can still quote and be quoted"
            return await self.bot.error(interaction, err)

        sql = """DELETE FROM quotes WHERE author_user_id = $1
                 OR submitter_user_id = $2"""

        if e is not None:
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    r = await connection.execute(sql, u, u)

            e.description = r.split(" ")[-1] + " quotes were deleted."

        txt = "You were removed from the Quote Database"

        return await edit(content=txt, embed=e, view=None)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
