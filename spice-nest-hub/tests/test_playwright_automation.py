"""
Automated Test Suite for Meesho Playwright Automation Engine
============================================================
Verifies:
1. TaskPacer: humanized pacing and sliding-window rate limiting
2. IdempotencyGuard & PageStateValidator: debouncing, duplicate protection, state validation
3. ChallengeDetector: CAPTCHA / Akamai challenge detection
4. ResilientActions: exponential backoff retries and error tolerance
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from meesho_tracker.playwright_engine.challenge import ChallengeDetector, ManualInterventionHandler
from meesho_tracker.playwright_engine.idempotency import IdempotencyGuard, PageStateValidator, StateValidationError
from meesho_tracker.playwright_engine.pacing import TaskPacer
from meesho_tracker.playwright_engine.actions import ResilientActions


class TestTaskPacer:
    def test_pacer_delay_bounds(self):
        async def _run():
            pacer = TaskPacer(min_action_delay=0.1, max_action_delay=0.2)
            start = time.time()
            await pacer.pace_action()
            elapsed = time.time() - start
            assert elapsed >= 0.09, f"Pacer delay too short: {elapsed}"
        asyncio.run(_run())

    def test_pacer_rate_limit_sliding_window(self):
        async def _run():
            # Allow max 3 actions per 60 seconds
            pacer = TaskPacer(min_action_delay=0.01, max_action_delay=0.02, max_actions_per_minute=3)
            now = time.time()
            # 2 old timestamps from >60s ago
            pacer._action_timestamps = [now - 70, now - 65]
            await pacer.pace_action()
            # Old timestamps should be evicted and new one added
            assert len(pacer._action_timestamps) == 1
        asyncio.run(_run())

    def test_pacer_type_naturally(self):
        async def _run():
            pacer = TaskPacer(min_keystroke_delay_ms=5, max_keystroke_delay_ms=10)
            mock_locator = AsyncMock()
            mock_locator.focus = AsyncMock()
            mock_locator.press_sequentially = AsyncMock()

            await pacer.type_naturally(mock_locator, "Spice")
            assert mock_locator.focus.called
            assert mock_locator.press_sequentially.call_count == 5
        asyncio.run(_run())


class TestIdempotencyAndStateValidator:
    def test_idempotency_debounce(self):
        async def _run():
            guard = IdempotencyGuard(debounce_window_sec=0.5)
            mock_loc = AsyncMock()
            mock_loc.wait_for = AsyncMock()
            mock_loc.is_enabled = AsyncMock(return_value=True)
            mock_loc.click = AsyncMock()

            # First click should succeed
            res1 = await guard.safe_click(mock_loc, "submit_btn")
            assert res1 is True
            assert mock_loc.click.call_count == 1

            # Immediate second click should be debounced
            res2 = await guard.safe_click(mock_loc, "submit_btn")
            assert res2 is False
            assert mock_loc.click.call_count == 1

            # Different action id should succeed
            res3 = await guard.safe_click(mock_loc, "cancel_btn")
            assert res3 is True
            assert mock_loc.click.call_count == 2
        asyncio.run(_run())

    def test_duplicate_ledger(self):
        guard = IdempotencyGuard()
        key1 = guard.get_action_key("order", "123", "summary1")
        key2 = guard.get_action_key("order", "456", "summary2")

        assert guard.has_executed(key1) is False
        guard.mark_executed(key1)
        assert guard.has_executed(key1) is True
        assert guard.has_executed(key2) is False

    def test_page_state_validator_url(self):
        async def _run():
            mock_page = MagicMock()
            # If wait_for_url completes without error, validation succeeds
            mock_page.wait_for_url = AsyncMock()
            await PageStateValidator.assert_url(mock_page, r"meesho\.com/SpiceNest")

            # When wait_for_url times out / fails, raises StateValidationError
            mock_page.wait_for_url = AsyncMock(side_effect=Exception("Timeout"))
            mock_page.url = "https://www.meesho.com/auth/login"
            with pytest.raises(StateValidationError, match="Unexpected navigation state"):
                await PageStateValidator.assert_url(mock_page, r"meesho\.com/SpiceNest")
        asyncio.run(_run())

    def test_page_state_validator_error_banner(self):
        async def _run():
            mock_page = MagicMock()
            mock_banner = AsyncMock()
            mock_banner.count = AsyncMock(return_value=1)
            
            mock_first = AsyncMock()
            mock_first.is_visible = AsyncMock(return_value=True)
            mock_first.inner_text = AsyncMock(return_value="Something went wrong. Please try again.")
            mock_banner.nth = MagicMock(return_value=mock_first)
            mock_page.locator = MagicMock(return_value=mock_banner)

            with pytest.raises(StateValidationError, match="Platform error detected"):
                await PageStateValidator.assert_healthy_state(mock_page)
        asyncio.run(_run())


class TestChallengeDetector:
    def test_challenge_detection_turnstile(self):
        async def _run():
            mock_page = MagicMock()
            mock_page.title = AsyncMock(return_value="Meesho Store")

            def locator_mock(selector):
                mock_loc = MagicMock()
                mock_el = AsyncMock()
                if "turnstile" in selector:
                    mock_el.is_visible = AsyncMock(return_value=True)
                else:
                    mock_el.is_visible = AsyncMock(return_value=False)
                mock_loc.first = mock_el
                return mock_loc

            mock_page.locator = MagicMock(side_effect=locator_mock)

            is_challenged, reason = await ChallengeDetector.inspect_page(mock_page)
            assert is_challenged is True
            assert "turnstile" in reason
        asyncio.run(_run())

    def test_challenge_detection_clean_page(self):
        async def _run():
            mock_page = MagicMock()
            mock_page.title = AsyncMock(return_value="Spice Nest Store")

            def locator_mock(selector):
                mock_loc = MagicMock()
                mock_el = AsyncMock()
                mock_el.is_visible = AsyncMock(return_value=False)
                mock_loc.first = mock_el
                return mock_loc

            mock_body = MagicMock()
            mock_body.inner_text = AsyncMock(return_value="Welcome to Spice Nest")
            def locator_side_effect(selector):
                if selector == "body":
                    return mock_body
                return locator_mock(selector)

            mock_page.locator = MagicMock(side_effect=locator_side_effect)

            is_challenged, reason = await ChallengeDetector.inspect_page(mock_page)
            assert is_challenged is False
            assert reason is None
        asyncio.run(_run())

    def test_manual_intervention_timeout(self):
        async def _run():
            handler = ManualInterventionHandler(timeout_sec=0.06, check_interval_sec=0.02)
            mock_page = MagicMock()
            orig_inspect = ChallengeDetector.inspect_page
            try:
                ChallengeDetector.inspect_page = AsyncMock(return_value=(True, "Akamai Bot Challenge"))
                resolved = await handler.wait_for_resolution(mock_page, "Akamai Bot Challenge")
                assert resolved is False
            finally:
                ChallengeDetector.inspect_page = orig_inspect
        asyncio.run(_run())


class TestResilientActions:
    def test_retry_with_backoff_success_after_failure(self):
        async def _run():
            actions = ResilientActions()
            attempts = 0

            async def faulty_action():
                nonlocal attempts
                attempts += 1
                if attempts < 2:
                    raise TimeoutError("Temporary network blip")
                return "SUCCESS"

            result = await actions.retry_with_backoff(
                faulty_action,
                max_retries=3,
                base_delay_sec=0.02,
                factor=1.5,
                description="Test Faulty Action"
            )
            assert result == "SUCCESS"
            assert attempts == 2
        asyncio.run(_run())

    def test_retry_with_backoff_exhausted(self):
        async def _run():
            actions = ResilientActions()
            attempts = 0

            async def always_failing():
                nonlocal attempts
                attempts += 1
                raise ValueError("Persistent element not found")

            with pytest.raises(ValueError, match="Persistent element not found"):
                await actions.retry_with_backoff(
                    always_failing,
                    max_retries=3,
                    base_delay_sec=0.02,
                    factor=1.5,
                    description="Test Persistent Failure"
                )
            assert attempts == 3
        asyncio.run(_run())
