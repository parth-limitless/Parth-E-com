"""
Meesho Buyer Monitor - Database Layer
=====================================
Manages persistent schema, atomic scheduler locking, observation logging,
and price history analytics for buyer-side product monitoring.
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("meesho_buyer_monitor.db")

# Timezone standard: Asia/Kolkata (IST = UTC+5:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def get_now_ist() -> datetime:
    """Returns current datetime in Asia/Kolkata timezone."""
    return datetime.now(IST_TZ)


def get_now_ist_str() -> str:
    """Returns formatted ISO string in Asia/Kolkata timezone: YYYY-MM-DD HH:MM:SS."""
    return get_now_ist().strftime("%Y-%m-%d %H:%M:%S")


def init_buyer_monitor_db(db_path: str = "spicenest.db"):
    """
    Initializes database tables required for 24-hour buyer price monitoring:
    1. meesho_monitored_products: Configured products, variants, and latest verified status.
    2. meesho_price_observations: Immutable historical price snapshots with buyer conditions.
    3. meesho_scheduler_state: Persistent background scheduler state, lock, and next run timestamp.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Monitored Products Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meesho_monitored_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                seller_name TEXT,
                variant TEXT,
                pack_qty INTEGER DEFAULT 1,
                product_code TEXT,
                target_price REAL,
                delivery_pin TEXT DEFAULT '110001',
                confirmed_product_id TEXT,
                confirmed_url TEXT,
                confirmed_title TEXT,
                confirmed_seller TEXT,
                confirmed_variant TEXT,
                confirmed_image_url TEXT,
                match_status TEXT DEFAULT 'PENDING_CONFIRMATION',
                is_active INTEGER DEFAULT 1,
                current_price REAL,
                current_mrp REAL,
                current_delivery REAL DEFAULT 0.0,
                current_final_payable REAL,
                current_availability TEXT DEFAULT 'UNKNOWN',
                current_offer_details TEXT,
                last_screenshot_path TEXT,
                last_checked_at TEXT,
                last_successful_check_at TEXT,
                last_status TEXT DEFAULT 'NEW',
                last_error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Historical Observations Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meesho_price_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitored_product_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                check_type TEXT NOT NULL, -- 'scheduled' or 'manual'
                check_timestamp TEXT NOT NULL,
                displayed_selling_price REAL NOT NULL,
                mrp REAL,
                discount_pct REAL,
                offer_price REAL,
                offer_details TEXT,
                delivery_charge REAL DEFAULT 0.0,
                final_payable_amount REAL,
                availability TEXT NOT NULL, -- 'IN_STOCK' or 'OUT_OF_STOCK'
                delivery_pin TEXT,
                payment_method TEXT,
                screenshot_path TEXT,
                status TEXT NOT NULL, -- 'VERIFIED_MATCH', 'FAILED', 'AMBIGUOUS_MATCH', 'ACTION_REQUIRED', 'OUT_OF_STOCK'
                notes TEXT,
                FOREIGN KEY(monitored_product_id) REFERENCES meesho_monitored_products(id)
            )
        """)

        # Indexes for fast historical queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_prod_time 
            ON meesho_price_observations (monitored_product_id, check_timestamp DESC)
        """)

        # 3. Persistent Scheduler State Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meesho_scheduler_state (
                id INTEGER PRIMARY KEY,
                scheduler_name TEXT UNIQUE DEFAULT 'meesho_24h_buyer_monitor',
                is_running INTEGER DEFAULT 0,
                last_run_start TEXT,
                last_run_finish TEXT,
                next_scheduled_run TEXT,
                current_run_id TEXT,
                lock_token TEXT,
                lock_expires_at TEXT,
                last_run_status TEXT DEFAULT 'IDLE',
                total_runs_count INTEGER DEFAULT 0,
                consecutive_failures INTEGER DEFAULT 0,
                last_error TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed default scheduler state row if not present
        row = cur.execute("SELECT id FROM meesho_scheduler_state WHERE id = 1").fetchone()
        if not row:
            next_initial = (get_now_ist() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                INSERT INTO meesho_scheduler_state 
                (id, scheduler_name, is_running, next_scheduled_run, last_run_status, updated_at)
                VALUES (1, 'meesho_24h_buyer_monitor', 0, ?, 'IDLE', ?)
            """, (next_initial, get_now_ist_str()))

        conn.commit()
        logger.info("Buyer Monitor database schema initialized successfully.")


# ---------------------------------------------------------------------------
# Product CRUD Operations
# ---------------------------------------------------------------------------
def add_monitored_product(
    db_path: str,
    name: str,
    seller_name: Optional[str] = None,
    variant: Optional[str] = None,
    pack_qty: int = 1,
    product_code: Optional[str] = None,
    target_price: Optional[float] = None,
    delivery_pin: str = "110001",
    direct_url: Optional[str] = None
) -> int:
    """Inserts a new product candidate into meesho_monitored_products table."""
    now_str = get_now_ist_str()
    status = "VERIFIED" if direct_url else "PENDING_CONFIRMATION"

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO meesho_monitored_products (
                name, seller_name, variant, pack_qty, product_code, target_price,
                delivery_pin, confirmed_url, match_status, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            name.strip(),
            seller_name.strip() if seller_name else None,
            variant.strip() if variant else None,
            pack_qty,
            product_code.strip() if product_code else None,
            target_price,
            delivery_pin.strip() if delivery_pin else "110001",
            direct_url.strip() if direct_url else None,
            status,
            now_str,
            now_str
        ))
        conn.commit()
        return cur.lastrowid


def confirm_product_match(
    db_path: str,
    product_id: int,
    confirmed_product_id: str,
    confirmed_url: str,
    confirmed_title: str,
    confirmed_seller: Optional[str] = None,
    confirmed_variant: Optional[str] = None,
    confirmed_image_url: Optional[str] = None
) -> bool:
    """
    Confirms candidate listing once and locks its verified identifier and URL
    for subsequent 24-hour automatic monitoring.
    """
    now_str = get_now_ist_str()
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE meesho_monitored_products SET
                confirmed_product_id = ?,
                confirmed_url = ?,
                confirmed_title = ?,
                confirmed_seller = ?,
                confirmed_variant = ?,
                confirmed_image_url = ?,
                match_status = 'VERIFIED',
                last_status = 'VERIFIED_AWAITING_FIRST_CHECK',
                updated_at = ?
            WHERE id = ?
        """, (
            confirmed_product_id,
            confirmed_url,
            confirmed_title,
            confirmed_seller,
            confirmed_variant,
            confirmed_image_url,
            now_str,
            product_id
        ))
        conn.commit()
        return cur.rowcount > 0


def toggle_product_monitoring(db_path: str, product_id: int, is_active: bool) -> bool:
    """Enables or pauses automatic 24-hour monitoring for a product."""
    now_str = get_now_ist_str()
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE meesho_monitored_products 
            SET is_active = ?, updated_at = ? 
            WHERE id = ?
        """, (1 if is_active else 0, now_str, product_id))
        conn.commit()
        return cur.rowcount > 0


def delete_monitored_product(db_path: str, product_id: int) -> bool:
    """Deletes a monitored product and its associated price observations."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM meesho_price_observations WHERE monitored_product_id = ?", (product_id,))
        cur.execute("DELETE FROM meesho_monitored_products WHERE id = ?", (product_id,))
        conn.commit()
        return cur.rowcount > 0


def get_monitored_products(db_path: str, only_active: bool = False) -> List[Dict[str, Any]]:
    """
    Retrieves monitored products with calculated price changes:
    - Previous verified price and date
    - Current verified price
    - Difference in rupees (diff_amount)
    - Difference in percentage (diff_pct)
    - Difference vs target price (target_diff)
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        query = "SELECT * FROM meesho_monitored_products"
        if only_active:
            query += " WHERE is_active = 1"
        query += " ORDER BY id DESC"

        products = [dict(r) for r in cur.execute(query).fetchall()]

        # Compute price changes for each product from price observations
        for p in products:
            pid = p["id"]
            # Fetch last 2 successful verified observations
            obs_rows = cur.execute("""
                SELECT displayed_selling_price, final_payable_amount, check_timestamp 
                FROM meesho_price_observations 
                WHERE monitored_product_id = ? AND status = 'VERIFIED_MATCH'
                ORDER BY id DESC LIMIT 2
            """, (pid,)).fetchall()

            curr_obs = dict(obs_rows[0]) if len(obs_rows) >= 1 else None
            prev_obs = dict(obs_rows[1]) if len(obs_rows) >= 2 else None

            p["prev_verified_price"] = prev_obs["displayed_selling_price"] if prev_obs else None
            p["prev_verified_date"] = prev_obs["check_timestamp"] if prev_obs else None

            # Calculate price change vs previous verified check
            if p.get("current_price") is not None and p.get("prev_verified_price") is not None:
                cur_p = float(p["current_price"])
                prev_p = float(p["prev_verified_price"])
                diff = round(cur_p - prev_p, 2)
                p["price_change_rs"] = diff
                p["price_change_pct"] = round((diff / prev_p) * 100, 1) if prev_p > 0 else 0.0
            else:
                p["price_change_rs"] = None
                p["price_change_pct"] = None

            # Calculate difference vs user target price
            if p.get("current_price") is not None and p.get("target_price") is not None:
                cur_p = float(p["current_price"])
                target_p = float(p["target_price"])
                p["target_diff_rs"] = round(cur_p - target_p, 2)
            else:
                p["target_diff_rs"] = None

        return products


def get_product_observations_history(db_path: str, product_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Returns chronologically ordered observation records for a product."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT * FROM meesho_price_observations 
            WHERE monitored_product_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (product_id, limit)).fetchall()
        return [dict(r) for r in rows]


def record_price_observation(db_path: str, obs: Dict[str, Any]) -> int:
    """
    Atomically inserts a price observation and updates the current state
    of the monitored product.
    """
    now_str = get_now_ist_str()
    pid = obs["monitored_product_id"]

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        # Insert observation record
        cur.execute("""
            INSERT INTO meesho_price_observations (
                monitored_product_id, run_id, check_type, check_timestamp,
                displayed_selling_price, mrp, discount_pct, offer_price, offer_details,
                delivery_charge, final_payable_amount, availability, delivery_pin,
                payment_method, screenshot_path, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pid,
            obs.get("run_id", f"run_{int(datetime.now().timestamp())}"),
            obs.get("check_type", "scheduled"),
            obs.get("check_timestamp", now_str),
            obs.get("displayed_selling_price", 0.0),
            obs.get("mrp"),
            obs.get("discount_pct"),
            obs.get("offer_price"),
            obs.get("offer_details"),
            obs.get("delivery_charge", 0.0),
            obs.get("final_payable_amount"),
            obs.get("availability", "IN_STOCK"),
            obs.get("delivery_pin", "110001"),
            obs.get("payment_method"),
            obs.get("screenshot_path"),
            obs.get("status", "VERIFIED_MATCH"),
            obs.get("notes")
        ))
        obs_id = cur.lastrowid

        # Update monitored product summary state if observation succeeded
        if obs.get("status") in ["VERIFIED_MATCH", "OUT_OF_STOCK"]:
            cur.execute("""
                UPDATE meesho_monitored_products SET
                    current_price = ?,
                    current_mrp = ?,
                    current_delivery = ?,
                    current_final_payable = ?,
                    current_availability = ?,
                    current_offer_details = ?,
                    last_screenshot_path = ?,
                    last_checked_at = ?,
                    last_successful_check_at = ?,
                    last_status = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
            """, (
                obs.get("displayed_selling_price"),
                obs.get("mrp"),
                obs.get("delivery_charge", 0.0),
                obs.get("final_payable_amount"),
                obs.get("availability", "IN_STOCK"),
                obs.get("offer_details"),
                obs.get("screenshot_path"),
                obs.get("check_timestamp", now_str),
                obs.get("check_timestamp", now_str),
                obs.get("status"),
                now_str,
                pid
            ))
        else:
            # Failed or ambiguous check: record timestamp and error, retain old price
            cur.execute("""
                UPDATE meesho_monitored_products SET
                    last_checked_at = ?,
                    last_status = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                obs.get("check_timestamp", now_str),
                obs.get("status", "FAILED"),
                obs.get("notes", "Check failed"),
                now_str,
                pid
            ))

        conn.commit()
        return obs_id


# ---------------------------------------------------------------------------
# Scheduler Lock & State Management
# ---------------------------------------------------------------------------
def acquire_scheduler_lock(db_path: str, run_id: str, lock_duration_sec: int = 900) -> bool:
    """
    Acquires an atomic lock on the 24-hour scheduler using SQLite transactions.
    Prevents overlapping executions across multiple processes or background workers.
    """
    now_ist = get_now_ist()
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")
    expires_str = (now_ist + timedelta(seconds=lock_duration_sec)).strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Check existing lock state
        row = cur.execute("SELECT * FROM meesho_scheduler_state WHERE id = 1").fetchone()
        if not row:
            init_buyer_monitor_db(db_path)
            row = cur.execute("SELECT * FROM meesho_scheduler_state WHERE id = 1").fetchone()

        is_running = row["is_running"]
        lock_expires_at = row["lock_expires_at"]

        # Lock is valid if currently running and not expired
        if is_running and lock_expires_at and lock_expires_at > now_str:
            logger.warning(f"Scheduler already locked by {row['current_run_id']} until {lock_expires_at}.")
            return False

        # Acquire lock
        cur.execute("""
            UPDATE meesho_scheduler_state SET
                is_running = 1,
                last_run_start = ?,
                current_run_id = ?,
                lock_token = ?,
                lock_expires_at = ?,
                last_run_status = 'RUNNING',
                total_runs_count = total_runs_count + 1,
                updated_at = ?
            WHERE id = 1
        """, (now_str, run_id, run_id, expires_str, now_str))
        conn.commit()
        return True


def release_scheduler_lock(
    db_path: str,
    run_id: str,
    status: str = "COMPLETED",
    error_message: Optional[str] = None
):
    """
    Releases the scheduler lock, records finish timestamp, and computes
    the exact NEXT automatic check: precisely 24 hours after this cycle's start time!
    """
    now_ist = get_now_ist()
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        row = cur.execute("SELECT last_run_start FROM meesho_scheduler_state WHERE id = 1").fetchone()
        cycle_start_str = row["last_run_start"] if row and row["last_run_start"] else now_str

        try:
            cycle_start = datetime.strptime(cycle_start_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_TZ)
        except Exception:
            cycle_start = now_ist

        # Exact 24-hour interval from cycle start time
        next_run = cycle_start + timedelta(hours=24)
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S")

        cur.execute("""
            UPDATE meesho_scheduler_state SET
                is_running = 0,
                last_run_finish = ?,
                next_scheduled_run = ?,
                current_run_id = NULL,
                lock_token = NULL,
                lock_expires_at = NULL,
                last_run_status = ?,
                consecutive_failures = CASE WHEN ? = 'FAILED' THEN consecutive_failures + 1 ELSE 0 END,
                last_error = ?,
                updated_at = ?
            WHERE id = 1
        """, (now_str, next_run_str, status, status, error_message, now_str))
        conn.commit()
        logger.info(f"Released lock for {run_id}. Next cycle scheduled at: {next_run_str} (Asia/Kolkata)")


def get_scheduler_status(db_path: str) -> Dict[str, Any]:
    """
    Returns live scheduler state in Asia/Kolkata timezone:
    - is_running, lock status
    - last_run_start, last_run_finish
    - next_scheduled_run
    - is_overdue (True if server was offline and scheduled time has passed)
    """
    now_ist = get_now_ist()
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM meesho_scheduler_state WHERE id = 1").fetchone()
        if not row:
            init_buyer_monitor_db(db_path)
            row = cur.execute("SELECT * FROM meesho_scheduler_state WHERE id = 1").fetchone()

        data = dict(row)
        next_run_str = data.get("next_scheduled_run")

        is_overdue = False
        remaining_seconds = 0
        if next_run_str:
            try:
                next_run_dt = datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_TZ)
                diff_sec = (next_run_dt - now_ist).total_seconds()
                if diff_sec <= 0 and not data.get("is_running"):
                    is_overdue = True
                    remaining_seconds = 0
                else:
                    remaining_seconds = max(0, int(diff_sec))
            except Exception:
                pass

        data["current_time_ist"] = now_str
        data["is_overdue"] = is_overdue
        data["seconds_until_next_run"] = remaining_seconds
        return data
