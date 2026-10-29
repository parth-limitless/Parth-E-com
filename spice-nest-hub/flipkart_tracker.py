"""Spice Nest Hub - Flipkart Marketplace Seller Intelligence & P&L Module
Integrates Flipkart Seller API, tracks unit-level Profit & Loss,
handles RTO/Customer returns, and computes SKU-wise margins.
"""

import os
import sys
import json
import time
import base64
import sqlite3
import random
import datetime as dt
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse
import urllib.error

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spicenest.db")

FLIPKART_AUTH_URL = "https://api.flipkart.net/oauth-service/oauth/token"
FLIPKART_SHIPMENT_FILTER_URL = "https://api.flipkart.net/sellers/v3/shipments/filter"

DEFAULT_MARKETPLACE_FEE_PCT = 0.22
RTO_REVERSE_SHIPPING_LOSS = 65.0      # Reverse shipping courier loss on RTO
CUSTOMER_RETURN_DAMAGE_LOSS = 140.0   # Reverse shipping + packaging damage loss


# ------------------------------------------------------------------------------
# 1. Database Schema
# ------------------------------------------------------------------------------
def init_flipkart_db(conn: Optional[sqlite3.Connection] = None, db_path: str = DEFAULT_DB_PATH):
    """Creates flipkart_orders and sku_costs tables in SQLite."""
    close_after = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        close_after = True

    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sku_costs (
            sku TEXT PRIMARY KEY,
            product_title TEXT,
            unit_cost REAL NOT NULL,
            packaging_cost REAL DEFAULT 15.0
        );

        CREATE TABLE IF NOT EXISTS flipkart_orders (
            order_item_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            order_date TEXT NOT NULL,
            fsn TEXT,
            sku TEXT NOT NULL,
            title TEXT,
            quantity INT NOT NULL,
            selling_price REAL NOT NULL,
            total_revenue REAL NOT NULL,
            item_unit_cost REAL DEFAULT 0.0,
            total_cogs REAL DEFAULT 0.0,
            marketplace_fee REAL DEFAULT 0.0,
            shipping_penalty REAL DEFAULT 0.0,
            net_pnl REAL DEFAULT 0.0,
            pnl_status TEXT,
            shipment_status TEXT NOT NULL,
            return_type TEXT DEFAULT 'NONE',
            tracking_id TEXT,
            dispatch_date TEXT,
            delivery_date TEXT,
            last_synced_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_fk_order_date ON flipkart_orders(order_date);
        CREATE INDEX IF NOT EXISTS idx_fk_sku ON flipkart_orders(sku);
        CREATE INDEX IF NOT EXISTS idx_fk_status ON flipkart_orders(shipment_status);
        """)

        # Seed initial SKU manufacturing costs if table is empty
        cnt = conn.execute("SELECT count(*) FROM sku_costs").fetchone()[0]
        if cnt == 0:
            conn.executemany("""
            INSERT OR REPLACE INTO sku_costs (sku, product_title, unit_cost, packaging_cost)
            VALUES (?, ?, ?, ?)
            """, [
                ("SN-CHILLI-500", "Kashmiri Lal Mirch (500g)", 195.0, 18.0),
                ("SN-TURMERIC-500", "Organic Salem Turmeric Powder (500g)", 130.0, 18.0),
                ("SN-GARAM-250", "Royal Shahi Garam Masala (250g)", 185.0, 15.0),
                ("SN-CARDAMOM-100", "Whole Green Cardamom 8mm (100g)", 290.0, 12.0),
                ("SN-JEERA-500", "Jeera Whole Cumin Seeds (500g)", 175.0, 18.0),
                ("SN-PEPPER-200", "Black Pepper Tellicherry (200g)", 220.0, 15.0)
            ])
        conn.commit()
    finally:
        if close_after:
            conn.close()


def get_sku_cost_map(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Dict[str, float]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM sku_costs").fetchall()
        return {
            r["sku"]: {
                "unit_cost": float(r["unit_cost"]),
                "packaging_cost": float(r["packaging_cost"])
            }
            for r in rows
        }
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# 2. Flipkart Seller API Client
# ------------------------------------------------------------------------------
class FlipkartSellerClient:
    def __init__(self):
        self.client_id = os.environ.get("FLIPKART_APP_ID", "").strip()
        self.client_secret = os.environ.get("FLIPKART_APP_SECRET", "").strip()
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0.0

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and "YOUR_" not in self.client_id)

    def get_access_token(self) -> str:
        if self.access_token and time.time() < (self.token_expiry - 300):
            return self.access_token

        basic_auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode("utf-8")
        headers = {
            "Authorization": f"Basic {basic_auth}",
            "Accept": "application/json"
        }
        params = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "Seller_Api"
        })
        url = f"{FLIPKART_AUTH_URL}?{params}"
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.access_token = data.get("access_token")
                expires_in = int(data.get("expires_in", 3600))
                self.token_expiry = time.time() + expires_in
                return self.access_token
        except Exception as e:
            raise RuntimeError(f"Flipkart OAuth failed: {e}")

    def fetch_shipments_live(self, from_date: dt.datetime, to_date: dt.datetime) -> List[Dict[str, Any]]:
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "filter": {
                "orderDate": {
                    "fromDate": from_date.strftime("%Y-%m-%dT00:00:00Z"),
                    "toDate": to_date.strftime("%Y-%m-%dT23:59:59Z")
                },
                "states": [
                    "APPROVED", "PACKED", "READY_TO_DISPATCH", "SHIPPED", 
                    "DELIVERED", "CANCELLED", "RETURN_REQUESTED", "RETURNED"
                ]
            },
            "pagination": {"pageSize": 50}
        }

        all_shipments = []
        next_url = FLIPKART_SHIPMENT_FILTER_URL

        while next_url:
            body_bytes = json.dumps(payload).encode("utf-8") if next_url == FLIPKART_SHIPMENT_FILTER_URL else None
            req = urllib.request.Request(next_url, data=body_bytes, headers=headers, method="POST" if next_url == FLIPKART_SHIPMENT_FILTER_URL else "GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    shipments = resp_data.get("shipments", [])
                    all_shipments.extend(shipments)
                    has_more = resp_data.get("hasMore", False)
                    next_url = resp_data.get("nextPageUrl") if has_more else None
                    if next_url:
                        time.sleep(1.2)
            except Exception as e:
                print(f"[Flipkart API Sync Error]: {e}")
                break

        return all_shipments


# ------------------------------------------------------------------------------
# 3. P&L Transformation & Simulation Engine
# ------------------------------------------------------------------------------
def process_shipments_to_pnl(shipments: List[Dict[str, Any]], sku_cost_map: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    processed_records = []
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for s in shipments:
        tracking_id = s.get("trackingId", "")
        dispatch_date = s.get("dispatchDate", "")
        delivery_date = s.get("deliveryDate", "")
        order_items = s.get("orderItems", [])

        for item in order_items:
            order_item_id = item.get("orderItemId", "")
            order_id = item.get("orderId", "")
            order_date = item.get("orderDate", "") or now_str
            sku = item.get("sku", "UNKNOWN-SKU")
            fsn = item.get("fsn", "")
            title = item.get("title") or item.get("productTitle", f"Spice Item ({sku})")
            qty = int(item.get("quantity", 1))
            status = str(item.get("status") or item.get("shipmentStatus") or "DELIVERED").upper()

            price_comps = item.get("priceComponents", {})
            selling_price = float(price_comps.get("sellingPrice", item.get("price", 0.0)))
            total_revenue = selling_price * qty

            cost_info = sku_cost_map.get(sku, {"unit_cost": round(selling_price * 0.45, 1), "packaging_cost": 15.0})
            unit_cogs = cost_info["unit_cost"] + cost_info["packaging_cost"]
            total_cogs = unit_cogs * qty

            sub_status = str(item.get("subStatus", "")).upper()
            if "RTO" in status or "RTO" in sub_status or "COURIER_RETURN" in status:
                return_type = "RTO (Courier Return)"
                shipping_penalty = RTO_REVERSE_SHIPPING_LOSS * qty
                marketplace_fee = 0.0
                net_pnl = round(-shipping_penalty, 2)
            elif "RETURN" in status or "REFUND" in status or "RETURNED" in status:
                return_type = "Customer Return"
                shipping_penalty = CUSTOMER_RETURN_DAMAGE_LOSS * qty
                marketplace_fee = round(total_revenue * 0.05, 2)
                net_pnl = round(- (shipping_penalty + marketplace_fee), 2)
            elif "CANCEL" in status:
                return_type = "Buyer Cancelled"
                shipping_penalty = 0.0
                marketplace_fee = 0.0
                net_pnl = 0.0
            else:
                return_type = "NONE"
                marketplace_fee = round(total_revenue * DEFAULT_MARKETPLACE_FEE_PCT, 2)
                shipping_penalty = 0.0
                net_pnl = round(total_revenue - marketplace_fee - total_cogs, 2)

            pnl_status = "PROFIT" if net_pnl > 0 else ("BREAKEVEN" if net_pnl == 0 else "LOSS")

            processed_records.append({
                "order_item_id": order_item_id,
                "order_id": order_id,
                "order_date": order_date,
                "fsn": fsn,
                "sku": sku,
                "title": title,
                "quantity": qty,
                "selling_price": round(selling_price, 2),
                "total_revenue": round(total_revenue, 2),
                "item_unit_cost": round(unit_cogs, 2),
                "total_cogs": round(total_cogs, 2),
                "marketplace_fee": round(marketplace_fee, 2),
                "shipping_penalty": round(shipping_penalty, 2),
                "net_pnl": net_pnl,
                "pnl_status": pnl_status,
                "shipment_status": status,
                "return_type": return_type,
                "tracking_id": tracking_id,
                "dispatch_date": dispatch_date,
                "delivery_date": delivery_date,
                "last_synced_at": now_str
            })

    return processed_records


def generate_simulated_flipkart_shipments(num_orders: int = 50) -> List[Dict[str, Any]]:
    skus = [
        ("SN-CHILLI-500", "Kashmiri Lal Mirch (500g)", 420.0),
        ("SN-TURMERIC-500", "Organic Salem Turmeric Powder (500g)", 290.0),
        ("SN-GARAM-250", "Royal Shahi Garam Masala (250g)", 380.0),
        ("SN-CARDAMOM-100", "Whole Green Cardamom 8mm (100g)", 550.0),
        ("SN-JEERA-500", "Jeera Whole Cumin Seeds (500g)", 340.0),
        ("SN-PEPPER-200", "Black Pepper Tellicherry (200g)", 460.0)
    ]

    shipments = []
    now = dt.datetime.now()

    for i in range(num_orders):
        days_ago = random.randint(0, 60)
        order_time = now - dt.timedelta(days=days_ago, hours=random.randint(1, 23), minutes=random.randint(0, 59))
        sku, title, price = random.choice(skus)
        qty = random.choice([1, 1, 1, 2, 3])

        roll = random.random()
        if roll < 0.74:
            status = "DELIVERED"
            sub_status = "DELIVERED_TO_BUYER"
        elif roll < 0.86:
            status = "RETURNED"
            sub_status = "RTO_DELIVERED_TO_SELLER"
        elif roll < 0.94:
            status = "RETURNED"
            sub_status = "CUSTOMER_RETURN_DELIVERED"
        else:
            status = "SHIPPED"
            sub_status = "IN_TRANSIT"

        shipments.append({
            "shipmentId": f"SHP-{90000 + i}",
            "trackingId": f"FMPC{random.randint(100000000, 999999999)}",
            "dispatchDate": (order_time + dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "deliveryDate": (order_time + dt.timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S") if status == "DELIVERED" else "",
            "orderItems": [{
                "orderItemId": f"FK-ITEM-{50000 + i}",
                "orderId": f"OD{random.randint(10000000000000, 99999999999999)}",
                "orderDate": order_time.strftime("%Y-%m-%d %H:%M:%S"),
                "fsn": f"SPICE{random.randint(100000, 999999)}",
                "sku": sku,
                "title": title,
                "quantity": qty,
                "status": status,
                "subStatus": sub_status,
                "priceComponents": {
                    "sellingPrice": price,
                    "totalPrice": price * qty
                }
            }]
        })

    return shipments


def sync_flipkart_orders(db_path: str = DEFAULT_DB_PATH, num_mock_orders: int = 50) -> Dict[str, Any]:
    """Syncs live orders if API credentials configured, else seeds simulated orders."""
    init_flipkart_db(db_path=db_path)
    client = FlipkartSellerClient()
    sku_cost_map = get_sku_cost_map(db_path)

    is_live = client.is_configured()
    if is_live:
        from_date = dt.datetime.now() - dt.timedelta(days=30)
        to_date = dt.datetime.now()
        shipments = client.fetch_shipments_live(from_date, to_date)
        mode = "LIVE FLIPKART SELLER API"
    else:
        shipments = generate_simulated_flipkart_shipments(num_orders=num_mock_orders)
        mode = "SIMULATION DEMO ENGINE"

    processed = process_shipments_to_pnl(shipments, sku_cost_map)

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany("""
        INSERT OR REPLACE INTO flipkart_orders (
            order_item_id, order_id, order_date, fsn, sku, title,
            quantity, selling_price, total_revenue, item_unit_cost,
            total_cogs, marketplace_fee, shipping_penalty, net_pnl,
            pnl_status, shipment_status, return_type, tracking_id,
            dispatch_date, delivery_date, last_synced_at
        ) VALUES (
            :order_item_id, :order_id, :order_date, :fsn, :sku, :title,
            :quantity, :selling_price, :total_revenue, :item_unit_cost,
            :total_cogs, :marketplace_fee, :shipping_penalty, :net_pnl,
            :pnl_status, :shipment_status, :return_type, :tracking_id,
            :dispatch_date, :delivery_date, :last_synced_at
        )
        """, processed)
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "count": len(processed),
        "mode": mode,
        "is_live": is_live
    }


# ------------------------------------------------------------------------------
# 4. Analytics & Dashboard Aggregation
# ------------------------------------------------------------------------------
def get_flipkart_dashboard_analytics(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    init_flipkart_db(db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM flipkart_orders ORDER BY order_date DESC").fetchall()]
    finally:
        conn.close()

    if not rows:
        # Auto-seed if empty
        sync_flipkart_orders(db_path=db_path, num_mock_orders=50)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM flipkart_orders ORDER BY order_date DESC").fetchall()]
        conn.close()

    total_orders = len(rows)
    total_revenue = round(sum(r["total_revenue"] for r in rows), 1)
    total_cogs = round(sum(r["total_cogs"] for r in rows), 1)
    total_fee = round(sum(r["marketplace_fee"] for r in rows), 1)
    total_penalties = round(sum(r["shipping_penalty"] for r in rows), 1)
    net_pnl = round(sum(r["net_pnl"] for r in rows), 1)
    net_margin_pct = round((net_pnl / total_revenue * 100), 1) if total_revenue > 0 else 0.0

    delivered_count = sum(1 for r in rows if r["shipment_status"] == "DELIVERED")
    rto_count = sum(1 for r in rows if "RTO" in r["return_type"])
    return_count = sum(1 for r in rows if "Customer" in r["return_type"])
    transit_count = sum(1 for r in rows if r["shipment_status"] == "SHIPPED")

    rto_loss = round(sum(r["shipping_penalty"] for r in rows if "RTO" in r["return_type"]), 1)
    customer_return_loss = round(sum(r["shipping_penalty"] + r["marketplace_fee"] for r in rows if "Customer" in r["return_type"]), 1)

    # 1. SKU-Level Profitability Analysis
    from collections import defaultdict
    sku_agg = defaultdict(lambda: {
        "sku": "", "title": "", "units": 0, "revenue": 0.0,
        "cogs": 0.0, "fees": 0.0, "penalties": 0.0, "net_pnl": 0.0,
        "delivered": 0, "returns": 0
    })

    for r in rows:
        sku = r["sku"]
        sku_agg[sku]["sku"] = sku
        sku_agg[sku]["title"] = r["title"]
        sku_agg[sku]["units"] += r["quantity"]
        sku_agg[sku]["revenue"] += r["total_revenue"]
        sku_agg[sku]["cogs"] += r["total_cogs"]
        sku_agg[sku]["fees"] += r["marketplace_fee"]
        sku_agg[sku]["penalties"] += r["shipping_penalty"]
        sku_agg[sku]["net_pnl"] += r["net_pnl"]
        if r["shipment_status"] == "DELIVERED":
            sku_agg[sku]["delivered"] += r["quantity"]
        if r["return_type"] != "NONE":
            sku_agg[sku]["returns"] += r["quantity"]

    sku_list = []
    for sku, s in sku_agg.items():
        margin = round((s["net_pnl"] / s["revenue"] * 100), 1) if s["revenue"] > 0 else 0.0
        return_rate = round((s["returns"] / s["units"] * 100), 1) if s["units"] > 0 else 0.0
        sku_list.append({
            "sku": sku,
            "title": s["title"],
            "units": s["units"],
            "revenue": round(s["revenue"], 1),
            "cogs": round(s["cogs"], 1),
            "fees": round(s["fees"], 1),
            "penalties": round(s["penalties"], 1),
            "net_pnl": round(s["net_pnl"], 1),
            "margin_pct": margin,
            "return_rate_pct": return_rate
        })
    sku_list.sort(key=lambda x: x["net_pnl"], reverse=True)

    # 2. Month-wise P&L Trend
    monthly_map = defaultdict(lambda: {"revenue": 0.0, "fees": 0.0, "cogs": 0.0, "pnl": 0.0, "orders": 0, "rto": 0})
    for r in rows:
        m_code = r["order_date"][:7] # YYYY-MM
        monthly_map[m_code]["revenue"] += r["total_revenue"]
        monthly_map[m_code]["fees"] += r["marketplace_fee"]
        monthly_map[m_code]["cogs"] += r["total_cogs"]
        monthly_map[m_code]["pnl"] += r["net_pnl"]
        monthly_map[m_code]["orders"] += 1
        if "RTO" in r["return_type"] or "Customer" in r["return_type"]:
            monthly_map[m_code]["rto"] += 1

    chart_months = sorted(monthly_map.keys())
    chart_revenue = [round(monthly_map[m]["revenue"], 1) for m in chart_months]
    chart_pnl = [round(monthly_map[m]["pnl"], 1) for m in chart_months]
    chart_fees = [round(monthly_map[m]["fees"], 1) for m in chart_months]

    # Convert month codes to nice labels (e.g. Sep 26)
    chart_labels = []
    for m in chart_months:
        try:
            chart_labels.append(dt.datetime.strptime(m, "%Y-%m").strftime("%b %y"))
        except Exception:
            chart_labels.append(m)

    client = FlipkartSellerClient()
    is_live = client.is_configured()

    return {
        "kpis": {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_cogs": total_cogs,
            "total_fee": total_fee,
            "total_penalties": total_penalties,
            "net_pnl": net_pnl,
            "net_margin_pct": net_margin_pct,
            "delivered_count": delivered_count,
            "rto_count": rto_count,
            "return_count": return_count,
            "transit_count": transit_count,
            "rto_loss": rto_loss,
            "customer_return_loss": customer_return_loss
        },
        "sku_list": sku_list,
        "recent_orders": rows,
        "is_live": is_live,
        "mode_title": "🟢 LIVE FLIPKART SELLER API" if is_live else "🟡 SIMULATION DEMO ENGINE",
        "chart_data": {
            "labels": chart_labels,
            "revenue": chart_revenue,
            "pnl": chart_pnl,
            "fees": chart_fees,
            "status_labels": ["Delivered", "In Transit", "RTO Returns", "Customer Returns"],
            "status_counts": [delivered_count, transit_count, rto_count, return_count]
        }
    }

