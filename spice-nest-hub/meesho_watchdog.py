"""
Meesho Listing Monitor & Deactivation Watchdog
==============================================
Extracts listings from public storefront & search, stores in spicenest.db,
and alerts whenever a new listing is added or an existing listing is deactivated.

Upgraded to use Playwright Automation Engine:
- Honest Chromium configuration (zero fingerprint spoofing, zero stealth hacks)
- Stable locators and dynamic waits on loading states
- Task pacing and rate limiting to avoid overwhelming servers
- Resilient challenge detection with manual intervention pause for CAPTCHA/MFA
- Idempotent catalog synchronization
"""

import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import asyncio
import json
import logging
import os
import random
import re
import sqlite3
import time
from datetime import datetime
from typing import Dict, Optional

from meesho_tracker.playwright_engine import (
    ChallengeDetector,
    IdempotencyGuard,
    ManualInterventionHandler,
    MeeshoLocators,
    PlaywrightSession,
    ResilientActions,
    TaskPacer,
)

logger = logging.getLogger("meesho_watchdog")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = "spicenest.db"
BRAND_QUERY = "Spice Nest Impex Private Limited"
STORE_URL = "https://www.meesho.com/SpiceNestImpexPrivateLimited?ms=2"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def init_meesho_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meesho_catalog (
                product_id TEXT PRIMARY KEY,
                title TEXT,
                price REAL,
                product_url TEXT,
                image_url TEXT,
                status TEXT, -- 'ACTIVE' or 'DEACTIVATED'
                first_seen TEXT,
                last_seen TEXT,
                deactivated_at TEXT
            )
        """)
        conn.commit()


def send_alert(event_type: str, product: dict):
    """Dispatch alerts to console, Telegram, or webhook."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if event_type == "NEW_LISTING":
        message = (
            f"🟢 [MEESHO ALERT] New Listing Added!\n"
            f"📦 Title: {product['title']}\n"
            f"💰 Price: ₹{product['price']}\n"
            f"🔗 Direct Link: {product['product_url']}\n"
            f"🕒 Detected At: {ts}"
        )
    elif event_type == "DEACTIVATED":
        message = (
            f"🔴 [MEESHO ALERT] Listing Deactivated / Missing!\n"
            f"📦 Title: {product['title']}\n"
            f"💰 Last Price: ₹{product['price']}\n"
            f"🔗 Direct Link: {product['product_url']}\n"
            f"🕒 Detected At: {ts}"
        )
    else:
        message = f"ℹ️ [MEESHO] Listing Updated: {product['title']} | ₹{product['price']}"

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60 + "\n", flush=True)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            import urllib.request
            tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode("utf-8")
            req = urllib.request.Request(tg_url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[Alert Error] Failed to send Telegram notification: {e}", flush=True)


async def _async_fetch_storefront_snapshot(target_url: Optional[str] = None) -> Optional[Dict[str, dict]]:
    """
    Fetches all active brand listings using honest Playwright browser automation
    with dynamic waits, challenge pauses, and task pacing.
    """
    url = target_url or STORE_URL
    products: Dict[str, dict] = {}

    pacer = TaskPacer(min_action_delay=0.5, max_action_delay=1.0, max_requests_per_minute=10)
    actions = ResilientActions(pacer=pacer)
    intervention_handler = ManualInterventionHandler(timeout_sec=120.0)

    logger.info(f"Navigating to storefront snapshot URL: {url}")

    async with PlaywrightSession(headless=True, filter_media=True) as session:
        page = await session.new_page()

        try:
            # 1. Paced honest navigation
            await pacer.apply_delay(0.5, 1.2)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            status = response.status if response else 200
            if status >= 400:
                logger.warning(f"HTTP {status} received on storefront page.")
                return None

            # 2. Inspect for challenges (CAPTCHA, Turnstile, Akamai)
            is_challenged, reason = await ChallengeDetector.inspect_page(page)
            if is_challenged:
                logger.warning(f"Security challenge detected: {reason}. Pausing for human resolution...")
                resolved = await intervention_handler.wait_for_resolution(page, reason or "Challenge")
                if not resolved:
                    logger.error("Human intervention timed out or was unhandled. Aborting snapshot safely.")
                    return None

            # 3. Dynamic wait for loading spinners and dismiss modal dialogs
            await actions.wait_for_loading_complete(page)
            await actions.dismiss_modal_dialogs(page)

            # 4. Smooth scrolling until catalog stabilizes
            locators = MeeshoLocators(page)
            prev_count = 0
            max_scrolls = 8

            for scroll_idx in range(1, max_scrolls + 1):
                count = await locators.product_cards.count()
                logger.info(f"Storefront scroll {scroll_idx}/{max_scrolls}: {count} product cards visible.")

                if scroll_idx > 2 and count == prev_count:
                    logger.info("Storefront product card count stabilized.")
                    break
                prev_count = count

                await pacer.scroll_smoothly(page, delta_y=1200, steps=4)
                await actions.dismiss_modal_dialogs(page)

            # 5. Extract product cards reliably
            card_anchors = await page.query_selector_all("a[href*='/p/']")
            for a in card_anchors:
                href = (await a.get_attribute("href")) or ""
                full_url = f"https://www.meesho.com{href}" if href.startswith("/") else href

                m_id = re.search(r'/p/([a-zA-Z0-9_-]+)', full_url)
                if not m_id:
                    continue
                pid = m_id.group(1)

                inner_text = await a.inner_text()
                card_lines = [l.strip() for l in inner_text.split("\n") if l.strip()]

                price = 0.0
                title = ""
                for line in card_lines:
                    if "₹" in line and not price:
                        m_p = re.search(r'₹\s*([\d,]+)', line)
                        if m_p:
                            price = float(m_p.group(1).replace(",", ""))
                    elif not title and not line.startswith("₹") and "off" not in line.lower() and "supplier" not in line.lower() and ":" not in line:
                        title = line

                if not title and card_lines:
                    title = card_lines[0]

                img_el = await a.query_selector("img")
                img_url = (await img_el.get_attribute("src")) if img_el else ""

                if pid not in products:
                    products[pid] = {
                        "product_id": pid,
                        "title": title or "Spice Nest Product",
                        "price": price,
                        "product_url": full_url,
                        "image_url": img_url,
                    }

            logger.info(f"Storefront snapshot retrieved {len(products)} active products.")
            await session.save_session()

        except Exception as e:
            logger.error(f"Error during storefront snapshot: {e}", exc_info=True)
            return None

    return products


def fetch_storefront_snapshot(target_url: Optional[str] = None) -> Optional[Dict[str, dict]]:
    """Synchronous interface for fetch_storefront_snapshot."""
    return asyncio.run(_async_fetch_storefront_snapshot(target_url))


def diff_and_sync_catalog(current_snapshot: dict):
    """Compares current storefront snapshot against the database to identify additions & deactivations."""
    if current_snapshot is None:
        print("[Watchdog] Skipping diff due to fetch failure.", flush=True)
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        db_rows = cur.execute("SELECT * FROM meesho_catalog").fetchall()
        known_products = {r["product_id"]: dict(r) for r in db_rows}

        new_count = 0
        deactivated_count = 0

        # 1. Detect NEW LISTINGS
        for pid, prod in current_snapshot.items():
            if pid not in known_products:
                cur.execute("""
                    INSERT INTO meesho_catalog 
                    (product_id, title, price, product_url, image_url, status, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                """, (pid, prod["title"], prod["price"], prod["product_url"], prod["image_url"], now_str, now_str))
                send_alert("NEW_LISTING", prod)
                new_count += 1
            else:
                cur.execute("""
                    UPDATE meesho_catalog 
                    SET last_seen = ?, price = ?, status = 'ACTIVE' 
                    WHERE product_id = ?
                """, (now_str, prod["price"], pid))

        # 2. Detect DEACTIVATED LISTINGS
        for pid, known in known_products.items():
            if known["status"] == "ACTIVE" and pid not in current_snapshot:
                cur.execute("""
                    UPDATE meesho_catalog 
                    SET status = 'DEACTIVATED', deactivated_at = ? 
                    WHERE product_id = ?
                """, (now_str, pid))
                send_alert("DEACTIVATED", known)
                deactivated_count += 1

        conn.commit()
        total_in_db = cur.execute("SELECT COUNT(*) FROM meesho_catalog").fetchone()[0]
        print(f"[Sync Summary] Synced {len(current_snapshot)} listings. New: {new_count}, Deactivated: {deactivated_count}, Total in DB: {total_in_db}", flush=True)


def run_watchdog_cycle():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Meesho Watchdog Scan...", flush=True)
    init_meesho_db()
    snapshot = fetch_storefront_snapshot()
    if snapshot is not None:
        diff_and_sync_catalog(snapshot)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Watchdog Scan Complete.", flush=True)


if __name__ == "__main__":
    run_watchdog_cycle()
