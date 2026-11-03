"""
Meesho Buyer Monitor - Persistent 24-Hour Scheduler
===================================================
Executes exact 24-hour recurring cycles with database-persisted state,
atomic SQLite distributed locks, offline recovery, limited failure retries,
and independent manual 'Check Now' execution. Displayed in Asia/Kolkata (IST).
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import uuid4

from meesho_buyer_monitor.db import (
    acquire_scheduler_lock,
    get_now_ist,
    get_now_ist_str,
    get_scheduler_status,
    get_monitored_products,
    record_price_observation,
    release_scheduler_lock,
    IST_TZ
)
from meesho_buyer_monitor.collector import collect_single_product_price

logger = logging.getLogger("meesho_buyer_monitor.scheduler")

_SCHEDULER_THREAD: Optional[threading.Thread] = None
_STOP_EVENT = threading.Event()


def run_monitoring_cycle(
    db_path: str,
    check_type: str = "scheduled",
    target_product_id: Optional[int] = None,
    max_retries_per_item: int = 2
) -> Dict[str, Any]:
    """
    Executes a monitoring cycle across active verified products.
    Logs each observation and updates current product states.
    """
    now_ist = get_now_ist()
    run_id = f"cycle_{now_ist.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    logger.info(f"Starting buyer monitor cycle [{run_id}] (Type: {check_type}, Target: {target_product_id or 'ALL'})...")

    # Fetch active products
    if target_product_id:
        all_prods = get_monitored_products(db_path)
        prods = [p for p in all_prods if p["id"] == target_product_id]
    else:
        prods = get_monitored_products(db_path, only_active=True)

    verified_prods = [p for p in prods if p.get("match_status") == "VERIFIED"]
    results = []

    for prod in verified_prods:
        attempt = 0
        obs = None
        while attempt <= max_retries_per_item:
            attempt += 1
            try:
                obs = collect_single_product_price(
                    product=prod,
                    screenshots_dir="static/screenshots",
                    headless=True
                )
                obs["run_id"] = run_id
                obs["check_type"] = check_type

                # Success or Out of Stock: break retry loop
                if obs.get("status") in ["VERIFIED_MATCH", "OUT_OF_STOCK"]:
                    break

                logger.warning(f"Product {prod['id']} check attempt {attempt} returned {obs.get('status')}. Retrying in 5s...")
                time.sleep(5)
            except Exception as ex:
                logger.error(f"Product {prod['id']} exception on attempt {attempt}: {ex}")
                time.sleep(5)

        if obs:
            obs_id = record_price_observation(db_path, obs)
            obs["observation_id"] = obs_id
            results.append(obs)

    logger.info(f"Cycle [{run_id}] finished. Processed {len(results)} of {len(verified_prods)} verified products.")
    return {
        "run_id": run_id,
        "processed_count": len(results),
        "total_verified": len(verified_prods),
        "results": results
    }


def _scheduler_background_loop(db_path: str, poll_interval_sec: int = 30):
    """
    Continuous background loop that wakes up every poll_interval_sec,
    inspects persistent SQLite scheduler state, and executes when due.
    """
    logger.info("24-Hour Buyer Monitor persistent scheduler background worker started.")

    while not _STOP_EVENT.is_set():
        try:
            status = get_scheduler_status(db_path)
            now_ist = get_now_ist()
            now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")

            next_run_str = status.get("next_scheduled_run")
            is_running = status.get("is_running")

            # Check if cycle is due or overdue
            if next_run_str and not is_running:
                try:
                    next_run_dt = datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_TZ)
                    is_due = now_ist >= next_run_dt
                except Exception:
                    is_due = False

                if is_due:
                    run_id = f"auto24h_{now_ist.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
                    logger.info(f"24-Hour cycle is due ({next_run_str} <= {now_str}). Attempting to acquire lock...")

                    if acquire_scheduler_lock(db_path, run_id, lock_duration_sec=900):
                        try:
                            res = run_monitoring_cycle(db_path, check_type="scheduled")
                            release_scheduler_lock(db_path, run_id, status="COMPLETED")
                        except Exception as cycle_ex:
                            logger.error(f"Scheduled 24-hour cycle failed with exception: {cycle_ex}")
                            release_scheduler_lock(db_path, run_id, status="FAILED", error_message=str(cycle_ex))
                    else:
                        logger.debug("Lock could not be acquired (cycle running in another worker).")

        except Exception as loop_ex:
            logger.error(f"Scheduler tick exception: {loop_ex}")

        # Sleep for poll interval or until stop event is signaled
        _STOP_EVENT.wait(timeout=poll_interval_sec)


def start_background_scheduler(db_path: str):
    """Starts the persistent background daemon thread if not already running."""
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
        logger.debug("Scheduler thread already active.")
        return

    _STOP_EVENT.clear()
    _SCHEDULER_THREAD = threading.Thread(
        target=_scheduler_background_loop,
        args=(db_path,),
        name="Meesho24hBuyerMonitorThread",
        daemon=True
    )
    _SCHEDULER_THREAD.start()
    logger.info("Started Meesho 24h Buyer Monitor background thread.")


def stop_background_scheduler():
    """Signals background worker to terminate cleanly."""
    _STOP_EVENT.set()
    if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
        _SCHEDULER_THREAD.join(timeout=5)
        logger.info("Stopped Meesho 24h Buyer Monitor background thread.")


def trigger_manual_check(db_path: str, product_id: int) -> Dict[str, Any]:
    """
    Executes an on-demand check for a single product without affecting
    or duplicating the 24-hour recurring schedule.
    """
    logger.info(f"Manual 'Check Now' triggered for product #{product_id}.")
    return run_monitoring_cycle(db_path, check_type="manual", target_product_id=product_id)
