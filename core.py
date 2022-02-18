"""Master file for toonbot."""
import asyncio
import json
from abc import ABC
from datetime import datetime

import asyncpg
from discord import Embed, Colour, HTTPException, ApplicationContext, Intents, Game
from discord.ext import commands

with open('credentials.json') as f:
    credentials = json.load(f)

COGS = ['errors', 'session',  # Utility Cogs
        # Slash commands.
        'admin', 'fixtures', 'fun', 'images', 'info', 'scores', 'ticker', "transfers", 'tv', 'logs', 'lookup', 'mod',
        'nufc', 'quotes', 'reminders', 'rss', 'sidebar', 'warships']

INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=250051254783311873&permissions=1514244730006" \
             "&scope=bot%20applications.commands"


class Context(commands.Context):
    """Override CTX for regular commands"""

    async def error(self, text, view=None, message=None):
        """Master reply handler for bot, with fallbacks."""
        e = Embed()
        e.colour = Colour.red()
        e.description = text

        if view is not None:
            if message is None:
                await self.reply(embed=e, view=view, ephemeral=True)
            else:
                await message.edit(embed=e, view=view)
        else:
            if message is None:
                await self.reply(embed=e, ephemeral=True)
            else:
                await message.edit(embed=e)

    async def reply(self, **kwargs):
        """Generic reply, with fallback options."""
        try:  # First we attempt to use direct reply functionality
            return await self.send(reference=self.message, **kwargs)
        except HTTPException:
            try:
                return await self.send(**kwargs)
            except HTTPException:
                # Final fallback, DM invoker.
                try:
                    target = self.author
                    return await target.send(**kwargs)
                except HTTPException:
                    pass


class AppContext(ApplicationContext):
    """Overridden Application Commands Context"""

    async def reply(self, **kwargs):
        """Master reply handler for bot, with fallbacks."""
        interaction = await self.respond(**kwargs)
        try:
            return await interaction.original_message()
        except AttributeError:  # actually a WebhookMessage, bot already responded
            return interaction

    async def error(self, text, view=None, message=None):
        """Send errors as a reply"""
        e = Embed()
        e.colour = Colour.red()
        e.description = text
        if view is not None:
            if message is None:
                await self.respond(embed=e, view=view, ephemeral=True)
            else:
                await message.edit(embed=e, view=view)
        else:
            if message is None:
                await self.respond(embed=e, ephemeral=True)
            else:
                await message.edit(embed=e)


class Bot(commands.Bot, ABC):
    """The core functionality of the bot."""

    def __init__(self, **kwargs):
        intents = Intents(bans=True, guilds=True, members=True, messages=True, reactions=True, voice_states=True,
                          emojis=True)
        super().__init__(
            description="Football lookup bot by Painezor#8489",
            command_prefix=".tb ",
            owner_id=210582977493598208,
            activity=Game(name="with /slash_commands"),
            intents=intents
        )
        self.db = kwargs.pop("database")
        self.credentials = credentials
        self.initialised_at = datetime.utcnow()
        self.invite = INVITE_URL

        for c in COGS:
            try:
                self.load_extension('ext.' + c)
            except Exception as e:
                print(f'Failed to load cog {c}\n{type(e).__name__}: {e}')
            else:
                print(f"Loaded extension {c}")

    async def on_ready(self):
        """Print notification to console that the bot has finished loading."""
        print(f'{self.user}: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}\n-----------------------------------')

    async def get_context(self, message, *, cls=Context):
        """Override ctx"""
        return await super().get_context(message, cls=cls)

    async def get_application_context(self, interaction, cls=AppContext):
        """Override ctx for application commands."""
        return await super().get_application_context(interaction, cls=cls)


async def run():
    """Start the bot running, loading all credentials and the database."""
    db = await asyncpg.create_pool(**credentials['Postgres'])
    bot = Bot(database=db)
    try:
        await bot.start(credentials['bot']['token'])
    except KeyboardInterrupt:
        for i in bot.cogs:
            bot.unload_extension(i.name)
        await db.close()
        await bot.close()


loop = asyncio.new_event_loop()
loop.run_until_complete(run())
