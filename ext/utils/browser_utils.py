"""Bot browser Session"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pyppeteer import launch
from pyppeteer.browser import Browser

if TYPE_CHECKING:
	from core import Bot
	from painezBot import PBot


async def make_browser(bot: Bot | PBot) -> Browser:
	"""Spawn an instance of Pyppeteer"""
	opts = {
		"headless": True,
		"devtools": True,
		"args": [
			'--allow-external-pages',
			'--autoplay-policy=user-gesture-required',
			'--disable-accelerated-2d-canvas',
			'--disable-backgrounding-occluded-windows',
			'--disable-background-timer-throttling',
			'--disable-breakpad',
			'--disable-client-side-phishing-detection',
			'--disable-component-extensions-with-background-pages',
			'--disable-component-update',
			'--disable-default-apps',
			'--disable-dev-shm-usage',
			'--disable-extensions',
			'--disable-features=IsolateOrigins',
			'--disable-features=',
			'--disable-ipc-flooding-protection',
			'--disable-infobars',
			'--disable-notifications',
			'--disable-renderer-backgrounding',
			'--disable-setuid-sandbox',
			'--disable-site-isolation-trials'
			'--disable-sync',
			'--disable-translate',
			'--disable-web-security',

			'--enable-features=NetworkService,NetworkServiceInProcess',
			'--force-color-profile=srgb',

			'--hide-scrollbars',

			'--ignore-certificate-errors',
			'--ignore-certificate-errors-skip-list',

			'--metrics-recording-only',
			'--mute-audio',
			'--no-default-browser-check',
			'--no-first-run',
			'--no-zygote',

			'--window-position=0,0'
		]}
	browser = await launch(options=opts)
	browser.bot = bot
	return browser
