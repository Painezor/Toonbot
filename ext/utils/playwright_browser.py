"""Use Playwright to control a header-less Browser"""
from __future__ import annotations
from playwright.async_api import async_playwright, Browser, ViewportSize


async def make_browser() -> Browser:
    """Spawn an instance of Chromium to act as the headerless browser"""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    size = ViewportSize(height=1080, width=1920)
    ctx = await browser.new_context(viewport=size)
    return ctx
