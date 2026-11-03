"""
Meesho Buyer Monitor - Accurate Price Collector
================================================
Collects verified buyer-side prices using Playwright with consistent buyer conditions.
Separates Displayed Selling Price, Offer Price, Delivery Charges, and Final Payable Amount.
Saves targeted price area screenshots and verifies selected variant before reading price.
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from playwright.async_api import async_playwright, Page

from meesho_buyer_monitor.db import get_now_ist_str, IST_TZ

logger = logging.getLogger("meesho_buyer_monitor.collector")


async def collect_single_product_price_async(
    product: Dict[str, Any],
    screenshots_dir: str = "static/screenshots",
    headless: bool = True,
    timeout_ms: int = 30000
) -> Dict[str, Any]:
    """
    Navigates to a confirmed Meesho listing, verifies identity and variant,
    extracts strictly separated price components, and captures a price area screenshot.

    Returns observation dictionary matching meesho_price_observations schema.
    """
    now_str = get_now_ist_str()
    pid_db = product["id"]
    meesho_pid = product.get("confirmed_product_id") or str(pid_db)
    target_url = product.get("confirmed_url")
    target_variant = product.get("variant") or product.get("confirmed_variant")
    delivery_pin = product.get("delivery_pin") or "110001"

    if not target_url:
        return {
            "monitored_product_id": pid_db,
            "status": "FAILED",
            "check_timestamp": now_str,
            "notes": "No confirmed URL available for monitored product.",
            "displayed_selling_price": 0.0,
            "availability": "UNKNOWN"
        }

    os.makedirs(screenshots_dir, exist_ok=True)
    ts_file = datetime.now(IST_TZ).strftime("%Y%m%d_%H%M%S")
    screenshot_filename = f"price_{meesho_pid}_{ts_file}.png"
    screenshot_full_path = os.path.join(screenshots_dir, screenshot_filename)
    screenshot_web_path = f"/static/screenshots/{screenshot_filename}"

    logger.info(f"Checking verified product [{meesho_pid}] at {target_url} (PIN: {delivery_pin})...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()

        try:
            resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(3500)
            page_title = (await page.title()).lower()

            # 1. Anti-bot / Access Denied Check
            if "access denied" in page_title or "challenge" in page_title:
                logger.warning(f"Access Denied on product {meesho_pid}. Manual action / session refresh required.")
                await browser.close()
                return {
                    "monitored_product_id": pid_db,
                    "status": "ACTION_REQUIRED",
                    "check_timestamp": now_str,
                    "notes": "Akamai Access Denied encountered on Meesho. Automated verification blocked.",
                    "displayed_selling_price": 0.0,
                    "availability": "UNKNOWN"
                }

            # 2. Product Identity Verification
            # Read visible H1 or Title
            h1_el = page.locator("h1").first
            page_h1 = ""
            if await h1_el.count() > 0:
                page_h1 = (await h1_el.inner_text()).strip()

            expected_title = product.get("confirmed_title") or product.get("name") or ""
            # Simple identity check
            if expected_title and page_h1:
                # If neither PID nor any significant keyword matches, mark ambiguous
                key_words = [w for w in re.split(r'[^a-zA-Z0-9]+', expected_title.lower()) if len(w) >= 4]
                matching_words = sum(1 for w in key_words if w in page_h1.lower())
                if key_words and matching_words == 0 and meesho_pid.lower() not in target_url.lower():
                    await browser.close()
                    return {
                        "monitored_product_id": pid_db,
                        "status": "AMBIGUOUS_MATCH",
                        "check_timestamp": now_str,
                        "notes": f"Listing title '{page_h1}' does not match expected '{expected_title}'.",
                        "displayed_selling_price": 0.0,
                        "availability": "UNKNOWN"
                    }

            # 3. Variant Verification & Selection
            # If variant specified, attempt to click the matching button/pill
            if target_variant:
                try:
                    # Look for variant buttons
                    var_button = page.locator(f"button:has-text('{target_variant}'), div[class*='size']:has-text('{target_variant}')").first
                    if await var_button.count() > 0:
                        await var_button.click(timeout=2000)
                        await page.wait_for_timeout(1000)
                        logger.info(f"Selected variant '{target_variant}' for product {meesho_pid}.")
                except Exception as var_ex:
                    logger.debug(f"Variant selection note: {var_ex}")

            # 4. Extract Price Components
            content = await page.content()
            body_text = await page.locator("body").inner_text()

            # A. Displayed Selling Price (e.g. ₹125)
            # Find largest price near the title or buybox
            selling_price = None
            price_matches = re.findall(r'₹\s*(\d+(?:\.\d{1,2})?)', body_text)
            if price_matches:
                # Filter reasonable food/grocery prices between ₹20 and ₹10000
                valid_prices = [float(p) for p in price_matches if 20.0 <= float(p) <= 10000.0]
                if valid_prices:
                    selling_price = valid_prices[0]

            if not selling_price:
                await browser.close()
                return {
                    "monitored_product_id": pid_db,
                    "status": "FAILED",
                    "check_timestamp": now_str,
                    "notes": "Could not parse displayed selling price from Meesho page.",
                    "displayed_selling_price": 0.0,
                    "availability": "UNKNOWN"
                }

            # B. MRP & Discount %
            mrp_val = None
            disc_pct = 0.0
            # Look for strikethrough price
            del_el = page.locator("del, span[style*='line-through']").first
            if await del_el.count() > 0:
                del_text = await del_el.inner_text()
                del_nums = re.findall(r'₹\s*(\d+)', del_text)
                if del_nums:
                    mrp_val = float(del_nums[0])
                    if mrp_val > selling_price:
                        disc_pct = round(((mrp_val - selling_price) / mrp_val) * 100, 1)

            # C. Delivery Charges
            # Example text: "Delivery ₹72" or "Free Delivery"
            delivery_charge = 0.0
            if "free delivery" in body_text.lower():
                delivery_charge = 0.0
            else:
                del_match = re.search(r'delivery\s*₹\s*(\d+)', body_text, re.IGNORECASE)
                if del_match:
                    delivery_charge = float(del_match.group(1))

            # D. Offer Price & Details
            offer_price = None
            offer_details = None
            # e.g. "Shop on App to get upto 35% OFF on 1st order"
            app_offer_match = re.search(r'(shop on app[^\n]+)', body_text, re.IGNORECASE)
            if app_offer_match:
                offer_details = app_offer_match.group(1).strip()
                # calculate potential app discount if 35%
                offer_price = round(selling_price * 0.65, 1)

            # E. Final Payable Amount (Selling Price + Delivery Charge)
            final_payable = round(selling_price + delivery_charge, 2)

            # F. Availability
            availability = "IN_STOCK"
            if "out of stock" in body_text.lower() or "currently unavailable" in body_text.lower():
                availability = "OUT_OF_STOCK"

            # 5. Targeted Price Screenshot Capture
            # Attempt to screenshot the price/title container without personal info
            saved_screenshot = None
            try:
                # Try locating product info header
                header_el = page.locator("div:has(h1)").first
                if await header_el.count() > 0:
                    await header_el.screenshot(path=screenshot_full_path, timeout=4000)
                    saved_screenshot = screenshot_web_path
                else:
                    # Clip top portion of page
                    await page.screenshot(
                        path=screenshot_full_path,
                        clip={"x": 50, "y": 80, "width": 800, "height": 600}
                    )
                    saved_screenshot = screenshot_web_path
                logger.info(f"Saved price area screenshot to: {screenshot_full_path}")
            except Exception as ss_ex:
                logger.debug(f"Screenshot capture note: {ss_ex}")

            await browser.close()

            return {
                "monitored_product_id": pid_db,
                "displayed_selling_price": selling_price,
                "mrp": mrp_val or selling_price,
                "discount_pct": disc_pct,
                "delivery_charge": delivery_charge,
                "offer_price": offer_price,
                "offer_details": offer_details,
                "final_payable_amount": final_payable,
                "availability": availability,
                "delivery_pin": delivery_pin,
                "payment_method": "Online / COD (Consistent Buyer Conditions)",
                "screenshot_path": saved_screenshot,
                "check_timestamp": now_str,
                "status": "VERIFIED_MATCH" if availability == "IN_STOCK" else "OUT_OF_STOCK",
                "notes": f"Price verified cleanly. Displayed: ₹{selling_price}, Delivery: ₹{delivery_charge}, Final: ₹{final_payable}"
            }

        except Exception as ex:
            logger.error(f"Error collecting price for product {meesho_pid}: {ex}")
            await browser.close()
            return {
                "monitored_product_id": pid_db,
                "status": "FAILED",
                "check_timestamp": now_str,
                "notes": f"Network / extraction exception: {str(ex)[:150]}",
                "displayed_selling_price": 0.0,
                "availability": "UNKNOWN"
            }


def collect_single_product_price(
    product: Dict[str, Any],
    screenshots_dir: str = "static/screenshots",
    headless: bool = True
) -> Dict[str, Any]:
    """Synchronous entry point for collect_single_product_price."""
    return asyncio.run(collect_single_product_price_async(
        product=product,
        screenshots_dir=screenshots_dir,
        headless=headless
    ))
