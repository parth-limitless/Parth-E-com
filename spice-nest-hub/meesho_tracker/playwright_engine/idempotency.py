"""
Playwright Automation - Idempotency & Page State Validation
===========================================================
Guarantees reliable, safe browser workflows:
- Prevents duplicate clicks, repeated submissions, and double order execution
- Validates expected page states, URL invariants, and error banners
- Stops execution safely rather than submitting incorrect data
"""

import hashlib
import logging
import re
import time
from typing import Dict, List, Optional, Set
from playwright.async_api import Locator, Page

logger = logging.getLogger("playwright_engine.idempotency")


class StateValidationError(Exception):
    """Raised when the browser reaches an unexpected or erroneous page state."""
    pass


class IdempotencyGuard:
    """Prevents duplicate clicks, double form submissions, and redundant actions."""

    def __init__(self, debounce_window_sec: float = 1.0):
        self.debounce_window_sec = debounce_window_sec
        self._completed_action_keys: Set[str] = set()
        self._last_click_times: Dict[str, float] = {}

    def get_action_key(self, action_type: str, entity_id: str, payload_summary: str = "") -> str:
        raw = f"{action_type}:{entity_id}:{payload_summary}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def has_executed(self, action_key: str) -> bool:
        return action_key in self._completed_action_keys

    def mark_executed(self, action_key: str):
        self._completed_action_keys.add(action_key)
        logger.debug(f"Marked action [{action_key}] as executed in idempotency ledger.")

    async def safe_click(self, locator: Locator, action_id: str, max_timeout_ms: int = 5000):
        """
        Clicks an element with debouncing and double-click prevention.
        Verifies element is visible and enabled before interacting.
        """
        now = time.time()
        last_time = self._last_click_times.get(action_id, 0.0)
        if now - last_time < self.debounce_window_sec:
            logger.warning(f"Debounce triggered: prevented duplicate click on [{action_id}].")
            return False

        # Verify button is ready
        await locator.wait_for(state="visible", timeout=max_timeout_ms)
        if not await locator.is_enabled():
            logger.warning(f"Click aborted: [{action_id}] button is disabled.")
            return False

        await locator.click()
        self._last_click_times[action_id] = time.time()
        logger.debug(f"Successfully performed debounced click on [{action_id}].")
        return True


class PageStateValidator:
    """Validates navigation states, error banners, and post-action invariants."""

    KNOWN_ERROR_PATTERNS = [
        re.compile(r"something went wrong", re.I),
        re.compile(r"temporarily unavailable", re.I),
        re.compile(r"item is out of stock", re.I),
        re.compile(r"price has changed", re.I),
        re.compile(r"unable to process", re.I),
        re.compile(r"invalid request", re.I),
        re.compile(r"session expired", re.I)
    ]

    @classmethod
    async def assert_url(cls, page: Page, expected_pattern: str, timeout_ms: int = 10000):
        """Ensures the current URL matches expected pattern, or fails safely."""
        try:
            await page.wait_for_url(re.compile(expected_pattern), timeout=timeout_ms)
        except Exception:
            current_url = page.url
            raise StateValidationError(
                f"Unexpected navigation state: expected pattern '{expected_pattern}' but current URL is '{current_url}'"
            )

    @classmethod
    async def check_for_error_banners(cls, page: Page) -> Optional[str]:
        """Scans the page for visible error toasts, banners, or notification cards."""
        # Check standard banner/toast elements
        banners = page.locator("div[role='alert'], div[class*='Toast' i], div[class*='Error' i], div[class*='Banner' i]")
        count = await banners.count()
        for idx in range(min(count, 5)):
            b = banners.nth(idx)
            try:
                if await b.is_visible():
                    txt = (await b.inner_text()).strip()
                    for pattern in cls.KNOWN_ERROR_PATTERNS:
                        if pattern.search(txt):
                            return f"Platform error detected: '{txt}'"
            except Exception:
                continue
        return None

    @classmethod
    async def assert_healthy_state(cls, page: Page):
        """Validates that no error banners or crash states are displayed."""
        err = await cls.check_for_error_banners(page)
        if err:
            raise StateValidationError(f"Safe stop triggered: {err}")

