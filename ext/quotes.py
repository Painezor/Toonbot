"""Commands related to the Quote Database Functionality"""
from __future__ import annotations

import random
from importlib import reload
from typing import TYPE_CHECKING

import discord
from asyncpg import UniqueViolationError, Record
from discord import Embed, ButtonStyle, Interaction, Colour, Message, Member, HTTPException
from discord.app_commands import Group, context_menu, describe, autocomplete, Choice, AppCommandError
from discord.ext import commands
from discord.ui import Button

from ext.utils import view_utils
from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot

QUOTE_IMG = "https://discordapp.com/assets/2c21aeda16de354ba5334551a883b481.png"
OPT_IN = "You are currently opted out of quotes, opting back in will allow " \
         "others to add quotes from you to the database. Are you sure?"


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

    def __init__(self, quote: Record, row: int = 3) -> None:
        self.quote: Record = quote
        super().__init__(style=ButtonStyle.red, label="Delete", emoji="🗑️", row=row)

    async def callback(self, interaction: Interaction):
        """Delete quote by quote ID"""
        bot: Bot = interaction.client
        r = self.quote

        if r["guild_id"] != interaction.guild.id or interaction.guild.id is None:
            if interaction.user.id not in [r["author_user_id"], r["submitter_user_id"], bot.owner_id]:
                return await self.view.update(content=f"You can't delete other servers quotes.")

        _ = self.view.interaction.user.id in [r["author_user_id"], r["submitter_user_id"]]
        if _ or interaction.app_permissions.manage_messages:
            view = view_utils.Confirmation(self.view.interaction, label_a="Delete",
                                           colour_a=ButtonStyle.red, label_b="Cancel")
            m = await bot.reply(interaction, content="Delete this quote?", view=view)
            await view.wait()

            try:
                await m.delete()
            except AttributeError:
                pass

            if view.value:
                async with bot.db.acquire(timeout=60) as connection:
                    async with connection.transaction():
                        await connection.execute("DELETE FROM quotes WHERE quote_id = $1", r['quote_id'])

                await self.view.interaction.followup.send(f"Quote #{r['quote_id']} has been deleted.")
                await self.view.update()
                if self.view.index != 0:
                    self.view.index -= 1
            else:
                await self.view.interaction.followup.send("Quote not deleted")
        else:
            await self.view.interaction.followup.send("Only people involved with the quote or"
                                                      " moderators can delete a quote")


class Global(Button):
    """Toggle This Server Only or Global"""

    def __init__(self, view: QuotesView, row: int = 3) -> None:
        super().__init__(style=ButtonStyle.green if view.all_guilds else ButtonStyle.gray, row=row, emoji="🌍")

    async def callback(self, interaction: Interaction) -> Message:
        """Flip the bool."""
        await interaction.response.defer()
        self.view.all_guilds = not self.view.all_guilds
        self.view.index = 0
        return await self.view.update()


class RandomQuote(Button):
    """Push a random quote to the view."""

    def __init__(self, row: int = 3) -> None:
        super().__init__(row=row, emoji="🎲")

    async def callback(self, interaction: Interaction) -> Message:
        """Randomly select a number"""
        await interaction.response.defer()
        self.view.index = random.randrange(0, len(self.view.pages))
        return await self.view.update()


class QuotesView(BaseView):
    """Generic Paginator that returns nothing."""
    def __init__(self, interaction: Interaction, all_guilds: bool = False) -> None:
        super().__init__(interaction)
        self.all_quotes: list[Record] = self.bot.quotes
        self.guild_quotes: list[Record] = [i for i in self.all_quotes if i['guild_id'] == interaction.guild.id]
        self.pages: list[Record] = []
        self.index: int = 0
        self.all_guilds = all_guilds

        self.jump_button = None

    async def on_timeout(self) -> Message:
        """Remove buttons and dropdowns when listening stops."""
        v = discord.ui.View()
        if self.jump_button is not None:
            v.add_item(self.jump_button)
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
                return await self.interaction.edit_original_response(embed=e, view=self)
        else:
            quote = self.pages[self.index]

        e: Embed = Embed(color=0x7289DA, description="", timestamp=quote['timestamp'])
        guild = "Deleted Server" if (guild := self.bot.get_guild(quote["guild_id"])) is None else guild.name

        if (channel := self.bot.get_channel(quote["channel_id"])) is None:
            channel = "Deleted Channel"
        else:
            try:
                message = await channel.fetch_message(quote["message_id"])
                self.jump_button = Button(style=ButtonStyle.link, url=message.jump_url, emoji="🔗", row=3)
                self.add_item(self.jump_button)
            except (AttributeError, HTTPException):
                # Channel Is Deleted or we don't have perms
                self.jump_button = None
            channel = channel.name

        if (submitter := self.bot.get_user(quote["submitter_user_id"])) is None:
            submitter = "Deleted User"
            ico = QUOTE_IMG
        else:
            ico = submitter.display_avatar.url
        e.set_footer(text=f"Quote #{quote['quote_id']}\n{guild} #{channel}\nAdded by {submitter}", icon_url=ico)

        if (author := self.bot.get_user(quote["author_user_id"])) is None:
            e.set_author(name=f"Deleted User", icon_url=QUOTE_IMG)
        else:
            e.set_author(name=f"{author}", icon_url=author.display_avatar.url)

        is_mod = self.interaction.user.resolved_permissions.manage_messages and not self.all_guilds
        if self.interaction.user.id in [quote['author_user_id'], quote['submitter_user_id']] or is_mod:
            self.add_item(DeleteQuote(quote))

        e.description += quote['message_content']

        self.add_item(RandomQuote(row=0))
        if len(self.pages) > 1:
            self.add_item(view_utils.Previous(self))
            if len(self.pages) > 3:
                self.add_item(view_utils.Jump(self))
            self.add_item(view_utils.Next(self))
            self.add_item(view_utils.Stop(row=0))
        else:
            self.add_item(view_utils.Stop())

        return await self.bot.reply(self.interaction, embed=e, view=self)


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

    async with bot.db.acquire(timeout=60) as connection:
        async with connection.transaction():
            try:
                await connection.fetchrow(
                    """INSERT INTO quotes
                    (channel_id,guild_id,message_id,author_user_id,submitter_user_id,message_content,timestamp)
                    VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
                    message.channel.id, message.guild.id, message.id, message.author.id, interaction.user.id,
                    message.content, message.created_at)
            except UniqueViolationError:
                return await bot.error(interaction, content="That quote is already in the database!")

        await bot.cache_quotes()

        e = Embed(colour=Colour.green(), description="Added to quote database")
        await interaction.followup.send(embed=e, ephemeral=True)

        v = QuotesView(interaction)
        v.index = -1
        return await v.update()


async def quote_ac(interaction: Interaction, current: str) -> list[Choice[str]]:
    """Autocomplete from guild quotes"""
    bot: Bot = interaction.client

    results = [i for i in bot.quotes if i['guild_id'] == interaction.guild.id]
    if interaction.namespace.user is not None:
        results = [i for i in results if i['author_user_id'] == interaction.namespace.user.id]

    results = [Choice(name=f"#{r['quote_id']}: {bot.get_user(r['author_user_id'])} {r['message_content']}"[:100],
                      value=str(r['quote_id'])) for r in results if current.lower() in r['message_content'].lower()]
    return results[:25]


class QuoteDB(commands.Cog):
    """Quote Database module"""

    def __init__(self, bot: Bot) -> None:
        bot.tree.add_command(quote_add)
        self.bot: Bot = bot
        QuotesView.bot = bot

        reload(view_utils)

    async def cog_load(self) -> None:
        """When the cog loads…"""
        await self.opt_outs()
        await self.bot.cache_quotes()

    async def opt_outs(self) -> None:
        """Cache the list of users who have opted out of the quote DB"""
        async with self.bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                records = await connection.fetch("""SELECT * FROM quotes_optout""")
        self.bot.quote_blacklist = [r['userid'] for r in records]

    quotes = Group(name="quote", description="Get from or add to the quote database")

    @quotes.command()
    async def random(self, interaction: Interaction) -> Message:
        """Get a random quote."""
        await interaction.response.defer(thinking=True)

        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError

        view = QuotesView(interaction)
        view.index = random.randrange(0, len(view.guild_quotes) - 1)
        return await view.update()

    @quotes.command()
    async def last(self, interaction: Interaction, all_guilds: bool = False) -> Message:
        """Get the most recent quote"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError
        v = QuotesView(interaction, all_guilds=all_guilds)
        v.index = -1
        return await v.update()

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

        v = QuotesView(interaction)
        v.index = v.guild_quotes.index(next(i for i in v.guild_quotes if i['quote_id'] == int(text)))
        return await v.update()

    @quotes.command()
    async def user(self, interaction: Interaction, member: Member):
        """Get a random quote from this user."""
        bot: Bot = interaction.client
        blacklist = bot.quote_blacklist

        if interaction.user.id in blacklist:
            raise OptedOutError
        if member.id in blacklist:
            raise TargetOptedOutError(member)

        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                sql = """SELECT * FROM quotes WHERE author_user_id = $1 ORDER BY random()"""
                r = await connection.fetch(sql, member.id)

        await QuotesView(interaction, r).update()

    @quotes.command()
    @describe(quote_id="Enter quote ID#")
    async def id(self, interaction: Interaction, quote_id: int) -> Message:
        """Get a quote by its ID Number"""
        if interaction.user.id in self.bot.quote_blacklist:
            raise OptedOutError

        try:
            v = QuotesView(interaction)
            v.all_guilds = True
            v.index = v.all_quotes.index(next(i for i in v.all_quotes if i['quote_id'] == quote_id))
            return await v.update()
        except StopIteration:
            return await self.bot.error(interaction, f"Quote #{quote_id} was not found.")

    @quotes.command()
    async def stats(self, interaction: Interaction, member: Member):
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

        async with bot.db.acquire(timeout=60) as connection:
            async with connection.transaction():
                r = await connection.fetchrow(sql, *escaped)

        e: Embed = Embed(color=Colour.og_blurple(), title="Quote Stats")
        e.set_author(icon_url=member.display_avatar.url, name=f"{member} ({member.id})")
        e.description = f"Quoted {r['auth_g']} times ({r['auth']} Globally)\n"\
                        f"Added {r['sub_g']} quotes ({r['sub']} Globally)"
        await bot.reply(interaction, embed=e)

    @quotes.command()
    async def opt_out(self, i: Interaction):
        """Remove all quotes about, or added by you, and prevent future quotes being added."""
        if i.user.id in self.bot.quote_blacklist:
            #   Opt Back In confirmation Dialogue
            v = view_utils.Confirmation(i, label_a="Opt In", colour_a=ButtonStyle.green, label_b="Cancel")
            await self.bot.reply(i, content=OPT_IN, view=v)
            await v.wait()

            if v.value:  # User has chosen to opt in.
                async with self.bot.db.acquire(timeout=60) as connection:
                    await connection.execute("""DELETE FROM quotes_optout WHERE userid = $1""", i.user.id)

                return await self.bot.reply(i, "You have opted back into the Quotes Database.", view=None)
            else:
                return await self.bot.error(i, "Opt in cancelled, quotes cannot be added about you.")

        sql = """SELECT (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1) AS author,
                        (SELECT COUNT(*) FROM quotes WHERE author_user_id = $1 AND guild_id = $2) AS auth_g,
                        (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1) AS sub,
                        (SELECT COUNT(*) FROM quotes WHERE submitter_user_id = $1 AND guild_id = $2) AS sub_g"""

        async with self.bot.db.acquire(timeout=60) as connection:
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
        await self.bot.reply(i, content="Opt out of QuoteDB?", embed=e, view=v)
        await v.wait()

        if not v.value:
            return await self.bot.error(i, "Opt out cancelled, you can still quote and be quoted")

        if e is not None:
            async with self.bot.db.acquire(timeout=60) as connection:
                async with connection.transaction():
                    sql = """DELETE FROM quotes WHERE author_user_id = $1 OR submitter_user_id = $2"""
                    r = await connection.execute(sql, i.user.id, i.user.id)
            e.description = r.split(' ')[-1] + " quotes were deleted."
        await self.bot.reply(i, content=f"You were removed from the Quote Database", embed=e)


async def setup(bot: Bot):
    """Load the quote database module into the bot"""
    await bot.add_cog(QuoteDB(bot))
