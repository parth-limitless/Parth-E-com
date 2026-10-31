"""
Execution Guards & Rate Limiting (24-Hour Rule, Single-Instance Lock, Cooldowns)
================================================================================
Enforces strict safety rules, single execution concurrency, and block cooldowns.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
from filelock import FileLock, Timeout

from meesho_tracker.config import TrackerConfig
from meesho_tracker.models import TrackerState
from meesho_tracker.storage import TrackerStorage


class GuardError(Exception):
    """Raised when an execution guard blocks the run."""
    pass


class SingleInstanceLock:
    """Ensures never more than one tracker process runs at the same time."""
    def __init__(self, lock_file: str = "meesho_tracker.lock", timeout_sec: float = 1.0):
        self.lock_path = Path(lock_file)
        self.lock = FileLock(str(self.lock_path), timeout=timeout_sec)

    def __enter__(self):
        try:
            self.lock.acquire()
            return self
        except Timeout:
            raise GuardError(
                f"Another instance of Meesho Store Tracker is already running (locked via {self.lock_path}). Aborting."
            )

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.lock.release()
        except Exception:
            pass
        if self.lock_path.exists():
            try: self.lock_path.unlink()
            except Exception: pass


TrackerLock = SingleInstanceLock


class TrackerGuards:
    def __init__(self, storage: TrackerStorage, config: TrackerConfig):
        self.storage = storage
        self.config = config

    def can_run(self, mode: str, force: bool = False) -> Tuple[bool, str]:
        return check_execution_guard(self.storage, self.config, mode, force)

    def check_schema_drift(self, valid_products: list) -> Tuple[bool, Optional[str]]:
        state = self.storage.get_state()
        prev_products = self.storage.get_latest_products()
        prev_count = len(prev_products)
        curr_count = len(valid_products)

        if not valid_products:
            return False, None

        # Calculate empty key fields ratio (price, name, url)
        empty_count = sum(1 for p in valid_products if not p.price or not p.name or not p.url)
        empty_ratio = empty_count / max(curr_count, 1)

        is_drift, reason = check_schema_drift(curr_count, prev_count, empty_ratio, self.config)
        return is_drift, reason if is_drift else None


def check_execution_guard(
    storage: TrackerStorage,
    config: TrackerConfig,
    mode: str,
    force: bool = False
) -> Tuple[bool, str]:
    """
    Evaluates whether the requested execution mode is permitted to run right now.
    
    :return: (allowed: bool, reason_or_message: str)
    """
    state = storage.get_state()
    now = datetime.now()

    # Rule 1: Check Active Circuit Breaker Cooldown (ABSOLUTE: --force CANNOT OVERRIDE)
    if state.cooldown_until and state.cooldown_until > now:
        remaining = state.cooldown_until - now
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        msg = f"Active Circuit Breaker Cooldown in effect until {state.cooldown_until.strftime('%Y-%m-%d %H:%M:%S')} ({hours}h {minutes}m remaining due to {state.consecutive_blocks} consecutive block(s)). Run refused."
        return False, msg

    # Rule 2: Scheduled / Full Run 24-Hour Rule
    if mode in ("scheduled", "full"):
        if state.last_success_time:
            hours_since_last = (now - state.last_success_time).total_seconds() / 3600.0
            min_hours = config.guards.min_hours_between_full_scans
            
            if hours_since_last < min_hours:
                next_allowed = state.last_success_time + timedelta(hours=min_hours)
                
                if force:
                    if state.force_used_at:
                        hours_since_force = (now - state.force_used_at).total_seconds() / 3600.0
                        if hours_since_force < min_hours:
                            return False, f"--force override already used within the last 24 hours ({hours_since_force:.1f}h ago). Next allowed run: {next_allowed.strftime('%Y-%m-%d %H:%M:%S')}"
                    storage.update_state(force_used_at=now, reset_blocks=True, cooldown_until="CLEAR")
                    print(f"⚠️ [WARNING] --force override applied! Run executing on demand. Next allowed standard: {next_allowed.strftime('%Y-%m-%d %H:%M:%S')}")
                    return True, "Force allowed"
                
                return False, f"24-Hour Rule: Only {hours_since_last:.1f}h elapsed since last success ({state.last_success_time.strftime('%Y-%m-%d %H:%M:%S')}). Next allowed run: {next_allowed.strftime('%Y-%m-%d %H:%M:%S')}"

    # Rule 3: Live Mode 30-Minute Guard
    elif mode == "live":
        if state.last_live_time:
            mins_since = (now - state.last_live_time).total_seconds() / 60.0
            min_mins = config.guards.min_minutes_between_live_scans
            if mins_since < min_mins and not force:
                next_allowed = state.last_live_time + timedelta(minutes=min_mins)
                return False, f"Live Mode Guard: Only {mins_since:.1f}m elapsed since last live scan. Minimum {min_mins}m required. Next allowed run: {next_allowed.strftime('%Y-%m-%d %H:%M:%S')}"

    return True, "Execution permitted"


def check_schema_drift(
    current_count: int,
    previous_count: int,
    empty_fields_ratio: float,
    config: TrackerConfig
) -> Tuple[bool, str]:
    """
    Checks for structural schema drift:
    - Products count drop > 30%
    - Key fields empty in > 20% rows
    """
    if previous_count > 0:
        drop_pct = ((previous_count - current_count) / previous_count) * 100.0
        if drop_pct > config.guards.schema_drift_drop_pct_threshold:
            return True, f"Product count dropped {drop_pct:.1f}% ({previous_count} -> {current_count}), exceeding {config.guards.schema_drift_drop_pct_threshold}% threshold."

    if empty_fields_ratio > (config.guards.empty_fields_threshold_pct / 100.0):
        return True, f"Key fields empty in {empty_fields_ratio * 100:.1f}% rows, exceeding {config.guards.empty_fields_threshold_pct}% threshold."

    return False, "Schema healthy"

