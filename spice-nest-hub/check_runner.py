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
import csv

def generate_report_csv(filepath):
    """Generates a detailed summary CSV of all SKUs and tracked competitors."""
    with app.db() as c:
        skus = c.execute("SELECT * FROM sku ORDER BY name").fetchall()
        comps = c.execute("SELECT * FROM competitors ORDER BY id DESC").fetchall()

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["=== SPICE NEST HUB - DAILY PRICE & STOCK REPORT ==="])
            w.writerow(["Generated At:", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
            w.writerow([])
            w.writerow(["--- YOUR TRACKED SKUS ---"])
            headers = ["SKU Name", "Pack Weight (g)"]
            for p in app.PLATFORMS:
                headers.extend([f"{p} Price (Rs)", f"{p} Live?", f"{p} Per 100g (Rs)"])
            w.writerow(headers)

            for s in skus:
                row = [s["name"], s["grams"]]
                grams = float(s["grams"] or 0)
                for p in app.PLATFORMS:
                    pr = c.execute(
                        "SELECT price, live, note FROM prices WHERE sku_id=? AND platform=? ORDER BY id DESC LIMIT 1",
                        (s["id"], p)
                    ).fetchone()
                    if pr and pr["price"] is not None:
                        price = pr["price"]
                        live_str = "Live" if pr["live"] == 1 else "Out of Stock"
                        p100 = round((price / (grams / 100)), 1) if grams > 0 else "N/A"
                        row.extend([price, live_str, p100])
                    else:
                        row.extend(["-", "-", "-"])
                w.writerow(row)

            w.writerow([])
            w.writerow(["--- TRACKED COMPETITORS ---"])
            w.writerow(["Competitor Product", "Brand", "Platform", "Price (Rs)", "Weight (g)", "Per 100g (Rs)", "Rating", "Reviews", "Est. Orders", "Stock Status", "URL"])
            for comp in comps:
                c_price = comp["price"] or 0
                c_grams = comp["grams"] or 0
                c_p100 = round((c_price / (c_grams / 100)), 1) if (c_grams > 0 and c_price > 0) else "N/A"
                w.writerow([
                    comp["name"],
                    comp["brand"] or "N/A",
                    comp["platform"],
                    comp["price"] if comp["price"] is not None else "N/A",
                    comp["grams"] if comp["grams"] else "N/A",
                    c_p100,
                    comp["rating"] or "N/A",
                    comp["reviews"] or "N/A",
                    comp["est_orders"] or "N/A",
                    comp["note"] or ("In Stock" if comp["live"] == 1 else "Out of Stock"),
                    comp["url"]
                ])


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
    generate_report_csv(report_file)

    with app.db() as c:
        skus = c.execute("SELECT * FROM sku").fetchall()
        comps = c.execute("SELECT * FROM competitors").fetchall()

    print(f"✅ Scan Complete! Total SKUs: {len(skus)}, Total Competitors: {len(comps)}")
    print(f"📄 Summary Report exported to: {report_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
