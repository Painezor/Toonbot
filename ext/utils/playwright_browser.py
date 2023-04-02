"""Use Playwright to control a header-less Browser"""
from __future__ import annotations

from playwright.async_api import async_playwright, BrowserContext, ViewportSize


async def make_browser() -> BrowserContext:
    """Spawn an instance of Chromium to act as the headerless browser"""
    browser = await async_playwright().start()
    browser = await browser.chromium.launch(headless=True)
    size = ViewportSize(height=1080, width=1920)
    browser_context = await browser.new_context(viewport=size)
    browser_context.set_default_timeout(5000)
    return browser_context
