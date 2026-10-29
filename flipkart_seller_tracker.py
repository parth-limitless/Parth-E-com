"""Flipkart Marketplace Seller API - Automated Tracking, P&L & Power BI Sync Engine
----------------------------------------------------------------------------------
Features:
1. OAuth 2.0 Self-Access Authentication (Client Credentials Flow with Auto-Renewal)
2. Shipment Filter API Integration (Pagination, Orders, Tracking)
3. Unit-Level P&L and Returns Tracking (RTO vs Customer Returns)
4. SQLite Database Persistence & Power BI Ready CSV Export
5. Built-in Simulation Mode for instant testing without live API keys
"""

import os
import sys
import json
import time
import base64
import sqlite3
import datetime as dt
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse
import urllib.error

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ------------------------------------------------------------------------------
# Configuration & Endpoints
# ------------------------------------------------------------------------------
FLIPKART_AUTH_URL = "https://api.flipkart.net/oauth-service/oauth/token"
FLIPKART_SHIPMENT_FILTER_URL = "https://api.flipkart.net/sellers/v3/shipments/filter"
FLIPKART_RETURNS_URL = "https://api.flipkart.net/sellers/v3/returns"

# Secure Credentials (Set via environment variables or .env file)
CLIENT_ID = os.environ.get("FLIPKART_APP_ID", "YOUR_FLIPKART_CLIENT_ID")
CLIENT_SECRET = os.environ.get("FLIPKART_APP_SECRET", "YOUR_FLIPKART_CLIENT_SECRET")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flipkart_seller.db")
POWERBI_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flipkart_orders_pnl_powerbi.csv")

# Estimated Flipkart Marketplace fee percentage if exact settlement is pending (~22%)
DEFAULT_MARKETPLACE_FEE_PCT = 0.22
RTO_REVERSE_SHIPPING_LOSS = 65.0  # Average courier penalty for RTO
CUSTOMER_RETURN_DAMAGE_LOSS = 140.0  # Average packaging/refurbishing penalty for customer return


# ------------------------------------------------------------------------------
# 1. Database Management (SQLite & Power BI Export)
# ------------------------------------------------------------------------------
class FlipkartDatabaseManager:
    """Manages local SQLite database schema, upserts, and Power BI CSV exports."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
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

            # Seed default spice unit manufacturing costs if empty
            count = conn.execute("SELECT count(*) FROM sku_costs").fetchone()[0]
            if count == 0:
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

    def get_sku_cost_map(self) -> Dict[str, Dict[str, float]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM sku_costs").fetchall()
            return {
                r["sku"]: {
                    "unit_cost": float(r["unit_cost"]),
                    "packaging_cost": float(r["packaging_cost"])
                }
                for r in rows
            }

    def upsert_orders(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        with self.get_connection() as conn:
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
            """, records)
            conn.commit()
        return len(records)

    def export_powerbi_csv(self, filepath: str = POWERBI_CSV_PATH) -> str:
        """Exports sanitized dataset optimized for direct Power BI drag-and-drop dashboards."""
        import csv
        with self.get_connection() as conn:
            cursor = conn.execute("""
            SELECT 
                order_item_id,
                order_id,
                order_date,
                strftime('%Y-%m', order_date) as order_month,
                strftime('%Y-%W', order_date) as order_week,
                sku,
                title,
                quantity,
                selling_price,
                total_revenue,
                item_unit_cost,
                total_cogs,
                marketplace_fee,
                shipping_penalty,
                net_pnl,
                pnl_status,
                shipment_status,
                return_type,
                last_synced_at
            FROM flipkart_orders
            ORDER BY order_date DESC
            """)
            rows = cursor.fetchall()

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([
                "Order Item ID", "Order ID", "Order Date", "Order Month", "Order Week",
                "SKU", "Product Title", "Quantity", "Selling Price (Rs)", "Total Revenue (Rs)",
                "Unit Cost (Rs)", "Total COGS (Rs)", "Marketplace Fee (Rs)", "Return/Shipping Penalty (Rs)",
                "Net Profit Loss (Rs)", "P&L Status", "Shipment Status", "Return Category", "Last Synced At"
            ])
            for r in rows:
                w.writerow(list(r))
        return filepath


# ------------------------------------------------------------------------------
# 2. Flipkart Marketplace Client (OAuth 2.0 & API Engine)
# ------------------------------------------------------------------------------
class FlipkartSellerClient:
    """Handles OAuth 2.0 Client Credentials flow, token caching, API calls, and error handling."""

    def __init__(self, client_id: str = CLIENT_ID, client_secret: str = CLIENT_SECRET):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0.0

    def is_configured(self) -> bool:
        return (
            bool(self.client_id) and 
            bool(self.client_secret) and 
            "YOUR_FLIPKART" not in self.client_id
        )

    def get_access_token(self) -> str:
        """Generates or auto-renews OAuth 2.0 Bearer Token using Client Credentials Flow."""
        # Check token validity with 300s buffer before expiration
        if self.access_token and time.time() < (self.token_expiry - 300):
            return self.access_token

        print("[Flipkart Auth] Requesting new OAuth Access Token from Flipkart...")
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
                print(f"[Flipkart Auth] Token successfully acquired! Valid for {expires_in} seconds.")
                return self.access_token
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Flipkart OAuth failed (HTTP {e.code}): {error_body}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Flipkart OAuth service: {e}")

    def fetch_shipments_live(self, from_date: dt.datetime, to_date: dt.datetime, page_size: int = 50) -> List[Dict[str, Any]]:
        """Calls Flipkart Shipment Filter API with automatic pagination handling."""
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Flipkart expects ISO-8601 UTC timestamp format: YYYY-MM-DDTHH:MM:SSZ
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
            "pagination": {
                "pageSize": page_size
            }
        }

        all_shipments = []
        next_url = FLIPKART_SHIPMENT_FILTER_URL

        while next_url:
            print(f"[Flipkart API] Querying shipments from: {next_url}")
            body_bytes = json.dumps(payload).encode("utf-8") if next_url == FLIPKART_SHIPMENT_FILTER_URL else None
            req = urllib.request.Request(
                next_url,
                data=body_bytes,
                headers=headers,
                method="POST" if next_url == FLIPKART_SHIPMENT_FILTER_URL else "GET"
            )

            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    shipments = resp_data.get("shipments", [])
                    all_shipments.extend(shipments)
                    print(f"[Flipkart API] Fetched {len(shipments)} shipments (Total accumulated: {len(all_shipments)})")

                    has_more = resp_data.get("hasMore", False)
                    next_url = resp_data.get("nextPageUrl") if has_more else None

                    # Respect Flipkart rate limits (cooldown between pages)
                    if next_url:
                        time.sleep(1.2)
            except urllib.error.HTTPError as e:
                err_content = e.read().decode("utf-8", errors="replace")
                print(f"[Flipkart API Error] HTTP {e.code}: {err_content}")
                break
            except Exception as e:
                print(f"[Flipkart API Error] Connection issue: {e}")
                break

        return all_shipments


# ------------------------------------------------------------------------------
# 3. P&L & Returns Transformation Engine
# ------------------------------------------------------------------------------
def process_shipments_to_pnl(shipments: List[Dict[str, Any]], sku_cost_map: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Transforms raw Flipkart shipment records into unit-level financial P&L records."""
    processed_records = []
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for s in shipments:
        shipment_id = s.get("shipmentId", "")
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

            # Price components from Flipkart payload
            price_comps = item.get("priceComponents", {})
            selling_price = float(price_comps.get("sellingPrice", item.get("price", 0.0)))
            total_revenue = selling_price * qty

            # Look up product manufacturing cost (COGS)
            cost_info = sku_cost_map.get(sku, {"unit_cost": round(selling_price * 0.45, 1), "packaging_cost": 15.0})
            unit_cogs = cost_info["unit_cost"] + cost_info["packaging_cost"]
            total_cogs = unit_cogs * qty

            # Detect Return Type (RTO vs Customer Return)
            return_type = "NONE"
            shipping_penalty = 0.0

            sub_status = str(item.get("subStatus", "")).upper()
            if "RTO" in status or "RTO" in sub_status or "COURIER_RETURN" in status:
                return_type = "RTO (Courier Return)"
                # In RTO: product returns to warehouse, but courier reverse shipping & packaging are lost
                shipping_penalty = RTO_REVERSE_SHIPPING_LOSS * qty
                marketplace_fee = 0.0  # Flipkart usually refunds commission on RTO
                net_pnl = round(-shipping_penalty, 2)
            elif "RETURN" in status or "REFUND" in status or "RETURNED" in status:
                return_type = "Customer Return"
                # Customer Return: Reverse shipping charged + packaging damaged/unsellable loss
                shipping_penalty = CUSTOMER_RETURN_DAMAGE_LOSS * qty
                marketplace_fee = round(total_revenue * 0.05, 2)  # Minor reverse closing fee
                net_pnl = round(- (shipping_penalty + marketplace_fee), 2)
            elif "CANCEL" in status:
                return_type = "Buyer Cancelled"
                shipping_penalty = 0.0
                marketplace_fee = 0.0
                net_pnl = 0.0
            else:
                # Successfully Dispatched / Delivered Order
                return_type = "NONE"
                marketplace_fee = round(total_revenue * DEFAULT_MARKETPLACE_FEE_PCT, 2)
                shipping_penalty = 0.0
                # Net Profit = Revenue - Marketplace Commission - COGS
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


# ------------------------------------------------------------------------------
# 4. Realistic Sandbox Simulator (For Immediate Testing without Live API Keys)
# ------------------------------------------------------------------------------
def generate_simulated_flipkart_shipments(num_orders: int = 40) -> List[Dict[str, Any]]:
    """Generates authentic Flipkart Seller API JSON payload for testing and Power BI demo."""
    import random
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
        days_ago = random.randint(0, 45)
        order_time = now - dt.timedelta(days=days_ago, hours=random.randint(1, 23))
        sku, title, price = random.choice(skus)
        qty = random.choice([1, 1, 1, 2, 3])

        # Realistic status distribution: 75% Delivered, 12% RTO, 8% Customer Return, 5% Dispatched
        roll = random.random()
        if roll < 0.75:
            status = "DELIVERED"
            sub_status = "DELIVERED_TO_BUYER"
        elif roll < 0.87:
            status = "RETURNED"
            sub_status = "RTO_DELIVERED_TO_SELLER"
        elif roll < 0.95:
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


# ------------------------------------------------------------------------------
# 5. Main Execution & CLI Pipeline
# ------------------------------------------------------------------------------
def run_flipkart_tracker():
    print("=" * 70)
    print("🌶️  Flipkart Marketplace Seller Tracker & P&L Automation Engine")
    print("=" * 70)

    db_manager = FlipkartDatabaseManager(DB_PATH)
    client = FlipkartSellerClient(CLIENT_ID, CLIENT_SECRET)
    sku_cost_map = db_manager.get_sku_cost_map()

    if client.is_configured():
        print("🔐 Live Flipkart API Credentials detected. Fetching live orders from seller portal...")
        from_date = dt.datetime.now() - dt.timedelta(days=30)
        to_date = dt.datetime.now()
        shipments = client.fetch_shipments_live(from_date, to_date)
    else:
        print("⚠️  Live FLIPKART_APP_ID / SECRET not set in environment.")
        print("💡 Running in Simulation / Demo Mode (Generating 40 realistic sample orders)...")
        shipments = generate_simulated_flipkart_shipments(num_orders=45)

    print(f"\nProcessing {len(shipments)} shipments through P&L Calculation Engine...")
    processed_orders = process_shipments_to_pnl(shipments, sku_cost_map)

    # Save to SQLite Database
    inserted = db_manager.upsert_orders(processed_orders)
    print(f"✅ Successfully updated {inserted} order records in SQLite: {DB_PATH}")

    # Export to Power BI CSV
    csv_file = db_manager.export_powerbi_csv(POWERBI_CSV_PATH)
    print(f"📊 Exported clean Power BI CSV dataset: {csv_file}")

    # Display Executive Summary
    total_rev = sum(o["total_revenue"] for o in processed_orders)
    total_cogs = sum(o["total_cogs"] for o in processed_orders)
    total_fees = sum(o["marketplace_fee"] for o in processed_orders)
    total_penalties = sum(o["shipping_penalty"] for o in processed_orders)
    net_profit = sum(o["net_pnl"] for o in processed_orders)

    delivered_count = sum(1 for o in processed_orders if o["shipment_status"] == "DELIVERED")
    rto_count = sum(1 for o in processed_orders if "RTO" in o["return_type"])
    return_count = sum(1 for o in processed_orders if "Customer" in o["return_type"])

    print("\n📈 --- FLIPKART FINANCIAL SUMMARY ---")
    print(f"Total Processed Orders : {len(processed_orders)}")
    print(f"Delivered Successfully : {delivered_count} ({round(delivered_count/len(processed_orders)*100, 1)}%)")
    print(f"RTO (Courier Returns)  : {rto_count} (Loss: ₹{rto_count * RTO_REVERSE_SHIPPING_LOSS:,.0f})")
    print(f"Customer Returns       : {return_count} (Loss: ₹{return_count * CUSTOMER_RETURN_DAMAGE_LOSS:,.0f})")
    print(f"Gross Revenue          : ₹{total_rev:,.2f}")
    print(f"Total COGS (Product)   : ₹{total_cogs:,.2f}")
    print(f"Marketplace Comm./Fees : ₹{total_fees:,.2f}")
    print(f"Reverse Shipping Loss  : ₹{total_penalties:,.2f}")
    print("-" * 50)
    profit_icon = "🟢" if net_profit > 0 else "🔴"
    print(f"{profit_icon} NET PROFIT / LOSS     : ₹{net_profit:,.2f} (Margin: {round(net_profit/total_rev*100, 1) if total_rev else 0}%)")
    print("=" * 70)


if __name__ == "__main__":
    run_flipkart_tracker()

