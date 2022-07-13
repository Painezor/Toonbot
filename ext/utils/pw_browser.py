"""Use Playwright to control a header-less Browser"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import async_playwright, Browser, ViewportSize

if TYPE_CHECKING:
	from core import Bot
	from painezBot import PBot


async def make_browser(bot: Bot | PBot) -> Browser:
	"""Spawn an instance of Chromium to act as the header-less browser of the bot"""
	pw = await async_playwright().start()
	browser = await pw.chromium.launch()
	ctx = await browser.new_context(viewport=ViewportSize(height=1080, width=1920))
	ctx.bot = bot
	return ctx
