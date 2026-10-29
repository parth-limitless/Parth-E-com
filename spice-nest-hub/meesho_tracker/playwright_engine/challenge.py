"""
Playwright Automation - Challenge Detection & Manual Intervention Handler
========================================================================
Detects CAPTCHA, MFA, Cloudflare/Akamai bot challenges, and OTP screens.
Policy Compliant:
- NEVER attempts automated solving or fingerprint spoofing
- Pauses execution and prompts for manual human intervention
- Resumes naturally once the human resolves the challenge, or safely times out
"""

import asyncio
import logging
from typing import Optional, Tuple
from playwright.async_api import Page

logger = logging.getLogger("playwright_engine.challenge")


class ChallengeDetector:
    """Monitors page states for anti-bot challenges, CAPTCHAs, or MFA screens."""

    CHALLENGE_SELECTORS = [
        "div.sec-if-cpt-container",
        "iframe[src*='captcha']",
        "iframe[src*='challenge']",
        "iframe[src*='turnstile']",
        "div#captcha-container",
        "div#challenge-form",
        "[data-sitekey]",
        "form[action*='verify']"
    ]

    CHALLENGE_TITLE_SIGNATURES = [
        "access denied",
        "security challenge",
        "robot check",
        "just a moment",
        "please verify you are human",
        "attention required"
    ]

    MFA_OTP_SELECTORS = [
        "input[name*='otp' i]",
        "input[placeholder*='otp' i]",
        "input[autocomplete*='one-time-code' i]",
        "div:has-text('Enter OTP')"
    ]

    @classmethod
    async def inspect_page(cls, page: Page) -> Tuple[bool, Optional[str]]:
        """
        Non-intrusive check to see if the current page is blocked by a challenge or MFA.
        Returns: (is_challenged: bool, challenge_type: Optional[str])
        """
        # 1. Check page title
        try:
            title = (await page.title()).lower()
            for sig in cls.CHALLENGE_TITLE_SIGNATURES:
                if sig in title:
                    return True, f"Security challenge detected in page title ('{sig}')"
        except Exception:
            pass

        # 2. Check for challenge DOM elements
        for sel in cls.CHALLENGE_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=300):
                    return True, f"Anti-bot verification element detected ('{sel}')"
            except Exception:
                continue

        # 3. Check for MFA / OTP screen
        for otp_sel in cls.MFA_OTP_SELECTORS:
            try:
                el = page.locator(otp_sel).first
                if await el.is_visible(timeout=300):
                    return True, f"MFA / OTP verification screen detected ('{otp_sel}')"
            except Exception:
                continue

        # 4. Check for Access Denied / EdgeSuite body text
        try:
            body_text = await page.locator("body").inner_text(timeout=500)
            if "access denied" in body_text.lower() and "permission to access" in body_text.lower():
                return True, "Akamai Access Denied server block detected"
        except Exception:
            pass

        return False, None


class ManualInterventionHandler:
    """Pauses automation when a challenge appears and waits for human resolution."""

    def __init__(self, timeout_sec: float = 120.0, check_interval_sec: float = 2.0):
        self.timeout_sec = timeout_sec
        self.check_interval_sec = check_interval_sec

    async def wait_for_resolution(self, page: Page, challenge_description: str) -> bool:
        """
        Pauses and prompts for human intervention.
        Monitors the page until the challenge disappears or timeout expires.
        Returns True if resolved by human, False if timed out.
        """
        logger.warning(
            f"\n"
            f"========================================================================\n"
            f"🚨 [MANUAL INTERVENTION REQUIRED]\n"
            f"   Detected: {challenge_description}\n"
            f"   The automation is paused for up to {self.timeout_sec:.0f} seconds.\n"
            f"   👉 Please solve the verification / enter the code in the browser window.\n"
            f"========================================================================\n"
        )
        print(
            f"\n🔔 [MANUAL INTERVENTION REQUIRED] {challenge_description}. "
            f"Please solve the verification in your browser window within {self.timeout_sec:.0f}s...",
            flush=True
        )

        elapsed = 0.0
        while elapsed < self.timeout_sec:
            await asyncio.sleep(self.check_interval_sec)
            elapsed += self.check_interval_sec

            # Check if challenge has been resolved
            challenged, _ = await ChallengeDetector.inspect_page(page)
            if not challenged:
                logger.info(
                    f"✅ Manual intervention completed successfully after {elapsed:.1f}s! "
                    f"Resuming automation naturally."
                )
                print(f"✅ Challenge resolved! Resuming automation...", flush=True)
                return True

        logger.error(
            f"❌ Manual intervention timed out after {self.timeout_sec:.0f}s. "
            f"Aborting workflow safely to prevent account lockouts or corrupted state."
        )
        return False

