"""
Playwright Automation Engine for Meesho
=======================================
Modular, policy-compliant automation framework providing:
- Accessibility-based resilient locators
- Smart dynamic waiting on elements & network responses
- Spinner/loader detachment and modal dialog dismissals
- Task pacing & rate limiting
- Persistent session context & expiration detection
- Anti-bot challenge detection with manual intervention pause
- Idempotency guards (duplicate click/submission prevention)
- Retries with exponential backoff
"""

from meesho_tracker.playwright_engine.locators import MeeshoLocators
from meesho_tracker.playwright_engine.pacing import TaskPacer
from meesho_tracker.playwright_engine.session import PlaywrightSession
from meesho_tracker.playwright_engine.challenge import ChallengeDetector, ManualInterventionHandler
from meesho_tracker.playwright_engine.idempotency import IdempotencyGuard, PageStateValidator, StateValidationError
from meesho_tracker.playwright_engine.actions import ResilientActions

__all__ = [
    "MeeshoLocators",
    "TaskPacer",
    "PlaywrightSession",
    "ChallengeDetector",
    "ManualInterventionHandler",
    "IdempotencyGuard",
    "PageStateValidator",
    "StateValidationError",
    "ResilientActions"
]

