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
        client = FlipkartSellerClient()
        is_live = client.is_configured()
        return {
            "kpis": {
                "total_orders": 0,
                "total_revenue": 0.0,
                "total_cogs": 0.0,
                "total_fee": 0.0,
                "total_penalties": 0.0,
                "net_pnl": 0.0,
                "net_margin_pct": 0.0,
                "delivered_count": 0,
                "rto_count": 0,
                "return_count": 0,
                "transit_count": 0,
                "rto_loss": 0.0,
                "customer_return_loss": 0.0
            },
            "sku_list": [],
            "recent_orders": [],
            "is_live": is_live,
            "mode_title": "🟢 LIVE FLIPKART SELLER API" if is_live else "⚡ FLIPKART SELLER DASHBOARD",
            "chart_data": {
                "labels": ["No Orders Yet"],
                "revenue": [0.0],
                "pnl": [0.0],
                "fees": [0.0],
                "status_labels": ["Delivered", "In Transit", "RTO Returns", "Customer Returns"],
                "status_counts": [0, 0, 0, 0]
            }
        }

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



# ------------------------------------------------------------------------------
# 7. Daily Flipkart Inventory, Out of Stock, Delisted & Price Delta Engine
# ------------------------------------------------------------------------------
def init_flipkart_snapshot_db(conn: sqlite3.Connection):
    """Ensures flipkart_snapshots and flipkart_changes tables exist with indices."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS flipkart_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        product_id TEXT NOT NULL,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        mrp REAL,
        rating REAL,
        review_count INT,
        in_stock INT DEFAULT 1,
        product_url TEXT,
        image_url TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_fk_snap_date ON flipkart_snapshots(snapshot_date);
    CREATE INDEX IF NOT EXISTS idx_fk_snap_pid ON flipkart_snapshots(product_id);
    CREATE INDEX IF NOT EXISTS idx_fk_snap_id ON flipkart_snapshots(snapshot_id);

    CREATE TABLE IF NOT EXISTS flipkart_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id TEXT,
        detected_at TEXT NOT NULL,
        product_id TEXT NOT NULL,
        name TEXT NOT NULL,
        change_type TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        diff_amount REAL DEFAULT 0.0,
        pct_change REAL DEFAULT 0.0,
        product_url TEXT,
        image_url TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_fk_chg_date ON flipkart_changes(detected_at);
    CREATE INDEX IF NOT EXISTS idx_fk_chg_type ON flipkart_changes(change_type);
    CREATE INDEX IF NOT EXISTS idx_fk_chg_pid ON flipkart_changes(product_id);
    """)


def record_flipkart_snapshot_and_diff(conn: sqlite3.Connection, parsed_items: List[Dict[str, Any]], now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Automated Daily Snapshot & Delta Intelligence Engine for Flipkart.
    Compares uploaded catalog against the previous day's snapshot and detects:
    - Price Increases (PRICE_HIKE)
    - Price Decreases (PRICE_DROP)
    - Out of Stock items (OUT_OF_STOCK)
    - Delisted / Removed items (DELISTED)
    - Back In Stock items (BACK_IN_STOCK)
    - Newly added listings (NEW_LISTING)
    """
    if not now_iso:
        now_iso = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    init_flipkart_snapshot_db(conn)
    cur = conn.cursor()

    snapshot_id = f"FK-SNAP-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{int(time.time()*1000)%10000:04d}"

    # 1. Fetch previous snapshot metadata
    cur.execute("""
        SELECT snapshot_id, snapshot_date 
        FROM flipkart_snapshots 
        GROUP BY snapshot_id 
        ORDER BY snapshot_date DESC 
        LIMIT 1
    """)
    prev_meta = cur.fetchone()

    prev_items: Dict[str, Dict[str, Any]] = {}
    if prev_meta:
        prev_snap_id = prev_meta[0]
        cur.execute("SELECT * FROM flipkart_snapshots WHERE snapshot_id = ?", (prev_snap_id,))
        for r in cur.fetchall():
            r_dict = dict(r) if hasattr(r, 'keys') else {
                "product_id": r[3], "name": r[4], "price": r[5], "mrp": r[6],
                "rating": r[7], "review_count": r[8], "in_stock": r[9],
                "product_url": r[10], "image_url": r[11]
            }
            prev_items[str(r_dict["product_id"])] = r_dict

    curr_map = {str(p["product_id"]): p for p in parsed_items if p.get("product_id")}

    changes_recorded = []
    hikes_count = 0
    drops_count = 0
    oos_count = 0
    back_count = 0
    delisted_count = 0
    new_count = 0

    # A. Compare current items with previous snapshot
    for pid, p in curr_map.items():
        new_price = float(p.get("price") or 0.0)
        new_stock = 1 if p.get("in_stock", True) else 0
        p_name = p.get("name") or "Spice Nest Product"
        p_url = p.get("product_url") or ""
        p_img = p.get("image_url") or ""

        if pid in prev_items:
            prev = prev_items[pid]
            old_price = float(prev.get("price") or new_price)
            old_stock = int(prev.get("in_stock", 1))

            # 1. Price analysis
            if new_price > old_price:
                diff = round(new_price - old_price, 2)
                pct = round((diff / old_price) * 100, 1) if old_price > 0 else 0.0
                hikes_count += 1
                cur.execute("""
                    INSERT INTO flipkart_changes 
                    (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                    VALUES (?, ?, ?, ?, 'PRICE_HIKE', ?, ?, ?, ?, ?, ?)
                """, (snapshot_id, now_iso, pid, p_name, f"₹{old_price:,.0f}", f"₹{new_price:,.0f}", diff, pct, p_url, p_img))
                changes_recorded.append({"type": "PRICE_HIKE", "pid": pid, "name": p_name, "old": old_price, "new": new_price, "diff": diff, "pct": pct})
            elif new_price < old_price:
                diff = round(old_price - new_price, 2)
                pct = round((diff / old_price) * 100, 1) if old_price > 0 else 0.0
                drops_count += 1
                cur.execute("""
                    INSERT INTO flipkart_changes 
                    (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                    VALUES (?, ?, ?, ?, 'PRICE_DROP', ?, ?, ?, ?, ?, ?)
                """, (snapshot_id, now_iso, pid, p_name, f"₹{old_price:,.0f}", f"₹{new_price:,.0f}", -diff, pct, p_url, p_img))
                changes_recorded.append({"type": "PRICE_DROP", "pid": pid, "name": p_name, "old": old_price, "new": new_price, "diff": -diff, "pct": pct})

            # 2. Stock analysis
            if old_stock == 1 and new_stock == 0:
                oos_count += 1
                cur.execute("""
                    INSERT INTO flipkart_changes 
                    (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                    VALUES (?, ?, ?, ?, 'OUT_OF_STOCK', 'In Stock', 'Out of Stock', 0, 0, ?, ?)
                """, (snapshot_id, now_iso, pid, p_name, p_url, p_img))
                changes_recorded.append({"type": "OUT_OF_STOCK", "pid": pid, "name": p_name})
            elif old_stock == 0 and new_stock == 1:
                back_count += 1
                cur.execute("""
                    INSERT INTO flipkart_changes 
                    (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                    VALUES (?, ?, ?, ?, 'BACK_IN_STOCK', 'Out of Stock', 'Back In Stock', 0, 0, ?, ?)
                """, (snapshot_id, now_iso, pid, p_name, p_url, p_img))
                changes_recorded.append({"type": "BACK_IN_STOCK", "pid": pid, "name": p_name})

        else:
            # If not in previous snapshot and previous snapshot existed -> NEW_LISTING
            if prev_items:
                new_count += 1
                cur.execute("""
                    INSERT INTO flipkart_changes 
                    (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                    VALUES (?, ?, ?, ?, 'NEW_LISTING', 'Not in Catalog', ?, 0, 0, ?, ?)
                """, (snapshot_id, now_iso, pid, p_name, f"Listed at ₹{new_price:,.0f}", p_url, p_img))
                changes_recorded.append({"type": "NEW_LISTING", "pid": pid, "name": p_name, "price": new_price})

        # Also detect if product explicitly marked out of stock in current json
        if not p.get("in_stock", True) and pid not in prev_items:
            oos_count += 1
            cur.execute("""
                INSERT INTO flipkart_changes 
                (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                VALUES (?, ?, ?, ?, 'OUT_OF_STOCK', 'Unknown', 'Out of Stock', 0, 0, ?, ?)
            """, (snapshot_id, now_iso, pid, p_name, p_url, p_img))

    # B. Delisted analysis (present in prev_items but absent in curr_map)
    if prev_items:
        for prev_pid, prev in prev_items.items():
            if prev_pid not in curr_map:
                delisted_count += 1
                prev_name = prev.get("name") or "Spice Nest Product"
                prev_price = float(prev.get("price") or 0.0)
                cur.execute("""
                    INSERT INTO flipkart_changes 
                    (snapshot_id, detected_at, product_id, name, change_type, old_value, new_value, diff_amount, pct_change, product_url, image_url)
                    VALUES (?, ?, ?, ?, 'DELISTED', ?, 'Delisted / Removed from Store', 0, 0, ?, ?)
                """, (snapshot_id, now_iso, prev_pid, prev_name, f"Was ₹{prev_price:,.0f}", prev.get("product_url", ""), prev.get("image_url", "")))
                changes_recorded.append({"type": "DELISTED", "pid": prev_pid, "name": prev_name})
                # Mark as out of stock / delisted in flipkart_catalog
                cur.execute("UPDATE flipkart_catalog SET in_stock = 0 WHERE product_id = ?", (prev_pid,))

    # C. Save the new snapshot
    for p in parsed_items:
        cur.execute("""
            INSERT INTO flipkart_snapshots 
            (snapshot_id, snapshot_date, product_id, name, price, mrp, rating, review_count, in_stock, product_url, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id, now_iso, p["product_id"], p["name"], float(p["price"]),
            float(p.get("mrp") or p["price"]), float(p.get("rating") or 4.1),
            int(p.get("review_count") or 50), 1 if p.get("in_stock", True) else 0,
            p.get("product_url", ""), p.get("image_url", "")
        ))

    return {
        "snapshot_id": snapshot_id,
        "total_items": len(parsed_items),
        "price_hikes": hikes_count,
        "price_drops": drops_count,
        "out_of_stock": oos_count,
        "back_in_stock": back_count,
        "delisted": delisted_count,
        "new_listings": new_count,
        "changes": changes_recorded
    }


def get_flipkart_delta_analytics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Returns the latest Flipkart changes, price movements, delisted items and snapshot stats."""
    init_flipkart_snapshot_db(conn)
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM flipkart_changes 
        ORDER BY detected_at DESC, id DESC 
        LIMIT 150
    """)
    changes = [dict(r) for r in cur.fetchall()]

    hikes = [c for c in changes if c.get("change_type") == "PRICE_HIKE"]
    drops = [c for c in changes if c.get("change_type") == "PRICE_DROP"]
    oos = [c for c in changes if c.get("change_type") == "OUT_OF_STOCK"]
    delisted = [c for c in changes if c.get("change_type") == "DELISTED"]
    new_skus = [c for c in changes if c.get("change_type") == "NEW_LISTING"]
    back_in = [c for c in changes if c.get("change_type") == "BACK_IN_STOCK"]

    cur.execute("""
        SELECT count(DISTINCT snapshot_id), max(snapshot_date) 
        FROM flipkart_snapshots
    """)
    snap_stats = cur.fetchone()

    total_snapshots = snap_stats[0] if snap_stats and snap_stats[0] else 0
    latest_snapshot_date = snap_stats[1] if snap_stats and snap_stats[1] else None

    return {
        "changes_items": changes,
        "price_hikes": hikes,
        "price_drops": drops,
        "out_of_stock": oos,
        "delisted": delisted,
        "new_skus": new_skus,
        "back_in_stock": back_in,
        "summary": {
            "price_hikes_count": len(hikes),
            "price_drops_count": len(drops),
            "out_of_stock_count": len(oos),
            "delisted_count": len(delisted),
            "new_skus_count": len(new_skus),
            "back_in_stock_count": len(back_in),
            "total_snapshots": total_snapshots,
            "latest_snapshot_date": latest_snapshot_date
        }
    }
