"""Use Playwright to control a header-less Browser"""
from __future__ import annotations
from playwright.async_api import async_playwright, BrowserContext, ViewportSize


async def make_browser() -> BrowserContext:
    """Spawn an instance of Chromium to act as the headerless browser"""
    plw = await async_playwright().start()
    chrm = plw.chromium
    path = "BrowserCache"
    size = ViewportSize(height=1080, width=1920)

    plw = await chrm.launch_persistent_context(
        path, viewport=size, strict_selectors=False
    )
    plw.set_default_timeout(5000)

    return plw
