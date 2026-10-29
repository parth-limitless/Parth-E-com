"""
Playwright Automation - Task Pacing & Rate Limiting Engine
==========================================================
Provides realistic task pacing with configurable delays:
- Paced discrete user interactions (clicks, focus, select)
- Natural keyboard typing delays
- Smooth, paced scrolling with viewport settlement checks
- Rate limiting to avoid overwhelming Meesho servers
"""

import asyncio
import logging
import random
import time
from typing import Optional, Tuple

logger = logging.getLogger("playwright_engine.pacing")


class TaskPacer:
    """Manages natural timing and pacing between automation actions."""

    def __init__(
        self,
        min_action_delay: float = 0.3,
        max_action_delay: float = 0.8,
        min_keystroke_delay_ms: int = 40,
        max_keystroke_delay_ms: int = 90,
        max_actions_per_minute: int = 30
    ):
        self.min_action_delay = min_action_delay
        self.max_action_delay = max_action_delay
        self.min_keystroke_delay_ms = min_keystroke_delay_ms
        self.max_keystroke_delay_ms = max_keystroke_delay_ms
        self.max_actions_per_minute = max_actions_per_minute

        self._action_timestamps = []

    async def pace_action(self, custom_delay: Optional[Tuple[float, float]] = None):
        """Pauses for a realistic, randomized delay between actions."""
        # 1. Enforce rate limit (sliding window of 60s)
        now = time.time()
        self._action_timestamps = [t for t in self._action_timestamps if now - t < 60.0]

        if len(self._action_timestamps) >= self.max_actions_per_minute:
            wait_time = 60.0 - (now - self._action_timestamps[0]) + random.uniform(0.5, 1.5)
            logger.info(f"Rate limit threshold reached ({self.max_actions_per_minute}/min). Pacing wait: {wait_time:.1f}s")
            await asyncio.sleep(wait_time)

        # 2. Add randomized humanized delay
        low, high = custom_delay or (self.min_action_delay, self.max_action_delay)
        delay = random.uniform(low, high)
        await asyncio.sleep(delay)
        self._action_timestamps.append(time.time())

    async def type_naturally(self, locator, text: str):
        """Types text with natural, varied keystroke pacing."""
        await locator.focus()
        for char in text:
            delay_ms = random.randint(self.min_keystroke_delay_ms, self.max_keystroke_delay_ms)
            await locator.press_sequentially(char, delay=delay_ms)
        await self.pace_action()

    async def scroll_smoothly(self, page, delta_y: int = 800, steps: int = 4):
        """Performs incremental smooth scrolling to trigger infinite load observers naturally."""
        step_delta = delta_y // steps
        for _ in range(steps):
            await page.mouse.wheel(0, step_delta)
            await asyncio.sleep(random.uniform(0.1, 0.25))
        await self.pace_action()

