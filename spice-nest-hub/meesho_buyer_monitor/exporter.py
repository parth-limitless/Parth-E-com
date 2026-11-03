"""
Meesho Buyer Monitor - CSV Exporter
===================================
Exports monitored products, latest price comparisons, and complete historical audit trails.
Safely escapes spreadsheet formula injection characters (=, +, -, @).
"""

import csv
import io
import sqlite3
from typing import List, Dict, Any


def sanitize_csv_cell(value: Any) -> str:
    """Escapes potential formula injection prefixes (=, +, -, @)."""
    if value is None:
        return ""
    val_str = str(value).strip()
    if val_str and val_str[0] in ["=", "+", "-", "@", "\t", "\r"]:
        return f"'{val_str}"
    return val_str


def export_buyer_monitor_csv(db_path: str) -> str:
    """Generates comprehensive CSV of monitored products and historical observations."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Product ID",
        "Target Name",
        "Seller Name",
        "Variant",
        "Pack Qty",
        "Meesho Product Code",
        "Target Price (Rs)",
        "Delivery PIN",
        "Match Status",
        "Is Active",
        "Latest Selling Price (Rs)",
        "Latest MRP (Rs)",
        "Latest Delivery Charge (Rs)",
        "Latest Final Payable (Rs)",
        "Availability",
        "Special Offer Details",
        "Check Timestamp (IST)",
        "Last Status",
        "Confirmed Meesho URL"
    ])

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM meesho_monitored_products ORDER BY id DESC").fetchall()

        for r in rows:
            writer.writerow([
                sanitize_csv_cell(r["id"]),
                sanitize_csv_cell(r["name"]),
                sanitize_csv_cell(r["seller_name"]),
                sanitize_csv_cell(r["variant"]),
                sanitize_csv_cell(r["pack_qty"]),
                sanitize_csv_cell(r["product_code"]),
                sanitize_csv_cell(r["target_price"]),
                sanitize_csv_cell(r["delivery_pin"]),
                sanitize_csv_cell(r["match_status"]),
                "ACTIVE" if r["is_active"] else "PAUSED",
                sanitize_csv_cell(r["current_price"]),
                sanitize_csv_cell(r["current_mrp"]),
                sanitize_csv_cell(r["current_delivery"]),
                sanitize_csv_cell(r["current_final_payable"]),
                sanitize_csv_cell(r["current_availability"]),
                sanitize_csv_cell(r["current_offer_details"]),
                sanitize_csv_cell(r["last_checked_at"]),
                sanitize_csv_cell(r["last_status"]),
                sanitize_csv_cell(r["confirmed_url"])
            ])

    return output.getvalue()


def export_observations_history_csv(db_path: str, product_id: int) -> str:
    """Generates detailed historical observation CSV for a single monitored product."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Observation ID",
        "Run ID",
        "Check Type",
        "Timestamp (IST)",
        "Displayed Selling Price (Rs)",
        "MRP (Rs)",
        "Discount %",
        "Offer Price (Rs)",
        "Offer Details",
        "Delivery Charge (Rs)",
        "Final Payable (Rs)",
        "Availability",
        "Delivery PIN",
        "Status",
        "Screenshot Web Path",
        "Notes"
    ])

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT * FROM meesho_price_observations 
            WHERE monitored_product_id = ? 
            ORDER BY id DESC
        """, (product_id,)).fetchall()

        for r in rows:
            writer.writerow([
                sanitize_csv_cell(r["id"]),
                sanitize_csv_cell(r["run_id"]),
                sanitize_csv_cell(r["check_type"]),
                sanitize_csv_cell(r["check_timestamp"]),
                sanitize_csv_cell(r["displayed_selling_price"]),
                sanitize_csv_cell(r["mrp"]),
                sanitize_csv_cell(r["discount_pct"]),
                sanitize_csv_cell(r["offer_price"]),
                sanitize_csv_cell(r["offer_details"]),
                sanitize_csv_cell(r["delivery_charge"]),
                sanitize_csv_cell(r["final_payable_amount"]),
                sanitize_csv_cell(r["availability"]),
                sanitize_csv_cell(r["delivery_pin"]),
                sanitize_csv_cell(r["status"]),
                sanitize_csv_cell(r["screenshot_path"]),
                sanitize_csv_cell(r["notes"])
            ])

    return output.getvalue()
