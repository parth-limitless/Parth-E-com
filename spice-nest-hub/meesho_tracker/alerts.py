"""
Meesho Tracker - Alerts System (Telegram & Run Log)
===================================================
Sends optional Telegram alerts for:
- Block / Challenge circuit breaker triggered
- Schema drift detected
- Out-of-stock product
- Price change > 10%
- Daily summary of changes
"""

import logging
import os
from typing import List, Optional

import httpx

from meesho_tracker.config import TrackerConfig
from meesho_tracker.models import ChangeRecord

logger = logging.getLogger("meesho_tracker.alerts")


class AlertManager:
    def __init__(self, config: TrackerConfig):
        self.config = config
        self.enabled = config.alerts.telegram_enabled
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.price_threshold = config.alerts.price_change_alert_threshold_pct

    def send_telegram(self, message: str):
        """Sends a message to the configured Telegram chat."""
        if not self.enabled or not self.bot_token or not self.chat_id:
            logger.debug(f"[Telegram Alert Disabled / Not Configured]: {message}")
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": f"🌶️ *Spice Nest Meesho Tracker*\n\n{message}",
            "parse_mode": "Markdown"
        }
        try:
            resp = httpx.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram notification delivered successfully.")
            else:
                logger.warning(f"Telegram API response: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.warning(f"Failed to deliver Telegram alert: {e}")

    def notify_block(self, run_id: str, reason: str, cooldown_hours: int):
        msg = (
            f"🚨 *CIRCUIT BREAKER TRIGGERED*\n"
            f"• Run ID: `{run_id}`\n"
            f"• Reason: {reason}\n"
            f"• Cooldown Active: {cooldown_hours} Hours\n"
            f"• Action: Scraper aborted cleanly to protect account."
        )
        self.send_telegram(msg)

    def notify_schema_drift(self, run_id: str, reason: str):
        msg = (
            f"⚠️ *SCHEMA DRIFT DETECTED*\n"
            f"• Run ID: `{run_id}`\n"
            f"• Warning: {reason}\n"
            f"• Action: Marked run as SUSPECT. Latest sheet preserved."
        )
        self.send_telegram(msg)

    def notify_changes(self, run_id: str, changes: List[ChangeRecord]):
        if not changes:
            return

        critical_changes = []
        for c in changes:
            if c.field_changed == "price" and c.old_value and c.new_value:
                try:
                    old_p = float(c.old_value)
                    new_p = float(c.new_value)
                    pct = abs(new_p - old_p) / old_p * 100
                    if pct >= self.price_threshold:
                        critical_changes.append(f"• Price Change: {c.product_id} changed from ₹{old_p} to ₹{new_p} ({pct:.1f}%)")
                except Exception:
                    pass
            elif c.field_changed == "in_stock" and c.new_value == "False":
                critical_changes.append(f"• Out of Stock: Product {c.product_id} marked OUT OF STOCK")

        if critical_changes:
            summary = "\n".join(critical_changes[:10])
            msg = (
                f"🔔 *CRITICAL STORE UPDATES [Run {run_id}]*\n"
                f"{summary}\n\n"
                f"Total changes recorded: {len(changes)}"
            )
            self.send_telegram(msg)

