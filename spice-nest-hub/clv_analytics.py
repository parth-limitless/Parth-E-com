"""Spice Nest Hub - Customer Lifetime Value (CLV) & Customer Segmentation Engine
Calculates RFM metrics, predicts future purchases & CLV using BG-NBD and Gamma-Gamma models,
and segments customers with actionable e-commerce retention strategies.
"""

import os
import sqlite3
import random
import datetime as dt
from typing import Dict, Any, List, Optional

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None
    np = None

try:
    from lifetimes import BetaGeoFitter, GammaGammaFitter
    from lifetimes.utils import summary_data_from_transaction_data
    HAS_LIFETIMES = True
except Exception:
    HAS_LIFETIMES = False
    BetaGeoFitter = None
    GammaGammaFitter = None
    summary_data_from_transaction_data = None


DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spicenest.db")


# -------------------------------------------------------------
# 1. Database Schema Initialization
# -------------------------------------------------------------
def init_clv_db(conn: Optional[sqlite3.Connection] = None, db_path: str = DEFAULT_DB_PATH) -> None:
    """Initializes the transactions table and indexes in SQLite."""
    close_after = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        close_after = True

    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            customer_name TEXT,
            order_date TEXT NOT NULL,
            order_value REAL NOT NULL,
            platform TEXT DEFAULT 'Direct',
            product_name TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_trans_cust ON transactions(customer_id);
        CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(order_date);
        """)
        conn.commit()
    finally:
        if close_after:
            conn.close()


# -------------------------------------------------------------
# 2. Realistic Mock Data Generator
# -------------------------------------------------------------
INDIAN_NAMES = [
    "Aarav Sharma", "Pooja Patel", "Rajesh Kumar", "Ananya Iyer", "Vikram Singh",
    "Sunita Verma", "Rohan Mehta", "Neha Gupta", "Kavita Reddy", "Deepak Joshi",
    "Priyanka Nair", "Amit Trivedi", "Siddharth Das", "Meera Pillai", "Arjun Bansal",
    "Sneha Rao", "Gaurav Malhotra", "Swati Chawla", "Aditya Sen", "Divya Deshmukh",
    "Karan Saxena", "Shreya Bhat", "Manoj Kulkarni", "Tanvi Sengupta", "Harish Nambiar",
    "Isha Kapoor", "Nikhil Chopra", "Ritu Agrawal", "Suresh Menon", "Bhavna Jain"
]

SPICE_PRODUCTS = [
    ("Kashmiri Lal Mirch (500g)", 420.0),
    ("Organic Salem Turmeric Powder (500g)", 290.0),
    ("Royal Shahi Garam Masala (250g)", 380.0),
    ("Whole Green Cardamom 8mm (100g)", 550.0),
    ("Jeera Whole Cumin Seeds (500g)", 340.0),
    ("Black Pepper Malabar Tellicherry (200g)", 460.0),
    ("Hyderabadi Biryani Special Masala (200g)", 260.0),
    ("Clove & Cinnamon Bakers Kit (150g)", 390.0),
    ("Organic Coriander Powder (500g)", 220.0),
    ("Guntur Chilli Whole Stemless (1kg)", 650.0)
]

CHANNELS = ["Amazon", "Flipkart", "Meesho", "Blinkit", "JioMart", "Direct Store"]


def seed_mock_transactions(db_path: str = DEFAULT_DB_PATH, num_customers: int = 75, clear_existing: bool = True) -> int:
    """Populates realistic transaction history spanning the past 365 days.
    
    Generates diverse customer segments:
    - High-Value Champions (many orders, high spend, recent)
    - Loyal Customers (consistent orders)
    - Potential Loyalists (2-3 recent orders)
    - At-Risk Customers (ordered often in the past, inactive recently)
    - Hibernating / Lost (one-off purchase long ago)
    - New Customers (single recent purchase)
    """
    init_clv_db(db_path=db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if clear_existing:
        cursor.execute("DELETE FROM transactions")

    now = dt.datetime.now()
    records = []
    order_counter = 10001

    for i in range(num_customers):
        cust_id = f"CUST-{100 + i:03d}"
        cust_name = INDIAN_NAMES[i % len(INDIAN_NAMES)]
        if i >= len(INDIAN_NAMES):
            cust_name += f" #{i // len(INDIAN_NAMES) + 1}"

        # Assign a customer archetype
        archetype_roll = random.random()

        if archetype_roll < 0.15:
            # 1. VIP / Champion: 6-11 orders, high value, recent
            num_orders = random.randint(6, 11)
            order_days_ago = sorted([random.randint(2, 25)] + [random.randint(26, 320) for _ in range(num_orders - 1)], reverse=True)
            spend_multiplier = random.uniform(1.8, 3.2)
        elif archetype_roll < 0.40:
            # 2. Loyal Repeat: 4-6 orders, moderate value, regular
            num_orders = random.randint(4, 6)
            order_days_ago = sorted([random.randint(10, 45)] + [random.randint(50, 340) for _ in range(num_orders - 1)], reverse=True)
            spend_multiplier = random.uniform(1.1, 1.8)
        elif archetype_roll < 0.60:
            # 3. Potential Loyalist: 2-3 orders recently placed
            num_orders = random.randint(2, 3)
            order_days_ago = sorted([random.randint(3, 40)] + [random.randint(45, 90) for _ in range(num_orders - 1)], reverse=True)
            spend_multiplier = random.uniform(1.0, 1.5)
        elif archetype_roll < 0.78:
            # 4. At-Risk: 3-5 orders in the past, but inactive for 90-250 days
            num_orders = random.randint(3, 5)
            order_days_ago = sorted([random.randint(95, 210)] + [random.randint(215, 360) for _ in range(num_orders - 1)], reverse=True)
            spend_multiplier = random.uniform(1.2, 2.0)
        elif archetype_roll < 0.90:
            # 5. Hibernating / Lost: 1-2 orders, 200+ days ago
            num_orders = random.choice([1, 2])
            order_days_ago = sorted([random.randint(200, 360) for _ in range(num_orders)], reverse=True)
            spend_multiplier = random.uniform(0.8, 1.2)
        else:
            # 6. New Customer: 1 order, past 3-20 days
            num_orders = 1
            order_days_ago = [random.randint(3, 20)]
            spend_multiplier = random.uniform(0.9, 1.6)

        preferred_channel = random.choice(CHANNELS)

        for days_ago in order_days_ago:
            order_date = now - dt.timedelta(days=days_ago, hours=random.randint(1, 23), minutes=random.randint(0, 59))
            product, base_price = random.choice(SPICE_PRODUCTS)
            # Basket may contain 1-3 items
            quantity = random.randint(1, 3)
            order_val = round(base_price * quantity * spend_multiplier, 2)
            channel = preferred_channel if random.random() > 0.3 else random.choice(CHANNELS)

            records.append((
                f"ORD-{order_counter}",
                cust_id,
                cust_name,
                order_date.strftime("%Y-%m-%d %H:%M:%S"),
                order_val,
                channel,
                product
            ))
            order_counter += 1

    cursor.executemany("""
    INSERT OR REPLACE INTO transactions (order_id, customer_id, customer_name, order_date, order_value, platform, product_name)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, records)

    conn.commit()
    conn.close()
    return len(records)


# -------------------------------------------------------------
# 3. Customer Segmentation Logic
# -------------------------------------------------------------
def assign_segment(r_score: int, f_score: int, m_score: int, p_alive: float, recency_days: int, frequency: int) -> Dict[str, str]:
    """Classifies customer into business segment with color tags and actionable retention advice."""
    rfm_composite = (r_score * 0.35) + (f_score * 0.35) + (m_score * 0.30)

    if (r_score >= 4 and f_score >= 4) or (rfm_composite >= 4.2 and p_alive >= 0.70):
        return {
            "name": "Champions (VIP)",
            "badge_class": "badge-champion",
            "icon": "🌟",
            "action": "Offer VIP perks, exclusive previews of rare spices, and priority express shipping.",
            "color": "#10b981"
        }
    elif f_score >= 3 and r_score >= 3:
        return {
            "name": "Loyal Customers",
            "badge_class": "badge-loyal",
            "icon": "💎",
            "action": "Cross-sell organic combos, offer loyalty points multiplier, and solicit product reviews.",
            "color": "#3b82f6"
        }
    elif r_score >= 4 and frequency in (2, 3):
        return {
            "name": "Potential Loyalists",
            "badge_class": "badge-potential",
            "icon": "🚀",
            "action": "Recommend spice refill subscriptions and offer bundle discounts to build buying habit.",
            "color": "#8b5cf6"
        }
    elif frequency == 1 and recency_days <= 45:
        return {
            "name": "New Customers",
            "badge_class": "badge-new",
            "icon": "🌱",
            "action": "Send onboarding recipe guide and a ₹100 welcome voucher for their 2nd purchase.",
            "color": "#06b6d4"
        }
    elif (recency_days > 75 and frequency >= 2) or (p_alive < 0.40 and frequency >= 2):
        return {
            "name": "At-Risk Customers",
            "badge_class": "badge-atrisk",
            "icon": "⚠️",
            "action": "Urgent win-back trigger: send ₹150 discount coupon and a personalized 'We Miss You' message.",
            "color": "#f59e0b"
        }
    else:
        return {
            "name": "Hibernating / Lost",
            "badge_class": "badge-lost",
            "icon": "💤",
            "action": "Run low-cost automated re-activation campaigns around major festivals (Diwali, Eid, Holi).",
            "color": "#ef4444"
        }


# -------------------------------------------------------------
# 4. Month-Wise Platform Order Analytics
# -------------------------------------------------------------
def get_month_wise_platform_analytics(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Computes month-wise total orders and revenue breakdown across all platforms."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    platforms = ["Flipkart", "Amazon", "Meesho", "Blinkit", "JioMart", "Direct Store"]

    try:
        q = """
        SELECT 
            strftime('%Y-%m', order_date) as month_code,
            platform,
            count(*) as orders,
            sum(order_value) as revenue
        FROM transactions
        WHERE order_date IS NOT NULL AND order_date != ''
        GROUP BY month_code, platform
        ORDER BY month_code DESC
        """
        rows = conn.execute(q).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    months_dict = {}
    platform_totals = {p: {"orders": 0, "revenue": 0.0} for p in platforms}

    for r in rows:
        m_code = r["month_code"]
        if not m_code:
            continue
        if m_code not in months_dict:
            try:
                m_dt = dt.datetime.strptime(m_code, "%Y-%m")
                label = m_dt.strftime("%B %Y")
                short_label = m_dt.strftime("%b %y")
            except Exception:
                label = m_code
                short_label = m_code
            months_dict[m_code] = {
                "month_code": m_code,
                "label": label,
                "short_label": short_label,
                "platforms": {p: {"orders": 0, "revenue": 0.0} for p in platforms},
                "total_orders": 0,
                "total_revenue": 0.0,
                "top_platform": "-",
                "top_platform_orders": 0
            }

        p = r["platform"] or "Direct Store"
        if p not in platforms:
            p = "Direct Store"
        orders = int(r["orders"])
        rev = round(float(r["revenue"] or 0.0), 1)

        months_dict[m_code]["platforms"][p]["orders"] += orders
        months_dict[m_code]["platforms"][p]["revenue"] = round(months_dict[m_code]["platforms"][p]["revenue"] + rev, 1)
        months_dict[m_code]["total_orders"] += orders
        months_dict[m_code]["total_revenue"] = round(months_dict[m_code]["total_revenue"] + rev, 1)

        platform_totals[p]["orders"] += orders
        platform_totals[p]["revenue"] = round(platform_totals[p]["revenue"] + rev, 1)

    for m_code, mdata in months_dict.items():
        top_p = max(platforms, key=lambda p: mdata["platforms"][p]["orders"])
        if mdata["platforms"][top_p]["orders"] > 0:
            mdata["top_platform"] = top_p
            mdata["top_platform_orders"] = mdata["platforms"][top_p]["orders"]

    months_desc = [months_dict[k] for k in sorted(months_dict.keys(), reverse=True)]
    months_asc = [months_dict[k] for k in sorted(months_dict.keys())]

    chart_labels = [m["short_label"] for m in months_asc]
    platform_colors = {
        "Flipkart": "#2874f0",
        "Amazon": "#ff9900",
        "Meesho": "#ec4899",
        "Blinkit": "#eab308",
        "JioMart": "#06b6d4",
        "Direct Store": "#10b981"
    }

    chart_order_datasets = []
    chart_revenue_datasets = []
    for p in platforms:
        chart_order_datasets.append({
            "label": p,
            "data": [m["platforms"][p]["orders"] for m in months_asc],
            "backgroundColor": platform_colors[p],
            "borderColor": platform_colors[p],
            "borderRadius": 4
        })
        chart_revenue_datasets.append({
            "label": p,
            "data": [m["platforms"][p]["revenue"] for m in months_asc],
            "backgroundColor": platform_colors[p],
            "borderColor": platform_colors[p],
            "borderRadius": 4
        })

    grand_total_orders = sum(platform_totals[p]["orders"] for p in platforms)
    grand_total_revenue = round(sum(platform_totals[p]["revenue"] for p in platforms), 1)

    return {
        "platforms": platforms,
        "platform_colors": platform_colors,
        "platform_totals": platform_totals,
        "grand_total_orders": grand_total_orders,
        "grand_total_revenue": grand_total_revenue,
        "months_list": months_desc,
        "chart_labels": chart_labels,
        "chart_order_datasets": chart_order_datasets,
        "chart_revenue_datasets": chart_revenue_datasets
    }


# -------------------------------------------------------------
# 5. RFM & CLV Analysis Pipeline
# -------------------------------------------------------------
def _analyze_with_pure_python(db_path: str, prediction_days: int = 30, clv_months: int = 12) -> Dict[str, Any]:
    """Pure Python fallback for RFM & CLV when Pandas/Lifetimes DLLs are unavailable."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM transactions ORDER BY order_date ASC").fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "total_customers": 0,
            "total_orders": 0,
            "total_revenue": 0.0,
            "avg_clv": 0.0,
            "pred_30d_revenue": 0.0,
            "customers": [],
            "segments_summary": {},
            "chart_data": {"labels": [], "counts": [], "clv": [], "colors": []},
            "model_status": "No transaction data found. Click 'Seed Sample Transactions' to start."
        }

    from collections import defaultdict
    cust_data = defaultdict(lambda: {"orders": [], "name": "", "platforms": defaultdict(int)})

    for r in rows:
        cid = r["customer_id"]
        try:
            odate = dt.datetime.strptime(r["order_date"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            odate = dt.datetime.now()
        val = float(r["order_value"] or 0.0)
        cust_data[cid]["orders"].append({"date": odate, "value": val})
        cust_data[cid]["name"] = r["customer_name"] or cid
        cust_data[cid]["platforms"][r["platform"] or "Direct"] += 1

    now = max(max(o["date"] for o in c["orders"]) for c in cust_data.values()) + dt.timedelta(days=1)

    customer_list = []
    for cid, cinfo in cust_data.items():
        orders = cinfo["orders"]
        total_orders = len(orders)
        total_spend = sum(o["value"] for o in orders)
        avg_basket = total_spend / total_orders if total_orders > 0 else 0.0
        first_date = min(o["date"] for o in orders)
        last_date = max(o["date"] for o in orders)
        recency_days = max(0, (now - last_date).days)
        age_days = max(1, (now - first_date).days)

        # Primary platform
        pref_platform = max(cinfo["platforms"].items(), key=lambda x: x[1])[0]

        # Scoring heuristics
        r_score = 5 if recency_days <= 25 else (4 if recency_days <= 50 else (3 if recency_days <= 90 else (2 if recency_days <= 180 else 1)))
        f_score = 5 if total_orders >= 7 else (4 if total_orders >= 5 else (3 if total_orders >= 3 else (2 if total_orders >= 2 else 1)))
        m_score = 5 if total_spend >= 4500 else (4 if total_spend >= 2500 else (3 if total_spend >= 1200 else (2 if total_spend >= 600 else 1)))

        # BG-NBD Analytical Probability of being Alive: P(Alive)
        recency_ratio = recency_days / max(float(age_days), 30.0)
        p_alive = max(0.05, min(0.99, 1.0 - recency_ratio))

        # Expected repeat purchases in next 30 days
        monthly_rate = total_orders / max(age_days / 30.0, 1.0)
        pred_orders_30d = round(monthly_rate * p_alive, 2)

        # Projected 12-Month CLV (orders expected over 1 year * AOV * standard 25% gross margin)
        predicted_clv_12m = round(pred_orders_30d * 12.0 * avg_basket * 0.25, 1)

        seg = assign_segment(r_score, f_score, m_score, p_alive, recency_days, total_orders)

        # Unique months and platforms for filtering
        c_months = list(set(o["date"].strftime("%Y-%m") for o in orders))
        c_platforms = list(cinfo["platforms"].keys())

        customer_list.append({
            "customer_id": cid,
            "customer_name": cinfo["name"],
            "total_orders": total_orders,
            "total_spend": round(total_spend, 1),
            "avg_order_value": round(avg_basket, 1),
            "recency_days": recency_days,
            "last_order_date": last_date.strftime("%Y-%m-%d"),
            "last_order_month": last_date.strftime("%B %Y"),
            "order_months": c_months,
            "all_platforms": c_platforms,
            "r_score": r_score,
            "f_score": f_score,
            "m_score": m_score,
            "p_alive_pct": round(p_alive * 100, 1),
            "pred_purchases_30d": pred_orders_30d,
            "predicted_clv_12m": predicted_clv_12m,
            "primary_platform": pref_platform,
            "segment": seg["name"],
            "segment_badge": seg["badge_class"],
            "segment_icon": seg["icon"],
            "segment_action": seg["action"],
            "segment_color": seg["color"]
        })

    customer_list.sort(key=lambda x: x["predicted_clv_12m"], reverse=True)

    # Distinct months across all orders
    all_months_map = {}
    for r in rows:
        try:
            m_code = r["order_date"][:7] # e.g. 2026-10
            if m_code not in all_months_map:
                m_dt = dt.datetime.strptime(m_code, "%Y-%m")
                all_months_map[m_code] = m_dt.strftime("%B %Y")
        except Exception:
            pass
    available_months = [{"value": k, "label": all_months_map[k]} for k in sorted(all_months_map.keys(), reverse=True)]
    available_platforms = ["Meesho", "Flipkart", "Amazon", "Blinkit", "JioMart", "Direct Store"]

    # Segment Aggregation
    seg_summary = {}
    for c in customer_list:
        s_name = c["segment"]
        if s_name not in seg_summary:
            seg_summary[s_name] = {
                "name": s_name,
                "icon": c["segment_icon"],
                "color": c["segment_color"],
                "badge": c["segment_badge"],
                "action": c["segment_action"],
                "count": 0,
                "total_spend": 0.0,
                "total_clv_12m": 0.0,
                "p_alive_sum": 0.0
            }
        seg_summary[s_name]["count"] += 1
        seg_summary[s_name]["total_spend"] += c["total_spend"]
        seg_summary[s_name]["total_clv_12m"] += c["predicted_clv_12m"]
        seg_summary[s_name]["p_alive_sum"] += c["p_alive_pct"]

    for s_name, data in seg_summary.items():
        data["avg_spend"] = round(data["total_spend"] / data["count"], 1) if data["count"] > 0 else 0
        data["avg_clv"] = round(data["total_clv_12m"] / data["count"], 1) if data["count"] > 0 else 0
        data["avg_p_alive"] = round(data["p_alive_sum"] / data["count"], 1) if data["count"] > 0 else 0
        data["pct_of_customers"] = round((data["count"] / len(customer_list)) * 100, 1)

    tot_cust = len(customer_list)
    tot_orders = len(rows)
    tot_rev = round(sum(c["total_spend"] for c in customer_list), 1)
    avg_clv = round(sum(c["predicted_clv_12m"] for c in customer_list) / tot_cust, 1) if tot_cust > 0 else 0.0
    pred_30d_rev = round(sum(c["pred_purchases_30d"] * c["avg_order_value"] for c in customer_list), 1)

    chart_labels = list(seg_summary.keys())
    chart_counts = [seg_summary[k]["count"] for k in chart_labels]
    chart_clv = [round(seg_summary[k]["total_clv_12m"], 1) for k in chart_labels]
    chart_colors = [seg_summary[k]["color"] for k in chart_labels]

    return {
        "total_customers": tot_cust,
        "total_orders": tot_orders,
        "total_revenue": tot_rev,
        "avg_clv": avg_clv,
        "pred_30d_revenue": pred_30d_rev,
        "customers": customer_list,
        "segments_summary": seg_summary,
        "chart_data": {
            "labels": chart_labels,
            "counts": chart_counts,
            "clv": chart_clv,
            "colors": chart_colors
        },
        "available_months": available_months,
        "available_platforms": available_platforms,
        "monthly_platforms": get_month_wise_platform_analytics(db_path),
        "model_status": "Analytical RFM & Poisson / BG-NBD Baseline Active 🛡️ (Zero External Dependencies)"
    }


def analyze_customer_clv(db_path: str = DEFAULT_DB_PATH, prediction_days: int = 30, clv_months: int = 12, discount_rate: float = 0.01) -> Dict[str, Any]:
    """Runs complete end-to-end RFM metrics, BG-NBD, Gamma-Gamma models,
    and returns rich analytical summary dictionary.
    """
    if not HAS_PANDAS:
        return _analyze_with_pure_python(db_path, prediction_days, clv_months)

    init_clv_db(db_path=db_path)
    conn = sqlite3.connect(db_path)

    try:
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
    finally:
        conn.close()

    if df.empty:
        return {
            "total_customers": 0,
            "total_orders": 0,
            "total_revenue": 0.0,
            "avg_clv": 0.0,
            "customers": [],
            "segments_summary": {},
            "model_status": "No transaction data found in database. Click 'Seed Mock Transactions' to initialize."
        }

    # Format dates and sort
    df['order_date'] = pd.to_datetime(df['order_date'])
    df['order_value'] = pd.to_numeric(df['order_value'], errors='coerce').fillna(0.0)

    now = df['order_date'].max() + pd.Timedelta(days=1)

    # 1. Traditional RFM Aggregation per Customer
    cust_group = df.groupby('customer_id')
    rfm_trad = cust_group.agg(
        customer_name=('customer_name', 'last'),
        total_orders=('order_id', 'count'),
        total_spend=('order_value', 'sum'),
        avg_order_value=('order_value', 'mean'),
        first_order=('order_date', 'min'),
        last_order=('order_date', 'max'),
        primary_platform=('platform', lambda s: s.mode().iloc[0] if not s.empty else 'Direct')
    ).reset_index()

    rfm_trad['recency_days'] = (now - rfm_trad['last_order']).dt.days
    rfm_trad['customer_age_days'] = (now - rfm_trad['first_order']).dt.days

    # Calculate 1-5 Scores for R, F, M
    # Higher recency_days = worse (lower score)
    try:
        rfm_trad['r_score'] = pd.qcut(rfm_trad['recency_days'].rank(method='first', ascending=False), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    except Exception:
        rfm_trad['r_score'] = rfm_trad['recency_days'].apply(lambda d: 5 if d <= 30 else (4 if d <= 60 else (3 if d <= 90 else (2 if d <= 180 else 1))))

    try:
        rfm_trad['f_score'] = pd.qcut(rfm_trad['total_orders'].rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    except Exception:
        rfm_trad['f_score'] = rfm_trad['total_orders'].apply(lambda f: 5 if f >= 6 else (4 if f >= 4 else (3 if f >= 3 else (2 if f >= 2 else 1))))

    try:
        rfm_trad['m_score'] = pd.qcut(rfm_trad['total_spend'].rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    except Exception:
        rfm_trad['m_score'] = rfm_trad['total_spend'].apply(lambda m: 5 if m >= 4000 else (4 if m >= 2000 else (3 if m >= 1000 else (2 if m >= 500 else 1))))

    # 2. Predictive Lifetimes Modeling (BG-NBD & Gamma-Gamma)
    lifetimes_available = HAS_LIFETIMES and (BetaGeoFitter is not None)
    model_notes = []

    # Initialize prediction columns with robust baseline fallback
    rfm_trad['p_alive'] = np.clip(1.0 - (rfm_trad['recency_days'] / np.maximum(rfm_trad['customer_age_days'], 30.0)), 0.05, 0.99)
    rfm_trad['pred_purchases_30d'] = np.round((rfm_trad['total_orders'] / np.maximum(rfm_trad['customer_age_days'] / 30.0, 1.0)) * rfm_trad['p_alive'], 2)
    rfm_trad['pred_avg_sales'] = rfm_trad['avg_order_value']
    # Estimated 12-month expected CLV (orders expected over 12m * avg order value * typical retail profit margin ~25%)
    rfm_trad['predicted_clv_12m'] = np.round(rfm_trad['pred_purchases_30d'] * 12.0 * rfm_trad['avg_order_value'] * 0.25, 1)

    if lifetimes_available:
        try:
            # Summary data in daily frequency for BG-NBD:
            # frequency = repeat purchases (total - 1)
            # recency = time between first and last order
            # T = customer age from first order to observation end
            lt_rfm = summary_data_from_transaction_data(
                df,
                customer_id_col='customer_id',
                datetime_col='order_date',
                monetary_value_col='order_value',
                observation_period_end=now,
                freq='D'
            )

            # Fit BG-NBD Model
            bgf = BetaGeoFitter(penalizer_coef=0.01)
            bgf.fit(lt_rfm['frequency'], lt_rfm['recency'], lt_rfm['T'])

            lt_rfm['lt_p_alive'] = bgf.conditional_probability_alive(lt_rfm['frequency'], lt_rfm['recency'], lt_rfm['T'])
            lt_rfm['lt_pred_orders'] = bgf.conditional_expected_number_of_purchases_up_to_time(
                prediction_days, lt_rfm['frequency'], lt_rfm['recency'], lt_rfm['T']
            )

            # Fit Gamma-Gamma Model on customers with at least 1 repeat purchase
            repeat_mask = (lt_rfm['frequency'] > 0) & (lt_rfm['monetary_value'] > 0)
            if repeat_mask.sum() >= 2:
                ggf = GammaGammaFitter(penalizer_coef=0.01)
                ggf.fit(lt_rfm.loc[repeat_mask, 'frequency'], lt_rfm.loc[repeat_mask, 'monetary_value'])

                # Expected average monetary value per transaction
                lt_rfm['lt_expected_avg_sales'] = ggf.conditional_expected_average_profit(
                    lt_rfm['frequency'], lt_rfm['monetary_value']
                )

                # 12-Month CLV projection (discount_rate monthly equivalent)
                clv_series = ggf.customer_lifetime_value(
                    bgf,
                    lt_rfm['frequency'],
                    lt_rfm['recency'],
                    lt_rfm['T'],
                    lt_rfm['monetary_value'],
                    time=clv_months,
                    freq='D',
                    discount_rate=discount_rate
                )
                lt_rfm['lt_clv_12m'] = clv_series
                model_notes.append("BG-NBD & Gamma-Gamma Fitted Successfully 🎯")
            else:
                model_notes.append("BG-NBD Fitted; Gamma-Gamma requires >= 2 repeat customers (fallback applied).")

            # Merge back into rfm_trad
            rfm_trad = rfm_trad.merge(
                lt_rfm[['lt_p_alive', 'lt_pred_orders'] + ([c for c in ['lt_expected_avg_sales', 'lt_clv_12m'] if c in lt_rfm.columns])],
                left_on='customer_id',
                right_index=True,
                how='left'
            )

            if 'lt_p_alive' in rfm_trad.columns:
                rfm_trad['p_alive'] = rfm_trad['lt_p_alive'].fillna(rfm_trad['p_alive'])
            if 'lt_pred_orders' in rfm_trad.columns:
                rfm_trad['pred_purchases_30d'] = np.round(rfm_trad['lt_pred_orders'].fillna(rfm_trad['pred_purchases_30d']), 2)
            if 'lt_clv_12m' in rfm_trad.columns:
                rfm_trad['predicted_clv_12m'] = np.round(rfm_trad['lt_clv_12m'].fillna(rfm_trad['predicted_clv_12m']), 1)
            if 'lt_expected_avg_sales' in rfm_trad.columns:
                rfm_trad['pred_avg_sales'] = np.round(rfm_trad['lt_expected_avg_sales'].fillna(rfm_trad['pred_avg_sales']), 1)

        except Exception as e:
            model_notes.append(f"Lifetimes fitting notice: {str(e)[:60]}... (Analytical model active)")
    else:
        model_notes.append("Lifetimes library not installed or numpy incompat. Using analytical RFM & Poisson baseline.")

    # 3. Apply Segmentation Engine
    segments_data = []
    for _, row in rfm_trad.iterrows():
        seg = assign_segment(
            r_score=int(row['r_score']),
            f_score=int(row['f_score']),
            m_score=int(row['m_score']),
            p_alive=float(row['p_alive']),
            recency_days=int(row['recency_days']),
            frequency=int(row['total_orders'])
        )
        segments_data.append(seg)

    rfm_trad['segment'] = [s['name'] for s in segments_data]
    rfm_trad['segment_badge'] = [s['badge_class'] for s in segments_data]
    rfm_trad['segment_icon'] = [s['icon'] for s in segments_data]
    rfm_trad['segment_action'] = [s['action'] for s in segments_data]
    rfm_trad['segment_color'] = [s['color'] for s in segments_data]

    # Convert to clean dicts for UI template
    rfm_trad = rfm_trad.sort_values(by='predicted_clv_12m', ascending=False)

    customers_list = []
    for _, row in rfm_trad.iterrows():
        customers_list.append({
            "customer_id": row['customer_id'],
            "customer_name": row['customer_name'],
            "total_orders": int(row['total_orders']),
            "total_spend": round(float(row['total_spend']), 1),
            "avg_order_value": round(float(row['avg_order_value']), 1),
            "recency_days": int(row['recency_days']),
            "r_score": int(row['r_score']),
            "f_score": int(row['f_score']),
            "m_score": int(row['m_score']),
            "p_alive_pct": round(float(row['p_alive']) * 100, 1),
            "pred_purchases_30d": round(float(row['pred_purchases_30d']), 2),
            "predicted_clv_12m": round(float(row['predicted_clv_12m']), 1),
            "primary_platform": row['primary_platform'],
            "segment": row['segment'],
            "segment_badge": row['segment_badge'],
            "segment_icon": row['segment_icon'],
            "segment_action": row['segment_action'],
            "segment_color": row['segment_color']
        })

    # Aggregated Summary by Segment
    seg_summary = {}
    for c in customers_list:
        s_name = c["segment"]
        if s_name not in seg_summary:
            seg_summary[s_name] = {
                "name": s_name,
                "icon": c["segment_icon"],
                "color": c["segment_color"],
                "badge": c["segment_badge"],
                "action": c["segment_action"],
                "count": 0,
                "total_spend": 0.0,
                "total_clv_12m": 0.0,
                "avg_p_alive": 0.0,
                "p_alive_sum": 0.0
            }
        seg_summary[s_name]["count"] += 1
        seg_summary[s_name]["total_spend"] += c["total_spend"]
        seg_summary[s_name]["total_clv_12m"] += c["predicted_clv_12m"]
        seg_summary[s_name]["p_alive_sum"] += c["p_alive_pct"]

    for s_name, data in seg_summary.items():
        data["avg_spend"] = round(data["total_spend"] / data["count"], 1) if data["count"] > 0 else 0
        data["avg_clv"] = round(data["total_clv_12m"] / data["count"], 1) if data["count"] > 0 else 0
        data["avg_p_alive"] = round(data["p_alive_sum"] / data["count"], 1) if data["count"] > 0 else 0
        data["pct_of_customers"] = round((data["count"] / len(customers_list)) * 100, 1)

    total_customers = len(customers_list)
    total_orders = int(df['order_id'].nunique())
    total_revenue = round(float(df['order_value'].sum()), 1)
    avg_clv = round(sum(c['predicted_clv_12m'] for c in customers_list) / total_customers, 1) if total_customers > 0 else 0.0
    pred_30d_revenue = round(sum(c['pred_purchases_30d'] * c['avg_order_value'] for c in customers_list), 1)

    # Segment labels & counts for Chart.js
    chart_labels = list(seg_summary.keys())
    chart_counts = [seg_summary[k]["count"] for k in chart_labels]
    chart_clv = [round(seg_summary[k]["total_clv_12m"], 1) for k in chart_labels]
    chart_colors = [seg_summary[k]["color"] for k in chart_labels]

    return {
        "total_customers": total_customers,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "avg_clv": avg_clv,
        "pred_30d_revenue": pred_30d_revenue,
        "customers": customers_list,
        "segments_summary": seg_summary,
        "chart_data": {
            "labels": chart_labels,
            "counts": chart_counts,
            "clv": chart_clv,
            "colors": chart_colors
        },
        "monthly_platforms": get_month_wise_platform_analytics(db_path),
        "model_status": " | ".join(model_notes) if model_notes else "Analytical Baseline Model Active"
    }
