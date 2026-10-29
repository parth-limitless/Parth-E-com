"""
Meesho Tracker - Block & Challenge Circuit Breaker
=================================================
Detects HTTP 403/429, Akamai bot challenges (sec-if-cpt-container, Access Denied),
and captcha forms. Implements non-negotiable safety rules:
- Max 1 retry after 60-120 s wait.
- Still blocked -> abort run, save partial data, set escalating cooldown (24h -> 48h -> 72h).
- Zero infinite loops, no stealth/fingerprint bypass.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from meesho_tracker.config import TrackerConfig, load_selectors
from meesho_tracker.storage import TrackerStorage

logger = logging.getLogger("meesho_tracker.block_detector")


class BlockDetector:
    """Detects security challenges, bot mitigations, and blocks."""

    def __init__(self, selectors: Optional[Dict[str, Any]] = None):
        self.selectors = selectors or load_selectors()
        self.block_sel = self.selectors.get("block_signatures", {})

    def check_response(
        self,
        status_code: int,
        html_content: str = "",
        headers: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates whether a page load represents a block or challenge.
        Returns: (is_blocked: bool, block_reason: Optional[str])
        """
        # 1. HTTP Status code checks
        if status_code in [403, 429]:
            return True, f"HTTP status {status_code} (Forbidden/Rate Limited)"

        if not html_content:
            return False, None

        # 2. Akamai Sec-if-cpt-container check
        akamai_container = self.block_sel.get("akamai_container", "sec-if-cpt-container")
        if akamai_container in html_content:
            return True, "Akamai bot challenge detected ('sec-if-cpt-container')"

        # 3. Known block titles and edge errors
        access_denied_titles = self.block_sel.get("access_denied_titles", [
            "Access Denied", "Security Challenge", "Robot Check"
        ])
        for title in access_denied_titles:
            if f"<title>{title}</title>".lower() in html_content.lower() or f"<h1>{title}</h1>".lower() in html_content.lower():
                return True, f"Akamai edge block detected ('{title}')"

        if "errors.edgesuite.net" in html_content:
            return True, "Akamai EdgeSuite error detected ('errors.edgesuite.net')"

        # 4. Captcha form / iframe detection
        captcha_sel = self.block_sel.get("captcha_form", "form#challenge-form")
        for sel_token in captcha_sel.split(","):
            token = sel_token.strip().replace("form#", "").replace("div#", "")
            if token and f'id="{token}"' in html_content:
                return True, f"Captcha element detected ('{token}')"

        # 5. Empty body or shell challenge (HTTP 200 with ~2.7 KB body and no ld+json/NEXT_DATA)
        if len(html_content) < 4000:
            has_next = '__NEXT_DATA__' in html_content
            has_ld = 'application/ld+json' in html_content
            if not has_next and not has_ld and ("denied" in html_content.lower() or "challenge" in html_content.lower() or "blocked" in html_content.lower()):
                return True, f"Suspicious short response ({len(html_content)} bytes) without Next.js/JSON-LD data"

        return False, None


class CircuitBreaker:
    """Manages cooldown escalation and abort decisions on block."""

    def __init__(self, storage: TrackerStorage, config: TrackerConfig):
        self.storage = storage
        self.config = config

    def handle_block(self, run_id: str, reason: str) -> datetime:
        """
        Escalates consecutive blocks and sets cooldown_until in SQLite tracker state.
        1st block: +24h
        2nd block: +48h
        3rd+ block: +72h
        Returns: cooldown_until datetime
        """
        state = self.storage.get_state()
        consecutive = state.consecutive_blocks + 1

        if consecutive == 1:
            cooldown_hours = self.config.circuit_breaker.cooldown_base_hours  # 24h
        elif consecutive == 2:
            cooldown_hours = self.config.circuit_breaker.cooldown_2nd_hours   # 48h
        else:
            cooldown_hours = self.config.circuit_breaker.cooldown_3rd_hours   # 72h

        cooldown_until = datetime.now() + timedelta(hours=cooldown_hours)

        self.storage.update_state(
            cooldown_until=cooldown_until,
            consecutive_blocks=consecutive,
            last_run_time=datetime.now()
        )

        logger.critical(
            f"CIRCUIT BREAKER TRIGGERED [Run {run_id}]: {reason}. "
            f"Consecutive blocks: {consecutive}. "
            f"Cooldown escalated to {cooldown_hours} hours (active until {cooldown_until.strftime('%Y-%m-%d %H:%M:%S')})."
        )
        return cooldown_until

    def reset_blocks(self):
        """Resets consecutive blocks counter on successful run."""
        self.storage.update_state(
            consecutive_blocks=0,
            reset_blocks=True
        )
