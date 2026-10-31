"""
Playwright Automation - Session & Persistent Context Manager
============================================================
Maintains a consistent browser session across runs:
- Saves & reuses authenticated cookies and storage state (storage_state.json)
- Detects session expiration and logged-out states cleanly
- Honest browser configuration (zero stealth hacks, standard Chromium)
"""

import logging
from pathlib import Path
from typing import Optional, Tuple
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger("playwright_engine.session")


class PlaywrightSession:
    """Manages lifecycle of Playwright Chromium browser and persistent context."""

    def __init__(
        self,
        storage_state_path: str = "./storage/meesho_session.json",
        headless: bool = True,
        viewport_width: int = 1280,
        viewport_height: int = 800,
        filter_media: bool = True
    ):
        self.storage_state_path = Path(storage_state_path)
        self.headless = headless
        self.viewport = {"width": viewport_width, "height": viewport_height}
        self.filter_media = filter_media

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Initializes Playwright Chromium with honest settings and persistent session."""
        self._playwright = await async_playwright().start()

        # Launch real honest Chromium (no fingerprint spoofing, no illegal stealth flags)
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless
        )

        context_kwargs = {
            "viewport": self.viewport,
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "extra_http_headers": {
                "Accept-Language": "en-IN,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "sec-ch-ua-platform": '"Windows"'
            }
        }

        # Load existing storage state if available
        if self.storage_state_path.exists():
            try:
                context_kwargs["storage_state"] = str(self.storage_state_path)
                logger.info(f"Restoring existing browser session state from: {self.storage_state_path}")
            except Exception as e:
                logger.warning(f"Could not load session state: {e}. Starting fresh context.")

        self._context = await self._browser.new_context(**context_kwargs)

        # Optional route filtering for speed & bandwidth efficiency
        if self.filter_media:
            await self._context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ["image", "media", "font"]
                else route.continue_()
            )

    async def new_page(self) -> Page:
        """Creates a new page in the managed context."""
        if not self._context:
            await self.start()
        return await self._context.new_page()

    async def save_session(self):
        """Persists session state (cookies & localStorage) to disk."""
        if self._context:
            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self.storage_state_path))
            logger.info(f"Saved active browser session state to: {self.storage_state_path}")

    async def check_session_expired(self, page: Page) -> Tuple[bool, Optional[str]]:
        """
        Inspects whether the current session has expired.
        Checks for redirect to login, auth failure modals, or session timeout messages.
        """
        current_url = page.url.lower()
        if "login" in current_url or "auth" in current_url or "signin" in current_url:
            return True, "Redirected to login/auth endpoint"

        # Check for visible session expired banner
        try:
            banner = page.locator("text='Session Expired', text='Please log in again'").first
            if await banner.is_visible(timeout=500):
                return True, "Session expired prompt displayed"
        except Exception:
            pass

        return False, None

    async def close(self):
        """Closes browser context and Playwright cleanly."""
        try:
            if self._context:
                await self.save_session()
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug(f"Session cleanup note: {e}")

