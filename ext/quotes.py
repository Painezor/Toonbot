"""Commands related to the Quote Database Functionality"""
from __future__ import annotations
import datetime

import random
from typing import TYPE_CHECKING, TypeAlias

import asyncpg
import discord
from discord.app_commands import Choice
from discord.ext import commands
from pydantic import BaseModel

from ext.utils import view_utils, embed_utils

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]


QT = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"
OPT_IN = (
    "You are currently opted out of quotes, opting back in will allow "
    "others to add quotes from you to the database. Are you sure?"
)


class Quote(BaseModel):
    quote_id: int
    channel_id: int | None
    guild_id: int | None
    message_id: int | None
    author_user_id: int
    submitter_user_id: int
    message_content: str
    timestamp: datetime.datetime

    @property
    def jump_url(self) -> str:
        gid = self.guild_id
        cid = self.channel_id
        mid = self.message_id

        if None in [gid, cid, mid]:
            return ""

        return f"https://discord.com/channels/{gid}/{cid}/{mid}"


class UserQuoteStats(BaseModel):
    auth: int
    auth_g: int
    sub: int
    sub_g: int

    # After parsing.
    guild_id: int | None
    user_id: int | None

    @property
    def total_quotes(self) -> int:
        return self.auth_g + self.sub_g


class QuoteDatabase:
    connection: asyncpg.Pool[asyncpg.Record]
    quotes: list[Quote] = []
    blacklist: list[int] = []

    @classmethod
    async def cache(cls) -> None:
        quotes = await cls.connection.fetch("""SELECT * FROM quotes""")
        cls.quotes = [Quote.parse_obj(i) for i in quotes]
        bad = await cls.connection.fetch("""SELECT * FROM quotes_optout""")
        cls.blacklist = [r["userid"] for r in bad]

    @classmethod
    def guild_quotes(cls, guild_id: int) -> list[Quote]:
        return [i for i in cls.quotes if i.guild_id == guild_id]

    @classmethod
    async def get_user_stats(
        cls,
        user_id: int,
        guild_id: int | None,
    ) -> UserQuoteStats:
        stats_sql = """ SELECT
        (SELECT COUNT(*) FROM
            quotes WHERE author_user_id = $1) AS auth,
        (SELECT COUNT(*) FROM
            quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
        (SELECT COUNT(*) FROM
            quotes WHERE submitter_user_id = $1) AS sub,
        (SELECT COUNT(*) FROM
            quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""
        rec = await cls.connection.fetchrow(stats_sql, user_id, guild_id)
        stats = UserQuoteStats.parse_obj(rec)
        stats.user_id = user_id
        stats.guild_id = guild_id
        return stats

    @classmethod
    async def get_user_quotes(cls, user_id: int) -> list[Quote]:
        sql = """SELECT * FROM quotes WHERE author_user_id = $1"""
        quotes = await cls.connection.fetch(sql, user_id)
        return [Quote.parse_obj(i) for i in quotes]

    @classmethod
    async def save_quote(
        cls, message: discord.Message, user: discord.User | discord.Member
    ) -> None:
        sql = """INSERT INTO quotes (channel_id, guild_id, message_id,
        author_user_id, submitter_user_id, message_content, timestamp)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *"""

        await cls.connection.execute(
            sql,
            message.channel.id,
            message.guild.id if message.guild else None,
            message.id,
            message.author.id,
            user.id,
            message.content,
            message.created_at,
        )

    @classmethod
    async def remove_blacklisted_user(cls, user_id: int) -> None:
        sql = """DELETE FROM quotes_optout WHERE userid = $1"""
        await cls.connection.execute(sql, user_id)
        try:
            QuoteDatabase.blacklist.remove(user_id)
        except ValueError:
            pass

    @classmethod
    async def remove_user_quotes(cls, user_id: int) -> None:
        sql = """DELETE FROM quotes WHERE author_user_id = $1
                 OR submitter_user_id = $2"""
        await cls.connection.execute(sql, user_id, user_id)


class QuoteTransformer(discord.app_commands.Transformer):
    """Get a quote Object from user input"""

    def __init__(self) -> None:
        pass

    async def autocomplete(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> list[Choice[str]]:
        """Autocomplete from guild quotes"""
        quotes = QuoteDatabase.quotes
        cur = value.casefold()

        results: list[discord.app_commands.Choice[str]] = []

        quotes.sort(key=lambda i: i.quote_id)
        for i in quotes:
            if interaction.guild and i.guild_id != interaction.guild.id:
                continue

            if interaction.namespace.user is not None:
                if i.author_user_id != interaction.namespace.user.id:
                    continue

            qid = i.quote_id
            auth = interaction.client.get_user(i.author_user_id)
            fmt = f"#{qid}: {auth} {i.message_content}"
            if cur not in f"#{qid}" + i.message_content.casefold():
                continue

            fmt = fmt[:100]

            opt = discord.app_commands.Choice(name=fmt, value=str(qid))
            results.append(opt)

            if len(results) == 25:
                break

        return results

    async def transform(  # type: ignore
        self, interaction: Interaction, value: str, /
    ) -> Quote | None:
        """Get Quote from selection"""
        quotes = QuoteDatabase.quotes
        try:
            return next(i for i in quotes if i.quote_id == value)
        except StopIteration:
            pass

        try:
            return next(i for i in quotes if value in i.message_content)
        except StopIteration:
            pass

        embed = discord.Embed(title="Quote not Found")
        embed.description = f"Could not find quote matching {value}"
        await interaction.response.send_message(embed=embed, ephemeral=True)


class QuoteEmbed(discord.Embed):
    """Convert a record object to an Embed"""

    def __init__(self, interaction: Interaction, quote: Quote):
        super().__init__(color=0x7289DA, timestamp=quote.timestamp)

        if quote.guild_id:
            if (guild := interaction.client.get_guild(quote.guild_id)) is None:
                guild = "Deleted Server"
            else:
                guild = guild.name
        else:
            guild = "Unknown Server"

        if quote.channel_id:
            cid = quote.channel_id
            if (channel := interaction.client.get_channel(cid)) is None:
                channel = "Deleted Channel"
        else:
            channel = "Unknown Channel"

        sub_id = quote.submitter_user_id
        if (submitter := interaction.client.get_user(sub_id)) is None:
            submitter = "Deleted User"
            ico = QT
        else:
            ico = submitter.display_avatar.url

        auth_id = quote.author_user_id
        self.set_footer(
            text=f"Quote #{quote.quote_id}\n"
            f"{guild} #{channel}\nAdded by {submitter}",
            icon_url=ico,
        )

        if (author := interaction.client.get_user(auth_id)) is None:
            self.set_author(name="Deleted User", icon_url=QT)
        else:
            embed_utils.user_to_author(self, author)

        self.description = quote.message_content


class QuotesView(view_utils.Paginator):
    """Generic Paginator that returns nothing."""

    def __init__(
        self, interaction: Interaction, all_guilds: bool = False
    ) -> None:
        self.all_guilds: bool = all_guilds
        self.current: list[Quote]

        if interaction.guild is not None:
            self.current = QuoteDatabase.guild_quotes(interaction.guild.id)
        else:
            self.current = QuoteDatabase.quotes

        super().__init__(interaction.user, len(self.current))

        self.qtjmp: discord.ui.Button[QuotesView] | None = None

    @discord.ui.button(row=0, emoji="🎲")
    async def random(
        self, interaction: Interaction, _: discord.ui.Button[QuotesView]
    ) -> None:
        """Randomly select a number"""
        try:
            rng_quote = random.choice(self.current)
            self.index = self.current.index(rng_quote)
            embed = QuoteEmbed(interaction, rng_quote)
        except ValueError:
            embed = discord.Embed(title="No Quotes on server")
            embed.description = "Your server does not have any quotes!"
        self.edit_buttons()
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(row=1, emoji="🌍")
    async def global_btn(
        self, interaction: Interaction, btn: discord.ui.Button[QuotesView]
    ) -> None:
        """Flip the bool."""
        self.all_guilds = not self.all_guilds
        if self.all_guilds or interaction.guild is None:
            self.current = QuoteDatabase.quotes
            self.global_btn.style = discord.ButtonStyle.green
        else:
            self.current = QuoteDatabase.guild_quotes(interaction.guild.id)
            self.global_btn.style = discord.ButtonStyle.red

        self.pages = len(self.current)
        self.index = 0
        embed = QuoteEmbed(interaction, self.current[self.index])
        self.edit_buttons()
        return await interaction.response.edit_message(embed=embed, view=self)

    def edit_buttons(self) -> None:
        """Refresh the jump button's text"""
        self.jump.label = f"{self.index + 1}/{self.pages}"

        try:
            quote = self.current[self.index]
        except IndexError:
            if self.qtjmp is not None:
                self.remove_item(self.qtjmp)
            return

        self.delete.disabled = not self.all_guilds

        self.next.disabled = self.pages <= self.index + 1
        self.jump.disabled = self.pages < 3
        self.previous.disabled = self.index == 0

        if self.qtjmp is not None:
            self.remove_item(self.qtjmp)

        if quote.jump_url is not None:
            self.qtjmp = discord.ui.Button(url=quote.jump_url, emoji="🔗")
            self.add_item(self.qtjmp)

    @discord.ui.button(
        row=1, emoji="🗑️", style=discord.ButtonStyle.red, label="Delete"
    )
    async def delete(self, interaction: Interaction, _) -> None:
        """Delete quote by quote ID"""
        quote = self.current[self.index]

        owner = interaction.client.owner_id
        override = [quote.author_user_id, quote.submitter_user_id, owner]
        if interaction.guild is None or interaction.guild.id != quote.guild_id:
            if interaction.user.id not in override:
                err = "🚫 You can't delete other servers quotes."
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = err
                return await interaction.response.edit_message(embed=embed)

        if not interaction.permissions.manage_messages:
            if interaction.user.id not in override:
                err = "🚫 You need manage messages permissions to do that"
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = err
                return await interaction.response.edit_message(embed=embed)

        confirm = view_utils.Confirmation(interaction.user)
        confirm.true.style = discord.ButtonStyle.red
        txt = "Delete this quote?"
        await interaction.response.edit_message(content=txt, view=confirm)
        await confirm.wait()

        if confirm.value:  # Bool is True
            qid = quote.quote_id
            sql = "DELETE FROM quotes WHERE quote_id = $1"
            await interaction.client.db.execute(sql, qid)

            QuotesView._cache = [j for j in QuotesView._cache if j != quote]

            txt = f"Quote #{qid} has been deleted."
            if self.index != 0:
                self.index -= 1

            embed = discord.Embed(title="Quote Deleted", description=txt)
            embed_utils.user_to_footer(embed, interaction.user)
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(title="Quote Not Deleted", description=txt)
            await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            embed = QuoteEmbed(interaction, self.current[self.index - 1])
        except IndexError:
            try:
                embed = QuoteEmbed(interaction, self.current[0])
            except IndexError:
                embed = discord.Embed(title="No Quotes Found")
        self.edit_buttons()
        await confirm.interaction.response.edit_message(embed=embed, view=self)

    async def handle_page(  # type: ignore
        self, interaction: Interaction
    ) -> None:
        """Generic, Entry point."""
        embed = QuoteEmbed(interaction, self.current[self.index])
        self.edit_buttons()
        await interaction.response.edit_message(embed=embed, view=self)


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

    try:
        await QuoteDatabase.save_quote(message, interaction.user)
    except asyncpg.UniqueViolationError:
        embed = discord.Embed(colour=discord.Colour.red())
        embed.description = "❌ That quote is already in the database"
        return await interaction.response.send_message(embed=embed)

    embed = discord.Embed(colour=discord.Colour.green())
    embed.description = "Added to quote database"
    await interaction.response.send_message(embed=embed)
    await QuoteDatabase.cache()


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot: Bot) -> None:
        bot.tree.add_command(quote_add)
        self.bot: Bot = bot

    async def cog_load(self) -> None:
        """When the cog loads…"""
        QuoteDatabase.connection = self.bot.db
        await QuoteDatabase.cache()

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

        rndqt = QuotesView(interaction, False)
        try:
            rndqt.index = random.randrange(0, len(rndqt.current) - 1)
            embed = QuoteEmbed(interaction, rndqt.current[rndqt.index])
        except ValueError:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 Your server has no quotes!"
        await interaction.response.send_message(embed=embed, view=rndqt)
        rndqt.message = await interaction.original_response()

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

        qtlst = QuotesView(interaction, all_guilds)
        qtlst.index = -1
        try:
            embed = QuoteEmbed(interaction, qtlst.current[qtlst.index])
        except IndexError:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "No quotes found on this server!"
        await interaction.response.send_message(embed=embed, view=qtlst)
        qtlst.message = await interaction.original_response()

    @quotes.command()
    @discord.app_commands.describe(text="Search by quote text")
    async def search(
        self,
        interaction: Interaction,
        text: discord.app_commands.Transform[Quote, QuoteTransformer],
        user: discord.Member | None = None,
    ) -> None:
        """Search for a quote by quote text"""
        if interaction.user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 You are opted out of the QuoteDB."
            return await interaction.response.send_message(embed=embed)

        if user is not None and user.id in self.bot.quote_blacklist:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 {user.mention} opted out of QuoteDB."
            return await interaction.response.send_message(embed=embed)

        qtsrch = QuotesView(interaction, False)
        try:
            qtsrch.index = qtsrch.current.index(text)
        except ValueError:
            qtsrch.index = 0
        embed = QuoteEmbed(interaction, text)
        await interaction.response.send_message(embed=embed, view=qtsrch)
        qtsrch.message = await interaction.original_response()

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

        if not (records := await QuoteDatabase.get_user_quotes(member.id)):
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = f"🚫 {member.mention} has no quotes."
            return await interaction.response.send_message(embed=embed)

        qtusr = QuotesView(interaction, False)
        try:
            qtusr.index = random.randrange(0, len(records) - 1)
        except ValueError:
            qtusr.index = 0
        embed = QuoteEmbed(interaction, records[qtusr.index])
        await interaction.response.send_message(embed=embed, view=qtusr)
        qtusr.message = await interaction.original_response()

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
        rec = await QuoteDatabase.get_user_stats(member.id, guild_id)
        embed = discord.Embed(color=discord.Colour.og_blurple())
        embed.title = "Quote Stats"

        nom = f"{member} ({member.id})"
        embed.set_author(icon_url=member.display_avatar.url, name=nom)

        if rec is not None:
            embed.description = (
                f"Quoted {rec.auth_g} times ({rec.auth} Globally)\n"
                f"Added {rec.sub_g} quotes ({rec.sub} Globally)"
            )
        else:
            embed.description = "No Quotes found for that user."

        return await interaction.response.send_message(embed=embed)

    @quotes.command()
    async def opt_out(self, interaction: Interaction) -> None:
        """Remove all quotes about, or added by you, and prevent
        future quotes being added."""
        guild_id = interaction.guild.id if interaction.guild else None
        user = interaction.user

        if user.id in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            cfrm = view_utils.Confirmation(user, "Opt In", "Cancel")
            cfrm.true.style = discord.ButtonStyle.green

            await interaction.response.send_message(content=OPT_IN, view=cfrm)
            await cfrm.wait()

            if cfrm.value:
                await QuoteDatabase.remove_blacklisted_user(user.id)
                msg = "You have opted back into the Quotes Database."
            else:
                msg = "Opt in cancelled, quotes cannot be added about you."

            resp = cfrm.interaction.response
            await resp.edit_message(content=msg, view=None)
            return

        rec = await QuoteDatabase.get_user_stats(user.id, guild_id)
        cfrm = view_utils.Confirmation(user, "Opt Out", "Cancel")
        cfrm.true.style = discord.ButtonStyle.red

        # Warn about quotes that will be deleted.
        embed = discord.Embed(colour=discord.Colour.red())
        if rec is None:
            embed.title = "Opt out of Quote Database?"
        elif any([rec.auth, rec.auth_g, rec.sub, rec.sub_g]):
            output = [f"You have been quoted {rec.auth} times"]

            guild = interaction.guild
            if rec.auth and guild is not None:
                output.append(f" ({rec.auth_g} times on {guild.name})")
            output.append("\n")

            output.append(f"You have submitted {rec.sub} quotes")
            if rec.sub and guild is not None:
                output.append(f" ({rec.sub_g} times on {guild.name})")

            _ = "\n\n**ALL of these quotes will be deleted if you opt out.**"
            output.append(_)
            embed.description = "".join(output)
            embed.title = "Your quotes will be deleted if you opt out."
        else:
            embed.title = "Opt out of Quote Database?"

        await interaction.response.send_message(embed=embed, view=cfrm)
        cfrm.message = await interaction.original_response()

        await cfrm.wait()
        if not cfrm.value:
            err = "🚫 Opt out cancelled, you can still quote and be quoted"
            embed = discord.Embed(colour=discord.Color.red())
            embed.description = err
            _ = cfrm.interaction.response.send_message
            return await _(embed=embed, ephemeral=True)

        await QuoteDatabase.remove_user_quotes(user.id)
        _ = f"{rec.total_quotes} quotes were deleted." if rec else ""
        txt = f"You were removed from the Quote Database. {_}"
        await cfrm.interaction.response.edit_message(content=txt, view=None)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
