"""Localisations for Bot Commands"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from discord import Locale
from discord.app_commands import Translator, locale_str, TranslationContext
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from core import Bot
    from painezBot import PBot

translations: dict[Locale, dict] = {}

for x in Locale:
    try:
        with open(f"./ext/utils/translations/{x.name}.json") as f:
            translations[x] = json.load(f)
    except Exception as e:
        logging.error(f"{e} Unable to load translation {x}, {x.name}.json")


class TL(Translator):
    """The Translation module"""

    async def load(self):
        """On load."""
        # this gets called when the translator first gets loaded!

    async def unload(self):
        """On Unload."""
        # in case you need to switch translators, this gets called
        # when being removed

    async def translate(
        self, string: locale_str, locale: Locale, context: TranslationContext
    ) -> str | None:
        """
        `locale_str` is the string that is requesting to be translated
        `locale` is the target language to translate to
        `context` is the origin of this string,
        eg TranslationContext.command_name, etc
        This function must return a string (that's been translated), or `None`
        to signal no available translation available, and will default to the
        original.
        """

        try:
            return translations[locale][string.message]
        except KeyError:
            return None


class Translations(Cog):
    """The translation cog."""

    def __init__(self, bot: Bot | PBot) -> None:
        """Load Translations"""
        self.bot: Bot | PBot = bot

    async def cog_load(self) -> None:
        """Load custom translations"""
        await self.bot.tree.set_translator(TL())

    async def cog_unload(self) -> None:
        """Unload Translations"""
        await self.bot.tree.set_translator(None)


async def setup(bot: Bot | PBot):
    """Load the translation Cog into the bot"""
    await bot.add_cog(Translations(bot))
