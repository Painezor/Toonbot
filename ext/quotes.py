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

    Interaction: typing.TypeAlias = discord.Interaction[Bot]

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


# TODO: Quote Transformer


async def cache_quotes(bot: Bot) -> None:
    """Cache the QuoteDB"""
    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            sql = """SELECT * FROM quotes"""
            bot.quotes = await connection.fetch(sql)


# Delete quotes
class DeleteQuote(discord.ui.Button["QuotesView"]):
    """Button to spawn a new view to delete a quote."""

    def __init__(self, quote: asyncpg.Record, row: int = 3) -> None:
        self.quote: asyncpg.Record = quote
        super().__init__(label="Delete", emoji="🗑️", row=row)
        self.style = discord.ButtonStyle.red

    async def callback(self, interaction: Interaction) -> None:
        """Delete quote by quote ID"""
        assert self.view is not None

        i = self.quote

        if interaction.guild is None or interaction.guild.id != i["guild_id"]:
            owner = interaction.client.owner_id
            valid = [i["author_user_id"], i["submitter_user_id"], owner]
            if interaction.user.id not in valid:
                err = "🚫 You can't delete other servers quotes."
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = err
                return await interaction.response.edit_message(embed=embed)

        dlt = view_utils.Confirmation(style_a=discord.ButtonStyle.red)

        txt = "Delete this quote?"
        edit = interaction.response.edit_message
        await edit(content=txt, view=dlt)

        await dlt.wait()
        if dlt.value:
            qid = i["quote_id"]
            async with interaction.client.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = "DELETE FROM quotes WHERE quote_id = $1"
                    await connection.execute(sql, qid)

            all_quotes = self.view.all_quotes
            guild_quotes = self.view.guild_quotes
            all_quotes = [j for j in all_quotes if j != i]
            guild_quotes = [j for j in guild_quotes if j != i]

            txt = f"Quote #{qid} has been deleted."
            if self.view.index != 0:
                self.view.index -= 1
        else:
            txt = "Quote not deleted"
        await edit(content=txt)
        return await self.view.update(interaction)


# TODO: Decorator Buttons
class QuotesView(view_utils.BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(
        self, interaction: Interaction, all_guilds: bool = False
    ) -> None:
        self.all_guilds: bool = all_guilds
        self.all_quotes: list[asyncpg.Record] = interaction.client.quotes
        self.guild_quotes: list[asyncpg.Record]

        if interaction.guild is None:
            self.guild_quotes = []
        else:
            guild_id = interaction.guild.id
            quotes = [i for i in self.all_quotes if i["guild_id"] == guild_id]
            self.guild_quotes = quotes

        self.jump_button: typing.Optional[discord.ui.Button] = None

    @discord.ui.button(row=0, emoji="🎲")
    async def random(self, interaction: Interaction, _) -> None:
        """Randomly select a number"""
        self.index = random.randrange(0, len(self.pages))
        return await self.update(interaction)

    @discord.ui.button(row=3, emoji="🌍")
    async def callback(self, interaction: Interaction, _) -> None:
        """Flip the bool."""
        if self.all_guilds:
            _.style = discord.ButtonStyle.green
        else:
            _.style = discord.ButtonStyle.gray

        self.all_guilds = not self.all_guilds
        self.index = 0
        return await self.update(interaction)

    async def update(self, interaction: Interaction) -> None:
        """Refresh the view and send to user"""
        self.clear_items()

        self.pages = self.all_quotes if self.all_guilds else self.guild_quotes

        if self.index is None:
            # Pull a random quote.
            try:
                quote = random.choice(self.pages)
                self.index = self.pages.index(quote)
            except IndexError:
                embed = discord.Embed(description="No quotes found")
                embed.color = discord.Colour.red()
                self.add_item(view_utils.Stop())

                edit = interaction.response.edit_message
                return await edit(embed=embed, view=self)
        else:
            quote = self.pages[self.index]

        embed = discord.Embed(color=0x7289DA, timestamp=quote["timestamp"])
        if (guild := interaction.client.get_guild(quote["guild_id"])) is None:
            guild = "Deleted Server"
        else:
            guild = guild.name

        gid = quote["guild_id"]
        cid = quote["channel_id"]
        mid = quote["message_id"]
        auth_id = quote["author_user_id"]
        sub_id = quote["submitter_user_id"]

        if (channel := interaction.client.get_channel(cid)) is None:
            channel = "Deleted Channel"
        elif not isinstance(
            channel,
            discord.abc.PrivateChannel
            | discord.ForumChannel
            | discord.StageChannel
            | discord.CategoryChannel,
        ):
            url = f"https://discord.com/channels/{gid}/{cid}/{mid}"
            btn = discord.ui.Button(row=3, emoji="🔗", url=url)
            btn.style = discord.ButtonStyle.link

            self.jump_button = btn
            self.add_item(self.jump_button)

            channel = channel.name

        if (submitter := interaction.client.get_user(sub_id)) is None:
            submitter = "Deleted User"
            ico = QT
        else:
            ico = submitter.display_avatar.url

        embed.set_footer(
            text=f"Quote #{quote['quote_id']}\n{guild} #{channel}\n"
            f"Added by {submitter}",
            icon_url=ico,
        )

        if (author := interaction.client.get_user(auth_id)) is None:
            embed.set_author(name="Deleted User", icon_url=QT)
        else:
            embed.set_author(
                name=f"{author}", icon_url=author.display_avatar.url
            )

        if isinstance(interaction.user, discord.Member):
            perms = interaction.user.resolved_permissions
            is_mod = perms and perms.manage_messages and not self.all_guilds

            if interaction.user.id in [auth_id, sub_id] or is_mod:
                self.add_item(DeleteQuote(quote))

        embed.description = quote["message_content"]
        self.add_page_buttons()

        edit = interaction.response.edit_message
        return await edit(embed=embed, view=self)


# MESSAGE COMMAND, (right click message -> Add quote)
@discord.app_commands.context_menu(name="Add to QuoteDB")
async def quote_add(
    interaction: Interaction, message: discord.Message
) -> None:
    """Add this message to the quote database"""
    blacklist = interaction.client.quote_blacklist

    embed = discord.Embed(colour=discord.Colour.red())

    if interaction.user.id in blacklist:
        embed.description = "❌ You are opted out of the QuoteDB."
        return await interaction.response.send_message(embed=embed)

    if message.author.id in blacklist:
        auth = message.author.mention
        embed.description = f"❌ {auth} is opted out of the QuoteDB."
        return await interaction.response.send_message(embed=embed)

    if interaction.guild is None:
        embed.description = "❌ This command cannot be used in DMs."
        return await interaction.response.send_message(embed=embed)

    if message.author.id == interaction.user.id:
        embed.description = "❌ You cannot quote yourself"
        return await interaction.response.send_message(embed=embed)

    if message.author.bot:
        embed.description = "❌ You cannot quote a bot"
        return await interaction.response.send_message(embed=embed)

    if not message.content:
        embed.description = "❌ That message has no content"
        return await interaction.response.send_message(embed=embed)

    sql = """INSERT INTO quotes (channel_id, guild_id, message_id,
    author_user_id, submitter_user_id, message_content, timestamp)
    VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *"""

    guild = message.guild.id if message.guild else None
    async with interaction.client.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            try:
                await connection.fetchrow(
                    sql,
                    message.channel.id,
                    guild,
                    message.id,
                    message.author.id,
                    interaction.user.id,
                    message.content,
                    message.created_at,
                )
            except asyncpg.UniqueViolationError:
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = "❌ That quote is already in the database"
                return await interaction.response.send_message(embed=embed)

        await cache_quotes(interaction.client)

        embed = discord.Embed(colour=discord.Colour.green())
        embed.description = "Added to quote database"
        await interaction.followup.send(embed=embed, ephemeral=True)

        view = QuotesView(interaction)
        view.index = -1
        return await view.update(interaction)


async def quote_ac(
    ctx: Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete from guild quotes"""

    cur = current.casefold()

    results = []

    client = ctx.client
    for record in sorted(client.quotes, key=lambda i: i["quote_id"]):
        if ctx.guild and record["guild_id"] != ctx.guild.id:
            continue

        if ctx.namespace.user is not None:
            if record["author_user_id"] != ctx.namespace.user.id:
                continue

        if cur not in record["message_content"].casefold():
            continue

        auth = client.get_user(record["author_user_id"])
        qid = record["quote_id"]
        fmt = f"#{qid}: {auth} {record['message_content']}"[:100]

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

        sql = """SELECT * FROM quotes_optout"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch(sql)

        self.bot.quote_blacklist = [r["userid"] for r in records]
        return self.bot.quote_blacklist

    quotes = discord.app_commands.Group(
        name="quote", description="Get from or add to the quote database"
    )

    @quotes.command()
    async def random(self, interaction: Interaction) -> None:
        """Get a random quote."""
        if interaction.user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        view = QuotesView(interaction)
        view.index = random.randrange(0, len(view.guild_quotes) - 1)
        return await view.update(interaction)

    @quotes.command()
    async def last(
        self,
        interaction: Interaction,
        all_guilds: bool = False,
    ) -> None:
        """Get the most recent quote"""
        if interaction.user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        view = QuotesView(interaction, all_guilds=all_guilds)
        view.index = -1
        return await view.update(interaction)

    @quotes.command()
    @discord.app_commands.autocomplete(text=quote_ac)
    @discord.app_commands.describe(text="Search by quote text")
    async def search(
        self,
        interaction: Interaction,
        text: str,
        user: typing.Optional[discord.Member] = None,
    ) -> None:
        """Search for a quote by quote text"""
        if interaction.user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        if user is not None:
            if user.id in self.bot.quote_blacklist:
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = f"🚫 {user.mention} opted out of QuoteDB."
                return await interaction.response.send_message(embed=embed)

        view = QuotesView(interaction)
        quotes = view.guild_quotes

        index = next(i for i in quotes if i["quote_id"] == int(text))
        view.index = quotes.index(index)
        return await view.update(interaction)

    @quotes.command()
    async def user(
        self, interaction: Interaction, member: discord.Member
    ) -> None:
        """Get a random quote from this user."""
        if interaction.user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        if member.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 {member.mention} opted out of QuoteDB."
            return await interaction.response.send_message(embed=embed)

        sql = """SELECT * FROM quotes WHERE author_user_id = $1"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                record = await connection.fetch(sql, member.id)

        view = QuotesView(interaction, record)
        view.all_quotes = record
        view.index = random.randrange(len(view.all_quotes) - 1)
        return await view.update(interaction)

    @quotes.command(name="id")
    @discord.app_commands.describe(quote_id="Enter quote ID#")
    async def quote_by_id(
        self, interaction: Interaction, quote_id: int
    ) -> None:
        """Get a quote by its ID Number"""
        await interaction.response.defer(thinking=True)

        if interaction.user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        try:
            view = QuotesView(interaction)
            view.all_guilds = True

            quotes = view.all_quotes
            index = next(i for i in quotes if i["quote_id"] == quote_id)
            view.index = quotes.index(index)
            return await view.update(interaction)
        except StopIteration:
            err = f"Quote #{quote_id} was not found."
            embed = discord.Embed()
            embed.description = "🚫 " + err
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

    @quotes.command()
    async def stats(
        self, interaction: Interaction, member: discord.Member
    ) -> None:
        """See quote stats for a user"""
        blacklist: list[int] = self.bot.quote_blacklist

        if interaction.user.id in blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        if member.id in blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 {member.mention} opted out of QuoteDB."
            return await interaction.response.send_message(embed=embed)

        guild_id = interaction.guild.id if interaction.guild else None
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                record = await connection.fetchrow(QT_SQL, member.id, guild_id)

        embed = discord.Embed(color=discord.Colour.og_blurple())
        embed.title = "Quote Stats"

        nom = f"{member} ({member.id})"
        embed.set_author(icon_url=member.display_avatar.url, name=nom)

        embed.description = (
            f"Quoted {record['auth_g']} times ({record['auth']} Globally)\n"
            f"Added {record['sub_g']} quotes ({record['sub']} Globally)"
        )

        return await interaction.response.send_message(embed=embed)

    @quotes.command()
    async def opt_out(
        self, interaction: Interaction
    ) -> discord.InteractionMessage:
        """Remove all quotes about, or added by you, and prevent
        future quotes being added."""
        await interaction.response.defer(thinking=True)
        guild_id = interaction.guild.id if interaction.guild else None
        user = interaction.user.id

        sql = """DELETE FROM quotes_optout WHERE userid = $1"""
        if user in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            args = [interaction, "Opt In", "Cancel", discord.ButtonStyle.green]
            view = view_utils.Confirmation(*args)

            await interaction.edit_original_response(content=OPT_IN, view=view)
            await view.wait()

            if view.value:
                # User has chosen to opt in.
                async with self.bot.db.acquire(timeout=60) as connection:
                    await connection.execute(sql, user)

                msg = "You have opted back into the Quotes Database."
            else:
                msg = "Opt in cancelled, quotes cannot be added about you."

            edit = interaction.edit_original_response
            return await edit(content=msg, view=None)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rec = await connection.fetchrow(QT_SQL, user, guild_id)

        # Warn about quotes that will be deleted.
        truthy = [rec["author"], rec["auth_g"], rec["sub"], rec["sub_g"]]
        if all(v == 0 for v in truthy):
            embed = None
        else:
            output = [f"You have been quoted {rec['author']} times"]

            guild = interaction.guild
            if rec["auth"] and guild is not None:
                output.append(f" ({rec['auth_g']} times on {guild.name})")
            output.append("\n")

            output.append(f"You have submitted {rec['sub']} quotes")
            if rec["sub"] and guild is not None:
                output.append(f" ({rec['sub_g']} times on {guild.name})")

            war = "\n\n**ALL of these quotes will be deleted if you opt out.**"
            output.append(war)

            embed = discord.Embed(colour=discord.Colour.red())

            embed.description = "".join(output)
            embed.title = "Your quotes will be deleted if you opt out."

        view = view_utils.Confirmation(
            "Opt out",
            "Cancel",
            discord.ButtonStyle.red,
        )

        txt = "Opt out of QuoteDB?"
        edit = interaction.edit_original_response
        await edit(content=txt, embed=embed, view=view)

        await view.wait()
        if not view.value:
            err = "Opt out cancelled, you can still quote and be quoted"
            embed = discord.Embed()
            embed.description = "🚫 " + err
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        sql = """DELETE FROM quotes WHERE author_user_id = $1
                 OR submitter_user_id = $2"""

        if embed is not None:
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    rec = await connection.execute(sql, user, user)

            embed.description = rec.split(" ")[-1] + " quotes were deleted."

        txt = "You were removed from the Quote Database"

        return await edit(content=txt, embed=embed, view=None)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
