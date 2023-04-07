"""Commands related to the Quote Database Functionality"""
from __future__ import annotations

import random
import typing
import importlib

import asyncpg
import discord
from discord.ext import commands

from ext.utils import view_utils, embed_utils

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


class QuoteTransformer(discord.app_commands.Transformer):
    """Get a quote Object from user input"""

    async def autocomplete(
        self, interaction: Interaction, value: str, /
    ) -> list[discord.app_commands.Choice[str]]:
        """Autocomplete from guild quotes"""
        cur = value.casefold()

        results = []

        quotes = interaction.client.quotes
        for quote in sorted(quotes, key=lambda i: i["quote_id"]):
            if interaction.guild and quote["guild_id"] != interaction.guild.id:
                continue

            if interaction.namespace.user is not None:
                if quote["author_user_id"] != interaction.namespace.user.id:
                    continue

            qid = quote["quote_id"]
            auth = interaction.client.get_user(quote["author_user_id"])
            fmt = f"#{qid}: {auth} {quote['message_content']}"
            if cur not in f"#{qid}" + quote["message_content"].casefold():
                continue

            fmt = fmt[:100]

            results.append(
                discord.app_commands.Choice(name=fmt, value=str(qid))
            )

            if len(results) == 25:
                break

        return results

    async def transform(
        self, interaction: Interaction, value: str, /
    ) -> asyncpg.Record:
        quotes = interaction.client.quotes
        return next(i for i in quotes if i["quote_id"] == value)


class QuoteEmbed(discord.Embed):
    """Convert a record object to an Embed"""

    def __init__(self, interaction: Interaction, quote: asyncpg.Record):
        super().__init__(color=0x7289DA, timestamp=quote["timestamp"])

        gid = quote["guild_id"]
        cid = quote["channel_id"]
        auth_id = quote["author_user_id"]
        sub_id = quote["submitter_user_id"]

        if (guild := interaction.client.get_guild(gid)) is None:
            guild = "Deleted Server"
        else:
            guild = guild.name

        if (channel := interaction.client.get_channel(cid)) is None:
            channel = "Deleted Channel"

        if (submitter := interaction.client.get_user(sub_id)) is None:
            submitter = "Deleted User"
            ico = QT
        else:
            ico = submitter.display_avatar.url

        self.set_footer(
            text=f"Quote #{quote['quote_id']}\n"
            f"{guild} #{channel}\nAdded by {submitter}",
            icon_url=ico,
        )

        if (author := interaction.client.get_user(auth_id)) is None:
            self.set_author(name="Deleted User", icon_url=QT)
        else:
            embed_utils.user_to_author(self, author)

        self.description = quote["message_content"]


async def cache_quotes(bot: Bot) -> None:
    """Cache the QuoteDB"""
    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            sql = """SELECT * FROM quotes"""
            bot.quotes = await connection.fetch(sql)


class QuotesView(view_utils.BaseView):
    """Generic Paginator that returns nothing."""

    def __init__(
        self, interaction: Interaction, all_guilds: bool = False
    ) -> None:
        super().__init__()
        self.all_guilds: bool = all_guilds
        self.all_quotes: list[asyncpg.Record] = interaction.client.quotes

        if interaction.guild is not None:
            _ = self.all_quotes
            _ = [i for i in _ if i["guild_id"] == interaction.guild.id]
            self.guild_quotes: list[asyncpg.Record] = _
        else:
            self.guild_quotes = []

    @discord.ui.button(row=0, emoji="🎲")
    async def random(self, interaction: Interaction, _) -> None:
        """Randomly select a number"""
        self.index = random.randrange(1, len(self.pages)) - 1

        quote = self.pages[self.index]
        embed = QuoteEmbed(interaction, quote)
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(row=3, emoji="🌍")
    async def global_btn(self, interaction: Interaction, btn) -> None:
        """Flip the bool."""
        self.all_guilds = not self.all_guilds
        if self.all_guilds:
            self.pages = self.all_quotes
            btn.style = discord.ButtonStyle.green
            self.delete.disabled = True
        else:
            self.pages = self.guild_quotes
            btn.style = discord.ButtonStyle.red
            self.delete.disabled = False

        self.index = 0
        embed = QuoteEmbed(interaction, self.pages[self.index])
        return await interaction.response.edit_message(embed=embed, view=self)

    def edit_buttons(self) -> None:
        """Refresh the jump button's text"""
        quote = self.pages[self.index]
        gid = quote["guild_id"]
        cid = quote["channel_id"]
        mid = quote["message_id"]
        self.jump.url = f"https://discord.com/channels/{gid}/{cid}/{mid}"

    @discord.ui.button(emoji="🔗", row=3, style=discord.ButtonStyle.url)
    async def jump(self, _: Interaction, __) -> None:
        """Jump to Quote"""
        return

    @discord.ui.button(
        row=3, emoji="🗑️", style=discord.ButtonStyle.red, label="Delete"
    )
    async def delete(self, interaction: Interaction, _) -> None:
        """Delete quote by quote ID"""
        quote = self.pages[self.index]

        owner = interaction.client.owner_id
        override = [quote["author_user_id"], quote["submitter_user_id"], owner]
        if (
            interaction.guild is None
            or interaction.guild.id != quote["guild_id"]
        ):

            if interaction.user.id not in override:
                err = "🚫 You can't delete other servers quotes."
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = err
                return await interaction.response.edit_message(embed=embed)

        if not interaction.permissions.manage_guild:
            if interaction.user.id not in override:
                err = "🚫 Only moderators, submitter, or author can delete."
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = err
                return await interaction.response.edit_message(embed=embed)

        view = view_utils.Confirmation()
        view.true.style = discord.ButtonStyle.red
        txt = "Delete this quote?"
        await interaction.response.edit_message(content=txt, view=view)
        await view.wait()

        if view.value:  # Bool is True
            qid = quote["quote_id"]
            async with interaction.client.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = "DELETE FROM quotes WHERE quote_id = $1"
                    await connection.execute(sql, qid)

            all_quotes = self.all_quotes
            guild_quotes = self.guild_quotes
            all_quotes = [j for j in all_quotes if j != quote]
            guild_quotes = [j for j in guild_quotes if j != quote]

            txt = f"Quote #{qid} has been deleted."
            if self.index != 0:
                self.index -= 1

            embed = discord.Embed(title="Quote Deleted", description=txt)
            embed_utils.user_to_footer(embed, interaction.user)
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(title="Quote Not Deleted", description=txt)
            await interaction.followup.send(embed=embed, ephemeral=True)

        embed = QuoteEmbed(interaction, quote)
        await view.interaction.response.edit_message(embed=embed, view=self)

    async def update(self, interaction: Interaction) -> None:
        """Generic, Entry point."""
        embed = QuoteEmbed(interaction, self.pages[self.index])
        return await interaction.response.edit_message(embed=embed)


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
                await connection.execute(
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
        view.index = len(interaction.client.quotes) - 1
        embed = QuoteEmbed(interaction, view)
        return await interaction.response.send_message(embed=embed, view=view)


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

        view = QuotesView(interaction, False)
        view.index = random.randrange(0, len(view.guild_quotes) - 1)
        embed = QuoteEmbed(interaction, view.pages[view.index])
        return await interaction.response.send_message(embed=embed, view=view)

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

        view = QuotesView(interaction, all_guilds)
        view.index = -1
        embed = QuoteEmbed(interaction, view.pages[view.index])
        return await interaction.response.send_message(embed=embed, view=view)

    @quotes.command()
    @discord.app_commands.describe(text="Search by quote text")
    async def search(
        self,
        interaction: Interaction,
        text: discord.app_commands.Transform[QuoteTransformer, asyncpg.Record],
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

        view = QuotesView(interaction, False)
        quotes = view.guild_quotes
        view.index = quotes.index(text)
        embed = QuoteEmbed(interaction, text)
        return await interaction.response.send_message(embed=embed, view=view)

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

        if record is None:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 {member.mention} has no quotes."
            return await interaction.response.send_message(embed=embed)

        view = QuotesView(interaction, False)
        view.all_quotes = record
        view.index = random.randrange(len(view.all_quotes) - 1)
        embed = QuoteEmbed(interaction, record)
        return await interaction.response.send_message(embed=embed, view=view)

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
    async def opt_out(self, interaction: Interaction) -> None:
        """Remove all quotes about, or added by you, and prevent
        future quotes being added."""
        guild_id = interaction.guild.id if interaction.guild else None
        user_id = interaction.user.id

        if user_id in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            confirm = view_utils.Confirmation("Opt In", "Cancel")
            confirm.true.style = discord.ButtonStyle.green

            await interaction.response.send_message(
                content=OPT_IN, view=confirm
            )
            await confirm.wait()

            if confirm.value:
                # User has chosen to opt in.
                sql = """DELETE FROM quotes_optout WHERE userid = $1"""
                async with self.bot.db.acquire(timeout=60) as connection:
                    await connection.execute(sql, user_id)

                msg = "You have opted back into the Quotes Database."
            else:
                msg = "Opt in cancelled, quotes cannot be added about you."

            send = confirm.interaction.response.edit_message
            return await send(content=msg, view=None)

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rec = await connection.fetchrow(QT_SQL, user_id, guild_id)

        confirm = view_utils.Confirmation("Opt Out", "Cancel")
        confirm.true.style = discord.ButtonStyle.red

        txt = "Opt out of QuoteDB?"
        send = interaction.response.send_message
        # Warn about quotes that will be deleted.
        if any([rec["author"], rec["auth_g"], rec["sub"], rec["sub_g"]]):
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
            await send(content=txt, embed=embed, view=confirm)
        else:
            await send(content=txt, view=confirm)

        await confirm.wait()
        if not confirm.value:
            err = "🚫 Opt out cancelled, you can still quote and be quoted"
            embed = discord.Embed(colour=discord.Color.red())
            embed.description = err
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True)

        sql = """DELETE FROM quotes WHERE author_user_id = $1
                 OR submitter_user_id = $2"""

        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                rec = await connection.execute(sql, user_id, user_id)

        deleted = rec.split(" ")[-1] + " quotes were deleted."
        txt = f"You were removed from the Quote Database. {deleted}"
        await confirm.interaction.response.edit_message(content=txt, view=None)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
