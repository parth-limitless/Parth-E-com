# 🌶️ Spice Nest Hub

**Multi-Platform E-commerce Price Monitoring & Competitor Intelligence Engine**

Spice Nest Hub is an automated price tracking, stock monitoring, and competitor intelligence platform designed for e-commerce brands selling across **Flipkart, Amazon, Meesho, Blinkit, and JioMart**.

---

## 🚀 Key Features

1. **Multi-Platform Price & Stock Tracking:**
   - Real-time price tracking across Flipkart, Amazon, Meesho, Blinkit, and JioMart.
   - Price per 100g normalization for fair comparison across different pack sizes.
   - Live / Out of Stock status detection.
   - Multi-platform price mismatch alerts (>20% gap).

2. **🔍 Competitor Live Spy & Action Advice:**
   - Paste any competitor link to instantly extract:
     - Product title, brand name, and pack weight (grams).
     - Live price and normalized price per 100g.
     - Rating (★) and review count.
     - Estimated monthly orders (Amazon "500+ bought in past month" or review velocity calculation).
     - Real-time stock status (In Stock / Low Inventory / Out of Stock).
   - **4 Strategic AI Action Cards:**
     - 🎯 **Pricing Strategy:** Price matching, coupon tactics (₹15-₹20 off), or margin preservation.
     - 🚨 **Stock Window Alert:** Golden opportunity alerts when a competitor runs out of stock.
     - ⭐ **Review & Trust Strategy:** Exploiting competitor complaints to defend listing USP.
     - 📦 **Pack Size & Combo Opportunity:** Multi-pack or family combo suggestions.

3. **🎭 Resilient Playwright Automation Engine (`meesho_tracker/playwright_engine/`):**
   - **Accessibility & Role Locators:** Uses stable semantic locators (`get_by_role`, `get_by_placeholder`, aria-labels, and semantic anchors) to withstand CSS obfuscation and DOM shifts.
   - **Dynamic Synchronization:** Eliminates arbitrary `sleep` timeouts; replaces them with explicit DOM hydration waits, spinner detachment polling, and navigation stabilization.
   - **Humanized Task Pacing (`TaskPacer`):** Realistic keystroke typing variations (40-90ms), smooth stepped scrolling, and sliding-window rate limiting to prevent server throttling.
   - **Persistent Contexts (`PlaywrightSession`):** Reuses authenticated cookies and storage states (`storage_state.json`) with automated session expiration detection.
   - **Idempotency & State Invariants (`IdempotencyGuard`, `PageStateValidator`):** Debounces rapid click triggers, prevents duplicate form and order executions, and inspects error banners before action commitments.
   - **Strict Policy Compliance & Zero Spoofing:** Standard Chromium with zero webdriver overrides, zero bot bypass scripts, and zero fake human signal falsification.
   - **Manual Intervention Flow (`ChallengeDetector`, `ManualInterventionHandler`):** When CAPTCHAs, MFA, or anti-bot challenge screens appear, execution gracefully pauses and prompts human resolution rather than attempting illegal evasion.

4. **📦 Meesho Public Catalog Synchronizer (ScrapingBee Integration):**
   - **Sitemap Shard Extraction:** Discovers Meesho root sitemaps and PDP shards (`https://www.meesho.com/sitemap/pdp/`).
   - **ScrapingBee HTTP API:** Fetches public pages with exponential backoff retries and geolocation routing (`country_code="in"`).
   - **Next.js Structured Data Extraction:** Parses `<script id="__NEXT_DATA__">` and Schema.org JSON-LD for prices, stock status, and supplier names.
   - **Dual Storage:** Automatically exports to CSV and synchronizes with SQLite `meesho_public_catalog` table.
   - **Standalone Script:** Accessible via [`meesho_catalog_sync.py`](file:///d:/code/spice-nest-hub/meesho_catalog_sync.py) with `--mock` testing mode.

5. **🛡️ Production Meesho Store Tracker (Crawlee + Power BI Multi-Sheet Excel):**
   - **Track Own Store Daily:** Tracks the Spice Nest public store (`https://www.meesho.com/SpiceNestImpexPrivateLimited?ms=2`) without login or private API keys.
   - **Multi-Sheet Power BI Deliverable:** `./output/meesho_store_tracker.xlsx`
     - `Dashboard`: KPI summary cards (Tracked Products, Avg Rating, Total Reviews, Price Changes Today) + native Excel charts (Review Count Top 5, Price History).
     - `Latest`: Real numeric/datetime types, frozen headers, autofilter, snake_case headers.
     - `History`: Append-only historical snapshots for longitudinal trend analysis.
     - `Changes`: Granular audit log of price changes, discount shifts, rating drops, review deltas, and stock status.
     - `Run_Log`: Timestamped log of execution duration, status, and records count.
     - `Rejected`: Schema-drifted rows isolated by Pydantic v2 validation without crashing the run.
   - **Circuit Breaker:** Automatic cooldown escalation (24h &rarr; 48h &rarr; 72h) on Akamai edge challenge detection (`sec-if-cpt-container` or `Access Denied`).
   - **24-Hour Rule Guard:** Prevents scheduled runs if <24h since last success; `--force` allowed only once per 24 hours and never overrides block cooldowns.
   - **Single-Instance Lock:** Process-level filelock (`meesho_tracker.lock`) prevents duplicate executions.
   - **Atomic Write & Backups:** Writes via `.tmp.xlsx` &rarr; atomic rename; maintains rolling 7-day backups in `./output/backups/`; writes timestamped fallback if file is open in Excel (`PermissionError`).

---

## 📊 Connecting Power BI to Meesho Store Tracker

1. Open **Power BI Desktop**.
2. Click **Get Data** &rarr; **Excel Workbook**.
3. Select file path:
   ```text
   D:\code\spice-nest-hub\spice-nest-hub\output\meesho_store_tracker.xlsx
   ```
4. In the Navigator pane, select:
   - `Latest` (for current product catalog and active prices)
   - `History` (for price and rating trend visuals over time)
   - `Changes` (for tracking daily price drops/spikes)
5. Click **Load**. Real currency, percentage, decimal, and datetime columns are pre-formatted for instant DAX calculations.

---

## 🛠️ Meesho Tracker & Automation CLI Commands

```powershell
cd spice-nest-hub
# Activate venv
.\venv\Scripts\activate

# 1. Check Tracker Health & Cooldown status
python -m meesho_tracker.cli --mode health

# 2. Run Scheduled Daily Scan (Guarded by 24h rule)
python -m meesho_tracker.cli --mode scheduled

# 3. Force Scheduled Scan (Allowed once per 24h, never overrides block cooldown)
python -m meesho_tracker.cli --mode scheduled --force

# 4. Live Refresh (Lightweight catalog check only, no product detail page visits)
python -m meesho_tracker.cli --mode live

# 5. Full Store Discovery + Product Page Enrichment Scan
python -m meesho_tracker.cli --mode full

# 6. Dry Run (Validates discovery and DOM selectors without database write)
python -m meesho_tracker.cli --mode dry-run

# 7. Export Only (Re-generates meesho_store_tracker.xlsx from SQLite)
python -m meesho_tracker.cli --mode export-only

# 8. Start Background APScheduler Daemon (Runs daily at 02:00 AM with 0-30 min jitter)
python -m meesho_tracker.cli --mode daemon

# 9. Run Automated Test Suite (21/21 Unit & Integration Tests)
python -m pytest tests/ -v
```

### Windows Task Scheduler Setup (Alternative to Daemon Mode)
1. Open **Windows Task Scheduler** (`taskschd.msc`).
2. Click **Create Basic Task** &rarr; Name: `SpiceNest_Meesho_Tracker`.
3. Trigger: **Daily** at `02:00 AM`.
4. Action: **Start a program**:
   - Program/script: `D:\code\spice-nest-hub\spice-nest-hub\venv\Scripts\python.exe`
   - Add arguments: `-m meesho_tracker.cli --mode scheduled`
   - Start in: `D:\code\spice-nest-hub\spice-nest-hub`
5. Finish. The built-in 24-hour guard and single-instance lock guarantee safe execution even if triggered multiple times.

---

## 💻 Windows Setup & Local Execution

### Prerequisites
- Windows 10/11 64-bit
- Python 3.11+ (or Python 3.14)

### Setup Steps
```powershell
# 1. Navigate to workspace
cd D:\code\spice-nest-hub\spice-nest-hub

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
.\venv\Scripts\activate

# 4. Install pinned requirements
pip install -r requirements.txt

# 5. Install Playwright browser binaries
playwright install chromium

# 6. Run test suite to verify installation
python -m pytest tests/ -v

# 7. Start web application
python app.py
```
Open **http://127.0.0.1:5000** in your browser.

