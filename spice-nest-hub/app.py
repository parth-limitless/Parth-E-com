"""Spice Nest Hub - Multi-Platform Price Monitor & Competitor Spy Engine
Run run.bat, then open http://localhost:5000
"""
import csv, io, json, os, random, re, sqlite3, threading, time
import datetime as dt
import urllib.request
from flask import Flask, Response, jsonify, redirect, render_template_string, request

DB = "spicenest.db"
PLATFORMS = ["Flipkart", "Amazon", "Meesho", "Blinkit", "JioMart"]
MISMATCH_PCT = 20

# Anti-Bot Genuine User-Agents Pool
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

NOT_LIVE = [
    "currently unavailable", "out of stock", "sold out",
    "item is out of stock", "temporarily unavailable", "page not found"
]

app = Flask(__name__)
state = {
    "running": False,
    "last": "-",
    "next": "Scheduling...",
    "msg": "Randomized 24h Scheduler Active 🛡️"
}


def get_ua():
    return random.choice(UA_POOL)


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def num(x):
    m = re.search(r"[\d.]+", str(x or ""))
    try:
        return float(m.group()) if m else 0.0
    except ValueError:
        return 0.0


def detect_platform(url):
    u = (url or "").lower()
    if "flipkart" in u:
        return "Flipkart"
    if "amazon" in u:
        return "Amazon"
    if "meesho" in u:
        return "Meesho"
    if "blinkit" in u:
        return "Blinkit"
    if "jiomart" in u:
        return "JioMart"
    return "Unknown"


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS sku(id INTEGER PRIMARY KEY, name TEXT, grams REAL);
        CREATE TABLE IF NOT EXISTS links(sku_id INT, platform TEXT, url TEXT, PRIMARY KEY(sku_id, platform));
        CREATE TABLE IF NOT EXISTS prices(id INTEGER PRIMARY KEY, ts TEXT, sku_id INT,
            platform TEXT, price REAL, live INT, note TEXT);
        CREATE TABLE IF NOT EXISTS competitors (
            id INTEGER PRIMARY KEY,
            sku_id INT,
            name TEXT,
            brand TEXT,
            platform TEXT,
            url TEXT,
            price REAL,
            grams REAL,
            rating REAL,
            reviews INT,
            est_orders TEXT,
            live INT,
            note TEXT,
            ts TEXT
        );
        """)


# ---------- Extraction Helpers ----------
def jsonld_extract(html):
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        stack = [data] if not isinstance(data, list) else list(data)
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                o = d.get("offers")
                if o or d.get("@type") in ["Product", "IndividualProduct"]:
                    offers = o if isinstance(o, list) else [o] if o else []
                    price = None
                    avail = ""
                    for off in offers:
                        if isinstance(off, dict):
                            p = off.get("price") or off.get("lowPrice")
                            if p:
                                try:
                                    price = float(str(p).replace(",", ""))
                                except ValueError:
                                    pass
                            avail = str(off.get("availability") or "").lower()
                    
                    agg = d.get("aggregateRating") or {}
                    rating = agg.get("ratingValue") if isinstance(agg, dict) else None
                    reviews = (agg.get("ratingCount") or agg.get("reviewCount")) if isinstance(agg, dict) else None
                    
                    brand = d.get("brand")
                    brand_name = brand.get("name") if isinstance(brand, dict) else str(brand) if brand else ""

                    return {
                        "price": price,
                        "name": d.get("name"),
                        "brand": brand_name,
                        "instock": "instock" in avail if avail else None,
                        "rating": float(rating) if rating else None,
                        "reviews": int(str(reviews).replace(",", "")) if reviews else None
                    }
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
    return None


def text_price(text):
    m = re.search(r'(?:₹|Rs\.?)\s?([\d,]+(?:\.\d+)?)', text or "")
    return float(m.group(1).replace(",", "")) if m else None


def extract_grams(text, html=None):
    """Robust weight / quantity extraction (grams, gm, gms, kg, ml, ltr, l).
    Supports titles, Flipkart swatches, Selected Quantity pills, and specification tables.
    """
    def parse_unit(val_str, unit_str):
        try:
            val = float(val_str)
            u = unit_str.strip().lower()
            if u in ["kg", "ltr", "l", "litre", "liter"]:
                val *= 1000
            return val
        except (ValueError, TypeError):
            return 0.0

    # 1. Check title/text first
    if text:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(kg|ltr|litre|liter|ml|gms|gm|grams|g|l)\b', text, re.I)
        if m:
            return parse_unit(m.group(1), m.group(2))

    # 2. Check HTML if available
    if html:
        # Pattern A: Explicit Flipkart / E-com "Selected Quantity: 120 g"
        m_sel = re.search(r'Selected\s*Quantity\s*:\s*(\d+(?:\.\d+)?)\s*(kg|ltr|litre|liter|ml|gms|gm|grams|g|l)\b', html, re.I)
        if m_sel:
            return parse_unit(m_sel.group(1), m_sel.group(2))

        # Pattern B: Swatch JSON / Attribute, e.g. "text":"120 g" or ATLAS_SWATCH_QUANTITY_ATTRIBUTE
        m_swatch = re.search(r'["\'](?:text|value|title|displayValue|selected)["\']\s*:\s*["\'](\d+(?:\.\d+)?)\s*(kg|ltr|litre|liter|ml|gms|gm|grams|g|l)["\']', html, re.I)
        if m_swatch:
            return parse_unit(m_swatch.group(1), m_swatch.group(2))

        # Pattern C: Net Quantity / Weight in specifications or attributes table
        m_net = re.search(r'(?:Net\s*(?:Quantity|Weight)|Item\s*Weight|Size\s*Name|Package\s*Quantity)\b[^<>{}\n]{0,80}?(\d+(?:\.\d+)?)\s*(kg|ltr|litre|liter|ml|gms|gm|grams|g|l)\b', html, re.I)
        if m_net:
            return parse_unit(m_net.group(1), m_net.group(2))

        # Pattern D: Quoted string with weight e.g. "120 g" or '120g'
        m_quote = re.search(r'["\'](\d+(?:\.\d+)?)\s*(kg|ltr|litre|liter|ml|gms|gm|grams|g|l)["\']', html, re.I)
        if m_quote:
            return parse_unit(m_quote.group(1), m_quote.group(2))

        # Pattern E: Clean text search (strip script/style so CSS classes like .v1zwn2g don't match)
        clean = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
        m_clean = re.search(r'\b(\d+(?:\.\d+)?)\s*(kg|ltr|litre|liter|ml|gms|gm|grams|g|l)\b', clean, re.I)
        if m_clean:
            return parse_unit(m_clean.group(1), m_clean.group(2))

    return 0.0



def fast_http_scrape(platform, url):
    """Fast extraction using lightweight HTTP request without launching heavy browser."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": get_ua(),
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        low = html.lower()
        if "enter the characters you see below" in low or "robot check" in low or "please complete the security check" in low:
            return None

        # Strip script and style tags so hidden JavaScript analytics don't cause false positives
        clean_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
        clean_text = clean_html.lower()

        jld = jsonld_extract(html)
        gone = False
        if jld and jld.get("instock") is not None:
            gone = not jld.get("instock")
        else:
            gone = any(k in clean_text for k in [
                "out of stock", "sold out", "currently unavailable",
                "item is out of stock", "temporarily unavailable"
            ])

        # If visible 'Add to cart' exists and not explicitly out of stock, it's Live
        if ("add to cart" in clean_text or "buy now" in clean_text) and not ("out of stock" in clean_text):
            gone = False

        price = None
        name = None
        if jld:
            price = jld.get("price")
            name = jld.get("name")

        if price is None and platform == "Flipkart":
            m = re.search(r'class="[^"]*(?:Nx9bqj|_30jeq3)[^"]*">₹?([\d,]+)', html)
            if m:
                price = float(m.group(1).replace(",", ""))

        if price is not None:
            live = 0 if gone else 1
            note = "Out of stock" if gone else "In Stock"
            grams = extract_grams(name, html)
            return price, live, note, name, grams
    except Exception:
        pass
    return None


def create_stealth_context(browser):
    return browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        user_agent=get_ua(),
        extra_http_headers={
            "Accept-Language": "en-IN,en;q=0.9",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
            "sec-ch-ua-platform": '"Windows"'
        }
    )


def read_page(page, platform, url):
    """Robust playwright extraction with dynamic selector waiting & multi-selector fallbacks."""
    resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    
    # Wait for price elements to render dynamically
    if platform == "Amazon":
        try:
            page.wait_for_selector(".a-price, #corePriceDisplay_desktopFeature_div, .a-price-whole", timeout=8000)
        except Exception:
            pass
    elif platform == "Flipkart":
        try:
            page.wait_for_selector("div.Nx9bqj, div._30jeq3, div.hl05eU", timeout=8000)
        except Exception:
            pass

    page.wait_for_timeout(random.randint(1500, 2500))
    if resp and resp.status >= 400:
        return None, 0, f"HTTP {resp.status}"

    html = page.content()
    text = page.inner_text("body").lower()
    if "enter the characters you see below" in text or "robot check" in text:
        return None, -1, "blocked/captcha"

    jld = jsonld_extract(html)
    gone = False
    if jld and jld.get("instock") is not None:
        gone = not jld.get("instock")
    else:
        gone = any(k in text for k in [
            "out of stock", "sold out", "currently unavailable",
            "item is out of stock", "temporarily unavailable"
        ])

    if ("add to cart" in text or "buy now" in text) and not ("out of stock" in text):
        gone = False
    price, note = None, ""

    if platform == "Amazon":
        amazon_selectors = [
            "span.a-price span.a-offscreen",
            "#corePriceDisplay_desktopFeature_div .a-price .a-offscreen",
            "#corePrice_desktop .a-price .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            ".a-price-whole",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#price",
            ".priceToPay span.a-offscreen",
            "span[data-a-color='price']"
        ]
        for sel in amazon_selectors:
            el = page.query_selector(sel)
            if el:
                p = text_price(el.text_content())
                if p:
                    price = p
                    break

    elif platform == "Flipkart":
        fk_selectors = [
            "div.Nx9bqj",
            "div._30jeq3",
            "div.hl05eU div._30jeq3",
            "div._16FRp0"
        ]
        for sel in fk_selectors:
            el = page.query_selector(sel)
            if el:
                p = text_price(el.text_content())
                if p:
                    price = p
                    break

    if price is None:
        jld = jsonld_extract(html)
        if jld:
            price = jld.get("price")
            if jld.get("instock") is False:
                gone = True

    if price is None:
        price = text_price(text)
        note = "approx" if price else ""

    if price is None:
        # Retry once after short delay
        page.wait_for_timeout(2000)
        text = page.inner_text("body")
        price = text_price(text)

    if price is None:
        return None, (0 if gone else -1), "price nahi mila"

    return price, (0 if gone else 1), ("Out of stock" if gone else note)


# ---------- Competitor Deep Scrape & Advice Engine ----------
def scrape_competitor(url):
    """Extract competitor product title, brand, price, grams, rating, reviews, stock & estimated orders."""
    pf = detect_platform(url)
    data = {
        "platform": pf,
        "url": url,
        "name": "",
        "brand": "",
        "price": None,
        "grams": 0.0,
        "p100": None,
        "rating": None,
        "reviews": None,
        "stock": "In Stock",
        "live": 1,
        "est_orders": "N/A"
    }

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": get_ua(),
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        html = ""

    # Parse JSON-LD
    jld = jsonld_extract(html) if html else None
    low = html.lower() if html else ""

    if jld:
        data["name"] = jld.get("name") or ""
        data["brand"] = jld.get("brand") or ""
        data["price"] = jld.get("price")
        data["rating"] = jld.get("rating")
        data["reviews"] = jld.get("reviews")
    # Stock check on clean visible text
    clean_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S | re.I) if html else ""
    clean_text = clean_html.lower()

    if jld and jld.get("instock") is not None:
        if not jld.get("instock"):
            data["stock"] = "Out of Stock"
            data["live"] = 0
    elif any(k in clean_text for k in NOT_LIVE):
        data["stock"] = "Out of Stock"
        data["live"] = 0
    else:
        m_stock = re.search(r'only\s+(\d+)\s+left\s+in\s+stock', clean_text)
        if m_stock:
            data["stock"] = f"Only {m_stock.group(1)} left in stock!"

    if ("add to cart" in clean_text or "buy now" in clean_text) and not ("out of stock" in clean_text):
        data["stock"] = "In Stock"
        data["live"] = 1

    # Amazon Social proof ("500+ bought in past month")
    m_bought = re.search(r'([\d,kK\+]+)\s+bought\s+in\s+past\s+month', html or "", re.I)
    if m_bought:
        data["est_orders"] = f"{m_bought.group(1)} bought in past month"
    elif data["reviews"] and data["reviews"] > 0:
        # Review Velocity estimation (average 2-3% leave reviews)
        rev = data["reviews"]
        if rev > 1000:
            data["est_orders"] = f"~1,500 - 3,000+ orders/mo ({rev} total ratings)"
        elif rev > 300:
            data["est_orders"] = f"~500 - 900 orders/mo ({rev} ratings)"
        elif rev > 50:
            data["est_orders"] = f"~150 - 300 orders/mo ({rev} ratings)"
        else:
            data["est_orders"] = f"~30 - 80 orders/mo ({rev} ratings)"

    # Fallback price regex for Flipkart / Amazon
    if data["price"] is None and html:
        if pf == "Flipkart":
            m = re.search(r'class="[^"]*(?:Nx9bqj|_30jeq3)[^"]*">₹?([\d,]+)', html)
            if m:
                data["price"] = float(m.group(1).replace(",", ""))
        elif pf == "Amazon":
            m = re.search(r'class="a-price-whole">([\d,]+)', html)
            if m:
                data["price"] = float(m.group(1).replace(",", ""))

    # Fallback to Playwright if price still None
    if data["price"] is None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                page = b.new_context(locale="en-IN", user_agent=get_ua()).new_page()
                price, live, note = read_page(page, pf, url)
                if price:
                    data["price"] = price
                    data["live"] = live
                    if live == 0:
                        data["stock"] = "Out of Stock"
                if not data["name"]:
                    data["name"] = page.title()[:120]
                b.close()
        except Exception:
            pass

    # Clean name & extract grams
    if data["name"]:
        data["grams"] = extract_grams(data["name"], html)
    if not data["name"]:
        data["name"] = f"{pf} Competitor Listing"

    if data["price"] and data["grams"]:
        data["p100"] = round((data["price"] / data["grams"]) * 100, 1)

    return data


def generate_action_advice(my_sku, comp):
    """Generate 4 Actionable Strategies based on competitor comparison."""
    advice = []
    my_price = my_sku.get("price") or 0.0
    my_grams = my_sku.get("grams") or 0.0
    comp_price = comp.get("price") or 0.0
    comp_grams = comp.get("grams") or 0.0

    my_p100 = round((my_price / my_grams) * 100, 1) if my_price and my_grams else None
    comp_p100 = comp.get("p100") or (round((comp_price / comp_grams) * 100, 1) if comp_price and comp_grams else None)

    # 1. 🎯 Pricing & Coupon Strategy
    if my_p100 and comp_p100:
        gap_pct = round(((my_p100 - comp_p100) / comp_p100) * 100, 1)
        if gap_pct > 8:
            advice.append({
                "type": "pricing",
                "badge": "⚠️ Rate Gap Alert",
                "color": "#f59e0b",
                "title": f"Aapka rate competitor se {gap_pct}% mehanga hai (₹{my_p100} vs ₹{comp_p100} / 100g)",
                "action": "Price seedha girane ke bajay listing par ₹15 ya ₹20 ka Instant Coupon lagayein. Isse CTR aur conversion badhega bina base rate giraye."
            })
        elif gap_pct < -8:
            advice.append({
                "type": "pricing",
                "badge": "🔥 Pricing Advantage",
                "color": "#10b981",
                "title": f"Aapka rate competitor se {abs(gap_pct)}% sasta hai! (₹{my_p100} vs ₹{comp_p100} / 100g)",
                "action": "Rate mat girao! Apni secondary image aur title me 'Best Value Pack / Pocket Friendly' highlight karein taaki budget buyers turant convert hon."
            })
        else:
            advice.append({
                "type": "pricing",
                "badge": "✅ Competitive Price",
                "color": "#3b82f6",
                "title": f"Dono ka per-100g rate lagbhag barabar hai (₹{my_p100} vs ₹{comp_p100})",
                "action": "Price war me mat pado. Sara dhyan product images, Korean recipe use-case videos aur taste authenticity dikhane par lagao."
            })
    else:
        advice.append({
            "type": "pricing",
            "badge": "💰 Price Check",
            "color": "#3b82f6",
            "title": f"Competitor Price: ₹{comp_price or 'N/A'}",
            "action": "Competitor ke discounts aur bank offers ko track karte rahein."
        })

    # 2. 🚨 Stock Window Alert (Golden Opportunity)
    stock_str = str(comp.get("stock") or "").lower()
    if "out of stock" in stock_str or comp.get("live") == 0:
        advice.append({
            "type": "stock",
            "badge": "🚨 GOLDEN OPPORTUNITY",
            "color": "#ef4444",
            "title": f"Competitor ({comp.get('brand') or 'Listing'}) OUT OF STOCK ho chuka hai!",
            "action": "Apne Flipkart / Amazon PPC ads ka budget agle 48 ghante ke liye 25% badha dijiye! Unke search keywords par aapka Spice Nest top par dikhega aur unke saare repeat buyers aapke paas aayenge."
        })
    elif "only" in stock_str and "left" in stock_str:
        advice.append({
            "type": "stock",
            "badge": "⚡ Low Inventory Detected",
            "color": "#f59e0b",
            "title": f"Competitor ki inventory khatam hone wali hai ({comp.get('stock')})",
            "action": "Apna stock FBA / Flipkart Fulfillment me ready rakhein. Jaise hi inka stock zero hoga, BuyBox aur search rank aapko milegi."
        })
    else:
        advice.append({
            "type": "stock",
            "badge": "📦 Stock Live",
            "color": "#10b981",
            "title": "Competitor ke paas healthy inventory live hai",
            "action": "Continuous daily check active rakhein taaki stock drop hote hi alert mil sake."
        })

    # 3. ⭐ Review & Social Proof Strategy
    rev_count = comp.get("reviews") or 0
    rating_val = comp.get("rating") or 0.0
    if rev_count >= 100:
        advice.append({
            "type": "review",
            "badge": "⭐ Social Proof Defense",
            "color": "#8b5cf6",
            "title": f"Competitor ke paas {rev_count}+ reviews ({rating_val}★) ka trust advantage hai",
            "action": "Competitor ke 1-star / 2-star complaints (jaise 'leaking bottle' ya 'too sweet') ke against apne bullet points me likhein: '100% Leak-Proof Seal & Balanced Authentic Flavor'. Saath hi product box me review insert card bhejna shuru karein."
        })
    else:
        advice.append({
            "type": "review",
            "badge": "⭐ Low Review Defense",
            "color": "#8b5cf6",
            "title": f"Competitor ke paas sirf {rev_count} ratings hain ({rating_val or 'New'}★)",
            "action": "Competitor abhi naya ya slow hai! Agar aap 20-30 positive customer ratings jaldi le aate hain, toh search rank me ise asaani se beat kar denge."
        })

    # 4. 📦 Pack Size & Combo Idea
    if comp_grams and my_grams:
        diff_g = abs(comp_grams - my_grams)
        if diff_g >= 25:
            advice.append({
                "type": "packaging",
                "badge": "📦 Pack Size Tactic",
                "color": "#ec4899",
                "title": f"Competitor {int(comp_grams)}g bech raha hai jabki aapka pack {int(my_grams)}g hai",
                "action": f"Agar customer bada size pasand kar raha hai, toh Spice Nest ka 'Pack of 2' (2x{int(my_grams)}g) combo offer nikal kar Average Order Value (AOV) badhayein."
            })
        else:
            advice.append({
                "type": "packaging",
                "badge": "📦 Packaging Match",
                "color": "#ec4899",
                "title": f"Dono ka pack size lagbhag same hai ({int(my_grams)}g vs {int(comp_grams)}g)",
                "action": "Cross-sell bundle banayein (jaise Gochujang Paste + Chilli Flakes / Schezwan Sauce) taaki buyer ek ke sath doosra product bhi add kare."
            })
    else:
        advice.append({
            "type": "packaging",
            "badge": "📦 Combo Idea",
            "color": "#ec4899",
            "title": "Family / Bulk Combo Opportunity",
            "action": "1+1 free ya combo trial pack launch karke customer acquisition cost (CAC) kam karein."
        })

    return advice


# ---------- Check Execution & Randomized Scheduler ----------
def check_sku_links(sku_id):
    """Check links for a single SKU with anti-bot randomized jitter."""
    with db() as c:
        rows = c.execute("SELECT sku_id, platform, url FROM links WHERE sku_id=? AND url<>''", (sku_id,)).fetchall()
    if not rows:
        return 0

    browser = None
    page = None
    count = 0
    try:
        for r in rows:
            fast_res = fast_http_scrape(r["platform"], r["url"])
            if fast_res:
                price, live, note = fast_res[0], fast_res[1], fast_res[2]
            else:
                if browser is None:
                    from playwright.sync_api import sync_playwright
                    p_ctx = sync_playwright().start()
                    browser = p_ctx.chromium.launch(headless=True)
                    page = create_stealth_context(browser).new_page()
                try:
                    price, live, note = read_page(page, r["platform"], r["url"])
                except Exception as e:
                    price, live, note = None, -1, str(e)[:80]
                # Anti-bot delay
                time.sleep(random.uniform(3.5, 7.5))

            with db() as c:
                if fast_res and len(fast_res) > 4 and fast_res[4] and fast_res[4] > 0:
                    c.execute("UPDATE sku SET grams=? WHERE id=? AND (grams IS NULL OR grams<=0)", (fast_res[4], r["sku_id"]))

                if price is not None:
                    c.execute(
                        "INSERT INTO prices(ts,sku_id,platform,price,live,note) VALUES(?,?,?,?,?,?)",
                        (now(), r["sku_id"], r["platform"], price, live, note)
                    )
                else:
                    # Retain last known good price so transient errors don't corrupt the dashboard
                    prev = c.execute(
                        "SELECT price, note FROM prices WHERE sku_id=? AND platform=? AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                        (r["sku_id"], r["platform"])
                    ).fetchone()
                    if prev:
                        c.execute(
                            "INSERT INTO prices(ts,sku_id,platform,price,live,note) VALUES(?,?,?,?,?,?)",
                            (now(), r["sku_id"], r["platform"], prev["price"], 1, prev["note"] or "Last verified")
                        )
                    else:
                        c.execute(
                            "INSERT INTO prices(ts,sku_id,platform,price,live,note) VALUES(?,?,?,?,?,?)",
                            (now(), r["sku_id"], r["platform"], price, live, note)
                        )
            count += 1
    finally:
        if browser:
            browser.close()
    return count


def check_all_headless():
    """Runs a full scan of all SKUs and tracked competitors with anti-bot jitter."""
    if state["running"]:
        return
    state.update(running=True, msg="Checking all SKUs & Competitors (Anti-bot delays active 🛡️)...")
    try:
        # Check SKUs
        with db() as c:
            sku_links = c.execute("SELECT sku_id, platform, url FROM links WHERE url<>''").fetchall()
            comps = c.execute("SELECT * FROM competitors").fetchall()

        browser = None
        page = None

        for r in sku_links:
            fast_res = fast_http_scrape(r["platform"], r["url"])
            if fast_res:
                price, live, note = fast_res[0], fast_res[1], fast_res[2]
            else:
                if browser is None:
                    from playwright.sync_api import sync_playwright
                    p_ctx = sync_playwright().start()
                    browser = p_ctx.chromium.launch(headless=True)
                    page = create_stealth_context(browser).new_page()
                try:
                    price, live, note = read_page(page, r["platform"], r["url"])
                except Exception as e:
                    price, live, note = None, -1, str(e)[:80]
            
            with db() as c:
                if fast_res and len(fast_res) > 4 and fast_res[4] and fast_res[4] > 0:
                    c.execute("UPDATE sku SET grams=? WHERE id=? AND (grams IS NULL OR grams<=0)", (fast_res[4], r["sku_id"]))

                if price is not None:
                    c.execute("INSERT INTO prices(ts,sku_id,platform,price,live,note) VALUES(?,?,?,?,?,?)",
                              (now(), r["sku_id"], r["platform"], price, live, note))
                else:
                    prev = c.execute(
                        "SELECT price, note FROM prices WHERE sku_id=? AND platform=? AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                        (r["sku_id"], r["platform"])
                    ).fetchone()
                    if prev:
                        c.execute("INSERT INTO prices(ts,sku_id,platform,price,live,note) VALUES(?,?,?,?,?,?)",
                                  (now(), r["sku_id"], r["platform"], prev["price"], 1, prev["note"] or "Last verified"))
                    else:
                        c.execute("INSERT INTO prices(ts,sku_id,platform,price,live,note) VALUES(?,?,?,?,?,?)",
                                  (now(), r["sku_id"], r["platform"], price, live, note))
            # Human jitter delay
            time.sleep(random.uniform(3.5, 7.5))

        # Check Tracked Competitors
        for comp in comps:
            try:
                c_data = scrape_competitor(comp["url"])
                with db() as c:
                    c.execute("""
                        UPDATE competitors SET price=?, grams=?, rating=?, reviews=?,
                        est_orders=?, live=?, note=?, ts=? WHERE id=?
                    """, (
                        c_data.get("price"), c_data.get("grams"), c_data.get("rating"),
                        c_data.get("reviews"), c_data.get("est_orders"), c_data.get("live"),
                        c_data.get("stock"), now(), comp["id"]
                    ))
            except Exception:
                pass
            time.sleep(random.uniform(3.5, 7.5))

        if browser:
            browser.close()
        state["msg"] = f"Check complete ({len(sku_links)} SKU links + {len(comps)} Competitors checked)."
    except Exception as e:
        state["msg"] = f"Error: {e}"
    finally:
        state.update(running=False, last=now())


def randomized_24h_loop():
    """Anti-Bot Scheduler: Runs once every 24 hours at a random time window to prevent pattern detection."""
    while True:
        # Random sleep between 21 to 27 hours (averages 24 hours, randomized daily)
        delay_seconds = random.randint(21 * 3600, 27 * 3600)
        next_dt = dt.datetime.now() + dt.timedelta(seconds=delay_seconds)
        state["next"] = next_dt.strftime("%d %b, %I:%M %p (Randomized)")
        
        time.sleep(delay_seconds)
        check_all_headless()


# ---------- Flask Routes ----------
@app.route("/")
def home():
    with db() as c:
        skus = [dict(r) for r in c.execute("SELECT * FROM sku ORDER BY name")]
        for s in skus:
            s["links"] = {
                r["platform"]: r["url"]
                for r in c.execute("SELECT platform,url FROM links WHERE sku_id=?", (s["id"],))
            }
            s["latest"] = {}
            for pf in PLATFORMS:
                r = c.execute(
                    "SELECT * FROM prices WHERE sku_id=? AND platform=? AND price IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (s["id"], pf)
                ).fetchone()
                if not r:
                    r = c.execute(
                        "SELECT * FROM prices WHERE sku_id=? AND platform=? ORDER BY id DESC LIMIT 1",
                        (s["id"], pf)
                    ).fetchone()
                if r:
                    d = dict(r)
                    d["p100"] = round(r["price"] / s["grams"] * 100, 1) if r["price"] and s["grams"] else None
                    d["cmp"] = d["p100"] or r["price"]
                    s["latest"][pf] = d
            vals = [v["cmp"] for v in s["latest"].values() if v.get("cmp") and v.get("live") == 1]
            s["mismatch"] = len(vals) > 1 and max(vals) > min(vals) * (1 + MISMATCH_PCT / 100)

        # Get saved competitors
        competitors = [dict(r) for r in c.execute("""
            SELECT c.*, s.name as sku_name, s.grams as sku_grams
            FROM competitors c
            LEFT JOIN sku s ON c.sku_id = s.id
            ORDER BY c.id DESC
        """)]

    return render_template_string(
        PAGE, skus=skus, platforms=PLATFORMS, competitors=competitors,
        state=state, pct=MISMATCH_PCT
    )


@app.post("/api/competitor/spy")
def api_competitor_spy():
    """Live Spy on competitor link & generate action advice against selected SKU."""
    data = request.get_json(force=True, silent=True) or request.form
    url = (data.get("url") or "").strip()
    sku_id = data.get("sku_id")

    if not url:
        return jsonify({"error": "Competitor link is required"}), 400

    comp = scrape_competitor(url)

    my_sku = {}
    if sku_id:
        with db() as c:
            row = c.execute("SELECT * FROM sku WHERE id=?", (sku_id,)).fetchone()
            if row:
                my_sku = dict(row)
                # fetch latest price
                pr = c.execute("SELECT price, platform FROM prices WHERE sku_id=? AND price IS NOT NULL ORDER BY id DESC LIMIT 1", (sku_id,)).fetchone()
                if pr:
                    my_sku["price"] = pr["price"]
                    my_sku["platform"] = pr["platform"]

    advice = generate_action_advice(my_sku, comp)

    return jsonify({
        "competitor": comp,
        "my_sku": my_sku,
        "advice": advice
    })


@app.post("/api/competitor/save")
def api_competitor_save():
    """Save an analyzed competitor to the permanent watchlist."""
    data = request.get_json(force=True, silent=True) or request.form
    url = (data.get("url") or "").strip()
    sku_id = data.get("sku_id") or None
    name = data.get("name") or "Competitor Product"
    brand = data.get("brand") or ""
    platform = data.get("platform") or detect_platform(url)
    price = num(data.get("price"))
    grams = num(data.get("grams"))
    rating = num(data.get("rating"))
    reviews = int(num(data.get("reviews")))
    est_orders = data.get("est_orders") or "N/A"
    stock = data.get("stock") or "In Stock"
    live = 0 if "out" in stock.lower() else 1

    with db() as c:
        c.execute("""
            INSERT INTO competitors (sku_id, name, brand, platform, url, price, grams, rating, reviews, est_orders, live, note, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sku_id, name, brand, platform, url, price, grams, rating, reviews, est_orders, live, stock, now()))

    return jsonify({"success": True, "msg": "Competitor added to Watchlist!"})


@app.post("/competitor/delete/<int:cid>")
def delete_competitor(cid):
    with db() as c:
        c.execute("DELETE FROM competitors WHERE id=?", (cid,))
    return redirect("/")


@app.post("/competitor/refresh/<int:cid>")
def refresh_competitor(cid):
    with db() as c:
        row = c.execute("SELECT * FROM competitors WHERE id=?", (cid,)).fetchone()
    if row:
        c_data = scrape_competitor(row["url"])
        with db() as c:
            c.execute("""
                UPDATE competitors SET price=?, grams=?, rating=?, reviews=?,
                est_orders=?, live=?, note=?, ts=? WHERE id=?
            """, (
                c_data.get("price"), c_data.get("grams"), c_data.get("rating"),
                c_data.get("reviews"), c_data.get("est_orders"), c_data.get("live"),
                c_data.get("stock"), now(), cid
            ))
    return redirect("/")


@app.get("/api/preview_url")
def preview_url():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No url provided"}), 400
    pf = detect_platform(url)
    res = fast_http_scrape(pf, url)
    if res and (res[0] is not None or res[3] or (len(res) > 4 and res[4] and res[4] > 0)):
        price, live, note, name, grams = res
        return jsonify({
            "platform": pf,
            "name": name,
            "grams": grams,
            "price": price,
            "live": live,
            "note": note
        })
    # Fallback lightweight HTTP extraction for name & grams
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": get_ua(),
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            jld = jsonld_extract(html)
            name = jld.get("name") if jld else None
            if not name:
                m_title = re.search(r'<title[^>]*>(.*?)</title>', html, re.I)
                if m_title:
                    name = m_title.group(1).split('|')[0].split('-')[0].strip()
            grams = extract_grams(name, html)
            price = jld.get("price") if jld else None
            return jsonify({
                "platform": pf,
                "name": name,
                "grams": grams,
                "price": price,
                "live": 1,
                "note": ""
            })
    except Exception:
        pass
    return jsonify({"platform": pf, "name": None, "grams": 0, "price": None})


@app.post("/sku/save")
def save():
    f = request.form
    raw_name = f.get("name", "").strip()
    raw_grams = num(f.get("grams"))
    sid = f.get("id")

    links = {p: f.get(p, "").strip() for p in PLATFORMS}

    # If raw_name is a URL, detect platform and link
    if raw_name.startswith("http://") or raw_name.startswith("https://"):
        pf = detect_platform(raw_name)
        if pf:
            links[pf] = raw_name
            res = fast_http_scrape(pf, raw_name)
            if res and res[3]:
                raw_name = res[3]
                if (not raw_grams or raw_grams <= 0) and res[4]:
                    raw_grams = res[4]
            else:
                raw_name = f"{pf} Product"

    # Auto-extract grams from links if user left grams empty or 0
    if not raw_grams or raw_grams <= 0:
        for pf, u in links.items():
            if u and (u.startswith("http://") or u.startswith("https://")):
                try:
                    res = fast_http_scrape(pf, u)
                    if res and len(res) > 4 and res[4] and res[4] > 0:
                        raw_grams = res[4]
                        if not raw_name or raw_name == f"{pf} Product":
                            raw_name = res[3]
                        break
                    # Direct HTML fallback to extract grams
                    req = urllib.request.Request(
                        u,
                        headers={"User-Agent": get_ua(), "Accept-Language": "en-IN,en;q=0.9"}
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                        g = extract_grams(raw_name, html)
                        if g > 0:
                            raw_grams = g
                            break
                except Exception:
                    continue

    with db() as c:
        if sid:
            c.execute("UPDATE sku SET name=?, grams=? WHERE id=?", (raw_name, raw_grams, sid))
        else:
            sid = c.execute("INSERT INTO sku(name,grams) VALUES(?,?)", (raw_name, raw_grams)).lastrowid

        for pf in PLATFORMS:
            c.execute("INSERT OR REPLACE INTO links VALUES(?,?,?)", (sid, pf, links.get(pf, "")))

    threading.Thread(target=check_sku_links, args=(sid,), daemon=True).start()
    time.sleep(0.3)
    return redirect("/")


@app.post("/sku/check/<int:sid>")
def check_single(sid):
    threading.Thread(target=check_sku_links, args=(sid,), daemon=True).start()
    time.sleep(0.5)
    return redirect("/")


@app.post("/sku/delete/<int:sid>")
def delete(sid):
    with db() as c:
        for t, k in (("sku", "id"), ("links", "sku_id"), ("prices", "sku_id")):
            c.execute(f"DELETE FROM {t} WHERE {k}=?", (sid,))
    return redirect("/")


@app.post("/import")
def imp():
    f = request.files.get("file")
    if f:
        text = f.read().decode("utf-8-sig")
        with db() as c:
            for row in csv.DictReader(io.StringIO(text)):
                name = (row.get("sku") or "").strip()
                if not name:
                    continue
                g = num(row.get("grams"))
                r = c.execute("SELECT id FROM sku WHERE name=?", (name,)).fetchone()
                if r:
                    sid = r["id"]
                    c.execute("UPDATE sku SET grams=? WHERE id=?", (g, sid))
                else:
                    sid = c.execute("INSERT INTO sku(name,grams) VALUES(?,?)", (name, g)).lastrowid
                for pf in PLATFORMS:
                    c.execute("INSERT OR REPLACE INTO links VALUES(?,?,?)", (sid, pf, (row.get(pf) or "").strip()))
    return redirect("/")


@app.get("/export.csv")
def export():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["sku", "grams"] + PLATFORMS)
    with db() as c:
        for s in c.execute("SELECT * FROM sku ORDER BY name").fetchall():
            L = {
                r["platform"]: r["url"]
                for r in c.execute("SELECT platform,url FROM links WHERE sku_id=?", (s["id"],))
            }
            w.writerow([s["name"], s["grams"]] + [L.get(p, "") for p in PLATFORMS])
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sku_links.csv"}
    )


@app.post("/check")
def check():
    threading.Thread(target=check_all_headless, daemon=True).start()
    time.sleep(0.5)
    return redirect("/")


@app.get("/api/history")
def history():
    fmt = "%Y-%m" if request.args.get("g") == "month" else "%Y-%m-%d"
    with db() as c:
        rows = c.execute(
            f"SELECT strftime('{fmt}', ts) d, platform, AVG(price) p FROM prices "
            "WHERE sku_id=? AND price IS NOT NULL GROUP BY d, platform ORDER BY d",
            (request.args.get("sku"),)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


PAGE = """<!doctype html>
<html lang="hi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Spice Nest Hub - Multi-Platform Price Monitor & Competitor Spy Engine</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0a0f1d;
      --card-bg: #111827;
      --card-border: #1f2937;
      --card-hover: #1e293b;
      --border: #24324f;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --primary: #10b981;
      --primary-hover: #059669;
      --accent-blue: #3b82f6;
      --accent-purple: #8b5cf6;
      --accent-pink: #ec4899;
      --flipkart: #2874f0;
      --amazon: #ff9900;
      --danger: #ef4444;
      --danger-bg: #451215;
      --badge-live: #064e3b;
      --badge-live-txt: #34d399;
      --badge-off: #4c1d24;
      --badge-off-txt: #f87171;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 24px;
      max-width: 1400px;
      margin: 0 auto;
    }

    /* Header */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 20px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .brand-icon {
      width: 46px;
      height: 46px;
      border-radius: 12px;
      background: linear-gradient(135deg, #10b981, #06b6d4);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      box-shadow: 0 4px 18px rgba(16, 185, 129, 0.4);
    }
    h1 {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.02em;
    }
    .subtitle {
      font-size: 13px;
      color: var(--text-muted);
    }

    /* Security Status Banner */
    .security-banner {
      background: linear-gradient(90deg, rgba(16, 185, 129, 0.12), rgba(59, 130, 246, 0.1));
      border: 1px solid rgba(16, 185, 129, 0.3);
      border-radius: 10px;
      padding: 12px 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 24px;
      font-size: 13px;
    }
    .sec-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(16, 185, 129, 0.2);
      color: #34d399;
      padding: 4px 10px;
      border-radius: 20px;
      font-weight: 600;
      font-size: 12px;
    }

    /* Cards */
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 22px;
      margin-bottom: 24px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .card-title {
      font-size: 17px;
      font-weight: 700;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    /* Buttons */
    button, .btn {
      font-family: inherit;
      font-size: 13px;
      font-weight: 600;
      padding: 9px 18px;
      border-radius: 8px;
      border: 1px solid transparent;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
      text-decoration: none;
      color: var(--text);
      background: #1f2937;
    }
    button:hover, .btn:hover { background: #374151; }
    button.primary, .btn.primary {
      background: var(--primary);
      color: #042f2e;
    }
    button.primary:hover, .btn.primary:hover {
      background: var(--primary-hover);
      box-shadow: 0 0 16px rgba(16, 185, 129, 0.4);
    }
    button.accent, .btn.accent {
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      color: #fff;
    }
    button.accent:hover, .btn.accent:hover {
      box-shadow: 0 0 18px rgba(99, 102, 241, 0.45);
    }
    button.danger, .btn.danger {
      background: #2c1a1d;
      color: #f87171;
      border-color: #551d24;
    }
    button.danger:hover { background: var(--danger-bg); color: #ff9999; }
    button.sm, .btn.sm { padding: 5px 10px; font-size: 12px; border-radius: 6px; }

    /* Inputs */
    input, select {
      font-family: inherit;
      font-size: 13px;
      padding: 10px 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #0b1324;
      color: var(--text);
      outline: none;
      transition: border-color 0.2s;
    }
    input:focus, select:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
    }

    /* Spy Scanner Grid */
    .spy-grid {
      display: grid;
      grid-template-columns: 2.5fr 1.5fr auto;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
    }
    @media(max-width: 850px) {
      .spy-grid { grid-template-columns: 1fr; }
    }

    /* Battle Card (Competitor vs Spice Nest) */
    .battle-card {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      background: #0c1222;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px;
      margin: 18px 0;
    }
    @media(max-width: 768px) {
      .battle-card { grid-template-columns: 1fr; }
    }
    .battle-side {
      padding: 14px;
      border-radius: 10px;
      background: #111827;
      border: 1px solid #1f2937;
    }
    .side-title {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .side-comp { border-left: 4px solid #ef4444; }
    .side-mine { border-left: 4px solid #10b981; }

    /* Strategy Advice Cards */
    .advice-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
      margin: 18px 0;
    }
    .advice-card {
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 16px;
      position: relative;
    }
    .advice-badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      margin-bottom: 8px;
    }
    .advice-title {
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 6px;
      color: #f3f4f6;
    }
    .advice-action {
      font-size: 13px;
      color: #94a3b8;
      line-height: 1.45;
    }

    /* Tabs */
    .filter-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }
    .tabs {
      display: flex;
      gap: 6px;
      background: #0b1324;
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .tab-btn {
      background: transparent;
      border: none;
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 12px;
      color: var(--text-muted);
    }
    .tab-btn:hover { color: var(--text); background: #19243d; }
    .tab-btn.active { background: var(--accent-blue); color: #fff; }

    /* Tables */
    .table-container {
      overflow-x: auto;
      border-radius: 10px;
      border: 1px solid var(--border);
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th {
      background: #0c1427;
      padding: 12px 14px;
      font-weight: 600;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.04em;
    }
    td {
      padding: 14px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      background: var(--card-bg);
    }
    tr:hover td { background: var(--card-hover); }
    tr.mismatch td:first-child { border-left: 4px solid var(--danger); }

    .sku-title { font-weight: 600; color: #fff; font-size: 14px; margin-bottom: 3px; }
    .sku-grams {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      background: #1e293b;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 600;
    }
    .price-tag { font-size: 15px; font-weight: 700; color: #fff; }
    .unit-price { font-size: 11px; color: var(--text-muted); margin-top: 1px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 7px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 600;
      margin-top: 4px;
    }
    .badge-live { background: var(--badge-live); color: var(--badge-live-txt); }
    .badge-off { background: var(--badge-off); color: var(--badge-off-txt); }
    .badge-none { color: var(--text-muted); font-style: italic; }
    .portal-link {
      color: #60a5fa;
      font-size: 11px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 2px;
      margin-top: 4px;
    }
    .portal-link:hover { text-decoration: underline; }
    .mismatch-badge {
      display: inline-block;
      margin-top: 4px;
      padding: 2px 6px;
      border-radius: 4px;
      background: var(--danger-bg);
      color: var(--danger);
      font-size: 11px;
      font-weight: 600;
    }
    .row-actions { display: flex; gap: 6px; align-items: center; }

    /* Form styling */
    .form-grid {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 12px;
      margin-bottom: 12px;
    }
    .platform-links-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .input-group { display: flex; flex-direction: column; gap: 4px; }
    .input-label {
      font-size: 12px;
      font-weight: 500;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .auto-hint {
      font-size: 12px;
      color: var(--primary);
      background: rgba(16, 185, 129, 0.1);
      padding: 6px 12px;
      border-radius: 6px;
      margin-bottom: 12px;
      display: none;
    }
    .tag-flipkart { color: #5aa1ff; }
    .tag-amazon { color: #fba42b; }
    .tag-meesho { color: #ff68b5; }
    .tag-blinkit { color: #fbd658; }
    .tag-jiomart { color: #32d0ff; }
  </style>
</head>
<body>

  <!-- Header -->
  <header>
    <div class="brand">
      <div class="brand-icon">🌶️</div>
      <div>
        <h1>Spice Nest Hub</h1>
        <div class="subtitle">Multi-Platform Price Monitoring & Competitor Intelligence Engine</div>
      </div>
    </div>
    <div style="display:flex; gap:10px; align-items:center;">
      <form method="post" action="/check" style="display:inline">
        <button class="primary" {% if state.running %}disabled{% endif %}>
          {% if state.running %}⏳ Running Scan...{% else %}🔄 Scan All Now (Manual){% endif %}
        </button>
      </form>
    </div>
  </header>

  <!-- Anti-Bot Security & Random 24h Scheduler Banner -->
  <div class="security-banner">
    <div>
      <span class="sec-badge">🛡️ Stealth Anti-Bot Mode Active</span>
      <span style="margin-left: 10px; color: #e2e8f0;">
        <b>Last Run:</b> {{ state.last }} &nbsp;|&nbsp; 
        <b>Next Randomized Auto-Check:</b> {{ state.next }}
      </span>
      <div style="font-size: 12px; color: var(--text-muted); margin-top: 3px;">
        Fixed time par bot nahi chalta. Har 24h me random time + 3-8s human jitter delay se portals aapko block nahi kar sakte.
      </div>
    </div>
    <div style="font-size: 12px; color: #94a3b8;">
      Price gap alert: <b>&gt; {{ pct }}%</b>
    </div>
  </div>

  <!-- SECTION: 🔍 Competitor Live Spy & Action Advice Card -->
  <div class="card" style="border: 1px solid rgba(139, 92, 246, 0.35); background: linear-gradient(180deg, #131b2e 0%, #111827 100%);">
    <div class="card-title">
      <span style="display:flex; align-items:center; gap:8px;">
        <span style="font-size: 20px;">🔍</span> Competitor Live Spy & Action Advice Engine
      </span>
      <span style="font-size: 12px; font-weight: normal; color: #c4b5fd;">
        Paste any Flipkart / Amazon / Meesho / Blinkit link to spy orders & get strategic advice
      </span>
    </div>

    <div class="spy-grid">
      <div class="input-group">
        <label class="input-label">Competitor Product Link</label>
        <input type="text" id="compUrl" placeholder="https://www.flipkart.com/... ya Amazon / Meesho link paste karein">
      </div>
      <div class="input-group">
        <label class="input-label">Compare With Your Spice Nest SKU</label>
        <select id="compTargetSku">
          {% for s in skus %}
          <option value="{{ s.id }}">{{ s.name }} ({{ '%g'|format(s.grams) }}g)</option>
          {% endfor %}
        </select>
      </div>
      <div style="margin-top: 20px;">
        <button class="accent" type="button" id="spyBtn" onclick="runCompetitorSpy()">
          🚀 Spy & Get Action Plan
        </button>
      </div>
    </div>

    <!-- Spinner / Loading state -->
    <div id="spyLoading" style="display:none; padding: 20px; text-align: center; color: #a78bfa;">
      ⏳ Analyzing Competitor link... Fetching live price, stock, ratings & estimated monthly orders...
    </div>

    <!-- Spy Results Box -->
    <div id="spyResultBox" style="display:none;">
      <div class="battle-card">
        <!-- Competitor Side -->
        <div class="battle-side side-comp">
          <div class="side-title" style="color: #f87171;">🎯 Competitor Listing</div>
          <h3 id="resCompName" style="font-size: 15px; margin-bottom: 6px; color:#fff;">-</h3>
          <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">
            Brand: <b id="resCompBrand" style="color:#e2e8f0;">-</b> | Platform: <b id="resCompPlatform" style="color:#60a5fa;">-</b>
          </div>
          <div style="display:flex; gap: 14px; align-items:baseline; margin-bottom: 8px;">
            <div style="font-size: 20px; font-weight:800; color:#fff;" id="resCompPrice">₹0</div>
            <div style="font-size: 12px; color:#94a3b8;" id="resCompP100">₹0 / 100g</div>
            <div id="resCompStockBadge" class="badge badge-live">In Stock</div>
          </div>
          <div style="font-size: 12px; color: #e2e8f0; background: #1e293b; padding: 8px 12px; border-radius: 6px; margin-top: 8px;">
            ⭐ <b id="resCompRating">-</b> &nbsp;|&nbsp; 
            📊 <b>Est. Orders:</b> <span id="resCompOrders" style="color:#34d399; font-weight:700;">-</span>
          </div>
        </div>

        <!-- Spice Nest Side -->
        <div class="battle-side side-mine">
          <div class="side-title" style="color: #34d399;">🌶️ Your Spice Nest Product</div>
          <h3 id="resMyName" style="font-size: 15px; margin-bottom: 6px; color:#fff;">-</h3>
          <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">
            Pack Weight: <b id="resMyGrams" style="color:#e2e8f0;">-</b>
          </div>
          <div style="display:flex; gap: 14px; align-items:baseline; margin-bottom: 8px;">
            <div style="font-size: 20px; font-weight:800; color:#10b981;" id="resMyPrice">₹0</div>
            <div style="font-size: 12px; color:#94a3b8;" id="resMyP100">₹0 / 100g</div>
            <div class="badge badge-live">Your Product</div>
          </div>
          <div style="font-size: 12px; color: #94a3b8; background: #1e293b; padding: 8px 12px; border-radius: 6px; margin-top: 8px;">
            Rate Gap Status: <b id="resGapStatus" style="color:#38bdf8;">-</b>
          </div>
        </div>
      </div>

      <!-- Actionable AI Recommendations -->
      <div style="margin-top: 14px;">
        <h4 style="font-size: 15px; font-weight:700; color:#c4b5fd; margin-bottom: 10px;">
          💡 Hamein Kya Action Lena Chahiye (Strategic Action Plan):
        </h4>
        <div class="advice-grid" id="adviceContainer"></div>
      </div>

      <div style="margin-top: 16px; display:flex; justify-content: flex-end; gap:10px;">
        <button class="primary" type="button" onclick="saveAnalyzedCompetitor()">
          💾 Save This Competitor to Watchlist
        </button>
      </div>
    </div>
  </div>

  <!-- SECTION: 📋 Competitor Watchlist Table -->
  {% if competitors %}
  <div class="card">
    <div class="card-title">
      <span>📋 Tracked Competitors Watchlist ({{ competitors|length }})</span>
      <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">
        These competitors are tracked automatically in every 24h scan
      </span>
    </div>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Competitor Product</th>
            <th>Brand & Portal</th>
            <th>Price & Rate/100g</th>
            <th>Rating & Est. Orders</th>
            <th>Stock Status</th>
            <th>Compared SKU</th>
            <th style="text-align: right;">Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for c in competitors %}
          <tr>
            <td>
              <div class="sku-title">{{ c.name }}</div>
              <a href="{{ c.url }}" target="_blank" class="portal-link">Open Listing ↗</a>
            </td>
            <td>
              <b>{{ c.brand or 'Unknown' }}</b>
              <br><span style="font-size:12px; color:var(--text-muted);">{{ c.platform }}</span>
            </td>
            <td>
              <div class="price-tag">₹{{ '%g'|format(c.price) if c.price else 'N/A' }}</div>
              {% if c.price and c.grams %}
              <div class="unit-price">₹{{ '%.1f'|format((c.price / c.grams) * 100) }} / 100g</div>
              {% endif %}
            </td>
            <td>
              <div>⭐ {{ c.rating or 'N/A' }} <small class="text-muted">({{ c.reviews or 0 }} rev)</small></div>
              <div style="font-size: 11px; color: #34d399; font-weight: 600; margin-top:2px;">{{ c.est_orders or 'N/A' }}</div>
            </td>
            <td>
              {% if c.live == 1 %}
              <span class="badge badge-live">{{ c.note or 'In Stock' }}</span>
              {% else %}
              <span class="badge badge-off">{{ c.note or 'Out of Stock' }}</span>
              {% endif %}
            </td>
            <td>
              <span style="font-size: 12px; color:#e2e8f0;">{{ c.sku_name or 'All SKUs' }}</span>
            </td>
            <td style="text-align: right;">
              <div class="row-actions" style="justify-content: flex-end;">
                <form method="post" action="/competitor/refresh/{{ c.id }}" style="display:inline" title="Refresh competitor price & stock">
                  <button class="sm">🔄</button>
                </form>
                <form method="post" action="/competitor/delete/{{ c.id }}" style="display:inline" onsubmit="return confirm('Is competitor ko delete karein?')">
                  <button class="danger sm">✕</button>
                </form>
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endif %}

  <!-- SECTION: ➕ SKU Add/Edit Form Card -->
  <div class="card">
    <div class="card-title">
      <span>➕ Naya SKU / Link Add Karo</span>
      <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">
        Tip: Direct link paste karenge toh portal aur product details auto-detect ho jayenge!
      </span>
    </div>

    <div id="autoHint" class="auto-hint"></div>

    <form method="post" action="/sku/save" id="skuForm">
      <input type="hidden" name="id" id="skuId">

      <div class="form-grid">
        <div class="input-group">
          <label class="input-label">Product / SKU Naam</label>
          <input name="name" id="skuName" placeholder="Jaise: Spice Nest Gochujang Korean Chilli Paste" required oninput="handleNameInput(this)">
        </div>
        <div class="input-group">
          <label class="input-label">Pack Weight (Grams)</label>
          <input name="grams" id="skuGrams" placeholder="Jaise: 170" type="number" step="any">
        </div>
      </div>

      <div class="input-label" style="margin-bottom: 6px;">Portal Links (Jo portal ka link ho bas wahi dalein, baaki khali chhod sakte hain):</div>
      <div class="platform-links-grid">
        {% for p in platforms %}
        <div class="input-group">
          <label class="input-label">
            <span class="tag-{{ p|lower }}">●</span> {{ p }} Link
          </label>
          <input name="{{ p }}" id="link_{{ p }}" placeholder="{{ p }} link paste karein" onpaste="handleLinkPaste(event, '{{ p }}')">
        </div>
        {% endfor %}
      </div>

      <div style="display: flex; gap: 8px;">
        <button class="primary" type="submit">💾 Save SKU</button>
        <button type="button" onclick="clearForm()">✕ Clear</button>
      </div>
    </form>

    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:16px; padding-top:14px; border-top:1px solid var(--border); font-size:12px; color:var(--text-muted); flex-wrap:wrap; gap:12px;">
      <form method="post" action="/import" enctype="multipart/form-data" style="display:inline-flex; align-items:center; gap:8px;">
        <span>Bulk CSV Import:</span>
        <input type="file" name="file" accept=".csv" style="padding: 4px;">
        <button class="sm">Upload CSV</button>
      </form>
      <a class="btn sm" href="/export.csv">📥 Download CSV Template</a>
    </div>
  </div>

  <!-- SECTION: 📊 SKU Table Card -->
  <div class="card">
    <div class="filter-bar">
      <div class="tabs">
        <button class="tab-btn active" onclick="setPortalFilter('all', this)">Sabhi Portals</button>
        <button class="tab-btn" onclick="setPortalFilter('Flipkart', this)">⚡ Sirf Flipkart</button>
        <button class="tab-btn" onclick="setPortalFilter('Amazon', this)">Amazon</button>
        <button class="tab-btn" onclick="setPortalFilter('Meesho', this)">Meesho</button>
        <button class="tab-btn" onclick="setPortalFilter('Blinkit', this)">Blinkit</button>
        <button class="tab-btn" onclick="setPortalFilter('JioMart', this)">JioMart</button>
      </div>

      <label style="font-size: 12px; color: var(--text-muted); display:flex; align-items:center; gap:6px; cursor:pointer;">
        <input type="checkbox" id="hideEmpty" onchange="applyPortalFilter()"> Sirf active links dikhao
      </label>
    </div>

    <div class="table-container">
      <table id="skuTable">
        <thead>
          <tr>
            <th style="min-width: 220px;">SKU Product</th>
            {% for p in platforms %}
            <th class="col-{{ p }}">{{ p }}</th>
            {% endfor %}
            <th style="text-align: right; width: 140px;">Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for s in skus %}
          <tr class="{{ 'mismatch' if s.mismatch }}">
            <td>
              <div class="sku-title">{{ s.name }}</div>
              <span class="sku-grams">{{ '%g'|format(s.grams) }} g</span>
              {% if s.mismatch %}
              <br><span class="mismatch-badge">Price mismatch &gt; {{ pct }}%</span>
              {% endif %}
            </td>

            {% for p in platforms %}
            {% set v = s.latest.get(p) %}
            {% set link = s.links.get(p) %}
            <td class="col-{{ p }}" data-has-portal="{{ '1' if link else '0' }}">
              {% if not link %}
                <span class="badge-none">-</span>
              {% elif not v %}
                <span class="badge-none">⏳ check baaki...</span>
                <br><a href="{{ link }}" target="_blank" class="portal-link">Open {{ p }} ↗</a>
              {% else %}
                {% if v.price %}
                  <div class="price-tag">₹{{ '%g'|format(v.price) }}</div>
                  {% if v.p100 %}
                  <div class="unit-price">₹{{ v.p100 }} / 100g</div>
                  {% endif %}
                {% endif %}

                {% if v.live == 1 %}
                  <span class="badge badge-live">● Live</span>
                {% elif v.live == 0 %}
                  <span class="badge badge-off">● Not Live</span>
                {% else %}
                  <span class="badge badge-off">⚠️ Error</span>
                {% endif %}

                {% if v.note %}
                <div style="font-size: 11px; color: var(--text-muted); margin-top:2px;">{{ v.note }}</div>
                {% endif %}

                <br><a href="{{ link }}" target="_blank" class="portal-link">Open {{ p }} ↗</a>
              {% endif %}
            </td>
            {% endfor %}

            <td style="text-align: right;">
              <div class="row-actions" style="justify-content: flex-end;">
                <form method="post" action="/sku/check/{{ s.id }}" style="display:inline" title="Is SKU ka price abhi refresh karo">
                  <button class="sm">🔄</button>
                </form>
                <button type="button" class="sm" onclick='editSku({{ s|tojson }})'>Edit</button>
                <form method="post" action="/sku/delete/{{ s.id }}" style="display:inline" onsubmit="return confirm('Kya aap is SKU ko delete karna chahte hain?')">
                  <button class="danger sm">✕</button>
                </form>
              </div>
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="{{ platforms|length + 2 }}" style="text-align:center; padding: 32px; color: var(--text-muted);">
              Abhi koi SKU nahi hai. Upar wale form me Flipkart/Amazon link paste karein aur Save karein.
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- SECTION: 📈 Price History Trend Card -->
  <div class="card">
    <div class="card-title">📈 Price History Trend</div>
    <div style="display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap;">
      <select id="skuSelect" onchange="loadChart()">
        {% for s in skus %}
        <option value="{{ s.id }}">{{ s.name }}</option>
        {% endfor %}
      </select>
      <select id="granularity" onchange="loadChart()">
        <option value="day">Din-wise (Daily)</option>
        <option value="month">Mahine-wise (Monthly)</option>
      </select>
    </div>
    <div style="position: relative; height: 260px;">
      <canvas id="historyChart"></canvas>
    </div>
  </div>

  {% raw %}
  <script>
    const PLATFORMS = ["Flipkart", "Amazon", "Meesho", "Blinkit", "JioMart"];
    let chartInstance = null;
    let currentFilter = 'all';
    let lastAnalyzedComp = null;

    // --- Competitor Spy Logic ---
    async function runCompetitorSpy() {
      const url = document.getElementById('compUrl').value.trim();
      const skuId = document.getElementById('compTargetSku').value;
      if (!url) {
        alert('Pehle Competitor ka link paste karein!');
        return;
      }

      document.getElementById('spyLoading').style.display = 'block';
      document.getElementById('spyResultBox').style.display = 'none';

      try {
        const resp = await fetch('/api/competitor/spy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url, sku_id: skuId })
        });
        const data = await resp.json();
        document.getElementById('spyLoading').style.display = 'none';

        if (data.error) {
          alert('Error: ' + data.error);
          return;
        }

        lastAnalyzedComp = data.competitor;
        lastAnalyzedComp.sku_id = skuId;

        // Populate Competitor Side
        const comp = data.competitor;
        document.getElementById('resCompName').innerText = comp.name || 'Competitor Product';
        document.getElementById('resCompBrand').innerText = comp.brand || 'Competitor';
        document.getElementById('resCompPlatform').innerText = comp.platform;
        document.getElementById('resCompPrice').innerText = comp.price ? '₹' + comp.price : 'N/A';
        document.getElementById('resCompP100').innerText = comp.p100 ? '₹' + comp.p100 + ' / 100g (' + (comp.grams || '') + 'g)' : (comp.grams ? comp.grams + 'g' : '');
        
        const stockBadge = document.getElementById('resCompStockBadge');
        if (comp.live === 1) {
          stockBadge.className = 'badge badge-live';
          stockBadge.innerText = comp.stock || 'In Stock';
        } else {
          stockBadge.className = 'badge badge-off';
          stockBadge.innerText = comp.stock || 'Out of Stock';
        }

        document.getElementById('resCompRating').innerText = (comp.rating ? comp.rating + '★' : 'Rating N/A') + (comp.reviews ? ' (' + comp.reviews + ' reviews)' : '');
        document.getElementById('resCompOrders').innerText = comp.est_orders || 'N/A';

        // Populate My SKU Side
        const mySku = data.my_sku || {};
        document.getElementById('resMyName').innerText = mySku.name || 'Spice Nest Product';
        document.getElementById('resMyGrams').innerText = (mySku.grams || 0) + ' g';
        document.getElementById('resMyPrice').innerText = mySku.price ? '₹' + mySku.price : 'N/A';
        const myP100 = (mySku.price && mySku.grams) ? Math.round((mySku.price / mySku.grams) * 1000) / 10 : null;
        document.getElementById('resMyP100').innerText = myP100 ? '₹' + myP100 + ' / 100g' : '';

        if (myP100 && comp.p100) {
          const diff = Math.round((myP100 - comp.p100) * 10) / 10;
          if (diff > 0) {
            document.getElementById('resGapStatus').innerHTML = `<span style="color:#f87171;">Competitor is ₹${diff}/100g cheaper</span>`;
          } else if (diff < 0) {
            document.getElementById('resGapStatus').innerHTML = `<span style="color:#34d399;">You are ₹${Math.abs(diff)}/100g cheaper!</span>`;
          } else {
            document.getElementById('resGapStatus').innerText = 'Both rates are identical';
          }
        } else {
          document.getElementById('resGapStatus').innerText = 'Rate compared';
        }

        // Populate Action Advice
        const adviceContainer = document.getElementById('adviceContainer');
        adviceContainer.innerHTML = '';
        (data.advice || []).forEach(adv => {
          const card = document.createElement('div');
          card.className = 'advice-card';
          card.style.borderLeft = `4px solid ${adv.color || '#3b82f6'}`;
          card.innerHTML = `
            <span class="advice-badge" style="background:${adv.color}22; color:${adv.color};">${adv.badge}</span>
            <div class="advice-title">${adv.title}</div>
            <div class="advice-action">${adv.action}</div>
          `;
          adviceContainer.appendChild(card);
        });

        document.getElementById('spyResultBox').style.display = 'block';
      } catch (e) {
        document.getElementById('spyLoading').style.display = 'none';
        alert('Failed to analyze competitor link: ' + e);
      }
    }

    async function saveAnalyzedCompetitor() {
      if (!lastAnalyzedComp) return;
      try {
        const resp = await fetch('/api/competitor/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(lastAnalyzedComp)
        });
        const res = await resp.json();
        if (res.success) {
          alert('✅ ' + res.msg);
          location.reload();
        }
      } catch (e) {
        alert('Save error: ' + e);
      }
    }

    // Filter Logic
    function setPortalFilter(portal, btn) {
      currentFilter = portal;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyPortalFilter();
    }

    function applyPortalFilter() {
      const hideEmpty = document.getElementById('hideEmpty').checked;
      PLATFORMS.forEach(p => {
        const th = document.querySelector('th.col-' + p);
        const tds = document.querySelectorAll('td.col-' + p);
        const show = (currentFilter === 'all' || currentFilter === p);
        if (th) th.style.display = show ? '' : 'none';
        tds.forEach(td => td.style.display = show ? '' : 'none');
      });

      document.querySelectorAll('#skuTable tbody tr').forEach(tr => {
        if (tr.children.length <= 1) return;
        if (hideEmpty && currentFilter !== 'all') {
          const portalTd = tr.querySelector('td.col-' + currentFilter);
          const hasPortal = portalTd && portalTd.getAttribute('data-has-portal') === '1';
          tr.style.display = hasPortal ? '' : 'none';
        } else {
          tr.style.display = '';
        }
      });
    }

    // Auto-detect URL input
    async function handleNameInput(input) {
      const val = input.value.trim();
      const hint = document.getElementById('autoHint');
      const skuGrams = document.getElementById('skuGrams');
      if (val.startsWith('http://') || val.startsWith('https://')) {
        let pf = null;
        if (val.includes('flipkart')) pf = 'Flipkart';
        else if (val.includes('amazon')) pf = 'Amazon';
        else if (val.includes('meesho')) pf = 'Meesho';
        else if (val.includes('blinkit')) pf = 'Blinkit';
        else if (val.includes('jiomart')) pf = 'JioMart';

        if (pf) {
          const target = document.getElementById('link_' + pf);
          if (target && !target.value) target.value = val;
          hint.style.display = 'block';
          hint.innerHTML = `✨ <b>${pf} link detected!</b> Fetching product name and pack weight...`;
          try {
            const res = await (await fetch('/api/preview_url?url=' + encodeURIComponent(val))).json();
            if (res.name) {
              input.value = res.name;
            }
            if (res.grams && (!skuGrams.value || skuGrams.value === '0')) {
              skuGrams.value = res.grams;
            }
            hint.innerHTML = `✅ Auto-filled: <b>${res.name || input.value}</b> (${res.grams || ''}g). Live price: ₹${res.price || 'N/A'}`;
          } catch(e) {
            hint.innerHTML = `✨ <b>${pf} link set!</b>`;
          }
        }
      }
    }

    async function handleLinkPaste(e, platform) {
      setTimeout(async () => {
        const val = document.getElementById('link_' + platform).value.trim();
        if (val.startsWith('http://') || val.startsWith('https://')) {
          const skuName = document.getElementById('skuName');
          const skuGrams = document.getElementById('skuGrams');
          const hint = document.getElementById('autoHint');
          if (!skuName.value || !skuGrams.value || skuGrams.value === '0') {
            try {
              if (hint) {
                hint.style.display = 'block';
                hint.innerHTML = `🔍 <b>${platform} link detected!</b> Fetching pack weight and details...`;
              }
              const res = await (await fetch('/api/preview_url?url=' + encodeURIComponent(val))).json();
              if (res.name && !skuName.value) {
                skuName.value = res.name;
              }
              if (res.grams && (!skuGrams.value || skuGrams.value === '0')) {
                skuGrams.value = res.grams;
              }
              if (hint) {
                hint.style.display = 'block';
                hint.innerHTML = `✅ <b>Auto-detected:</b> ${res.name || skuName.value} ${res.grams ? '— ' + res.grams + 'g' : ''} ${res.price ? '(₹' + res.price + ')' : ''}`;
              }
            } catch(e) {}
          }
        }
      }, 50);
    }

    function editSku(s) {
      document.getElementById('skuId').value = s.id;
      document.getElementById('skuName').value = s.name;
      document.getElementById('skuGrams').value = s.grams || '';
      PLATFORMS.forEach(p => {
        document.getElementById('link_' + p).value = (s.links && s.links[p]) || '';
      });
      window.scrollTo({ top: 300, behavior: 'smooth' });
    }

    function clearForm() {
      document.getElementById('skuForm').reset();
      document.getElementById('skuId').value = '';
      document.getElementById('autoHint').style.display = 'none';
    }

    async function loadChart() {
      const sid = document.getElementById('skuSelect').value;
      if (!sid) return;
      const gr = document.getElementById('granularity').value;
      const rows = await (await fetch('/api/history?sku=' + sid + '&g=' + gr)).json();

      const labels = [...new Set(rows.map(r => r.d))];
      const pfs = [...new Set(rows.map(r => r.platform))];

      const colors = {
        'Flipkart': '#3b82f6',
        'Amazon': '#f59e0b',
        'Meesho': '#ec4899',
        'Blinkit': '#eab308',
        'JioMart': '#06b6d4'
      };

      const datasets = pfs.map(p => ({
        label: p,
        borderColor: colors[p] || '#10b981',
        backgroundColor: colors[p] || '#10b981',
        spanGaps: true,
        tension: 0.3,
        data: labels.map(l => {
          const r = rows.find(x => x.d === l && x.platform === p);
          return r ? Math.round(r.p * 100) / 100 : null;
        })
      }));

      if (chartInstance) chartInstance.destroy();
      const ctx = document.getElementById('historyChart').getContext('2d');
      chartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#94a3b8' } }
          },
          scales: {
            x: { grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } },
            y: {
              grid: { color: '#1e293b' },
              ticks: { color: '#94a3b8' },
              title: { display: true, text: 'Price (₹)', color: '#94a3b8' }
            }
          }
        }
      });
    }

    loadChart();
  </script>
  {% endraw %}
  {% if state.running %}
  <script>setTimeout(() => location.reload(), 4000);</script>
  {% endif %}
</body>
</html>
"""

if __name__ == "__main__":
    init()
    # Start randomized 24-hour scheduler daemon thread
    threading.Thread(target=randomized_24h_loop, daemon=True).start()
    print("Dashboard: http://localhost:5000")
    app.run(port=5000)
