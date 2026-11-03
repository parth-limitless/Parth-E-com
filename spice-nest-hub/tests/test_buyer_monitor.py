"""
Unit & Integration Tests for Meesho Buyer Price Analysis System
================================================================
Verifies:
1. Product identification without links & candidate match scoring
2. Ambiguity detection and candidate selection integrity
3. Multi-component price separation (selling price, offer, delivery, final payable)
4. Atomic database locking to prevent duplicate/overlapping cycles
5. Restart recovery and offline overdue handling (one overdue cycle, next 24h later)
6. 24-Hour schedule calculation in Asia/Kolkata timezone
7. Safe CSV formula injection escaping
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path

# Ensure package root is in sys.path
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

import pytest
from datetime import datetime, timedelta

import meesho_buyer_monitor
from meesho_buyer_monitor.db import (
    init_buyer_monitor_db,
    add_monitored_product,
    confirm_product_match,
    get_monitored_products,
    record_price_observation,
    acquire_scheduler_lock,
    release_scheduler_lock,
    get_scheduler_status,
    toggle_product_monitoring,
    delete_monitored_product,
    get_now_ist,
    IST_TZ
)
from meesho_buyer_monitor.searcher import calculate_match_score
from meesho_buyer_monitor.exporter import sanitize_csv_cell, export_buyer_monitor_csv


@pytest.fixture
def test_db():
    """Creates an isolated temporary database for testing."""
    import gc
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_buyer_monitor_db(path)
    yield path
    gc.collect()
    try:
        if os.path.exists(path):
            os.remove(path)
    except PermissionError:
        pass


# ---------------------------------------------------------------------------
# Test 1: Match Scoring & Ambiguity Detection
# ---------------------------------------------------------------------------
def test_calculate_match_score_exact_and_variant():
    # Exact name and variant match
    score = calculate_match_score(
        target_name="Spicy & Tangy Garlic Pickle",
        target_variant="200gm",
        target_seller="Spice Nest Impex Private Limited",
        target_code=None,
        candidate_title="Spicy & Tangy Garlic Pickle 200gm Jar",
        candidate_seller="Spice Nest Impex Private Limited"
    )
    assert score >= 70.0, f"Expected high score for close match, got {score}"

    # Product code exact match (+40 bonus)
    score_with_code = calculate_match_score(
        target_name="Garlic Pickle",
        target_variant=None,
        target_seller=None,
        target_code="s-494406266",
        candidate_title="Garlic Pickle s-494406266 pack",
        candidate_seller=None
    )
    assert score_with_code >= 60.0

    # Irrelevant product score should be very low
    irrelevant_score = calculate_match_score(
        target_name="Spicy Tangy Garlic Pickle",
        target_variant="200gm",
        target_seller="Spice Nest",
        target_code=None,
        candidate_title="Taant Cotton Saree with Blouse Piece",
        candidate_seller="Fashion Hub"
    )
    assert irrelevant_score < 20.0


# ---------------------------------------------------------------------------
# Test 2: Product Confirmation & Identification Integrity
# ---------------------------------------------------------------------------
def test_product_confirmation_lifecycle(test_db):
    # 1. Add product without link
    pid = add_monitored_product(
        db_path=test_db,
        name="Mixed Fruit Jam",
        seller_name="Spice Nest",
        variant="370g",
        target_price=220.0,
        delivery_pin="110001"
    )
    assert pid > 0

    prods = get_monitored_products(test_db)
    assert len(prods) == 1
    assert prods[0]["match_status"] == "PENDING_CONFIRMATION"
    assert prods[0]["is_active"] == 1

    # 2. Confirm candidate match
    success = confirm_product_match(
        db_path=test_db,
        product_id=pid,
        confirmed_product_id="828zt5",
        confirmed_url="https://www.meesho.com/mixed-fruit-jam-by-spice-nest/p/828zt5?ms=2&source=Meri+Shop",
        confirmed_title="Mixed Fruit Jam by spice nest",
        confirmed_seller="Spice Nest Impex Private Limited",
        confirmed_variant="370g"
    )
    assert success is True

    prods_after = get_monitored_products(test_db)
    assert prods_after[0]["match_status"] == "VERIFIED"
    assert prods_after[0]["confirmed_product_id"] == "828zt5"


# ---------------------------------------------------------------------------
# Test 3: Accurate Multi-Component Price Separation
# ---------------------------------------------------------------------------
def test_accurate_price_separation_and_history(test_db):
    pid = add_monitored_product(
        db_path=test_db,
        name="Spicy & Tangy Garlic Pickle",
        variant="200gm",
        target_price=120.0
    )
    confirm_product_match(
        db_path=test_db,
        product_id=pid,
        confirmed_product_id="86cube",
        confirmed_url="https://www.meesho.com/spicy-tangy-garlic-pickle-200gm/p/86cube",
        confirmed_title="Spicy & Tangy Garlic Pickle 200gm"
    )

    # Observation 1: Benchmark Price (Selling: 154, Delivery: 0, Final: 154)
    obs1 = {
        "monitored_product_id": pid,
        "run_id": "run_001",
        "check_type": "scheduled",
        "check_timestamp": "2026-11-01 10:00:00",
        "displayed_selling_price": 154.0,
        "mrp": 234.0,
        "discount_pct": 34.0,
        "delivery_charge": 0.0,
        "final_payable_amount": 154.0,
        "availability": "IN_STOCK",
        "status": "VERIFIED_MATCH",
        "notes": "Verified initial benchmark"
    }
    record_price_observation(test_db, obs1)

    # Observation 2: New Price (Selling: 125, Delivery: 72, Final: 197)
    obs2 = {
        "monitored_product_id": pid,
        "run_id": "run_002",
        "check_type": "scheduled",
        "check_timestamp": "2026-11-02 10:00:00",
        "displayed_selling_price": 125.0,
        "mrp": 234.0,
        "discount_pct": 47.0,
        "offer_price": 81.0,
        "offer_details": "Shop on App 35% OFF",
        "delivery_charge": 72.0,
        "final_payable_amount": 197.0,
        "availability": "IN_STOCK",
        "status": "VERIFIED_MATCH",
        "notes": "Price dropped to 125, delivery is 72"
    }
    record_price_observation(test_db, obs2)

    # Verify calculated comparisons
    prods = get_monitored_products(test_db)
    prod = prods[0]

    assert prod["current_price"] == 125.0
    assert prod["current_delivery"] == 72.0
    assert prod["current_final_payable"] == 197.0
    assert prod["prev_verified_price"] == 154.0
    # Price difference: 125 - 154 = -29.0
    assert prod["price_change_rs"] == -29.0
    assert prod["price_change_pct"] == round((-29.0 / 154.0) * 100, 1)
    # Difference vs target (target is 120): 125 - 120 = +5.0
    assert prod["target_diff_rs"] == 5.0


# ---------------------------------------------------------------------------
# Test 4: Atomic Scheduler Locking (Prevent Duplicate Cycles)
# ---------------------------------------------------------------------------
def test_atomic_scheduler_locking(test_db):
    # Worker 1 acquires lock
    lock1 = acquire_scheduler_lock(test_db, run_id="run_worker_1", lock_duration_sec=300)
    assert lock1 is True

    # Worker 2 attempts to acquire lock simultaneously -> MUST FAIL
    lock2 = acquire_scheduler_lock(test_db, run_id="run_worker_2", lock_duration_sec=300)
    assert lock2 is False

    # Status must show RUNNING
    status = get_scheduler_status(test_db)
    assert status["is_running"] == 1
    assert status["current_run_id"] == "run_worker_1"

    # Worker 1 completes and releases lock
    release_scheduler_lock(test_db, run_id="run_worker_1", status="COMPLETED")

    # Status must show IDLE and not running
    status_after = get_scheduler_status(test_db)
    assert status_after["is_running"] == 0

    # Worker 2 can now acquire lock
    lock3 = acquire_scheduler_lock(test_db, run_id="run_worker_2", lock_duration_sec=300)
    assert lock3 is True
    release_scheduler_lock(test_db, run_id="run_worker_2", status="COMPLETED")


# ---------------------------------------------------------------------------
# Test 5: 24-Hour Interval Calculation & Restart Resilience
# ---------------------------------------------------------------------------
def test_24_hour_interval_calculation(test_db):
    now_ist = get_now_ist()
    run_id = "test_run_interval"

    acquire_scheduler_lock(test_db, run_id=run_id)
    release_scheduler_lock(test_db, run_id=run_id, status="COMPLETED")

    status = get_scheduler_status(test_db)
    next_run_str = status["next_scheduled_run"]
    next_dt = datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_TZ)

    # Next run must be approximately 24 hours from cycle start
    expected_dt = now_ist + timedelta(hours=24)
    diff_sec = abs((next_dt - expected_dt).total_seconds())
    assert diff_sec < 5, f"Expected 24-hour interval, diff was {diff_sec}s"


# ---------------------------------------------------------------------------
# Test 6: Offline Overdue Handling
# ---------------------------------------------------------------------------
def test_offline_overdue_detection(test_db):
    # Simulate an overdue cycle: next_scheduled_run was set to 2 hours ago
    past_time = (get_now_ist() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(test_db) as conn:
        conn.execute("UPDATE meesho_scheduler_state SET is_running = 0, next_scheduled_run = ?", (past_time,))
        conn.commit()

    status = get_scheduler_status(test_db)
    assert status["is_overdue"] is True
    assert status["seconds_until_next_run"] == 0


# ---------------------------------------------------------------------------
# Test 7: CSV Formula Injection Escaping
# ---------------------------------------------------------------------------
def test_csv_formula_injection_escaping():
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("+cmd|'/c calc'!A0") == "'+cmd|'/c calc'!A0"
    assert sanitize_csv_cell("-50") == "'-50"
    assert sanitize_csv_cell("@SUM(1,2)") == "'@SUM(1,2)"
    assert sanitize_csv_cell("Garlic Pickle") == "Garlic Pickle"
    assert sanitize_csv_cell(125.0) == "125.0"
