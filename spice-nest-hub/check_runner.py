"""Spice Nest Hub - Headless Automation Runner (for GitHub Actions & Scheduled Cron)
Runs without web server, checks all SKUs and Competitors, updates spicenest.db,
and exports an updated summary CSV.
"""
import os, sys, datetime as dt

# Ensure current directory is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app

def main():
    print("=" * 60)
    print(f"[Spice Nest Hub] Daily Scan Started at {dt.datetime.now()}")
    print("[Anti-Bot Protection] Genuine Chrome UA + Random Jitter Active")
    print("=" * 60)

    app.init()
    
    # Run full scan of SKUs & Competitors
    app.check_all_headless()

    # Generate summary CSV
    report_file = os.path.join(current_dir, "spicenest_daily_report.csv")
    with app.db() as c:
        skus = c.execute("SELECT * FROM sku").fetchall()
        comps = c.execute("SELECT * FROM competitors").fetchall()
        
    print(f"✅ Scan Complete! Total SKUs checked: {len(skus)}, Total Competitors checked: {len(comps)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
