"""Spice Nest Hub - Mock Transactions Seeder & CLI Analysis Tool
Run this script to initialize SQLite transactions table and populate realistic
mock customer purchase data.
"""

import sys
import os

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Ensure current dir in path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from clv_analytics import seed_mock_transactions, analyze_customer_clv, DEFAULT_DB_PATH

def main():
    print("=" * 65)
    print("🌶️  Spice Nest Hub - Customer CLV & Segmentation Seeder")
    print("=" * 65)
    print(f"Target Database: {DEFAULT_DB_PATH}")
    
    num_customers = 75
    print(f"Generating mock transaction history for {num_customers} customers...")
    records_count = seed_mock_transactions(db_path=DEFAULT_DB_PATH, num_customers=num_customers, clear_existing=True)
    print(f"✅ Successfully inserted {records_count} transactions across {num_customers} customers!")
    
    print("\nRunning RFM & CLV Analysis Pipeline...")
    results = analyze_customer_clv(db_path=DEFAULT_DB_PATH)
    
    if "error" in results:
        print(f"⚠️ Notice: {results['error']}")
        return

    print("\n📊 --- ANALYSIS SUMMARY ---")
    print(f"Total Unique Customers : {results['total_customers']}")
    print(f"Total Orders Placed    : {results['total_orders']}")
    print(f"Total Historical Spend : ₹{results['total_revenue']:,.2f}")
    print(f"Average 12M CLV        : ₹{results['avg_clv']:,.2f}")
    print(f"Projected 30D Revenue  : ₹{results['pred_30d_revenue']:,.2f}")
    print(f"Model Engine           : {results['model_status']}")

    print("\n👥 --- SEGMENTATION BREAKDOWN ---")
    for name, seg in results['segments_summary'].items():
        print(f"{seg['icon']} {name:20s}: {seg['count']:2d} customers ({seg['pct_of_customers']}%) | Avg CLV: ₹{seg['avg_clv']:,.0f} | Retain: {seg['action'][:45]}...")

    print("\n🏆 --- TOP 5 HIGHEST CLV CUSTOMERS ---")
    for c in results['customers'][:5]:
        print(f"• [{c['customer_id']}] {c['customer_name']:18s} | Orders: {c['total_orders']:2d} | Spend: ₹{c['total_spend']:7.1f} | P(Alive): {c['p_alive_pct']}% | CLV 12M: ₹{c['predicted_clv_12m']:7.1f} | {c['segment']}")

    print("\n✨ Done! You can view this live in the dashboard at: http://localhost:5000/clv")
    print("=" * 65)

if __name__ == "__main__":
    main()
