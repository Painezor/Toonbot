from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import FLASHSCORE

if TYPE_CHECKING:
    from playwright.async_api import Page


class HasLogo:
    logo_url: str | None

    async def get_logo(self, page: Page) -> None:
        """Re-Cache the logo of this item."""
        if self.logo_url is None:
            logo = page.locator("img.heading__logo")
            logo_url = await logo.get_attribute("src")
            if logo_url is not None:
                logo_url = logo_url.rsplit("/", maxsplit=1)[-1]
                logo_url = FLASHSCORE + "/res/image/data/" + logo_url
                self.logo_url = logo_url
