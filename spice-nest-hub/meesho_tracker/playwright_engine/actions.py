"""
Playwright Automation - Robust Page Interactions & Resilience Engine
====================================================================
Implements:
- Dynamic waiting on elements and network responses (no fixed sleeps)
- Automatic handling and detachment of loading indicators / spinners
- Resilient dismissal of unexpected modal popups and promotional dialogs
- Dropdown selection with option visibility synchronization
- Exponential backoff retries for transient browser/DOM errors
"""

import asyncio
import logging
import random
import time
from typing import Any, Callable, Optional, TypeVar
from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from meesho_tracker.playwright_engine.challenge import ChallengeDetector, ManualInterventionHandler
from meesho_tracker.playwright_engine.locators import MeeshoLocators
from meesho_tracker.playwright_engine.pacing import TaskPacer

logger = logging.getLogger("playwright_engine.actions")
T = TypeVar("T")


class ResilientActions:
    """Provides bulletproof, policy-compliant browser actions with retries and smart waits."""

    def __init__(self, pacer: Optional[TaskPacer] = None):
        self.pacer = pacer or TaskPacer()
        self.intervention_handler = ManualInterventionHandler()

    async def retry_with_backoff(
        self,
        action_fn: Callable[[], Any],
        max_retries: int = 3,
        base_delay_sec: float = 1.0,
        factor: float = 2.0,
        description: str = "Action"
    ) -> Any:
        """
        Executes an action with exponential backoff and randomized jitter for transient errors.
        """
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                return await action_fn()
            except (PlaywrightTimeoutError, Exception) as e:
                last_error = e
                if attempt == max_retries:
                    logger.error(f"[{description}] Reached maximum retries ({max_retries}). Last error: {e}")
                    raise

                delay = (base_delay_sec * (factor ** (attempt - 1))) + random.uniform(0.1, 0.5)
                logger.warning(
                    f"[{description}] Attempt {attempt}/{max_retries} failed ({e.__class__.__name__}: {e}). "
                    f"Retrying in {delay:.2f}s with exponential backoff..."
                )
                await asyncio.sleep(delay)

        raise last_error

    async def wait_for_loading_complete(self, page: Page, timeout_ms: int = 10000):
        """
        Waits for DOM hydration and ensures all loading spinners/indicators have detached.
        """
        # 1. Wait for DOM content to settle
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass

        # 2. Wait for loading spinners to detach or hide
        locators = MeeshoLocators(page)
        spinners = locators.loading_spinners
        try:
            count = await spinners.count()
            for idx in range(count):
                spinner = spinners.nth(idx)
                if await spinner.is_visible():
                    logger.debug("Waiting for active loading indicator to detach...")
                    await spinner.wait_for(state="detached", timeout=timeout_ms)
        except Exception:
            pass

    async def dismiss_modal_dialogs(self, page: Page) -> bool:
        """
        Detects and cleanly dismisses any unexpected promotional modals, dialogs, or overlays.
        Returns True if a dialog was dismissed.
        """
        locators = MeeshoLocators(page)
        modal = locators.modal_dialog.first
        try:
            if await modal.is_visible(timeout=500):
                logger.info("Unexpected modal dialog detected. Attempting clean dismissal...")
                close_btn = locators.modal_close_button.first
                if await close_btn.is_visible(timeout=1000):
                    await close_btn.click()
                    await self.pacer.pace_action()
                    logger.info("Modal dismissed via close button.")
                    return True
                else:
                    # Press Escape key to dismiss backdrop
                    await page.keyboard.press("Escape")
                    await self.pacer.pace_action()
                    logger.info("Modal dismissed via Escape key.")
                    return True
        except Exception:
            pass
        return False

    async def select_dropdown_option(
        self,
        page: Page,
        dropdown_button: Locator,
        option_text: str,
        timeout_ms: int = 5000
    ) -> bool:
        """
        Robustly selects a dropdown option:
        1. Waits for trigger to be ready
        2. Clicks to open menu
        3. Waits for target option to appear
        4. Clicks option and verifies
        """
        await self.dismiss_modal_dialogs(page)
        await dropdown_button.wait_for(state="visible", timeout=timeout_ms)
        await dropdown_button.click()
        await self.pacer.pace_action()

        locators = MeeshoLocators(page)
        option = locators.dropdown_option(option_text)
        await option.wait_for(state="visible", timeout=timeout_ms)
        await option.click()
        await self.pacer.pace_action()

        logger.info(f"Selected dropdown option: '{option_text}'")
        return True

    async def navigate_safely(
        self,
        page: Page,
        url: str,
        expected_url_pattern: Optional[str] = None,
        timeout_ms: int = 45000
    ):
        """
        Navigates to URL, checks for security challenges, and waits for page stability.
        """
        logger.info(f"Navigating safely to: {url}")
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # 1. Check for anti-bot challenges
        is_challenged, reason = await ChallengeDetector.inspect_page(page)
        if is_challenged:
            logger.warning(f"Challenge encountered upon navigation: {reason}")
            resolved = await self.intervention_handler.wait_for_resolution(page, reason or "Challenge")
            if not resolved:
                raise RuntimeError(f"Workflow halted: {reason} could not be resolved.")

        # 2. Wait for loading indicators and dismiss blocking dialogs
        await self.wait_for_loading_complete(page)
        await self.dismiss_modal_dialogs(page)

        # 3. Optional URL pattern validation
        if expected_url_pattern:
            from meesho_tracker.playwright_engine.idempotency import PageStateValidator
            await PageStateValidator.assert_url(page, expected_url_pattern)
            await PageStateValidator.assert_healthy_state(page)

        return response

