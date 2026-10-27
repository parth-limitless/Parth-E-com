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

3. **🛡️ Stealth Anti-Bot Protection:**
   - Genuine desktop Chrome User-Agent rotation.
   - Randomized 3.5s – 7.5s human-like jitter between requests.
   - **Randomized 24-Hour Scheduler:** Scans occur once every 24 hours at a random time window to prevent bot pattern detection.

4. **☁️ GitHub Actions Cloud Automation:**
   - Fully automated cloud scanning via `.github/workflows/daily_check.yml`.
   - Runs headless daily without needing a local computer turned on.
   - Automatically updates and commits `spicenest.db` back to the repository.

---

## 💻 How to Run Locally

### Option 1: One-Click Run (Windows)
Double-click `run.bat` in the project root. It will:
- Automatically initialize the virtual environment (`venv`).
- Install all dependencies (`Flask`, `Playwright`).
- Download required Chromium browser binaries.
- Launch the server and open `http://localhost:5000` in your browser.

### Option 2: Manual Run
```bash
cd spice-nest-hub
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python app.py
```
Open **http://localhost:5000** in your browser.

---

## ☁️ How to Push to GitHub

1. Create a new repository on [GitHub](https://github.com/new) (e.g. `spice-nest-hub`).
2. Run the following commands in your terminal:
```bash
git add .
git commit -m "Initial commit: Spice Nest Hub with Competitor Intelligence"
git remote add origin https://github.com/<your-username>/spice-nest-hub.git
git push -u origin main
```
3. Once pushed, **GitHub Actions** will automatically manage daily scheduled checks in the cloud!
